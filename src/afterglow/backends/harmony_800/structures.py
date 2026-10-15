"""The byte forms of the GSPM structures a generated Harmony 800 image is built from.

Key registers, screen slots and trailers, contexts, the command index, navigation and
device objects, font and engine records, and the clock stamp: each written exactly as
measured in Logitech's images. Where they go is the layout's business; these only say
what the bytes are.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import font_index, gspm, lights, records


IR_OBJECT_KIND_FALLBACK = 0x0FCA
ADDRESS_WINDOW = 0x10000


def _atom(operand: int, opcode: int) -> bytes:
    if isinstance(operand, bool) or not isinstance(operand, int) or not 0 <= operand <= 0xFFFF:
        raise ValueError("object atom operand must fit in 16 bits")
    if isinstance(opcode, bool) or not isinstance(opcode, int) or not 0 <= opcode <= 0xFF:
        raise ValueError("object atom opcode must fit in 8 bits")
    return struct.pack("<HB", *lights.instruction(operand, opcode))


def _pointer24(offset: int) -> bytes:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("a native pointer must address a non-negative offset")
    absolute = gspm.BASE + offset
    if absolute >= 1 << 24:
        raise ValueError("a native pointer does not fit in 24 bits")
    return absolute.to_bytes(3, "little")


def indirection_object(target_object: int, kind: int) -> bytes:
    """Build the measured object-A wrapper used by command buttons."""
    return b"\x02" + _atom(kind, 0x75) + _atom(target_object, 0x7F)


def navigation_object(screen_ordinal: int, kind: int) -> bytes:
    """Build the measured object that opens a section-6 screen ordinal."""
    return b"\x02" + _atom(kind, 0x75) + _atom(screen_ordinal, 0x7E)


def device_objects(
        device_index: int, command_count: int, first_object_id: int, kind: int,
) -> tuple[list[bytes], list[int]]:
    """Build command objects and their wrappers in measured B/A order."""
    for value, label, maximum in (
            (device_index, "device index", 0xFF),
            (command_count, "command count", 0x100),
            (first_object_id, "first object ID", 0xFFFF)):
        if (isinstance(value, bool) or not isinstance(value, int)
                or not 0 <= value <= maximum):
            raise ValueError(f"{label} is outside its native range")
    if first_object_id + 2 * command_count > 0x10000:
        raise ValueError("device objects exceed the 16-bit object ID space")
    bodies = []
    wrappers = []
    device_id = (device_index << 8) | 1
    for ordinal in range(command_count):
        command_object_id = first_object_id + 2 * ordinal
        wrapper_id = command_object_id + 1
        bodies.extend((
            records.command_object((device_index << 8) | ordinal, device_id),
            indirection_object(command_object_id, kind),
        ))
        wrappers.append(wrapper_id)
    return bodies, wrappers


# On the 800 a list of no rows is `00 00 00`: after `00 00` the firmware reads the count.
EMPTY_KEY_REGISTER = b"\x00\x00\x00"


# The One's events (harmony_one/gspm.md, "Where the events come from") under the numbers the
# 800's firmware posts for the same thing (gsgd.md, "Events"). The battery levels 0-5 (0x18-
# 0x1D), motion (0x17), USB changed (0x2D), a mode entered or left (0x06, 0x07) and a
# context's own codes (1, 2, 5) are the same on both.
EVENTS = {
    0x0F: 0x20, 0x10: 0x21,          # the battery level went up / down
    0x0D: 0x1E, 0x0E: 0x1F,          # the battery at level 6 / 7
    0x1F: 0x23, 0x1E: 0x22, 0x20: 0x24,  # external power connected / removed / changed
    0x21: 0x26,                      # the charger's state changed
    0x22: 0x27, 0x25: 0x2A, 0x23: 0x29,  # ... to off external power / charged / a fault
    0x26: 0x2B, 0x27: 0x2C, 0x28: 0x2D,  # USB connected / disconnected / changed
    0x29: 0x2E,                      # a page was drawn
    0x30: 0x31,                      # the touch screen touched: it wakes the remote
}


# A code that is the 800's own and no One code names - an event only the 800 posts - is
# written NATIVE | code, and tag() passes it as it is.
NATIVE = 0x10000


def tag(code: int) -> int:
    """The 800's list tag for a One key code: an event is renumbered to the 800's (EVENTS);
    a key or touch zone going down, the One's `0x80 | n`, is the 800's `0xC000 | n`
    (gsgd.md, "Lists"). A code marked NATIVE is the 800's already."""
    if code & NATIVE and code <= NATIVE | 0xFFFF:
        return code & 0xFFFF
    if code > 0xFF:                  # already an 800 tag: a keyboard key, say
        if code > 0xFFFF:
            raise ValueError(f"list tag {code!r} does not fit in 16 bits")
        return code
    if code < 0:
        raise ValueError(f"key code {code!r} is negative")
    return 0xC000 | (code & 0x7F) if code & 0x80 else EVENTS.get(code, code)


