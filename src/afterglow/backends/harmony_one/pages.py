"""How a generated Harmony One draws a page: labels fitted to their room, button and menu
pages, softkeys, titles and counters, at the places every donor draws them.

These return drawing programs (drawing.py) and never place anything; the screens that use
them are laid out by layout.py.

Format reference: docs/harmony_one/generating.md
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from . import drawing


# Where the six command buttons sit, in reading order, and how far below a button's top
# its label's baseline falls. Both measured across every command page in the donors.
BUTTON_POSITIONS = ((6, 38), (89, 38), (6, 92), (89, 92), (6, 146), (89, 146))
LABEL_BASELINE = 20

# The first of the six touch keys; a page's buttons take consecutive codes from here.
FIRST_BUTTON_KEY = 0xB0

# A label too wide for its place is wrapped onto two lines, as the donors draw one: the
# lines sit 6 pixels either side of a menu row's baseline (51 and 63 for 57) and at 5 above
# and 6 below a button's (53 and 64 for 58).
MENU_LINE_OFFSETS = (-6, 6)
BUTTON_LINE_OFFSETS = (-5, 6)
ELLIPSIS = ".."

# A pad's label as Logitech's compiler lays it out on a device page and an activity's
# screen (Danny Bloe's harmony-explorations, architectures/harmony-one/compiler.md, "a
# pad's label"): split into words at spaces, before a capital, digit or "+" after a lower
# case letter, and after a single hyphen; lines filled greedily to 72 pixels, a lone word
# up to 73 and a wider one cut with ".." on its own line; at most three lines, 11 apart
# and centred on the pad's label row - 20, or 15 and 26, or 9, 20 and 31.
PAD_ROOM, PAD_LONE_ROOM, PAD_LINES = 72, 73, 3
PAD_LINE_OFFSETS = (-11, 0, 11)
_PAD_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z0-9+])|(?<=[^-]-)(?=[^-])")


def measure(font: dict):
    metrics = font.get("metrics") or font["glyphs"]
    widths = {code: item["width"] for code, item in metrics.items()}
    codes = {item["char"]: code for code, item in metrics.items() if item["char"]}
    return widths, codes


def fit_label(label: str, font: dict, room: int, lines: int = 2) -> list[bytes]:
    """A label as the glyph lines that fit ``room`` pixels, at most ``lines`` of them.

    Words wrap at spaces; a word wider than a line on its own is split where it stops
    fitting. What still does not fit after the last line is cut, and the cut is marked
    with two full stops when the font has them, so a long name is shortened rather than
    refused or drawn past its frame, which nothing in the format clips.
    """
    widths, codes = measure(font)
    missing = sorted(set(label) - set(codes))
    if missing:
        raise ValueError(
            f"this font cannot draw {', '.join(repr(item) for item in missing)}")

    def width(text):
        return sum(widths[codes[character]] for character in text)

    # Each line remembers how it joins the one before: a space, or nothing where a word
    # was split, so what is cut after the last line reads as the label did.
    out, line, joins = [], "", []
    words = [(word, " ") for word in label.split()]
    while words:
        word, join = words.pop(0)
        candidate = f"{line} {word}" if line else word
        if width(candidate) <= room:
            if not line:
                joins.append(join)
            line = candidate
            continue
        if line:
            out.append(line)
            line = ""
            words.insert(0, (word, join))
            continue
        # One word wider than a whole line: take as much of it as fits.
        cut = 1
        while cut < len(word) and width(word[:cut + 1]) <= room:
            cut += 1
        out.append(word[:cut])
        joins.append(join)
        if word[cut:]:
            words.insert(0, (word[cut:], ""))
    if line:
        out.append(line)
    if len(out) > lines:
        rest = out[lines - 1] + "".join(
            join + text for join, text in zip(joins[lines:], out[lines:]))
        mark = ELLIPSIS if all(character in codes for character in ELLIPSIS) else ""
        while rest and width(rest.rstrip() + mark) > room:
            rest = rest[:-1]
        out = out[:lines - 1] + [rest.rstrip() + mark]
    # what the font was asked to draw - the whole label, since its characters are checked
    # before it is cut, and the cut's mark - so a build can carry exactly those glyphs
    font.setdefault("drawn", set()).update(label, *out)
    return [drawing.GlyphCodes.of(codes[character] for character in text) for text in out]


def line_ys(baseline: int, count: int, offsets: tuple[int, int]) -> list[int]:
    return [baseline] if count == 1 else [baseline + offset for offset in offsets[:count]]


def pad_words(label: str) -> list[tuple[str, str]]:
    """A pad label's words as Logitech's compiler splits them, each with what joins it
    to the one before: a space, or nothing where a word was split."""
    out = []
    for word in re.split(r"[ \t\n]+", label):
        if word:
            parts = _PAD_SPLIT.split(word)
            out += [(parts[0], " ")] + [(part, "") for part in parts[1:]]
    return out


def pad_label(label: str, font: dict) -> list[bytes]:
    """A pad's label as Logitech lays it out (PAD_ROOM): its glyph lines, one to
    three."""
    widths, codes = measure(font)
    missing = sorted(set(label) - set(codes))
    if missing:
        raise ValueError(
            f"this font cannot draw {', '.join(repr(item) for item in missing)}")

    def width(text):
        return sum(widths[codes[character]] for character in text)
    mark = ELLIPSIS if all(character in codes for character in ELLIPSIS) else ""

    def cut(text, room):
        while text and width(text + mark) > room:
            text = text[:-1]
        return text + mark
    out, joins, line = [], [], ""
    for word, join in pad_words(label):
        candidate = line + join + word if line else word
        if line and width(candidate) <= PAD_ROOM:
            line = candidate
            continue
        if line:
            out.append(line)
        joins.append(join)
        if width(word) <= PAD_LONE_ROOM:
            line = word
        else:                                     # too wide even alone: cut, on its own
            out.append(cut(word, PAD_LONE_ROOM))
            line = ""
    if line:
        out.append(line)
    if len(out) > PAD_LINES:
        rest = out[PAD_LINES - 1] + "".join(
            join + text for join, text in zip(joins[PAD_LINES:], out[PAD_LINES:]))
        out = out[:PAD_LINES - 1] + [cut(rest, PAD_ROOM)]
    font.setdefault("drawn", set()).update(label, *out)
    return [drawing.GlyphCodes.of(codes[character] for character in text) for text in out]


def button_page(labels: list[str], frames: list[int], font: dict, *,
                prologue: int | None = None, backdrop: int | None = None,
                attribute: int = 0, frame_width: int | None = None) -> list[dict]:
    """The drawing program for a page of command buttons.

    Each button is its frame and then its label, centred over the frame the way every
    donor page centres one: the label's x is the midpoint of the frame less half the
    text's width. A label wraps as Logitech's does (pad_label). A place whose
    frame is None is a gap: nothing is drawn there. A button with an icon has it drawn
    on its frame (pictures.button_picture), and its label over it like any other's.
    """
    if len(labels) != len(frames):
        raise ValueError("a page needs one frame per label")
    if len(labels) > len(BUTTON_POSITIONS):
        raise ValueError(
            f"a page holds at most {len(BUTTON_POSITIONS)} buttons, not {len(labels)}")
    widths, _codes = measure(font)
    out = []
    if prologue is not None:
        out.append({"opcode": "call", "target": prologue})
    # Nothing in the format clears the screen, so a page that draws no backdrop leaves
    # whatever the last one drew underneath its buttons.
    if backdrop is not None:
        out.append({"opcode": "bitmap", "x": 0, "y": 0, "target": backdrop})
    # A label is measured in one font, so it has to be drawn in that font: the drawing
    # VM draws text in whichever attribute was set last, and a page that sets none draws
    # in whatever the previous program left behind. Every donor page sets it explicitly.
    out.append({"opcode": "attribute", "value": attribute})
    for index, (label, frame) in enumerate(zip(labels, frames)):
        if frame is None:          # a gap: the place is left empty
            continue
        left, top = BUTTON_POSITIONS[index]
        out.append({"opcode": "bitmap", "x": left, "y": top, "target": frame})
        frame_width = FRAME_WIDTH if frame_width is None else frame_width
        if label is None:          # a picture that says it all: a favourite's logo
            continue
        lines = (pad_label(label, font) if frame_width == FRAME_WIDTH
                 else fit_label(label, font, frame_width))
        offsets = PAD_LINE_OFFSETS if len(lines) == PAD_LINES else BUTTON_LINE_OFFSETS
        for glyphs, y in zip(lines, line_ys(top + LABEL_BASELINE, len(lines), offsets)):
            width = sum(widths[code] for code in glyphs)
            out.append({
                "opcode": "inline_text",
                "x": (2 * left + frame_width - width) // 2,
                "y": y,
                "glyphs": glyphs.hex(),
            })
    out.append({"opcode": "end"})
    return out


FRAME_WIDTH = 81

# The softkeys, as upstairs draws them in the bottom strip of the screen (raw touch
# coordinates, y measured upwards): Options or Activities on the left, Devices on the
# right, each label in its own font - the attribute numbers are upstairs', which the
# scaffold's fonts keep.
SOFTKEY_LEFT_ZONE = {"x": 1257, "width": 1395, "y": 271, "height": 1001}
SOFTKEY_RIGHT_ZONE = {"x": 2406, "width": 1150, "y": 271, "height": 1001}
SOFTKEYS = {"options": (22, 202), "activities": (16, 202), "devices": (110, 202),
            "commands": (16, 202), "favourites": (16, 202), "exit": (142, 202),
            # Help's and the Remote Assistant's answers, as upstairs draws them
            "yes": (32, 201), "no": (125, 201), "ok": (124, 201)}


SOFTKEY_FONTS = {"options": 13, "activities": 6, "devices": 9, "commands": 6,
                 "favourites": 6, "exit": 15, "yes": 1, "no": 1, "ok": 1}


# The keys each screen binds them to, as upstairs does: the Activities screen's softkeys
# are its 0x30 and 0x31 zones, the device list's Activities is its template's 0x33, and a
# command page's are 0x2B and 0x2C.
HOME_OPTIONS_TAG, HOME_DEVICES_TAG = 0x30, 0x31
SOFTKEY_RIGHT_KEY = 0x80 | HOME_DEVICES_TAG
MENU_ACTIVITIES_KEY = 0xB3

# The Activities menu, which has both softkeys besides its rows, as upstairs' has.
MENU_OPTIONS_KEY, MENU_DEVICES_KEY = 0xB3, 0xB4
PAGE_ACTIVITIES_KEY, PAGE_DEVICES_KEY = 0xAB, 0xAC

# The Options screen, as upstairs draws it: its row frames at the menu rows, labels centred
# on them in its row font (attribute 5). Screen Sounds' label reads its flag: 0 offers to
# turn the sounds off, 1 to turn them on.
OPTIONS_FONT = 5
OPTIONS_FRAME_WIDTH = 164
OPTIONS_LABEL_ROOM = OPTIONS_FRAME_WIDTH - 8


def picture_size(body: bytes) -> tuple[int, int]:
    """A stored picture's width and height, from its header."""
    return struct.unpack_from("<HH", body, 1)


