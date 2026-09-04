"""Lazy online adapters for Flipper-IRDB and IRDB.

Both projects are public IR catalogues, but they expose different evidence. Flipper-IRDB
stores complete Flipper ``.ir`` remote files, including raw captures. IRDB stores compact
CSV rows in protocol/device/subdevice/function notation. This module indexes their live
branches without cloning them and materializes one selected record into Afterglow's
portable device schema. Unsupported protocols stay explicit in the capability report.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import json
from pathlib import PurePosixPath
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import backends, device_json, ir_signal, remotes
from .corpus_provider import Manufacturer, _hard_key, _inputs, _power
from .flipper import parse_ir_text


FLIPPER_TREE_URL = (
    "https://api.github.com/repos/Lucaslhm/Flipper-IRDB/git/trees/main?recursive=1")
FLIPPER_RAW_URL = "https://raw.githubusercontent.com/Lucaslhm/Flipper-IRDB/main"
IRDB_INDEX_URL = "https://cdn.jsdelivr.net/gh/probonopd/irdb@master/codes/index"
IRDB_RAW_URL = "https://cdn.jsdelivr.net/gh/probonopd/irdb@master/codes"


@dataclass(frozen=True)
class PublicModel:
    manufacturer: str
    name: str
    relative_path: str
    device_type: str
    source_id: str

    @property
    def global_device_id(self) -> str:
        return self.source_id


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Afterglow public IR source/1"})
    try:
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"could not read online IR source: {exc}") from exc


def _pretty(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ")).strip()


def _device_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    types = {
        "tv": "Television",
        "tvs": "Television",
        "television": "Television",
        "audioreceiver": "Receiver",
        "audioreceivers": "Receiver",
        "receiver": "Receiver",
        "receivers": "Receiver",
        "dvd": "DvdCd",
        "dvdplayer": "DvdCd",
        "bluray": "DvdCd",
        "blurayplayer": "DvdCd",
        "projector": "Projector",
        "projectors": "Projector",
        "settopbox": "Pvr",
        "cablebox": "Pvr",
        "satellite": "Pvr",
        "mediaplayer": "MediaCenterPC",
        "gameconsole": "GameConsole",
        "airconditioner": "HomeAppliance",
        "acs": "HomeAppliance",
        "fan": "HomeAppliance",
        "fans": "HomeAppliance",
    }
    return types.get(normalized, "HomeAppliance")


def _byte(text: str, index: int = 0) -> int:
    fields = str(text).split()
    if index >= len(fields):
        return 0
    return int(fields[index], 16)


def _flipper_signal(record: dict) -> tuple[dict | None, str]:
    kind = str(record.get("type", "")).casefold()
    if kind == "raw":
        try:
            frequency = int(record["frequency"])
            durations = [int(value) for value in str(record["data"]).split()]
            pulses = [value if index % 2 == 0 else -value
                      for index, value in enumerate(durations)]
            duty = float(record["duty_cycle"]) if record.get("duty_cycle") else None
            provenance = {"kind": "flipper-irdb"}
            if duty is not None:
                provenance["duty_cycle"] = duty
            return ir_signal.waveform(
                pulses, carrier_hz=frequency,
                provenance=provenance), "raw capture"
        except (KeyError, TypeError, ValueError) as exc:
            return None, f"invalid Flipper raw signal: {exc}"
    if kind != "parsed":
        return None, f"unsupported Flipper signal type {record.get('type')!r}"
    try:
        protocol = re.sub(r"[^a-z0-9]", "", str(record["protocol"]).casefold())
        address_low = _byte(record.get("address", ""), 0)
        address_high = _byte(record.get("address", ""), 1)
        command = _byte(record.get("command_bytes", record.get("command", "")), 0)
        provenance = {"kind": "flipper-irdb", "protocol": record["protocol"]}
        if protocol in {"nec", "nec1"}:
            if address_high:
                parameters = {
                    "address_low": address_low,
                    "address_high": address_high,
                    "command": command,
                }
                return ir_signal.protocol_signal(
                    "nec-ext", parameters, provenance=provenance), "parsed protocol"
            return ir_signal.protocol_signal(
                "nec1", {"address": address_low, "command": command},
                provenance=provenance), "parsed protocol"
        if protocol in {"necext", "necextended"}:
            return ir_signal.protocol_signal(
                "nec-ext", {
                    "address_low": address_low,
                    "address_high": address_high,
                    "command": command,
                }, provenance=provenance), "parsed protocol"
        if protocol == "samsung32":
            return ir_signal.protocol_signal(
                "samsung32", {"address": address_low, "command": command},
                provenance=provenance), "parsed protocol"
        if protocol in {"jvc", "jvc16"}:
            return ir_signal.protocol_signal(
                "jvc16", {"code": (address_low << 8) | command},
                provenance=provenance), "parsed protocol"
        return None, f"Flipper parsed protocol {record['protocol']!r} is not mapped yet"
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"invalid Flipper parsed signal: {exc}"


def _irdb_signal(row: dict) -> tuple[dict | None, str]:
    try:
        protocol = re.sub(r"[^a-z0-9]", "", row["protocol"].casefold())
        device = int(row["device"])
        subdevice = int(row["subdevice"])
        function = int(row["function"])
        provenance = {"kind": "irdb", "protocol": row["protocol"]}
        if not 0 <= function <= 0xFF:
            return None, "IRDB function does not fit the supported command byte"
        if protocol == "nec1":
            if subdevice < 0:
                return ir_signal.protocol_signal(
                    "nec1", {"address": device, "command": function},
                    provenance=provenance), "protocol tuple"
            return ir_signal.protocol_signal(
                "nec-ext", {
                    "address_low": device,
                    "address_high": subdevice,
                    "command": function,
                }, provenance=provenance), "protocol tuple"
        if protocol == "nec2":
            name = "nec2" if subdevice < 0 else "nec2-ext"
            parameters = ({"address": device, "command": function}
                          if subdevice < 0 else {
                              "address_low": device,
                              "address_high": subdevice,
                              "command": function,
                          })
            return ir_signal.protocol_signal(
                name, parameters, provenance=provenance), "protocol tuple"
        if protocol == "necx2" and device == subdevice:
            return ir_signal.protocol_signal(
                "samsung32", {"address": device, "command": function},
                provenance=provenance), "Samsung-style NECx2 tuple"
        if protocol == "samsung32":
            return ir_signal.protocol_signal(
                "samsung32", {"address": device, "command": function},
                provenance=provenance), "protocol tuple"
        if protocol in {"jvc", "jvc16"} and subdevice < 0:
            return ir_signal.protocol_signal(
                "jvc16", {"code": (device << 8) | function},
                provenance=provenance), "protocol tuple"
        return None, f"IRDB protocol {row['protocol']!r} is not mapped yet"
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"invalid IRDB row: {exc}"


class _PublicCatalog:
    source_kind = "public-ir"

    def __init__(self, *, fetch=None, remote_id: str = "harmony-900"):
        self.fetch = fetch or _fetch_text
        self.profile = remotes.get(remote_id)
        self._models: list[PublicModel] | None = None

    def _load_models(self) -> list[PublicModel]:
        raise NotImplementedError

    def _commands(self, model: PublicModel) -> list[dict]:
        raise NotImplementedError

    def _all_models(self) -> list[PublicModel]:
        if self._models is None:
            self._models = self._load_models()
        return self._models

    def manufacturers(self, query: str = "", *, limit: int = 200) -> list[Manufacturer]:
        counts = {}
        for model in self._all_models():
            counts[model.manufacturer] = counts.get(model.manufacturer, 0) + 1
        needle = query.strip().casefold()
        entries = [Manufacturer(name, name, count) for name, count in sorted(counts.items())
                   if not needle or needle in name.casefold()]
        return entries[:limit]

    def manufacturer(self, name: str) -> Manufacturer:
        wanted = name.strip().casefold()
        try:
            return next(entry for entry in self.manufacturers(limit=100_000)
                        if entry.name.casefold() == wanted)
        except StopIteration:
            raise LookupError(f"manufacturer {name!r} is not in the source") from None

    def models(self, manufacturer: str, query: str = "", *, limit: int = 300):
        maker = self.manufacturer(manufacturer)
        needle = query.strip().casefold()
        matches = [model for model in self._all_models()
                   if model.manufacturer == maker.name
                   and (not needle or needle in model.name.casefold())]
        return matches[:limit]

    def materialize(self, model: PublicModel) -> dict:
        report = []
        commands = []
        used = set()
        for source_command in self._commands(model):
            label = source_command["name"].strip() or "Unnamed"
            name = label
            suffix = 2
            while name in used:
                name = f"{label} {suffix}"
                suffix += 1
            used.add(name)
            signal = source_command.get("signal")
            verdict = self._capability(
                name, signal, source_command.get("classification", "source"),
                source_command.get("reason", "no portable signal"))
            report.append(verdict)
            if not verdict["supported"]:
                continue
            entry = {"name": name, "label": label, "signal": signal}
            hard_key = _hard_key(name, self.profile.hard_keys)
            if hard_key:
                entry["hard_key"] = hard_key
            commands.append(entry)
        if not commands:
            reasons = sorted({entry["reason"] for entry in report})
            raise ValueError(
                f"{model.manufacturer} {model.name} has no faithfully reproducible "
                f"commands: {'; '.join(reasons)}")
        names = {entry["name"] for entry in commands}
        template = {
            "schema": device_json.PORTABLE_SCHEMA,
            "manufacturer": model.manufacturer,
            "model": model.name,
            "names": [model.name],
            "type": model.device_type,
            "source": {
                "kind": self.source_kind,
                "path": model.relative_path,
                "id": model.source_id,
            },
            "commands": commands,
        }
        power = _power(names)
        if power:
            template["power"] = power
        inputs = _inputs(names)
        if inputs:
            template["inputs"] = inputs
        if all(str(number) in names for number in range(10)):
            template["numeric"] = True
        supported = sum(entry["supported"] for entry in report)
        return {
            "template": template,
            "commands": report,
            "counts": {
                "source": len(report),
                "supported": supported,
                "excluded": len(report) - supported,
            },
            "catalogue_id": model.source_id,
        }

    def _capability(self, name: str, signal: dict | None,
                    classification: str, reason: str) -> dict:
        base = {
            "name": name,
            "classification": classification,
            "supported": False,
            "strategy": "unavailable",
            "reason": reason,
        }
        if not isinstance(signal, dict):
            return base
        base.update(backends.for_profile(self.profile).capability(signal, self.profile))
        return base


class FlipperIrdbCatalog(_PublicCatalog):
    source_kind = "flipper-irdb"

    def _load_models(self) -> list[PublicModel]:
        try:
            tree = json.loads(self.fetch(FLIPPER_TREE_URL))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Flipper-IRDB returned an invalid index: {exc}") from exc
        models = []
        for entry in tree.get("tree", []):
            path = entry.get("path", "")
            parts = PurePosixPath(path).parts
            if entry.get("type") != "blob" or not path.endswith(".ir") or len(parts) < 3:
                continue
            manufacturer = _pretty(parts[1])
            stem = _pretty(PurePosixPath(parts[-1]).stem)
            series = " / ".join(_pretty(part) for part in parts[2:-1])
            model_name = f"{series} / {stem}" if series else stem
            models.append(PublicModel(
                manufacturer, model_name, path, _device_type(parts[0]), path))
        return models

    def _commands(self, model: PublicModel) -> list[dict]:
        encoded = "/".join(quote(part, safe="")
                           for part in PurePosixPath(model.relative_path).parts)
        records = parse_ir_text(self.fetch(f"{FLIPPER_RAW_URL}/{encoded}"))
        commands = []
        for record in records:
            signal, reason = _flipper_signal(record)
            commands.append({
                "name": str(record.get("name", "Unnamed")),
                "signal": signal,
                "classification": "Flipper parsed" if record.get("type") == "parsed"
                                  else "Flipper raw",
                "reason": reason,
            })
        return commands


class IrdbCatalog(_PublicCatalog):
    source_kind = "irdb"

    def _load_models(self) -> list[PublicModel]:
        models = []
        for line in self.fetch(IRDB_INDEX_URL).splitlines():
            path = line.strip()
            parts = PurePosixPath(path).parts
            if not path.endswith(".csv") or len(parts) < 3:
                continue
            manufacturer = _pretty(parts[0])
            kind = " / ".join(_pretty(part) for part in parts[1:-1])
            tuple_name = PurePosixPath(parts[-1]).stem
            models.append(PublicModel(
                manufacturer, f"{kind} · {tuple_name}", path,
                _device_type(parts[1]), path))
        return models

    def _commands(self, model: PublicModel) -> list[dict]:
        encoded = "/".join(quote(part, safe="")
                           for part in PurePosixPath(model.relative_path).parts)
        text = self.fetch(f"{IRDB_RAW_URL}/{encoded}")
        commands = []
        for row in csv.DictReader(io.StringIO(text)):
            signal, reason = _irdb_signal(row)
            commands.append({
                "name": _pretty(row.get("functionname", "Unnamed")),
                "signal": signal,
                "classification": "IRDB protocol tuple",
                "reason": reason,
            })
        return commands