def key_register(entries: list[tuple[int, int, int]]) -> bytes:
    """Build one counted key register of ``(key code, object index, class)`` rows.

    A screen slot that binds no key at all has an empty register - 50 and 62 of them in
    the two broader donors - so zero entries is a shape the format uses, not a mistake.
    The count is one byte, and a screen's own button map is a register of 55 rows in
    every image measured, so the limit is 255. The narrower bound of 39 that `pages`
    uses is a rule for recognising a page while scanning section 9, not a rule of the
    format.
    """
    if len(entries) > 0xFF:
        raise ValueError("a Harmony 800 key register holds at most 255 entries")
    if len({key for key, _object, _category in entries}) != len(entries):
        raise ValueError("a Harmony 800 key register cannot repeat a key code")
    if not entries:
        # A leading zero is not "no rows": it selects the wide form, whose count is the
        # next byte. Every empty register in the donors is that form with a count of
        # zero, `00 00`; a lone `00` makes the reader take whatever follows as a count.
        return bytes(EMPTY_KEY_REGISTER)
    out = bytearray([len(entries)])
    for key, object_id, category in entries:
        if not 0 <= key <= 0xFFFF or not 0 <= object_id <= 0xFFFF:
            raise ValueError("key register key and object ID are outside their native ranges")
        out += struct.pack("<H", tag(key)) + _atom(object_id, category)
    return bytes(out)


def screen_slot(template: int, key_register_offset: int, program_offset: int) -> bytes:
    """Build the seven-byte section-6 slot record."""
    if isinstance(template, bool) or not isinstance(template, int) or not 0 <= template <= 0xFF:
        raise ValueError("a screen slot template must fit in one byte")
    return bytes([template]) + _pointer24(key_register_offset) + _pointer24(program_offset)


def screen_trailer(flag: int, header_offset: int, slot_offsets: list[int]) -> bytes:
    """Build the section-6 trailer that gathers one screen's slots."""
    if isinstance(flag, bool) or not isinstance(flag, int) or not 0 <= flag <= 0xFF:
        raise ValueError("a screen trailer flag must fit in one byte")
    if not slot_offsets or len(slot_offsets) > 0xFFFF:
        raise ValueError("a screen must declare between 1 and 65535 slots")
    out = bytearray([flag]) + _pointer24(header_offset)
    out += len(slot_offsets).to_bytes(2, "little")
    for offset in slot_offsets:
        out += _pointer24(offset)
    return bytes(out)


def screen_index(trailer_offsets: list[int]) -> bytes:
    """Build the section-6 screen index addressed by the master slot at 0x24."""
    if not trailer_offsets or len(trailer_offsets) > 0xFFFF:
        raise ValueError("section 6 must index between 1 and 65535 screens")
    out = bytearray(len(trailer_offsets).to_bytes(2, "little") + b"\x00")
    for offset in trailer_offsets:
        out += _pointer24(offset)
    return bytes(out)


