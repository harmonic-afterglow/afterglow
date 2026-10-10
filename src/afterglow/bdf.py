"""Read a BDF bitmap font, gzipped or not, with the standard library.

A pixel font is best kept as what it is - bitmaps - rather than as outlines that have to
be filled back into the same pixels, and BDF is the plain-text format such fonts are
published in. This reads the glyphs a caller asks for, each as rows of on/off pixels with
its advance and its place against the baseline, plus the font's cap height. A font is
indexed once and a glyph parsed when it is first wanted, so a font with tens of thousands
of characters costs little when an image needs a hundred of them.

Nothing here knows about any remote.
"""
from __future__ import annotations

import gzip
from pathlib import Path


class Bitmap:
    """One BDF font: which characters it has and each one's pixels."""

    def __init__(self, text: str):
        self.text = text
        self.properties: dict[str, str] = {}
        self.index: dict[int, int] = {}        # code point -> offset of its STARTCHAR
        self._glyphs: dict[int, dict] = {}
        at = 0
        header_end = text.find("STARTCHAR")
        for line in text[:header_end].splitlines():
            name, _space, value = line.partition(" ")
            self.properties[name] = value.strip().strip('"')
        while True:
            start = text.find("STARTCHAR", at)
            if start < 0:
                break
            encoding = text.find("ENCODING", start)
            end = text.find("\n", encoding)
            code = int(text[encoding + 8:end].split()[0])
            if code >= 0:
                self.index[code] = start
            at = end
        if not self.index:
            raise ValueError("this BDF font has no characters")

    @classmethod
    def read(cls, path) -> "Bitmap":
        data = Path(path).read_bytes()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        if not data.startswith(b"STARTFONT"):
            raise ValueError("this is not a BDF font")
        return cls(data.decode("utf-8", "replace"))

    def cap_height(self) -> int:
        if "CAP_HEIGHT" in self.properties:
            return int(self.properties["CAP_HEIGHT"])
        glyph = self.glyph("H")
        return glyph["height"] + glyph["y"] if glyph else int(self.properties["FONT_ASCENT"])

    def glyph(self, char: str) -> dict | None:
        """``{"advance", "x", "y", "width", "height", "rows"}``: the bitmap's offset from the
        origin and its rows of booleans top first, ``y`` the bottom row's height above
        the baseline; None for a character the font lacks."""
        code = ord(char)
        if code not in self.index:
            return None
        if code not in self._glyphs:
            start = self.index[code]
            end = self.text.find("ENDCHAR", start)
            advance, box, rows, in_bitmap = 0, (0, 0, 0, 0), [], False
            for line in self.text[start:end].splitlines():
                if in_bitmap:
                    rows.append(line.strip())
                elif line.startswith("DWIDTH"):
                    advance = int(line.split()[1])
                elif line.startswith("BBX"):
                    box = tuple(int(value) for value in line.split()[1:5])
                elif line.startswith("BITMAP"):
                    in_bitmap = True
            width, height, x, y = box
            bits = [[bool(int(row, 16) >> (len(row) * 4 - 1 - column) & 1)
                     for column in range(width)] for row in rows[:height] if row]
            self._glyphs[code] = {"advance": advance, "x": x, "y": y, "width": width,
                                  "height": height, "rows": bits}
        return self._glyphs[code]
