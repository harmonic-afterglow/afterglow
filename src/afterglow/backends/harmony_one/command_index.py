"""Read Harmony One's authoritative device-to-command index.

Section 5 is the path the firmware uses to resolve the high and low bytes of a command
ID. It owns command records; byte-pattern scans do not. Section-11 command objects add
runtime device IDs, which are retained as evidence rather than mistaken for device names.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from collections import Counter, defaultdict
import struct

from ... import ir_signal
from . import gspm


MAX_WAVEFORM_WORDS = 4096


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


def objects(payload: bytes) -> list[dict]:
    """Return the bounded section-11 objects in authoritative table order."""
    start, end = gspm.section_ranges(payload)[11]
    count = struct.unpack_from("<H", payload, start)[0]
    table_end = start + 2 + 3 * count
    if not count or table_end > end:
        raise ValueError(f"GSPM object table declares {count} entries outside section 11")
    pointers = tuple(
        _relative(payload, start + 2 + 3 * index, f"object {index}")
        for index in range(count)
    )
    if len(pointers) != len(set(pointers)):
        raise ValueError("GSPM object pointers are not unique")
    checksum_offset = struct.unpack_from("<I", payload, 4)[0] - gspm.BASE - 2
    out = []
    for index, offset in enumerate(pointers):
        atom_count = payload[offset]
        object_end = offset + 1 + 3 * atom_count
        if object_end > checksum_offset:
            raise ValueError(f"GSPM object {index} exceeds the native object region")
        atoms = tuple(
            struct.unpack_from("<HB", payload, offset + 1 + 3 * atom)
            for atom in range(atom_count)
        )
        out.append({"index": index, "offset": offset, "atoms": atoms})
    occupied = sorted(
        (item["offset"], item["offset"] + 1 + 3 * len(item["atoms"]), item["index"])
        for item in out
    )
    for previous, current in zip(occupied, occupied[1:]):
        if current[0] < previous[1]:
            raise ValueError(
                f"GSPM objects {previous[2]} and {current[2]} overlap")
    return out


def command_objects(payload: bytes) -> dict[int, list[dict]]:
    """Return exact two-atom command objects grouped by their command ID."""
    found: dict[int, list[dict]] = defaultdict(list)
    for item in objects(payload):
        atoms = item["atoms"]
        if len(atoms) != 2 or atoms[0][1] != 0x7D or atoms[1][1] != 0x7C:
            continue
        found[atoms[0][0]].append({
            "object_index": item["index"],
            "object_offset": item["offset"],
            "device_id": atoms[1][0],
        })
    return dict(found)


def _decode_waveform(payload: bytes, offset: int, *, press: bool) -> dict:
    """Decode a bounded native waveform into signed portable durations."""
    words = []
    seen_mark = False
    cursor = offset
    for _ in range(MAX_WAVEFORM_WORDS):
        if cursor + 2 > len(payload):
            break
        word = struct.unpack_from("<H", payload, cursor)[0]
        cursor += 2
        duration = word & 0x7FFF
        if not duration:
            raise ValueError(f"waveform at {offset:#x} contains a zero-duration word")
        words.append(word)
        seen_mark |= bool(word & 0x8000)
        if (seen_mark and len(words) >= 2 and not word & 0x8000
                and not words[-2] & 0x8000 and duration < 200):
            break
    else:
        raise ValueError(f"waveform at {offset:#x} exceeds the bounded native word count")
    if not words or not seen_mark or not (
            len(words) >= 2 and not words[-1] & 0x8000
            and not words[-2] & 0x8000 and (words[-1] & 0x7FFF) < 200):
        raise ValueError(f"waveform at {offset:#x} has no native terminator")

    body = words[:-1]
    entry_us = 0
    if press:
        while body and not body[0] & 0x8000:
            entry_us += body.pop(0) & 0x7FFF
        if not entry_us:
            raise ValueError(f"press waveform at {offset:#x} has no lead-in")
    elif not body or not body[0] & 0x8000:
        raise ValueError(f"hold waveform at {offset:#x} does not begin with a mark")

    pulses: list[int] = []
    for word in body:
        duration = word & 0x7FFF
        pulse = duration if word & 0x8000 else -duration
        if pulses and (pulses[-1] > 0) == (pulse > 0):
            pulses[-1] += pulse
        else:
            pulses.append(pulse)
    if not pulses or pulses[0] < 0 or pulses[-1] > 0:
        raise ValueError(f"waveform at {offset:#x} does not contain mark/space pairs")
    return {
        "offset": offset,
        "entry_us": entry_us,
        "close_us": words[-1] & 0x7FFF,
        "word_count": len(words),
        "pulses_us": pulses,
    }


def _decode_release_waveform(payload: bytes, offset: int) -> dict:
    """Decode the zero-terminated waveform stored in the release slot."""
    words = []
    cursor = offset
    for _ in range(MAX_WAVEFORM_WORDS):
        if cursor + 2 > len(payload):
            break
        word = struct.unpack_from("<H", payload, cursor)[0]
        cursor += 2
        if word == 0:
            break
        if not word & 0x7FFF:
            raise ValueError(
                f"release waveform at {offset:#x} contains a zero-duration word")
        words.append(word)
    else:
        raise ValueError(
            f"release waveform at {offset:#x} exceeds the bounded native word count")
    if cursor > len(payload) or not words or payload[cursor - 2:cursor] != b"\x00\x00":
        raise ValueError(f"release waveform at {offset:#x} has no zero terminator")
    if not words[0] & 0x8000 or not words[-1] & 0x8000:
        raise ValueError(
            f"release waveform at {offset:#x} must begin and end with a mark")

    pulses: list[int] = []
    for word in words:
        duration = word & 0x7FFF
        pulse = duration if word & 0x8000 else -duration
        if pulses and (pulses[-1] > 0) == (pulse > 0):
            pulses[-1] += pulse
        else:
            pulses.append(pulse)
    return {
        "offset": offset,
        "entry_us": 0,
        "word_count": len(words) + 1,
        "pulses_us": pulses,
    }


def _carrier_hz(period_ns: int) -> int:
    candidate = round(1_000_000_000 / period_ns)
    if 1_000_000_000 // candidate == period_ns:
        return candidate
    lowest = 1_000_000_000 // (period_ns + 1) + 1
    if lowest > 0 and 1_000_000_000 // lowest == period_ns:
        return lowest
    raise ValueError(f"carrier period {period_ns} ns has no exact integer-Hz representation")


def _record(payload: bytes, offset: int) -> dict:
    if not (0 <= offset and offset + 25 <= len(payload)):
        raise ValueError(f"command record {offset:#x} falls outside the GSPM image")
    period = _u24(payload, offset + 5)
    half = _u24(payload, offset + 8)
    if not period or half != period // 2:
        raise ValueError(f"command record {offset:#x} has inconsistent carrier fields")
    if payload[offset + 11] != 1:
        raise ValueError(f"command record {offset:#x} has no type-1 self reference")
    if _u24(payload, offset + 12) != gspm.BASE + offset + 4:
        raise ValueError(f"command record {offset:#x} has an invalid self-pointer")
    waveform_mode = payload[offset + 15]
    if waveform_mode not in (1, 2):
        raise ValueError(
            f"command record {offset:#x} has unsupported waveform mode {waveform_mode}")
    # Mode 2 is a toggling (RC5/RC6) command: a second set of three pointers follows,
    # which the remote sends on every other press (records.command_record). Every one in
    # Logitech's images has it; one without is read as the single set it is.
    pointers = [_u24(payload, offset + field) for field in (16, 19, 22)]
    if not pointers[0]:
        raise ValueError(f"command record {offset:#x} has no press waveform")
    names = ("press", "hold")
    waveforms = {}
    for index, (name, absolute) in enumerate(zip(names, pointers[:2])):
        if not absolute:
            continue
        target = absolute - gspm.BASE
        if not 0 <= target < len(payload):
            raise ValueError(
                f"command record {offset:#x} {name} waveform points outside the image")
        waveforms[name] = _decode_waveform(payload, target, press=index == 0)
    if pointers[2]:
        release_offset = pointers[2] - gspm.BASE
        if not 0 <= release_offset < len(payload):
            raise ValueError(
                f"command record {offset:#x} release pointer falls outside the image")
        waveforms["release"] = _decode_release_waveform(payload, release_offset)
    alternate = {}
    second = ([_u24(payload, offset + field) for field in (25, 28, 31)]
              if waveform_mode == 2 and offset + 34 <= len(payload) else [0, 0, 0])
    if second[0] and 0 <= second[0] - gspm.BASE < len(payload):
        try:
            for index, (name, absolute) in enumerate(zip(names, second[:2])):
                if absolute:
                    alternate[name] = _decode_waveform(
                        payload, absolute - gspm.BASE, press=index == 0)
            if second[2]:
                alternate["release"] = _decode_release_waveform(
                    payload, second[2] - gspm.BASE)
        except ValueError:
            alternate = {}          # not a second set after all; the first still stands
    return {
        "record_offset": offset,
        "record_prefix": payload[offset:offset + 5].hex(),
        "carrier_period_ns": period,
        "carrier_half_period_ns": half,
        "carrier_hz": _carrier_hz(period),
        "waveform_mode": waveform_mode,
        "waveforms": waveforms,
        **({"alternate_waveforms": alternate} if alternate else {}),
    }


def inspect(payload: bytes) -> dict:
    """Resolve indexed commands, retaining every mismatch as an explicit count."""
    gspm.validate(payload)
    ranges = gspm.section_ranges(payload)
    start, end = ranges[5]
    device_count = payload[start]
    if start + 1 + 3 * device_count > end:
        raise ValueError("GSPM section 5 device index exceeds its section")

    objects = command_objects(payload)
    used_object_ids = set()
    rejected = Counter()
    devices = []
    seen_records = set()
    for device_index in range(device_count):
        subtable = _relative(
            payload, start + 1 + 3 * device_index,
            f"section 5 device {device_index} sub-table")
        if subtable + 3 > len(payload) or payload[subtable] != 0:
            raise ValueError(f"section 5 device {device_index} has an invalid sub-table")
        command_count = struct.unpack_from("<H", payload, subtable + 1)[0]
        if command_count > 0x100:
            raise ValueError(
                f"section 5 device {device_index} exceeds the one-byte command ordinal")
        if subtable + 3 + 3 * command_count > len(payload):
            raise ValueError(f"section 5 device {device_index} sub-table is truncated")

        commands = []
        for ordinal in range(command_count):
            command_id = (device_index << 8) | ordinal
            target = _relative(
                payload, subtable + 3 + 3 * ordinal,
                f"section 5 command {command_id:#06x}")
            record_offset = target - 11
            if record_offset in seen_records:
                rejected["duplicate_record_pointer"] += 1
                continue
            seen_records.add(record_offset)
            refs = objects.get(command_id, [])
            if not refs:
                rejected["command_without_object"] += 1
                continue
            used_object_ids.add(command_id)
            mismatched = [ref for ref in refs if ref["device_id"] >> 8 != device_index]
            if mismatched:
                rejected["object_device_mismatch"] += len(mismatched)
            try:
                record = _record(payload, record_offset)
            except ValueError:
                rejected["invalid_command_record"] += 1
                continue
            record.update({
                "command_id": command_id,
                "device_index": device_index,
                "ordinal": ordinal,
                "object_indexes": [ref["object_index"] for ref in refs],
                "device_ids": sorted({ref["device_id"] for ref in refs}),
            })
            commands.append(record)
        devices.append({
            "device_index": device_index,
            "declared_commands": command_count,
            "commands": commands,
        })

    unindexed = len(set(objects) - used_object_ids)
    if unindexed:
        rejected["unindexed_command_object"] += unindexed
    return {
        "devices": devices,
        "counts": {
            "devices": device_count,
            "declared_commands": sum(item["declared_commands"] for item in devices),
            "decoded_commands": sum(len(item["commands"]) for item in devices),
            "portable_waveform_commands": sum(
                1 for item in devices for command in item["commands"]),
            "release_commands": sum(
                "release" in command["waveforms"]
                for item in devices for command in item["commands"]),
            "command_objects": sum(len(items) for items in objects.values()),
            "duplicate_command_objects": sum(max(0, len(items) - 1)
                                             for items in objects.values()),
        },
        "rejected": dict(rejected),
    }


def portable_devices(
        report: dict, key_report: dict | None = None, menu_report: dict | None = None,
) -> list[dict]:
    """Convert resolved native devices to honest, unnamed portable waveform devices."""
    bindings_by_command: dict[int, list[dict]] = defaultdict(list)
    for binding in (key_report or {}).get("bindings", []):
        bindings_by_command[binding["command_id"]].append(dict(binding))
    menus_by_device = {
        item["device_index"]: item for item in (menu_report or {}).get("devices", [])
    }
    devices = []
    for native_device in report["devices"]:
        commands = []
        signals = {}
        for native in native_device["commands"]:
            name = f"Command {native['ordinal']:02X}"
            waves = native["waveforms"]
            evidence = {
                "command_id": native["command_id"],
                "record_offset": native["record_offset"],
                "record_prefix": native["record_prefix"],
                "carrier_period_ns": native["carrier_period_ns"],
                "waveform_mode": native["waveform_mode"],
                "waveform_offsets": {
                    phase: waveform["offset"] for phase, waveform in waves.items()
                },
                "entry_us": waves["press"]["entry_us"],
                "device_ids": native["device_ids"],
                "object_indexes": native["object_indexes"],
            }
            key_bindings = bindings_by_command.get(native["command_id"])
            if key_bindings:
                evidence["key_bindings"] = key_bindings
            pulses = list(waves["press"]["pulses_us"])
            sections = None
            if "hold" in waves or "release" in waves:
                hold_pulses = waves.get("hold", {}).get("pulses_us", [])
                release_pulses = waves.get("release", {}).get("pulses_us", [])
                pulses += hold_pulses
                pulses += release_pulses
                sections = {
                    "intro_pulses": len(waves["press"]["pulses_us"]),
                    "repeat_pulses": len(hold_pulses),
                }
                if release_pulses:
                    sections["release_pulses"] = len(release_pulses)
            signals[name] = ir_signal.waveform(
                pulses,
                name=name,
                carrier_hz=native["carrier_hz"],
                sections=sections,
                provenance={"kind": "structural-native-import", "backend": "harmony-one"},
                native={"harmony-one": evidence},
            )
            commands.append([name, name, "00", "00", None])
        index = native_device["device_index"]
        native_evidence = {
            "device_index": index,
            "declared_commands": native_device["declared_commands"],
        }
        menu = menus_by_device.get(index)
        if menu and menu["occurrences"]:
            native_evidence["menu"] = {
                "glyph_lines": menu["glyph_lines"],
                "target_screen": menu["target_screen"],
                "occurrences": menu["occurrences"],
            }
            if menu.get("label_lines"):
                native_evidence["menu"]["label_lines"] = menu["label_lines"]
        label = (
            menu.get("label") if menu and menu.get("label") else
            f"Harmony One device {index}"
        )
        devices.append({
            "schema": "afterglow-project-device/1",
            "id": f"harmony-one-{index}",
            "label": label,
            "manufacturer": "",
            "model": "",
            "type": "Unknown",
            "commands": commands,
            "signals": signals,
            "native": {"harmony-one": native_evidence},
        })
    return devices


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
