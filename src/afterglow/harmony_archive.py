"""Logitech's Harmony device database, read a device at a time from Afterglow's archive.

The archive (harmonic-afterglow/harmony-ir-archive) keeps the raw capture of Logitech's
service and serves it as a static API: manufacturers and their devices as JSON, devices in
1,024 gzipped buckets by id, shared command sets in 4,096 by hash, every protocol in one
file. Looking a device up fetches its manufacturer's list, its bucket, its command set's
bucket and the protocols - a few hundred kilobytes, cached - never the whole database.

`ApiArchive` serves those records under the paths `logitech_archive` reads - an index of
manufacturers, each manufacturer's devices, a device, a code set, a protocol - so the
catalogue and every command's analysis work unchanged. A device carries what Logitech knew
about driving it: every timing field (the delay before a smart TV's apps answer,
`connectedAppPowerOnDelay`, among them), power, inputs - each with `online` when it is one
of those apps - channel tuning and states.

The projection from Logitech's raw fields is checked against an earlier projection of the
same capture (tests/test_harmony_archive.py).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

from . import logitech_archive

ArchiveError = logitech_archive.ArchiveError

API = "api/v1"
POWER_TYPES = {1: "discrete", 2: "toggle", 3: "none", 0: "unknown"}


# -- Logitech's action lists, as the curated schema writes them

def _actions(actions) -> list:
    """An action list in `Order`: a command name, `{"delayMs": n}`, `{"set", "to"}`."""
    out = []
    for action in sorted(actions or [], key=lambda item: item.get("Order", 0)):
        kind = action.get("__type", "").split(":")[0]
        if kind == "IRPressAction":
            name = action.get("IRCommandName")
            out.append({"command": name, "durationMs": action["Duration"]}
                       if action.get("Duration") else name)
        elif kind == "IRHoldAction":
            out.append({"hold": action.get("IRCommandName")})
        elif kind == "IRDelayAction":
            out.append({"delayMs": action.get("Delay", 0)})
        elif kind == "IRDevAction":
            out.append({"set": action.get("StateName"), "to": action.get("StateValue")})
    return out


def _first(features: dict, kind: str) -> dict:
    found = features.get(kind) or []
    return found[0] if found else {}


def project_device(device_id: int, entry: dict, codeset_path: str) -> dict:
    """A raw device as the curated schema's device record, with what it left out added:
    each input's `online`, and every timing field."""
    device, features = entry["device"], entry["features"]
    power = _first(features, "PowerFeature")
    inputs = _first(features, "InputFeature")
    tuning = _first(features, "ChannelTuningFeature")
    out = {
        "codeset": codeset_path,
        # the catalogue's type where it has one: for a few devices the two disagree, and
        # the catalogue's is the one device types were mapped from
        "deviceType": (entry.get("catalog") or {}).get("DeviceType", device.get("DeviceType")),
        "globalDeviceId": device_id,
        "manufacturer": device.get("Manufacturer"),
        "model": device.get("Model") or None,
    }
    timing = {
        "connectedAppPowerOnDelay": power.get("ConnectedAppPowerOnDelay", 0),
        "holdInterDeviceDelay": device.get("HoldInterDeviceDelay", 0),
        "inputDelay": inputs.get("InputDelay", 0),
        "interDeviceDelay": device.get("InterDeviceDelay", 0),
        "interKeyDelay": device.get("InterKeyDelay", 0),
        "isInterKeyDelayOptimized": bool(device.get("IsInterKeyDelayOptimized", False)),
        "pressMinRepeats": device.get("PressMinRepeats", 0),
    }
    if "MinRepeats" in (entry.get("catalog") or {}):
        timing["minRepeats"] = entry["catalog"]["MinRepeats"]
    if "PowerOnDelay" in power:
        timing["powerOnDelay"] = power["PowerOnDelay"]
    out["timing"] = timing
    kind = POWER_TYPES.get(power.get("PowerTypeId"))
    if kind is not None:
        block = {"type": kind}
        for source, target in (("PowerOnActions", "on"), ("PowerOffActions", "off"),
                               ("PowerToggleActions", "toggle"),
                               ("PowerOnResetActions", "onReset")):
            steps = _actions(power.get(source))
            if steps:
                block[target] = steps
        # no power and nothing to do about it says nothing
        if kind != "none" or len(block) > 1:
            out["power"] = block
    listed = []
    # in the list's own order, which InputOrder never contradicts (RAW-SCHEMA.md)
    for item in inputs.get("Inputs") or []:
        if not item.get("InputName"):
            continue                   # an input with no name selects nothing nameable
        entry_out = {"name": item.get("InputName")}
        steps = _actions(item.get("Actions"))
        if steps:
            entry_out["commands"] = steps
        ports = [port.get("Name") for port in item.get("PortTypes") or [] if port.get("Name")]
        if ports:
            entry_out["ports"] = ports
        if item.get("IsOnline"):
            entry_out["online"] = True
        listed.append(entry_out)
    if listed:
        block = {"list": listed, "type": inputs.get("InputType", 0)}
        for source, target in (("NextActions", "next"), ("PreviousActions", "previous"),
                               ("StartActions", "start"), ("FinishActions", "finish")):
            steps = _actions(inputs.get(source))
            if steps:
                block[target] = steps
        if inputs.get("CanSkipInputs"):
            block["canSkip"] = True
        out["inputs"] = block
    if tuning:
        block = {}
        if tuning.get("FixedDigits"):
            block["fixedDigits"] = tuning["FixedDigits"]
        for source, target in (("StartActions", "start"), ("FinishActions", "finish"),
                               ("GreaterTenActions", "greaterTen"),
                               ("GreaterHundredActions", "greaterHundred")):
            steps = _actions(tuning.get(source))
            if steps:
                block[target] = steps
        if block:
            out["channelTuning"] = block
    states = {}
    for state in features.get("InternalStateFeature") or []:
        # A value is listed once for itself and again for each way of selecting it.
        values: dict[str, dict] = {}
        for value in state.get("StateValues") or []:
            entry_value = values.setdefault(value.get("StateValueName"),
                                            {"name": value.get("StateValueName")})
            if value.get("Actions"):
                select = {"commands": _actions(value["Actions"]),
                          "setType": value.get("ActionSetType")}
                if select not in entry_value.setdefault("select", []):
                    entry_value["select"].append(select)
        block = {"values": list(values.values())}
        if state.get("ValueDelay"):
            block["valueDelay"] = state["ValueDelay"]
        for source, target in (("NextActions", "next"), ("PreviousActions", "previous"),
                               ("StartActions", "start"), ("FinishActions", "finish")):
            steps = _actions(state.get(source))
            if steps:
                block[target] = steps
        states[state.get("StateName")] = block
    if states:
        out["states"] = states
    return out


