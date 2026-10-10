"""Index Harmony One drawing programs, touch geometry, and owned menu labels.

Text remains a sequence of image-local glyph codes until its font mapping is proved.  A
menu row is owned by the touch zone that opens its target screen, rather than by scanning
for plausible strings or assuming every menu replica has the same row order.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import struct

from . import command_index, gspm, key_index


SIDE_STRIP_TAGS = frozenset((0x2E, 0x2F))
DEVICE_LABEL_X = 0x3F
DEVICE_ROW_CENTERS = (57, 111, 165)
ROW_TOLERANCE = 12


def _u24(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset:offset + 3], "little")


def _relative(payload: bytes, offset: int, label: str, *, allow_zero: bool = False) -> int | None:
    if not (0 <= offset and offset + 3 <= len(payload)):
        raise ValueError(f"{label} pointer field falls outside the GSPM image")
    absolute = _u24(payload, offset)
    if not absolute and allow_zero:
        return None
    relative = absolute - gspm.BASE
    if not 0 <= relative < len(payload):
        raise ValueError(f"{label} points outside the GSPM image: {absolute:#08x}")
    return relative


def _terminated_glyphs(payload: bytes, offset: int) -> bytes:
    if not 0 <= offset < len(payload):
        raise ValueError(f"glyph string starts outside the GSPM image: {offset:#x}")
    end = payload.find(b"\x00", offset)
    if end < 0:
        raise ValueError(f"glyph string at {offset:#x} has no terminator")
    return payload[offset:end]


def drawing_program(payload: bytes, offset: int, *, limit: int = 400) -> dict:
    """Disassemble the measured drawing VM without following jumps or calls."""
    instructions = []
    cursor = offset
    stopped = "limit"
    for _ in range(limit):
        if not 0 <= cursor < len(payload):
            stopped = "outside_image"
            break
        at = cursor
        opcode = payload[cursor]
        cursor += 1
        if opcode == 0x00:
            instructions.append({"offset": at, "opcode": "end"})
            stopped = "end"
            break
        if opcode == 0x17:
            instructions.append({"offset": at, "opcode": "return"})
            stopped = "return"
            break
        if opcode in (0x14, 0x16):
            target = _relative(payload, cursor, f"drawing opcode {opcode:#04x}")
            instructions.append({
                "offset": at,
                "opcode": "jump" if opcode == 0x14 else "call",
                "target": target,
            })
            cursor += 3
            if opcode == 0x14:
                stopped = "jump"
                break
            continue
        if opcode == 0x10:
            if cursor >= len(payload):
                stopped = "truncated"
                break
            instructions.append({"offset": at, "opcode": "attribute", "value": payload[cursor]})
            cursor += 1
            continue
        if opcode in (0x02, 0x04):
            if cursor + 5 > len(payload):
                stopped = "truncated"
                break
            target = _relative(payload, cursor + 2, f"drawing opcode {opcode:#04x}")
            item = {
                "offset": at,
                "opcode": "bitmap" if opcode == 0x02 else "text",
                "x": payload[cursor],
                "y": payload[cursor + 1],
                "target": target,
            }
            if opcode == 0x04:
                item["glyphs"] = _terminated_glyphs(payload, target).hex()
            instructions.append(item)
            cursor += 5
            continue
        if opcode == 0x05:
            if cursor + 2 > len(payload):
                stopped = "truncated"
                break
            end = payload.find(b"\x00", cursor + 2)
            if end < 0:
                stopped = "truncated"
                break
            instructions.append({
                "offset": at,
                "opcode": "inline_text",
                "x": payload[cursor],
                "y": payload[cursor + 1],
                "glyphs": payload[cursor + 2:end].hex(),
            })
            cursor = end + 1
            continue
        if opcode == 0x11:
            if cursor + 3 > len(payload):
                stopped = "truncated"
                break
            operand, category = struct.unpack_from("<HB", payload, cursor)
            instructions.append({
                "offset": at, "opcode": "atom", "operand": operand, "category": category,
            })
            cursor += 3
            continue
        if opcode == 0x01:
            if cursor + 6 > len(payload):
                stopped = "truncated"
                break
            x, y, width, height, color = struct.unpack_from("<BBBBH", payload, cursor)
            instructions.append({
                "offset": at, "opcode": "rectangle", "x": x, "y": y,
                "width": width, "height": height, "color": color,
            })
            cursor += 6
            continue
        if opcode == 0x12:
            if cursor + 2 > len(payload):
                stopped = "truncated"
                break
            selector, case_count = payload[cursor:cursor + 2]
            cursor += 2
            cases = []
            for case in range(case_count):
                if cursor + 4 > len(payload):
                    stopped = "truncated"
                    break
                cases.append((payload[cursor], _relative(
                    payload, cursor + 1, f"drawing switch case {case}")))
                cursor += 4
            else:
                if cursor >= len(payload):
                    stopped = "truncated"
                    break
                range_count = payload[cursor]
                cursor += 1
                ranges = []
                for range_index in range(range_count):
                    if cursor + 5 > len(payload):
                        stopped = "truncated"
                        break
                    ranges.append((payload[cursor], payload[cursor + 1], _relative(
                        payload, cursor + 2, f"drawing switch range {range_index}")))
                    cursor += 5
                else:
                    instructions.append({
                        "offset": at, "opcode": "switch", "selector": selector,
                        "cases": cases, "ranges": ranges,
                    })
                    continue
            break
        instructions.append({"offset": at, "opcode": "unknown", "value": opcode})
        stopped = "unknown_opcode"
        break
    return {"offset": offset, "instructions": instructions, "stopped": stopped}


def touch_templates(payload: bytes) -> dict[int, list[dict]]:
    """Return section-19 touch zones, guarded by each zone's self-pointer."""
    start, end = gspm.section_ranges(payload)[19]
    count = payload[start]
    if start + 1 + 3 * count > end:
        raise ValueError(f"section 19 declares {count} templates outside its index")
    out = {}
    for template in range(count):
        table = _relative(payload, start + 1 + 3 * template, f"touch template {template}")
        zone_count = payload[table]
        if table + 1 + 3 * zone_count > len(payload):
            raise ValueError(f"touch template {template} has a truncated zone index")
        zones = []
        for index in range(zone_count):
            zone = _relative(payload, table + 1 + 3 * index,
                             f"touch template {template} zone {index}")
            if zone + 12 > len(payload):
                raise ValueError(f"touch template {template} zone {index} is truncated")
            self_pointer = _relative(payload, zone + 9,
                                     f"touch template {template} zone {index} self")
            if self_pointer != zone:
                raise ValueError(
                    f"touch template {template} zone {index} self-pointer does not close")
            x, width, y, height = struct.unpack_from("<HHHH", payload, zone)
            tag = payload[zone + 8]
            zones.append({
                "index": index, "offset": zone, "tag": tag, "key_code": tag | 0x80,
                "x": x, "width": width, "y": y, "height": height,
            })
        out[template] = zones
    return out


