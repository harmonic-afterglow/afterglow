"""Native Harmony One records needed by device and key authoring.

These helpers serialize only measured structures. They do not select screen artwork or
make a configuration writable on their own.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from collections import Counter
import struct

from . import (
    activity_index,
    command_index,
    glyph_codec,
    gspm,
    ir_lowering,
    key_index,
    records,
    relocation,
    screen_program,
    ui_index,
)


IR_OBJECT_KIND_FALLBACK = 0x0FCA
PHYSICAL_KEY_ORDER = (0xB2, 0xB3, 0xB0, 0xB1, 0xB4, 0xB5)
PAGE_TAGS = frozenset((0x72, 0x7E, 0x7F))
ADDRESS_WINDOW = 0x10000


def _atom(operand: int, opcode: int) -> bytes:
    if isinstance(operand, bool) or not isinstance(operand, int) or not 0 <= operand <= 0xFFFF:
        raise ValueError("object atom operand must fit in 16 bits")
    if isinstance(opcode, bool) or not isinstance(opcode, int) or not 0 <= opcode <= 0xFF:
        raise ValueError("object atom opcode must fit in 8 bits")
    return struct.pack("<HB", operand, opcode)


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


def key_register(entries: list[tuple[int, int, int]]) -> bytes:
    """Build one counted key register of ``(key code, object index, class)`` rows."""
    if not entries or len(entries) >= 40:
        raise ValueError("a Harmony One key register must hold between 1 and 39 entries")
    if len({key for key, _object, _category in entries}) != len(entries):
        raise ValueError("a Harmony One key register cannot repeat a key code")
    out = bytearray([len(entries)])
    for key, object_id, category in entries:
        if not 0 <= key <= 0xFF or not 0 <= object_id <= 0xFFFF:
            raise ValueError("key register key and object ID are outside their native ranges")
        out += bytes([key]) + _atom(object_id, category)
    return bytes(out)


def page(entries: list[tuple[int, int]]) -> bytes:
    """Build one counted section-9 page of key-to-object entries."""
    return key_register([(key, object_id, 0x7F) for key, object_id in entries])


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


def pages(payload: bytes) -> list[dict]:
    """Return structurally recognized pages in section 9, in ordinal order."""
    start, end = gspm.section_ranges(payload)[9]
    out = []
    cursor = start
    while cursor < end:
        count = payload[cursor]
        stop = cursor + 1 + 4 * count
        if (not 0 < count < 40 or stop > end
                or any(payload[cursor + 4 + 4 * index] not in PAGE_TAGS
                       for index in range(count))):
            cursor += 1
            continue
        entries = []
        for index in range(count):
            at = cursor + 1 + 4 * index
            key, object_id, tag = struct.unpack_from("<BHB", payload, at)
            entries.append({
                "index": index, "field": at + 1, "key_code": key,
                "object_id": object_id, "tag": tag,
            })
        out.append({"ordinal": len(out), "offset": cursor, "entries": entries})
        cursor = stop
    return out


def page_command_map(payload: bytes) -> dict[tuple[int, int], tuple[int, int | None]]:
    """Resolve section-9 page keys through their object wrappers."""
    objects = command_index.objects(payload)
    out = {}
    for item in pages(payload):
        for entry in item["entries"]:
            targets = []
            object_id = entry["object_id"]
            if 0 <= object_id < len(objects):
                for operand, opcode in objects[object_id]["atoms"]:
                    if opcode == 0x7F and 0 <= operand < len(objects):
                        targets.extend(objects[operand]["atoms"])
                    else:
                        targets.append((operand, opcode))
            commands = {operand for operand, opcode in targets if opcode == 0x7D}
            devices = {operand for operand, opcode in targets if opcode == 0x7C}
            if len(commands) == 1 and len(devices) <= 1:
                out[(item["ordinal"], entry["key_code"])] = (
                    next(iter(commands)), next(iter(devices)) if devices else None)
    return out


def _clone_indirection(payload: bytes, object_id: int, new_target: int) -> bytes:
    objects = command_index.objects(payload)
    if not 0 <= object_id < len(objects):
        raise ValueError(f"object {object_id} falls outside section 11")
    atoms = objects[object_id]["atoms"]
    if sum(opcode == 0x7F for _operand, opcode in atoms) != 1:
        raise ValueError(
            f"object {object_id} does not have exactly one indirection atom")
    return bytes([len(atoms)]) + b"".join(
        _atom(new_target if opcode == 0x7F else operand, opcode)
        for operand, opcode in atoms
    )


def assign_keys(
        payload: bytes, changes: list[tuple[int, int, int]], *,
        device_ids: list[int | None] | None = None,
) -> tuple[bytes, dict]:
    """Reassign existing section-9 keys to existing section-5 commands in one pass.

    ``changes`` contains ``(page ordinal, key code, command ID)``. The original
    wrapper object is cloned so navigation and unknown atoms survive unchanged.
    """
    if not changes:
        raise ValueError("there are no key changes to apply")
    device_ids = list(device_ids or [None] * len(changes))
    if len(device_ids) != len(changes):
        raise ValueError("device_ids must have one entry per key change")
    keys = {
        (item["ordinal"], entry["key_code"]): entry
        for item in pages(payload) for entry in item["entries"]
    }
    before = page_command_map(payload)
    commands = {
        (device["device_index"] << 8) | command["ordinal"]
        for device in section5_layout(payload) for command in device["commands"]
    }
    command_devices = command_index.command_objects(payload)
    object_count = len(command_index.objects(payload))
    ranges = gspm.section_ranges(payload)
    start9, end9 = ranges[9]
    start10, end10 = ranges[10]
    body9 = bytearray(payload[start9:end9])
    body10 = bytearray(payload[start10:end10])
    extra_offsets = []
    edited9 = []
    requested = {}
    seen = set()
    for (page_ordinal, key_code, command_id), explicit_device in zip(changes, device_ids):
        key = (page_ordinal, key_code)
        if key in seen:
            raise ValueError(f"page {page_ordinal} key {key_code:#x} is repeated")
        seen.add(key)
        entry = keys.get(key)
        if entry is None:
            raise ValueError(f"page {page_ordinal} has no key {key_code:#x}")
        if key not in before:
            raise ValueError(f"page {page_ordinal} key {key_code:#x} has no current command")
        if command_id not in commands:
            raise ValueError(f"command {command_id:#06x} is not reachable through section 5")
        candidates = sorted({
            item["device_id"] for item in command_devices.get(command_id, [])
        })
        if explicit_device is None:
            if len(candidates) != 1:
                raise ValueError(
                    f"command {command_id:#06x} has ambiguous runtime device IDs")
            device_id = candidates[0]
        else:
            device_id = explicit_device
        if not 0 <= device_id <= 0xFFFF or device_id >> 8 != command_id >> 8:
            raise ValueError("runtime device and command IDs must have the same high byte")

        command_object_id = object_count + len(extra_offsets)
        extra_offsets.append(len(body10))
        body10 += records.command_object(command_id, device_id)
        wrapper_id = object_count + len(extra_offsets)
        extra_offsets.append(len(body10))
        body10 += _clone_indirection(
            payload, entry["object_id"], command_object_id)
        local = entry["field"] - start9
        body9[local:local + 2] = wrapper_id.to_bytes(2, "little")
        edited9.append((local, local + 2))
        requested[key] = (command_id, device_id)

    result, relocation_report = relocation.relocate(
        payload, {9: bytes(body9), 10: bytes(body10)},
        maps={9: ((0, len(body9), 0),)}, edited={9: tuple(edited9)},
        extra_object_offsets=tuple(extra_offsets),
    )
    after = page_command_map(result)
    if set(after) != set(before):
        raise RuntimeError("key reassignment changed the recognized page-key set")
    unwanted = {
        key for key in before if key not in requested and before[key] != after[key]
    }
    wrong = {key for key, expected in requested.items() if after.get(key) != expected}
    if unwanted or wrong:
        raise RuntimeError(
            f"key reassignment changed {len(unwanted)} unrelated keys and "
            f"misassigned {len(wrong)} requested keys")
    return result, {
        "mode": "reassign-existing-page-keys", "changes": len(changes),
        "assignments": [
            {"page": page, "key_code": key, "command_id": value[0],
             "device_id": value[1]}
            for (page, key), value in requested.items()
        ],
        "relocation": relocation_report,
    }


def _replace_command_atoms(
        atoms: tuple[tuple[int, int], ...], command_id: int, device_id: int,
) -> bytes:
    if sum(opcode == 0x7D for _operand, opcode in atoms) != 1:
        raise ValueError("command action does not have exactly one command atom")
    if sum(opcode == 0x7C for _operand, opcode in atoms) != 1:
        raise ValueError("command action does not have exactly one runtime-device atom")
    return bytes([len(atoms)]) + b"".join(
        _atom(command_id if opcode == 0x7D else device_id if opcode == 0x7C else operand,
              opcode)
        for operand, opcode in atoms
    )


def _physical_map(payload: bytes) -> dict[tuple[int, int], tuple[int, int]]:
    report = activity_index.physical_contexts(payload)
    return {
        (context["ordinal"], row["index"]): (row["command_id"], row["device_id"])
        for context in report["contexts"] for row in context["rows"] if row["editable"]
    }


def assign_context_keys(
        payload: bytes, changes: list[tuple[int, int, int]], *,
        device_ids: list[int | None] | None = None,
) -> tuple[bytes, dict]:
    """Reassign editable section-10 context rows in one relocation pass.

    ``changes`` contains ``(context ordinal, row index, command ID)``. Direct and
    one-hop action shapes are cloned independently so unrelated native atoms survive.
    """
    if not changes:
        raise ValueError("there are no context-key changes to apply")
    device_ids = list(device_ids or [None] * len(changes))
    if len(device_ids) != len(changes):
        raise ValueError("device_ids must have one entry per context-key change")
    physical = activity_index.physical_contexts(payload)
    rows = {
        (context["ordinal"], row["index"]): (context, row)
        for context in physical["contexts"] for row in context["rows"]
    }
    before = _physical_map(payload)
    objects = command_index.objects(payload)
    command_devices = command_index.command_objects(payload)
    commands = {
        (device["device_index"] << 8) | command["ordinal"]
        for device in section5_layout(payload) for command in device["commands"]
    }
    ranges = gspm.section_ranges(payload)
    start10, end10 = ranges[10]
    body10 = bytearray(payload[start10:end10])
    extra_offsets = []
    row_patches = []
    requested = {}
    seen = set()

    def append_object(body: bytes) -> int:
        object_id = len(objects) + len(extra_offsets)
        extra_offsets.append(len(body10))
        body10.extend(body)
        return object_id

    for (context_ordinal, row_index, command_id), explicit_device in zip(
            changes, device_ids):
        key = (context_ordinal, row_index)
        if key in seen:
            raise ValueError(f"context {context_ordinal} row {row_index} is repeated")
        seen.add(key)
        pair = rows.get(key)
        if pair is None:
            raise ValueError(f"context {context_ordinal} has no row {row_index}")
        context, row = pair
        if not row["editable"]:
            raise ValueError(
                f"context {context_ordinal} row {row_index} is not an owned command action")
        if command_id not in commands:
            raise ValueError(f"command {command_id:#06x} is not reachable through section 5")
        candidates = sorted({
            item["device_id"] for item in command_devices.get(command_id, [])
        })
        if explicit_device is None:
            if len(candidates) != 1:
                raise ValueError(
                    f"command {command_id:#06x} has ambiguous runtime device IDs")
            device_id = candidates[0]
        else:
            device_id = explicit_device
        if not 0 <= device_id <= 0xFFFF or device_id >> 8 != command_id >> 8:
            raise ValueError("runtime device and command IDs must have the same high byte")

        old_object = objects[row["operand"]]
        if row["shape"] == "direct":
            new_action = append_object(
                _replace_command_atoms(old_object["atoms"], command_id, device_id))
        elif row["shape"] == "indirect":
            jumps = [
                operand for operand, opcode in old_object["atoms"] if opcode == 0x7F
            ]
            if len(jumps) != 1 or not 0 <= jumps[0] < len(objects):
                raise ValueError("indirect context action has an ambiguous object jump")
            new_nested = append_object(
                _replace_command_atoms(objects[jumps[0]]["atoms"], command_id, device_id))
            new_action = append_object(
                bytes([len(old_object["atoms"])]) + b"".join(
                    _atom(new_nested if opcode == 0x7F else operand, opcode)
                    for operand, opcode in old_object["atoms"]
                ))
        else:
            raise ValueError("context action shape is not writable")

        operand_field = row["offset"] + (2 if context["form"] == "long" else 1)
        row_patches.append((operand_field, new_action))
        requested[key] = (command_id, device_id)

    result, relocation_report = relocation.relocate(
        payload, {10: bytes(body10)}, extra_object_offsets=tuple(extra_offsets),
    )
    patched = bytearray(result[:-6])
    new10_start = relocation_report["sections"][10]["new"][0]
    patched_fields = []
    for field, object_id in row_patches:
        relocated_field = (
            new10_start + field - start10 if start10 <= field < end10 else field
        )
        if not 0 <= relocated_field <= len(patched) - 2:
            raise RuntimeError("context-key field was lost during relocation")
        patched[relocated_field:relocated_field + 2] = object_id.to_bytes(2, "little")
        patched_fields.append(relocated_field)
    result = relocation.repair_integrity(bytes(patched))
    after = _physical_map(result)
    if set(after) != set(before):
        raise RuntimeError("context-key reassignment changed the editable row set")
    unwanted = {
        key for key in before if key not in requested and before[key] != after[key]
    }
    wrong = {key for key, expected in requested.items() if after.get(key) != expected}
    if unwanted or wrong:
        raise RuntimeError(
            f"context-key reassignment changed {len(unwanted)} unrelated rows and "
            f"misassigned {len(wrong)} requested rows")
    return result, {
        "mode": "reassign-existing-context-keys", "changes": len(changes),
        "assignments": [
            {"context": context, "row": row, "command_id": value[0],
             "device_id": value[1]}
            for (context, row), value in requested.items()
        ],
        "patched_fields": patched_fields,
        "relocation": relocation_report,
    }


def section5_layout(payload: bytes) -> list[dict]:
    """Return section-5 device and command pointer fields with exact bounds."""
    start, end = gspm.section_ranges(payload)[5]
    device_count = payload[start]
    if start + 1 + 3 * device_count > end:
        raise ValueError("section 5 device index exceeds its section")
    out = []
    for device_index in range(device_count):
        field = start + 1 + 3 * device_index
        subtable = int.from_bytes(payload[field:field + 3], "little") - gspm.BASE
        if not 0 <= subtable + 3 <= len(payload) or payload[subtable] != 0:
            raise ValueError(f"section 5 device {device_index} has an invalid sub-table")
        count = struct.unpack_from("<H", payload, subtable + 1)[0]
        if count > 0x100 or subtable + 3 + 3 * count > len(payload):
            raise ValueError(f"section 5 device {device_index} has an invalid command table")
        commands = []
        for ordinal in range(count):
            command_field = subtable + 3 + 3 * ordinal
            target = int.from_bytes(
                payload[command_field:command_field + 3], "little") - gspm.BASE
            if not 11 <= target < len(payload):
                raise ValueError(f"section 5 command {(device_index << 8) | ordinal:#x} is invalid")
            commands.append({
                "ordinal": ordinal, "field": command_field,
                "record_offset": target - 11,
            })
        out.append({
            "device_index": device_index, "field": field, "subtable": subtable,
            "commands": commands,
        })
    return out


def command_subtable(record_offsets: list[int]) -> bytes:
    """Build a section-5 per-device table pointing at record byte +11."""
    if len(record_offsets) > 0x100:
        raise ValueError("a Harmony One device cannot exceed 256 command ordinals")
    out = bytearray(b"\x00" + len(record_offsets).to_bytes(2, "little"))
    for offset in record_offsets:
        absolute = gspm.BASE + offset + 11
        if offset < 0 or absolute >= 1 << 24:
            raise ValueError("command record pointer does not fit in 24 bits")
        out += absolute.to_bytes(3, "little")
    return bytes(out)


def section5(subtable_offsets: list[int]) -> bytes:
    """Build the top-level section-5 device index."""
    if not subtable_offsets or len(subtable_offsets) > 0xFF:
        raise ValueError("section 5 must contain between 1 and 255 devices")
    out = bytearray([len(subtable_offsets)])
    for offset in subtable_offsets:
        absolute = gspm.BASE + offset
        if offset < 0 or absolute >= 1 << 24:
            raise ValueError("section 5 sub-table pointer does not fit in 24 bits")
        out += absolute.to_bytes(3, "little")
    return bytes(out)


def ir_object_kind(payload: bytes) -> int:
    """Derive the dominant opcode-75 operand instead of freezing a donor value."""
    counts: dict[int, int] = {}
    for item in command_index.objects(payload):
        for operand, opcode in item["atoms"]:
            if opcode == 0x75:
                counts[operand] = counts.get(operand, 0) + 1
    if not counts:
        return IR_OBJECT_KIND_FALLBACK
    return min(counts, key=lambda value: (-counts[value], value))


def _align_window(out: bytearray, size: int) -> int:
    """Pad so a sequential native read stays inside one 64 KiB window."""
    if size <= 0 or size > ADDRESS_WINDOW:
        raise ValueError("native allocation must fit inside one 64 KiB window")
    if len(out) // ADDRESS_WINDOW != (len(out) + size - 1) // ADDRESS_WINDOW:
        out += bytes(ADDRESS_WINDOW - len(out) % ADDRESS_WINDOW)
    return len(out)


def add_command_device(
        payload: bytes, signals: list[dict], *, library=None,
) -> tuple[bytes, dict]:
    """Append lowered command records, extend section 5, and index their objects.

    This establishes native command ownership only. It intentionally does not claim
    that the new device has a menu row or reachable command screen.
    """
    if not signals:
        raise ValueError("a new Harmony One device needs at least one command")
    if len(signals) > 0x100:
        raise ValueError("a Harmony One device cannot exceed 256 commands")
    existing = section5_layout(payload)
    device_index = len(existing)
    if device_index >= 0xFF:
        raise ValueError("section 5 cannot index another device")
    lowered = [ir_lowering.lower(signal, library=library) for signal in signals]
    checksum_offset = int.from_bytes(payload[4:8], "little") - gspm.BASE - 2
    out = bytearray(payload[:checksum_offset])
    record_offsets = []
    allocation = []
    for ordinal, native in enumerate(lowered):
        waveform_size = (
            len(native.press_waveform) + len(native.hold_waveform or b"")
            + len(native.release_waveform or b"")
        )
        unit_size = waveform_size + 25
        start = _align_window(out, unit_size)
        press_offset = len(out)
        out += native.press_waveform
        hold_offset = None
        if native.hold_waveform is not None:
            hold_offset = len(out)
            out += native.hold_waveform
        release_offset = None
        if native.release_waveform is not None:
            release_offset = len(out)
            out += native.release_waveform
        record_offset = len(out)
        out += records.command_record(
            record_offset, press_offset, hold_offset,
            native.carrier_period_ns, native.carrier_half_period_ns,
            release_offset=release_offset,
        )
        record_offsets.append(record_offset)
        allocation.append({
            "ordinal": ordinal, "start": start, "end": len(out),
            "record_offset": record_offset, "press_offset": press_offset,
            "hold_offset": hold_offset, "release_offset": release_offset,
        })

    subtable = command_subtable(record_offsets)
    subtable_offset = _align_window(out, len(subtable))
    out += subtable
    old_subtables = [item["subtable"] for item in existing]
    top = section5(old_subtables + [subtable_offset])
    section5_offset = _align_window(out, len(top))
    out += top
    out[0x20:0x24] = (gspm.BASE + section5_offset).to_bytes(4, "little")
    indexed = relocation.repair_integrity(bytes(out))
    gspm.validate(indexed)

    start10, end10 = gspm.section_ranges(indexed)[10]
    body10 = bytearray(indexed[start10:end10])
    object_count = len(command_index.objects(indexed))
    bodies, wrapper_ids = device_objects(
        device_index, len(signals), object_count, ir_object_kind(indexed))
    extra_offsets = []
    for body in bodies:
        extra_offsets.append(len(body10))
        body10 += body
    result, relocation_report = relocation.relocate(
        indexed, {10: bytes(body10)}, extra_object_offsets=tuple(extra_offsets))
    ownership = command_index.inspect(result)
    added = ownership["devices"][device_index]
    if len(added["commands"]) != len(signals):
        raise RuntimeError(
            f"new section-5 device resolves {len(added['commands'])} of "
            f"{len(signals)} commands")
    return result, {
        "mode": "add-command-device", "device_index": device_index,
        "commands": len(signals), "section5_offset": section5_offset,
        "subtable_offset": subtable_offset, "allocations": allocation,
        "wrapper_object_ids": wrapper_ids, "relocation": relocation_report,
    }


def command_screen_sources(payload: bytes, ownership: dict | None = None) -> list[dict]:
    """Return single-device screen slots whose shape can carry another device.

    A usable source binds at least one section-5 command, reaches exactly one device,
    and navigates nowhere. A slot that opens another screen is refused because a clone
    would inherit navigation belonging to the screen it was copied from.
    """
    ownership = command_index.inspect(payload) if ownership is None else ownership
    objects = command_index.objects(payload)
    commands = {
        command["command_id"]
        for device in ownership["devices"] for command in device["commands"]
    }
    out = []
    for screen in ui_index.screen_slots(payload):
        for slot in screen["slots"]:
            devices = set()
            command_keys = []
            usable = True
            for entry in slot["entries"]:
                if entry["category"] != 0x7F:
                    continue
                targets = key_index.object_targets(objects, entry["operand"])
                if targets is None or any(opcode == 0x7E for _value, opcode in targets):
                    usable = False
                    break
                bound = {value for value, opcode in targets if opcode == 0x7D}
                if not bound:
                    continue
                if len(bound) != 1 or not bound <= commands:
                    usable = False
                    break
                devices.add(next(iter(bound)) >> 8)
                command_keys.append(entry["key_code"])
            if not usable or len(devices) != 1 or not command_keys:
                continue
            trailer = screen["trailer_offset"]
            out.append({
                "screen": screen["ordinal"],
                "slot": slot["index"],
                "device_index": next(iter(devices)),
                "template": slot["template"],
                "flag": payload[trailer],
                "header_offset": int.from_bytes(
                    payload[trailer + 1:trailer + 4], "little") - gspm.BASE,
                "program_offset": slot["program_offset"],
                "key_register_offset": slot["key_register_offset"],
                "command_key_codes": command_keys,
                "entries": len(slot["entries"]),
            })
    return out


def add_command_screen(
        payload: bytes, pages: list[list[tuple[int, int]]], *, sources: list[dict],
        labels: list[dict] | None = None, title: str | None = None,
) -> tuple[bytes, dict]:
    """Append a screen of one or more pages, each cloned from an owned native slot.

    ``pages`` gives the ``(key code, object index)`` bindings of each page and
    ``sources`` the slot each is cloned from, both from :func:`command_screen_sources`.
    A page must rebind every command key its source declares: a partly rebound clone
    would still fire the source device. Non-command entries are copied byte for byte.

    Without ``labels`` the pages keep the artwork and names of the slots they were
    cloned from. With them, each page's drawing program is re-emitted naming the new
    commands, and ``title`` renames the screen in the prologue the pages share.
    """
    if not pages:
        raise ValueError("a command screen needs at least one page")
    if len(sources) != len(pages):
        raise ValueError(
            f"{len(pages)} pages were given {len(sources)} source slots")
    if labels is not None and len(labels) != len(pages):
        raise ValueError(f"{len(pages)} pages were given {len(labels)} label sets")
    object_count = len(command_index.objects(payload))
    requested = []
    for index, (page, source) in enumerate(zip(pages, sources)):
        binding = dict(page)
        if len(binding) != len(page):
            raise ValueError(f"page {index} binds one key code twice")
        if set(binding) != set(source["command_key_codes"]):
            raise ValueError(
                f"page {index} must rebind every command key of its source slot: "
                f"{sorted(source['command_key_codes'])} declared, "
                f"{sorted(binding)} given")
        outside = sorted(
            str(value) for value in binding.values()
            if isinstance(value, bool) or not isinstance(value, int)
            or not 0 <= value < object_count)
        if outside:
            raise ValueError(
                f"page {index} names objects outside section 11: " + ", ".join(outside))
        requested.append(binding)

    screens = ui_index.screen_slots(payload)
    slots = [
        screens[source["screen"]]["slots"][source["slot"]] for source in sources
    ]
    numbered = [
        screen_program.page_indicator(
            payload, slot["program_offset"], screen_program.PAGE_NUMBER_XY) is not None
        for slot in slots
    ]
    if len(set(numbered)) != 1:
        raise ValueError(
            "some source slots number their pages and others do not; a screen numbers "
            "every page or none")
    if len(pages) > 1 and not numbered[0]:
        raise ValueError(
            "these source slots draw no page number, so a multi-page screen built from "
            "them could not say which page it is on")

    start9, end9 = gspm.section_ranges(payload)[9]
    body9 = bytearray(payload[start9:end9])
    locals9 = []
    for slot, binding in zip(slots, requested):
        locals9.append(len(body9))
        body9 += key_register([
            (entry["key_code"], binding.get(entry["key_code"], entry["operand"]),
             entry["category"])
            for entry in slot["entries"]
        ])
    relocated, relocation_report = relocation.relocate(payload, {9: bytes(body9)})
    new9 = relocation_report["sections"][9]["new"][0]
    registers = [new9 + local for local in locals9]
    for offset, local, following in zip(registers, locals9, locals9[1:] + [len(body9)]):
        if offset // ADDRESS_WINDOW != (offset + following - local - 1) // ADDRESS_WINDOW:
            raise ValueError("a cloned key register would cross a 64 KiB window")

    trailers = [screen["trailer_offset"] for screen in ui_index.screen_slots(relocated)]
    checksum_offset = int.from_bytes(relocated[4:8], "little") - gspm.BASE - 2
    out = bytearray(relocated[:checksum_offset])

    prologue_offset = None
    if labels is not None or title is not None or len(pages) > 1:
        first = ui_index.drawing_program(
            relocated, slots[0]["program_offset"])["instructions"][0]
        if first["opcode"] != "call":
            raise ValueError("the source slot opens no prologue to share")
        prologue = screen_program.render_prologue(
            relocated, first["target"], title=title,
            total=len(pages) if numbered[0] else None)
        prologue_offset = _align_window(out, len(prologue))
        out += prologue

    offsets = []
    programs = []
    for index, (slot, source, register) in enumerate(zip(slots, sources, registers)):
        program_offset = slot["program_offset"]
        if labels is not None or prologue_offset is not None:
            order = screen_program.key_button_order(
                relocated, source["template"], sorted(requested[index]))
            drawn = None
            if labels is not None:
                if set(labels[index]) != set(order):
                    raise ValueError(
                        f"page {index} must label every rebound key: "
                        f"{sorted(order)} bound, {sorted(labels[index])} labelled")
                drawn = [labels[index][key] for key in order]
            body = screen_program.render(
                relocated, program_offset,
                drawn if drawn is not None else screen_program.labelled(
                    relocated, program_offset),
                page_number=index + 1 if numbered[0] else None,
                call_target=prologue_offset)
            program_offset = _align_window(out, len(body))
            out += body
        programs.append(program_offset)
        record = screen_slot(source["template"], register, program_offset)
        offsets.append(_align_window(out, len(record)))
        out += record

    trailer_record = screen_trailer(
        sources[0]["flag"], sources[0]["header_offset"], offsets)
    trailer_offset = _align_window(out, len(trailer_record))
    out += trailer_record
    index_body = screen_index(trailers + [trailer_offset])
    index_offset = _align_window(out, len(index_body))
    out += index_body
    out[0x24:0x28] = (gspm.BASE + index_offset).to_bytes(4, "little")
    result = relocation.repair_integrity(bytes(out))
    gspm.validate(result)

    ordinal = len(trailers)

    def _meaning(bindings: list[dict]) -> list[tuple]:
        # Key-register and program offsets move with relocation; what must not change
        # is which key on which screen reaches which command on which device.
        return [
            (item["screen"], item["slot"], item["template"], item["key_code"],
             item["object_index"], item["command_id"], tuple(item["device_ids"]),
             tuple(item["target_pages"]))
            for item in bindings
        ]

    before = key_index.inspect(payload)["bindings"]
    after = key_index.inspect(result)["bindings"]
    added = [item for item in after if item["screen"] == ordinal]
    if _meaning([item for item in after if item["screen"] != ordinal]) != _meaning(before):
        raise RuntimeError("adding a command screen changed an existing key binding")
    for index, binding in enumerate(requested):
        resolved = {
            item["key_code"] for item in added if item["slot"] == index
        }
        if resolved != set(binding):
            raise RuntimeError(
                f"page {index} resolves {len(resolved)} of {len(binding)} bindings")
    if labels is not None:
        for index, program_offset in enumerate(programs):
            order = screen_program.key_button_order(
                result, sources[index]["template"], sorted(requested[index]))
            wanted = [
                [labels[index][key]] if isinstance(labels[index][key], str)
                else list(labels[index][key]) for key in order
            ]
            if screen_program.labelled(result, program_offset) != wanted:
                raise RuntimeError(f"page {index} draws labels that were not requested")
    if title is not None:
        drawn = screen_program.screen_title(result, prologue_offset)
        if drawn != title:
            raise RuntimeError(f"the new screen is titled {drawn!r}, not {title!r}")
    return result, {
        "mode": "clone-command-screen",
        "screen": ordinal,
        "pages": len(pages),
        "cloned_from": [
            {"screen": source["screen"], "slot": source["slot"]} for source in sources
        ],
        "artwork": "cloned-from-source-screen" if labels is None else "relabelled-clone",
        "title": title,
        "numbered": numbered[0],
        "program_offsets": programs,
        "prologue_offset": prologue_offset,
        # Nothing opens the new ordinal yet: a Devices-menu row with its own text,
        # touch zone and 0x7e navigation object is a separate operation.
        "navigation": "unreferenced",
        "slot_offsets": offsets,
        "trailer_offset": trailer_offset,
        "screen_index_offset": index_offset,
        "key_register_offsets": registers,
        "relocation": relocation_report,
    }


def _clone_navigation(payload: bytes, object_id: int, screen_ordinal: int) -> bytes:
    objects = command_index.objects(payload)
    if not 0 <= object_id < len(objects):
        raise ValueError(f"object {object_id} falls outside section 11")
    atoms = objects[object_id]["atoms"]
    if sum(opcode == 0x7E for _operand, opcode in atoms) != 1:
        raise ValueError(f"object {object_id} does not open exactly one screen")
    return bytes([len(atoms)]) + b"".join(
        _atom(screen_ordinal if opcode == 0x7E else operand, opcode)
        for operand, opcode in atoms
    )


def _menu_row_state(report: dict) -> dict:
    return {
        (menu["screen"], row["slot"], row["row"]): (
            row["target_screen"], tuple(line["glyphs"] for line in row["lines"]))
        for menu in report["menus"] for row in menu["rows"]
    }


def assign_menu_row(
        payload: bytes, device_index: int, *,
        target_screen: int | None = None, label: object | None = None,
) -> tuple[bytes, dict]:
    """Point one Devices-menu row at another screen, rename it, or both.

    The menu is replicated, and the replicas are only recognized as one menu because
    they agree. Every occurrence of the row is therefore changed together: a row edited
    in one replica and not the others would break that agreement and leave the remote
    showing two different device lists depending on how the menu was reached.
    """
    if target_screen is None and label is None:
        raise ValueError("a menu row change must give a target screen, a label, or both")
    ownership = command_index.inspect(payload)
    menus = ui_index.device_menus(payload, ownership)
    if not 0 <= device_index < len(menus["devices"]):
        raise ValueError(f"section 5 declares no device {device_index}")
    if menus["devices"][device_index]["target_screen"] is None:
        raise ValueError(
            f"device {device_index} has no single agreed menu row to change")
    occurrences = [
        {"menu_screen": menu["screen"], **row}
        for menu in menus["menus"] for row in menu["rows"]
        if row["device_indices"] == [device_index]
    ]
    if len(occurrences) != len(menus["menus"]):
        raise ValueError(
            f"device {device_index} occupies {len(occurrences)} rows across "
            f"{len(menus['menus'])} menu replicas; every replica must carry it once")
    screens = ui_index.screen_slots(payload)
    if target_screen is not None and not 0 <= target_screen < len(screens):
        raise ValueError(f"section 6 declares no screen {target_screen}")

    result = payload
    relocation_report = None
    if target_screen is not None:
        start9, end9 = gspm.section_ranges(payload)[9]
        start10, end10 = gspm.section_ranges(payload)[10]
        body9 = bytearray(payload[start9:end9])
        body10 = bytearray(payload[start10:end10])
        object_count = len(command_index.objects(payload))
        extra_offsets = []
        edited9 = []
        for row in occurrences:
            slot = screens[row["menu_screen"]]["slots"][row["slot"]]
            field = next(
                entry["offset"] for entry in slot["entries"]
                if entry["key_code"] == row["key_code"]) + 1
            # Every key register in both broader donors lives in section 9, which is
            # what makes repointing one an in-place edit inside a relocated section.
            if not start9 <= field and field + 2 <= end9:
                raise ValueError(
                    f"the menu row's key register at {field:#x} is outside section 9")
            navigation = object_count + len(extra_offsets)
            extra_offsets.append(len(body10))
            body10 += _clone_navigation(payload, row["object_index"], target_screen)
            local = field - start9
            body9[local:local + 2] = navigation.to_bytes(2, "little")
            edited9.append((local, local + 2))
        result, relocation_report = relocation.relocate(
            payload, {9: bytes(body9), 10: bytes(body10)},
            maps={9: ((0, len(body9), 0),)}, edited={9: tuple(edited9)},
            extra_object_offsets=tuple(extra_offsets),
        )

    if label is not None:
        screens = ui_index.screen_slots(result)
        checksum_offset = int.from_bytes(result[4:8], "little") - gspm.BASE - 2
        out = bytearray(result[:checksum_offset])
        rebuilt = {}
        for row in occurrences:
            slot = screens[row["menu_screen"]]["slots"][row["slot"]]
            program = screen_program.render_menu_row(
                result, slot["program_offset"], row["row"], label)
            program_offset = _align_window(out, len(program))
            out += program
            record = screen_slot(
                slot["template"], slot["key_register_offset"], program_offset)
            rebuilt[(row["menu_screen"], row["slot"])] = _align_window(out, len(record))
            out += record
        trailers = [screen["trailer_offset"] for screen in screens]
        for ordinal in sorted({row["menu_screen"] for row in occurrences}):
            trailer = trailers[ordinal]
            record = screen_trailer(
                result[trailer],
                int.from_bytes(result[trailer + 1:trailer + 4], "little") - gspm.BASE,
                [rebuilt.get((ordinal, slot["index"]), slot["offset"])
                 for slot in screens[ordinal]["slots"]],
            )
            trailers[ordinal] = _align_window(out, len(record))
            out += record
        index = screen_index(trailers)
        index_offset = _align_window(out, len(index))
        out += index
        out[0x24:0x28] = (gspm.BASE + index_offset).to_bytes(4, "little")
        result = relocation.repair_integrity(bytes(out))
    gspm.validate(result)

    after = ui_index.device_menus(result)
    if after["counts"]["replica_menus"] != menus["counts"]["replica_menus"]:
        raise RuntimeError(
            "the menu replicas no longer agree after changing one row in each")
    before_rows = _menu_row_state(menus)
    after_rows = _menu_row_state(after)
    changed = {row["menu_screen"] for row in occurrences}
    wanted = {(row["menu_screen"], row["slot"], row["row"]) for row in occurrences}
    if set(after_rows) != set(before_rows):
        raise RuntimeError("changing a menu row changed which rows the menu has")
    stray = [
        key for key, value in before_rows.items()
        if key not in wanted and after_rows[key] != value
    ]
    if stray:
        raise RuntimeError(f"{len(stray)} unrelated menu rows changed")
    report = glyph_codec.inspect(result)
    for key in sorted(wanted):
        target, glyphs = after_rows[key]
        if target_screen is not None and target != target_screen:
            raise RuntimeError(
                f"menu row {key} opens screen {target}, not {target_screen}")
        if label is not None:
            drawn = [glyph_codec.decode(bytes.fromhex(item), report) for item in glyphs]
            if drawn != ([label] if isinstance(label, str) else list(label)):
                raise RuntimeError(f"menu row {key} draws {drawn}, not the label asked for")
    return result, {
        "mode": "assign-menu-row",
        "device_index": device_index,
        "replicas": len(occurrences),
        "menu_screens": sorted(changed),
        "target_screen": target_screen,
        "label": label,
        "relocation": relocation_report,
    }


def menu_row_zones(zones: list[dict]) -> list[dict]:
    """Return a menu template's device-row zones, in reading order.

    Rows are the equally sized content zones. The bottom softkey shares the template
    but is a different size, and one replica in each donor binds it in the navigation
    class like a row, so its binding class cannot be used to tell them apart.
    """
    content = [zone for zone in zones if zone["tag"] not in ui_index.SIDE_STRIP_TAGS]
    if not content:
        return []
    sizes = Counter((zone["width"], zone["height"]) for zone in content)
    size, count = sizes.most_common(1)[0]
    if count < 2:
        raise ValueError("this menu template has no repeated row-sized touch zone")
    return sorted(
        (zone for zone in content if (zone["width"], zone["height"]) == size),
        key=lambda zone: (-zone["y"], zone["x"]),
    )


def menu_capacity(payload: bytes, ownership: dict | None = None) -> dict:
    """Report whether the Devices menu can take another row, and how.

    A menu page has as many rows as its touch template has content zones bound to it.
    When every page of every replica is full, another row needs another page, which the
    native producer only numbers on screens that already carry a page counter.
    """
    ownership = command_index.inspect(payload) if ownership is None else ownership
    menus = ui_index.device_menus(payload, ownership)
    screens = ui_index.screen_slots(payload)
    templates = ui_index.touch_templates(payload)
    pages = []
    for menu in menus["menus"]:
        for slot in screens[menu["screen"]]["slots"]:
            zones = menu_row_zones(templates.get(slot["template"], []))
            drawn = [
                row["row"] for row in screen_program.menu_rows(
                    payload, slot["program_offset"])
            ]
            pages.append({
                "screen": menu["screen"], "slot": slot["index"],
                "rows": len(drawn), "row_zones": len(zones),
                "numbered": screen_program.page_indicator(
                    payload, slot["program_offset"],
                    screen_program.PAGE_NUMBER_XY) is not None,
            })
    slots = {menu["screen"]: len(screens[menu["screen"]]["slots"]) for menu in menus["menus"]}
    totals = {}
    for menu in menus["menus"]:
        first = screens[menu["screen"]]["slots"][0]
        program = ui_index.drawing_program(payload, first["program_offset"])
        prologue = program["instructions"][0]
        totals[menu["screen"]] = None
        if prologue["opcode"] == "call":
            counter = screen_program.page_indicator(
                payload, prologue["target"], screen_program.PAGE_TOTAL_XY)
            totals[menu["screen"]] = None if counter is None else counter["text"]
    return {
        "replicas": [menu["screen"] for menu in menus["menus"]],
        "pages": pages,
        "slots_per_replica": slots,
        "page_totals": totals,
        "free_rows": sum(max(0, page["row_zones"] - page["rows"]) for page in pages),
        "every_page_numbered": bool(pages) and all(page["numbered"] for page in pages),
        "replicas_agree_on_pages": len(set(slots.values())) == 1,
    }


def add_menu_row(payload: bytes, target_screen: int, label: object) -> tuple[bytes, dict]:
    """Add a Devices-menu page carrying one new row, in every replica.

    Both broader donors fill every existing page, so a new row means a new page. The
    page is cloned from the replica's own last page: same template, same prologue, same
    chrome, with every row but the new one dropped and the page counter advanced. The
    prologue's page total is advanced to match, which is safe because no prologue in
    either donor is shared between screens.
    """
    ownership = command_index.inspect(payload)
    menus = ui_index.device_menus(payload, ownership)
    screens = ui_index.screen_slots(payload)
    if not menus["menus"]:
        raise ValueError("this image has no agreed Devices menu to add a row to")
    if not 0 <= target_screen < len(screens):
        raise ValueError(f"section 6 declares no screen {target_screen}")
    if any(row["target_screen"] == target_screen
           for menu in menus["menus"] for row in menu["rows"]):
        raise ValueError(
            f"the menu already has a row opening screen {target_screen}; a second one "
            "would give that device two names")
    capacity = menu_capacity(payload, ownership)
    if capacity["free_rows"]:
        return _fill_menu_row(payload, menus, target_screen, label, capacity)
    if not capacity["replicas_agree_on_pages"]:
        raise ValueError("the menu replicas do not all have the same number of pages")
    if not capacity["every_page_numbered"]:
        raise ValueError(
            "this menu draws no page numbers, so growing it would need a page counter "
            "built rather than advanced; only menus that already page can grow")
    missing = sorted(
        screen for screen, total in capacity["page_totals"].items() if total is None)
    if missing:
        raise ValueError(
            "these menu replicas state no page total: " + ", ".join(map(str, missing)))

    templates = ui_index.touch_templates(payload)
    ir_kind = ir_object_kind(payload)
    start9, end9 = gspm.section_ranges(payload)[9]
    start10, end10 = gspm.section_ranges(payload)[10]
    body9 = bytearray(payload[start9:end9])
    body10 = bytearray(payload[start10:end10])
    object_count = len(command_index.objects(payload))
    registers = {}
    extra_offsets = [len(body10)]
    body10 += navigation_object(target_screen, ir_kind)
    navigation = object_count
    for menu in menus["menus"]:
        last = screens[menu["screen"]]["slots"][-1]
        rows = screen_program.menu_rows(payload, last["program_offset"])
        first_row = min(row["row"] for row in rows)
        order = [
            zone["key_code"]
            for zone in menu_row_zones(templates.get(last["template"], []))
        ]
        keep = order[first_row]
        entries = [
            (entry["key_code"],
             navigation if entry["key_code"] == keep else entry["operand"],
             entry["category"])
            for entry in last["entries"]
            if entry["key_code"] == keep or entry["key_code"] not in order
        ]
        if not any(key == keep for key, _object, _category in entries):
            raise ValueError(
                f"menu replica {menu['screen']} binds no key for its first row zone")
        registers[menu["screen"]] = (len(body9), first_row)
        body9 += key_register(entries)

    result, relocation_report = relocation.relocate(
        payload, {9: bytes(body9), 10: bytes(body10)},
        extra_object_offsets=tuple(extra_offsets),
    )

    screens = ui_index.screen_slots(result)
    start9 = gspm.section_ranges(result)[9][0]
    checksum_offset = int.from_bytes(result[4:8], "little") - gspm.BASE - 2
    out = bytearray(result[:checksum_offset])
    trailers = [screen["trailer_offset"] for screen in screens]
    for menu in menus["menus"]:
        ordinal = menu["screen"]
        slots = screens[ordinal]["slots"]
        pages = len(slots) + 1
        last = slots[-1]
        local, first_row = registers[ordinal]
        register_offset = start9 + local

        # The prologue states the total, so it moves first and every slot of this
        # screen - the new page included - is re-emitted calling the new one.
        prologue = ui_index.drawing_program(
            result, last["program_offset"])["instructions"][0]["target"]
        total = screen_program.render_page_counter(
            result, prologue, screen_program.PAGE_TOTAL_XY, pages)
        total_offset = _align_window(out, len(total))
        out += total

        program = screen_program.render_menu_page(
            result, last["program_offset"], {first_row: label},
            page_number=pages, call_target=total_offset)
        program_offset = _align_window(out, len(program))
        out += program
        record = screen_slot(last["template"], register_offset, program_offset)
        slot_offset = _align_window(out, len(record))
        out += record
        offsets = []
        for slot in slots:
            body = screen_program.render_call(result, slot["program_offset"], total_offset)
            at = _align_window(out, len(body))
            out += body
            record = screen_slot(slot["template"], slot["key_register_offset"], at)
            offsets.append(_align_window(out, len(record)))
            out += record
        offsets.append(slot_offset)
        trailer = trailers[ordinal]
        record = screen_trailer(
            result[trailer],
            int.from_bytes(result[trailer + 1:trailer + 4], "little") - gspm.BASE,
            offsets)
        trailers[ordinal] = _align_window(out, len(record))
        out += record
    index = screen_index(trailers)
    index_offset = _align_window(out, len(index))
    out += index
    out[0x24:0x28] = (gspm.BASE + index_offset).to_bytes(4, "little")
    result = relocation.repair_integrity(bytes(out))
    gspm.validate(result)

    after = ui_index.device_menus(result)
    if after["counts"]["replica_menus"] != menus["counts"]["replica_menus"]:
        raise RuntimeError("the menu replicas no longer agree after adding a page")
    expected = menus["counts"]["replica_rows"] + len(menus["menus"])
    if after["counts"]["replica_rows"] != expected:
        raise RuntimeError(
            f"the menu now has {after['counts']['replica_rows']} rows, expected {expected}")
    added = [
        row for menu in after["menus"] for row in menu["rows"]
        if row["target_screen"] == target_screen
    ]
    if len(added) != len(menus["menus"]):
        raise RuntimeError(
            f"{len(added)} replicas reach the new screen, expected {len(menus['menus'])}")
    if after["rejected"] != menus["rejected"]:
        raise RuntimeError(
            f"adding a menu page changed what the menu reader rejects: {after['rejected']}")
    return result, {
        "mode": "add-menu-page",
        "target_screen": target_screen,
        "label": label,
        "replicas": len(menus["menus"]),
        "pages": {menu["screen"]: len(screens[menu["screen"]]["slots"]) + 1
                  for menu in menus["menus"]},
        "relocation": relocation_report,
    }


def _menu_slot_state(payload: bytes, ordinal: int, index: int) -> dict:
    slot = ui_index.screen_slots(payload)[ordinal]["slots"][index]
    rows = screen_program.menu_rows(payload, slot["program_offset"])
    report = glyph_codec.inspect(payload)
    return {
        "slot": slot,
        "bands": [row["row"] for row in rows],
        "labels": {
            row["row"]: screen_program.menu_row_labels(
                payload, slot["program_offset"], report)[row["row"]]
            for row in rows
        },
    }


def _rebuild_menu_pages(payload: bytes, pages: dict, registers: dict) -> bytes:
    """Re-emit the named menu pages and repoint their screens through section 6.

    ``pages`` maps ``(screen, slot)`` to the labels that page must draw and, optionally,
    the page number it must show; ``registers`` maps the same key to a new key-register
    offset. Slots that are not named keep their bytes.
    """
    screens = ui_index.screen_slots(payload)
    checksum_offset = int.from_bytes(payload[4:8], "little") - gspm.BASE - 2
    out = bytearray(payload[:checksum_offset])
    rebuilt = {}
    for (ordinal, index), request in sorted(pages.items()):
        slot = screens[ordinal]["slots"][index]
        program = screen_program.render_menu_page(
            payload, slot["program_offset"], request["labels"],
            page_number=request.get("page_number"))
        program_offset = _align_window(out, len(program))
        out += program
        record = screen_slot(
            slot["template"],
            registers.get((ordinal, index), slot["key_register_offset"]),
            program_offset)
        rebuilt[(ordinal, index)] = _align_window(out, len(record))
        out += record
    trailers = [screen["trailer_offset"] for screen in screens]
    for ordinal in sorted({key[0] for key in pages}):
        trailer = trailers[ordinal]
        record = screen_trailer(
            payload[trailer],
            int.from_bytes(payload[trailer + 1:trailer + 4], "little") - gspm.BASE,
            [rebuilt.get((ordinal, slot["index"]), slot["offset"])
             for slot in screens[ordinal]["slots"]])
        trailers[ordinal] = _align_window(out, len(record))
        out += record
    index_body = screen_index(trailers)
    index_offset = _align_window(out, len(index_body))
    out += index_body
    out[0x24:0x28] = (gspm.BASE + index_offset).to_bytes(4, "little")
    return relocation.repair_integrity(bytes(out))


def _fill_menu_row(payload: bytes, menus: dict, target_screen: int, label,
                   capacity: dict) -> tuple[bytes, dict]:
    """Draw a new row in a band every replica already leaves empty."""
    free = {}
    for page in capacity["pages"]:
        if page["rows"] < page["row_zones"]:
            free.setdefault(page["screen"], (page["slot"], page["rows"]))
    if len(free) != len(menus["menus"]):
        raise ValueError(
            f"{len(free)} of {len(menus['menus'])} menu replicas have an unused row "
            "zone; every replica must have the same room")
    templates = ui_index.touch_templates(payload)
    screens = ui_index.screen_slots(payload)
    start9, end9 = gspm.section_ranges(payload)[9]
    start10, end10 = gspm.section_ranges(payload)[10]
    body9 = bytearray(payload[start9:end9])
    body10 = bytearray(payload[start10:end10])
    navigation = len(command_index.objects(payload))
    extra = [len(body10)]
    body10 += navigation_object(target_screen, ir_object_kind(payload))
    locals9 = {}
    plan = {}
    for menu in menus["menus"]:
        ordinal = menu["screen"]
        index, used = free[ordinal]
        slot = screens[ordinal]["slots"][index]
        state = _menu_slot_state(payload, ordinal, index)
        order = [zone["key_code"] for zone in menu_row_zones(
            templates.get(slot["template"], []))]
        band = next(
            (position for position in range(len(order))
             if position not in state["bands"]), None)
        if band is None:
            raise ValueError(f"menu replica {ordinal} has no free row band to draw in")
        if any(entry["key_code"] == order[band] for entry in slot["entries"]):
            raise ValueError(
                f"menu replica {ordinal} already binds the key of its free row band")
        locals9[(ordinal, index)] = len(body9)
        body9 += key_register(
            [(entry["key_code"], entry["operand"], entry["category"])
             for entry in slot["entries"]] + [(order[band], navigation, 0x7F)])
        plan[(ordinal, index)] = {"labels": {**state["labels"], band: label}}

    relocated, relocation_report = relocation.relocate(
        payload, {9: bytes(body9), 10: bytes(body10)},
        extra_object_offsets=tuple(extra))
    new9 = relocation_report["sections"][9]["new"][0]
    registers = {key: new9 + local for key, local in locals9.items()}
    result = _rebuild_menu_pages(relocated, plan, registers)
    gspm.validate(result)
    return result, _menu_growth_report(
        payload, result, menus, target_screen, label, "fill-menu-row",
        relocation_report)


def _menu_growth_report(payload, result, menus, target_screen, label, mode,
                        relocation_report) -> dict:
    after = ui_index.device_menus(result)
    if after["counts"]["replica_menus"] != menus["counts"]["replica_menus"]:
        raise RuntimeError("the menu replicas no longer agree after adding a row")
    expected = menus["counts"]["replica_rows"] + len(menus["menus"])
    if after["counts"]["replica_rows"] != expected:
        raise RuntimeError(
            f"the menu now has {after['counts']['replica_rows']} rows, expected {expected}")
    added = [
        row for menu in after["menus"] for row in menu["rows"]
        if row["target_screen"] == target_screen
    ]
    if len(added) != len(menus["menus"]):
        raise RuntimeError(
            f"{len(added)} replicas reach the new screen, expected {len(menus['menus'])}")
    if after["rejected"] != menus["rejected"]:
        raise RuntimeError(
            f"adding a menu row changed what the menu reader rejects: {after['rejected']}")
    return {
        "mode": mode,
        "target_screen": target_screen,
        "label": label,
        "replicas": len(menus["menus"]),
        "relocation": relocation_report,
    }


def remove_menu_row(payload: bytes, device_index: int) -> tuple[bytes, dict]:
    """Take one device's row out of the Devices menu, in every replica.

    The device's commands and screen stay in the image, unreachable, the way relocation
    already leaves the bytes it moves past. Removing a screen instead would renumber
    every ordinal above it and break the navigation objects that name them.

    A page that would be left with no rows is removed and the pages after it renumbered,
    which needs the menu to number its pages; a menu that does not is refused rather than
    left with an empty page.
    """
    ownership = command_index.inspect(payload)
    menus = ui_index.device_menus(payload, ownership)
    if not 0 <= device_index < len(menus["devices"]):
        raise ValueError(f"section 5 declares no device {device_index}")
    if menus["devices"][device_index]["target_screen"] is None:
        raise ValueError(f"device {device_index} has no single agreed menu row to remove")
    occurrences = [
        {"menu_screen": menu["screen"], **row}
        for menu in menus["menus"] for row in menu["rows"]
        if row["device_indices"] == [device_index]
    ]
    if len(occurrences) != len(menus["menus"]):
        raise ValueError(
            f"device {device_index} occupies {len(occurrences)} rows across "
            f"{len(menus['menus'])} menu replicas; every replica must carry it once")

    screens = ui_index.screen_slots(payload)
    start9, end9 = gspm.section_ranges(payload)[9]
    body9 = bytearray(payload[start9:end9])
    locals9 = {}
    plan = {}
    emptied = set()
    for row in occurrences:
        ordinal, index = row["menu_screen"], row["slot"]
        slot = screens[ordinal]["slots"][index]
        state = _menu_slot_state(payload, ordinal, index)
        remaining = {
            band: lines for band, lines in state["labels"].items() if band != row["row"]
        }
        if not remaining:
            emptied.add(ordinal)
            continue
        locals9[(ordinal, index)] = len(body9)
        body9 += key_register([
            (entry["key_code"], entry["operand"], entry["category"])
            for entry in slot["entries"] if entry["key_code"] != row["key_code"]
        ])
        plan[(ordinal, index)] = {"labels": remaining}
    if emptied:
        raise ValueError(
            "removing this row would leave menu pages "
            + ", ".join(map(str, sorted(emptied)))
            + " with no rows; dropping a page is not implemented")

    relocated, relocation_report = relocation.relocate(payload, {9: bytes(body9)})
    new9 = relocation_report["sections"][9]["new"][0]
    result = _rebuild_menu_pages(
        relocated, plan, {key: new9 + local for key, local in locals9.items()})
    gspm.validate(result)

    after = ui_index.device_menus(result)
    if after["counts"]["replica_menus"] != menus["counts"]["replica_menus"]:
        raise RuntimeError("the menu replicas no longer agree after removing a row")
    expected = menus["counts"]["replica_rows"] - len(occurrences)
    if after["counts"]["replica_rows"] != expected:
        raise RuntimeError(
            f"the menu now has {after['counts']['replica_rows']} rows, expected {expected}")
    if any(row["target_screen"] == occurrences[0]["target_screen"]
           for menu in after["menus"] for row in menu["rows"]):
        raise RuntimeError("the removed row still opens its screen")
    return result, {
        "mode": "remove-menu-row",
        "device_index": device_index,
        "replicas": len(occurrences),
        "orphaned_screen": occurrences[0]["target_screen"],
        "relocation": relocation_report,
    }


def rename_activity_row(payload: bytes, activity: int, label) -> tuple[bytes, dict]:
    """Rename the Activities-menu row that starts one activity.

    Only the drawn text changes: the row keeps the object that starts the activity, so
    what the row does cannot move while its name does. Unlike the Devices menu, neither
    donor replicates its Activities menu, so a row is renamed where it is found and the
    reader must still find exactly one row per activity afterwards.
    """
    before = ui_index.activity_rows(payload)
    rows = [row for row in before["rows"] if row["activity"] == activity]
    if not rows:
        raise ValueError(f"no Activities-menu row starts activity {activity}")
    if len(rows) > 1:
        raise ValueError(
            f"activity {activity} appears on {len(rows)} rows; renaming one would leave "
            "the others saying something else")
    row = rows[0]
    state = _menu_slot_state(payload, row["screen"], row["slot"])
    result = _rebuild_menu_pages(
        payload,
        {(row["screen"], row["slot"]): {
            "labels": {**state["labels"], row["row"]: label}}},
        {})
    gspm.validate(result)

    after = ui_index.activity_rows(result)
    if after["counts"] != before["counts"] or after["rejected"] != before["rejected"]:
        raise RuntimeError("renaming an activity row changed which rows the menu has")
    moved = [
        (item["activity"], item["screen"], item["slot"], item["row"], item["object_index"])
        for item in after["rows"]
    ]
    if moved != [
            (item["activity"], item["screen"], item["slot"], item["row"],
             item["object_index"])
            for item in before["rows"]]:
        raise RuntimeError("renaming an activity row changed what a row starts")
    report = glyph_codec.inspect(result)
    drawn = [
        glyph_codec.decode(bytes.fromhex(line["glyphs"]), report)
        for line in next(
            item for item in after["rows"] if item["activity"] == activity)["lines"]
    ]
    wanted = [label] if isinstance(label, str) else list(label)
    if drawn != wanted:
        raise RuntimeError(f"the row now draws {drawn}, not the label asked for")
    return result, {
        "mode": "rename-activity-row",
        "activity": activity,
        "screen": row["screen"],
        "slot": row["slot"],
        "row": row["row"],
        "label": label,
        "changed_ranges": [
            list(item) for item in relocation.changed_ranges(payload, result)
        ],
    }


def activity_start_contexts(payload: bytes) -> dict[int, list[dict]]:
    """Return the section-10 context rows that start an activity directly.

    In both donors this is one row: the Off key in the base context starting All Off.
    An activity reached this way is part of the remote's power path rather than a menu
    entry, so removing its row would strand it.
    """
    out: dict[int, list[dict]] = {}
    for context in activity_index.contexts(payload):
        for row in context["rows"]:
            if (row["category"] == activity_index.ACTIVITY
                    and row["operand"] >> 8 == ui_index.ACTIVITY_MARK):
                out.setdefault(row["operand"] & 0xFF, []).append({
                    "context": context["ordinal"], "key_code": row["key_code"],
                })
    return out


def delete_activity(payload: bytes, activity: int) -> tuple[bytes, dict]:
    """Take an activity off the Activities menu so nothing can start it.

    Its section-10 context and the objects that named it stay in the image,
    unreferenced. Reclaiming the ordinal would mean renumbering every context above it
    and every reference to those ordinals, and that cannot be proved safe yet: a large
    block of the object table is reachable from nothing this backend owns, and each
    activity's own spare object sits inside it. Until that block is accounted for, an
    activity is removed by making it unreachable, the same way a removed device's
    commands are left in place.
    """
    before = ui_index.activity_rows(payload)
    rows = [row for row in before["rows"] if row["activity"] == activity]
    if not rows:
        raise ValueError(f"no Activities-menu row starts activity {activity}")
    if len(rows) > 1:
        raise ValueError(
            f"activity {activity} appears on {len(rows)} rows; removing one would leave "
            "the others")
    started = activity_start_contexts(payload)
    if activity in started:
        where = ", ".join(
            f"context {item['context']} key {item['key_code']:#x}"
            for item in started[activity])
        raise ValueError(
            f"activity {activity} is also started from {where}; removing its menu row "
            "would leave that key starting an activity the menu no longer shows")
    row = rows[0]
    state = _menu_slot_state(payload, row["screen"], row["slot"])
    remaining = {
        band: lines for band, lines in state["labels"].items() if band != row["row"]
    }
    if not remaining:
        raise ValueError(
            f"removing activity {activity} would leave menu page {row['slot']} with no "
            "rows; dropping a page is not implemented")

    slot = ui_index.screen_slots(payload)[row["screen"]]["slots"][row["slot"]]
    start9, end9 = gspm.section_ranges(payload)[9]
    field = slot["key_register_offset"]
    if not start9 <= field < end9:
        raise ValueError(
            f"the Activities-menu key register at {field:#x} is outside section 9")
    body9 = bytearray(payload[start9:end9])
    local = len(body9)
    body9 += key_register([
        (entry["key_code"], entry["operand"], entry["category"])
        for entry in slot["entries"] if entry["key_code"] != row["key_code"]
    ])
    relocated, relocation_report = relocation.relocate(payload, {9: bytes(body9)})
    register = relocation_report["sections"][9]["new"][0] + local
    result = _rebuild_menu_pages(
        relocated,
        {(row["screen"], row["slot"]): {"labels": remaining}},
        {(row["screen"], row["slot"]): register})
    gspm.validate(result)

    after = ui_index.activity_rows(result)
    if after["counts"]["rows"] != before["counts"]["rows"] - 1:
        raise RuntimeError(
            f"the menu now shows {after['counts']['rows']} rows, expected "
            f"{before['counts']['rows'] - 1}")
    if any(item["activity"] == activity for item in after["rows"]):
        raise RuntimeError(f"activity {activity} is still on the menu")
    kept = [
        (item["activity"], item["screen"], item["slot"], item["object_index"])
        for item in after["rows"]
    ]
    if kept != [
            (item["activity"], item["screen"], item["slot"], item["object_index"])
            for item in before["rows"] if item["activity"] != activity]:
        raise RuntimeError("removing an activity row moved another one")
    contexts = activity_index.contexts(result)
    context = contexts[activity] if activity < len(contexts) else None
    return result, {
        "mode": "delete-activity",
        "activity": activity,
        "screen": row["screen"],
        "slot": row["slot"],
        "row": row["row"],
        # What stays behind, named rather than silently left: the ordinal is not
        # reclaimed, so nothing above it moves.
        "orphaned": {
            "context": None if context is None else context["ordinal"],
            "context_rows": None if context is None else len(context["rows"]),
            "objects": sorted({
                index for index, item in enumerate(command_index.objects(result))
                for value, opcode in item["atoms"]
                if opcode == activity_index.ACTIVITY
                and value >> 8 == ui_index.ACTIVITY_MARK
                and value & 0xFF == activity
            }),
        },
        "relocation": relocation_report,
    }
