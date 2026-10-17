"""What every generated Harmony 800 image takes from the remote's platform layer.

A build generates everything from the project, but a few things are the firmware's, not
the configuration's: the screen ordinals it reserves for its own notices, and the
sections every image measured holds byte for byte. They are recorded here, with the
evidence, rather than copied from a donor.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from . import activity_index, gspm, structures
from .structures import COMPARE, ENTER_MODE, OBJECT_ATOM, object_body


# A screen's ordinal is not free: the firmware selects its own screens by index, and the
# first forty belong to it. Both household donors draw the same text with the same
# instruction shape in all forty - 40 of 40 - and nothing an owner owns appears before
# ordinal 40 in one or 44 in the other. They are notices and diagnostics: the battery
# warning and the charging-problem screen with their OK buttons, "Learning...", "Update
# in progress", and then the thirty messages the factory configuration also carries,
# among them "Invalid Configuration" and "Configuration Corrupted" - the two the remote
# would use to say it had rejected a configuration.
#
# A generated image that starts its own screens at ordinal 0 is therefore not merely
# missing them; its first command page stands where the low-battery notice belongs.
#
# They are the vendor's own work and delivered rather than dumped: both donor containers
# carry `TRANSFERTYPE Winsock`, post to members.harmonyremote.com, hold one payload
# member and match their own checksum. And they are structurally constant without being
# byte-constant - the same text and instruction shape in all forty, at the same addresses,
# but only 2 of the 40 programs identical, because each points at pictures and glyph
# strings that sit elsewhere in each configuration. Carrying them means carrying a model
# and linking it, not copying a blob.
#
# `generate.build` does exactly that: it emits them at ordinals 0 to 39 from the
# scaffold's `platform/system-screens.json`, and a project's own screens start at 40.
SYSTEM_SCREENS = 40

# Section 16 indexes section 15's tail at these offsets: the 800's own tables, from a
# factory remote's /cfg/usercfg (platform/platform.json, "properties") - but for tables
# 6 and 7, the battery's levels, which are the One's (docs/harmony_800/gsgd.md, "Battery
# levels").
SECTION_16_OFFSETS = (0, 3, 16, 19, 28, 31, 40, 73, 106, 109, 114)

# Sections whose bytes are identical in all four images measured.
# The 800's own, from a factory remote's /fw/embeddedcfg (platform/platform.json).
CONSTANT_SECTIONS = {
    1: bytes.fromhex("1212560d000000"),
    2: bytes.fromhex("00000300003d000040"),
    17: bytes.fromhex("00"),
    18: bytes.fromhex("0000"),
}
HEADER_SIZE = 0x68

# The factory image counts 2 buttons where every household one counts 55.
HOUSEHOLD_BUTTONS = 55

# What follows the count is mode 0's own list - mode 0 is the "battery level is low"
# screen - and the firmware reads it at that fixed place. Every Harmony One user
# configuration carries these same 55 entries: an event code, then instruction 0x7F
# calling the object numbered by the entry's position. 52 are key presses; the entries
# at 7, 9 and 46 (codes 06, 07 and 2D) are mode events, not keys. Writing the count
# without the entries had the firmware read whatever came next as this list.
MODE_ZERO_EVENTS = bytes.fromhex(
    "89 88 8b 8a 8d 8c 8f 06 8e 07 81 83 82 85 84 87 86 98 99 9a 9b 9c 9d 9e 9f 90 91 92 "
    "93 94 95 96 97 ab a8 af ae ad ac a3 a2 a1 a0 a7 a6 a5 2d a4 b2 b3 b0 b1 b7 b4 b5")


# So objects 0 to 54 are mode 0's handlers, and the image's own objects start after
# them. In the user configurations they do nothing - three empty atoms, a deliberate
# swallow - except event 2D, which draws the status overlays as the platform screens do.
MODE_ZERO_REDRAW = 46

# second, minute, hour, day, month, year - the day and month counting from zero.
DEFAULT_STAMP = (0, 0, 0, 0, 0, 2024)

# Section 14 opens with the same clock section 3 holds: seven properties whose limits are
# 59, 59, 23, 30, 6, 11 and a year, and whose initial values are the timestamp's fields.
# All five images measured agree on all seven, so a generated image keeps them in step.
CLOCK_LIMITS = (59, 59, 23, 30, 6, 11)


def _wrap(operand, category: int = 0x1F) -> dict:
    """A transition taken whenever a property wraps back to zero, from any state."""
    return {"flags": 0, "from": activity_index.ANY_STATE, "to": 0,
            "operand": operand, "category": category}


# The clock carries: a minute wrapping runs `0xf202`, an hour wrapping runs an object of
# `0xf203` and `0xf204`, a day `0xf205` and a month `0xf206`. The factory image and both
# donors carry exactly these four, so they are the firmware's and not a configuration's.
# An operand given as atoms is an object the build places and replaces with its index.
CLOCK_CARRIES = {
    1: [_wrap(0xF202)],
    2: [_wrap({"atoms": [(0xF203, 0x1F), (0xF204, 0x1F)]}, 0x7F)],
    3: [_wrap(0xF205)],
    5: [_wrap(0xF206)],
}

# Section 14's properties 7 to 17, as `(initial, limit)`: identical in the factory image
# and both donors except property 14, which is (0, 1) in the factory image and (2, 4) in
# both donors. The donors' value is taken, since the platform screens are theirs too.
# The 800's (its /fw/embeddedcfg): twelve, not the One's eleven, and records 11 and 14 differ.
PLATFORM_RECORDS = ((0, 2), (0, 3), (5, 7), (0, 7), (0, 28), (0, 1), (1, 1), (0, 1),
                    (0, 3), (0, 1), (0, 3), (0, 1))


def clock_records(second: int, minute: int, hour: int, day: int, month: int,
                  year: int) -> list[dict]:
    """Section 14's first seven properties, holding the same time section 3 does."""
    weekday = structures.stamp_weekday(day, month, year)
    values = (second, minute, hour, day, weekday, month)
    records = [
        {"initial": value, "limit": limit, "padding": 0,
         "transitions": [dict(row) for row in CLOCK_CARRIES.get(index, ())]}
        for index, (value, limit) in enumerate(zip(values, CLOCK_LIMITS))
    ]
    # The year's limit is one past the year it holds in every image measured.
    records.append({"initial": year - 2000, "limit": year - 2000 + 1,
                    "padding": 0, "transitions": []})
    return records