def button_inventory(payload: bytes) -> dict:
    """Read the header's key vocabulary; its sequential u16 is not a binding."""
    offset = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC) - 1
    count = payload[offset]
    if offset + 1 + 4 * count > len(payload):
        raise ValueError(f"button inventory declares {count} rows outside the image")
    touch_codes = {
        zone["key_code"] for zones in touch_templates(payload).values() for zone in zones
    }
    rows = []
    classification = Counter()
    for index in range(count):
        at = offset + 1 + 4 * index
        code, row_index, tag = struct.unpack_from("<BHB", payload, at)
        if code in (0x06, 0x07):
            kind = "system_hook"
        elif code in (0xAB, 0xAC):
            kind = "established_touch"
        elif code in (0xAE, 0xAF):
            kind = "paging_strip"
        elif code in (0xB0, 0xB1, 0xB2, 0xB3, 0xB4, 0xB5) and code in touch_codes:
            kind = "physical_touch_ambiguous"
        elif code in touch_codes:
            kind = "touch"
        else:
            kind = "physical_candidate"
        classification[kind] += 1
        rows.append({
            "index": index, "offset": at, "key_code": code,
            "row_index": row_index, "tag": tag, "classification": kind,
        })
    return {
        "count": count,
        "index_is_sequential": all(row["row_index"] == row["index"] for row in rows),
        "classification": dict(classification), "rows": rows,
    }


def section12_programs(payload: bytes) -> dict[int, int]:
    """Return the section-12 drawing subprogram index."""
    start, end = gspm.section_ranges(payload)[12]
    count = struct.unpack_from("<H", payload, start)[0]
    if start + 2 + 3 * count > end:
        raise ValueError(f"section 12 declares {count} programs outside its index")
    return {
        index: _relative(payload, start + 2 + 3 * index, f"section 12 program {index}")
        for index in range(count)
    }


