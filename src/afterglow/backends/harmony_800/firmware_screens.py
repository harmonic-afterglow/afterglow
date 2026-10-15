"""The firmware's own forty screens - the battery warning, USB Connected, the update
notices and the system messages - carried into a generated image from the scaffold's
model (platform/system-screens.json), at the ordinals and template indices the firmware
looks for.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import json
from pathlib import Path

from .pages import PAGE_COUNTER_Y
from .screens import BACKDROP
from . import drawing, gspm, structures
from .scaffold import ENTER, LEAVE, REDRAW, platform_object
from .structures import OBJECT_ATOM


def event_handlers(header, first: int) -> dict[int, int]:
    """A platform screen's event handlers, ``tag -> image object index``."""
    return {key: platform_object(operand, first)
            for key, operand, category in header
            if category == OBJECT_ATOM and key in (ENTER, LEAVE, REDRAW)}


def owned_handlers(system, first: int) -> list[tuple[int, int, int]]:
    """Enter, leave and redraw for a screen the image owns, as platform screens have them.

    Every mode on a Harmony 800 carries an enter and a leave handler, and the firmware's
    own screens also redraw their status overlays on event 2D. A screen this backend adds
    uses the same three: the platform's enter and leave actions and its redraw object.
    """
    if not system:
        return []
    for screen in system["screens"]:
        rows = {key: (operand, category) for key, operand, category in screen["header"]}
        if ENTER in rows and LEAVE in rows and REDRAW in rows \
                and rows[ENTER][1] != OBJECT_ATOM and rows[LEAVE][1] != OBJECT_ATOM:
            return [(tag, platform_object(rows[tag][0], first), rows[tag][1])
                    for tag in (ENTER, LEAVE, REDRAW)]
    return []


SYSTEM_SCREENS_FILE = "platform/system-screens.json"
SYSTEM_TEMPLATES_FILE = "platform/system-templates.json"
SYSTEM_SCHEMA = "afterglow-harmony-one-system-screens/1"

# Addresses for blocks built from a model rather than read out of an image. A pointer is
# 24 bits past the mapping base, so these sit inside that range but far above anything
# an image this backend will write can reach.
MODEL_BLOCK = 0xF00000

# The status bar's clock - its words and the patch it is drawn on - sits on the One's top
# row at 18; on the 800 it drops onto the page counter's line, beside the title bar's
# counter rather than across the edge between the bar's two bands.
CLOCK_PATCH = "status/progress"
CLOCK_ROW = 18
CLOCK_DROP = PAGE_COUNTER_Y - CLOCK_ROW


def load_system(directory=None) -> dict:
    """The firmware's own screens, as the scaffold carries them."""
    from ... import paths

    directory = Path(paths.scaffolds("harmony-800") if directory is None else directory)
    model = json.loads((directory / SYSTEM_SCREENS_FILE).read_text("utf-8"))
    if model.get("schema") != SYSTEM_SCHEMA:
        raise ValueError(
            f"{SYSTEM_SCREENS_FILE} declares {model.get('schema')!r}, not {SYSTEM_SCHEMA!r}")
    model["templates"] = json.loads((directory / SYSTEM_TEMPLATES_FILE).read_text("utf-8"))
    return model


