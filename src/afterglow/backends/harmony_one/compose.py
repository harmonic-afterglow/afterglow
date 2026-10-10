"""Lay out the household-owned half of a Harmony One image from a model.

Every operation before this one edited an image in place: relocate a section, append a
record, repoint a pointer. That works, but it cannot delete, cannot compact, and grows
the file on every change, because nothing is ever laid out afresh - only added to.

This module does what the producer of these images did instead. It reads the structures
this backend owns into a model with no addresses in it, then emits them all together at
chosen addresses and fixes every reference in one pass. What it does not model - command
records and their waveforms, fonts, bitmaps, glyph strings, touch templates, and the
sections with no model at all - stays exactly where it is and is referenced from the new
layout, so an image is still the user's own image rather than an invention.

The gate is that a no-change re-emission reads back as the same model. Addresses move;
nothing else may.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import (
    activity_index,
    authoring,
    bitmap,
    command_index,
    drawing,
    font_index,
    gspm,
    records,
    relocation,
    ui_index,
)


# The master-index slots this module lays out. Everything else keeps its own pointer.
# They are emitted last and in this order, so each one's computed range - which runs to
# whichever section starts next - covers its own table and nothing else.
COMPOSED_SECTIONS = (4, 5, 6, 7, 9, 10, 11, 12, 14)


def _read_fonts(payload: bytes) -> list[dict]:
    """Every font as its height and its glyphs' own bytes, addresses left behind."""
    out = []
    for font in font_index.fonts(payload):
        glyphs = {}
        for code, glyph in font["glyphs"].items():
            at = glyph["pointer"] - gspm.BASE
            glyphs[code] = bytes(payload[at:at + glyph["encoded_size"]])
        out.append({
            "height": font["height"], "slots": font["slots"],
            "layout": font["layout"], "glyphs": glyphs,
        })
    return out


def _overlay_roots(payload: bytes) -> list[int]:
    """Return the drawing programs section 12 indexes, in table order."""
    start, end = gspm.section_ranges(payload)[12]
    count = struct.unpack_from("<H", payload, start)[0]
    if start + 2 + 3 * count > end:
        raise ValueError("section 12 overlay index exceeds its section")
    out = []
    for index in range(count):
        at = start + 2 + 3 * index
        offset = int.from_bytes(payload[at:at + 3], "little") - gspm.BASE
        if not 0 <= offset < len(payload):
            raise ValueError(f"section 12 entry {index} falls outside the image")
        out.append(offset)
    return out


def read(payload: bytes) -> dict:
    """Read the composable structures into a model that holds no addresses of its own."""
    gspm.validate(payload)
    screens = []
    roots = []
    for screen in ui_index.screen_slots(payload):
        trailer = screen["trailer_offset"]
        slots = []
        for slot in screen["slots"]:
            roots.append(slot["program_offset"])
            slots.append({
                "template": slot["template"],
                "entries": [
                    (entry["key_code"], entry["operand"], entry["category"])
                    for entry in slot["entries"]
                ],
                "program": slot["program_offset"],
            })
        # A trailer's header is another key register - a count and `{key, u16, class}`
        # rows - holding the physical buttons that screen answers. Most carry four to
        # six; a few carry the whole 55-button vocabulary the LWJL marker counts.
        header = int.from_bytes(payload[trailer + 1:trailer + 4], "little") - gspm.BASE
        rows = payload[header]
        screens.append({
            "flag": payload[trailer],
            "header": [
                (payload[header + 1 + 4 * index],
                 int.from_bytes(payload[header + 2 + 4 * index:header + 4 + 4 * index],
                                "little"),
                 payload[header + 4 + 4 * index])
                for index in range(rows)
            ],
            "slots": slots,
        })
    overlays = _overlay_roots(payload)
    # Section 12 is a drawing root set of its own: no screen calls it, and its status-bar
    # and battery programs are the only thing that reaches 14 to 18 pictures per image.
    programs = drawing.program_blocks(payload, roots + overlays)
    pictures, strings = {}, {}
    for item in (i for block in programs.values() for i in block):
        if item["opcode"] == "bitmap":
            pictures.setdefault(item["target"], bitmap.decode(payload, item["target"]))
        elif item["opcode"] == "text":
            strings.setdefault(
                item["target"], ui_index._terminated_glyphs(payload, item["target"]))
    ownership = command_index.inspect(payload)
    devices = []
    for device in ownership["devices"]:
        commands = []
        for command in device["commands"]:
            waves = command["waveforms"]
            commands.append({
                "prefix": bytes.fromhex(command["record_prefix"]),
                "carrier_period_ns": command["carrier_period_ns"],
                "carrier_half_period_ns": command["carrier_half_period_ns"],
                "phases": {
                    phase: bytes(payload[wave["offset"]:
                                         wave["offset"] + 2 * wave["word_count"]])
                    for phase, wave in waves.items()
                },
            })
        devices.append(commands)
    return {
        "devices": devices,
        "fonts": _read_fonts(payload),
        "objects": [item["atoms"] for item in command_index.objects(payload)],
        "contexts": [
            {"form": item["form"],
             "rows": [
                 {"flags": row["flags"], "key_code": row["key_code"],
                  "operand": row["operand"], "category": row["category"]}
                 for row in item["rows"]]}
            for item in activity_index.contexts(payload)
        ],
        "screens": screens,
        # Section 14's records hold no addresses at all: every field is a state number,
        # an object index or a byte, so they move without anything being repaired. What
        # they mean is still unestablished; that they are portable is measured.
        "engine": [
            {"initial": item["initial"], "limit": item["limit"],
             "padding": item["padding"],
             "transitions": [
                 {"flags": row["flags"], "from": row["from"], "to": row["to"],
                  "operand": row["operand"], "category": row["category"]}
                 for row in item["transitions"]]}
            for item in activity_index.engine_records(payload)
        ],
        "overlays": overlays,
        "programs": programs,
        # The pictures and glyph strings the programs draw. Holding them here is what
        # lets an image be laid out somewhere else entirely rather than kept in place.
        "pictures": pictures,
        "strings": strings,
    }


