"""Draw an arch-9 screen as the remote does: a 96 x 64 picture, one 8-row band at a time.

A 5xx page program selects a band (`16 r`), draws into it - pictures copied by region,
text glyph by glyph - and sends it to the display (`17`). A draw reaches only the band
selected, so a line that crosses two bands is drawn in each; one drawn in only one shows
half its height on the remote (docs/harmony_5xx/ahcm.md, "Pages"). This renderer keeps
that rule rather than drawing whole glyphs, so a missing band shows here as it would on
the remote.

Glyphs are two bits a pixel: ink sets a pixel and paper clears it. Pictures are one bit a
pixel, copied as they are.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

from . import font_index, pixels, ui_index

WIDTH, HEIGHT, BAND = 96, 64, 8


class Fonts:
    """An image's fonts as drawn: glyph rows of 0 (paper), 1 (ink) and 2 (untouched)."""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.fonts = {font["attribute"]: font for font in font_index.fonts(payload)}
        self.cache: dict[tuple[int, int], list[list[int]] | None] = {}

    def glyph(self, attribute: int, code: int) -> list[list[int]] | None:
        key = (attribute, code)
        if key not in self.cache:
            glyph = self.fonts.get(attribute, {}).get("glyphs", {}).get(code)
            if glyph is None:
                self.cache[key] = None
            else:
                rows = _glyph_rows(self.payload, glyph["pointer"] - _base())
                self.cache[key] = rows
        return self.cache[key]


def _base() -> int:
    from . import gspm
    return gspm.BASE


def _glyph_rows(payload: bytes, offset: int) -> list[list[int]]:
    """A glyph's rows: 1 ink, 0 paper (glyph_mask reads paper and ink alike as drawn)."""
    rows, _size = ui_index.glyph_mask(payload, offset)
    return [[1 if value else 0 for value in row] for row in rows]


def blank() -> list[list[int]]:
    return [[0] * WIDTH for _ in range(HEIGHT)]


def render(payload: bytes, program: int, fonts: Fonts | None = None, *,
           canvas: list[list[int]] | None = None, depth: int = 8) -> list[list[int]]:
    """The screen ``program`` draws, as rows of 0 and 1."""
    fonts = fonts or Fonts(payload)
    canvas = canvas if canvas is not None else blank()
    state = {"band": None, "attribute": 0}
    _run(payload, program, fonts, canvas, state, depth)
    return canvas


def _run(payload, program, fonts, canvas, state, depth):
    if depth < 0:
        raise ValueError("drawing programs jump too deep")
    listing = ui_index.drawing_program(payload, program, limit=4000)
    for item in listing["instructions"]:
        kind = item["opcode"]
        if kind == "row":
            state["band"] = item["value"]
        elif kind == "attribute":
            state["attribute"] = item["value"]
        elif kind == "sized_bitmap":
            sx, sy = bytes.fromhex(item["reserved"])
            _copy(payload, item["target"], sx, sy, item["x"], item["y"],
                  item["width"], item["height"], canvas, state["band"])
        elif kind == "bitmap":
            picture = pixels.decode_picture(payload, item["target"])
            _copy(payload, item["target"], 0, 0, item["x"], item["y"],
                  picture["width"], picture["height"], canvas, state["band"])
        elif kind in ("text", "inline_text"):
            codes = bytes.fromhex(item["glyphs"])
            _text(fonts, state["attribute"], codes, item["x"], item["y"], canvas,
                  state["band"])
        elif kind == "jump":
            _run(payload, item["target"], fonts, canvas, state, depth - 1)
    if listing["stopped"] not in ("end", "jump"):
        raise ValueError(f"drawing program {program:#x} stops at {listing['stopped']}")


def _in_band(y: int, band: int | None) -> bool:
    return 0 <= y < HEIGHT and (band is None or band * BAND <= y < band * BAND + BAND)


def _copy(payload, target, sx, sy, dx, dy, width, height, canvas, band):
    picture = pixels.decode_picture(payload, target)
    for row in range(height):
        y = dy + row
        if not _in_band(y, band) or not 0 <= sy + row < picture["height"]:
            continue
        source = picture["rows"][sy + row]
        for column in range(width):
            x = dx + column
            if 0 <= x < WIDTH and 0 <= sx + column < picture["width"]:
                canvas[y][x] = source[sx + column]


def _text(fonts, attribute, codes, x, y, canvas, band):
    for code in codes:
        rows = fonts.glyph(attribute, code)
        if rows is None:
            continue
        for row_index, row in enumerate(rows):
            if not _in_band(y + row_index, band):
                continue
            for column, value in enumerate(row):
                if 0 <= x + column < WIDTH:
                    canvas[y + row_index][x + column] = value
        x += len(rows[0]) if rows else 0


def screen(payload: bytes, ordinal: int, page: int = 0, fonts: Fonts | None = None
           ) -> list[list[int]]:
    """Screen ``ordinal``'s page ``page``, drawn."""
    slots = ui_index.screen_slots(payload)[ordinal]["slots"]
    return render(payload, slots[page]["program_offset"], fonts)
