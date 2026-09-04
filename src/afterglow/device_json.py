#!/usr/bin/env python3
"""Portable device-database records and their project representation.

New databases store ``afterglow-device/2``: product identity, button names and one
portable signal per command. A signal is either semantic protocol parameters or a raw
carrier waveform, so it does not name a remote, native bytecode block, runtime index or
command codec. Selecting a database entry produces ``afterglow-project-device/1``, the
same backend-neutral shape the GUI edits and project files persist.

    {
      "schema": "afterglow-device/2",
      "manufacturer": "Apple",  "model": "Apple TV 4K",  "type": "MediaCenterPC",
      "power": {"mode": "always_on"},
      "commands": [
        {"name": "Menu", "label": "TV / Menu", "signal": {
          "schema": "afterglow-ir-signal/1", "kind": "protocol",
          "protocol": "nec-ext",
          "parameters": {"address_low": 229, "address_high": 135, "command": 3}
        }}
      ]
    }

The old ``harmony-ir-device/1`` database layout remains readable at the input boundary.
It is migrated immediately; native fields never enter a project or get written by the
current library code.

    python -m afterglow.device_json show library/devices/apple-tv-4k.json
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "harmony-ir-device/1"
PORTABLE_SCHEMA = "afterglow-device/2"
SCHEMAS = (SCHEMA, PORTABLE_SCHEMA)

def display_name(spec: dict) -> str:
    """Something to show in a list. Any of a device's names will do - see `names`."""
    known = names(spec)
    return known[0] if known else spec.get("model", "")


def names(spec: dict) -> list[str]:
    """Every name this device is known by, none of them primary.

    The same product turns up in different people's configurations under whatever they
    happened to call it - "TV Samsung", "Living Room", "la télé". Picking one as the real
    name and demoting the rest to aliases makes a claim nothing supports: the first
    person to import is not more correct than the second. They are all just names, so
    they are kept as one set.
    """
    found = list(spec.get("names") or [])
    for legacy in ("label",):                    # older files had a single name
        value = spec.get(legacy)
        if value and value not in found:
            found.append(value)
    return found


def add_name(spec: dict, name: str) -> bool:
    """Record another name. Returns whether it was new."""
    name = (name or "").strip()
    if not name:
        return False
    known = names(spec)
    if name in known:
        return False
    spec["names"] = sorted(known + [name])
    spec.pop("label", None)
    return True


def load(path) -> dict:
    spec = json.loads(Path(path).read_text())
    if spec.get("schema") not in SCHEMAS:
        raise ValueError(
            f"{path}: expected one of {SCHEMAS!r}, got {spec.get('schema')!r}")
    if spec["schema"] == PORTABLE_SCHEMA:
        from . import ir_signal
        commands = spec.get("commands")
        if not isinstance(commands, list):
            raise ValueError(f"{path}: a portable device needs a commands list")
        for command in commands:
            if not command.get("name") or "signal" not in command:
                raise ValueError(
                    f"{path}: every portable device command needs name and signal")
            if isinstance(command["signal"], dict):
                ir_signal.validate(command["signal"])
            elif not isinstance(command["signal"], str) or not command["signal"]:
                raise ValueError(f"{path}: command signal must be an object or path")
    return spec


def save(spec: dict, path) -> None:
    Path(path).write_text(json.dumps(spec, indent=2) + "\n")


def _signal_reference(spec: dict, command: dict, library: Path | None) -> dict:
    """Resolve one v2 command signal without allowing a path to escape its library."""
    from . import ir_signal

    reference = command["signal"]
    if isinstance(reference, dict):
        ir_signal.validate(reference)
        return dict(reference)
    root = Path(library).resolve() if library is not None else None
    if root is None and spec.get("_source_file"):
        root = Path(spec["_source_file"]).resolve().parent.parent
    if root is None:
        raise ValueError(
            f"command {command['name']!r} references {reference!r}, but no library path "
            "is known")
    path = (root / reference).resolve()
    if root not in path.parents:
        raise ValueError(f"signal reference escapes the library: {reference!r}")
    if not path.is_file():
        raise ValueError(f"command {command['name']!r} references missing signal {path}")
    return ir_signal.load(path)


