"""Bounded inventory of native Harmony One objects and command records.

This module reports structures without assigning portable meaning to them. Classification
is evidence for the next importer slice, not permission to mutate or relocate the image.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from collections import defaultdict
import struct

from . import activity_index, command_index, gspm, key_index, named_index, ui_index


LEAD_IN = 0x7FFF


def _u24(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset:offset + 3], "little")


def object_inventory(payload: bytes) -> dict:
    """Inventory the section-11 master object table and every bounded object."""
    ranges = gspm.section_ranges(payload)
    start, end = ranges[11]
    count = struct.unpack_from("<H", payload, start)[0]
    table_end = start + 2 + count * 3
    if not count or table_end > end:
        raise ValueError(
            f"GSPM object table declares {count} entries outside section 11")

    pointers = tuple(_u24(payload, start + 2 + index * 3) - gspm.BASE
                     for index in range(count))
    if list(pointers) != sorted(set(pointers)):
        raise ValueError("GSPM object pointers are not unique and ascending")
    checksum_offset = struct.unpack_from("<I", payload, 4)[0] - gspm.BASE - 2
    per_opcode: dict[int, list[int]] = defaultdict(list)
    atoms = 0
    for index, pointer in enumerate(pointers):
        if not 0 <= pointer < checksum_offset:
            raise ValueError(
                f"GSPM object {index} points outside the configuration: {pointer:#x}")
        atom_count = payload[pointer]
        object_end = pointer + 1 + atom_count * 3
        next_pointer = pointers[index + 1] if index + 1 < count else checksum_offset
        if object_end > next_pointer:
            raise ValueError(f"GSPM object {index} overlaps the next native object")
        atoms += atom_count
        for atom in range(atom_count):
            offset = pointer + 1 + atom * 3
            operand, opcode = struct.unpack_from("<HB", payload, offset)
            per_opcode[opcode].append(operand)

    reference_opcodes = sorted(
        opcode for opcode, operands in per_opcode.items()
        if operands and all(operand < count for operand in operands)
    )
    return {
        "objects": count,
        "atoms": atoms,
        "opcodes": len(per_opcode),
        "reference_opcodes": reference_opcodes,
    }


def command_inventory(payload: bytes, ownership: dict | None = None) -> dict:
    """Count records reached by the firmware's section-5 command index."""
    ownership = command_index.inspect(payload) if ownership is None else ownership
    records = [record for device in ownership["devices"] for record in device["commands"]]
    return {
        "commands": len(records),
        "repeating_commands": sum("hold" in record["waveforms"] for record in records),
        "record_offsets": [record["record_offset"] for record in records],
    }


def inspect(payload: bytes) -> dict:
    ownership = command_index.inspect(payload)
    ui = ui_index.inspect(payload, ownership)
    try:
        names = named_index.inspect(payload)
    except ValueError as error:
        names = {
            "counts": {"records": 0, "containers": 0, "leaves": 0, "other_types": 0},
            "rejected": {"invalid_named_record_structure": 1},
            "error": str(error), "records": [],
        }
    try:
        activities = activity_index.inspect(payload, ownership, names)
    except ValueError as error:
        activities = {
            "counts": {
                "contexts": 0, "context_rows": 0, "engine_properties": 0,
                "engine_transitions": 0, "activities": 0, "determined_activities": 0,
                "menu_activities": 0, "mixed_device_screens": 0, "engine_commands": 0,
                "physical_context_rows": 0, "editable_physical_context_rows": 0,
            },
            "rejected": {"invalid_activity_structure": 1}, "error": str(error),
            "menu": None, "activities": [], "mixed_device_screens": [],
            "physical_contexts": {"counts": {"contexts": 0, "rows": 0,
                                               "editable_rows": 0},
                                  "rejected": {}, "contexts": []},
        }
    return {
        "objects": object_inventory(payload),
        "commands": command_inventory(payload, ownership),
        "ownership": ownership,
        "keys": key_index.inspect(payload, ownership),
        "ui": ui,
        "names": names,
        "activities": activities,
    }
