"""The 800's lists: handler lists, key registers and contexts, and the instructions in them.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

import struct

from . import lights

KEY_DOWN = 0xC000
KEY_UP = 0x8000
MAX_ROWS = 0xFF

# Events a screen's list or a context answers (gsgd.md, "Lists").
ENTER = 0x06
LEAVE = 0x07

# Opcodes (gsgd.md, "Instructions").
OBJECT = 0x7F
SCREEN = 0x7E
IR_SEND = 0x7D
IR_REPEAT = 0x7C
NOTHING = (0x0000, 0x00)


def instruction(operand: int, opcode: int) -> bytes:
    if isinstance(operand, bool) or not isinstance(operand, int) or not 0 <= operand <= 0xFFFF:
        raise ValueError(f"instruction operand {operand!r} does not fit in 16 bits")
    if isinstance(opcode, bool) or not isinstance(opcode, int) or not 0 <= opcode <= 0xFF:
        raise ValueError(f"opcode {opcode!r} does not fit in a byte")
    return struct.pack("<HB", *lights.instruction(operand, opcode))


def wide(rows: list[tuple[int, int, int]], *, flags: int = 0) -> bytes:
    """``00 00 count {flags, u16 tag, instruction}``: the form the factory images use for
    every screen's list, and the only one that holds an empty list unambiguously."""
    if len(rows) > MAX_ROWS:
        raise ValueError(f"a list holds at most {MAX_ROWS} rows, not {len(rows)}")
    out = bytearray(b"\x00\x00" + bytes([len(rows)]))
    for tag, operand, opcode in rows:
        if not 0 <= tag <= 0xFFFF:
            raise ValueError(f"list tag {tag!r} does not fit in 16 bits")
        out += bytes([flags]) + struct.pack("<H", tag) + instruction(operand, opcode)
    return bytes(out)


def read(payload: bytes, offset: int) -> list[dict]:
    """A list as ``FUN_08017f1c`` searches it."""
    first = payload[offset]
    if first:
        return [{"flags": None, "tag": struct.unpack_from("<H", payload, offset + 1 + 5 * j)[0],
                 "operand": struct.unpack_from("<H", payload, offset + 3 + 5 * j)[0],
                 "opcode": payload[offset + 5 + 5 * j]} for j in range(first)]
    count, at = payload[offset + 1], offset + 2
    if not count:
        count, at = payload[offset + 2], offset + 3
    return [{"flags": payload[at + 6 * j], "tag": struct.unpack_from("<H", payload, at + 6 * j + 1)[0],
             "operand": struct.unpack_from("<H", payload, at + 6 * j + 3)[0],
             "opcode": payload[at + 6 * j + 5]} for j in range(count)]


def object_body(atoms) -> bytes:
    """A section-11 object: its instruction count, then the instructions."""
    atoms = list(atoms)
    if not 1 <= len(atoms) <= 0xFF:
        raise ValueError("an object holds between 1 and 255 instructions")
    return bytes([len(atoms)]) + b"".join(instruction(*atom) for atom in atoms)