def canonical(payload: bytes) -> dict:
    """Return a reading with every address this module assigns replaced by an index.

    Two images that differ only in where the composed structures were put produce the
    same canonical reading, which is what makes a re-emission checkable.
    """
    model = read(payload)
    order = {}
    stack = [slot["program"] for screen in model["screens"] for slot in screen["slots"]]
    stack += list(model["overlays"])
    while stack:
        block = stack.pop(0)
        if block in order:
            continue
        order[block] = len(order)
        for item in model["programs"][block]:
            if item["opcode"] in ("call", "jump"):
                stack.append(item["target"])
            elif item["opcode"] == "switch":
                stack.extend(target for _value, target in item["cases"])
                stack.extend(target for _low, _high, target in item["ranges"])

    def _instruction(item: dict) -> tuple:
        fields = []
        for key in sorted(item):
            if key == "offset":
                continue
            value = item[key]
            if key == "target" and item["opcode"] in ("call", "jump"):
                value = order.get(value, value)
            elif key == "target" and item["opcode"] == "bitmap":
                # A picture is what it draws, not where it is kept.
                drawn = model["pictures"][value]
                value = ("picture", drawn["width"], drawn["height"],
                         tuple(tuple(row) for row in drawn["rows"]))
            elif key == "target" and item["opcode"] == "text":
                value = ("string", bytes(model["strings"][value]))
            elif key == "cases":
                value = tuple((code, order.get(t, t)) for code, t in value)
            elif key == "ranges":
                value = tuple((low, high, order.get(t, t)) for low, high, t in value)
            fields.append((key, value))
        return tuple(fields)

    return {
        "devices": model["devices"],
        "fonts": model["fonts"],
        "objects": model["objects"],
        "contexts": model["contexts"],
        "engine": model["engine"],
        "screens": [
            {"flag": screen["flag"], "header": screen["header"],
             "slots": [
                 {"template": slot["template"], "entries": slot["entries"],
                  "program": order[slot["program"]]}
                 for slot in screen["slots"]]}
            for screen in model["screens"]
        ],
        "overlays": [order[block] for block in model["overlays"]],
        "programs": [
            tuple(_instruction(item) for item in model["programs"][block])
            for block, _index in sorted(order.items(), key=lambda pair: pair[1])
        ],
    }


def _place(out: bytearray, body: bytes) -> int:
    """Put a structure where a sequential native read stays inside one 64 KiB window."""
    offset = authoring._align_window(out, len(body))
    out += body
    return offset