def _hex_field(value) -> str:
    """Format one semantic integer for the command editor's hexadecimal cells."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return f"{value:02X}"
    text = str(value).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        parsed = int(text, 16)
    except ValueError:
        return text
    return f"{parsed:0{max(2, len(text))}X}"


def command_fields(signal: dict) -> tuple[str, str]:
    """Project a semantic signal into the editor's legacy address/command columns.

    These columns predate portable signals, but they remain a useful compact editor for
    protocols with address/command parameters. RC6 has no address, so its full semantic
    code is shown in the command column. Waveforms and opaque backend codes deliberately
    remain blank because pretending they have byte parameters would be misleading.
    """
    if not isinstance(signal, dict) or signal.get("kind") != "protocol":
        return "", ""
    parameters = signal.get("parameters") or {}
    address = parameters.get("address", parameters.get("address_low"))
    command = parameters.get(
        "command",
        parameters.get("code", parameters.get("payload", parameters.get("Code0"))),
    )
    return _hex_field(address), _hex_field(command)


def update_signal_fields(signals: dict, commands: list) -> dict:
    """Apply edited address/command cells back to their semantic protocol signals."""
    updated = dict(signals or {})
    for row in commands:
        if len(row) < 4:
            continue
        name, _label, address, command = row[:4]
        signal = updated.get(name)
        if not isinstance(signal, dict) or signal.get("kind") != "protocol":
            continue
        parameters = dict(signal.get("parameters") or {})
        old_address = parameters.get("address", parameters.get("address_low"))
        old_command = parameters.get(
            "command",
            parameters.get("code", parameters.get("payload", parameters.get("Code0"))),
        )
        if address and _hex_field(address) != _hex_field(old_address):
            if "address" in parameters:
                parameters["address"] = address
            elif "address_low" in parameters:
                parameters["address_low"] = address
        if command and _hex_field(command) != _hex_field(old_command):
            if "command" in parameters:
                parameters["command"] = command
            elif "code" in parameters:
                parameters["code"] = command
            elif "payload" in parameters:
                parameters["payload"] = command
            elif "Code0" in parameters:
                parameters["Code0"] = command
        changed = dict(signal)
        changed["parameters"] = parameters
        updated[name] = changed
    return updated


def to_project_device(spec: dict, device_id: str = "", *,
                      library: Path | None = None) -> dict:
    """A database device -> the backend-neutral representation stored in a project."""
    if spec.get("schema") != PORTABLE_SCHEMA:
        from . import backends
        # Interpreting a pre-portable record needs one architecture's knowledge of block
        # ids and command framing. Let the backends say which of them owns this schema
        # rather than naming one here; see `backends.for_legacy_device`.
        return backends.for_legacy_device(spec).migrate_legacy_device(
            spec, device_id=device_id, library=library)

    from . import project_devices

    resolved = {command["name"]: _signal_reference(spec, command, library)
                for command in spec["commands"]}
    out = {
        "schema": project_devices.SCHEMA,
        "id": str(device_id or spec.get("id") or ""),
        "type": spec.get("type", "Misc"),
        "mfr": spec.get("manufacturer", ""),
        "model": spec.get("model", ""),
        "label": display_name(spec) or spec.get("model") or "Unnamed Device",
        "commands": [],
        "signals": resolved,
    }
    power = spec.get("power") or {}
    if power.get("mode") == "always_on":
        out["always_on"] = True
    for source, target in (("on", "power_on_cmd"), ("off", "power_off_cmd"),
                           ("toggle", "power_cmd")):
        if power.get(source):
            out[target] = power[source]
    if power.get("delay_ms") is not None:
        out["power_delay"] = power["delay_ms"]
    for key in ("inputs", "input_cycle", "numeric", "properties", "states",
                "control_states", "icons"):
        if spec.get(key):
            out[key] = json.loads(json.dumps(spec[key]))
    for key, value in (spec.get("timing") or {}).items():
        if key in ("press_presilence", "press_interkey", "hold_presilence",
                   "hold_interkey"):
            out[key] = value
    for command in spec["commands"]:
        address, value = command_fields(resolved[command["name"]])
        out["commands"].append([
            command["name"], command.get("label", command["name"]), address, value,
            command.get("hard_key"),
        ])
    from . import ir_protocol
    needed = {signal.get("protocol") for signal in resolved.values()
              if signal.get("kind") == "protocol"}
    carried = {}
    inline = spec.get("portable_protocol_definitions") or {}
    if not isinstance(inline, dict):
        raise ValueError("portable_protocol_definitions must be an object")
    for protocol_id, definition in inline.items():
        ir_protocol.validate(definition)
        if definition["id"] != protocol_id:
            raise ValueError(
                f"portable protocol key {protocol_id!r} contains id {definition['id']!r}")
        if protocol_id in needed:
            carried[protocol_id] = json.loads(json.dumps(definition))
    if library is not None:
        folder = Path(library) / "protocols"
        if folder.is_dir():
            available = ir_protocol.catalog(folder)
            for protocol_id in needed:
                if protocol_id not in available:
                    continue
                existing = carried.get(protocol_id)
                if existing is not None and existing != available[protocol_id]:
                    raise ValueError(
                        f"inline portable protocol {protocol_id!r} conflicts with library")
                carried[protocol_id] = available[protocol_id]
    if carried:
        out["portable_protocol_definitions"] = carried
    project_devices.validate(out)
    return out


def summarise(spec: dict) -> str:
    commands = spec.get("commands") or []
    bound = sum(1 for command in commands
                if isinstance(command, dict) and command.get("hard_key"))
    kinds = sorted({command.get("signal", {}).get("kind", "reference")
                    for command in commands if isinstance(command, dict)})
    known = names(spec)
    return (f"{spec.get('manufacturer','')} {spec.get('model','')}".strip()
            + f"  [{spec.get('type','?')}]\n"
            + (f"  known as : {', '.join(known)}\n" if known else "")
            + f"  signals  : {', '.join(kinds) or 'none'}\n"
            + f"  commands : {len(commands)} ({bound} on physical keys)")


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    show = sub.add_parser("show", help="summarise a device definition")
    show.add_argument("path")
    args = parser.parse_args(argv)
    if args.cmd == "show":
        print(summarise(load(args.path)))


if __name__ == "__main__":
    main()
