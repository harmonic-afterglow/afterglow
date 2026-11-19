"""Write the 5xx's pixels: its glyphs and its pictures, as the readers read them back.

The 96 x 64 screen is monochrome. A picture is one bit a pixel; a glyph is two, run-coded
row by row. Both writers are the exact inverses of the readers (ui_index.glyph_mask,
`decode_picture`), and the glyph writer chooses runs and literals as Logitech's compiler
did, so a font Logitech wrote encodes back to its own bytes.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

import itertools
import struct

LITERAL, PAPER, INK = 0x5, 0x6, 0xA
ROW_LEADER = 0x20
# A command covers at most 16 pixels; a row's commands at most 31 bytes.
MOST = 16
MOST_ROW_BYTES = 0x1F
# Logitech writes a run of this many pixels or more as a run, the pixels between such
# runs as literals - and a literal of one colour as a run after all.
RUN_FROM = 5
PICTURE_KIND = 2


def _runs(ink: int, count: int) -> list[int]:
    out = []
    while count:
        size = min(count, MOST)
        out.append((INK if ink else PAPER) << 4 | (size - 1))
        count -= size
    return out


def _literals(pixels: list[int]) -> list[int]:
    out = []
    for start in range(0, len(pixels), MOST):
        chunk = pixels[start:start + MOST]
        if len(set(chunk)) == 1:
            out += _runs(chunk[0], len(chunk))
            continue
        bits = 0
        for pixel in chunk:
            bits = bits << 2 | (1 if pixel else 2)
        size = (2 * len(chunk) + 7) // 8
        bits <<= 8 * size - 2 * len(chunk)
        out += [LITERAL << 4 | (len(chunk) - 1), *bits.to_bytes(size, "big")]
    return out


def glyph_row(pixels) -> bytes:
    """One glyph row's commands, 1 for ink and 0 for paper."""
    out, pending = [], []
    for ink, group in itertools.groupby(1 if pixel else 0 for pixel in pixels):
        count = len(list(group))
        if count >= RUN_FROM:
            if pending:
                out += _literals(pending)
                pending = []
            out += _runs(ink, count)
        else:
            pending += [ink] * count
    if pending:
        out += _literals(pending)
    return bytes(out)


def encode_glyph(rows) -> bytes:
    """A glyph: its width, each row's leader and commands, and the zero that ends it."""
    if not rows or not rows[0]:
        raise ValueError("a glyph needs at least one pixel")
    width = len(rows[0])
    if any(len(row) != width for row in rows) or width > 96:
        raise ValueError("a glyph's rows must share one width of at most 96")
    out = bytearray([width])
    for row in rows:
        commands = glyph_row(row)
        if len(commands) > MOST_ROW_BYTES:
            raise ValueError("a glyph row needs more than 31 bytes of commands")
        out += bytes([ROW_LEADER | len(commands)]) + commands
    return bytes(out + b"\x00")


def decode_picture(payload: bytes, offset: int) -> dict:
    """A picture: kind 2, u16 width and height, then one bit a pixel, most significant
    first, each row padded to a whole byte."""
    if not 0 <= offset <= len(payload) - 5:
        raise ValueError(f"picture at {offset:#x} is outside the image")
    if payload[offset] != PICTURE_KIND:
        raise ValueError(f"picture at {offset:#x} is kind {payload[offset]}, not 2")
    width, height = struct.unpack_from("<HH", payload, offset + 1)
    stride = (width + 7) // 8
    end = offset + 5 + stride * height
    if not width or not height or end > len(payload):
        raise ValueError(f"picture at {offset:#x} declares {width} x {height}")
    data = payload[offset + 5:end]
    rows = [[data[y * stride + (x >> 3)] >> (7 - (x & 7)) & 1 for x in range(width)]
            for y in range(height)]
    return {"width": width, "height": height, "rows": rows, "size": end - offset}


def encode_picture(rows) -> bytes:
    """A picture from rows of 1 (ink) and 0 (paper)."""
    if not rows or not rows[0]:
        raise ValueError("a picture needs at least one pixel")
    width, height = len(rows[0]), len(rows)
    if any(len(row) != width for row in rows):
        raise ValueError("a picture's rows must share one width")
    out = bytearray([PICTURE_KIND]) + struct.pack("<HH", width, height)
    for row in rows:
        for start in range(0, width, 8):
            byte = 0
            for x, pixel in enumerate(row[start:start + 8]):
                byte |= (1 if pixel else 0) << (7 - x)
            out.append(byte)
    return bytes(out)