def keycode_fields(definition: dict) -> dict:
    """Each field a key code carries, by the segment it fills: its bits, its segment, the
    sequence (start, repeat, finish) and its place there - derived from the definition."""
    segments = {segment.get("Name"): (index, segment)
                for index, segment in enumerate(definition.get("IRSegments") or [])}
    out, number = {}, 0
    for sequence in ("Start", "Repeat", "Finish"):
        for token, item in enumerate((definition.get("KeyCode") or {}).get(sequence) or []):
            found = segments.get(item.get("SegmentName"))
            payload = found and found[1].get("Payload")
            if not payload:
                continue
            out[f"Code{number}"] = {"bits": payload.get("NumberOfBits"),
                                    "segment": str(found[0]), "sequence": sequence.lower(),
                                    "toggleBit": payload.get("ToggleBit"), "token": token}
            number += 1
    return out


def project_protocol(definition: dict) -> dict:
    """A raw protocol as the curated schema's protocol record."""
    return {
        "carrierHz": definition.get("CarrierFrequency"),
        "definition": definition,
        "keycodeFields": keycode_fields(definition),
        "logitechProtocolId": definition.get("Id-"),
        "name": definition.get("Name"),
        "pressMinimumRepeats": definition.get("PressMinimumRepeats"),
    }


def project_command(command: dict, protocols: dict) -> dict:
    out = {"name": command.get("Name"), "keycode": command.get("KeyCode")}
    if not command.get("KeyCode") and command.get("Raw"):
        # learned in Logitech's software: no protocol, only the timings it captured
        out["raw"] = command["Raw"]
    protocol = protocols.get(str(command.get("ProtocolId")))
    if protocol is not None:
        out["protocol"] = protocol.get("Name")
    for key in ("pronto", "prontoRepeat"):
        if command.get(key):
            out[key] = command[key]
    return out


def _store(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _decode(relative: str, payload: bytes):
    if relative.endswith(".gz"):
        payload = gzip.decompress(payload)
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"archive file is not JSON: {relative}") from exc


