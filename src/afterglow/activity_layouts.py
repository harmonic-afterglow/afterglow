"""An activity's Sound and Picture layouts, for the remotes that have the two keys.

The Harmony 5xx's and the 688's Sound and Picture keys turn an activity's screen and
keys over to one device for a while: Sound to the device that plays the sound, Picture
to the one that shows the picture. Pressed again, the key goes back to the activity; the
other key swaps layouts. A layout binds a few keys of its device - every other key keeps
the activity's - and may show buttons of its own on the screen.

A project says this remote-agnostically, and only where it differs from the default:

    activity["layouts"] = {
        "sound":   {"device": id, "hard_macros": {key: macro}, "soft_buttons": [...]},
        "picture": {"device": None},           # no Picture layout for this activity
    }

``hard_macros`` and ``soft_buttons`` have the shapes an activity's own have. A key whose
macro is empty keeps the activity's command; ``soft_buttons``, when present, replaces the
default list. A backend builds from `resolve`, never from the stored fields.

A device's own screen has its own Sound and Picture layouts, all of its keys and its
sound or picture settings as buttons; which of the two it has goes by its type
(`device_kinds`), and ``device["layouts"]``, a list of kinds, says otherwise.

The defaults are what Logitech's software chose, measured over the eleven household 555
and 550 configurations (55 activity layouts):

- Sound is the activity's volume device and Picture its display; never the source box.
  An activity with no display (radio, music) has no Picture layout.
- Sound binds Volume up, down and Mute - and, when the same device also shows the
  picture (a TV playing its own sound), its menu keys too, so its sound menu can be
  worked. Picture binds the direction pad, OK, Exit, Info and Guide.

The 688, 676 and 670 (2012-2025 configurations) give each activity both layouts too, as
a copy of the activity's keys with OK alone rebound, and show the device's Audio,
SubTitle and PIP commands on them. Their devices get layouts by type as the 5xx's do: a
TV, disc player or recorder both, a receiver or amplifier Sound, a lamp or a heater
neither. A set-top box has Sound on the 5xx and Picture on the 688; it gets both.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from . import paths

KINDS = ("sound", "picture")
TITLES = {"sound": "Sound", "picture": "Picture"}

VOLUME_KEYS = ("VolumeUp", "VolumeDown", "VolumeMute")
MENU_KEYS = ("DirectionUp", "DirectionDown", "DirectionLeft", "DirectionRight", "Select",
             "Menu", "Exit")
PICTURE_KEYS = ("DirectionUp", "DirectionDown", "DirectionLeft", "DirectionRight",
                "Select", "Exit", "Info", "Guide")

# Commands a layout shows on the screen by default: a device's own sound or picture
# settings. Logitech's software picked them by its database's function groups, which a
# project does not carry; library/layout-commands.json holds the names that database
# files there, and these words catch what it never named - a learned "Bass +", and the
# Audio and SubTitle the 688's configurations show on both layouts.
BUTTON_WORDS = {
    "sound": re.compile(r"sound|surround|effect|dsp|listen|audio|bass|treble|dialog|"
                        r"night|loudness|stereo|dolby|dts|subtitle|^mode", re.IGNORECASE),
    "picture": re.compile(r"picture|aspect|zoom|wide|format|ratio|p\.?mode|pip|"
                          r"backlight|contrast|brightness|sharpness|subtitle",
                          re.IGNORECASE),
}

# Which layouts a device's own screen has, by its type; a type not listed has both.
SOUND_ONLY_TYPES = {"Receiver", "Amplifier", "AudioVideoSwitch", "Cd", "CdJukebox",
                    "Cassette", "Dat", "Minidisc", "MusicServer", "RadioTuner",
                    "CdRadioCassette"}
NO_LAYOUT_TYPES = {"Light", "HomeAppliance", "ClimateControl"}


def device_kinds(device: dict) -> tuple[str, ...]:
    """The layouts a device's own screen has: the project's list, else its type's."""
    if "layouts" in device:
        return tuple(kind for kind in KINDS if kind in (device["layouts"] or ()))
    kind = device.get("type")
    if kind in NO_LAYOUT_TYPES:
        return ()
    if kind in SOUND_ONLY_TYPES:
        return ("sound",)
    return KINDS


def device_layout(device: dict, kind: str) -> dict:
    """A device's own Sound or Picture layout: every key the device binds, and its
    sound or picture settings as buttons."""
    return {"device": device.get("id"),
            "hard_macros": {key: [["command", device.get("id"), name]]
                            for key, name in _key_commands(device).items()},
            "soft_buttons": default_buttons(kind, device)}


# Device types that show the picture (the activity editor's Display list), and the
# types that say nothing of what a device is - a 5xx import's.
DISPLAY_TYPES = {"Television", "Projector", "Monitor", "TvDvd", "TvDvdVcr", "TvVcr",
                 "TvHdd", "MediaCenterPC", "Laptop", "Computer"}
UNKNOWN_TYPES = {None, "", "Unknown", "HomeAppliance"}


def layout_device(activity: dict, kind: str, devices: list[dict] = ()) -> str | None:
    """The device a layout is for: the project's choice, else the default."""
    stored = (activity.get("layouts") or {}).get(kind) or {}
    if "device" in stored:
        return stored["device"]
    return default_device(activity, kind, devices)


