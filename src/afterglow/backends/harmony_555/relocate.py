"""Find every pointer an arch-9 image holds, and move bytes without breaking one.

A 5xx configuration addresses its structures absolutely, so a structure can grow or a new
one go in only if every pointer to what follows it moves too. This module lists each
pointer field by walking the structures the readers read - the section table, the counted
indexes, screens and pages, drawing programs, fonts, the infrared chain, state variables
and switch tables - and refuses an image where two walks disagree or a field would point
nowhere. `insert` then opens a gap and moves every field and target past it.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

import struct

from . import gspm, ui_index

HEADER_FIELDS = 4          # the end vector, a u32 at offset 4


def _u24(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset:offset + 3], "little")


class Census:
    """Every three-byte pointer field in an image, field offset to target offset."""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.fields: dict[int, int] = {}
        self.walked_programs: set[int] = set()
        ranges = gspm.section_ranges(payload)
        self.ranges = ranges
        self._section_table()
        self._screens(ranges[6][0])
        self._fonts(ranges[7][0])
        self._infrared(ranges[5][0])
        self._counted(ranges[10][0], payload[ranges[10][0]], 1)            # contexts
        self._counted(ranges[11][0], _h(payload, ranges[11][0]), 2)        # objects
        programs = self._counted(ranges[12][0], _h(payload, ranges[12][0]), 2)
        self._counted(ranges[13][0], payload[ranges[13][0]], 1)            # timers
        self._counted(ranges[14][0] + 6, _h(payload, ranges[14][0]), 2)    # state variables
        tables = self._counted(ranges[15][0], payload[ranges[15][0]], 1)
        self._counted(ranges[16][0], payload[ranges[16][0]], 1)            # section 16
        for table in tables:
            self._switch_table(table)
        for program in programs:
            self._program(program)

    def point(self, field: int, *, allow_zero: bool = False) -> int | None:
        """Record the pointer at ``field``; its target, or None for a zero pointer."""
        absolute = _u24(self.payload, field)
        if not absolute and allow_zero:
            return None
        target = absolute - gspm.BASE
        if not 0 <= target < len(self.payload):
            raise ValueError(f"pointer at {field:#x} reaches {absolute:#08x}, outside the image")
        if self.fields.get(field, target) != target:
            raise ValueError(f"pointer at {field:#x} was read two ways")
        self.fields[field] = target
        return target

    def _section_table(self) -> None:
        for slot in range(len(gspm.SLOT_SECTIONS)):
            self.point(gspm.TABLE_OFFSET + 4 * slot + 1)

    def _counted(self, start: int, count: int, header: int) -> list[int]:
        return [self.point(start + header + 3 * index) for index in range(count)]

    def _screens(self, start: int) -> None:
        payload = self.payload
        for trailer in self._counted(start, _h(payload, start), 3):
            self.point(trailer + 1)                                 # the physical-key list
            for slot in self._counted(trailer + 4, _h(payload, trailer + 4), 2):
                self.point(slot)                                    # the page's key list
                self._program(self.point(slot + 3))

    def _program(self, offset: int) -> None:
        stack = [offset]
        while stack:
            at = stack.pop()
            if at in self.walked_programs:
                continue
            self.walked_programs.add(at)
            program = ui_index.drawing_program(self.payload, at, limit=4000)
            if program["stopped"] not in ("end", "jump"):
                raise ValueError(f"drawing program {at:#x} stops at {program['stopped']}")
            for item in program["instructions"]:
                where = item["offset"]
                kind = item["opcode"]
                if kind in ("text", "bitmap"):
                    self.point(where + 3)
                elif kind == "sized_bitmap":
                    self.point(where + 7)
                elif kind == "jump":
                    stack.append(self.point(where + 1))
                elif kind == "switch" and not item.get("wide"):
                    cursor = where + 3
                    for _value, _target in item["cases"]:
                        stack.append(self.point(cursor + 1))
                        cursor += 4
                    cursor += 1
                    for _range in item["ranges"]:
                        stack.append(self.point(cursor + 2))
                        cursor += 5
                elif kind == "switch":
                    cursor = where + 4
                    for _value, _target in item["cases"]:
                        stack.append(self.point(cursor + 2))
                        cursor += 5

    def _switch_table(self, at: int) -> None:
        # 02, a u8 case count, {u16 value, u24 block} cases, a u8 range count
        cursor = at + 2
        for _case in range(self.payload[at + 1]):
            self._program(self.point(cursor + 2))
            cursor += 5
        for _range in range(self.payload[cursor]):
            self._program(self.point(cursor + 5))
            cursor += 7

    def _fonts(self, start: int) -> None:
        payload = self.payload
        from . import font_index

        fonts = self._counted(start, _h(payload, start), 2)
        for font in font_index.fonts(payload):
            for glyph in font["glyphs"].values():
                self.point(glyph["field"])
        if len(fonts) != len(font_index.fonts(payload)):
            raise ValueError("section 7 counts its fonts two ways")

    def _infrared(self, start: int) -> None:
        payload = self.payload
        tables = set()
        for subtable in self._counted(start, payload[start], 1):
            for target in self._counted(subtable, _h(payload, subtable + 1), 3):
                record = target - 11
                self.point(record + 12)                             # its own address + 4
                fields = (16, 19, 22, 25, 28, 31) if payload[record + 15] == 2 else (16, 19, 22)
                for field in fields:
                    body = self.point(record + field, allow_zero=True)
                    if body is not None:
                        tables.add(self.point(body))
        for table in tables:
            for index in range(payload[table]):
                self.point(table + 1 + 3 * index)


def _h(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<H", payload, offset)[0]


def pointers(payload: bytes) -> dict[int, int]:
    """Every pointer field in ``payload`` and the offset it points at."""
    return dict(Census(payload).fields)


def insert(payload: bytes, at: int, data: bytes, census: dict[int, int] | None = None
           ) -> bytes:
    """``payload`` with ``data`` inserted at ``at``, every pointer moved to follow what it
    pointed at, and the image sealed again. A target at ``at`` itself moves too: the
    inserted bytes go in front of what was there."""
    fields = pointers(payload) if census is None else census
    end = struct.unpack_from("<I", payload, 4)[0] - gspm.BASE - 2
    if not gspm.TABLE_OFFSET + 4 * gspm.TABLE_ITEMS <= at <= end:
        raise ValueError(f"cannot insert at {at:#x}, outside the image's body")
    shift = len(data)
    out = bytearray(payload[:at] + data + payload[at:end])
    for field, target in fields.items():
        moved = field + shift if field >= at else field
        out[moved:moved + 3] = (gspm.BASE + target + (shift if target >= at else 0)
                                ).to_bytes(3, "little")
    if gspm.BASE + len(out) + 6 > 1 << 24:
        raise ValueError("the image no longer fits its 24-bit addresses")
    return gspm.seal(bytes(out))
