"""Read Harmony One screen key registers without assigning button vocabulary.

Section 6 reaches the exact key registers used by each screen. Command resolution then
follows section-11 object references to IDs already owned by section 5. Navigation,
multi-command actions, and other classes stay explicitly counted rather than being
flattened into portable hard-key assignments.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from collections import Counter
import struct

from . import command_index, gspm


def _u24(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset:offset + 3], "little")


def _relative(payload: bytes, offset: int, label: str) -> int:
    if not (0 <= offset and offset + 3 <= len(payload)):
        raise ValueError(f"{label} pointer field falls outside the GSPM image")
    absolute = _u24(payload, offset)
    relative = absolute - gspm.BASE
    if not 0 <= relative < len(payload):
        raise ValueError(f"{label} points outside the GSPM image: {absolute:#08x}")
    return relative


def object_targets(objects: list[dict], index: int) -> list[tuple[int, int]] | None:
    """Resolve the measured direct-or-one-jump object path."""
    if not 0 <= index < len(objects):
        return None
    targets = []
    for operand, opcode in objects[index]["atoms"]:
        if opcode in (0x7C, 0x7D, 0x7E):
            targets.append((operand, opcode))
        elif opcode == 0x7F and 0 <= operand < len(objects):
            targets.extend(
                (nested_operand, nested_opcode)
                for nested_operand, nested_opcode in objects[operand]["atoms"]
                if nested_opcode in (0x7C, 0x7D, 0x7E)
            )
    return targets


def inspect(payload: bytes, ownership: dict | None = None) -> dict:
    """Inventory screen key bindings reached through the native section indexes."""
    ownership = command_index.inspect(payload) if ownership is None else ownership
    indexed_commands = {
        command["command_id"]
        for device in ownership["devices"] for command in device["commands"]
    }
    objects = command_index.objects(payload)
    start, end = gspm.section_ranges(payload)[6]
    if start + 3 > end:
        raise ValueError("GSPM section 6 has no screen index header")
    screen_count = struct.unpack_from("<H", payload, start)[0]
    if payload[start + 2] != 0:
        raise ValueError("GSPM section 6 screen index has a non-zero reserved byte")
    if not screen_count or start + 3 + 3 * screen_count > end:
        raise ValueError(
            f"GSPM section 6 declares {screen_count} screens outside its index")

    counts = Counter(screens=screen_count)
    rejected = Counter()
    bindings = []
    for screen in range(screen_count):
        trailer = _relative(
            payload, start + 3 + 3 * screen, f"section 6 screen {screen}")
        if trailer + 6 > len(payload):
            raise ValueError(f"screen {screen} trailer is truncated")
        slot_count = struct.unpack_from("<H", payload, trailer + 4)[0]
        if not slot_count or trailer + 6 + 3 * slot_count > len(payload):
            raise ValueError(f"screen {screen} has an invalid slot table")
        counts["slots"] += slot_count

        for slot in range(slot_count):
            slot_offset = _relative(
                payload, trailer + 6 + 3 * slot,
                f"screen {screen} slot {slot}")
            if slot_offset + 7 > len(payload):
                raise ValueError(f"screen {screen} slot {slot} is truncated")
            template = payload[slot_offset]
            key_register = _relative(
                payload, slot_offset + 1,
                f"screen {screen} slot {slot} key register")
            program = _relative(
                payload, slot_offset + 4,
                f"screen {screen} slot {slot} program")
            entry_count = payload[key_register]
            if key_register + 1 + 4 * entry_count > len(payload):
                raise ValueError(
                    f"screen {screen} slot {slot} key register is truncated")
            counts["key_registers"] += 1
            counts["entries"] += entry_count

            for entry in range(entry_count):
                offset = key_register + 1 + 4 * entry
                key_code = payload[offset]
                object_index, category = struct.unpack_from("<HB", payload, offset + 1)
                if category != 0x7F:
                    counts["other_class_bindings"] += 1
                    continue
                targets = object_targets(objects, object_index)
                if targets is None:
                    rejected["invalid_object_index"] += 1
                    continue
                commands = {value for value, opcode in targets if opcode == 0x7D}
                devices = {value for value, opcode in targets if opcode == 0x7C}
                pages = {value for value, opcode in targets if opcode == 0x7E}
                if not commands:
                    if pages:
                        counts["page_bindings"] += 1
                    else:
                        rejected["object_without_command_or_page"] += 1
                    continue
                if len(commands) != 1 or len(devices) > 1:
                    rejected["ambiguous_command_action"] += 1
                    continue
                command_id = next(iter(commands))
                device_ids = sorted(devices)
                if command_id not in indexed_commands:
                    rejected["command_without_section5_record"] += 1
                    continue
                if device_ids and device_ids[0] >> 8 != command_id >> 8:
                    rejected["command_device_mismatch"] += 1
                    continue
                bindings.append({
                    "screen": screen,
                    "slot": slot,
                    "template": template,
                    "key_code": key_code,
                    "object_index": object_index,
                    "command_id": command_id,
                    "device_ids": device_ids,
                    "target_pages": sorted(pages),
                    "key_register_offset": key_register,
                    "program_offset": program,
                })
                counts["command_bindings"] += 1

    for key in (
            "screens", "slots", "key_registers", "entries", "command_bindings",
            "page_bindings", "other_class_bindings"):
        counts[key] += 0
    return {
        "counts": dict(counts),
        "rejected": dict(rejected),
        "bindings": bindings,
    }
