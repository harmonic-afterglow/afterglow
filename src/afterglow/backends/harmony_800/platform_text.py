"""The words on the firmware's own screens and in the status bar, drawn by each build.

The first forty screens of a Harmony 800 configuration belong to the firmware - the
battery warning, USB Connected, the update notices and thirty system messages - and the
status bar draws the clock as text. The scaffold carries their pictures and their logic
(platform/system-screens.json), but every piece of text in them is a ``label`` item that
names a message of the catalogue (catalogue.py), so no donor's words come along and they
follow the project's language. A build draws each label in its slot's font, placed by the
item's rule: centred on the screen, from a left edge, or against a right edge, as the
donors placed them. A notice translated into more or fewer lines is centred on the space
its English lines took.
"""
from __future__ import annotations

SCREEN_WIDTH = 176
LINE_SPACING = 12                  # a notice's lines, where the original had only one
TEXT_HEIGHT = 18                   # the 800's line spacing for its 18-pixel text (faces.py)
SOFTKEY_ROW = 195                  # where the One draws its softkeys' labels
TITLE_ROW = 30                     # and its titles, above
NOTICE_DROP = 6                    # the 800's taller text, clear of a notice's picture
# A notice's words may use the 800's whole display, which reaches this far either side of
# the One's screen it is placed in (geometry.ONE_ORIGIN), less a few pixels.
WIDE_MARGIN = 28
WIDE_ROOM = SCREEN_WIDTH + 2 * WIDE_MARGIN


def text(item: dict, words) -> str:
    """The words a ``label`` item stands for (one line of a notice: see ``lines``)."""
    key = item["key"]
    if key.startswith("screen-"):
        return lines(item, words)[item["line"]]
    if key == "ok":
        return words("system.ok")
    if key == "system-message":
        return words("system.message", number=item["value"])
    if key == "weekday":
        return words(f"clock.weekday.{item['value']}")
    if key == "hour":                     # the clock's hour runs 0-23; it shows 12-hour
        return f"{item['value'] % 12 or 12}:"
    if key == "minute":
        return f"{item['value']:02d}"
    raise ValueError(f"the platform screens name a label {key!r} the catalogue lacks")


def lines(item: dict, words) -> list[str]:
    return words(f"system.screen.{item['key'].split('-')[1]}").split("\n")


def render(model: dict, label, words=None) -> dict:
    """``model`` with every ``label`` item drawn: an attribute, then the text placed by its
    rule. ``label(text, attribute, room)`` gives the glyph codes (hex) and the width; with
    no ``label`` - an image built without fonts - the words are left out. ``words`` is the
    language (catalogue.Words), English when not given."""
    from .catalogue import ENGLISH

    words = ENGLISH if words is None else words
    blocks = []
    for block in model["blocks"]:
        out, font = [], None
        notice_ys = {}
        for item in block:
            if item.get("opcode") == "label" and item["key"].startswith("screen-"):
                notice_ys.setdefault(item["key"], []).append(item["y"])

        def draw(words_, item, y, x=None):
            nonlocal font
            # what a label is goes by where the One drew it: its title row, its softkey
            # row, or a notice between them, which may use the 800's whole width
            notice = TITLE_ROW <= item["y"] < SOFTKEY_ROW
            glyphs, width = label(words_, item["font"], WIDE_ROOM if notice else SCREEN_WIDTH)
            if x is None:
                x = {"centre": (SCREEN_WIDTH - width) // 2, "left": item.get("x", 0),
                     "right": item.get("x", SCREEN_WIDTH) - width}[item["align"]]
            if font != item["font"]:
                out.append({"opcode": "attribute", "value": item["font"]})
                font = item["font"]
            if item["y"] >= SOFTKEY_ROW:
                # the 800: a softkey's label goes to the foot of its display, centred over
                # its half of the bar (pages.py), not where the One drew it
                from .pages import SOFTKEY_Y, softkey_x
                half = 0 if max(0, x) + width // 2 < SCREEN_WIDTH // 2 else 120
                out.append({"opcode": "inline_text", "x": softkey_x(width, half),
                            "y": SOFTKEY_Y, "glyphs": glyphs, "native": True})
                return
            if item["y"] < TITLE_ROW:
                # a title: at the top of the 800's display, where every screen has its own
                out.append({"opcode": "inline_text", "x": max(0, x), "y": y,
                            "glyphs": glyphs, "native": True})
                return
            out.append({"opcode": "inline_text", "x": max(-WIDE_MARGIN, x), "y": y + NOTICE_DROP,
                        "glyphs": glyphs})

        for item in block:
            if item.get("opcode") == "attribute":
                font = item["value"]
            if item.get("opcode") != "label":
                out.append(item)
                continue
            if label is None:          # no fonts to draw with: the words are left out
                continue
            if item["key"].startswith("screen-"):
                # the whole notice is drawn at its first line, centred on the English lines
                if item["line"]:
                    continue
                ys = notice_ys[item["key"]]
                spacing = (max(ys) - min(ys)) // (len(ys) - 1) if len(ys) > 1 else LINE_SPACING
                # the 800's text is taller than the One's: its lines never overlap
                spacing = max(spacing, TEXT_HEIGHT)
                texts = lines(item, words)
                top = (min(ys) + max(ys)) // 2 - spacing * (len(texts) - 1) // 2
                for index, words_ in enumerate(texts):
                    draw(words_, item, top + spacing * index)
                continue
            draw(text(item, words), item, item["y"])
        blocks.append(out)
    return {**model, "blocks": blocks}