def walk_drawing(payload: bytes, offset: int, programs12: dict[int, int] | None = None) -> dict:
    """Walk every statically reachable drawing block from one screen program."""
    programs12 = section12_programs(payload) if programs12 is None else programs12
    stack = [offset]
    visited = set()
    instructions = []
    rejected = Counter()
    while stack:
        target = stack.pop()
        if target in visited:
            continue
        if not 0 <= target < len(payload):
            rejected["target_outside_image"] += 1
            continue
        visited.add(target)
        block = drawing_program(payload, target)
        instructions.extend(block["instructions"])
        if block["stopped"] in ("unknown_opcode", "truncated", "outside_image", "limit"):
            rejected[block["stopped"]] += 1
        for instruction in block["instructions"]:
            opcode = instruction["opcode"]
            if opcode in ("call", "jump"):
                stack.append(instruction["target"])
            elif opcode == "switch":
                stack.extend(target for _value, target in instruction["cases"])
                stack.extend(target for _low, _high, target in instruction["ranges"])
            elif opcode == "atom" and instruction["category"] == 0x73:
                subprogram = programs12.get(instruction["operand"])
                if subprogram is None:
                    rejected["missing_section12_program"] += 1
                else:
                    stack.append(subprogram)
    return {
        "blocks": len(visited), "instructions": instructions, "rejected": dict(rejected),
    }


def _bitmap_resource(payload: bytes, offset: int) -> dict:
    # Mode, then width and height as u16s, for both modes.
    if offset + 5 > len(payload):
        raise ValueError(f"bitmap at {offset:#x} has a truncated header")
    mode, width, height = struct.unpack_from("<BHH", payload, offset)
    if mode not in (0, 1) or not 1 <= width <= 176 or not 1 <= height <= 220:
        raise ValueError(f"bitmap at {offset:#x} has an invalid header")
    if mode == 0:
        size = 5 + 2 * width * height
        if offset + size > len(payload):
            raise ValueError(f"bitmap at {offset:#x} is truncated")
    else:
        cursor = offset + 5
        rows = 0
        row_width = 0
        while cursor < len(payload):
            control = payload[cursor]
            cursor += 1
            if control == 0:
                if row_width:
                    rows += 1
                break
            if control == 0x80:
                if row_width != width:
                    raise ValueError(f"bitmap at {offset:#x} has an inconsistent row width")
                rows += 1
                row_width = 0
                continue
            length = control & 0x7F
            row_width += length
            if not control & 0x80:
                cursor += 2 * length
            if cursor > len(payload) or row_width > width:
                raise ValueError(f"bitmap at {offset:#x} has a truncated run")
        else:
            raise ValueError(f"bitmap at {offset:#x} has no terminator")
        if rows != height or row_width not in (0, width):
            raise ValueError(f"bitmap at {offset:#x} does not match its declared dimensions")
        size = cursor - offset
    return {"offset": offset, "mode": mode, "width": width, "height": height, "size": size}


def drawing_inventory(payload: bytes) -> dict:
    """Inventory statically reachable drawing instructions and referenced bitmaps."""
    programs12 = section12_programs(payload)
    instruction_counts = Counter()
    rejected = Counter()
    bitmap_uses: dict[int, list[dict]] = defaultdict(list)
    text_uses = 0
    blocks = 0
    for screen in screen_slots(payload):
        for slot in screen["slots"]:
            walked = walk_drawing(payload, slot["program_offset"], programs12)
            blocks += walked["blocks"]
            rejected.update(walked["rejected"])
            for instruction in walked["instructions"]:
                instruction_counts[instruction["opcode"]] += 1
                if instruction["opcode"] == "bitmap":
                    bitmap_uses[instruction["target"]].append({
                        "screen": screen["ordinal"], "slot": slot["index"],
                        "x": instruction["x"], "y": instruction["y"],
                    })
                elif instruction["opcode"] in ("text", "inline_text"):
                    text_uses += 1
    resources = []
    for offset, uses in sorted(bitmap_uses.items()):
        try:
            resource = _bitmap_resource(payload, offset)
        except ValueError:
            rejected["invalid_bitmap_resource"] += 1
            continue
        resource["uses"] = uses
        resources.append(resource)
    return {
        "counts": {
            "blocks": blocks, "instructions": sum(instruction_counts.values()),
            "text_uses": text_uses, "bitmap_uses": sum(len(v) for v in bitmap_uses.values()),
            "referenced_bitmaps": len(bitmap_uses), "decoded_bitmaps": len(resources),
        },
        "instruction_counts": dict(instruction_counts), "rejected": dict(rejected),
        "bitmaps": resources,
    }


