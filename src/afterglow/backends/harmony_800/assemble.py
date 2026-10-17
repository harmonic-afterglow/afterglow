"""Placing everything a layout numbered, then the nineteen tables that index it.

Bodies are placed first - objects, command records and their waveforms, fonts, pictures,
touch templates, drawing programs, switch tables, contexts, timers and section 14's
records - and then the tables contiguously in ascending order, so that each section's
derived range covers its own table and nothing else, then the checksum and `PTYY`.
Section 9 is the exception that proves the order matters: it is not a table but the key
registers themselves, back to back between 7 and 10, as in every donor.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import drawing, firmware_screens, gspm, mark, records, scaffold, structures
from .carried import CARRIED_BLOCK
from .devices import transition
from .layout import bounded_objects, place, place_picture
from .firmware_screens import MODEL_BLOCK
from .scaffold import CHARGE_CONTEXTS, MODE_ZERO_EVENTS
from .structures import (
    OBJECT_ATOM, counted_index, engine_index, name_chain, name_record, object_body,
    timer_record, touch_zone)


def place_objects(layout) -> list[int]:
    """The objects, in the order they were numbered, none longer than the donors'."""
    return [place(layout.out, body) for body in bounded_objects(layout.objects)]


def place_commands(layout, devices) -> list[list[int]]:
    """Each device's command records. A record points at its own waveforms, so those are
    placed before it."""
    out = layout.out
    placed_devices = []
    for device in devices:
        placed = []
        for command in device["commands"]:
            phases = {phase: place(out, body)
                      for phase, body in sorted(command["phases"].items())}
            # A toggling command's other state: a second set, sent on every other press.
            others = {phase: place(out, body)
                      for phase, body in sorted((command.get("alternate_phases")
                                                 or {}).items())}
            alternate = ((others["press"], others.get("hold"), others.get("release"))
                         if others else None)
            size = records.record_size(alternate is not None)
            record = place(out, bytes(size))
            out[record:record + size] = records.command_record(
                record, phases["press"], phases.get("hold"),
                command["carrier_period_ns"], command["carrier_half_period_ns"],
                release_offset=phases.get("release"), alternate=alternate)
            placed.append(record)
        placed_devices.append(placed)
    return placed_devices


def section_names(variables, carried, engine_size: int) -> list[bytes]:
    """Section 0 names the state variables, by index, under `Root` and `State`, as every
    donor does; commands are not named."""
    leaves = [(variables.first + index, name)
              for index, (name, _record) in enumerate(variables.records)]
    if carried:
        sounds = carried.model["sounds"]["switch"]["variable"]
        if isinstance(sounds, dict):
            leaves.append((engine_size - 1 + sounds["variable"], "ButtonSoundVolume_2"))
    if not leaves:
        return []
    return ([name_record(0, "Root", leaf=False), name_record(1, "State", leaf=False)]
            + [name_record(index, name) for index, name in sorted(leaves)])


def place_fonts(layout, fonts) -> list[int]:
    out = []
    for font in fonts:
        placed = {code: place(layout.out, body) for code, body in sorted(font["glyphs"].items())}
        out.append(place(layout.out, structures.font_record(font, placed)))
    return out


def place_pictures(layout, pictures) -> dict[str, int]:
    """Only the pictures some program draws."""
    return {role: place_picture(layout.out, pictures[role]) for role in sorted(layout.drawn)}


def place_templates(layout) -> list[int]:
    out = []
    for zones in layout.template_zones:
        placed = []
        for zone in zones:
            at = len(layout.out)
            layout.out += touch_zone(zone, at)
            placed.append(at)
        out.append(place(layout.out, counted_index(placed, width=1, label="a touch template")))
    return out


def place_programs(layout, system, carried, picture_offsets, first_platform) -> tuple[dict, list]:
    """The drawing programs, once the pictures they draw have addresses: the firmware's
    fragments and page programs into the modes reserved for them, the carried screens'
    likewise, the rest together, then every owned page program. The mapping from model
    block to address, and section 12's overlays."""
    out = layout.out
    overlays = []
    mapping = {}
    if system:
        blocks = firmware_screens.system_blocks(system, picture_offsets, first_platform)
        if carried:
            for index, block in enumerate(carried.model["blocks"]):
                blocks[CARRIED_BLOCK + index] = carried.block(block, picture_offsets.__getitem__)
            blocks.update(layout.blocks)
        fixed = {**layout.fixed_blocks, **layout.carried_fixed}
        rest = {at: block for at, block in blocks.items() if at not in fixed}
        size = sum(len(drawing.encode_program(block)) for block in rest.values())
        body, mapping = drawing.lay_out(
            rest, structures._align_window(out, min(size, structures.ADDRESS_WINDOW)),
            mapping=fixed)
        out += body
        for at, offset in list(fixed.items()) + layout.extra_copies:
            block = drawing.relocated(blocks[at], mapping)
            if at in layout.fragments:
                block.append({"opcode": "end"})
            encoded = drawing.encode_program(block)
            out[offset:offset + len(encoded)] = encoded
        overlays = [mapping[MODEL_BLOCK + index] for index in system["overlays"]]
    for at, build, prologue in layout.pending_programs:
        encoded = drawing.encode_program(drawing.relocated(
            build(picture_offsets.__getitem__, prologue), mapping))
        out[at:at + len(encoded)] = encoded
    return mapping, overlays