def default_device(activity: dict, kind: str, devices: list[dict] = ()) -> str | None:
    """Sound: the volume device. Picture: the screen - the Display when it is one, else
    a screen the activity turns on; none for an activity with no screen (a radio's).
    Without types to go by, the Display."""
    display = activity.get("display")
    if kind == "sound":
        return activity.get("volume") or display
    types = {device.get("id"): device.get("type") for device in devices}
    if display is None or not types or types.get(display) in DISPLAY_TYPES:
        return display
    screens = [did for did in activity.get("power_on_devices") or ()
               if types.get(did) in DISPLAY_TYPES]
    if screens:
        return screens[0]
    return display if types.get(display) in UNKNOWN_TYPES else None


def _key_commands(device: dict) -> dict[str, str]:
    """{key: command name} as the device's own command rows bind them."""
    out: dict[str, str] = {}
    for row in device.get("commands") or ():
        keys = row[4] if len(row) > 4 else None
        for key in keys if isinstance(keys, (list, tuple)) else [keys] if keys else ():
            out.setdefault(key, row[0])
    return out


def default_keys(activity: dict, kind: str, device: dict | None,
                 devices: list[dict] = ()) -> dict[str, list]:
    """The keys a layout binds when the project says nothing: each the device's own
    command for that key, where it has one."""
    if device is None:
        return {}
    if kind == "sound":
        wanted = VOLUME_KEYS
        if device.get("id") == layout_device(activity, "picture", devices):
            wanted += MENU_KEYS
    else:
        wanted = PICTURE_KEYS
    own = _key_commands(device)
    # a command of the key's own name that the device's rows put on no key: an imported
    # device's DirectionUp
    names = {row[0] for row in device.get("commands") or ()}
    own.update({key: key for key in wanted if key not in own and key in names})
    return {key: [["command", device["id"], own[key]]] for key in wanted if key in own}


@lru_cache(maxsize=None)
def _filed() -> dict[str, frozenset[str]]:
    data = json.loads(paths.library("layout-commands.json").read_text(encoding="utf-8"))
    return {kind: frozenset(data[kind]) for kind in KINDS}


def _plain(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def is_layout_command(kind: str, name: str) -> bool:
    """Whether a command of this name is one of a device's sound or picture settings."""
    return _plain(name) in _filed()[kind] or bool(BUTTON_WORDS[kind].search(name))


def default_buttons(kind: str, device: dict | None) -> list[list]:
    """The device's sound or picture settings that are on no key, as screen buttons."""
    if device is None:
        return []
    on_keys = set(_key_commands(device).values())
    out = []
    for row in device.get("commands") or ():
        name, label = row[0], (row[1] if len(row) > 1 and row[1] else row[0])
        if name not in on_keys and is_layout_command(kind, name):
            out.append([label, device["id"], name])
    return out


def _same_button(entry):
    """A screen button in one shape, to compare by: the editor's dict, or the
    ``[label, device, command(, icon)]`` the defaults are."""
    if isinstance(entry, (list, tuple)):
        return {"label": entry[0], "device": entry[1], "command": entry[2],
                **({"icon": entry[3]} if len(entry) > 3 and entry[3] else {})}
    return entry


def same_buttons(a, b) -> bool:
    """Whether two lists of screen buttons say the same, whatever shape each is in."""
    return [_same_button(x) for x in a or ()] == [_same_button(x) for x in b or ()]


def resolve(activity: dict, devices: list[dict], kinds=KINDS) -> dict[str, dict]:
    """Each layout the activity has: ``{"device", "hard_macros", "soft_buttons"}``,
    the project's choices over the defaults. A layout with no device is left out."""
    by_id = {device.get("id"): device for device in devices}
    stored_all = activity.get("layouts") or {}
    out = {}
    for kind in kinds:
        did = layout_device(activity, kind, devices)
        device = by_id.get(did)
        if device is None:
            continue
        stored = stored_all.get(kind) or {}
        keys = default_keys(activity, kind, device, devices)
        for key, macro in (stored.get("hard_macros") or {}).items():
            if macro:
                keys[key] = macro
            else:
                keys.pop(key, None)
        buttons = (stored["soft_buttons"] if "soft_buttons" in stored
                   else default_buttons(kind, device))
        out[kind] = {"device": did, "hard_macros": keys, "soft_buttons": list(buttons)}
    return out


def minimal(activity: dict, devices: list[dict], layouts: dict[str, dict]) -> dict:
    """``layouts`` (as `resolve` gives them, or as read from a configuration) as the
    project stores them: only what differs from the defaults. A kind missing from
    ``layouts`` is stored as having no device, unless its default has none either."""
    by_id = {device.get("id"): device for device in devices}
    # the defaults compared against are those of the layouts as given: Sound's menu keys
    # follow the Picture device it has, not the one it would have by default
    picture = (layouts.get("picture") or {}).get("device")
    given = dict(activity, layouts={"picture": {"device": picture}})
    out: dict[str, dict] = {}
    for kind in KINDS:
        layout = layouts.get(kind)
        default = default_device(activity, kind, devices)
        if layout is None:
            if by_id.get(default) is not None:
                out[kind] = {"device": None}
            continue
        did = layout["device"]
        entry: dict = {}
        if did != default:
            entry["device"] = did
        device = by_id.get(did)
        base = default_keys(given, kind, device, devices)
        keys = layout.get("hard_macros") or {}
        changed = {key: macro for key, macro in keys.items() if base.get(key) != macro}
        changed.update({key: [] for key in base if key not in keys})
        if changed:
            entry["hard_macros"] = changed
        buttons = list(layout.get("soft_buttons") or [])
        if not same_buttons(buttons, default_buttons(kind, device)):
            entry["soft_buttons"] = buttons
        if entry:
            out[kind] = entry
    return out