def _glyph_shape(payload: bytes, offset: int) -> dict:
    """Decode a font glyph's mode-0 run stream into a palette-independent shape."""
    if not 0 <= offset < len(payload):
        raise ValueError(f"glyph starts outside the GSPM image: {offset:#x}")
    declared_width = payload[offset]
    cursor = offset + 1
    rows: list[bytes] = []
    row = bytearray()
    width = None
    while cursor < len(payload):
        control = payload[cursor]
        cursor += 1
        if control == 0:
            if row:
                rows.append(bytes(row))
            break
        if control == 0x80:
            if width is None:
                width = len(row)
            elif len(row) != width:
                raise ValueError(f"glyph at {offset:#x} has inconsistent row widths")
            rows.append(bytes(row))
            row.clear()
            if len(rows) > 220:
                raise ValueError(f"glyph at {offset:#x} exceeds the display height")
            continue
        length = control & 0x7F
        if not length:
            raise ValueError(f"glyph at {offset:#x} has a zero-length run")
        if control & 0x80:
            row.extend(b"\x00" * length)
        else:
            if cursor + 2 * length > len(payload):
                raise ValueError(f"glyph at {offset:#x} has a truncated literal run")
            row.extend(b"\x01" * length)
            cursor += 2 * length
        if len(row) > 176:
            raise ValueError(f"glyph at {offset:#x} exceeds the display width")
    else:
        raise ValueError(f"glyph at {offset:#x} has no terminator")
    if not rows:
        raise ValueError(f"glyph at {offset:#x} has no rows")
    width = len(rows[0]) if width is None else width
    if any(len(item) != width for item in rows) or declared_width != width:
        raise ValueError(
            f"glyph at {offset:#x} declares width {declared_width}, decoded {width}")
    shape = bytes([width, len(rows)]) + b"".join(rows)
    return {
        "offset": offset, "width": width, "height": len(rows),
        "shape": hashlib.sha256(shape).hexdigest(), "encoded_size": cursor - offset,
    }


def font_inventory(payload: bytes) -> dict:
    """Inventory section-7 fonts and stable shapes without assigning characters."""
    start, end = gspm.section_ranges(payload)[7]
    count = struct.unpack_from("<H", payload, start)[0]
    if start + 2 + 3 * count > end:
        raise ValueError(f"section 7 declares {count} fonts outside its index")
    fonts = []
    rejected = Counter()
    shapes: dict[str, set[int]] = defaultdict(set)
    for attribute in range(count):
        offset = _relative(payload, start + 2 + 3 * attribute, f"font {attribute}")
        if offset + 3 > len(payload):
            raise ValueError(f"font {attribute} header is truncated")
        height = payload[offset]
        glyph_count = struct.unpack_from("<H", payload, offset + 1)[0]
        if offset + 3 + 3 * glyph_count > len(payload):
            raise ValueError(f"font {attribute} glyph index is truncated")
        present = 0
        decoded = 0
        for index in range(glyph_count):
            glyph = _relative(payload, offset + 3 + 3 * index,
                              f"font {attribute} glyph {index + 1}", allow_zero=True)
            if glyph is None:
                continue
            present += 1
            try:
                info = _glyph_shape(payload, glyph)
            except ValueError:
                rejected["invalid_glyph"] += 1
                continue
            decoded += 1
            shapes[info["shape"]].add(index + 1)
        fonts.append({
            "attribute": attribute, "offset": offset, "height": height,
            "declared_glyphs": glyph_count, "present_glyphs": present,
            "decoded_glyphs": decoded,
        })
    return {
        "counts": {
            "fonts": count,
            "declared_glyph_slots": sum(item["declared_glyphs"] for item in fonts),
            "present_glyphs": sum(item["present_glyphs"] for item in fonts),
            "decoded_glyphs": sum(item["decoded_glyphs"] for item in fonts),
            "distinct_shapes": len(shapes),
            "shapes_with_multiple_codes": sum(len(codes) > 1 for codes in shapes.values()),
        },
        "rejected": dict(rejected),
        "fonts": fonts,
    }


