#!/usr/bin/env python3
"""Learning from an imported configuration.

Importing a configuration teaches the library things: protocols not seen before, a
device's full command set, waveforms for commands no protocol describes. Without this
module all of that stayed inside one project file and the next person started from
nothing - and a config using an unknown protocol could not even be rebuilt.

`learn()` takes what an import produced and writes it into the current user's private
data directory as protocol, device and capture definitions. Nothing is contributed or
written into the application checkout. The files happen to use the shareable Afterglow
format, so publishing an entry later remains an explicit user action.

## Recognising what we already have

The same product appears in different people's configurations under different names - one
person's "TV Samsung" is another's "Living Room TV" - so a definition is identified by
**what it does, not what it is called**. A device's fingerprint is its protocol plus its
command names and codes; a capture's is its bytes; a protocol's is the block id, which is
already content-addressed. Two owners of the same television therefore produce one entry,
and re-importing a config adds nothing.

Names are kept as a set with no primary. The first person to import a television is not
more authoritative about what it is called than the second, so every name a device is
known by sits in `names` as an equal.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import device_json, ir_signal, paths, project_devices

LIBRARY = paths.user_library()


def slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return out or "unnamed"


def device_fingerprint(spec: dict) -> str:
    """What a portable device does, independent of names and provenance."""
    signals = spec.get("signals") or {}
    payload = []
    for command in spec.get("commands") or []:
        name = str(command[0] if isinstance(command, (list, tuple)) else command["name"])
        signal = dict(signals.get(name) or command.get("signal") or {})
        signal.pop("name", None)
        signal.pop("provenance", None)
        payload.append((name, signal))
    encoded = json.dumps(sorted(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:12]


def _index(folder: Path, key):
    """Index a library folder, saying so when an entry cannot be read.

    This is the *user's* library, not shipped data, so an unparseable file is reported
    rather than skipped: otherwise a protocol someone believed they had saved is simply
    absent, and saving it again lands on the same unreadable file.
    """
    out = {}
    for path in sorted(folder.glob("*.json")):
        try:
            spec = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"Warning: library entry {path.name} is not readable JSON and was "
                  f"skipped ({exc}). Nothing in it is available until it is fixed "
                  f"or removed.")
            continue
        value = key(spec)
        if value:
            out[value] = (path, spec)
    return out


def learn(project: dict, extracted_dir: str | Path, library: Path | str = LIBRARY,
          dry_run: bool = False) -> dict:
    """Save a project's portable devices, signals and protocols to the private library.

    ``extracted_dir`` remains in the signature for callers from older versions. Native
    protocol harvesting is deliberately gone: a user library is portable data, not an
    extension of one remote backend's bytecode catalogue.
    """
    project_devices.normalise_project(project)
    library = Path(library)
    protocols_dir = library / "protocols"
    devices_dir = library / "devices"
    captures_dir = library / "captures"
    for folder in (protocols_dir, devices_dir, captures_dir):
        folder.mkdir(parents=True, exist_ok=True)

    report = {"protocols": [], "devices": [], "captures": [],
              "known_devices": [], "unresolved_protocols": []}

    # portable protocols
    known_protocols = _index(protocols_dir, lambda definition: definition.get("id"))
    for device in project.get("devices", []):
        for protocol_id, definition in (
                device.get("portable_protocol_definitions") or {}).items():
            if protocol_id in known_protocols:
                if known_protocols[protocol_id][1] != definition:
                    raise ValueError(f"conflicting portable protocol {protocol_id!r}")
                continue
            path = protocols_dir / f"{slug(protocol_id)}.json"
            if not dry_run:
                path.write_text(json.dumps(definition, indent=2) + "\n")
            known_protocols[protocol_id] = (path, definition)
            report["protocols"].append(protocol_id)

    # captures
    by_bytes = _index(captures_dir, lambda s: s.get("fingerprint"))
    capture_names = {}
    for device in project.get("devices", []):
        for command_name, capture in (device.get("signals") or {}).items():
            if capture.get("kind") != "waveform":
                continue
            semantic = dict(ir_signal.normalise(capture))
            semantic.pop("name", None)
            semantic.pop("provenance", None)
            semantic.pop("native", None)
            encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
            finger = hashlib.sha256(encoded.encode()).hexdigest()[:12]
            if finger in by_bytes:
                capture_names[(device["id"], command_name)] = by_bytes[finger][0].stem
                continue
            spec = dict(capture)
            spec["fingerprint"] = finger
            name = slug(f"{device.get('model') or device.get('label')}-{spec.get('name','')}")[:60]
            path = captures_dir / f"{name}.json"
            n = 2
            while path.exists():
                path = captures_dir / f"{name}-{n}.json"
                n += 1
            if not dry_run:
                path.write_text(json.dumps(spec, indent=2) + "\n")
            by_bytes[finger] = (path, spec)
            capture_names[(device["id"], command_name)] = path.stem
            report["captures"].append(path.stem)

    # devices
    by_finger = _index(devices_dir, lambda s: s.get("fingerprint"))
    for device in project.get("devices", []):
        finger = device_fingerprint(device)
        label = device.get("label") or device.get("model") or device["id"]
        if finger in by_finger:
            path, spec = by_finger[finger]
            if device_json.add_name(spec, label) and not dry_run:
                device_json.save(spec, path)
            report["known_devices"].append(f"{label} = {path.stem}")
            continue
        spec = {
            "schema": device_json.PORTABLE_SCHEMA,
            "fingerprint": finger,
            "manufacturer": device.get("mfr", ""),
            "model": device.get("model", ""),
            "names": [label],
            "type": device.get("type", "Misc"),
            "commands": [],
        }
        # How the device is turned on and off. Without this a device added from the
        # library has no power at all, so an activity cannot start it - 24 of the
        # first 26 entries were learned before this was recorded.
        power = {}
        if device.get("always_on"):
            power["mode"] = "always_on"
        else:
            if device.get("power_on_cmd"):
                power["on"] = device["power_on_cmd"]
            if device.get("power_off_cmd"):
                power["off"] = device["power_off_cmd"]
            if device.get("power_cmd"):
                power["toggle"] = device["power_cmd"]
        if device.get("power_delay") is not None:
            power["delay_ms"] = device["power_delay"]
        if power:
            spec["power"] = power
        # The inputs an activity can switch this device to. Only the ones that send a
        # command are portable: an input that works by setting a second state refers to
        # that device's own state machine, which does not transfer to another config.
        inputs = [[name, command] for name, command in (device.get("inputs") or [])
                  if command]
        if inputs:
            spec["inputs"] = inputs
        # Whether this device can be given a channel to dial. Only the *shape* is
        # portable - the digit actions in an imported block name that config's device
        # id, so the builder regenerates them from this device's own number keys.
        # What the device *is*: whether it is a display, how many discs it holds,
        # which input its tuner uses. The remote changes its behaviour on these, and
        # they were being dropped along with power and inputs - so a device added from
        # the library arrived with nothing set and the Advanced page looked broken.
        if device.get("properties"):
            spec["properties"] = dict(device["properties"])

        numeric = device.get("numeric")
        if numeric:
            portable = {}
            if isinstance(numeric, dict):
                if numeric.get("fixed"):
                    portable["fixed"] = numeric["fixed"]
                finish = (numeric.get("finish") or {}).get("params")
                if finish:
                    command = dict(finish).get("Command")
                    if command:
                        portable["finish"] = command
            spec["numeric"] = portable or True
        icons = device.get("icons") or {}
        for command in device.get("commands", []):
            name, cmd_label = command[0], command[1]
            entry = {"name": name, "label": cmd_label}
            signal = device["signals"][name]
            key = (device["id"], name)
            if signal.get("kind") == "waveform" and key in capture_names:
                entry["signal"] = f"captures/{capture_names[key]}.json"
            else:
                entry["signal"] = signal
            if command[4]:
                entry["hard_key"] = command[4]
            if name in icons:
                entry["icon"] = icons[name]
            spec["commands"].append(entry)
        name = slug(f"{spec['manufacturer']}-{spec['model']}" if spec["model"] else label)
        path = devices_dir / f"{name}.json"
        n = 2
        while path.exists():
            path = devices_dir / f"{name}-{n}.json"
            n += 1
        if not dry_run:
            device_json.save(spec, path)
        by_finger[finger] = (path, spec)
        report["devices"].append(path.stem)
    return report


def duplicate_ids(library: Path | str = LIBRARY) -> dict:
    """Protocol ids with more than one file. Two files for one protocol means one of
    them is being ignored, which is worse than either being wrong."""
    seen: dict = {}
    for path in sorted((Path(library) / "protocols").glob("*.json")):
        try:
            block_id = json.loads(path.read_text()).get("id")
        except json.JSONDecodeError:
            # Reported by `_index`, which reads the same folder; duplicated warnings
            # here would say the same thing twice for one broken file.
            continue
        seen.setdefault(block_id, []).append(path)
    return {k: v for k, v in seen.items() if len(v) > 1}


def summarise(report: dict) -> str:
    lines = []
    for key, title in (("protocols", "new protocol"), ("devices", "new device"),
                       ("captures", "new capture")):
        if report[key]:
            lines.append(f"{len(report[key])} {title}(s): " + ", ".join(report[key][:6])
                         + (" …" if len(report[key]) > 6 else ""))
    if report["known_devices"]:
        lines.append(f"{len(report['known_devices'])} device(s) already known: "
                     + ", ".join(report["known_devices"][:4]))
    if report["unresolved_protocols"]:
        lines.append("pointer fields assumed (seen in only one config) for: "
                     + ", ".join(report["unresolved_protocols"]))
    return "\n".join(lines) or "nothing new - everything in this config is already known."