def engine_records(*stamp_fields) -> list[dict]:
    """The whole of section 14 a configuration without activities has.

    The clock, the platform's own properties, then the terminator - nineteen records,
    which is what the factory image holds. Property ids are positions, so a firmware
    reading a platform property by id reads past the table if any of them is missing.
    """
    records = clock_records(*stamp_fields)
    records += [{"initial": initial, "limit": limit, "padding": 0, "transitions": []}
                for initial, limit in PLATFORM_RECORDS]
    records.append({"initial": 0, "limit": activity_index.TERMINATOR_LIMIT,
                    "padding": 0, "transitions": []})
    return records


PLATFORM_TAIL = "platform/platform.json"
PLATFORM_TAIL_SIZE = 131


def platform_tail(directory=None) -> bytes:
    """The 800's property tables section 16 indexes - battery thresholds and the like,
    measured rather than derivable."""
    from ... import paths
    directory = paths.scaffolds("harmony-800") if directory is None else directory
    properties = json.loads((Path(directory) / PLATFORM_TAIL).read_text())["properties"]
    if tuple(properties["tables"]) != SECTION_16_OFFSETS:
        raise ValueError("the scaffold's property tables are not where section 16 points")
    tail = bytes.fromhex(properties["tail"])
    if len(tail) != PLATFORM_TAIL_SIZE:
        raise ValueError(
            f"{PLATFORM_TAIL} is {len(tail)} bytes; section 15's table is "
            f"{PLATFORM_TAIL_SIZE}")
    return tail




def mode_zero_list() -> bytes:
    """Mode 0's 55 entries: each event calls the object numbered by its position."""
    return b"".join(struct.pack("<HHB", structures.tag(code), index, OBJECT_ATOM)
                    for index, code in enumerate(MODE_ZERO_EVENTS))


def header(buttons: int = HOUSEHOLD_BUTTONS) -> bytearray:
    """An image's header: the magic, the constant, the `LWJL` button count, and - in a
    household image - mode 0's list, which the firmware reads at that fixed place."""
    out = bytearray(HEADER_SIZE)
    out[0:4] = gspm.MAGIC
    struct.pack_into("<I", out, 8, gspm.HEADER_CONSTANT)
    out[gspm.BUTTON_MAP_OFFSET:gspm.BUTTON_MAP_OFFSET + 4] = gspm.BUTTON_MAP_MAGIC
    out[gspm.BUTTON_MAP_OFFSET + 4] = buttons
    if buttons == HOUSEHOLD_BUTTONS:
        out += mode_zero_list()
    return out


