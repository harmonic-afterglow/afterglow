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


def input_names(device: dict) -> list[str]:
    """The inputs a device can be switched to, in order, however it reaches them.

    Directly chosen inputs, the values a cycle steps through, or - for an imported
    device - the values of its own Input state. A cycle-only device has no direct
    inputs at all, and offering nothing for it is how an activity could not say which
    input to end on.
    """
    names = [entry[0] if isinstance(entry, (list, tuple)) else entry
             for entry in device.get("inputs") or []]
    names += [v for v in (device.get("input_cycle") or {}).get("values", [])
              if v not in names]
    if not names:
        for state in device.get("states") or []:
            if state.get("id") == "Input":
                names = [a["name"] for a in state.get("actions", []) if a.get("name")] \
                    or list(state.get("values", []))
    return names


# What Logitech's own Harmony 900 configurations put on the transport skip keys when the
# device has no command of the key's own name, most common first (measured over the
# donors: NextTrack 12, ChapterNext 10, Replay 10, ...). A device whose skip is called
# ChapterNext or NextTrack otherwise left both keys doing nothing.
KEY_STAND_INS = {
    "SkipForward": ("SkipForward", "NextTrack", "ChapterNext", "NextChapter", "Skip",
                    "Advance", "Next"),
    "SkipBack": ("SkipBack", "SkipBackward", "PreviousTrack", "ChapterPrev",
                 "PrevChapter", "PreviousChapter", "Replay", "Prev"),
}
KEYS_FILLED = "free_keys_filled"


def free_key_assignments(bound: dict, available) -> dict:
    """{command name: key} for the skip keys nothing is bound to yet.

    `bound` is {command name: its key, a list of keys, or None}. Only commands with no
    key of their own are offered, and only keys the remote has.
    """
    taken = set()
    for keys in bound.values():
        taken.update(keys if isinstance(keys, list) else [keys] if keys else [])
    out = {}
    for key, names in KEY_STAND_INS.items():
        if key in taken or key not in available:
            continue
        for name in names:
            if name in bound and not bound[name] and name not in out:
                out[name] = key
                break
    return out


def fill_free_keys(project: dict, available) -> int:
    """Bind each device's skip keys to its own equivalent, once per device. Returns how
    many were bound. A device is marked when done, so a key its owner clears later stays
    clear."""
    filled = 0
    for device in project.get("devices") or []:
        if device.get(KEYS_FILLED):
            continue
        commands = [c for c in device.get("commands") or [] if c]
        bound = {c[0]: (c[4] if len(c) > 4 else None) for c in commands}
        new = free_key_assignments(bound, available)
        for command in commands:
            if command[0] in new:
                while len(command) < 5:
                    command.append(None)
                command[4] = new[command[0]]
                filled += 1
        device[KEYS_FILLED] = True
    return filled


def rename_hard_keys(project: dict, aliases: dict) -> int:
    """Rename physical-key bindings a remote's profile no longer calls that, in place.

    A key is bound in two places: a device command's hard slot (one name or a list) and
    an activity's `hard_macros`. Both are renamed, and a binding that would collide with
    one already on the new name is kept as it was rather than overwrite it. Returns how
    many were renamed.
    """
    if not aliases:
        return 0
    renamed = 0
    for device in project.get("devices") or []:
        for command in device.get("commands") or []:
            if len(command) < 5 or not command[4]:
                continue
            slots = command[4] if isinstance(command[4], list) else [command[4]]
            fixed = [aliases.get(slot, slot) for slot in slots]
            renamed += sum(a != b for a, b in zip(slots, fixed))
            command[4] = fixed if isinstance(command[4], list) else fixed[0]
    for activity in project.get("activities") or []:
        macros = activity.get("hard_macros") or {}
        for old, new in aliases.items():
            if old in macros and new not in macros:
                macros[new] = macros.pop(old)
                renamed += 1
    return renamed


def normalise_project(project: dict) -> dict:
    """Migrate old project devices at the read boundary and validate current ones."""
    from . import backends, remotes

    profile = remotes.for_project(project)
    rename_hard_keys(project, profile.hard_key_aliases)
    fill_free_keys(project, profile.hard_keys)
    backend = backends.for_profile(profile)
    migrated = []
    for device in project.get("devices") or []:
        migrated.append(clean(device) if is_portable(device)
                        else backend.migrate_legacy_device(device))
    project["devices"] = migrated
    return project
