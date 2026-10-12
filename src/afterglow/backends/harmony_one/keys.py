"""The Harmony One's physical keys: which scan code each key sends.

A project names keys the way every Harmony remote's software does - `VolumeUp`,
`DirectionLeft`, `Number7` - in a device command's hard slot and an activity's
`hard_macros`. The configuration binds them by scan code: a context or a mode list row
for key `0x80 | scan`. This is the one table between the two, and the three keys the
firmware's flow owns rather than any device: Activities, Off and Help.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

# Scan code by key name, for the 40 keys of the keypad.
SCANS = {
    "Number4": 1, "Exit": 2, "VolumeUp": 3, "VolumeDown": 4, "Rewind": 5, "SkipBack": 6,
    "Record": 7, "Number1": 8, "VolumeMute": 9, "Info": 10, "DirectionLeft": 11,
    "NumberPlus": 12, "NumberEnter": 13, "Number0": 14, "Number9": 15, "Number8": 16,
    "Number6": 17, "Guide": 18, "ChannelUp": 19, "ChannelDown": 20, "FastForward": 21,
    "SkipForward": 22, "Stop": 23, "Number3": 24, "Number5": 25, "DownArrow": 26,
    "DirectionUp": 27, "Select": 28, "DirectionDown": 29, "Play": 30, "Pause": 31,
    "Number2": 32, "DirectionRight": 33, "Activities": 34, "PrevChannel": 35,
    "UpArrow": 36, "Off": 37, "Help": 38, "Number7": 39, "Menu": 40,
}
ACTIVITIES, OFF, HELP = SCANS["Activities"], SCANS["Off"], SCANS["Help"]
# The keys that send a device's commands: everything but the three the flow owns.
COMMAND_KEYS = tuple(name for name, scan in SCANS.items()
                     if scan not in (ACTIVITIES, OFF, HELP))


# Names a key's own command goes by in Logitech's database besides the key's: the digits
# are "1" to "0", mute is "Mute" (gspm.md, "A page you can press").
_OWN_NAMES = {**{f"Number{digit}": (str(digit),) for digit in range(10)},
              "VolumeMute": ("Mute",), "NumberEnter": ("Enter",)}


def is_own_command(key: str, command: str) -> bool:
    """Whether ``command`` is the one ``key`` is for - VolumeUp on VolumeUp, 1 on Number1,
    a device's NextTrack on SkipForward - rather than one put on it in its place, as
    Return on Exit is. Logitech's device pages leave out only the first kind."""
    from ...project_devices import KEY_STAND_INS

    return (command == key or command in _OWN_NAMES.get(key, ())
            or command in KEY_STAND_INS.get(key, ()))


def code(scan: int) -> int:
    """The key code a list or context row binds a scan code by."""
    return 0x80 | scan


def by_name(name: str) -> int | None:
    """The key code of a named key, or None for a key the One does not have."""
    scan = SCANS.get(name)
    return None if scan is None else code(scan)


def name_of(key_code: int) -> str | None:
    """The name of the key a row binds by ``key_code``, or None for a code that is no
    key - a touch zone, an event."""
    if not key_code & 0x80:
        return None
    return _NAMES.get(key_code & 0x7F)


_NAMES = {scan: name for name, scan in SCANS.items()}