def screen_slots(payload: bytes) -> list[dict]:
    start, end = gspm.section_ranges(payload)[6]
    count = struct.unpack_from("<H", payload, start)[0]
    if payload[start + 2] != 0 or start + 3 + 3 * count > end:
        raise ValueError("section 6 has an invalid screen index")
    screens = []
    for ordinal in range(count):
        trailer = _relative(payload, start + 3 + 3 * ordinal, f"screen {ordinal}")
        if trailer + 6 > len(payload):
            raise ValueError(f"screen {ordinal} trailer is truncated")
        slot_count = struct.unpack_from("<H", payload, trailer + 4)[0]
        if not slot_count or trailer + 6 + 3 * slot_count > len(payload):
            raise ValueError(f"screen {ordinal} has an invalid slot index")
        slots = []
        for index in range(slot_count):
            offset = _relative(payload, trailer + 6 + 3 * index,
                               f"screen {ordinal} slot {index}")
            if offset + 7 > len(payload):
                raise ValueError(f"screen {ordinal} slot {index} is truncated")
            key_register = _relative(payload, offset + 1,
                                     f"screen {ordinal} slot {index} key register")
            program = _relative(payload, offset + 4,
                                f"screen {ordinal} slot {index} program")
            entry_count = payload[key_register]
            if key_register + 1 + 4 * entry_count > len(payload):
                raise ValueError(f"screen {ordinal} slot {index} key register is truncated")
            entries = []
            for entry in range(entry_count):
                at = key_register + 1 + 4 * entry
                code = payload[at]
                operand, category = struct.unpack_from("<HB", payload, at + 1)
                entries.append({
                    "key_code": code, "operand": operand, "category": category,
                    "offset": at,
                })
            slots.append({
                "index": index, "offset": offset, "template": payload[offset],
                "key_register_offset": key_register, "program_offset": program,
                "entries": entries,
            })
        screens.append({"ordinal": ordinal, "trailer_offset": trailer, "slots": slots})
    return screens


def row_index(y: int) -> int | None:
    row = min(range(len(DEVICE_ROW_CENTERS)), key=lambda item: abs(y - DEVICE_ROW_CENTERS[item]))
    return row if abs(y - DEVICE_ROW_CENTERS[row]) <= ROW_TOLERANCE else None