SOFTKEY_HALF = 88           # half the One's 176-pixel display


def softkey_x(width: int, x: int) -> int:
    """A softkey's label centred over its half of the bar - the left half for a label
    Logitech starts in it, else the right - which is where Logitech's own English sits,
    and lets a longer word use the whole half, as on the 800."""
    start = 0 if x < SOFTKEY_HALF else SOFTKEY_HALF
    return start + max(0, (SOFTKEY_HALF - width) // 2)


def softkey_label(text: str, font: dict, attribute: int, xy) -> list[dict]:
    """A softkey's label: one line in its own font, cut to the half-strip it sits in and
    centred on it."""
    lines = fit_label(text, font, SOFTKEY_HALF - 4, lines=1)
    widths, _codes = measure(font)
    width = sum(widths[code] for code in lines[0])
    return [{"opcode": "attribute", "value": attribute},
            {"opcode": "inline_text", "x": softkey_x(width, xy[0]), "y": xy[1],
             "glyphs": lines[0].hex()}]


# A screen's title and page counter, as every donor draws them: the title at (6,4) in a
# title font, a paged screen's total at (23,18) followed by the word, and each page's
# number right-aligned against the slash at (18,18), in a smaller font of the same colour.
# Which fonts follow the screen: cyan for Activities, green for Options, orange for the
# device screens.
TITLE_XY = (6, 4)
# what the status bar leaves of the top line: its icons start at x 128 (drawing.md, "the
# status bar"), the clock is on the line below
TITLE_ROOM = 120
PAGE_COUNTER_Y = 18
PAGE_TOTAL_XY = (23, 18)
PAGE_SLASH_XY = (18, 18)
PAGES_GAP = 5
TITLE_FONTS = {"activities": (10, 12), "options": (2, 7), "devices": (3, 4),
               "commands": (3, 4), "commands-paged": (3, 4),
               "activity": (10, 12), "activity-paged": (10, 12), "help": (2, 7),
               "activity-both": (10, 12), "activity-both-paged": (10, 12),
               "question": (2, 7), "tutorial": (2, 7)}


# The device menu: three rows a page, each a full-width frame, a device icon and a label,
# with the row's touch key opening that device's first command page. Geometry measured on
# every donor and identical across them.
MENU_ROWS_PER_PAGE = 3
MENU_FRAME_XY = ((6, 38), (6, 92), (6, 146))
MENU_ICON_XY = ((11, 39), (11, 93), (11, 147))
MENU_LABEL_XY = ((63, 57), (63, 111), (63, 165))
MENU_ROW_KEYS = (0xB0, 0xB1, 0xB2)

# The two side-strip touch zones every screen template carries, used here to move between
# a device's command pages and between menu pages. Their tags are 0x2e and 0x2f.
SIDE_PREV_KEY = 0xAE
SIDE_NEXT_KEY = 0xAF


def menu_page(labels: list[str], frame: int, icons: list[int], font: dict, *,
              prologue: int | None = None, backdrop: int | None = None,
              attribute: int = 0, label_room: int | None = None,
              rows=None) -> list[dict]:
    """The drawing program for a page of device-menu rows.

    Each row is the full-width frame, the device's icon, and its name on the frame's
    baseline. A name too wide for the row wraps onto a second line. ``rows`` are the
    row places to draw in, the first ones when not given.
    """
    if len(labels) > MENU_ROWS_PER_PAGE:
        raise ValueError(
            f"a menu page holds {MENU_ROWS_PER_PAGE} rows, not {len(labels)}")
    out = []
    if prologue is not None:
        out.append({"opcode": "call", "target": prologue})
    if backdrop is not None:
        out.append({"opcode": "bitmap", "x": 0, "y": 0, "target": backdrop})
    out.append({"opcode": "attribute", "value": attribute})
    places = range(len(labels)) if rows is None else rows
    for index, label, icon in zip(places, labels, icons):
        out.append({"opcode": "bitmap", "x": MENU_FRAME_XY[index][0],
                    "y": MENU_FRAME_XY[index][1], "target": frame})
        if icon is not None:
            out.append({"opcode": "bitmap", "x": MENU_ICON_XY[index][0],
                        "y": MENU_ICON_XY[index][1], "target": icon})
        lines = fit_label(label, font, MENU_LABEL_MAX if label_room is None else label_room)
        x, baseline = MENU_LABEL_XY[index]
        for glyphs, y in zip(lines, line_ys(baseline, len(lines), MENU_LINE_OFFSETS)):
            out.append({"opcode": "inline_text", "x": x, "y": y, "glyphs": glyphs.hex()})
    out.append({"opcode": "end"})
    return out


# What an image with no devices shows on the screen it boots into.
SCREEN_WIDTH = 176
EMPTY_MESSAGE_WIDTH = SCREEN_WIDTH - 12
EMPTY_MESSAGE_Y = 111

# A device row's label starts at x=63 on a 176-wide screen, so it has this much room.
MENU_LABEL_MAX = 176 - 63

# What the starting and Help screens draw, and where, as every donor's draw them: the
# starting screen's name in attribute 11, the rest in attribute 0, lines 12 apart.
START_FONT, HELP_FONT = 11, 0
START_TEXT_Y, START_KEEP_TOP = 124, 179
HELP_TOP, HELP_KEEP_TOP, HELP_SENDING_XY = 43, 162, (57, 95)
QUESTION_TOP = 70
LINE_SPACING = 12
# Help's questions and the Remote Assistant's notes, as upstairs lays them out: the
# activity's icon where its starting screen has it, a question under it, Help's first
# question higher with its explanation below; the Remote Assistant's heading and note in
# the middle of an otherwise empty screen.
HELP_QUESTION_Y, HELP_PROMPT_Y, ASSISTANT_Y = 137, 119, 99


def labeller(fonts: list[dict]):
    """``label(text, attribute, room)``: one line of text in the image's font of that
    attribute, as glyph codes (hex) and its width, cut to ``room`` pixels; with ``lines``,
    the text wrapped onto that many at most, a (codes, width) pair for each."""
    def label(text, attribute, room, lines=1):
        found = fit_label(text, fonts[attribute], room, lines=lines)
        widths, _codes = measure(fonts[attribute])
        out = [(glyphs.hex(), sum(widths[code] for code in glyphs)) for glyphs in found]
        return out[0] if lines == 1 else out
    return label


@dataclass
class Frames:
    """The frames a scaffold draws buttons and rows on: a button frame per position,
    the widest one's width, and the room a row's label has on the row frame."""
    buttons: list[str]
    width: int = FRAME_WIDTH
    row_label_room: int = MENU_LABEL_MAX


def frames(pictures) -> Frames:
    """The scaffold's frames, checked against the places they are drawn in. Pictures may
    be redrawn at another size, but not moved: labels are fitted to the frames as drawn,
    and a frame too big for its place is refused."""
    roles = set(pictures) if isinstance(pictures, dict) else set()
    out = Frames([f"button-frame/{index}" for index in range(len(BUTTON_POSITIONS))])
    if all(role in roles for role in out.buttons):
        sizes = {picture_size(pictures[role]) for role in out.buttons}
        out.width = max(width for width, _height in sizes)
        room = (BUTTON_POSITIONS[1][0] - BUTTON_POSITIONS[0][0],
                BUTTON_POSITIONS[2][1] - BUTTON_POSITIONS[0][1])
        for width, height in sizes:
            if width > room[0] or height > room[1]:
                raise ValueError(f"a button frame is {width}x{height}; a button has "
                                 f"{room[0]}x{room[1]} before it reaches the next one")
    if "row-frame" in roles:
        width, height = picture_size(pictures["row-frame"])
        if MENU_FRAME_XY[0][0] + width > SCREEN_WIDTH or \
                height > MENU_FRAME_XY[1][1] - MENU_FRAME_XY[0][1]:
            raise ValueError(f"the menu row frame is {width}x{height}, which does not fit "
                             "its row")
        out.row_label_room = min(MENU_LABEL_MAX,
                                 MENU_FRAME_XY[0][0] + width - MENU_LABEL_XY[0][0])
    return out