def system_blocks(model: dict, pictures: dict[str, int], first_object: int) -> dict:
    """The platform's blocks with every name resolved, keyed by a model address.

    Block references become model addresses the layout maps to where each block lands;
    pictures resolve to where they were placed; an object reference becomes the index the
    platform's objects were given in this image. Nothing refers to a donor any more.
    """
    from . import geometry

    # The status bar - the overlays and every block they reach - sits at the display's top
    # right on the 800; the rest of the platform's screens in its middle (geometry.py).
    status, todo = set(), list(model.get("overlays") or [])
    while todo:
        index = todo.pop()
        if index in status:
            continue
        status.add(index)
        for item in model["blocks"][index]:
            target = item.get("target")
            if isinstance(target, dict) and "block" in target:
                todo.append(target["block"])
            for case in item.get("cases", ()) + item.get("ranges", ()) if \
                    item.get("opcode") == "switch" else ():
                todo.append(case[-1])
    blocks = {}
    for index, block in enumerate(model["blocks"]):
        instructions = []
        for item in block:
            item = dict(item)
            if index in status:
                # the clock's words too: platform_text puts a label on the One's top row
                # at the 800's top left, which is the title's place, not the status bar's.
                # The clock and the patch under it drop onto the page counter's line.
                item.pop("native", None)
                clock = item["opcode"] == "inline_text" or (
                    isinstance(item.get("target"), dict)
                    and item["target"].get("picture") == CLOCK_PATCH)
                item["origin"] = (geometry.STATUS_ORIGIN[0],
                                  geometry.STATUS_ORIGIN[1] + (CLOCK_DROP if clock else 0))
            target = item.get("target")
            if isinstance(target, dict) and "block" in target:
                item["target"] = MODEL_BLOCK + target["block"]
            elif isinstance(target, dict) and "picture" in target:
                role = target["picture"]
                if role not in pictures:
                    raise ValueError(
                        f"the platform screens draw {role!r}, which the scaffold lacks")
                item["target"] = pictures[role]
            if item["opcode"] == "switch":
                item["cases"] = [(value, MODEL_BLOCK + at) for value, at in item["cases"]]
                item["ranges"] = [(low, high, MODEL_BLOCK + at)
                                  for low, high, at in item["ranges"]]
            if item["opcode"] == "atom" and isinstance(item.get("operand"), dict):
                item["operand"] = first_object + item["operand"]["object"]
            if (item["opcode"] == "bitmap" and index not in status
                    and item["x"] == item["y"] == 0):
                # the One's whole-screen picture covers only the 800's middle: the
                # display's backdrop first, so nothing another screen drew stays beside it
                instructions.append({"opcode": "bitmap", "x": 0, "y": 0,
                                     "target": pictures[BACKDROP], "native": True})
            instructions.append(item)
        blocks[MODEL_BLOCK + index] = instructions
    return blocks


def place(layout, system, household, platform_handlers, navigate, roles, first_platform):
    """The firmware's own screens, at the ordinals and template indices it looks for.

    Their OK buttons open the first screen the project owns; the object bindings of their
    physical keys lead into the donor's help flow and are not carried. Each one's page
    program opens by calling a fragment no other program calls, which is the fragment its
    mode carries after its list."""
    # the firmware's screens name their templates by index, so these are all kept
    layout.keep_templates(system["templates"])
    layout.fix_templates()
    measured = system_blocks(system, {role: 0 for role in roles}, first_platform)
    layout.drawn.update(item["target"]["picture"] for block in system["blocks"] for item in block
                        if isinstance(item.get("target"), dict) and "picture" in item["target"])
    layout.drawn.add(BACKDROP)
    callers = {}
    for at, block in measured.items():
        for item in block:
            targets = [item.get("target")] if item["opcode"] in ("call", "jump") else []
            if item["opcode"] == "switch":
                targets = [t for _v, t in item["cases"]] + [t for *_r, t in item["ranges"]]
            for target in targets:
                callers.setdefault(target, set()).add(at)
    shared = {MODEL_BLOCK + index for index in system["overlays"]}
    for screen in system["screens"]:
        shared.update(MODEL_BLOCK + slot["program"] for slot in screen["slots"])
    for ordinal, screen in enumerate(system["screens"]):
        if ordinal == 0 and household:
            # Mode 0's list is the one the firmware reads after LWJL.
            header = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC)
        else:
            rows = [(key, platform_object(operand, first_platform), category)
                    for key, operand, category in screen["header"]
                    if (ordinal, key) not in platform_handlers]
            rows += [(tag, *platform_handlers[(ordinal, tag)])
                     for tag in (ENTER, LEAVE, REDRAW)
                     if (ordinal, tag) in platform_handlers]
            header = structures.key_register(rows)
        mode_pages, owned = [], []
        for slot in screen["slots"]:
            program = MODEL_BLOCK + slot["program"]
            first = measured[program][0]
            blocks = [program]
            if (first["opcode"] == "call" and first["target"] not in shared
                    and callers.get(first["target"]) == {program}):
                blocks.insert(0, first["target"])
                shared.add(first["target"])
                layout.fragments.add(first["target"])
            rows = [(key["key"], navigate, OBJECT_ATOM) for key in slot["keys"]]
            # A fragment ends at its return, and every donor follows that with an end.
            sizes = [len(drawing.encode_program(measured[at])) + (at in layout.fragments)
                     for at in blocks]
            mode_pages.append((slot["template"], rows, sizes))
            owned.append(blocks)
        for blocks, placed in zip(owned, layout.mode(header, screen["flag"], mode_pages)):
            layout.fixed_blocks.update(zip(blocks, placed))