def device_menus(payload: bytes, ownership: dict | None = None) -> dict:
    """Own device-menu rows without requiring identical replica order or decoded text."""
    ownership = command_index.inspect(payload) if ownership is None else ownership
    objects = command_index.objects(payload)
    screens = screen_slots(payload)
    templates = touch_templates(payload)
    command_devices_by_screen: dict[int, set[int]] = defaultdict(set)
    for binding in key_index.inspect(payload, ownership)["bindings"]:
        command_devices_by_screen[binding["screen"]].add(binding["command_id"] >> 8)

    candidates = []
    rejected = Counter()
    for screen in screens:
        rows = []
        valid = True
        for slot in screen["slots"]:
            program = drawing_program(payload, slot["program_offset"])
            if (not program["instructions"]
                    or program["instructions"][0]["opcode"] != "call"):
                valid = False
                break
            lines: dict[int, list[dict]] = defaultdict(list)
            for instruction in program["instructions"]:
                if instruction["opcode"] not in ("text", "inline_text"):
                    continue
                if instruction["x"] != DEVICE_LABEL_X:
                    continue
                row = row_index(instruction["y"])
                if row is not None:
                    lines[row].append({
                        "y": instruction["y"], "glyphs": instruction["glyphs"],
                        "target": instruction.get("target"),
                    })
            if not lines:
                valid = False
                break
            zones = templates.get(slot["template"])
            if zones is None:
                rejected["missing_touch_template"] += 1
                valid = False
                break
            ordered_codes = [
                zone["key_code"] for zone in sorted(
                    (zone for zone in zones if zone["tag"] not in SIDE_STRIP_TAGS),
                    key=lambda zone: (-zone["y"], zone["x"]),
                )
            ]
            entries = {entry["key_code"]: entry for entry in slot["entries"]}
            navigations = []
            for code in ordered_codes:
                entry = entries.get(code)
                if entry is None or entry["category"] != 0x7F:
                    continue
                atoms = objects[entry["operand"]]["atoms"] if (
                    0 <= entry["operand"] < len(objects)) else ()
                if any(opcode == 0x1F and operand >> 8 == 0xFF
                       for operand, opcode in atoms):
                    valid = False
                    break
                targets = key_index.object_targets(objects, entry["operand"])
                pages = sorted({value for value, opcode in (targets or ()) if opcode == 0x7E})
                if len(pages) == 1:
                    navigations.append((code, entry["operand"], pages[0]))
            if not valid:
                break
            if len(navigations) < len(lines):
                rejected["text_rows_without_navigation"] += len(lines) - len(navigations)
                valid = False
                break
            for row, (code, object_index, target_screen) in zip(sorted(lines), navigations):
                rows.append({
                    "slot": slot["index"], "row": row, "key_code": code,
                    "object_index": object_index, "target_screen": target_screen,
                    "device_indices": sorted(command_devices_by_screen[target_screen]),
                    "lines": sorted(lines[row], key=lambda item: item["y"]),
                })
        if valid and rows:
            candidates.append({"screen": screen["ordinal"], "rows": rows})

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for candidate in candidates:
        identity = tuple(sorted(
            (tuple(line["glyphs"] for line in row["lines"]), row["target_screen"],
             tuple(row["device_indices"]))
            for row in candidate["rows"]
        ))
        groups[identity].append(candidate)
    replicas = max(groups.values(), key=len) if groups else []
    if groups and len(groups) > 1:
        rejected["non_replica_menu_candidates"] += sum(
            len(items) for items in groups.values() if items is not replicas)

    owned_by_device: dict[int, list[dict]] = defaultdict(list)
    native_only = []
    for menu in replicas:
        for row in menu["rows"]:
            if len(row["device_indices"]) == 1:
                owned_by_device[row["device_indices"][0]].append({
                    "menu_screen": menu["screen"], **row,
                })
            elif not row["device_indices"]:
                native_only.append({"menu_screen": menu["screen"], **row})
            else:
                rejected["row_reaches_multiple_devices"] += 1

    devices = []
    declared = len(ownership["devices"])
    for device_index in range(declared):
        occurrences = owned_by_device.get(device_index, [])
        labels = {
            tuple(line["glyphs"] for line in row["lines"])
            for row in occurrences
        }
        screens_for_device = {row["target_screen"] for row in occurrences}
        if len(labels) > 1:
            rejected["device_label_disagreement"] += 1
        if len(screens_for_device) > 1:
            rejected["device_screen_disagreement"] += 1
        devices.append({
            "device_index": device_index,
            "glyph_lines": list(next(iter(labels))) if len(labels) == 1 else [],
            "target_screen": next(iter(screens_for_device)) if len(screens_for_device) == 1 else None,
            "occurrences": len(occurrences),
        })
    return {
        "counts": {
            "candidate_menus": len(candidates), "replica_menus": len(replicas),
            "replica_rows": sum(len(menu["rows"]) for menu in replicas),
            "owned_devices": sum(bool(device["occurrences"]) for device in devices),
            "native_only_rows": len(native_only),
        },
        "rejected": dict(rejected),
        "menus": replicas,
        "devices": devices,
        "native_only_rows": native_only,
    }


def inspect(payload: bytes, ownership: dict | None = None) -> dict:
    """Return the owned UI inventory currently needed by portable import."""
    try:
        menus = device_menus(payload, ownership)
    except ValueError as error:
        # Outer GSPM validation deliberately does not claim that every inner section is
        # understood. Keep a malformed or as-yet-different UI grammar visible without
        # discarding the commands and waveforms that were independently owned.
        menus = {
            "counts": {
                "candidate_menus": 0, "replica_menus": 0, "replica_rows": 0,
                "owned_devices": 0, "native_only_rows": 0,
            },
            "rejected": {"invalid_ui_structure": 1},
            "error": str(error),
            "menus": [], "devices": [], "native_only_rows": [],
        }
    try:
        fonts = font_inventory(payload)
    except ValueError as error:
        fonts = {
            "counts": {
                "fonts": 0, "declared_glyph_slots": 0, "present_glyphs": 0,
                "decoded_glyphs": 0, "distinct_shapes": 0,
                "shapes_with_multiple_codes": 0,
            },
            "rejected": {"invalid_font_structure": 1}, "error": str(error), "fonts": [],
        }
    try:
        drawing = drawing_inventory(payload)
    except ValueError as error:
        drawing = {
            "counts": {"blocks": 0, "instructions": 0, "text_uses": 0,
                       "bitmap_uses": 0, "referenced_bitmaps": 0, "decoded_bitmaps": 0},
            "instruction_counts": {}, "rejected": {"invalid_drawing_structure": 1},
            "error": str(error), "bitmaps": [],
        }
    try:
        buttons = button_inventory(payload)
    except ValueError as error:
        buttons = {"count": 0, "index_is_sequential": False,
                   "classification": {}, "rows": [], "error": str(error)}
    return {"device_menus": menus, "fonts": fonts, "drawing": drawing, "buttons": buttons}


