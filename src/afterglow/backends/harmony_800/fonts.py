"""Fonts a generated Harmony 800 image draws its text with, from the scaffold's bitmap face.

A font is one colour at one height. Each glyph is the bitmap face's character scaled by a
whole number - the face was drawn for a smaller screen - and stored as rows of runs: the
pixels that are ink, and the ones that are left alone. A text's codes are 1-based glyph
indexes into its font, so the build chooses them: printable ASCII, then whatever else the
image's labels use, in the order they first appear.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

REPERTOIRE = tuple(chr(code) for code in range(0x20, 0x7F))
MISSING = "?"


@dataclass
class Font:
    """``height`` rows tall; ``glyphs`` the encoded glyphs in code order (code 1 first)."""

    height: int
    colour: int
    scale: int
    characters: list[str] = field(default_factory=list)
    glyphs: list[bytes] = field(default_factory=list)
    widths: list[int] = field(default_factory=list)

    def code(self, char: str) -> int:
        try:
            return self.characters.index(char) + 1
        except ValueError:
            return self.characters.index(MISSING) + 1

    def codes(self, text: str) -> list[int]:
        return [self.code(char) for char in text]

    def width(self, text: str) -> int:
        return sum(self.widths[code - 1] for code in self.codes(text))

    def record(self, glyph_addresses: list[int]) -> bytes:
        """The section-7 font: height, glyph count, an absolute pointer per glyph."""
        out = bytearray([self.height]) + struct.pack("<H", len(glyph_addresses))
        for address in glyph_addresses:
            out += address.to_bytes(3, "little")
        return bytes(out)


def _runs(row: list[bool], colour: int) -> bytes:
    out = bytearray()
    x = 0
    while x < len(row):
        ink = row[x]
        n = 1
        while x + n < len(row) and row[x + n] == ink and n < 0x7F:
            n += 1
        if ink:
            out.append(n)
            out += struct.pack(">H", colour) * n
        else:
            out.append(0x80 | n)
        x += n
    return bytes(out) + b"\x80"


def encode_glyph(rows: list[list[bool]], colour: int) -> bytes:
    """``{width, rows of runs, 00}`` for a glyph whose rows are all one width."""
    width = len(rows[0]) if rows else 0
    if not 1 <= width <= 0xFF or any(len(row) != width for row in rows):
        raise ValueError("a glyph's rows must be one width between 1 and 255")
    return bytes([width]) + b"".join(_runs(row, colour) for row in rows) + b"\x00"


def glyph_rows(face, char: str, scale: int) -> list[list[bool]] | None:
    """``char`` from a BDF ``face`` (afterglow.bdf) on the face's own line, scaled."""
    glyph = face.glyph(char)
    if glyph is None:
        return None
    ascent = int(face.properties.get("FONT_ASCENT", face.cap_height()))
    descent = int(face.properties.get("FONT_DESCENT", 0))
    height, width = ascent + descent, max(1, glyph["advance"])
    grid = [[False] * width for _ in range(height)]
    top = ascent - (glyph["y"] + glyph["height"])
    for r, line in enumerate(glyph["rows"]):
        for c, on in enumerate(line):
            y, x = top + r, glyph["x"] + c
            if on and 0 <= y < height and 0 <= x < width:
                grid[y][x] = True
    return [[cell for cell in row for _ in range(scale)] for row in grid for _ in range(scale)]


def build(face, *, scale: int, colour: int, extra: str = "") -> Font:
    """A font of ``face`` with printable ASCII and the characters in ``extra``."""
    characters = list(REPERTOIRE)
    for char in extra:
        if char not in characters and face.glyph(char) is not None:
            characters.append(char)
    font = Font(height=0, colour=colour, scale=scale)
    for char in characters:
        rows = glyph_rows(face, char, scale)
        if rows is None:
            continue
        font.characters.append(char)
        font.glyphs.append(encode_glyph(rows, colour))
        font.widths.append(len(rows[0]))
        font.height = len(rows)
    if MISSING not in font.characters:
        raise ValueError(f"the font face has no {MISSING!r} to stand in for a missing character")
    return font
