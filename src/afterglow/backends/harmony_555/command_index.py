"""Read Harmony One's authoritative device-to-command index.

Section 5 is the path the firmware uses to resolve the high and low bytes of a command
ID. It owns command records; byte-pattern scans do not. Section-11 command objects add
runtime device IDs, which are retained as evidence rather than mistaken for device names.

Format reference: docs/harmony_650_700/gspm.md, docs/harmony_one/README.md
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
    """Return command objects grouped by their command ID: ``{cmd 7D}{dev 7C}``, after any
    number of ``{object 7F}`` atoms - a 650 runs another object before every command."""
    found: dict[int, list[dict]] = defaultdict(list)
    for item in objects(payload):
        atoms = item["atoms"]
        if (len(atoms) < 2 or atoms[-2][1] != 0x7D or atoms[-1][1] != 0x7C
                or any(opcode != 0x7F for _operand, opcode in atoms[:-2])):
            continue
        atoms = atoms[-2:]
        found[atoms[0][0]].append({
            "object_index": item["index"],
            "object_offset": item["offset"],
            "device_id": atoms[1][0],
        })
    return dict(found)


class SilentCommand(ValueError):
    """A command whose press is silence: Logitech's stand-in for a device it does not
    reach by infrared - a Sony PS4's power off, on a 650 - which sends nothing."""