# An activity row's object carries opcode 0x1f with 0xff in the operand's high byte and
# the activity ordinal in the low one. Device-menu rows are refused when they contain it,
# which is what keeps the two menus apart.
ACTIVITY_ACTION = 0x1F
ACTIVITY_MARK = 0xFF


def activity_rows(payload: bytes, ownership: dict | None = None) -> dict:
    """Own the Activities menu: which row band starts which activity, and its text.

    Rows are read the same way device-menu rows are - equally sized touch zones in
    reading order paired band for band with the labels drawn in those bands - because
    both menus draw the same row grid. What differs is the action: a row starts an
    activity rather than opening a screen.
    """
    objects = command_index.objects(payload)
    templates = touch_templates(payload)
    rows = []
    rejected = Counter()
    screens = set()
    for screen in screen_slots(payload):
        for slot in screen["slots"]:
            try:
                program = drawing_program(payload, slot["program_offset"])
            except ValueError:
                rejected["unreadable_program"] += 1
                continue
            lines: dict[int, list[dict]] = defaultdict(list)
            for instruction in program["instructions"]:
                if (instruction["opcode"] not in ("text", "inline_text")
                        or instruction["x"] != DEVICE_LABEL_X):
                    continue
                band = row_index(instruction["y"])
                if band is not None:
                    lines[band].append({
                        "y": instruction["y"], "glyphs": instruction["glyphs"]})
            if not lines:
                continue
            zones = templates.get(slot["template"])
            if zones is None:
                rejected["missing_touch_template"] += 1
                continue
            content = [zone for zone in zones if zone["tag"] not in SIDE_STRIP_TAGS]
            sizes = Counter((zone["width"], zone["height"]) for zone in content)
            if not sizes:
                continue
            size, repeats = sizes.most_common(1)[0]
            if repeats < 2:
                continue
            ordered = sorted(
                (zone for zone in content if (zone["width"], zone["height"]) == size),
                key=lambda zone: (-zone["y"], zone["x"]))
            entries = {entry["key_code"]: entry for entry in slot["entries"]}
            found = []
            for band in sorted(lines):
                if band >= len(ordered):
                    rejected["row_band_without_a_zone"] += 1
                    continue
                entry = entries.get(ordered[band]["key_code"])
                if entry is None or entry["category"] != 0x7F:
                    continue
                if not 0 <= entry["operand"] < len(objects):
                    rejected["invalid_object_index"] += 1
                    continue
                started = {
                    operand & 0xFF
                    for operand, opcode in objects[entry["operand"]]["atoms"]
                    if opcode == ACTIVITY_ACTION and operand >> 8 == ACTIVITY_MARK
                }
                if not started:
                    continue
                if len(started) > 1:
                    rejected["row_starts_several_activities"] += 1
                    continue
                found.append({
                    "screen": screen["ordinal"], "slot": slot["index"], "row": band,
                    "key_code": ordered[band]["key_code"],
                    "object_index": entry["operand"],
                    "activity": next(iter(started)),
                    "lines": sorted(lines[band], key=lambda item: item["y"]),
                })
            if found:
                screens.add(screen["ordinal"])
                rows.extend(found)
    by_activity = defaultdict(list)
    for row in rows:
        by_activity[row["activity"]].append(row)
    for activity, occurrences in by_activity.items():
        if len(occurrences) > 1:
            rejected["activity_on_several_rows"] += 1
    return {
        "counts": {
            "screens": len(screens), "rows": len(rows),
            "activities": len(by_activity),
        },
        "rejected": dict(rejected),
        "screens": sorted(screens),
        "rows": rows,
    }