def _place_picture(out: bytearray, body: bytes) -> int:
    """Put a picture down without that constraint, because pictures do not obey it.

    Between 15 and 19 pictures in each of the four images cross a 64 KiB boundary, and
    7 to 9 of them are larger than the window itself - a 176x220 backdrop stored whole
    is 77,445 bytes. Whatever the window protects, it is not pixel data.
    """
    offset = len(out)
    out += body
    return offset


def emit(model: dict, payload: bytes) -> tuple[bytes, dict]:
    """Lay the model out after the image's own resources and repoint the master index.

    The four composed sections are emitted last and in ascending order, so each one's
    range covers its own table and nothing else. Everything the model references but
    does not contain keeps the address it already had.
    """
    checksum_offset = int.from_bytes(payload[4:8], "little") - gspm.BASE - 2
    out = bytearray(payload[:checksum_offset])
    start = len(out)

    # Commands first: a record points at its own waveforms, so they are placed before it.
    device_records = []
    for commands in model["devices"]:
        offsets = []
        for command in commands:
            phases = {}
            for phase in ("press", "hold", "release"):
                body = command["phases"].get(phase)
                if body is not None:
                    phases[phase] = _place(out, body)
            record = _place(out, bytes(25))
            out[record:record + 25] = records.command_record(
                record, phases["press"], phases.get("hold"),
                command["carrier_period_ns"], command["carrier_half_period_ns"],
                release_offset=phases.get("release"), prefix=command["prefix"])
            offsets.append(record)
        device_records.append(offsets)

    font_records = []
    for font in model["fonts"]:
        placed = {code: _place(out, body) for code, body in sorted(font["glyphs"].items())}
        font_records.append(_place(out, _font_record(font, placed)))

    resources = {}
    for address, picture in sorted(model["pictures"].items()):
        resources[address] = _place_picture(out, bitmap.encode(
            picture["rows"], mode=picture["mode"]))
    # Glyph strings are deliberately not placed. A `text` target always names the inline
    # payload of an `inline_text` instruction rather than a string of its own, so the
    # layout registers those addresses and the sharing is preserved; placing a copy here
    # would give every pointer a private string the format never has.

    programs, mapping = drawing.lay_out(
        model["programs"], authoring._align_window(out, 1), mapping=resources)
    out += programs

    objects = []
    for atoms in model["objects"]:
        body = bytes([len(atoms)]) + b"".join(
            struct.pack("<HB", operand, opcode) for operand, opcode in atoms)
        objects.append(_place(out, body))
    contexts = [
        _place(out, authoring.context_record(item)) for item in model["contexts"]
    ]

    # Section 9 must hold every key register and nothing else, so the slots that point
    # at them are emitted first and filled in once the registers have their addresses.
    # No donor shares a register between slots - 213 and 439 slots, as many registers -
    # so each slot is given its own.
    headers = [
        _place(out, authoring.key_register(list(screen["header"])))
        for screen in model["screens"]
    ]
    trailers = []
    placed_slots = [
        [_place(out, bytes(7)) for _slot in screen["slots"]]
        for screen in model["screens"]
    ]
    for screen, offsets, header in zip(model["screens"], placed_slots, headers):
        trailers.append(_place(
            out, authoring.screen_trailer(screen["flag"], header, offsets)))

    section9 = None
    register_offsets = []
    for screen in model["screens"]:
        for slot in screen["slots"]:
            offset = _place(out, authoring.key_register(list(slot["entries"])))
            if section9 is None:
                section9 = offset
            register_offsets.append(offset)
    # Section 5's per-device sub-tables are not copies of section 4's device runs, they
    # are those runs: every one of the 20 sub-tables across the four donors begins
    # exactly where its device's run inside section 4 begins. So section 4 is emitted
    # once and section 5 points into it, instead of each run being written twice.
    section4 = _place(out, authoring.command_flat_index(device_records))
    subtables = []
    run = section4 + authoring.COMMAND_INDEX_HEAD_SIZE
    for offsets in device_records:
        subtables.append(run)
        run += len(authoring.command_subtable(offsets))
    section5 = _place(out, authoring.section5(subtables))
    section6 = _place(out, authoring.screen_index(trailers))
    section7 = _place(out, _font_index(font_records))
    section10 = _place(out, authoring.context_table(contexts))
    section11 = _place(out, _object_table(objects))
    section12 = _place(out, _overlay_index(
        [mapping[block] for block in model["overlays"]]))
    engine = [_place(out, _engine_record(item)) for item in model["engine"]]
    section14 = _place(out, _engine_index(engine))

    index = 0
    for screen, offsets in zip(model["screens"], placed_slots):
        for slot, offset in zip(screen["slots"], offsets):
            out[offset:offset + 7] = authoring.screen_slot(
                slot["template"], register_offsets[index], mapping[slot["program"]])
            index += 1

    placed = {
        4: section4, 5: section5, 6: section6, 7: section7,
        9: section9, 10: section10, 11: section11, 12: section12,
        14: section14,
    }
    for section in COMPOSED_SECTIONS:
        struct.pack_into("<I", out, 0x0C + 4 * section, gspm.BASE + placed[section])
    result = relocation.repair_integrity(bytes(out))
    gspm.validate(result)
    return result, {
        "mode": "compose",
        "sections": placed,
        "commands": sum(len(o) for o in device_records),
        "fonts": len(font_records),
        "pictures": len(model["pictures"]),
        "strings": len(model["strings"]),
        "programs": len(model["programs"]),
        "objects": len(model["objects"]),
        "contexts": len(model["contexts"]),
        "screens": len(model["screens"]),
        "overlays": len(model["overlays"]),
        "engine": len(model["engine"]),
        "key_registers": len(register_offsets),
        "emitted_bytes": len(out) - start,
        "size": {"before": len(payload), "after": len(result)},
    }


