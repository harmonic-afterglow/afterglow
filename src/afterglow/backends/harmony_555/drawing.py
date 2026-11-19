"""Encode the drawing bytecode the reader disassembles (arch 9: 96 x 64, drawn by rows).

Everything else this backend authors is a counted table it can serialize. Drawing
programs are the exception: they are bytecode holding absolute pointers to other
programs, to bitmaps and to glyph strings, so until they can be emitted rather than
copied, a configuration can only be patched in place - never laid out afresh.

This module closes that gap at the smallest useful scale: an encoder that is the exact
inverse of the reader, proved by re-encoding every instruction of every reachable
program in a donor and getting its own bytes back. Relocating or generating a program
is then a matter of what addresses the instructions are given, not of guessing their
shape.

Format reference: docs/harmony_5xx/ahcm.md, docs/harmony_650_700/gspm.md
"""

from __future__ import annotations

import struct

from . import gspm


END = 0x00
RECTANGLE = 0x01
BITMAP = 0x02
SIZED_BITMAP = 0x03
TEXT = 0x04
INLINE_TEXT = 0x05
ATTRIBUTE = 0x10
ATOM = 0x11
SWITCH = 0x12
WIDE_SWITCH = 0x13
JUMP = 0x14
ROW = 0x16
TRANSFER = 0x17

# The instruction fields that hold an absolute address, by opcode. Everything else an
# instruction carries is a literal and moves with it unchanged.
ADDRESS_FIELDS = {
    "jump": ("target",),
    "bitmap": ("target",),
    "sized_bitmap": ("target",),
    "text": ("target",),
}


# A glyph code is one byte up to 0x7F; past it, two: the first with its high bit set,
# `((first << 8) | second) & 0x7FFF` - the Harmony 800's text VM reads codes so - which is
# how a font holds more than 127 characters. The second byte may be zero.
MAX_GLYPH_CODE = 0x7FFF


class GlyphCodes(bytes):
    """A line of text as its stored bytes; iterating it gives the codes."""

    @classmethod
    def of(cls, codes) -> "GlyphCodes":
        out = bytearray()
        for code in codes:
            if not 0 < code <= MAX_GLYPH_CODE:
                raise ValueError(f"glyph code {code} is outside 1..{MAX_GLYPH_CODE}")
            out += bytes([code]) if code < 0x80 else bytes([0x80 | code >> 8, code & 0xFF])
        return cls(out)

    def __iter__(self):
        return iter(glyph_codes(bytes(self)))


def glyph_codes(stored: bytes) -> list[int]:
    """The codes a stored line of glyphs holds."""
    out, at = [], 0
    while at < len(stored):
        first = stored[at]
        if first & 0x80:
            if at + 1 >= len(stored):
                raise ValueError("a two-byte glyph code is cut short")
            out.append(((first << 8) | stored[at + 1]) & MAX_GLYPH_CODE)
            at += 2
        else:
            out.append(first)
            at += 1
    return out


def glyphs_end(payload: bytes, offset: int) -> int:
    """Where a zero-terminated line of glyphs at ``offset`` ends (its terminator), the
    second byte of a two-byte code - which may be zero - skipped; -1 if it runs out."""
    at = offset
    while at < len(payload):
        if payload[at] == 0:
            return at
        at += 2 if payload[at] & 0x80 else 1
    return -1


def _pointer(offset: int) -> bytes:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("a drawing pointer must address a non-negative offset")
    absolute = gspm.BASE + offset
    if absolute >= 1 << 24:
        raise ValueError("a drawing pointer does not fit in 24 bits")
    return absolute.to_bytes(3, "little")


def _byte(value: int, label: str) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFF:
        raise ValueError(f"{label} must fit in one byte")
    return bytes([value])


def encode(instruction: dict) -> bytes:
    """Return the bytes of one disassembled instruction."""
    opcode = instruction["opcode"]
    if opcode == "end":
        return bytes([END])
    if opcode == "row":
        return bytes([ROW]) + _byte(instruction["value"], "a display row")
    if opcode == "transfer":
        return bytes([TRANSFER])
    if opcode == "jump":
        return bytes([JUMP]) + _pointer(instruction["target"])
    if opcode == "attribute":
        return bytes([ATTRIBUTE]) + _byte(instruction["value"], "a font attribute")
    if opcode in ("bitmap", "text"):
        return (bytes([BITMAP if opcode == "bitmap" else TEXT])
                + _byte(instruction["x"], "an x coordinate")
                + _byte(instruction["y"], "a y coordinate")
                + _pointer(instruction["target"]))
    if opcode == "sized_bitmap":
        reserved = bytes.fromhex(instruction.get("reserved", "0000"))
        if len(reserved) != 2:
            raise ValueError("a sized picture carries exactly two reserved bytes")
        return (bytes([SIZED_BITMAP])
                + _byte(instruction["x"], "an x coordinate")
                + _byte(instruction["y"], "a y coordinate") + reserved
                + _byte(instruction["width"], "a picture width")
                + _byte(instruction["height"], "a picture height")
                + _pointer(instruction["target"]))
    if opcode == "inline_text":
        glyphs = bytes.fromhex(instruction["glyphs"])
        if 0 in glyph_codes(glyphs):
            raise ValueError("inline text cannot contain its own terminator")
        return (bytes([INLINE_TEXT])
                + _byte(instruction["x"], "an x coordinate")
                + _byte(instruction["y"], "a y coordinate")
                + glyphs + bytes([END]))
    if opcode == "atom":
        return bytes([ATOM]) + struct.pack(
            "<HB", instruction["operand"], instruction["category"])
    if opcode == "rectangle":
        return bytes([RECTANGLE]) + struct.pack(
            "<BBBBH", instruction["x"], instruction["y"], instruction["width"],
            instruction["height"], instruction["color"])
    if opcode == "switch" and instruction.get("wide"):
        if instruction["ranges"]:
            raise ValueError("a wide switch with ranges has never been measured")
        out = bytearray([WIDE_SWITCH])
        out += _byte(instruction["selector"], "a switch selector")
        out += struct.pack("<H", len(instruction["cases"]))
        for value, target in instruction["cases"]:
            out += struct.pack("<H", value) + _pointer(target)
        return bytes(out + struct.pack("<H", 0))
    if opcode == "switch":
        out = bytearray([SWITCH])
        out += _byte(instruction["selector"], "a switch selector")
        out += _byte(len(instruction["cases"]), "a switch case count")
        for value, target in instruction["cases"]:
            out += _byte(value, "a switch case value") + _pointer(target)
        out += _byte(len(instruction["ranges"]), "a switch range count")
        for low, high, target in instruction["ranges"]:
            out += (_byte(low, "a switch range start")
                    + _byte(high, "a switch range end") + _pointer(target))
        return bytes(out)
    raise ValueError(f"the drawing encoder does not emit {opcode!r} instructions")


def encode_program(instructions: list[dict]) -> bytes:
    """Return the bytes of a whole disassembled program."""
    if not instructions:
        raise ValueError("a drawing program needs at least one instruction")
    if instructions[-1]["opcode"] not in ("end", "jump"):
        raise ValueError(
            "a drawing program must finish at end or jump, not "
            + instructions[-1]["opcode"])
    return b"".join(encode(item) for item in instructions)
