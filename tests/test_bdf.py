"""The standard-library BDF reader."""

from __future__ import annotations

import gzip

import pytest

from afterglow import bdf

FONT = """STARTFONT 2.1
FONT -test-Tiny-Regular
SIZE 8 75 75
FONTBOUNDINGBOX 5 9 0 -2
STARTPROPERTIES 2
FONT_ASCENT 7
CAP_HEIGHT 7
ENDPROPERTIES
CHARS 2
STARTCHAR H
ENCODING 72
DWIDTH 6 0
BBX 5 7 0 0
BITMAP
88
88
88
F8
88
88
88
ENDCHAR
STARTCHAR g
ENCODING 103
DWIDTH 5 0
BBX 4 6 0 -2
BITMAP
70
90
90
70
10
E0
ENDCHAR
ENDFONT
"""


def test_a_glyph_is_its_pixels_its_advance_and_its_place_against_the_baseline(tmp_path):
    path = tmp_path / "tiny.bdf.gz"
    path.write_bytes(gzip.compress(FONT.encode()))
    font = bdf.Bitmap.read(path)
    assert font.cap_height() == 7
    h = font.glyph("H")
    assert (h["advance"], h["width"], h["height"], h["y"]) == (6, 5, 7, 0)
    assert h["rows"][3] == [True] * 5 and h["rows"][0] == [True, False, False, False, True]
    g = font.glyph("g")
    assert g["y"] == -2 and g["rows"][-1] == [True, True, True, False]
    assert font.glyph("Z") is None


def test_something_that_is_not_bdf_is_refused(tmp_path):
    path = tmp_path / "not.bdf"
    path.write_bytes(b"\x00\x01\x00\x00")
    with pytest.raises(ValueError, match="not a BDF"):
        bdf.Bitmap.read(path)