class ApiArchive(logitech_archive.Archive):
    """Afterglow's archive over HTTPS (or a local checkout's `docs/`), a few files a
    device, kept in ``cache``. The manifest is fetched afresh each time the archive is
    opened - the copy in the cache is only for when the archive cannot be reached - and
    every other file is cached under the manifest's `build`, which changes whenever any
    of them does: a rebuilt archive is read at once, and nothing is fetched twice."""

    def __init__(self, base, cache):
        self.base = str(base).rstrip("/")
        self.local = not self.base.startswith(("https://", "http://"))
        self.cache_base = Path(cache).expanduser().resolve()
        self.cache_base.mkdir(parents=True, exist_ok=True)
        self._buckets: dict[str, dict] = {}
        self._slugs: dict[str, str] = {}
        self._protocols: dict | None = None
        manifest = self.cache_base / "manifest.json"
        try:
            payload = self._download("manifest.json")
            _store(manifest, payload)
        except ArchiveError:
            if not manifest.is_file():
                raise
            payload = manifest.read_bytes()
        self._api_manifest = _decode("manifest.json", payload)
        if self._api_manifest.get("api") != 1:
            raise ArchiveError(f"expected archive API 1, got "
                               f"{self._api_manifest.get('api')!r}")
        build = str(self._api_manifest.get("build") or "unstamped")
        self.cache_root = self.cache_base / build
        logitech_archive.Archive.__init__(self, self.cache_root)
        self.revision = build

    # -- the API's own files

    def _download(self, relative: str) -> bytes:
        if self.local:
            try:
                return (Path(self.base) / API / relative).read_bytes()
            except OSError as exc:
                raise ArchiveError(f"archive file is missing: {relative}") from exc
        request = Request(f"{self.base}/{API}/{relative}",
                          headers={"User-Agent": "Afterglow archive reader/1"})
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except OSError as exc:
            raise ArchiveError(f"could not fetch {relative}: {exc}") from exc

    def _fetch(self, relative: str) -> bytes:
        cached = self.cache_root / relative
        if cached.is_file():
            return cached.read_bytes()
        payload = self._download(relative)
        _store(cached, payload)
        return payload

    def _json(self, relative: str):
        return _decode(relative, self._fetch(relative))

    @property
    def api_manifest(self) -> dict:
        return self._api_manifest

    def _bucket(self, relative: str) -> dict:
        if relative not in self._buckets:
            self._buckets[relative] = self._json(relative)
        return self._buckets[relative]

    @property
    def protocols(self) -> dict:
        if self._protocols is None:
            self._protocols = self._json("protocols.json")
        return self._protocols

    def raw_device(self, device_id: int) -> dict:
        found = self._bucket(f"devices/{device_id % self.api_manifest['device_buckets']:03x}"
                             ".json.gz").get(str(device_id))
        if found is None:
            raise ArchiveError(f"device {device_id} is not in the archive")
        return found

    # -- the paths logitech_archive reads

    def read_json(self, relative: str):
        parts = PurePosixPath(relative).parts
        if relative == "manifest.json":
            counts = self.api_manifest["counts"]
            return {"schemaVersion": logitech_archive.ARCHIVE_SCHEMA_VERSION,
                    "counts": counts, "source": self.api_manifest.get("source")}
        if relative == "index.json":
            makers = self._json("manufacturers.json")
            self._slugs = {maker["slug"]: maker["name"] for maker in makers}
            return [{"n": maker["name"], "s": maker["slug"], "c": maker["devices"]}
                    for maker in makers]
        if len(parts) == 3 and parts[0] == "devices" and parts[2] == "index.json":
            return [{"f": f"{item['id']}.json", "m": item.get("model"), "id": item["id"]}
                    for item in self._json(f"manufacturers/{parts[1]}.json")]
        if len(parts) == 3 and parts[0] == "devices":
            device_id = int(PurePosixPath(parts[2]).stem)
            entry = self.raw_device(device_id)
            return project_device(device_id, entry, f"codesets/{entry['codeset']}.json")
        if len(parts) == 2 and parts[0] == "codesets":
            codeset = PurePosixPath(parts[1]).stem
            commands = self._bucket(
                f"codesets/{codeset[:self.api_manifest['codeset_prefix']]}.json.gz"
            ).get(codeset)
            if commands is None:
                raise ArchiveError(f"code set {codeset} is not in the archive")
            return {"commands": [project_command(command, self.protocols)
                                 for command in commands]}
        if relative == "protocols/index.json":
            return [{"f": f"{key}.json", "id": int(key), "n": value.get("Name"),
                     "carrierHz": value.get("CarrierFrequency")}
                    for key, value in self.protocols.items()]
        if len(parts) == 2 and parts[0] == "protocols":
            definition = self.protocols.get(PurePosixPath(parts[1]).stem)
            if definition is None:
                raise ArchiveError(f"archive protocol {relative} does not exist")
            return project_protocol(definition)
        raise ArchiveError(f"the archive has no {relative}")

    def iter_codesets(self):
        raise ArchiveError("a whole-database audit reads a local checkout of the archive")

    def iter_devices(self):
        raise ArchiveError("a whole-database conversion reads a local checkout of the archive")