def command_subtable(record_offsets: list[int]) -> bytes:
    """Build a section-5 per-device table pointing at record byte +11."""
    if len(record_offsets) > 0x100:
        raise ValueError("a Harmony 800 device cannot exceed 256 command ordinals")
    out = bytearray(b"\x00" + len(record_offsets).to_bytes(2, "little"))
    for offset in record_offsets:
        absolute = gspm.BASE + offset + 11
        if offset < 0 or absolute >= 1 << 24:
            raise ValueError("command record pointer does not fit in 24 bits")
        out += absolute.to_bytes(3, "little")
    return bytes(out)


def _align_window(out: bytearray, size: int) -> int:
    """Pad so a sequential native read stays inside one 64 KiB window."""
    if size <= 0 or size > ADDRESS_WINDOW:
        raise ValueError("native allocation must fit inside one 64 KiB window")
    if len(out) // ADDRESS_WINDOW != (len(out) + size - 1) // ADDRESS_WINDOW:
        out += bytes(ADDRESS_WINDOW - len(out) % ADDRESS_WINDOW)
    return len(out)


def context_record(context: dict) -> bytes:
    """Build one section-10 context from its parsed rows.

    A short context is a row count followed by four-byte rows; a long one opens with a
    zero, then its count, then five-byte rows whose extra leading byte the reader keeps
    as ``flags``. Which form a context uses is a property of the context, not of its
    contents, so it is carried rather than chosen.
    """
    rows = context["rows"]
    long_form = context["form"] == "long"
    if context["form"] not in ("short", "long"):
        raise ValueError(f"unknown section-10 context form {context['form']!r}")
    if not rows or len(rows) > 0xFF:
        raise ValueError("a section-10 context holds between 1 and 255 rows")
    out = bytearray(b"\x00" if long_form else b"")
    out.append(len(rows))
    for row in rows:
        if long_form:
            if row["flags"] is None:
                raise ValueError("a long-form context row needs its flags byte")
            out.append(row["flags"])
        elif row["flags"] is not None:
            raise ValueError("a short-form context row cannot carry a flags byte")
        out += struct.pack("<H", tag(row["key_code"])) + _atom(row["operand"], row["category"])
    return bytes(out)


# Section 4 opens with a generated table rather than a constant: two u24 headers - a
# first key and the count 30 - then thirty `{u24 key, u8 value}` records whose keys run
# up from that first key and whose values run 1 to 30, cut to 125 bytes. Household
# configurations start their keys at 10; the factory configuration shipped in the
# Harmony One firmware starts at 0, which is what showed the table was generated.
COMMAND_INDEX_KEYS = 30
COMMAND_INDEX_HEAD_SIZE = 125
HOUSEHOLD_FIRST_KEY = 10


def command_index_head(first_key: int = HOUSEHOLD_FIRST_KEY) -> bytes:
    """Build section 4's leading key table."""
    if isinstance(first_key, bool) or not isinstance(first_key, int) or first_key < 0:
        raise ValueError("the section 4 key table starts at a non-negative key")
    out = bytearray(first_key.to_bytes(3, "little")
                    + COMMAND_INDEX_KEYS.to_bytes(3, "little"))
    for index in range(COMMAND_INDEX_KEYS):
        out += (first_key + index).to_bytes(3, "little") + bytes([index + 1])
    return bytes(out[:COMMAND_INDEX_HEAD_SIZE])


def command_flat_index(devices: list[list[int]], *,
                       first_key: int = HOUSEHOLD_FIRST_KEY) -> bytes:
    """Build section 4: every command record again, counted and grouped by device.

    Section 5 reaches a command through its device's sub-table; section 4 lists the same
    records flat, each device's run introduced by its own count. Both point at the record
    plus eleven. The grouping matched section 5's exactly in all four images measured.
    """
    if len(devices) > 0xFF:
        raise ValueError("section 4 groups at most 255 devices")
    out = bytearray(command_index_head(first_key))
    for commands in devices:
        if len(commands) > 0xFFFF:
            raise ValueError("a device cannot hold more than 65535 commands")
        # Every run opens with a zero byte before its count, the first included. The
        # factory configuration in firmware settles this: with no devices at all its
        # section 4 is the head alone.
        out += b"\x00" + len(commands).to_bytes(2, "little")
        for offset in commands:
            absolute = gspm.BASE + offset + 11
            if offset < 0 or absolute >= 1 << 24:
                raise ValueError("a command record pointer does not fit in 24 bits")
            out += absolute.to_bytes(3, "little")
    return bytes(out)


