"""Glyphs for the Harmony One's font slots, drawn from a font face.

A Harmony One stores every glyph it draws in the configuration, in eighteen slots that are
Logitech's few typefaces in many colours: an 11-pixel slot for the clock and counters,
14-, 15- and 16-pixel slots for everything else, each one colour over a one-pixel shadow
down and to the right. A build fills each slot from a font face - the scaffold's default
(Galmuri, a bitmap font) or the owner's own TrueType font - in the slot's colours, on the
baseline Logitech's fonts of that height use. A bitmap or pixel TrueType font is drawn
one font pixel a screen pixel; any other TrueType font is scaled to the slot's cap height.

Pure standard library.
"""
from __future__ import annotations

# Where a scaffold's owner may put a TrueType font that replaces the default face in every
# slot, and optionally a smaller one for the 11-pixel slots (the clock, page counters).
TYPEFACE = "fonts/font.ttf"
SMALL_TYPEFACE = "fonts/font-small.ttf"
SMALL_SLOT = 11
INK = 0.5            # a pixel at least this covered is drawn; the display cannot blend

# Each slot height's baseline (the row a capital stands on, from the top) and the cap
# height an outline font is scaled to, as Logitech's fonts of that height have them.
SLOTS = {11: {"baseline": 9, "cap": 7}, 14: {"baseline": 11, "cap": 8},
         15: {"baseline": 12, "cap": 9}, 16: {"baseline": 12, "cap": 9}}

# The characters every slot carries unless a build says which: printable ASCII, numbered
# from 1. Every word an image draws is set by its build, so the codes are the build's to
# choose (gspm.md, "Words are the build's own, and so are the font codes").
REPERTOIRE = tuple(chr(code) for code in range(0x20, 0x7F))


def _place(cells, height, width, colour, shadow):
    """Pixels at ``cells`` (row, column) in ``colour``, each with its shadow, in a glyph
    ``width`` wide; what falls outside is cut."""
    cells = [(y, x) for y, x in cells if 0 <= y < height and 0 <= x < width]
    out = [[None] * width for _ in range(height)]
    if shadow is not None:
        for y, x in cells:
            if y + 1 < height and x + 1 < width:
                out[y + 1][x + 1] = tuple(shadow)
    for y, x in cells:
        out[y][x] = tuple(colour)
    return {"width": width, "rows": out}


def bitmap_glyph(face, char: str, height: int, colour, shadow=None) -> dict | None:
    """``char`` from a bitmap font (afterglow.bdf) for a slot ``height`` pixels tall, on
    the slot's baseline and exactly its advance wide; None when the font lacks it."""
    glyph = face.glyph(char)
    if glyph is None or height not in SLOTS:
        return None
    top = SLOTS[height]["baseline"] - (glyph["y"] + glyph["height"])
    cells = [(top + r, glyph["x"] + c) for r, line in enumerate(glyph["rows"])
             for c, on in enumerate(line) if on]
    return _place(cells, height, max(1, glyph["advance"]), colour, shadow)


def typeface_glyph(face, char: str, height: int, colour, shadow=None) -> dict | None:
    """``char`` from a TrueType ``face`` (afterglow.ttf) for a slot ``height`` pixels
    tall, on the slot's baseline and exactly its advance wide - the joins of a script meet
    their neighbours rather than being cut by a gap; None when the face lacks it."""
    from ...ttf import coverage

    glyph = face.glyph(char)
    if glyph is None or height not in SLOTS:
        return None
    slot = SLOTS[height]
    # A pixel font - outlines on a grid of square pixels - is drawn at its own size, one
    # grid square a pixel, so it stays crisp; any other face is scaled to the cap height.
    grid = pixel_grid(face)
    scale = 1 / grid if grid else slot["cap"] / face.cap_height()
    width = max(1, round(face.advance(glyph) * scale))
    grid_cover = coverage(face.contours(glyph), scale, 0, slot["baseline"], width, height)
    cells = [(y, x) for y, line in enumerate(grid_cover) for x, value in enumerate(line)
             if value >= INK]
    return _place(cells, height, width, colour, shadow)


def face_glyph(face, char: str, height: int, colour, shadow=None) -> dict | None:
    """A glyph from whichever kind of font ``face`` is: bitmap (BDF) or TrueType."""
    if hasattr(face, "index"):
        return bitmap_glyph(face, char, height, colour, shadow)
    return typeface_glyph(face, char, height, colour, shadow)


def pixel_grid(face) -> int | None:
    """The font units a pixel spans when TrueType ``face`` is a pixel font - every point
    of its letters on one coarse grid - or None for an ordinary outline font."""
    if hasattr(face, "_pixel_grid"):
        return face._pixel_grid
    import math

    grid = 0
    for char in "HAgox":
        index = face.glyph(char)
        if index is None:
            continue
        for contour in face.contours(index):
            for x, y in contour:
                if x != int(x) or y != int(y):
                    grid = 1
                    break
                grid = math.gcd(grid, int(x), int(y))
    # a grid finer than a thirtieth of the em is an outline font's own precision
    face._pixel_grid = grid if grid and face.units_per_em / grid <= 30 else None
    return face._pixel_grid
