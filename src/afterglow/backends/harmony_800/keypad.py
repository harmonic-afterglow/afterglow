"""The 800's number keypad: the remote has no number keys, so its 123 key opens a keypad on
the screen - in an activity, the digits of the device it changes channels on; on a device's
pages, that device's own.

A keypad is twelve places, 1 to 9 then +, 0 and E, as the 800's guide draws its keypad; a
place whose key the device lacks keeps its label and does nothing.
Back, the left softkey, and the 123 key go back to the pages it was opened from; Devices
opens the device list.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from . import geometry, keys
from .pages import (
    ACTIVITY_NUMPAD_FRAME, FIRST_BUTTON_KEY, KEYPAD_FONT, KEYPAD_TEXT_HEIGHT, NUMPAD_FRAME,
    NUMPAD_HEIGHT, NUMPAD_POSITIONS, NUMPAD_WIDTH, PAGE_ACTIVITIES_KEY, PAGE_DEVICES_KEY,
    SOFTKEY_LEFT_ZONE, SOFTKEY_RIGHT_ZONE, TEXT_HEIGHT, numpad_page)
from .structures import OBJECT_ATOM

NUMPAD = tuple(f"Number{digit}" for digit in range(1, 10)) + (
    "NumberPlus", "Number0", "NumberEnter")
# What each place reads: its digit, and + and E at the foot, as the 800's keypad has them.
LABELS = tuple(str(digit) for digit in range(1, 10)) + ("+", "0", "E")


def digits(device: dict) -> list[tuple]:
    """A device's keypad: for each of the twelve places ``(label, command)``, the command
    None for a key it lacks - or nothing at all for a device with no digits. A command
    fills a place when it was put on that key or is named for it ("1", "Enter") - hidden
    from the device's pages or not, as a command on a key is."""
    found = {}
    for command in device["commands"]:
        for name in NUMPAD:
            if name in (command.get("keys") or ()) or keys.is_own_command(name, command["name"]):
                found.setdefault(name, command)
    if not any(f"Number{digit}" in found for digit in range(10)):
        return []
    return [(label, found.get(name)) for name, label in zip(NUMPAD, LABELS)]


def screen(screens, places: list[tuple], *, title: str, kind: str, back: int,
           device_list: int):
    """Reserve and draw a keypad screen in ``screens``. ``places`` are its twelve
    ``(label, object)`` - the object a touch runs, None for a key the device lacks;
    ``back`` the screen Back and the 123 key return to, ``device_list`` Devices'."""
    layout = screens.layout
    rows, zones = [], []
    for slot, (_label, target) in enumerate(places):
        if target is None:
            continue
        key = FIRST_BUTTON_KEY + slot
        rows.append((key, target, OBJECT_ATOM))
        x, y = NUMPAD_POSITIONS[slot]
        zones.append(geometry.pixels(x, y, NUMPAD_WIDTH, NUMPAD_HEIGHT, key & 0x7F))
    rows.append((PAGE_ACTIVITIES_KEY, layout.navigation(back), OBJECT_ATOM))
    rows.append((PAGE_DEVICES_KEY, layout.navigation(device_list), OBJECT_ATOM))
    zones += [dict(SOFTKEY_LEFT_ZONE, tag=PAGE_ACTIVITIES_KEY & 0x7F),
              dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F)]
    labels = [label for label, _target in places]
    # an activity's keys in the activities' colour, a device's in the devices'
    role = ACTIVITY_NUMPAD_FRAME if kind == "activity" else NUMPAD_FRAME
    if role not in screens.roles:
        role = NUMPAD_FRAME

    # the digits in the keypad's large font, where the image has it
    large = KEYPAD_FONT < len(screens.fonts or ()) and \
        screens.fonts[KEYPAD_FONT].get("height") == KEYPAD_TEXT_HEIGHT
    attribute = KEYPAD_FONT if large else screens.label

    def program(picture, prologue):
        frame = picture(role) if role in screens.roles else None
        built = numpad_page(labels, frame, screens.fonts[attribute], prologue=prologue,
                            attribute=attribute,
                            text_height=KEYPAD_TEXT_HEIGHT if large else TEXT_HEIGHT)
        return screens.softkeys(built, ["back", "devices"])
    # both softkeys lit, Back and Devices: in the activities' colour or the devices'
    lit = "activity-both" if kind == "activity" else kind
    screens.owned(rows, zones, program, lit, title, keys=opener(layout, back))


def with_opener(rows: list[tuple], layout, ordinal: int) -> list[tuple]:
    """``rows`` with the 123 key opening screen ``ordinal`` in place of any row of theirs
    for the same key - a list binds each key once."""
    opening = opener(layout, ordinal)
    taken = {row[0] for row in opening}
    return [row for row in rows if row[0] not in taken] + opening


def opener(layout, ordinal: int) -> list[tuple]:
    """The 123 key's row, opening screen ``ordinal``."""
    return [(keys.code(keys.NUMBERS), layout.navigation(ordinal), OBJECT_ATOM)]