# Section 3 is two markers around seven bytes holding a timestamp: second, minute, hour,
# day, weekday, month, year. Section 14's first seven records are the same clock, and
# their limits settle how the fields count - 59, 59, 23, 30, 6, 11 - so the day and the
# month count from zero, not from one. Reading them that way makes the fifth byte the
# weekday with Sunday as zero, which every image agrees with: 2007-10-25 Thursday 4,
# 2023-08-23 Wednesday 3, 2024-12-28 Saturday 6, 2015-08-02 Sunday 0, 2026-05-06
# Wednesday 3. Read one-based instead, two of those dates are the same weekday and carry
# different values, which is what left the byte unexplained.
STAMP_PREFIX = bytes.fromhex("dfad")
STAMP_SUFFIX = bytes.fromhex("bfef000000")
# Zero-based, so a day is 0 to 30 and a month 0 to 11.
STAMP_LIMITS = (("second", 59), ("minute", 59), ("hour", 23), ("day", 30),
                ("weekday", 6), ("month", 11), ("year", 255))


def stamp_weekday(day: int, month: int, year: int) -> int:
    """The weekday a zero-based day and month fall on, counting Sunday as zero."""
    import datetime
    return (datetime.date(year, month + 1, day + 1).weekday() + 1) % 7


def read_stamp(payload: bytes) -> dict:
    """Read section 3's timestamp, or say why it cannot be read."""
    start, end = gspm.section_ranges(payload)[3]
    body = payload[start:end]
    if (len(body) != len(STAMP_PREFIX) + 7 + len(STAMP_SUFFIX)
            or not body.startswith(STAMP_PREFIX) or not body.endswith(STAMP_SUFFIX)):
        raise ValueError("section 3 is not the measured marker-wrapped stamp")
    second, minute, hour, day, weekday, month, year = body[2:9]
    in_range = (second < 60 and minute < 60 and hour < 24
                and day <= 30 and month <= 11 and weekday <= 6)
    agrees = None
    if in_range:
        agrees = weekday == stamp_weekday(day, month, 2000 + year)
    return {
        "second": second, "minute": minute, "hour": hour, "day": day,
        "month": month, "year": 2000 + year, "weekday": weekday,
        # Whether the stored weekday is the one the date actually falls on.
        "weekday_agrees": agrees,
        "in_range": in_range,
    }


def stamp(second: int, minute: int, hour: int, day: int, month: int, year: int,
          weekday: int | None = None) -> bytes:
    """Build section 3. The day and the month count from zero, as section 14's do.

    ``weekday`` is derived from the date when it is not given, and checked against it
    when it is, because a stored weekday that disagrees with its own date is how this
    field came to be called unexplained.
    """
    values = (second, minute, hour, day,
              0 if weekday is None else weekday, month, year - 2000)
    for value, (label, limit) in zip(values, STAMP_LIMITS):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
            raise ValueError(
                f"section 3 {label} is outside its measured range of 0 to {limit}")
    actual = stamp_weekday(day, month, year)
    if weekday is None:
        weekday = actual
    elif weekday != actual:
        raise ValueError(
            f"section 3 weekday {weekday} disagrees with the date, which is {actual}")
    return (STAMP_PREFIX
            + bytes([second, minute, hour, day, weekday, month, year - 2000])
            + STAMP_SUFFIX)