def _group(group, address) -> bytes:
    """A section-15 switch table: a lead byte, the exact cases `{u16 value, u24
    program}`, then the ranges `{u16 low, u16 high, u24 program}`."""
    record = bytearray([group["lead"], len(group["cases"])])
    for value, at in group["cases"]:
        record += struct.pack("<H", value) + (gspm.BASE + address(at)).to_bytes(3, "little")
    record.append(len(group["ranges"]))
    for low, high, at in group["ranges"]:
        record += struct.pack("<HH", low, high) + (gspm.BASE + address(at)).to_bytes(
            3, "little")
    return bytes(record)


def place_groups(layout, carried, mapping) -> list[int]:
    """Section 15's switch tables, now their programs have addresses: the carried
    screens', then the build's own."""
    out = [place(layout.out, _group(group, lambda at: mapping[CARRIED_BLOCK + at]))
           for group in (carried.model["groups"] if carried else ())]
    out += [place(layout.out, _group(group, mapping.__getitem__)) for group in layout.groups]
    return out


def place_contexts(layout, carried, activity_rows, global_keys) -> list[int]:
    """Section 10: the image's own context, then the idle layer's - its events, the key
    light, the charge contexts - and each activity's, then Off's."""
    out = layout.out
    idle = carried.idle if carried else None
    if idle is None:
        # A context needs a row, and no context in any image binds key 0. The factory
        # image leaves keys it does not use as category 0 with operand 0, so the one row
        # this context holds is the factory's own unbound row rather than an object 0.
        return [place(out, structures.context_record({
            "form": "short",
            "rows": [{"flags": None, "key_code": 0x10, "operand": 0, "category": 0x00}],
        }))]

    def charge_rows(name):
        return [{"flags": 1, "key_code": int(code, 16), "operand": carried.operand(operand),
                 "category": carried.category(category)}
                for code, (operand, category) in idle["charge"][name].items()]
    placed = [place(out, structures.context_record({"form": "long",
                                                   "rows": charge_rows("normal")}))]
    # The events the firmware posts - USB, charging, redraws, the side strips' paging -
    # and the key light every physical key runs and then passes on (flags bit 0 set, so
    # the search goes on down the stack), as upstairs' contexts 1 and 4 are.
    event_rows = [{"flags": None, "key_code": int(code, 16),
                   "operand": carried.operand(operand), "category": carried.category(category)}
                  for code, (operand, category) in idle["events"].items()]
    # The keys the flow owns, under everything else on the stack: Activities opens the
    # Activities menu, Off selects Off's context.
    event_rows += [{"flags": None, "key_code": code, "operand": operand,
                    "category": OBJECT_ATOM} for code, operand in global_keys]
    placed.append(place(out, structures.context_record({"form": "short", "rows": event_rows})))
    operand, category = idle["key_light"]
    rows = [{"flags": 1, "key_code": key, "operand": carried.operand(operand),
             "category": carried.category(category)}
            for key in MODE_ZERO_EVENTS if key >= 0x80]
    # and the two codes below the keys that wake it too: picking it up, and 0x30
    rows += [{"flags": 1, "key_code": int(code, 16), "operand": carried.operand(value),
              "category": carried.category(cat)}
             for code, (value, cat) in idle.get("key_rows", {}).items()]
    placed.append(place(out, structures.context_record({"form": "long", "rows": rows})))
    for name in ("usb", "low"):
        if len(placed) != CHARGE_CONTEXTS[name]:
            raise ValueError(f"the {name} charge context is not where 0xFC finds it")
        placed.append(place(out, structures.context_record({"form": "long",
                                                           "rows": charge_rows(name)})))
    # Each activity's context, then Off's: enter, leave and picked again, Help, and the
    # keys it routes.
    for index in sorted(activity_rows):
        if index != len(placed):
            raise ValueError("an activity's context is not where its rows select it")
        placed.append(place(out, structures.context_record({"form": "short", "rows": [
            {"flags": None, "key_code": code, "operand": operand, "category": OBJECT_ATOM}
            for code, operand in activity_rows[index]]})))
    return placed


def place_timers(layout, system, carried, first_platform) -> list[int]:
    """Section 13. The platform screens start timer by index while they are shown - the
    status bar's refresh - so the image carries the platform's timers; an empty table
    left every one of those starts reading past its end."""
    out = layout.out
    placed = [place(out, timer_record(item["flags"], item["duration"],
                                      scaffold.platform_object(item["action"][0],
                                                               first_platform),
                                      item["action"][1]))
              for item in (system or {}).get("timers", ())]
    if carried:
        placed += [place(out, timer_record(item["flags"], item["duration"],
                                           carried.operand(item["action"][0]),
                                           carried.category(item["action"][1])))
                   for item in carried.model["timers"]]
    return placed


