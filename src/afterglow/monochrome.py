"""Any PNG drawn on a one-colour screen, as the SST-768's, the 688's and the 5xx's
pictures are - a theme's included.

A picture is turned grey (transparent counts as white, colour weighed as the eye weighs
it), shrunk to fit its box if it is too big, its proportions kept, dithered to black and
white (Floyd-Steinberg) and centred in the box. A picture drawn black on white at the
box's size comes through pixel for pixel. Each remote lays the result out its own way:
in pages of eight rows, or as rows.
"""
from __future__ import annotations

from . import imaging


def shades(data: bytes) -> list[list[float]]:
    """A PNG's rows as grey levels, 0 black to 255 white, laid over white where it is
    transparent; colour weighed as the eye weighs it."""
    image = imaging.decode(data)
    return [[255 - alpha / 255 * (255 - (0.299 * red + 0.587 * green + 0.114 * blue))
             for red, green, blue, alpha in row] for row in image["rows"]]


def fitted(rows: list[list[float]], width: int, height: int) -> list[list[float]]:
    """`rows` shrunk to fit `width` x `height`, its proportions kept, each new pixel the
    average of the area it covers; a picture that fits already is left as it is."""
    source_h, source_w = len(rows), len(rows[0])
    factor = min(width / source_w, height / source_h, 1.0)
    if factor == 1.0:
        return rows
    new_w, new_h = max(1, round(source_w * factor)), max(1, round(source_h * factor))
    out = []
    for y in range(new_h):
        top, bottom = y * source_h / new_h, (y + 1) * source_h / new_h
        line = []
        for x in range(new_w):
            left, right = x * source_w / new_w, (x + 1) * source_w / new_w
            total = weight = 0.0
            for sy in range(int(top), min(source_h, -int(-bottom // 1))):
                cover_y = min(bottom, sy + 1) - max(top, sy)
                for sx in range(int(left), min(source_w, -int(-right // 1))):
                    cover = cover_y * (min(right, sx + 1) - max(left, sx))
                    total += rows[sy][sx] * cover
                    weight += cover
            line.append(total / weight)
        out.append(line)
    return out


def dithered(rows: list[list[float]]) -> list[list[bool]]:
    """Grey levels as drawn pixels, Floyd-Steinberg: each pixel's error carried to the
    ones not yet decided. Black and white come through as they are."""
    rows = [list(row) for row in rows]
    out = []
    for y, row in enumerate(rows):
        line = []
        for x, level in enumerate(row):
            on = level < 128
            line.append(on)
            error = level - (0 if on else 255)
            for dx, dy, share in ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)):
                if 0 <= x + dx < len(row) and y + dy < len(rows):
                    rows[y + dy][x + dx] += error * share / 16
        out.append(line)
    return out


def picture(data: bytes, width: int, height: int) -> list[list[bool]]:
    """Any PNG as a one-colour screen can show it in a `width` x `height` box: in grey,
    shrunk to fit, dithered to black and white, centred; True where it is drawn."""
    drawn = dithered(fitted(shades(data), width, height))
    left, top = (width - len(drawn[0])) // 2, (height - len(drawn)) // 2
    box = [[False] * width for _ in range(height)]
    for y, row in enumerate(drawn):
        box[top + y][left:left + len(row)] = row
    return box