def font_record(font: dict, placed: dict[int, int]) -> bytes:
    """Write a font's header and its glyph index, in the header layout it was read in."""
    slots = font["slots"]
    if font["layout"] == font_index.BYTE_COUNT:
        if slots > 0xFF:
            raise ValueError("this font header cannot count more than 255 glyphs")
        head = bytes([font["height"], 1, slots])
    else:
        head = bytes([font["height"]]) + slots.to_bytes(2, "little")
    out = bytearray(head)
    for code in range(1, slots + 1):
        offset = placed.get(code)
        out += (0 if offset is None else gspm.BASE + offset).to_bytes(3, "little")
    return bytes(out)


def engine_record(record: dict) -> bytes:
    """One section-14 property: its initial state, its limit, and its transitions."""
    out = struct.pack("<HHH", record["initial"], record["limit"],
                      len(record["transitions"]))
    out += bytes([record["padding"]])
    for row in record["transitions"]:
        out += struct.pack("<BHHHB", row["flags"], row["from"], row["to"],
                           row["operand"], row["category"])
    return out


# Section 14's header, measured in the factory image and both donors: a count, one less
# than the count, a one, and one less than the count again, then a pointer per record.
def engine_index(records: list[int]) -> bytes:
    count = len(records)
    if count > 0xFFFF:
        raise ValueError("section 14 indexes at most 65535 engine records")
    trailing = max(0, count - 1)
    return (struct.pack("<HHHH", count, trailing, 1, trailing)
            + b"".join((gspm.BASE + offset).to_bytes(3, "little") for offset in records))


def name_chain(records: list[bytes] = ()) -> bytes:
    """Section 0. An empty chain declares zero, which is what the factory image writes."""
    body = b"".join(records)
    if not body:
        return b"\xed\xfe\x00\x00\x00\xef\xbe"
    return (b"\xed\xfe" + (3 + len(body) + 2).to_bytes(3, "little") + body + b"\xef\xbe")


def counted_index(offsets: list[int], *, width: int, label: str) -> bytes:
    """A count of the given width, then one 24-bit pointer per entry."""
    limit = 0xFF if width == 1 else 0xFFFF
    if len(offsets) > limit:
        raise ValueError(f"{label} indexes at most {limit} entries")
    return (len(offsets).to_bytes(width, "little")
            + b"".join((gspm.BASE + offset).to_bytes(3, "little") for offset in offsets))


def name_record(identifier: int, name: str, *, leaf: bool = True) -> bytes:
    """One section-0 named record: `a7`, a length, a type, an id, then the name."""
    encoded = name.encode("utf-8")
    if not encoded:
        raise ValueError("a named record needs a name")
    length = 4 + len(encoded)
    if length > 0xFFFF:
        raise ValueError("a named record is too long to declare its own length")
    return (b"\xa7" + length.to_bytes(2, "little")
            + (1 if leaf else 0).to_bytes(2, "little")
            + identifier.to_bytes(2, "little") + encoded)


OBJECT_ATOM = 0x7F
DRAW_OVERLAY = 0x73   # run section-12 program n: the status bar's clock, battery and signal
COMPARE = 0x71
ENTER_MODE = 0x7E


def timer_record(flags: int, duration: int, operand: int, opcode: int) -> bytes:
    """A section-13 timer: flags, a 24-bit duration, then the instruction it runs."""
    return (bytes([flags]) + duration.to_bytes(3, "little")
            + struct.pack("<HB", *lights.instruction(operand, opcode)))


def object_body(atoms) -> bytes:
    """A section-11 object: a count, then one `(u16 operand, u8 category)` per atom."""
    return bytes([len(atoms)]) + b"".join(
        struct.pack("<HB", *lights.instruction(operand, category)) for operand, category in atoms)


def touch_zone(zone: dict, offset: int) -> bytes:
    """One twelve-byte zone: its rectangle, its tag, and a pointer back to itself."""
    from . import geometry
    zone = geometry.touch_zone(zone)
    return (struct.pack("<HHHH", zone["x"], zone["width"], zone["y"], zone["height"])
            + bytes([zone["tag"]])
            + (gspm.BASE + offset).to_bytes(3, "little"))
