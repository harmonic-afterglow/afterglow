"""Harmony PK implementation of the portable backend contract.

Only this module is selected by the application.  It accepts portable project devices,
lowers their signals into transient Harmony ``Code``/``SsIr``/``IrProto`` inputs, and
hands those to the arch-15 tree builder.  Native fields never travel back into the
project.  The legacy migration entry point is intentionally here as well: interpreting a
``harmony-ir-device/1`` file requires knowledge of Harmony block ids and command framing.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from ... import ir_protocol, ir_signal, project_devices
from . import BACKEND_NAMES, NAME
from . import ir_compile, protocol_json, ssir
from .mappings import protocol as protocol_mapping


def _native_evidence(signal: dict) -> dict:
    native = signal.get("native") or {}
    for name in BACKEND_NAMES:
        if native.get(name):
            return native[name]
    return {}


def _hex_bytes(code: str) -> bytes:
    text = str(code).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    if len(text) % 2:
        raise ValueError(f"Harmony PK command has an odd number of hex digits: {code!r}")
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(f"invalid Harmony PK command code {code!r}") from exc


def _bitrev(value: int) -> int:
    return int(f"{value:08b}"[::-1], 2)


def _decodable(block_id: str) -> bool:
    """Whether a semantic decode of this block could still be resolved after import."""
    from ... import ir_protocol
    from . import mappings

    installed = set(ir_protocol.catalog(ir_protocol.LIBRARY))
    return any(spec.get("block_id") == block_id and protocol_id in installed
               for protocol_id, spec in mappings.PROTOCOLS.items())


def _decode_protocol_code(block_id: str | None, code: str, *, name: str = "",
                          codec: str | None = None) -> dict | None:
    """Translate the native families we understand back into semantic parameters.

    Declines when the protocol it would name is not installed. This decoder produces a
    signal referring to a library protocol *by id*, which is only useful if something can
    resolve that id later. With no protocol library present it produced devices citing
    `nec1` and `rc6-mce` that carried no definition of either - a project that imported
    cleanly and could not be built, or moved to another remote.

    Declining is not a loss. The block is then reconstructed from the configuration's own
    IrProto by `extract_definition` and `promote`, which is self-contained by
    construction. What is given up is the *semantic* reading - `address` and `command`
    instead of an opaque payload - and that reading was only ever available because a
    definition of the family happened to be installed.
    """
    if block_id and not _decodable(block_id):
        return None
    raw = _hex_bytes(code)
    if block_id == "a7b8a0e6c639" and len(raw) >= 11:
        data = [_bitrev(value) for value in raw[7:11]]
        if data[3] != (data[2] ^ 0xFF):
            return None
        if codec == "necext" or data[1] != (data[0] ^ 0xFF):
            return ir_signal.protocol_signal(
                "nec-ext",
                {"address_low": data[0], "address_high": data[1], "command": data[2]},
                name=name,
                provenance={"kind": "decoded-native", "backend": NAME},
            )
        return ir_signal.protocol_signal(
            "nec1", {"address": data[0], "command": data[2]}, name=name,
            provenance={"kind": "decoded-native", "backend": NAME})
    if block_id == "e8f716b9ee19" and len(raw) >= 11:
        data = [_bitrev(value) for value in raw[7:11]]
        if data[1] != data[0] or data[3] != (data[2] ^ 0xFF):
            return None
        return ir_signal.protocol_signal(
            "samsung32", {"address": data[0], "command": data[2]}, name=name,
            provenance={"kind": "decoded-native", "backend": NAME})
    if block_id == "6bd42e0eea79" and len(raw) >= 13:
        if raw[1:8] != bytes.fromhex("00F40100000100"):
            return None
        value = int.from_bytes(raw[8:12], "big")
        if value & 0b11:
            return None
        return ir_signal.protocol_signal(
            "rc6-mce", {"code": value >> 2}, name=name,
            provenance={"kind": "decoded-native", "backend": NAME})
    return None


def _block_id(reference, library: Path | None) -> str | None:
    """Resolve a device record's protocol reference to a block id.

    **Afterglow ships no native protocol files** - `library/protocols/` is the
    only protocol data in the package, and a native block is a build intermediary that
    `ir_emit` generates from a portable definition, assembles into `IrProto.bin` inside
    the temporary build tree, and discards. A ratchet in `tests/test_ir_emit.py` keeps it
    that way.

    ``library`` here is **not** that shipped directory. It is a user-supplied root: a
    private device library, or an external Afterglow database (an HTTPS Git repository of
    dumped devices). Such a root may legitimately carry `protocols/<name>.json` - a native
    block someone dumped off their own remote for a device the portable grammar cannot
    yet describe. That is evidence they own, not a catalogue we distribute, and reading it
    is what lets a dumped device build at all.

    Removing this lookup on the assumption it was dead broke exactly that feature; the
    external-database test caught it.

    The alias table for the 21 filenames the removed native catalogue used is **gone**.
    It existed so records naming `nec-38-0-khz.json` still resolved, and it only ever
    covered 4 of the 21 - the other 17 failed anyway. With the generic compiler
    reproducing 99.96% of the archive there is nothing left for it to rescue, and a
    partial rescue that silently succeeds for four names and fails for seventeen is worse
    than an honest refusal.
    """
    if reference is None or isinstance(reference, int):
        return {0: "a7b8a0e6c639", 1: "e8f716b9ee19"}.get(reference)
    text = str(reference)
    if len(text) == 12 and all(char in "0123456789abcdef" for char in text.lower()):
        return text
    if library is None:
        return None
    path = Path(library) / "protocols" / text
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text()).get("id")
    except (OSError, json.JSONDecodeError):
        return None


def _protocol_definition(reference, block_id: str | None,
                         library: Path | None) -> dict | None:
    """A native block carried by a user-supplied library or external database.

    Same distinction as `_block_id`: never our own package data, always somebody's dumped
    evidence travelling with their device record.
    """
    if not block_id or library is None:
        return None
    folder = Path(library) / "protocols"
    direct = folder / str(reference)
    candidates = [direct] if direct.is_file() else list(folder.glob("*.json"))
    for path in candidates:
        try:
            definition = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if definition.get("id") == block_id:
            return definition
    return None


def _capture(reference: str, library: Path | None) -> dict | None:
    if not reference or library is None:
        return None
    name = Path(reference)
    if name.name != str(reference):
        raise ValueError(f"capture reference must be a filename, got {reference!r}")
    path = Path(library) / "captures" / name
    return ssir.normalise_signal(json.loads(path.read_text())) if path.is_file() else None


def _common_device(source: dict, device_id: str) -> dict:
    """Presentation/behaviour fields shared by old library and project records."""
    out = {
        "schema": project_devices.SCHEMA,
        "id": str(device_id or source.get("id") or ""),
        "label": source.get("label") or (source.get("names") or [""])[0]
                 or source.get("model") or "Unnamed Device",
        "type": source.get("type", "Misc"),
        "mfr": source.get("mfr", source.get("manufacturer", "")),
        "model": source.get("model", ""),
        "commands": [],
        "signals": {},
    }
    # Preserve behaviour fields this version does not know yet. Native transport and
    # database bookkeeping are the only things intentionally removed; using an allowlist
    # here made every future portable field disappear during migration.
    excluded = {
        "_database_root", "_source_file", "_template_name", "codec", "commands", "encoding",
        "fingerprint", "id", "label", "manufacturer", "mfr", "model", "names",
        "necext_addr", "notes", "power", "protocol", "protocol_definitions",
        "raw_codes", "raw_ir",
        "remote_models", "schema", "signals", "source", "timing",
    }
    for key, value in source.items():
        if key not in excluded:
            out[key] = deepcopy(value)
    power = source.get("power") or {}
    if power.get("mode") == "always_on":
        out["always_on"] = True
    for field, target in (("on", "power_on_cmd"), ("off", "power_off_cmd"),
                          ("toggle", "power_cmd")):
        if power.get(field):
            out[target] = power[field]
    if power.get("delay_ms") is not None:
        out["power_delay"] = power["delay_ms"]
    timing = source.get("timing") or {}
    for key in ("press_presilence", "press_interkey", "hold_presilence", "hold_interkey"):
        if timing.get(key) is not None:
            out[key] = timing[key]
    return out


# Pre-portable device records this backend authored, and therefore knows how to read.
# Declaring it here rather than letting shared code name this backend is what keeps
# `backends/harmony_pk/` deletable; see `afterglow.backends.for_legacy_device`.
LEGACY_DEVICE_SCHEMAS = ("harmony-ir-device/1",)


def claims_legacy(spec: dict) -> bool:
    """True when this backend recognises a pre-portable device record.

    Records predating the schema field are Harmony PK library devices: that is the only
    format this project ever wrote before `afterglow-device/2`. A second backend must
    claim its own schemas explicitly rather than relying on that history.
    """
    schema = spec.get("schema")
    return schema in LEGACY_DEVICE_SCHEMAS or schema is None


def migrate_legacy_device(source: dict, *, device_id: str = "",
                          library: Path | None = None) -> dict:
    """Convert a legacy Harmony device/library record to a portable project device."""
    out = _common_device(source, device_id)
    block_id = _block_id(source.get("protocol"), library)
    reference = source.get("protocol")
    # Only a *filename* reference is an error. A record naming a block by an arbitrary
    # label ("Denon-K") never resolved to an id and correctly carries its commands as
    # opaque native evidence, which is lossless. A record naming `something.json` is
    # different: it points at the native catalogue this project used to ship and no
    # longer does, so nothing will ever resolve it and the device cannot be rebuilt.
    if block_id is None and isinstance(reference, str) and reference.endswith(".json"):
        raise ValueError(
            f"device {source.get('model') or device_id or '?'!r} names protocol "
            f"{reference!r}, which this version cannot resolve. It predates the portable "
            "protocol format. Re-import the device from the configuration it came from; "
            "if that configuration is what produced this, please open an issue and "
            "attach the .ezhex so the protocol can be added.")
    # Inline evidence first: a record that carries its own definition is self-contained.
    # The library lookup is the fallback for a dumped device in a private or external
    # database, whose native block sits beside it rather than inside it.
    block_definition = (source.get("protocol_definitions") or {}).get(block_id)
    if block_definition is None:
        block_definition = _protocol_definition(source.get("protocol"), block_id, library)
    # Old Afterglow projects omitted the codec when they meant NEC; that was the
    # original builder's documented default. Preserve that exact legacy meaning at
    # migration time, then discard the codec from the portable result.
    codec = (source.get("encoding") or {}).get("codec", source.get("codec")) or "nec"
    encoding = source.get("encoding") or {}
    raw_codes = source.get("raw_codes") or {}
    raw_ir = source.get("raw_ir") or {}
    supplied_signals = source.get("signals") or {}

    for entry in source.get("commands") or []:
        if isinstance(entry, dict):
            name = str(entry["name"])
            label = entry.get("label", name)
            hard_key = entry.get("hard_key")
            row = [name, label, "", "", hard_key]
            signal = entry.get("signal") if isinstance(entry.get("signal"), dict) else None
            raw_code = entry.get("raw")
            capture = _capture(entry.get("capture", ""), library)
            value = entry.get("value")
        else:
            row = list(entry)
            while len(row) < 5:
                row.append(None if len(row) == 4 else "")
            name, label = str(row[0]), row[1]
            signal = supplied_signals.get(name)
            raw_code = raw_codes.get(name)
            capture = None
            index = ssir.raw_index(raw_code or "")
            if index is not None:
                capture = raw_ir.get(str(index))
            value = row[3]

        if signal is not None:
            signal = ir_signal.normalise(signal)
        elif capture is not None:
            signal = ir_signal.normalise(capture)
        elif raw_code:
            signal = _decode_protocol_code(block_id, raw_code, name=name, codec=codec)
            if signal is None:
                native = {"format": "command-code", "code": raw_code}
                if block_id:
                    native["protocol_block_id"] = block_id
                if block_definition:
                    native["protocol_definition"] = block_definition
                signal = ir_signal.backend_opaque(
                    {NAME: native}, name=name,
                    provenance={"kind": "legacy-device", "backend": NAME})
        elif value is not None and codec in ("nec", "necext", "samsung"):
            if codec == "necext":
                address = encoding.get("address") or source.get("necext_addr") or []
                parameters = {"address_low": address[0], "address_high": address[1],
                              "command": value}
                protocol_id = "nec-ext"
            else:
                address = (encoding.get("address") or [row[2]])[0]
                parameters = {"address": address, "command": value}
                protocol_id = "samsung32" if codec == "samsung" else "nec1"
            signal = ir_signal.protocol_signal(
                protocol_id, parameters, name=name,
                provenance={"kind": "legacy-device", "backend": NAME})
        else:
            raise ValueError(f"command {name!r} has no portable signal or native evidence")

        from ... import device_json
        address, command = device_json.command_fields(signal)
        if not row[2]:
            row[2] = address
        if not row[3] or raw_code:
            row[3] = command
        out["commands"].append(row)
        out["signals"][name] = signal

    project_devices.validate(out)
    return out


def _native_requirement(signal: dict, library, emissions: dict) -> tuple[
        str | None, dict | None, str | None]:
    if signal["kind"] == "protocol":
        mapping = protocol_mapping(signal["protocol"])
        needs_generic_lifecycle = False
        if mapping and mapping.get("emitter"):
            portable = ir_protocol.protocol(signal["protocol"], library)
            lifecycle = signal.get("transmission") or portable.get("transmission") or {}
            needs_generic_lifecycle = bool(lifecycle.get("release"))
            if not needs_generic_lifecycle:
                from . import ir_emit
                definition = emissions.get(signal["protocol"])
                if definition is None:
                    definition = ir_emit.emit(signal["protocol"], mapping, library=library)
                    emissions[signal["protocol"]] = definition
                return definition["id"], definition, None

        # No reviewed family is required here. Compile the portable meaning itself and
        # accept it only after the generated block and this command's complete lifecycle
        # pass the carrier VM gate. A failure is not fatal yet: `ir_compile` may still use
        # an exact fixed waveform when press and hold genuinely have the same meaning.
        from . import ir_emit
        from .builder import codes
        try:
            portable = ir_protocol.protocol(signal["protocol"], library)
            definition = ir_emit.emit_generic(
                portable, parameters=signal["parameters"],
                transmission=signal.get("transmission"))
            code = codes.generic_code(
                portable, ir_emit.element_order(portable), signal["parameters"], 0,
                transmission=signal.get("transmission"))
        except (KeyError, LookupError, ValueError):
            # A bespoke Code does not encode release. If generic lifecycle compilation
            # failed, leaving the mapped block here would make the ordinary codec appear
            # usable and silently erase release. Force normal lowering to refuse instead.
            block_id = None if needs_generic_lifecycle else (mapping or {}).get("block_id")
            return block_id, None, None
        emissions.setdefault(signal["protocol"], definition)
        return definition["id"], definition, code
    if signal["kind"] == "backend-opaque":
        native = _native_evidence(signal)
        return (native.get("protocol_block_id"), native.get("protocol_definition"), None)
    return None, None, None


def lower_devices(devices: list[dict], profile, *, library=None) -> list[dict]:
    """Portable project devices -> transient dictionaries consumed by arch-15 builder."""
    library = ir_protocol.LIBRARY if library is None else library
    lowered = []
    emissions = {}
    for source in devices:
        device = project_devices.clean(source)
        device.pop("schema", None)
        requirements = {
            name: _native_requirement(signal, library, emissions)
            for name, signal in device.get("signals", {}).items()
        }
        block_ids = {
            block_id for block_id, _definition, _code in requirements.values() if block_id}
        device["command_protocols"] = {
            name: block_id
            for name, (block_id, _definition, _code) in requirements.items()
            if block_id
        }
        # Retain the old transient field only when it is truthful. Builder validation
        # uses command_protocols; this is a compatibility aid for legacy callers.
        device["protocol"] = next(iter(block_ids)) if len(block_ids) == 1 else None
        definitions = {}
        for name, (block_id, definition, code) in requirements.items():
            if code is not None:
                device.setdefault("raw_codes", {})[name] = code
            if not block_id or definition is None:
                continue
            existing = definitions.get(block_id)
            if (existing is not None
                    and protocol_json.encode(existing) != protocol_json.encode(definition)):
                raise ValueError(f"conflicting native definitions for block {block_id}")
            if existing is not None:
                continue
            definitions[block_id] = definition
        if definitions:
            device["protocol_definitions"] = definitions
        lowered.append(device)
    ir_compile.prepare_devices(lowered, profile, library=library)
    return lowered


def capability(signal: dict, profile, *, library=None) -> dict:
    """Explain whether this backend can faithfully lower one portable signal."""
    library = ir_protocol.LIBRARY if library is None else library
    ir_signal.validate(signal)
    probe = {
        "schema": project_devices.SCHEMA,
        "id": "capability-probe",
        "label": "Capability probe",
        "type": "Misc",
        "mfr": "",
        "model": "",
        "commands": [["Probe", "Probe", "", "", None]],
        "signals": {"Probe": deepcopy(signal)},
    }
    try:
        lowered = lower_devices([probe], profile, library=library)[0]
        code = (lowered.get("raw_codes") or {}).get("Probe")
        if code and ssir.is_raw(code):
            index = ssir.raw_index(code)
            waveform = (lowered.get("raw_ir") or {}).get(str(index))
            if waveform is None:
                raise ValueError("backend produced a waveform reference with no waveform")
            ssir.encode_capture(waveform)
            return {"supported": True, "strategy": "waveform", "reason": "recorded waveform"}
        if signal["kind"] == "backend-opaque":
            return {
                "supported": True,
                "strategy": "imported-command",
                "reason": "preserved imported command",
                "validation": "source-roundtrip",
            }
        mapping = protocol_mapping(signal["protocol"])
        validation = (mapping or {}).get("validation")
        # ``reason`` is shown to users, one row per command, in the Add Device wizard.
        # It used to read "portable protocol (vm validated)" - our evidence tier, printed
        # 77 times when adding a television. That is engineering bookkeeping, and it
        # changes nothing a user would do: they add the device either way, and they have
        # a far better test available for free, which is to press the button and watch
        # the appliance. It could also mislead in both directions, since an anchor was
        # measured against somebody else's hardware, not theirs.
        #
        # So the tier stays in the payload for tooling and tests, and out of the prose.
        # A user-facing reason is worth words only when a command is *excluded*.
        return {
            "supported": True,
            "strategy": "native-protocol",
            "reason": "protocol command",
            "validation": validation or "vm-validated",
        }
    except (KeyError, LookupError, ValueError) as exc:
        return {"supported": False, "strategy": "unsupported", "reason": str(exc)}


def build_tree(devices, work, **kwargs) -> None:
    """Build the Harmony PK configuration tree from already-lowered devices.

    Keyword form is the portable contract every backend answers to; `BuildRequest` is
    this backend's own shape for it, so an unknown keyword fails here by name rather
    than being carried further in.
    """
    from . import builder
    builder.build(devices, work, builder.BuildRequest(**kwargs))


def import_project(extracted_dir, out_file=None) -> dict:
    """Read one extracted arch-15 configuration into the portable project model."""
    from . import importer
    return importer._build_project_harmony_pk(extracted_dir, out_file=out_file)