def place_engine(layout, objects, records, carried, variables) -> list[int]:
    """Section 14's records, which hold no addresses, so they are placed as they are
    given - the platform's, the carried screens', the build's own, the terminator - once
    any object a transition names by its atoms has been placed and given an index."""
    out = layout.out
    if carried or variables.records:
        records = list(records[:-1]) + [
            {"initial": item["initial"], "limit": item["limit"], "padding": 0,
             "transitions": [
                 transition(t["from"], t["to"], carried.operand(t["action"][0]),
                            carried.category(t["action"][1]))
                 | {"flags": t["flags"]} for t in item.get("transitions", ())]}
            for item in (carried.model if carried else {}).get("variables", ())] + [
            record for _name, record in variables.records] + list(records[-1:])
    placed = []
    for item in records:
        rows = []
        for row in item["transitions"]:
            if isinstance(row["operand"], dict):
                objects.append(place(out, object_body(row["operand"]["atoms"])))
                row = {**row, "operand": len(objects) - 1}
            rows.append(row)
        placed.append(place(out, structures.engine_record({**item, "transitions": rows})))
    return placed


def write_tables(layout, *, sections: dict, device_records, startup: int, groups, tail) -> None:
    """The nineteen tables, contiguously and in ascending order, and the master index."""
    out = layout.out
    placed = {}
    for index in range(20):
        if index == 9:
            # The start-up list, then every slot's register, in slot order, with nothing
            # between them. A pad zero is not an empty register: a leading zero selects
            # the wide form, so it would take the next byte as a count and put a walk of
            # the section out of step. The section is placed whole, so any window padding
            # comes before it.
            registers = [structures.key_register(rows)
                         for _slot, _t, rows, _p in layout.pending_slots]
            lead = object_body([(startup, OBJECT_ATOM)])
            offset = place(out, lead + b"".join(registers))
            register = offset + len(lead)
            for (slot, template, _rows, program), body in zip(layout.pending_slots, registers):
                out[slot:slot + 7] = structures.screen_slot(template, register, program)
                register += len(body)
        elif index == 5:
            # Section 5's sub-tables are section 4's device runs, so it points into
            # section 4 rather than holding copies of them.
            offset = len(out)
            run = placed[4] + structures.COMMAND_INDEX_HEAD_SIZE
            subtables = []
            for commands in device_records:
                subtables.append(run)
                run += len(structures.command_subtable(commands))
            out += (bytes([len(subtables)])
                    + b"".join((gspm.BASE + item).to_bytes(3, "little") for item in subtables))
        elif index == 15:
            offset = len(out)
            out += scaffold.platform_table(groups, tail)
            tail_at = offset + 1 + 3 * len(groups)
        elif index == 16:
            offset = len(out)
            out += scaffold.platform_index(tail_at)
        else:
            offset = len(out)
            out += sections[index]
        placed[index] = offset
    for index, offset in placed.items():
        struct.pack_into("<I", out, 0x0C + 4 * index, gspm.BASE + offset)


def image(layout, *, devices, fonts, pictures, system, carried, variables, engine,
          activity_rows, global_keys, startup, stamp, tail, first_platform,
          project: dict) -> bytes:
    """Place everything ``layout`` numbered, write the tables, mark the image with the
    ``project`` it was built from (mark.py), and seal it."""
    objects = place_objects(layout)
    device_records = place_commands(layout, devices)
    names = section_names(variables, carried, len(engine))
    font_records = place_fonts(layout, fonts)
    picture_offsets = place_pictures(layout, pictures)
    templates = place_templates(layout)
    if system and not isinstance(pictures, dict):
        raise ValueError("the firmware's screens draw pictures by name, so name them")
    mapping, overlays = place_programs(layout, system, carried, picture_offsets, first_platform)
    groups = place_groups(layout, carried, mapping)
    contexts = place_contexts(layout, carried, activity_rows, global_keys)
    if not objects:
        objects.append(place(layout.out, b"\x00"))
    timers = place_timers(layout, system, carried, first_platform)
    records = place_engine(layout, objects, engine, carried, variables)
    write_tables(layout, device_records=device_records, startup=startup, groups=groups,
                 tail=tail, sections={
                     0: name_chain(names),
                     1: scaffold.CONSTANT_SECTIONS[1],
                     2: scaffold.CONSTANT_SECTIONS[2],
                     3: stamp,
                     4: structures.command_flat_index(device_records),
                     6: structures.screen_index(layout.trailers),
                     7: counted_index(font_records, width=2, label="section 7"),
                     8: b"\x00",              # the 800's radio commands: none
                     10: counted_index(contexts, width=1, label="section 10"),
                     11: counted_index(objects, width=2, label="section 11"),
                     12: counted_index(overlays, width=2, label="section 12"),
                     13: counted_index(timers, width=1, label="section 13"),
                     14: engine_index(records),
                     17: scaffold.CONSTANT_SECTIONS[17],
                     18: scaffold.CONSTANT_SECTIONS[18],
                     19: counted_index(templates, width=1, label="section 19"),
                 })
    result = gspm.seal(mark.append(layout.out, project))
    gspm.validate(result)
    return result