# Section 9 opens with the image's own action list, `u8 count; {u16 operand; u8 opcode}`,
# and only then the page registers. The firmware runs it to start the image: in the factory
# image it is `[0x7F 0]`, and object 0 pushes context 0 onto the key stack, enters the
# "update settings" home screen, and shows USB CONNECTED when variable 0x10 is set. All
# four household images name an object of the same shape, ending in the same USB check.
# Without it the firmware read the first page register as this list.
PUSH_CONTEXT = 0xFE00    # `0x1F` band FE: push a section-10 context; FD names the mode
PUSH_CURRENT_MODE = 0xFEFD

# `3F F0xx` writes the firmware's setting 0 (10 at reset), which the 800's handbook reads
# as the timers' unit; the factory image and every donor set it to 100 first thing.
TIMER_UNIT = (0xF064, 0x3F)
LOAD_ONE = 0xFB01        # `0x1F` band FB: load the byte register
USB_CONNECTED = 0x10     # the state variable the USB check compares

# The platform screen that says USB CONNECTED: mode 1 in both donors, whose screens the
# scaffold carries, and mode 28 in the factory image.
USB_SCREEN = 1


def startup_objects(home: int, usb_screen: int | None, first: int,
                    idle: dict | None = None, select: int | None = None) -> list[bytes]:
    """The objects the image's start-up list runs, numbered from ``first``.

    The factory image's three, in its own shape: push the image's context and then the
    current mode, so a key is looked up in the mode before the context, enter ``home``,
    and then, in a list of its own because a failed comparison ends the list it is in,
    enter ``usb_screen`` if the remote is on USB.

    With the idle layer, as upstairs starts: the screen timer, the flag resets, then the
    event context, the current mode and the key light on top - so every key lights the
    keypad on its way down - then the light and sound set-up, and only then ``home``:
    the set-up clears the zone flags, which entering a screen sets.
    ``idle`` gives those as `{"resets": [...], "setup": [...]}`, instructions. The
    stack is every donor's: the events, `0xFE`, the current mode, `0xFC`, the key light.
    ``select`` is a context to select last - Off's, so the remote starts with nothing
    running, as every donor starts. Selecting it enters ``home`` itself, so the start-up
    then does not: on the 800 a screen takes most of a second to draw, and entering it
    twice showed as the Activities menu drawn, cleared and drawn again.
    """
    head = [(PUSH_CONTEXT, 0x1F), (PUSH_CURRENT_MODE, 0x1F), (home, ENTER_MODE), TIMER_UNIT]
    if idle is not None:
        head = ([TIMER_UNIT] + list(idle["resets"])
                + [(PUSH_CONTEXT | EVENT_CONTEXT, 0x1F), (PUSH_CONTEXT | 0xFE, 0x1F),
                   (PUSH_CURRENT_MODE, 0x1F), (PUSH_CONTEXT | 0xFC, 0x1F),
                   (PUSH_CONTEXT | KEY_LIGHT_CONTEXT, 0x1F)]
                + list(idle["setup"]))
        head.append((home, ENTER_MODE) if select is None else (0xFF00 | select, 0x1F))
    if usb_screen is None:
        return [object_body(head)]
    return [
        object_body(head + [(first + 1, OBJECT_ATOM)]),
        object_body([(LOAD_ONE, 0x1F), (first + 2, OBJECT_ATOM)]),
        object_body([(USB_CONNECTED, COMPARE), (usb_screen, ENTER_MODE)]),
    ]


# The idle layer's contexts, after the image's own (0): events, then the key light. The
# charge contexts the firmware looks up under 0xFC are 0 - the image's own, as in every
# donor - and the two after the key light.
EVENT_CONTEXT, KEY_LIGHT_CONTEXT = 1, 2
CHARGE_CONTEXTS = {"normal": 0, "usb": 3, "low": 4}

