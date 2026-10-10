"""Read a TrueType font and draw its glyphs at a few pixels tall, with the standard library.

A remote's text can be drawn from any font its owner chooses, and a build has to do that
headless - from the command line and the tests as well as the app - so it cannot lean on
FreeType or Pillow. This reads the handful of TrueType tables that say what a character
looks like (`cmap`, `head`, `hhea`, `hmtx`, `maxp`, `loca`, `glyf`, and `OS/2` for the cap
height) and fills a glyph's outline by sampling it, which is all a pixel font needs: no
hinting, kerning or shaping. Fonts with PostScript (CFF) outlines and font collections
are refused by name rather than half-read.

Nothing here knows about any remote; a backend decides the size and colours.
"""
from __future__ import annotations

import struct

SAMPLES = 4          # samples per pixel along each axis when measuring coverage


class TrueType:
    """One TrueType font: which glyph draws a character, how wide it is, its outline."""

    def __init__(self, data: bytes):
        if len(data) < 12:
            raise ValueError("this is too short to be a TrueType font")
        tag = data[:4]
        if tag == b"OTTO":
            raise ValueError("this font has PostScript (CFF) outlines; only TrueType is read")
        if tag == b"ttcf":
            raise ValueError("this is a font collection; extract one font from it")
        if tag not in (b"\x00\x01\x00\x00", b"true"):
            raise ValueError(f"this is not a TrueType font (it starts {tag!r})")
        self.data = data
        count = struct.unpack_from(">H", data, 4)[0]
        self.tables = {}
        for index in range(count):
            name, _checksum, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * index)
            self.tables[name.decode("latin-1")] = (offset, length)
        for name in ("cmap", "head", "hhea", "hmtx", "maxp", "loca", "glyf"):
            if name not in self.tables:
                raise ValueError(f"this TrueType font has no {name!r} table")
        head = self.tables["head"][0]
        self.units_per_em = struct.unpack_from(">H", data, head + 18)[0]
        self.long_offsets = struct.unpack_from(">h", data, head + 50)[0] == 1
        self.glyph_count = struct.unpack_from(">H", data, self.tables["maxp"][0] + 4)[0]
        self.metric_count = struct.unpack_from(">H", data, self.tables["hhea"][0] + 34)[0]
        self.ascent = struct.unpack_from(">h", data, self.tables["hhea"][0] + 4)[0]
        self.characters = self._cmap()

    # -- tables ---------------------------------------------------------------------------

    def _cmap(self) -> dict[int, int]:
        start = self.tables["cmap"][0]
        count = struct.unpack_from(">H", self.data, start + 2)[0]
        chosen = None
        for index in range(count):
            platform, encoding, offset = struct.unpack_from(">HHI", self.data, start + 4 + 8 * index)
            form = struct.unpack_from(">H", self.data, start + offset)[0]
            rank = {(3, 10, 12): 0, (0, 4, 12): 0, (3, 1, 4): 1, (0, 3, 4): 1}.get(
                (platform, encoding, form), 2 if form in (4, 12) else None)
            if rank is not None and (chosen is None or rank < chosen[0]):
                chosen = (rank, start + offset, form)
        if chosen is None:
            raise ValueError("this font maps no Unicode characters")
        _rank, at, form = chosen
        out = {}
        if form == 4:
            segments = struct.unpack_from(">H", self.data, at + 6)[0] // 2
            ends = at + 14
            starts = ends + 2 * segments + 2
            deltas = starts + 2 * segments
            ranges = deltas + 2 * segments
            for index in range(segments):
                end = struct.unpack_from(">H", self.data, ends + 2 * index)[0]
                first = struct.unpack_from(">H", self.data, starts + 2 * index)[0]
                delta = struct.unpack_from(">h", self.data, deltas + 2 * index)[0]
                offset = struct.unpack_from(">H", self.data, ranges + 2 * index)[0]
                for code in range(first, end + 1):
                    if code == 0xFFFF:
                        continue
                    if offset == 0:
                        glyph = (code + delta) & 0xFFFF
                    else:
                        where = ranges + 2 * index + offset + 2 * (code - first)
                        glyph = struct.unpack_from(">H", self.data, where)[0]
                        glyph = (glyph + delta) & 0xFFFF if glyph else 0
                    if glyph:
                        out[code] = glyph
        else:
            groups = struct.unpack_from(">I", self.data, at + 12)[0]
            for index in range(groups):
                first, last, glyph = struct.unpack_from(">III", self.data, at + 16 + 12 * index)
                for code in range(first, min(last, 0x10FFFF) + 1):
                    out[code] = glyph + code - first
        return out

    def _location(self, glyph: int) -> tuple[int, int]:
        loca = self.tables["loca"][0]
        if self.long_offsets:
            start, end = struct.unpack_from(">II", self.data, loca + 4 * glyph)
        else:
            start, end = (2 * value for value in
                          struct.unpack_from(">HH", self.data, loca + 2 * glyph))
        return self.tables["glyf"][0] + start, end - start

    # -- what callers ask -----------------------------------------------------------------

    def glyph(self, char: str) -> int | None:
        return self.characters.get(ord(char))

    def advance(self, glyph: int) -> int:
        """The glyph's advance width in font units."""
        at = self.tables["hmtx"][0]
        index = min(glyph, self.metric_count - 1)
        return struct.unpack_from(">H", self.data, at + 4 * index)[0]

    def cap_height(self) -> int:
        """The height of a capital in font units: OS/2's own figure, else the top of H."""
        if "OS/2" in self.tables:
            at, length = self.tables["OS/2"]
            version = struct.unpack_from(">H", self.data, at)[0]
            if version >= 2 and length >= 90:
                value = struct.unpack_from(">h", self.data, at + 88)[0]
                if value > 0:
                    return value
        glyph = self.glyph("H")
        if glyph is not None:
            points = [point for contour in self.contours(glyph) for point in contour]
            if points:
                return max(y for _x, y in points)
        return round(self.ascent * 0.7)

    def contours(self, glyph: int, depth: int = 0) -> list[list[tuple[float, float]]]:
        """The glyph's outline as closed polygons in font units, curves flattened."""
        at, length = self._location(glyph)
        if length == 0 or depth > 8:
            return []
        count = struct.unpack_from(">h", self.data, at)[0]
        if count < 0:
            return self._composite(at + 10, depth)
        ends = struct.unpack_from(f">{count}H", self.data, at + 10)
        total = ends[-1] + 1 if count else 0
        cursor = at + 10 + 2 * count
        cursor += 2 + struct.unpack_from(">H", self.data, cursor)[0]   # instructions
        flags = []
        while len(flags) < total:
            flag = self.data[cursor]
            cursor += 1
            repeat = 1
            if flag & 8:
                repeat += self.data[cursor]
                cursor += 1
            flags += [flag] * repeat
        flags = flags[:total]
        xs, cursor = self._coordinates(flags, cursor, 2, 16)
        ys, cursor = self._coordinates(flags, cursor, 4, 32)
        out, first = [], 0
        for end in ends:
            points = [(xs[i], ys[i], bool(flags[i] & 1)) for i in range(first, end + 1)]
            first = end + 1
            if points:
                out.append(_flatten(points))
        return out

    def _coordinates(self, flags, cursor, short, same):
        values, value = [], 0
        for flag in flags:
            if flag & short:
                step = self.data[cursor]
                cursor += 1
                value += step if flag & same else -step
            elif not flag & same:
                value += struct.unpack_from(">h", self.data, cursor)[0]
                cursor += 2
            values.append(value)
        return values, cursor

    def _composite(self, cursor: int, depth: int) -> list[list[tuple[float, float]]]:
        out = []
        while True:
            flags, glyph = struct.unpack_from(">HH", self.data, cursor)
            cursor += 4
            if flags & 1:
                dx, dy = struct.unpack_from(">hh", self.data, cursor)
                cursor += 4
            else:
                dx, dy = struct.unpack_from(">bb", self.data, cursor)
                cursor += 2
            if not flags & 2:
                dx = dy = 0        # point-matched placement: rare, left in place
            a, b, c, d = 1.0, 0.0, 0.0, 1.0
            if flags & 8:
                a = d = struct.unpack_from(">h", self.data, cursor)[0] / 16384
                cursor += 2
            elif flags & 0x40:
                a, d = (v / 16384 for v in struct.unpack_from(">hh", self.data, cursor))
                cursor += 4
            elif flags & 0x80:
                a, b, c, d = (v / 16384 for v in struct.unpack_from(">hhhh", self.data, cursor))
                cursor += 8
            for contour in self.contours(glyph, depth + 1):
                out.append([(a * x + c * y + dx, b * x + d * y + dy) for x, y in contour])
            if not flags & 0x20:
                return out


