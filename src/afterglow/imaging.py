"""Read and write PNG files using nothing but the standard library.

Assets a build draws - button frames, backdrops, status icons, font glyphs - live in a
scaffold directory so that they can be edited, and PNG is the format every image editor
already opens. The format layer takes no third-party dependency, so Pillow cannot be used
here; PNG's own compression is `zlib`, which is in the standard library, and the rest of
the container is a handful of length-prefixed chunks.

What is supported is what an editor writes when asked for a PNG: greyscale, palette,
truecolour, each with or without alpha, at every bit depth the format allows, not
interlaced. Sixteen-bit channels are reduced to eight, which is all the display holds.
Interlaced files are refused by name rather than guessed at, because a silently misread
asset would reach the remote as noise.
"""

from __future__ import annotations

import struct
import zlib


SIGNATURE = b"\x89PNG\r\n\x1a\n"

GREY = 0
TRUECOLOUR = 2
PALETTE = 3
GREY_ALPHA = 4
TRUECOLOUR_ALPHA = 6

_CHANNELS = {GREY: 1, TRUECOLOUR: 3, PALETTE: 1, GREY_ALPHA: 2, TRUECOLOUR_ALPHA: 4}
_COLOUR_NAMES = {
    GREY: "greyscale", TRUECOLOUR: "truecolour", PALETTE: "palette",
    GREY_ALPHA: "greyscale with alpha", TRUECOLOUR_ALPHA: "truecolour with alpha",
}


def _chunks(data: bytes):
    """Yield each (type, payload) chunk, checking every CRC."""
    if data[:8] != SIGNATURE:
        raise ValueError("this file does not start with a PNG signature")
    cursor = 8
    while cursor + 8 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, cursor)
        body = data[cursor + 8:cursor + 8 + length]
        if len(body) != length:
            raise ValueError(f"PNG chunk {kind.decode('ascii', 'replace')} is truncated")
        expected = struct.unpack_from(">I", data, cursor + 8 + length)[0]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != expected:
            raise ValueError(
                f"PNG chunk {kind.decode('ascii', 'replace')} fails its checksum")
        yield kind, body
        cursor += 12 + length
        if kind == b"IEND":
            return
    raise ValueError("this PNG has no IEND chunk")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw: bytes, height: int, stride: int, step: int) -> bytearray:
    """Undo the per-scanline filter PNG applies before compressing."""
    out = bytearray()
    previous = bytearray(stride)
    cursor = 0
    for row in range(height):
        if cursor + 1 + stride > len(raw):
            raise ValueError("this PNG's pixel data is shorter than its own dimensions")
        method = raw[cursor]
        line = bytearray(raw[cursor + 1:cursor + 1 + stride])
        cursor += 1 + stride
        if method == 1:
            for i in range(step, stride):
                line[i] = (line[i] + line[i - step]) & 0xFF
        elif method == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif method == 3:
            for i in range(stride):
                left = line[i - step] if i >= step else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif method == 4:
            for i in range(stride):
                left = line[i - step] if i >= step else 0
                upper_left = previous[i - step] if i >= step else 0
                line[i] = (line[i] + _paeth(left, previous[i], upper_left)) & 0xFF
        elif method:
            raise ValueError(f"this PNG uses unknown scanline filter {method}")
        out += line
        previous = line
    return out


def _samples(line: bytes, count: int, depth: int) -> list[int]:
    """Unpack one scanline into its raw sample values, one per channel per pixel."""
    if depth == 8:
        return list(line[:count])
    if depth == 16:
        # The display holds eight bits a channel, so the low byte is dropped; it could
        # not survive the trip to RGB565 either way.
        return list(line[0:2 * count:2])
    out = []
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    for index in range(count):
        byte = line[index // per_byte]
        shift = 8 - depth * (index % per_byte + 1)
        out.append((byte >> shift) & mask)
    return out


def decode(data: bytes) -> dict:
    """Return a PNG's size and its rows of `(red, green, blue, alpha)` bytes."""
    header = None
    palette: list[tuple[int, int, int]] = []
    transparency = b""
    compressed = bytearray()
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            compressed += body
    if header is None:
        raise ValueError("this PNG has no IHDR chunk")
    width, height, depth, colour, compression, filtering, interlace = header
    if not width or not height:
        raise ValueError("this PNG declares an empty image")
    if compression or filtering:
        raise ValueError("this PNG uses a compression or filter method PNG never defined")
    if interlace:
        raise ValueError("this PNG is interlaced; save it without Adam7 interlacing")
    if colour not in _CHANNELS:
        raise ValueError(f"this PNG declares unknown colour type {colour}")
    if depth not in (1, 2, 4, 8, 16):
        raise ValueError(f"this PNG declares bit depth {depth}, which PNG never defines")
    if depth != 8 and colour in (TRUECOLOUR, GREY_ALPHA, TRUECOLOUR_ALPHA) and depth != 16:
        raise ValueError(
            f"a {_COLOUR_NAMES[colour]} PNG cannot be {depth} bits per channel")
    if depth < 8 and colour not in (GREY, PALETTE):
        raise ValueError(
            f"a {_COLOUR_NAMES[colour]} PNG cannot be {depth} bits per channel")

    channels = _CHANNELS[colour]
    # Sub-byte samples are packed several to a byte and filtered a whole byte at a time;
    # wider ones are filtered a whole pixel at a time.
    stride = (width * channels * depth + 7) // 8
    step = max(1, channels * depth // 8)
    raw = _unfilter(zlib.decompress(bytes(compressed)), height, stride, step)

    rows = []
    for y in range(height):
        line = raw[y * stride:(y + 1) * stride]
        samples = _samples(line, width * channels, depth)
        row = []
        for x in range(width):
            pixel = samples[x * channels:(x + 1) * channels]
            if colour == GREY:
                level = pixel[0] * 255 // ((1 << depth) - 1) if depth < 8 else pixel[0]
                row.append((level, level, level, 255))
            elif colour == GREY_ALPHA:
                row.append((pixel[0], pixel[0], pixel[0], pixel[1]))
            elif colour == TRUECOLOUR:
                row.append((pixel[0], pixel[1], pixel[2], 255))
            elif colour == TRUECOLOUR_ALPHA:
                row.append((pixel[0], pixel[1], pixel[2], pixel[3]))
            else:
                index = pixel[0]
                if not palette:
                    raise ValueError("this palette PNG has no PLTE chunk")
                if index >= len(palette):
                    raise ValueError(
                        f"this PNG uses palette entry {index}, which it does not define")
                alpha = transparency[index] if index < len(transparency) else 255
                row.append((*palette[index], alpha))
        rows.append(row)
    return {"width": width, "height": height, "rows": rows}


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def encode(rows: list[list[tuple[int, int, int, int]]]) -> bytes:
    """Write rows of `(red, green, blue, alpha)` bytes as a truecolour-with-alpha PNG."""
    if not rows or not rows[0]:
        raise ValueError("an image must have at least one pixel")
    height, width = len(rows), len(rows[0])
    raw = bytearray()
    for row in rows:
        if len(row) != width:
            raise ValueError("every row of an image must be the same width")
        # Filter 0 keeps the writer trivial and readable; zlib does the compressing.
        raw.append(0)
        for pixel in row:
            if len(pixel) != 4 or any(
                    isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255
                    for v in pixel):
                raise ValueError("every pixel must be four bytes of red, green, blue, alpha")
            raw += bytes(pixel)
    return (SIGNATURE
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8,
                                          TRUECOLOUR_ALPHA, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))
