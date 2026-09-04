"""The portable device shape stored in projects and passed between application layers.

The GUI historically edited the same dictionary the Harmony PK XML builder consumed.
Consequently project files accumulated ``raw_codes``, ``raw_ir``, native protocol block
ids and a codec chosen for one remote.  This module defines the boundary those files were
missing: presentation and device behaviour stay here, every command has one portable
signal, and native build products are forbidden.

An importer may preserve a command as ``backend-opaque`` when its meaning is not yet
known.  That is explicit evidence, not a portability claim; ordinary protocol and
waveform signals work with any backend able to reproduce their meaning.
"""
from __future__ import annotations

from copy import deepcopy

from . import ir_signal

SCHEMA = "afterglow-project-device/1"
NATIVE_FIELDS = frozenset({
    "codec",
    "necext_addr",
    "protocol",
    "protocol_definitions",
    "raw_codes",
    "raw_ir",
})


def validate(device: dict, *, allow_opaque: bool = True) -> None:
    """Validate the cross-backend project representation."""
    if device.get("schema") != SCHEMA:
        raise ValueError(f"expected project device schema {SCHEMA!r}")
    leaked = sorted(NATIVE_FIELDS & set(device))
    if leaked:
        raise ValueError(f"project device contains backend fields: {', '.join(leaked)}")
    commands = device.get("commands")
    signals = device.get("signals")
    if not isinstance(commands, list) or not isinstance(signals, dict):
        raise ValueError("a project device needs commands and signals")
    names = []
    for command in commands:
        if not isinstance(command, (list, tuple)) or not command or not command[0]:
            raise ValueError("every project command needs a name")
        names.append(str(command[0]))
    if len(names) != len(set(names)):
        raise ValueError("project command names must be unique")
    missing = set(names) - set(signals)
    extra = set(signals) - set(names)
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing signals for {sorted(missing)}")
        if extra:
            detail.append(f"signals without commands {sorted(extra)}")
        raise ValueError("; ".join(detail))
    for name in names:
        ir_signal.validate(signals[name])
        if not allow_opaque and signals[name]["kind"] == "backend-opaque":
            raise ValueError(f"command {name!r} has only backend-opaque evidence")
    definitions = device.get("portable_protocol_definitions") or {}
    if not isinstance(definitions, dict):
        raise ValueError("portable_protocol_definitions must be an object")
    if definitions:
        from . import ir_protocol
        for protocol_id, definition in definitions.items():
            ir_protocol.validate(definition)
            if definition["id"] != protocol_id:
                raise ValueError(
                    f"portable protocol key {protocol_id!r} contains id "
                    f"{definition['id']!r}")


def clean(device: dict) -> dict:
    """Return a defensive copy after enforcing the portable boundary."""
    out = deepcopy(device)
    validate(out)
    out["commands"] = [list(command) for command in out["commands"]]
    return out


def is_portable(device: dict) -> bool:
    try:
        validate(device)
    except (TypeError, ValueError):
        return False
    return True


def normalise_project(project: dict) -> dict:
    """Migrate old project devices at the read boundary and validate current ones."""
    from . import backends, remotes

    remote_id = (project.get("settings") or {}).get("remote", "harmony-900")
    backend = backends.for_profile(remotes.get(remote_id))
    migrated = []
    for device in project.get("devices") or []:
        migrated.append(clean(device) if is_portable(device)
                        else backend.migrate_legacy_device(device))
    project["devices"] = migrated
    return project