def _silent(payload: bytes, offset: int) -> bool:
    """Whether a waveform is spaces only, up to the zero word that ends it: a hold that
    sends nothing while the key is held."""
    cursor = offset
    for _ in range(MAX_WAVEFORM_WORDS):
        if cursor + 2 > len(payload):
            return False
        word = struct.unpack_from("<H", payload, cursor)[0]
        cursor += 2
        if not word:
            return cursor - 2 > offset
        if word & 0x8000:
            return False
    return False


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
        if not word and len(words) >= 2 and words[-2] & 0x8000 \
                and not words[-1] & 0x8000 and (words[-1] & 0x7FFF) < 200:
            # the other ending, on a Dutch 650's long amplifier code: the last mark, a
            # space of a microsecond, then a zero word - the space is the frame's last,
            # and nothing closes it
            words.append(0)
            break
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
            and not words[-2] & 0x8000 and ((words[-1] & 0x7FFF) < 200 or not words[-1])):
        raise ValueError(f"waveform at {offset:#x} has no native terminator")

    body = words[:-1]
    entry_us = 0
    # A press leads with the silence before its first frame. A 5xx hold may lead with
    # silence too: the gap before each repeat, which the remote plays as written - an
    # XMP-style set-top box's on two Logitech-built 555s (docs/harmony_5xx/ahcm.md,
    # "Infrared").
    while body and not body[0] & 0x8000:
        entry_us += body.pop(0) & 0x7FFF
    if not body:
        raise ValueError(f"waveform at {offset:#x} has no mark")

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
    # It may begin with silence on a 5xx, the gap before the release frame, and may end
    # in a space, the gap after its last frame
    entry_us = 0
    body = list(words)
    while body and not body[0] & 0x8000:
        entry_us += body.pop(0) & 0x7FFF
    if not body:
        raise ValueError(f"release waveform at {offset:#x} has no mark")

    pulses: list[int] = []
    for word in body:
        duration = word & 0x7FFF
        pulse = duration if word & 0x8000 else -duration
        if pulses and (pulses[-1] > 0) == (pulse > 0):
            pulses[-1] += pulse
        else:
            pulses.append(pulse)
    return {
        "offset": offset,
        "entry_us": entry_us,
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


# Every 5xx command record is class 5: its press, hold and release pointers name a body
# that spells the code from a dictionary of pulse blocks, where the 650's class 1 names
# the words themselves (docs/harmony_5xx/ahcm.md, "Infrared").
CLASS_5 = 5
MAX_SYMBOLS = 255


def _expand(payload: bytes, body: int) -> bytes:
    """A class-5 body spelled out: its symbols' pulse words in index order and the zero
    word that ends a class-1 waveform, so the class-1 decoders read it unchanged."""
    if not 0 <= body or body + 5 > len(payload):
        raise ValueError(f"class-5 body {body:#x} falls outside the image")
    table = _u24(payload, body) - gspm.BASE
    size = struct.unpack_from("<H", payload, body + 3)[0]
    if not 0 <= table < len(payload) or body + 5 + size > len(payload):
        raise ValueError(f"class-5 body {body:#x} is truncated")
    indexes = payload[body + 5:body + 5 + size]
    # The count is the table's size modulo 256: Logitech's compiler wrote an Xbox 360's
    # factory demo table of 287 symbols with the count 31. An index is one byte, so it
    # names one of the first 256 whatever the count says; one past the count is read
    # from a table that wrapped, its symbol checked like any other.
    count = payload[table]
    if indexes and max(indexes) >= count:
        count += 256
    if not count or table + 1 + 3 * min(count, MAX_SYMBOLS + 1) > len(payload):
        raise ValueError(f"class-5 symbol table {table:#x} is truncated")
    words = bytearray()
    for index in indexes:
        if index >= count:
            raise ValueError(f"class-5 body {body:#x} names symbol {index} of {count}")
        symbol = _u24(payload, table + 1 + 3 * index) - gspm.BASE
        if not 0 <= symbol or symbol + 2 > len(payload):
            raise ValueError(f"class-5 symbol {index} falls outside the image")
        length = struct.unpack_from("<H", payload, symbol)[0]
        end = symbol + 2 + 2 * length
        if not length or end + 2 > len(payload) or payload[end:end + 2] != b"\x00\x00":
            raise ValueError(f"class-5 symbol {index} at {symbol:#x} is malformed")
        words += payload[symbol + 2:end]
        if len(words) // 2 > MAX_WAVEFORM_WORDS:
            raise ValueError(f"class-5 body {body:#x} exceeds the bounded word count")
    return bytes(words) + b"\x00\x00"


def _spelled(payload: bytes, absolute: int, decode, **options) -> dict:
    """Decode the class-5 body at ``absolute`` with a class-1 waveform decoder, keeping
    the body's own offset as the evidence."""
    body = absolute - gspm.BASE
    out = decode(_expand(payload, body), 0, **options)
    out["offset"] = body
    return out


def _record(payload: bytes, offset: int) -> dict:
    if not (0 <= offset and offset + 25 <= len(payload)):
        raise ValueError(f"command record {offset:#x} falls outside the AHCM image")
    period = _u24(payload, offset + 5)
    half = _u24(payload, offset + 8)
    if not period or half != period // 2:
        raise ValueError(f"command record {offset:#x} has inconsistent carrier fields")
    if payload[offset + 11] != CLASS_5:
        raise ValueError(f"command record {offset:#x} is class {payload[offset + 11]}, not 5")
    if _u24(payload, offset + 12) != gspm.BASE + offset + 4:
        raise ValueError(f"command record {offset:#x} has an invalid self-pointer")
    waveform_mode = payload[offset + 15]
    if waveform_mode not in (1, 2):
        raise ValueError(
            f"command record {offset:#x} has unsupported waveform mode {waveform_mode}")
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
        if name == "press" and _silent(_expand(payload, target), 0):
            raise SilentCommand(f"command record {offset:#x} sends silence")
        if name == "hold" and _silent(_expand(payload, target), 0):
            # a hold of nothing but silence repeats nothing
            continue
        waveforms[name] = _spelled(payload, absolute, _decode_waveform, press=index == 0)
    if pointers[2]:
        release_offset = pointers[2] - gspm.BASE
        if not 0 <= release_offset < len(payload):
            raise ValueError(
                f"command record {offset:#x} release pointer falls outside the image")
        waveforms["release"] = _spelled(payload, pointers[2], _decode_release_waveform)
    # Mode 2 is a toggling (RC5/RC6) command: a second set of three pointers follows,
    # which the remote sends on every other press, as on the 650 and the One.
    alternate = {}
    second = ([_u24(payload, offset + field) for field in (25, 28, 31)]
              if waveform_mode == 2 and offset + 34 <= len(payload) else [0, 0, 0])
    if second[0] and 0 <= second[0] - gspm.BASE < len(payload):
        try:
            for index, (name, absolute) in enumerate(zip(names, second[:2])):
                if not absolute or (name == "hold" and _silent(
                        _expand(payload, absolute - gspm.BASE), 0)):
                    continue
                alternate[name] = _spelled(payload, absolute, _decode_waveform,
                                           press=index == 0)
            if second[2]:
                alternate["release"] = _spelled(payload, second[2],
                                                _decode_release_waveform)
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
    silent = 0
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
            except SilentCommand:
                # sends nothing, so it is no signal: counted, not rejected
                silent += 1
                continue
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
            "silent_commands": silent,
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


def _recording(waves: dict) -> tuple[list[int], dict | None]:
    """A record's (press, hold, release) waveforms as one recording and its sections."""
    pulses = list(waves["press"]["pulses_us"])
    if "hold" not in waves and "release" not in waves:
        return pulses, None
    hold_pulses = list(waves.get("hold", {}).get("pulses_us", []))
    release_pulses = list(waves.get("release", {}).get("pulses_us", []))
    # A hold or release that leads with silence: the silence goes after what precedes
    # it - the press, and each repeat - as a recording's sections carry gaps at their end.
    # Press to first repeat and repeat to repeat stay exact; the release then follows a
    # repeat's gap before its own.
    hold_gap = waves.get("hold", {}).get("entry_us", 0)
    if hold_gap:
        pulses[-1] -= hold_gap
        hold_pulses[-1] -= hold_gap
    release_gap = waves.get("release", {}).get("entry_us", 0)
    if release_gap:
        (hold_pulses or pulses)[-1] -= release_gap
    sections = {"intro_pulses": len(pulses), "repeat_pulses": len(hold_pulses)}
    if release_pulses:
        sections["release_pulses"] = len(release_pulses)
    return pulses + hold_pulses + release_pulses, sections


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
            pulses, sections = _recording(waves)
            # A toggling command's other state, sent on every other press.
            others = native.get("alternate_waveforms")
            alternate = None
            if others and "press" in others:
                other_pulses, other_sections = _recording(others)
                alternate = {"pulses_us": other_pulses, "sections": other_sections}
                evidence["alternate_waveform_offsets"] = {
                    phase: waveform["offset"] for phase, waveform in others.items()}
            signals[name] = ir_signal.waveform(
                pulses,
                name=name,
                carrier_hz=native["carrier_hz"],
                sections=sections,
                alternate=alternate,
                provenance={"kind": "structural-native-import", "backend": "harmony-555"},
                native={"harmony-555": evidence},
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
            f"Device {index + 1}"
        )
        devices.append({
            "schema": "afterglow-project-device/1",
            "id": f"harmony-555-{index}",
            "label": label,
            "manufacturer": "",
            "model": "",
            "type": "Unknown",
            "commands": commands,
            "signals": signals,
            "native": {"harmony-555": native_evidence},
        })
    return devices
