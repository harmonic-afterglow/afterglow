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
    # The index must fit; the section is not required to end with it. Every other
    # counted index here is checked that way, and sections routinely carry more than
    # their index - section 15 keeps a 151-byte table after its count, section 6 its
    # trailers and slots. Demanding an exact size held for the donors by luck and
    # refused any image whose last section absorbed the padding byte a body of odd
    # length gets closed with.
    if start + 8 + 3 * count > end:
        raise ValueError(
            f"section 14 index of {count} records exceeds its section")
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
        # LEAVE is followed too, though it has never reached a command: every activity
        # but All Off carries one, each writing eight properties, and in all four donors
        # not one of those writes reaches an indexed command. Following it costs nothing
        # and stops the hook being read and silently dropped.
        for hook_name in ("enter", "refresh", "leave"):
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
            # An activity that reaches no command is not necessarily unresolved. The
            # All Off context writes eight properties in every donor, none of them one
            # that drives a device, and its set is always a subset of what a real
            # activity writes - so it is state-only by construction rather than by our
            # failing to follow it. Its command path is not in section 14 at all.
            "state_only": not reached_commands and bool(writes) and not any(
                item["command_ids"] for item in writes),
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
            "state_only_activities": sum(item["state_only"] for item in activities),
            "menu_activities": len(menu_ordinals), "mixed_device_screens": len(mixed),
            "engine_commands": len(all_engine_commands),
            "physical_context_rows": physical["counts"]["rows"],
            "editable_physical_context_rows": physical["counts"]["editable_rows"],
        },
        "rejected": dict(rejected), "menu": menu, "activities": activities,
        "physical_contexts": physical,
        "mixed_device_screens": mixed,
    }


# Section 14 falls into three parts in every image measured, the factory configuration in
# firmware 54.2.5 included. Records 0 to 6 are the clock section 3 also holds. Records 7
# to 17 are platform properties with no transitions, byte-identical across the donors.
# The final record is a terminator. What lies between is the household part.
CLOCK_PROPERTIES = 7
PLATFORM_PROPERTIES = 18
TERMINATOR_LIMIT = 0xFEFD
# `from` in a transition, meaning "whatever state the property is in now".
ANY_STATE = 0xFFFE
COMMAND_ATOM = 0x7D
OBJECT_ATOM = 0x7F


def _sent_commands(objects: list[dict], index: int, seen=None, depth: int = 0) -> list:
    """Every (device, command) an object sends, following the objects it references."""
    seen = set() if seen is None else seen
    out: list[tuple[int, int]] = []
    if not 0 <= index < len(objects) or index in seen or depth > 6:
        return out
    seen.add(index)
    for value, kind in objects[index]["atoms"]:
        if kind == COMMAND_ATOM:
            # Both fields of a command object carry the device in their high byte.
            out.append((value >> 8, value & 0xFF))
        elif kind == OBJECT_ATOM:
            out += _sent_commands(objects, value, seen, depth + 1)
    return out


def engine_shape(payload: bytes, objects: list[dict] | None = None) -> dict:
    """Split section 14 into its three parts and say which device each record drives.

    A household property is a device's discrete state: its limit is the highest state it
    reaches, and each transition names an object holding the commands that get there. The
    pattern is visible in the objects - one donor reaches state N by sending a setup
    command, the input command N times, then a confirm - which is how a device whose input
    is cycled by a single button is driven.

    Every household record that sends anything sends it to exactly one device: 5, 8, 11
    and 5 records across the four donors, never two devices in one record. Records that
    send nothing are state the remote tracks but cannot drive.
    """
    from . import command_index

    objects = command_index.objects(payload) if objects is None else objects
    records = engine_records(payload)
    terminator = (
        records[-1] if records and records[-1]["limit"] == TERMINATOR_LIMIT else None)
    body = records[:-1] if terminator is not None else records
    household = body[PLATFORM_PROPERTIES:]
    driven = {}
    for record in household:
        devices = set()
        for transition in record["transitions"]:
            if transition["category"] == OBJECT_ATOM:
                devices |= {
                    device for device, _command
                    in _sent_commands(objects, transition["operand"])
                }
        driven[record["property_id"]] = sorted(devices)
    return {
        "clock": body[:CLOCK_PROPERTIES],
        "platform": body[CLOCK_PROPERTIES:PLATFORM_PROPERTIES],
        "household": household,
        "terminator": terminator,
        # Which device each household property drives, by property id.
        "driven": driven,
        "counts": {
            "records": len(records),
            "household": len(household),
            "driving": sum(1 for value in driven.values() if value),
            "silent": sum(1 for value in driven.values() if not value),
            "ambiguous": sum(1 for value in driven.values() if len(value) > 1),
        },
    }


def current_activity(payload: bytes, activities: int) -> int | None:
    """The activity a configuration was saved in, if section 14 names one unambiguously.

    One household property counts the activities: its limit is one less than how many
    there are, and its initial value is the one that was running. Where a configuration
    has few activities that limit is shared with the boolean properties, so a non-zero
    initial is what singles it out - which means an image saved in activity zero cannot
    be told from one that names no activity at all.
    """
    if activities < 1:
        return None
    shape = engine_shape(payload)
    found = [
        record["initial"] for record in shape["household"]
        if record["limit"] == activities - 1 and record["initial"]
    ]
    if len(found) != 1 or found[0] >= activities:
        return None
    return found[0]


def all_off(payload: bytes, objects: list[dict] | None = None) -> dict:
    """The commands turning everything off, and the properties they come from.

    The All Off context stores none of them. It writes eight properties in every donor,
    none of which drives a device, so following its hooks reaches nothing and it looked
    for a while as though the path were missing. It is not stored because it does not
    need to be: every property that drives a device has exactly one transition to state
    zero and that transition carries a command - 5, 8, 11 and 5 properties across the
    four donors, without exception - so turning everything off is driving every property
    to zero, using the transitions the activities themselves installed.

    A property whose limit is 1 and which drives a device is a power toggle: state 1 on,
    state 0 off. Most devices have one. Where a device has none, its power sits inside a
    property with more states, which is why counting limit-1 records alone does not give
    the device count.
    """
    from . import command_index

    objects = command_index.objects(payload) if objects is None else objects
    ownership = command_index.inspect(payload)
    indexed = {
        command["command_id"]
        for device in ownership["devices"] for command in device["commands"]
    }
    records = engine_records(payload)
    shape = engine_shape(payload, objects)
    out, missing = {}, []
    for property_id, devices in sorted(shape["driven"].items()):
        if not devices:
            continue
        record = records[property_id]
        commands: set[int] = set()
        for transition in record["transitions"]:
            if transition["to"] == 0 and transition["category"] == OBJECT:
                commands |= _object_commands(objects, transition["operand"]) & indexed
        if not commands:
            missing.append(property_id)
        out[property_id] = {
            "device": devices[0] if len(devices) == 1 else None,
            "limit": record["limit"],
            "power_toggle": record["limit"] == 1,
            "command_ids": sorted(commands),
        }
    commands = sorted({
        command for item in out.values() for command in item["command_ids"]})
    return {
        "properties": out,
        "command_ids": commands,
        "device_indices": sorted({command >> 8 for command in commands}),
        # A driving property with no way back to zero would leave a device on.
        "properties_without_an_off": missing,
        "counts": {
            "properties": len(out), "commands": len(commands),
            "power_toggles": sum(item["power_toggle"] for item in out.values()),
        },
    }
