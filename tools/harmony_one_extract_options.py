#!/usr/bin/env python3
"""Carry a Harmony One's Options screens into the scaffold as a model a build can link.

    python3 tools/harmony_one_extract_options.py donor.EZHex src/afterglow/scaffolds/harmony-one

## Why this exists

Every Logitech configuration has an Options screen whatever it holds - Date and Time,
Screen Sensitivity, Screen Sounds - and those screens are the builder's boilerplate, not
the owner's: they set the remote's clock and its touch screen, nothing a device or an
activity owns. So they are copied the way the firmware's own forty screens are: the
screens a donor's Options entries reach, with everything those reach in turn - programs,
objects, timers, section-15 switch tables, state variables, pictures - written as a model
whose every reference is a name, so a build can number them afresh.

The walk stops where the screens lead out of Options: back to the Options screen itself,
or to Activities and Devices. Those become named exits. Remote Assistant and Tutorial are
left out: they lead into a configuration's activities and its help flow.

Nothing that identifies a remote or its owner is read; the screens draw the builder's
text and the builder's pictures.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from afterglow.backends.harmony_one import (  # noqa: E402
    activity_index, command_index, compose, drawing, gspm, ui_index)
import harmony_one_extract_assets as assets_tool  # noqa: E402


SCHEMA = "afterglow-harmony-one-carried-screens/1"
MODEL_FILE = "platform/options.json"
PLATFORM_VARIABLES = 18
OVERLAYS = 4
# Opcodes, as the Harmony 800's interpreter reads them (harmony-800.md).
OBJECT, MODE, OVERLAY, SWITCH = 0x7F, 0x7E, 0x73, 0x72
TESTS = (0x70, 0x71)
ROW_FRAME_YS = (38, 92, 146)
PICTURE_KINDS = {(81, 50): "button-frame", (164, 50): "row-frame"}
REGISTER = 0x1F
TIMER_BANDS = (0xEA, 0xEB)
CONTEXT_BANDS = (0xFF, 0xFE, 0xFD)

# Upstairs, the donor the scaffold is drawn from: its Options screen, the screens its
# entries open, and the ones the walk must not enter.
OPTIONS = {
    "options": 276,
    "entries": {"date-and-time": 176, "screen-sensitivity": 104},
    "sounds": {"key": 0xB0, "page": 1},     # the switch Options' Screen Sounds row runs
    "exits": {276: "options", 197: "home", 72: "devices"},
}


def _u24(payload: bytes, at: int) -> int:
    return int.from_bytes(payload[at:at + 3], "little") - gspm.BASE


def _rows(payload: bytes, at: int) -> list[tuple[int, int, int]]:
    """A key list in either form: `count {key, u16, op}` or `00 count {flags, key, u16, op}`."""
    count = payload[at]
    if count:
        return [(payload[at + 1 + 4 * k], *struct.unpack_from("<HB", payload, at + 2 + 4 * k))
                for k in range(count)]
    count = payload[at + 1]
    return [(payload[at + 3 + 5 * k], *struct.unpack_from("<HB", payload, at + 4 + 5 * k))
            for k in range(count)]


def carried_screens(payload: bytes, roles: dict[str, int], spec=OPTIONS) -> tuple[dict, dict]:
    """The model of the screens ``spec`` names, and the pictures it needs named."""
    ranges = gspm.section_ranges(payload)
    objects = command_index.objects(payload)
    records = activity_index.engine_records(payload)
    templates = ui_index.touch_templates(payload)
    role_of = {target: role for role, target in roles.items()}
    new_roles: dict[str, int] = {}
    exits = spec["exits"]

    mode_index: dict[int, int] = {}
    model_modes: list = []
    object_index: dict[int, int] = {}
    model_objects: list = []
    timer_index: dict[int, int] = {}
    model_timers: list = []
    group_index: dict[int, int] = {}
    model_groups: list = []
    variable_index: dict[int, int] = {}
    model_variables: list = []
    template_index: dict[int, int] = {}
    model_templates: list = []
    block_index: dict[int, int] = {}
    model_blocks: list = []

    def variable(donor: int):
        if donor < PLATFORM_VARIABLES:
            return donor
        if donor not in variable_index:
            record = records[donor]
            if record["transitions"]:
                raise SystemExit(f"carried variable {donor} has transitions")
            variable_index[donor] = len(model_variables)
            model_variables.append({"initial": record["initial"], "limit": record["limit"]})
        return {"variable": variable_index[donor]}

    def mode(donor: int):
        if donor in exits:
            return {"exit": exits[donor]}
        if donor < 40:
            return donor
        if donor not in mode_index:
            mode_index[donor] = len(model_modes)
            model_modes.append(None)
            model_modes[mode_index[donor]] = carry_mode(donor)
        return {"mode": mode_index[donor]}

    def obj(donor: int):
        if donor not in object_index:
            object_index[donor] = len(model_objects)
            model_objects.append(None)
            model_objects[object_index[donor]] = [
                instruction(value, category) for value, category in objects[donor]["atoms"]]
        return {"object": object_index[donor]}

    def timer(donor: int):
        if donor not in timer_index:
            start = ranges[13][0]
            at = _u24(payload, start + 1 + 3 * donor)
            timer_index[donor] = len(model_timers)
            model_timers.append(None)
            operand, opcode = struct.unpack_from("<HB", payload, at + 4)
            model_timers[timer_index[donor]] = {
                "flags": payload[at], "duration": int.from_bytes(payload[at + 1:at + 4], "little"),
                "action": instruction(operand, opcode)}
        return timer_index[donor]

    def group(donor: int):
        if donor not in group_index:
            start = ranges[15][0]
            at = _u24(payload, start + 1 + 3 * donor)
            group_index[donor] = len(model_groups)
            model_groups.append(None)
            lead, n = payload[at], payload[at + 1]
            cases, cursor = [], at + 2
            for _ in range(n):
                value = struct.unpack_from("<H", payload, cursor)[0]
                cases.append([value, block(_u24(payload, cursor + 2))])
                cursor += 5
            m, cursor = payload[cursor], cursor + 1
            spans = []
            for _ in range(m):
                low, high = struct.unpack_from("<HH", payload, cursor)
                spans.append([low, high, block(_u24(payload, cursor + 4))])
                cursor += 7
            model_groups[group_index[donor]] = {"lead": lead, "cases": cases, "ranges": spans}
        return group_index[donor]

    def instruction(operand: int, opcode: int) -> list:
        """One `(operand, opcode)` with every reference named."""
        high, low = operand >> 8, operand & 0xFF
        if opcode == OBJECT:
            return [obj(operand), opcode]
        if opcode == MODE:
            return [mode(operand), opcode]
        if opcode == OVERLAY:
            if operand >= OVERLAYS:
                raise SystemExit(f"a carried screen draws overlay {operand}")
            return [operand, opcode]
        if opcode == SWITCH:
            return [{"group": group(high), "variable": variable(low)}, opcode]
        if opcode in TESTS:
            return [{"test": high, "variable": variable(low)}, opcode]
        if opcode >= 0x80:
            return [operand, {"write": variable(opcode & 0x7F)}]
        if opcode == REGISTER and high in TIMER_BANDS:
            return [{"timer": timer(low), "band": high}, opcode]
        if opcode == REGISTER and high in CONTEXT_BANDS and low < 0xFC:
            raise SystemExit(f"a carried screen selects context {low}")
        return [operand, opcode]

    def picture(target: int) -> str:
        """A picture's role, naming a new one after what its size makes it."""
        if target not in role_of:
            width, height = struct.unpack_from("<HH", payload, target + 1)
            kind = PICTURE_KINDS.get((width, height), "picture")
            count = sum(1 for role in new_roles if role.startswith(f"options/{kind}/"))
            role = f"options/{kind}/{count}"
            new_roles[role] = target
            role_of[target] = role
        return role_of[target]

    def block(at: int) -> int:
        if at in block_index:
            return block_index[at]
        block_index[at] = len(model_blocks)
        model_blocks.append(None)
        listing = drawing.program_blocks(payload, [at])[at]
        out = []
        for item in listing:
            kind = item["opcode"]
            item = {key: value for key, value in item.items() if key != "offset"}
            if kind in ("call", "jump"):
                item["target"] = {"block": block(item["target"])}
            elif kind == "switch":
                item["selector"] = variable(item["selector"])
                item["cases"] = [[value, block(target)] for value, target in item["cases"]]
                item["ranges"] = [[low, high, block(target)]
                                  for low, high, target in item["ranges"]]
            elif kind == "bitmap":
                item["target"] = {"picture": picture(item["target"])}
            elif kind == "text":
                item = {"opcode": "inline_text", "x": item["x"], "y": item["y"],
                        "glyphs": item["glyphs"]}
            elif kind == "atom":
                item["operand"], item["category"] = instruction(item["operand"],
                                                                item["category"])
            out.append(item)
        model_blocks[block_index[at]] = out
        return block_index[at]

    def template(donor: int) -> int:
        if donor not in template_index:
            template_index[donor] = len(model_templates)
            model_templates.append([
                {"tag": zone["tag"], "x": zone["x"], "width": zone["width"],
                 "y": zone["y"], "height": zone["height"]}
                for zone in templates[donor]])
        return template_index[donor]

    def rows(at: int) -> list:
        return [[key, *instruction(operand, opcode)] for key, operand, opcode in _rows(payload, at)]

    def carry_mode(donor: int) -> dict:
        start = ranges[6][0]
        entry = _u24(payload, start + 3 + 3 * donor)
        pages = []
        for page in range(struct.unpack_from("<H", payload, entry + 4)[0]):
            record = _u24(payload, entry + 6 + 3 * page)
            pages.append({"template": template(payload[record]),
                          "rows": rows(_u24(payload, record + 1)),
                          "program": block(_u24(payload, record + 4))})
        return {"flag": payload[entry], "header": rows(_u24(payload, entry + 1)),
                "pages": pages, "donor": donor}

    entries = {name: mode(donor)["mode"] for name, donor in spec["entries"].items()}
    # Screen Sounds is a row of the Options screen itself: a switch on its flag, whose
    # programs toggle it. The row is drawn by the build; the switch and flag are carried.
    options_entry = _u24(payload, ranges[6][0] + 3 + 3 * spec["options"])
    record = _u24(payload, options_entry + 6 + 3 * spec["sounds"]["page"])
    sounds = next(instruction(operand, opcode)
                  for key, operand, opcode in _rows(payload, _u24(payload, record + 1))
                  if key == spec["sounds"]["key"])
    model = {
        "schema": SCHEMA,
        "entries": entries,
        "sounds": {"switch": sounds[0]},
        "modes": model_modes,
        "templates": model_templates,
        "blocks": model_blocks,
        "objects": model_objects,
        "timers": model_timers,
        "groups": model_groups,
        "variables": model_variables,
    }
    return model, new_roles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("donor", type=Path, help="an .EZHex backup or a raw GSPM payload")
    parser.add_argument("directory", type=Path, help="the scaffold to write into")
    args = parser.parse_args()

    payload = assets_tool.payload_of(args.donor)
    gspm.validate(payload)
    roles = {**assets_tool.picture_roles(payload), **assets_tool.overlay_roles(payload)}
    roles.update(assets_tool.system_picture_roles(payload, set(roles.values())))
    model, new_roles = carried_screens(payload, roles)

    # The Options screen's own row frames, top to bottom, which the build draws its rows
    # on: named like every other picture, and the model records which they are.
    options_entry = _u24(payload,
                         gspm.section_ranges(payload)[6][0] + 3 + 3 * OPTIONS["options"])
    program = _u24(payload, _u24(payload, options_entry + 6) + 4)
    drawn = [item for block in drawing.program_blocks(payload, [program]).values()
             for item in block if item["opcode"] == "bitmap"]
    named = {target: role for role, target in {**roles, **new_roles}.items()}
    frames = []
    for y in ROW_FRAME_YS:
        target = next(item["target"] for item in drawn if (item["x"], item["y"]) == (6, y))
        if target not in named:
            count = sum(1 for role in new_roles if role.startswith("options/row-frame/"))
            role = f"options/row-frame/{count}"
            new_roles[role] = target
            named[target] = role
        frames.append(named[target])
    model["row_frames"] = frames

    manifest_path = args.directory / "assets.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    for role, target in sorted(new_roles.items()):
        name = f"images/{role}.png"
        manifest["pictures"][role] = {
            "file": name, **assets_tool.write_picture(payload, target, args.directory / name)}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8")
    (args.directory / MODEL_FILE).write_text(json.dumps(model) + "\n", "utf-8")
    print(f"carried {len(model['modes'])} screens, {len(model['blocks'])} blocks, "
          f"{len(model['objects'])} objects, {len(model['timers'])} timers, "
          f"{len(model['groups'])} switch tables, {len(model['variables'])} variables, "
          f"{len(new_roles)} new pictures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
