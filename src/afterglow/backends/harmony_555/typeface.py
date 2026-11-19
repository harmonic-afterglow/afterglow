"""The typeface a generated 5xx draws its text in, as the remote's glyphs.

Logitech's 5xx fonts are eleven rows a glyph: two rows above the capitals for accents,
seven of capitals from the third row, and two of descenders (docs/harmony_5xx/ahcm.md,
"Glyphs"). A build draws every font slot from Galmuri Afterglow 7 - the same seven-row
capitals, in the SIL Open Font License face the other remotes' scaffolds ship - placed on
that grid, and writes each glyph with the remote's own row encoding (pixels.encode_glyph).
A glyph's width is its advance, its gap to the next letter included, as Logitech's are.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ... import bdf
from . import pixels

FACE = "fonts/galmuri/GalmuriAfterglow7.bdf.gz"
SLOT_HEIGHT = 11
# the row under the capitals: a capital's lowest row is the one above it
BASELINE = 9
# The page counter's "n OF m" is drawn in a font eight rows high, its capitals from the
# top row, so it fits under a page's last line (y 56 to 63).
COUNTER_HEIGHT, COUNTER_BASELINE = 8, 7
# Galmuri draws 0 as it draws O. A text is read back by its glyphs' shapes, so a build's
# zero is slashed - the pixel font's usual one - and "GP0" reads back as it was typed.
# Pixels added, as (rows above the baseline, column).
MARKS = {"0": ((5, 2), (4, 1))}


class Typeface:
    def __init__(self, directory: Path):
        self.face = bdf.Bitmap.read(Path(directory) / FACE)

    def has(self, character: str) -> bool:
        return self.face.glyph(character) is not None

    def rows(self, character: str, height: int = SLOT_HEIGHT,
             baseline: int = BASELINE) -> list[list[int]]:
        """A character on the remote's eleven-row grid (or another), 1 for ink."""
        glyph = self.face.glyph(character)
        if glyph is None:
            raise ValueError(f"the typeface has no {character!r}")
        width = max(1, glyph["advance"])
        out = [[0] * width for _ in range(height)]
        for row_index, row in enumerate(glyph["rows"]):
            y = baseline - (glyph["y"] + glyph["height"] - row_index)
            if not 0 <= y < height:
                continue
            for column, pixel in enumerate(row):
                x = glyph["x"] + column
                if pixel and 0 <= x < width:
                    out[y][x] = 1
        for above, x in MARKS.get(character, ()):
            if 0 <= baseline - above < height:
                out[baseline - above][x] = 1
        return out

    def width(self, text: str) -> int:
        return sum(self.face.glyph(character)["advance"] if self.has(character) else 0
                   for character in text)

    def body(self, character: str, height: int = SLOT_HEIGHT,
             baseline: int = BASELINE) -> bytes:
        """The glyph as the remote stores it."""
        return pixels.encode_glyph(self.rows(character, height, baseline))


@lru_cache(maxsize=4)
def load(directory: str) -> Typeface:
    return Typeface(Path(directory))
