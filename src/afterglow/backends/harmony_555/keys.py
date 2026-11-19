"""The Harmony 5xx's keys: the firmware's own, and how a model's command keys are named.

A configuration binds keys by scan code - a context or a key register row for key
`0x80 | scan` - and every 5xx scans one grid of 8 x 8 positions. The keys the firmware's
flow owns sit on the same scan codes on every model: the four soft keys beside the
screen, the two page keys, Help, Devices, Off and Activities. They are this module's.

Which command key a scan code is, is not. The 550 and the 555 bind the same scan codes
under different labels, and the 510 swaps two of the 525's, so each model's profile
names its command keys (`vocabulary.hard_key_scans`, name: scan code), measured from what
Logitech's compiler bound there in the model's configurations.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

# The four keys beside the screen, by the corner of the screen each one labels
# (Danny Bloemendaal, harmony-explorations; harmony-decompiler's 525 presses).
SCREEN_KEYS = {"top-left": 39, "top-right": 38, "bottom-left": 31, "bottom-right": 30}
# The page keys: the firmware turns a page on an action that names one, and every model
# binds that action to these two at the bottom of its context stack.
PAGE_FORWARD, PAGE_BACK = 22, 23
HELP, DEVICES, OFF, ACTIVITIES = 46, 47, 54, 55
FLOW = {"Help": HELP, "Devices": DEVICES, "Off": OFF, "Activities": ACTIVITIES}
# A code the platform's idle key set binds to a routine of its own and no configuration
# of the 21 binds to a command - not a command key, whatever it is on the face.
FIRMWARE_ONLY = (42,)
# A 5xx has no key that starts one activity.
ACTIVITY_BUTTONS: dict[str, int] = {}


def code(scan: int) -> int:
    """The key code a list or context row binds a scan code by."""
    return 0x80 | scan


class Keypad:
    """One model's keys by name: its profile's command keys and the firmware's own."""

    def __init__(self, scans: dict[str, int] | None = None):
        self.scans = {**dict(scans or {}), **FLOW}
        if len(set(self.scans.values())) != len(self.scans):
            raise ValueError("two keys of one keypad share a scan code")
        self._names = {scan: name for name, scan in self.scans.items()}

    @classmethod
    def of(cls, profile) -> "Keypad":
        vocabulary = getattr(profile, "vocabulary", None) or {}
        return cls(vocabulary.get("hard_key_scans"))

    def by_name(self, name: str) -> int | None:
        """The key code of a named key, or None for a key this model does not have."""
        scan = self.scans.get(name)
        return None if scan is None else code(scan)

    def name_of(self, key_code: int) -> str | None:
        """The name of the key a row binds by ``key_code``, or None for a code that is no
        named key - a key beside the screen, an event, a key not yet identified."""
        if not key_code & 0x80:
            return None
        return self._names.get(key_code & 0x7F)


def is_own_command(key: str, command: str) -> bool:
    """Whether ``command`` is the one ``key`` is for - VolumeUp on VolumeUp, 1 on Number1,
    a device's NextTrack on SkipForward - rather than one put on it in its place."""
    from ...project_devices import KEY_STAND_INS

    own = {**{f"Number{digit}": (str(digit),) for digit in range(10)},
           "VolumeMute": ("Mute",), "NumberEnter": ("Enter",)}
    return (command == key or command in own.get(key, ())
            or command in KEY_STAND_INS.get(key, ()))
