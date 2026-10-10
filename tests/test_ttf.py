"""The standard-library TrueType reader, against fonts built here byte by byte."""

from __future__ import annotations

import struct

import pytest

from afterglow import ttf


def _table_font(glyphs: dict[str, tuple[int, list[list[tuple[int, int, bool]]]]],
                units: int = 1000, cap: int | None = None) -> bytes:
    """A minimal TrueType font: ``glyphs`` maps a character to its advance and contours of
    ``(x, y, on_curve)`` points. Glyph 0 is an empty .notdef."""
    chars = sorted(glyphs)
    bodies = [b""]
    for char in chars:
        _advance, contours = glyphs[char]
        points = [p for contour in contours for p in contour]
        if not points:
            bodies.append(b"")
            continue
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        ends, total = [], 0
        for contour in contours:
            total += len(contour)
            ends.append(total - 1)
        body = struct.pack(">hhhhh", len(contours), min(xs), min(ys), max(xs), max(ys))
        body += struct.pack(f">{len(ends)}H", *ends) + struct.pack(">H", 0)
        body += bytes(1 if on else 0 for _x, _y, on in points)
        for axis in (0, 1):
            last = 0
            for point in points:
                body += struct.pack(">h", point[axis] - last)
                last = point[axis]
        bodies.append(body + b"\x00" * (len(body) % 2))
    glyf, loca, at = b"", [], 0
    for body in bodies:
        loca.append(at)
        glyf += body
        at += len(body)
    loca.append(at)
    count = len(bodies)
    head = struct.pack(">IIIIHH", 0x10000, 0x10000, 0, 0x5F0F3CF5, 0, units)
    head += b"\x00" * 16 + struct.pack(">hhhhHHhhh", 0, 0, units, units, 0, 8, 2, 1, 0)
    hhea = struct.pack(">I", 0x10000) + struct.pack(">hhh", units, -200, 0) + b"\x00" * 24
    hhea += struct.pack(">H", count)
    maxp = struct.pack(">IH", 0x5000, count)
    hmtx = struct.pack(">HH", 500, 0) + b"".join(
        struct.pack(">Hh", glyphs[c][0], 0) for c in chars)
    # cmap format 4: one segment per character, then the closing 0xFFFF segment
    codes = [ord(c) for c in chars] + [0xFFFF]
    segments = len(codes)
    sub = struct.pack(">HHHHHHH", 4, 0, 0, 2 * segments, 0, 0, 0)
    sub += struct.pack(f">{segments}H", *codes) + b"\x00\x00"
    sub += struct.pack(f">{segments}H", *codes)
    sub += struct.pack(f">{segments}H", *[(i + 1 - code) & 0xFFFF if code != 0xFFFF else 1
                                          for i, code in enumerate(codes)])
    sub += struct.pack(f">{segments}H", *([0] * segments))
    sub = sub[:2] + struct.pack(">H", len(sub)) + sub[4:]
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + sub
    tables = {"cmap": cmap, "glyf": glyf, "head": head, "hhea": hhea, "hmtx": hmtx,
              "loca": struct.pack(f">{len(loca)}I", *loca), "maxp": maxp}
    if cap is not None:
        tables["OS/2"] = struct.pack(">H", 2) + b"\x00" * 86 + struct.pack(">h", cap) + b"\x00" * 8
    out = struct.pack(">IHHHH", 0x10000, len(tables), 0, 0, 0)
    offset = 12 + 16 * len(tables)
    directory, data = b"", b""
    for name in sorted(tables):
        body = tables[name]
        directory += struct.pack(">4sIII", name.encode(), 0, offset + len(data), len(body))
        data += body + b"\x00" * (-len(body) % 4)
    return out + directory + data


def _box(x0, y0, x1, y1):
    return [(x0, y0, True), (x0, y1, True), (x1, y1, True), (x1, y0, True)]


BLOCKS = {"H": (600, [_box(0, 0, 500, 700)]), " ": (300, [])}


def test_a_font_says_which_glyph_draws_a_character_and_how_wide_it_is():
    face = ttf.TrueType(_table_font(BLOCKS))
    assert face.glyph("H") is not None and face.glyph("Z") is None
    assert face.advance(face.glyph("H")) == 600
    # no OS/2 cap height, so the top of the H
    assert face.cap_height() == 700
    assert ttf.TrueType(_table_font(BLOCKS, cap=650)).cap_height() == 650


def test_an_outline_fills_the_pixels_it_covers():
    face = ttf.TrueType(_table_font(BLOCKS))
    contours = face.contours(face.glyph("H"))
    grid = ttf.coverage(contours, 0.01, 0, 8, 7, 10)    # 500x700 units -> 5x7 pixels
    filled = [[value >= 0.5 for value in line] for line in grid]
    assert all(filled[y][x] for y in range(1, 8) for x in range(5))
    assert not any(filled[0]) and not any(filled[8]) and not any(line[6] for line in filled)


def test_a_curve_s_control_points_bend_the_outline_between_them():
    # two off-curve points in a row imply an on-curve point midway between them
    polygon = ttf._flatten([(0, 0, True), (0, 100, False), (100, 100, False),
                            (100, 0, True)], steps=2)
    assert (50.0, 100.0) in polygon and (0, 0) == polygon[0]


@pytest.mark.parametrize("start, message", [(b"OTTO", "PostScript"),
                                            (b"ttcf", "collection"),
                                            (b"wOFF", "not a TrueType")])
def test_fonts_this_does_not_read_are_refused_by_name(start, message):
    with pytest.raises(ValueError, match=message):
        ttf.TrueType(start + b"\x00" * 64)
