"""Encode the Harmony One drawing bytecode the reader disassembles.

Everything else this backend authors is a counted table it can serialize. Drawing
programs are the exception: they are bytecode holding absolute pointers to other
programs, to bitmaps and to glyph strings, so until they can be emitted rather than
copied, a configuration can only be patched in place - never laid out afresh.

This module closes that gap at the smallest useful scale: an encoder that is the exact
inverse of the reader, proved by re-encoding every instruction of every reachable
program in a donor and getting its own bytes back. Relocating or generating a program
is then a matter of what addresses the instructions are given, not of guessing their
shape.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import gspm, ui_index


END = 0x00
RECTANGLE = 0x01
BITMAP = 0x02
TEXT = 0x04
INLINE_TEXT = 0x05
ATTRIBUTE = 0x10
ATOM = 0x11
SWITCH = 0x12
JUMP = 0x14
CALL = 0x16
RETURN = 0x17

# The instruction fields that hold an absolute address, by opcode. Everything else an
# instruction carries is a literal and moves with it unchanged.
ADDRESS_FIELDS = {
    "call": ("target",),
    "jump": ("target",),
    "bitmap": ("target",),
    "text": ("target",),
}


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
    if opcode == "return":
        return bytes([RETURN])
    if opcode in ("call", "jump"):
        return bytes([CALL if opcode == "call" else JUMP]) + _pointer(instruction["target"])
    if opcode == "attribute":
        return bytes([ATTRIBUTE]) + _byte(instruction["value"], "a font attribute")
    if opcode in ("bitmap", "text"):
        return (bytes([BITMAP if opcode == "bitmap" else TEXT])
                + _byte(instruction["x"], "an x coordinate")
                + _byte(instruction["y"], "a y coordinate")
                + _pointer(instruction["target"]))
    if opcode == "inline_text":
        glyphs = bytes.fromhex(instruction["glyphs"])
        if END in glyphs:
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
    if instructions[-1]["opcode"] not in ("end", "return", "jump"):
        raise ValueError(
            "a drawing program must finish at end, return or jump, not "
            + instructions[-1]["opcode"])
    return b"".join(encode(item) for item in instructions)


def relocated(instructions: list[dict], mapping: dict[int, int]) -> list[dict]:
    """Return the same instructions with every address field remapped.

    An address the mapping does not name is left alone, which is what keeps a program
    that points into resources it does not own - bitmaps, glyph strings, blocks it only
    calls - working when only some blocks move.
    """
    out = []
    for item in instructions:
        fields = ADDRESS_FIELDS.get(item["opcode"])
        moved = dict(item)
        for field in fields or ():
            moved[field] = mapping.get(item[field], item[field])
        if item["opcode"] == "switch":
            moved["cases"] = [
                (value, mapping.get(target, target))
                for value, target in item["cases"]
            ]
            moved["ranges"] = [
                (low, high, mapping.get(target, target))
                for low, high, target in item["ranges"]
            ]
        out.append(moved)
    return out


def program_blocks(payload: bytes, roots) -> dict[int, list[dict]]:
    """Disassemble every program reachable from ``roots``, keyed by its own address."""
    programs12 = ui_index.section12_programs(payload)
    blocks: dict[int, list[dict]] = {}
    stack = list(roots)
    while stack:
        offset = stack.pop()
        if offset in blocks:
            continue
        program = ui_index.drawing_program(payload, offset)
        if program["stopped"] not in ("end", "return", "jump"):
            raise ValueError(
                f"the program at {offset:#x} stops at {program['stopped']}, so it "
                "cannot be emitted")
        blocks[offset] = program["instructions"]
        for item in program["instructions"]:
            if item["opcode"] in ("call", "jump"):
                stack.append(item["target"])
            elif item["opcode"] == "switch":
                stack.extend(target for _value, target in item["cases"])
                stack.extend(target for _low, _high, target in item["ranges"])
            elif item["opcode"] == "atom" and item["category"] == 0x73:
                subprogram = programs12.get(item["operand"])
                if subprogram is not None:
                    stack.append(subprogram)
    return blocks


def lay_out(blocks: dict[int, list[dict]], at: int, *,
            mapping: dict[int, int] | None = None) -> tuple[bytes, dict[int, int]]:
    """Emit every block one after another from ``at`` and return the address map.

    Every block ends at end, return or jump, so none falls through into its neighbour
    and the order is free; they are laid out in their original order anyway, which
    keeps a diff between an image and its re-emission readable.

    ``mapping`` seeds the addresses already decided elsewhere - the pictures and glyph
    strings these blocks draw - so a block's references to them move too.
    """
    mapping = dict(mapping or {})
    cursor = at
    for offset in sorted(blocks):
        mapping[offset] = cursor
        cursor += len(encode_program(blocks[offset]))
    body = b"".join(
        encode_program(relocated(blocks[offset], mapping))
        for offset in sorted(blocks)
    )
    return body, mapping
