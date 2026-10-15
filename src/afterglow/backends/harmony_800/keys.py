"""The Harmony 800's physical keys: which scan code each key sends.

A project names keys the way every Harmony remote's software does - `VolumeUp`,
`DirectionLeft`, `Select` - in a device command's hard slot and an activity's
`hard_macros`. The configuration binds them by scan code: a context or a mode list row
for key `0x80 | scan`, which the firmware posts as the list tag `0xC000 | scan` when the
key goes down (structures.tag). This is the one table between the two, and the four keys
the remote keeps for itself rather than give any device: Activities, Off, Help and 123,
and Mouse, which turns the display into a touchpad once Afterglow drives that.

The codes are the ones asdfgpio's 800 named on the key test (key_test.py), 2026-10-15. The
800 has no number keys - its 123 key opens a keypad on the screen (keypad.py) - and keys
the One lacks: TV, DVR, Mouse, and Back, Home and PIP on the bottom row, named as
Logitech's database names the commands they are for. The slide-out keyboard sends
`0xC4xx` and is not here yet.

Format reference: docs/harmony_800/gsgd.md
"""
from __future__ import annotations

# Scan code by key name, for the 35 keys of the front panel.
SCANS = {
    "Back": 0x01, "Record": 0x02, "SkipBack": 0x03, "Rewind": 0x04, "Exit": 0x05,
    "Guide": 0x06, "VolumeMute": 0x07, "Home": 0x08, "Pause": 0x09, "Play": 0x0A,
    "DownArrow": 0x0B, "UpArrow": 0x0C, "DirectionDown": 0x0D, "Select": 0x0E, "PIP": 0x0F,
    "Stop": 0x10, "SkipForward": 0x11, "FastForward": 0x12, "Menu": 0x13, "Info": 0x14,
    "PrevChannel": 0x15, "TV": 0x16, "Activities": 0x17, "VolumeUp": 0x18, "Off": 0x19,
    "VolumeDown": 0x1A, "Numbers": 0x1B, "DirectionLeft": 0x1C, "ChannelDown": 0x1D,
    "DVR": 0x1E, "ChannelUp": 0x1F, "Help": 0x20, "DirectionUp": 0x21, "Mouse": 0x22,
    "DirectionRight": 0x23,
}
ACTIVITIES, OFF, HELP = SCANS["Activities"], SCANS["Off"], SCANS["Help"]
# The 123 key, which opens the number keypad of the activity or device on screen.
NUMBERS = SCANS["Numbers"]
# Mouse: kept for the touchpad, so no command is put on it.
MOUSE = SCANS["Mouse"]
# The keys the flow owns, and those that send a device's commands: every other one.
FLOW = (ACTIVITIES, OFF, HELP, NUMBERS, MOUSE)
COMMAND_KEYS = tuple(name for name, scan in SCANS.items() if scan not in FLOW)


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
    """The key code of a named key, or None for a key the 800 does not have."""
    scan = SCANS.get(name)
    return None if scan is None else code(scan)


def name_of(key_code: int) -> str | None:
    """The name of the key a row binds by ``key_code``, or None for a code that is no
    key - a touch zone, an event."""
    if not key_code & 0x80:
        return None
    return _NAMES.get(key_code & 0x7F)


_NAMES = {scan: name for name, scan in SCANS.items()}
