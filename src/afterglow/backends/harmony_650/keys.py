"""The Harmony 650's physical keys: which scan code each key sends.

A project names keys the way every Harmony remote's software does - `VolumeUp`,
`DirectionLeft`, `Number7` - in a device command's hard slot and an activity's
`hard_macros`. The configuration binds them by scan code: a context or a mode list row
for key `0x80 | scan`. This is the one table between the two, and the keys the
firmware's flow owns rather than any device: the activity keys, Off, Help, the four keys
beside the screen, the centre key below it and the arrows either side of it.

The table is read off configurations, not a manual: a key that sends a device's
command is named by the code the device is sent, looked up in Logitech's own database, and
the firmware's own keys by the Tutorial screens that ask for them (docs/harmony_650_700/gspm.md,
"Pages").

Format reference: docs/harmony_650_700/gspm.md
"""
from __future__ import annotations

# Scan code by key name, for the keys that send a device's commands and the three the
# flow owns that a project's activities never bind: Activities, Off and Help.
SCANS = {
    "Help": 0x03, "Activities": 0x04, "Off": 0x06,
    "Menu": 0x0A, "Exit": 0x0C, "Red": 0x0D, "VolumeUp": 0x0E, "VolumeDown": 0x0F,
    "VolumeMute": 0x10, "Number4": 0x11, "Number7": 0x12, "NumberPlus": 0x13,
    "Number0": 0x14, "SkipBack": 0x15, "Rewind": 0x16, "Record": 0x17, "Number1": 0x18,
    "Yellow": 0x1C,
    "Blue": 0x1D, "FastForward": 0x1E, "ChannelUp": 0x1F, "ChannelDown": 0x20,
    "Guide": 0x21, "Info": 0x24, "Number6": 0x25, "Number3": 0x27, "Stop": 0x28,
    "DirectionRight": 0x29, "DirectionDown": 0x2A, "PrevChannel": 0x2B, "Play": 0x2C,
    "Number9": 0x2D, "Pause": 0x2E, "Number2": 0x2F, "Number5": 0x30, "Green": 0x31,
    "DirectionUp": 0x32, "Select": 0x33, "DirectionLeft": 0x34, "Number8": 0x35,
    "NumberEnter": 0x36, "SkipForward": 0x26, "UpArrow": 0x1A, "DownArrow": 0x1B,
}
ACTIVITIES, OFF, HELP = SCANS["Activities"], SCANS["Off"], SCANS["Help"]
# The keys that send a device's commands: everything but the three the flow owns.
COMMAND_KEYS = tuple(name for name, scan in SCANS.items()
                     if scan not in (ACTIVITIES, OFF, HELP))

# The four keys beside the screen, by the corner of the screen each one labels, then the
# centre key below it and the arrows either side of the centre key.
SCREEN_KEYS = {"top-left": 0x08, "top-right": 0x02, "bottom-left": 0x09,
               "bottom-right": 0x22}
CENTRE, PAGE_LEFT, PAGE_RIGHT = 0x19, 0x0B, 0x23
# The activity keys above the screen, by the button each is - Watch a Movie, Watch TV,
# Listen to Music - as every configuration measured binds them: a 700's "Watch Roku" on
# the key its owner calls Watch a Movie, a 665's "Radio" and a Dutch 650's "Radio FM" on
# the music key; Watch TV is the one the Tutorial asks for.
WATCH_TV = 0x05
ACTIVITY_BUTTONS = {"Movie": 0x01, "TV": WATCH_TV, "Music": 0x07}
ACTIVITY_KEYS = tuple(ACTIVITY_BUTTONS.values())


# Names a key's own command goes by in Logitech's database besides the key's: the digits
# are "1" to "0", mute is "Mute".
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
    """The key code of a named key, or None for a key the 650 does not have."""
    scan = SCANS.get(name)
    return None if scan is None else code(scan)


def name_of(key_code: int) -> str | None:
    """The name of the key a row binds by ``key_code``, or None for a code that is no
    named key - a key beside the screen, an event."""
    if not key_code & 0x80:
        return None
    return _NAMES.get(key_code & 0x7F)


_NAMES = {scan: name for name, scan in SCANS.items()}
