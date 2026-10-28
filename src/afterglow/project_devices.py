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

import re

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
    page = device.get("screen_buttons")
    if page is not None:
        if not isinstance(page, list):
            raise ValueError("screen_buttons must be a list")
        for entry in page:
            if entry is not None and not (
                    isinstance(entry, (list, tuple)) and 2 <= len(entry) <= 3
                    and all(isinstance(part, str) for part in entry)):
                raise ValueError(f"a screen button is [command, label(, icon)] or null, "
                                 f"not {entry!r}")
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


# Abbreviations an input's command spells as a word ("InputHdmi1"), as Logitech's
# input names write them ("HDMI 1").
_INPUT_WORDS = {word.casefold(): word for word in (
    "AV", "TV", "HDMI", "DVI", "VGA", "USB", "PC", "RGB", "CD", "DVD", "VCR", "FM", "AM",
    "AUX", "DTV", "ATV", "BD", "LAN", "DVR", "SAT", "CBL", "MD", "DAB", "HD", "SD", "S")}


def input_label(name: str) -> str:
    """An input as a person reads it: a command name like `InputHdmi1` becomes `HDMI 1`
    and `InputComponent` `Component`; anything else - `HDMI 1`, `Netflix` - is already
    one, and stays as it is."""
    match = re.fullmatch(r"Input([A-Z][A-Za-z]*?)(\d*)", name or "")
    if not match:
        return name
    words = re.findall(r"[A-Z][a-z]*", match[1])
    spelled = " ".join(_INPUT_WORDS.get(word.casefold(), word) for word in words)
    return f"{spelled} {match[2]}".strip() if match[2] else spelled


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


def screen_buttons(device: dict) -> list:
    """The buttons on a device's own page of the remote's screen, in order: each
    ``[command, label]`` or ``[command, label, icon]``, or None for a gap.

    A device carries them as `screen_buttons` once its page has been read from a
    configuration or arranged in the editor. Logitech's pages show a chosen few commands
    in an order of their own - often under other names, now and then one command twice -
    and an older project has no such list. Its page is then every command with a label,
    in the order of its commands, which is how it was always built. A button whose
    command the device no longer has is dropped, and so are gaps after the last button;
    gaps before the first are Logitech's own, and kept."""
    names = {str(row[0]) for row in device.get("commands") or [] if row}
    page = device.get("screen_buttons")
    if page is None:
        icons = device.get("icons") or {}
        page = [[row[0], row[1]] + ([icons[row[0]]] if row[0] in icons else [])
                for row in device.get("commands") or []
                if row and len(row) > 1 and row[1]]
    out = [list(entry) if entry else None for entry in page
           if entry is None or entry[0] in names]
    while out and out[-1] is None:
        out.pop()
    return out


def rename_screen_command(device: dict, old: str, new: str | None) -> None:
    """Follow a command renamed (or removed, when ``new`` is None) on the device's page,
    if it has one of its own."""
    page = device.get("screen_buttons")
    if page is None:
        return
    device["screen_buttons"] = [
        entry if entry is None or entry[0] != old else [new, *entry[1:]]
        for entry in page if entry is None or entry[0] != old or new is not None]


POWER_FIELDS = ("power_cmd", "power_on_cmd", "power_off_cmd")


