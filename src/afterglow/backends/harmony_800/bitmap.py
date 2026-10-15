"""Read and write the pictures a Harmony 800 configuration draws.

Bitmaps are most of a configuration: 1.1 to 1.5 MB of the 1.3 to 1.8 MB in the four
images measured, around 85 per cent. Every backdrop, button frame, row frame, softkey
and icon the remote shows is stored here rather than in firmware, which is why a
configuration generated from a project has to supply them and why they can be ours.

Pixels are RGB565, big-endian, after a five-byte header. Mode 0 stores every pixel of
every row. Mode 1 runs them - a byte with the high bit set leaves that many pixels
untouched, a byte without it introduces that many stored pixels, `80` closes a row and
`00` closes the picture - which is the same run encoding, and the same byte order, that a
font glyph uses. Nothing in the format carries
an alpha channel; a run simply declines to write, so what was already on the screen shows
through.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct


RAW = 0
RUNS = 1
# Both encodings are big-endian. Stored-whole pictures were once read little-endian a
# byte early, which reads each pixel's high byte correctly and borrows its low byte from
# the pixel before - close enough to look right, and to pass for a byte-order split.
# Read from the true header, a 163x83 panel's neighbouring pixels differ by 47 big-endian
# and by 98 little-endian. Danny Bloe's renderer reads both kinds big-endian too.
RAW_ORDER = "big"
RUN_ORDER = "big"
MAX_RUN = 0x7F
# Both encodings open with the same five bytes: the mode, then width and height as
# little-endian u16s. Raw pictures were once read with four, the height's high byte
# taken as the first pixel's, which round-tripped against itself and drew every stored
# pixel a byte out; donor pictures sit exactly `5 + 2 * width * height` apart.
HEADER_SIZE = 5
ROW_END = 0x80
PICTURE_END = 0x00
# The reader that guards screen resources uses these bounds; keep to them so a picture
# written here is one it will accept back.
MAX_WIDTH = 240           # the Harmony 800's screen (the One's is 176 x 220)
MAX_HEIGHT = 320


def to_rgb565(colour: tuple[int, int, int]) -> int:
    """Pack one 8-bit-per-channel colour into the display's 16-bit format."""
    red, green, blue = colour
    for value, label in ((red, "red"), (green, "green"), (blue, "blue")):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError(f"the {label} channel must be a byte")
    return ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)


def from_rgb565(value: int) -> tuple[int, int, int]:
    """Unpack a display colour, spreading each channel back over its full range."""
    red, green, blue = (value >> 11) & 0x1F, (value >> 5) & 0x3F, value & 0x1F
    return red * 255 // 31, green * 255 // 63, blue * 255 // 31


def decode(payload: bytes, offset: int) -> dict:
    """Return a picture's size and its rows of colours, with None where nothing is drawn."""
    if offset < 0 or offset + HEADER_SIZE > len(payload):
        raise ValueError(f"picture at {offset:#x} has a truncated header")
    mode, width, height = struct.unpack_from("<BHH", payload, offset)
    if mode not in (RAW, RUNS):
        raise ValueError(f"picture at {offset:#x} has an unknown header")
    if not 1 <= width <= MAX_WIDTH or not 1 <= height <= MAX_HEIGHT:
        raise ValueError(f"picture at {offset:#x} is {width}x{height}")
    if mode == RAW:
        end = offset + HEADER_SIZE + 2 * width * height
        if end > len(payload):
            raise ValueError(f"picture at {offset:#x} is truncated")
        rows = []
        cursor = offset + HEADER_SIZE
        for _y in range(height):
            row = []
            for _x in range(width):
                row.append(from_rgb565(
                    int.from_bytes(payload[cursor:cursor + 2], RAW_ORDER)))
                cursor += 2
            rows.append(row)
        return {"mode": RAW, "width": width, "height": height,
                "rows": rows, "size": end - offset}

    cursor = offset + HEADER_SIZE
    rows, row = [], []
    while cursor < len(payload):
        control = payload[cursor]
        cursor += 1
        if control == PICTURE_END:
            if row:
                rows.append(row)
            break
        if control == ROW_END:
            if len(row) != width:
                raise ValueError(f"picture at {offset:#x} has an inconsistent row width")
            rows.append(row)
            row = []
            continue
        length = control & MAX_RUN
        if control & ROW_END:
            row += [None] * length
        else:
            if cursor + 2 * length > len(payload):
                raise ValueError(f"picture at {offset:#x} has a truncated run")
            for _index in range(length):
                row.append(from_rgb565(
                    int.from_bytes(payload[cursor:cursor + 2], RUN_ORDER)))
                cursor += 2
        if len(row) > width:
            raise ValueError(f"picture at {offset:#x} overruns its width")
    else:
        raise ValueError(f"picture at {offset:#x} has no terminator")
    if len(rows) != height:
        raise ValueError(
            f"picture at {offset:#x} decoded {len(rows)} rows, not {height}")
    return {"mode": RUNS, "width": width, "height": height,
            "rows": rows, "size": cursor - offset}