def _font_record(font: dict, placed: dict[int, int]) -> bytes:
    """Write a font's header and its glyph index, in the header layout it was read in."""
    slots = font["slots"]
    if font["layout"] == font_index.BYTE_COUNT:
        if slots > 0xFF:
            raise ValueError("this font header cannot count more than 255 glyphs")
        head = bytes([font["height"], 1, slots])
    else:
        head = bytes([font["height"]]) + slots.to_bytes(2, "little")
    out = bytearray(head)
    for code in range(1, slots + 1):
        offset = placed.get(code)
        out += (0 if offset is None else gspm.BASE + offset).to_bytes(3, "little")
    return bytes(out)


def _font_index(offsets: list[int]) -> bytes:
    if len(offsets) > 0xFFFF:
        raise ValueError("section 7 indexes at most 65535 fonts")
    return len(offsets).to_bytes(2, "little") + b"".join(
        (gspm.BASE + offset).to_bytes(3, "little") for offset in offsets)


def _object_table(offsets: list[int]) -> bytes:
    if not offsets or len(offsets) > 0xFFFF:
        raise ValueError("section 11 indexes between 1 and 65535 objects")
    return len(offsets).to_bytes(2, "little") + b"".join(
        (gspm.BASE + offset).to_bytes(3, "little") for offset in offsets)


def _engine_record(record: dict) -> bytes:
    """One section-14 property: its initial state, its limit, and its transitions."""
    out = struct.pack("<HHH", record["initial"], record["limit"],
                      len(record["transitions"]))
    out += bytes([record["padding"]])
    for row in record["transitions"]:
        out += struct.pack("<BHHHB", row["flags"], row["from"], row["to"],
                           row["operand"], row["category"])
    return out


def _engine_index(offsets: list[int]) -> bytes:
    """Section 14's header, measured in the factory image and every donor."""
    if len(offsets) > 0xFFFF:
        raise ValueError("section 14 indexes at most 65535 engine records")
    trailing = max(0, len(offsets) - 1)
    return (struct.pack("<HHHH", len(offsets), trailing, 1, trailing)
            + b"".join((gspm.BASE + offset).to_bytes(3, "little") for offset in offsets))


def _overlay_index(offsets: list[int]) -> bytes:
    if len(offsets) > 0xFFFF:
        raise ValueError("section 12 indexes at most 65535 overlay programs")
    return len(offsets).to_bytes(2, "little") + b"".join(
        (gspm.BASE + offset).to_bytes(3, "little") for offset in offsets)


def recompose(payload: bytes) -> tuple[bytes, dict]:
    """Re-emit an image's composable structures unchanged, and prove nothing moved.

    This is the no-change control for laying out a configuration: the model that goes
    in must be the model that comes back, with only addresses different.
    """
    before = canonical(payload)
    result, report = emit(read(payload), payload)
    after = canonical(result)
    if after != before:
        differing = sorted(
            key for key in before if before[key] != after.get(key))
        raise RuntimeError(
            "re-emitting the image changed its model: " + ", ".join(differing))
    return result, report