# Mode 0's three events, by their position in its list.
MODE_ZERO_EVENT_AT = {0x06: 7, 0x07: 9, 0x2D: MODE_ZERO_REDRAW}
ENTER, LEAVE, REDRAW = 0x06, 0x07, 0x2D


def platform_object(value, first: int):
    """A platform model's operand: an object it names, a timer, or a literal.

    The platform's timers are the image's section 13 in model order, so a timer's index
    is its model index and the operand is the band that starts or stops it.
    """
    if isinstance(value, dict) and "timer" in value:
        return (value["band"] << 8) | value["timer"]
    if isinstance(value, dict) and "charge" in value:
        return (value["band"] << 8) | CHARGE_CONTEXTS[value["charge"]]
    return first + value["object"] if isinstance(value, dict) else value


def mode_zero_handler(index: int, platform: dict[int, int] | None = None) -> bytes:
    """What mode 0 does for its entry ``index``, as the user configurations have it.

    The three events call the platform's own mode 0 handlers when a build carries them;
    every key entry does nothing, three empty atoms, a deliberate swallow.
    """
    for tag, at in MODE_ZERO_EVENT_AT.items():
        if index == at and platform and tag in platform:
            return object_body([(platform[tag], OBJECT_ATOM)])
    if index == MODE_ZERO_REDRAW:
        return object_body([(1, 0x73), (3, 0x73), (2, 0x73)])
    return object_body([(0, 0), (0, 0), (0, 0)])


def _strips() -> list[dict]:
    from . import geometry
    return [dict(strip, tag=tag, native=True) for tag, strip in geometry.STRIPS.items()]


def touch_templates(directory=None) -> dict[int, list[dict]]:
    """The panel geometry a page of a given button count uses: on the 800 made from its
    own layout (pages.py) - a zone over each button, tagged as the One tags them, the two
    softkeys and the strips - where the One carries its donors' templates."""
    from . import geometry
    from .pages import (BUTTON_POSITIONS, FIRST_BUTTON_KEY, FRAME_HEIGHT, FRAME_WIDTH,
                        SOFTKEY_LEFT_ZONE, SOFTKEY_RIGHT_ZONE)
    out = {}
    for count in range(1, len(BUTTON_POSITIONS) + 1):
        zones = [geometry.pixels(x, y, FRAME_WIDTH, FRAME_HEIGHT,
                                 (FIRST_BUTTON_KEY & 0x7F) + index)
                 for index, (x, y) in enumerate(BUTTON_POSITIONS[:count])]
        zones += [dict(SOFTKEY_LEFT_ZONE, tag=0x2B), dict(SOFTKEY_RIGHT_ZONE, tag=0x2C)]
        out[count] = zones + _strips()
    return out


# Donor menu rows end with `(1, 0x99)`, which looked like a constant marker. Opcodes from
# 0x80 write variable `opcode & 0x7f`, so it sets the donor's own variable 25, whose
# meaning and range differ from donor to donor; a generated image has no variable 25.


def menu_template(directory=None) -> list[dict]:
    """The device menu's touch geometry: on the 800 its four rows (pages.py), the bottom
    left softkey the One's menu template has (tag 0x33), and the strips."""
    from . import geometry
    from .pages import (FRAME_HEIGHT, MENU_FRAME_XY, MENU_ROW_KEYS, ROW_FRAME_WIDTH,
                        SOFTKEY_LEFT_ZONE)
    zones = [geometry.pixels(x, y, ROW_FRAME_WIDTH, FRAME_HEIGHT, key & 0x7F)
             for (x, y), key in zip(MENU_FRAME_XY, MENU_ROW_KEYS)]
    return zones + [dict(SOFTKEY_LEFT_ZONE, tag=0x33)] + _strips()


def platform_table(entries: list[int], tail: bytes) -> bytes:
    """Section 15: a count of pointers, then the platform table section 16 indexes."""
    if len(entries) > 0xFF:
        raise ValueError("section 15 counts at most 255 entries")
    return (bytes([len(entries)])
            + b"".join((gspm.BASE + offset).to_bytes(3, "little") for offset in entries)
            + tail)


def platform_index(tail_offset: int) -> bytes:
    """Section 16: eleven pointers into section 15's tail, at the measured offsets."""
    return (bytes([len(SECTION_16_OFFSETS)])
            + b"".join((gspm.BASE + tail_offset + offset).to_bytes(3, "little")
                       for offset in SECTION_16_OFFSETS))