def encode(rows: list[list], *, mode: int | None = None) -> bytes:
    """Write a picture. ``rows`` holds colours, or None where nothing is to be drawn.

    Without a mode, the shorter encoding wins, except that a picture with anything
    undrawn in it must be run-encoded, because storing every pixel leaves no way to say
    "leave this one alone".
    """
    if not rows or not rows[0]:
        raise ValueError("a picture needs at least one row of at least one pixel")
    height, width = len(rows), len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("every row of a picture has the same width")
    if not 1 <= width <= MAX_WIDTH or not 1 <= height <= MAX_HEIGHT:
        raise ValueError(
            f"a picture is at most {MAX_WIDTH}x{MAX_HEIGHT}; this is {width}x{height}")
    transparent = any(pixel is None for row in rows for pixel in row)
    if mode == RAW and transparent:
        raise ValueError("a picture with undrawn pixels cannot store every pixel")
    raw = _encode_raw(rows) if not transparent else None
    runs = _encode_runs(rows)
    if mode == RAW:
        return raw
    if mode == RUNS:
        return runs
    return runs if raw is None or len(runs) < len(raw) else raw


def _encode_raw(rows: list[list]) -> bytes:
    out = bytearray(struct.pack("<BHH", RAW, len(rows[0]), len(rows)))
    for row in rows:
        for pixel in row:
            out += to_rgb565(pixel).to_bytes(2, RAW_ORDER)
    return bytes(out)


def _encode_runs(rows: list[list]) -> bytes:
    out = bytearray(struct.pack("<BHH", RUNS, len(rows[0]), len(rows)))
    for number, row in enumerate(rows):
        index = 0
        while index < len(row):
            drawn = row[index] is not None
            run = 0
            while (index + run < len(row) and run < MAX_RUN
                   and (row[index + run] is not None) == drawn):
                run += 1
            if drawn:
                out.append(run)
                for pixel in row[index:index + run]:
                    out += to_rgb565(pixel).to_bytes(2, RUN_ORDER)
            else:
                out.append(ROW_END | run)
            index += run
        # The last row needs no separator: the picture's own terminator closes it, and
        # every run-encoded picture in the donors leaves it off.
        if number + 1 < len(rows):
            out.append(ROW_END)
    out.append(PICTURE_END)
    return bytes(out)


# A font glyph is the same run encoding with a different header: one byte of width where
# a picture has four bytes of mode, width, zero and height. There is no stored-whole
# variant, because a glyph is mostly the gaps between its strokes. Every glyph carries
# real colours rather than a mask - the donors' fonts use two apiece, a stroke colour and
# a shadow - so a glyph is a small coloured picture and recolouring one means editing it.
def decode_glyph(payload: bytes, offset: int) -> dict:
    """Return a glyph's size and its rows of colours, with None where nothing is drawn."""
    if offset < 0 or offset >= len(payload):
        raise ValueError(f"glyph at {offset:#x} starts outside the image")
    width = payload[offset]
    if not 1 <= width <= MAX_WIDTH:
        raise ValueError(f"glyph at {offset:#x} declares width {width}")
    cursor = offset + 1
    rows, row = [], []
    while cursor < len(payload):
        control = payload[cursor]
        cursor += 1
        if control == PICTURE_END:
            if row:
                rows.append(row)
            break
        if control == ROW_END:
            if len(row) != width:
                raise ValueError(f"glyph at {offset:#x} has an inconsistent row width")
            rows.append(row)
            row = []
            continue
        length = control & MAX_RUN
        if not length:
            raise ValueError(f"glyph at {offset:#x} has a zero-length run")
        if control & ROW_END:
            row += [None] * length
        else:
            if cursor + 2 * length > len(payload):
                raise ValueError(f"glyph at {offset:#x} has a truncated run")
            for _index in range(length):
                row.append(from_rgb565(
                    int.from_bytes(payload[cursor:cursor + 2], RUN_ORDER)))
                cursor += 2
        if len(row) > width:
            raise ValueError(f"glyph at {offset:#x} overruns its declared width")
    else:
        raise ValueError(f"glyph at {offset:#x} has no terminator")
    if not rows or any(len(item) != width for item in rows):
        raise ValueError(f"glyph at {offset:#x} has no rows of its declared width")
    if len(rows) > MAX_HEIGHT:
        raise ValueError(f"glyph at {offset:#x} is taller than the display")
    return {"width": width, "height": len(rows), "rows": rows,
            "size": cursor - offset}


def encode_glyph(rows: list[list]) -> bytes:
    """Write a glyph. ``rows`` holds colours, or None where nothing is to be drawn."""
    if not rows or not rows[0]:
        raise ValueError("a glyph needs at least one row of at least one pixel")
    height, width = len(rows), len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("every row of a glyph has the same width")
    if not 1 <= width <= MAX_WIDTH or not 1 <= height <= MAX_HEIGHT:
        raise ValueError(
            f"a glyph is at most {MAX_WIDTH}x{MAX_HEIGHT}; this is {width}x{height}")
    out = bytearray([width])
    for number, row in enumerate(rows):
        index = 0
        while index < len(row):
            drawn = row[index] is not None
            run = 0
            while (index + run < len(row) and run < MAX_RUN
                   and (row[index + run] is not None) == drawn):
                run += 1
            if drawn:
                out.append(run)
                for pixel in row[index:index + run]:
                    out += to_rgb565(pixel).to_bytes(2, RUN_ORDER)
            else:
                out.append(ROW_END | run)
            index += run
        if number + 1 < len(rows):
            out.append(ROW_END)
    out.append(PICTURE_END)
    return bytes(out)
