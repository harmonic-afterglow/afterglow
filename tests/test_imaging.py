"""The PNG codec the scaffold artwork is read through.

The format layer takes no third-party dependency, so this reader replaces Pillow for the
one job of getting a user's artwork into a configuration. A misread asset would reach the
remote as noise rather than as an error, so the tests here care about pixels, not about
whether decoding raised.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from afterglow import imaging


def chunk(kind: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def png(width, height, depth, colour, raw, *, palette=b"", transparency=b"",
        interlace=0, compression=0, filtering=0):
    out = imaging.SIGNATURE + chunk(b"IHDR", struct.pack(
        ">IIBBBBB", width, height, depth, colour, compression, filtering, interlace))
    if palette:
        out += chunk(b"PLTE", palette)
    if transparency:
        out += chunk(b"tRNS", transparency)
    return out + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_a_written_image_reads_back_pixel_for_pixel():
    rows = [[(x * 9 % 256, y * 7 % 256, (x * y) % 256, 255 if (x + y) % 4 else 0)
             for x in range(23)] for y in range(11)]

    image = imaging.decode(imaging.encode(rows))

    assert (image["width"], image["height"]) == (23, 11)
    assert image["rows"] == rows


@pytest.mark.parametrize("depth", [1, 2, 4])
def test_a_sub_byte_palette_image_unpacks_its_indices(depth):
    # two entries, so one bit is enough at every depth under test
    palette = bytes((255, 0, 0, 0, 0, 255))
    per_byte = 8 // depth
    entries = (1, 0, 1, 0)
    line = bytearray((len(entries) * depth + 7) // 8)
    for index, entry in enumerate(entries):
        line[index // per_byte] |= entry << (8 - depth * (index % per_byte + 1))
    raw = bytes([0]) + bytes(line)

    image = imaging.decode(png(4, 1, depth, imaging.PALETTE, raw, palette=palette))

    assert image["rows"][0] == [
        (0, 0, 255, 255), (255, 0, 0, 255), (0, 0, 255, 255), (255, 0, 0, 255)]


def test_a_sub_byte_grey_level_is_spread_over_the_whole_range():
    # depth 2: levels 0 and 3 are black and white, not 0 and 3
    image = imaging.decode(png(4, 1, 2, imaging.GREY, bytes([0, 0b00_01_10_11])))

    assert [pixel[0] for pixel in image["rows"][0]] == [0, 85, 170, 255]


def test_a_sixteen_bit_channel_keeps_its_high_byte():
    raw = bytes([0]) + struct.pack(">HHH", 0x1234, 0xABCD, 0x00FF)

    image = imaging.decode(png(1, 1, 16, imaging.TRUECOLOUR, raw))

    assert image["rows"][0][0] == (0x12, 0xAB, 0x00, 255)


@pytest.mark.parametrize("method", [1, 2, 3, 4])
def test_every_scanline_filter_reconstructs_the_same_picture(method):
    width, height = 6, 4
    plain = [[(x * 30 % 256, y * 60 % 256, 40) for x in range(width)]
             for y in range(height)]
    # filter the rows the way a writer would, so decoding has to undo it
    raw = bytearray()
    previous = bytearray(width * 3)
    for row in plain:
        line = bytearray(b"".join(bytes(p) for p in row))
        out = bytearray(len(line))
        for i, value in enumerate(line):
            left = line[i - 3] if i >= 3 else 0
            upper_left = previous[i - 3] if i >= 3 else 0
            up = previous[i]
            if method == 1:
                out[i] = (value - left) & 0xFF
            elif method == 2:
                out[i] = (value - up) & 0xFF
            elif method == 3:
                out[i] = (value - ((left + up) >> 1)) & 0xFF
            else:
                out[i] = (value - imaging._paeth(left, up, upper_left)) & 0xFF
        raw += bytes([method]) + out
        previous = line

    image = imaging.decode(png(width, height, 8, imaging.TRUECOLOUR, bytes(raw)))

    assert [[p[:3] for p in row] for row in image["rows"]] == plain


def test_an_interlaced_file_is_refused_by_name():
    raw = bytes([0, 1, 2, 3])
    with pytest.raises(ValueError, match="interlaced"):
        imaging.decode(png(1, 1, 8, imaging.TRUECOLOUR, raw, interlace=1))


def test_a_corrupt_chunk_is_not_read_as_pixels():
    data = bytearray(imaging.encode([[(1, 2, 3, 255)]]))
    data[-5] ^= 0xFF  # inside IEND's checksum region

    with pytest.raises(ValueError, match="checksum"):
        imaging.decode(bytes(data))


def test_something_that_is_not_a_png_is_refused():
    with pytest.raises(ValueError, match="PNG signature"):
        imaging.decode(b"GIF89a" + bytes(64))