def rename_commands(device: dict, renames: dict, activities=()) -> None:
    """Follow commands renamed in the editor - {old: new} - everywhere the device and
    the project's activities name them: its power, inputs, number keys and page, and the
    activities' steps, keys and buttons. Renaming one used to keep the old name in all of
    them, and the device was refused on Save for commands with no code."""
    renames = {old: new for old, new in (renames or {}).items() if old and new and old != new}
    if not renames:
        return

    def name(value):
        return renames.get(value, value) if isinstance(value, str) else value

    for field in POWER_FIELDS:
        if device.get(field):
            device[field] = name(device[field])
    if device.get("inputs"):
        device["inputs"] = [[entry[0], name(entry[1]), *entry[2:]] if len(entry) > 1
                            else list(entry) for entry in device["inputs"]]
    cycle = device.get("input_cycle")
    if isinstance(cycle, dict):
        for key in ("next", "previous"):
            if cycle.get(key):
                cycle[key] = name(cycle[key])
    numeric = device.get("numeric")
    if isinstance(numeric, dict):
        if numeric.get("finish"):
            numeric["finish"] = name(numeric["finish"])
        if isinstance(numeric.get("digits"), dict):
            numeric["digits"] = {digit: name(command)
                                 for digit, command in numeric["digits"].items()}
    if isinstance(device.get("icons"), dict):
        device["icons"] = {name(command): icon for command, icon in device["icons"].items()}
    for old, new in renames.items():
        rename_screen_command(device, old, new)

    ours = str(device.get("id"))

    def step(entry):
        if isinstance(entry, (list, tuple)) and len(entry) >= 3 and entry[0] == "command" \
                and str(entry[1]) == ours:
            return [entry[0], entry[1], name(entry[2]), *entry[3:]]
        return entry

    def steps(entries):
        return [step(entry) for entry in entries or []]

    for activity in activities or []:
        for field in ("enter", "leave"):
            if activity.get(field):
                activity[field] = steps(activity[field])
        if activity.get("hard_macros"):
            activity["hard_macros"] = {key: steps(macro)
                                       for key, macro in activity["hard_macros"].items()}
        buttons = []
        for button in activity.get("soft_buttons") or []:
            if isinstance(button, dict):
                button = dict(button)
                if str(button.get("device")) == ours:
                    button["command"] = name(button.get("command"))
                if button.get("macro"):
                    button["macro"] = steps(button["macro"])
            elif isinstance(button, (list, tuple)) and len(button) >= 3 \
                    and str(button[1]) == ours:
                button = [button[0], button[1], name(button[2]), *button[3:]]
            buttons.append(button)
        if "soft_buttons" in activity:
            activity["soft_buttons"] = buttons
        favourites = []
        for favourite in activity.get("image_buttons") or []:
            favourite = list(favourite)
            if len(favourite) > 2 and favourite[1] == "command" \
                    and isinstance(favourite[2], (list, tuple)) \
                    and str(favourite[2][0]) == ours:
                favourite[2] = [favourite[2][0], name(favourite[2][1]), *favourite[2][2:]]
            elif len(favourite) > 2 and favourite[1] == "macro":
                favourite[2] = steps(favourite[2])
            favourites.append(favourite)
        if "image_buttons" in activity:
            activity["image_buttons"] = favourites
        confirm = activity.get("channel_confirm")
        if isinstance(confirm, (list, tuple)) and len(confirm) >= 2 \
                and str(confirm[0]) == ours:
            activity["channel_confirm"] = [confirm[0], name(confirm[1]), *confirm[2:]]


def command_rows(device: dict) -> list[list]:
    """A device's command rows as lists, made so in place, for code that changes them.

    The editor handed rows back as tuples, and a project changed in the window kept them
    until it was saved and read again - so renaming or dropping a key in one (moving a
    Harmony 900 project to the One) failed with "'tuple' object does not support item
    assignment"."""
    rows = [list(row) for row in device.get("commands") or []]
    if "commands" in device:
        device["commands"] = rows
    return rows


def fill_free_keys(project: dict, available) -> int:
    """Bind each device's skip keys to its own equivalent, once per device. Returns how
    many were bound. A device is marked when done, so a key its owner clears later stays
    clear."""
    filled = 0
    for device in project.get("devices") or []:
        if device.get(KEYS_FILLED):
            continue
        commands = [c for c in command_rows(device) if c]
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
        for command in command_rows(device):
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
    _promote_native_signals(migrated)
    return project


def native_only(project: dict) -> int:
    """How many commands in a project are a remote's native code ("backend-opaque") -
    playable only on the remote they were read from."""
    return sum(signal.get("kind") == "backend-opaque"
               for device in project.get("devices") or []
               for signal in (device.get("signals") or {}).values()
               if isinstance(signal, dict))


def _promote_native_signals(devices: list[dict]) -> None:
    """Native-only commands become portable protocols where their backend can convert them.

    Every installed backend is offered every device, whatever the project's remote: a
    device keeps its native evidence however often it moves between remotes, and each
    backend converts only its own (`promote_native_signals`, optional).
    """
    from . import backends
    for name in backends.installed():
        try:
            promote = getattr(backends.get(name), "promote_native_signals", None)
        except (LookupError, TypeError):
            continue
        if promote is not None:
            for device in devices:
                promote(device)
