"""Own Harmony One activities through their menus, contexts, and state engine.

An activity is retained as native evidence unless its section-10 ENTER/REFRESH hooks and
section-14 transitions reach indexed commands unambiguously. An empty result is explicitly
undetermined because RE-HARMONY did not establish the separate All Off/default-state path.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from collections import Counter, defaultdict
import struct

from . import command_index, gspm, key_index, named_index, ui_index


OBJECT = 0x7F
COMMAND = 0x7D
ACTIVITY = 0x1F
ENTER = 0x01
LEAVE = 0x02
REFRESH = 0x05


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


def contexts(payload: bytes) -> list[dict]:
    """Read section-10 short and long physical-key/activity contexts."""
    start, end = gspm.section_ranges(payload)[10]
    count = payload[start]
    if not 1 <= count <= 64 or start + 1 + 3 * count > end:
        raise ValueError(f"section 10 declares {count} contexts outside its index")
    out = []
    for ordinal in range(count):
        offset = _relative(payload, start + 1 + 3 * ordinal, f"context {ordinal}")
        if offset + 1 > len(payload):
            raise ValueError(f"context {ordinal} is truncated")
        short_count = payload[offset]
        long_form = short_count == 0
        row_count = payload[offset + 1] if long_form and offset + 1 < len(payload) else short_count
        header = 2 if long_form else 1
        width = 5 if long_form else 4
        if offset + header + width * row_count > len(payload):
            raise ValueError(f"context {ordinal} is truncated")
        rows = []
        for index in range(row_count):
            at = offset + header + width * index
            flags = payload[at] if long_form else None
            code_at = at + 1 if long_form else at
            operand, category = struct.unpack_from("<HB", payload, code_at + 1)
            rows.append({
                "index": index, "offset": at, "flags": flags,
                "key_code": payload[code_at], "operand": operand, "category": category,
            })
        out.append({
            "ordinal": ordinal, "offset": offset,
            "form": "long" if long_form else "short", "rows": rows,
        })
    return out


def engine_records(payload: bytes) -> list[dict]:
    """Read section-14 property records and their eight-byte transitions."""
    start, end = gspm.section_ranges(payload)[14]
    if end - start < 8:
        raise ValueError("section 14 is shorter than its activity-engine header")
    count = struct.unpack_from("<H", payload, start)[0]
    if end - start != 8 + 3 * count:
        raise ValueError(
            f"section 14 size {end - start} does not match 8 + 3 * {count}")
    out = []
    for property_id in range(count):
        offset = _relative(payload, start + 8 + 3 * property_id,
                           f"activity property {property_id}")
        if offset + 7 > len(payload):
            raise ValueError(f"activity property {property_id} is truncated")
        initial, limit, transition_count = struct.unpack_from("<HHH", payload, offset)
        if offset + 7 + 8 * transition_count > len(payload):
            raise ValueError(f"activity property {property_id} transitions are truncated")
        transitions = []
        for index in range(transition_count):
            at = offset + 7 + 8 * index
            flags, source, target, operand, category = struct.unpack_from(
                "<BHHHB", payload, at)
            transitions.append({
                "index": index, "offset": at, "flags": flags, "from": source,
                "to": target, "operand": operand, "category": category,
            })
        out.append({
            "property_id": property_id, "offset": offset, "initial": initial,
            "limit": limit, "padding": payload[offset + 6], "transitions": transitions,
        })
    return out


def _object_commands(objects: list[dict], index: int) -> set[int]:
    stack = [index]
    seen = set()
    commands = set()
    while stack:
        current = stack.pop()
        if current in seen or not 0 <= current < len(objects):
            continue
        seen.add(current)
        for operand, opcode in objects[current]["atoms"]:
            if opcode == COMMAND:
                commands.add(operand)
            elif opcode == OBJECT:
                stack.append(operand)
    return commands


def _object_sets(objects: list[dict], index: int) -> list[tuple[int, int]]:
    stack = [index]
    seen = set()
    writes = []
    while stack:
        current = stack.pop()
        if current in seen or not 0 <= current < len(objects):
            continue
        seen.add(current)
        for operand, opcode in objects[current]["atoms"]:
            if opcode >= 0x80:
                writes.append((opcode & 0x7F, operand))
            elif opcode == OBJECT:
                stack.append(operand)
    return writes


def physical_contexts(
        payload: bytes, ownership: dict | None = None, context_rows: list[dict] | None = None,
) -> dict:
    """Classify the physical-key bindings stored in every section-10 context."""
    ownership = command_index.inspect(payload) if ownership is None else ownership
    context_rows = contexts(payload) if context_rows is None else context_rows
    indexed = {
        command["command_id"]
        for device in ownership["devices"] for command in device["commands"]
    }
    objects = command_index.objects(payload)
    button_kinds = {
        row["key_code"]: row["classification"]
        for row in ui_index.button_inventory(payload)["rows"]
    }
    rejected = Counter()
    out = []
    editable_count = 0
    for context in context_rows:
        rows = []
        for source in context["rows"]:
            row = dict(source)
            row["key_classification"] = button_kinds.get(source["key_code"], "not_in_inventory")
            row.update({
                "shape": "other", "command_id": None, "device_id": None,
                "target_page": None, "editable": False,
            })
            if source["category"] != OBJECT:
                row["reason"] = "not_an_object_reference"
            elif not 0 <= source["operand"] < len(objects):
                row["reason"] = "object_outside_table"
                rejected[row["reason"]] += 1
            else:
                atoms = objects[source["operand"]]["atoms"]
                commands = [operand for operand, opcode in atoms if opcode == COMMAND]
                devices = [operand for operand, opcode in atoms if opcode == 0x7C]
                pages = [operand for operand, opcode in atoms if opcode == 0x7E]
                other = [opcode for _operand, opcode in atoms if opcode not in (0x7C, 0x7D, 0x7E)]
                if (commands or devices) and not other:
                    row["shape"] = "direct"
                else:
                    jumps = [operand for operand, opcode in atoms if opcode == OBJECT]
                    if len(jumps) == 1 and 0 <= jumps[0] < len(objects):
                        nested = objects[jumps[0]]["atoms"]
                        nested_commands = [
                            operand for operand, opcode in nested if opcode == COMMAND]
                        nested_devices = [
                            operand for operand, opcode in nested if opcode == 0x7C]
                        if nested_commands and nested_devices:
                            row["shape"] = "indirect"
                            commands = nested_commands
                            devices = nested_devices
                if len(commands) == 1:
                    row["command_id"] = commands[0]
                if len(devices) == 1:
                    row["device_id"] = devices[0]
                if len(pages) == 1:
                    row["target_page"] = pages[0]
                if row["shape"] not in ("direct", "indirect"):
                    row["reason"] = "unrecognized_object_shape"
                elif len(commands) != 1 or len(devices) != 1:
                    row["reason"] = "incomplete_or_ambiguous_command_device"
                    rejected[row["reason"]] += 1
                elif commands[0] not in indexed:
                    row["reason"] = "command_not_in_section5"
                    rejected[row["reason"]] += 1
                elif devices[0] >> 8 != commands[0] >> 8:
                    row["reason"] = "command_device_mismatch"
                    rejected[row["reason"]] += 1
                else:
                    row["editable"] = True
                    row["device_index"] = commands[0] >> 8
                    editable_count += 1
            rows.append(row)
        out.append({
            "ordinal": context["ordinal"], "offset": context["offset"],
            "form": context["form"], "rows": rows,
            "editable_rows": sum(row["editable"] for row in rows),
        })
    return {
        "counts": {
            "contexts": len(out), "rows": sum(len(context["rows"]) for context in out),
            "editable_rows": editable_count,
        },
        "rejected": dict(rejected), "contexts": out,
    }


def activity_menu(payload: bytes) -> dict | None:
    """Find the screen whose row objects select `0xff00 | activity`."""
    objects = command_index.objects(payload)
    templates = ui_index.touch_templates(payload)
    for screen in ui_index.screen_slots(payload):
        for slot in screen["slots"]:
            activity_rows = {}
            for entry in slot["entries"]:
                if entry["category"] != OBJECT or not 0 <= entry["operand"] < len(objects):
                    continue
                choices = [
                    operand & 0xFF
                    for operand, opcode in objects[entry["operand"]]["atoms"]
                    if opcode == ACTIVITY and operand >> 8 == 0xFF
                ]
                if len(choices) == 1:
                    activity_rows[entry["key_code"]] = {
                        "activity": choices[0], "object_index": entry["operand"],
                    }
            if not activity_rows:
                continue
            zones = templates.get(slot["template"], [])
            ordered = [
                zone["key_code"] for zone in sorted(
                    (zone for zone in zones if zone["tag"] not in ui_index.SIDE_STRIP_TAGS),
                    key=lambda zone: (-zone["y"], zone["x"]),
                ) if zone["key_code"] in activity_rows
            ]
            program = ui_index.drawing_program(payload, slot["program_offset"])
            labels: dict[int, list[dict]] = defaultdict(list)
            for instruction in program["instructions"]:
                if (instruction["opcode"] in ("text", "inline_text")
                        and instruction["x"] == ui_index.DEVICE_LABEL_X):
                    row = ui_index.row_index(instruction["y"])
                    if row is not None:
                        labels[row].append({
                            "y": instruction["y"], "glyphs": instruction["glyphs"],
                            "target": instruction.get("target"),
                        })
            rows = []
            for row_index, code in zip(sorted(labels), ordered):
                rows.append({
                    "row": row_index, "key_code": code, **activity_rows[code],
                    "lines": sorted(labels[row_index], key=lambda item: item["y"]),
                })
            return {
                "screen": screen["ordinal"], "slot": slot["index"],
                "template": slot["template"], "rows": rows,
                "unlabeled_rows": max(0, len(activity_rows) - len(rows)),
            }
    return None


def inspect(
        payload: bytes, ownership: dict | None = None, names_report: dict | None = None,
) -> dict:
    """Attribute activity hooks and property transitions to indexed commands."""
    ownership = command_index.inspect(payload) if ownership is None else ownership
    indexed_commands = {
        command["command_id"]
        for device in ownership["devices"] for command in device["commands"]
    }
    objects = command_index.objects(payload)
    if names_report is None:
        try:
            names_report = named_index.inspect(payload)
        except ValueError:
            names_report = {"records": []}
    names = named_index.leaf_names(names_report)
    context_rows = contexts(payload)
    physical = physical_contexts(payload, ownership, context_rows)
    engine = engine_records(payload)
    menu = activity_menu(payload)
    menu_names = {
        row["activity"]: [line["glyphs"] for line in row["lines"]]
        for row in (menu or {}).get("rows", [])
    }
    menu_ordinals = set(menu_names)
    rejected = Counter()
    activities = []
    all_engine_commands = set()
    for record in engine:
        for transition in record["transitions"]:
            if transition["category"] == OBJECT:
                all_engine_commands |= _object_commands(objects, transition["operand"])
    for context in context_rows:
        hooks = {
            name: next((row for row in context["rows"] if row["key_code"] == code), None)
            for name, code in (("enter", ENTER), ("leave", LEAVE), ("refresh", REFRESH))
        }
        if hooks["enter"] is None:
            continue
        writes = []
        reached_commands = set()
        for hook_name in ("enter", "refresh"):
            hook = hooks[hook_name]
            if hook is None or hook["category"] != OBJECT:
                continue
            for property_id, value in _object_sets(objects, hook["operand"]):
                transitions = engine[property_id]["transitions"] if property_id < len(engine) else []
                matching = [item for item in transitions if item["to"] == value]
                commands = set()
                for transition in matching:
                    if transition["category"] == OBJECT:
                        commands |= _object_commands(objects, transition["operand"])
                invalid = commands - indexed_commands
                if invalid:
                    rejected["activity_command_not_in_section5"] += len(invalid)
                commands &= indexed_commands
                reached_commands |= commands
                writes.append({
                    "hook": hook_name, "property_id": property_id, "value": value,
                    "property_name": names.get(property_id),
                    "limit": engine[property_id]["limit"] if property_id < len(engine) else None,
                    "transition_count": len(transitions),
                    "command_ids": sorted(commands),
                    "device_indices": sorted({command >> 8 for command in commands}),
                })
        activities.append({
            "ordinal": context["ordinal"], "context_offset": context["offset"],
            "context_form": context["form"], "in_menu": context["ordinal"] in menu_ordinals,
            "glyph_lines": menu_names.get(context["ordinal"], []),
            "hooks": {
                name: None if row is None else {
                    "object_index": row["operand"], "category": row["category"],
                }
                for name, row in hooks.items()
            },
            "writes": writes, "command_ids": sorted(reached_commands),
            "device_indices": sorted({command >> 8 for command in reached_commands}),
            "determined": bool(reached_commands),
        })
    mixed_screens: dict[int, set[int]] = defaultdict(set)
    for binding in key_index.inspect(payload, ownership)["bindings"]:
        mixed_screens[binding["screen"]].add(binding["command_id"] >> 8)
    mixed = [
        {"screen": screen, "device_indices": sorted(devices)}
        for screen, devices in sorted(mixed_screens.items()) if len(devices) > 1
    ]
    return {
        "counts": {
            "contexts": len(context_rows), "context_rows": sum(
                len(context["rows"]) for context in context_rows),
            "engine_properties": len(engine), "engine_transitions": sum(
                len(record["transitions"]) for record in engine),
            "activities": len(activities),
            "determined_activities": sum(item["determined"] for item in activities),
            "menu_activities": len(menu_ordinals), "mixed_device_screens": len(mixed),
            "engine_commands": len(all_engine_commands),
            "physical_context_rows": physical["counts"]["rows"],
            "editable_physical_context_rows": physical["counts"]["editable_rows"],
        },
        "rejected": dict(rejected), "menu": menu, "activities": activities,
        "physical_contexts": physical,
        "mixed_device_screens": mixed,
    }