def _flatten(points, steps: int = 4) -> list[tuple[float, float]]:
    """A TrueType contour - on-curve points and quadratic control points, with implied
    on-curve points between two controls - as a polygon."""
    count = len(points)
    start = next((i for i, p in enumerate(points) if p[2]), None)
    if start is None:      # all control points: start halfway between the first two
        x = (points[0][0] + points[1 % count][0]) / 2
        y = (points[0][1] + points[1 % count][1]) / 2
        points = [(x, y, True)] + points
        count, start = len(points), 0
    ordered = points[start:] + points[:start]
    polygon = [ordered[0][:2]]
    control = None
    for x, y, on in ordered[1:] + ordered[:1]:
        if on:
            if control is None:
                polygon.append((x, y))
            else:
                polygon += _quadratic(polygon[-1], control, (x, y), steps)
                control = None
        else:
            if control is not None:
                middle = ((control[0] + x) / 2, (control[1] + y) / 2)
                polygon += _quadratic(polygon[-1], control, middle, steps)
            control = (x, y)
    return polygon


def _quadratic(p0, p1, p2, steps):
    out = []
    for step in range(1, steps + 1):
        t = step / steps
        u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def coverage(contours, scale: float, left: int, baseline: int, width: int,
             height: int) -> list[list[float]]:
    """How much of each pixel in a ``width`` x ``height`` grid the outline covers, 0 to 1.

    Font units go right and up from the glyph's origin; the grid goes right and down, the
    origin sitting ``left`` pixels in and on row ``baseline``. Filled by the non-zero
    winding rule, which is TrueType's."""
    edges = []
    for contour in contours:
        for (x0, y0), (x1, y1) in zip(contour, contour[1:] + contour[:1]):
            a = (left + x0 * scale, baseline - y0 * scale)
            b = (left + x1 * scale, baseline - y1 * scale)
            if a[1] != b[1]:
                edges.append((a, b))
    grid = [[0.0] * width for _ in range(height)]
    share = 1 / (SAMPLES * SAMPLES)
    for row in range(height):
        for sub in range(SAMPLES):
            y = row + (sub + 0.5) / SAMPLES
            crossings = []
            for (x0, y0), (x1, y1) in edges:
                if (y0 <= y < y1) or (y1 <= y < y0):
                    x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                    crossings.append((x, 1 if y1 > y0 else -1))
            if not crossings:
                continue
            crossings.sort()
            for column in range(width):
                for sample in range(SAMPLES):
                    x = column + (sample + 0.5) / SAMPLES
                    winding = sum(direction for cx, direction in crossings if cx < x)
                    if winding:
                        grid[row][column] += share
    return grid
