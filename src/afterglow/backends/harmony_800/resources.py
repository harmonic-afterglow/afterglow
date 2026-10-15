"""Name the interface parts a Harmony 800 image is drawn from.

The parts a screen is made of turn out to be constant within an image: one frame bitmap
per button position, one font per role, one shared softkey string, one background, one
selector. This module derives them from a configuration and refuses any that the image
does not agree on, which is how the scaffold's artwork is extracted
(tools/harmony_one_extract_assets.py). It names resources; it does not invent them.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from collections import Counter, defaultdict

from . import command_index, gspm, key_index, ui_index


TITLE_FONT_ROLE = "title"
BUTTON_FONT_ROLE = "button"
SOFTKEY_FONT_ROLE = "softkey"
INDICATOR_FONT_ROLE = "indicator"
MENU_ROW_FONT_ROLE = "menu_row"

SOFTKEY_XY = (110, 202)
PAGES_WORD_XY = (35, 18)


def _agreed(counts: Counter, label: str, rejected: Counter):
    """Return the single value an image uses, or nothing when it disagrees."""
    if not counts:
        return None
    if len(counts) > 1:
        rejected[f"{label}_disagrees"] += len(counts)
        return None
    return next(iter(counts))


def catalogue(payload: bytes, ownership: dict | None = None) -> dict:
    """Derive the interface parts this image agrees on, with its disagreements counted."""
    ownership = command_index.inspect(payload) if ownership is None else ownership
    rejected: Counter = Counter()
    frames: dict[tuple[int, int], Counter] = defaultdict(Counter)
    fonts: dict[str, Counter] = defaultdict(Counter)
    softkey: Counter = Counter()
    switches: Counter = Counter()
    templates: dict[int, Counter] = defaultdict(Counter)
    background: Counter = Counter()
    prologue_atom: Counter = Counter()
    pages_word: Counter = Counter()
    prologue_shape: Counter = Counter()

    sources = command_screen_sources(payload, ownership)
    for source in sources:
        program = ui_index.drawing_program(payload, source["program_offset"])
        try:
            drawn = buttons(payload, source["program_offset"])
        except ValueError:
            rejected["unreadable_command_page"] += 1
            continue
        templates[len(source["command_key_codes"])][source["template"]] += 1
        fonts[BUTTON_FONT_ROLE][drawn[0]["attribute"]] += 1
        for button in drawn:
            frames[(button["x"], button["y"])][
                program["instructions"][button["instruction"]]["target"]] += 1
        attribute = None
        for item in program["instructions"]:
            if item["opcode"] == "attribute":
                attribute = item["value"]
            elif item["opcode"] == "switch":
                switches[item["selector"]] += 1
            elif item["opcode"] in ("text", "inline_text"):
                where = (item["x"], item["y"])
                if where == SOFTKEY_XY and "target" in item:
                    softkey[item["target"]] += 1
                    fonts[SOFTKEY_FONT_ROLE][attribute] += 1
                elif where == PAGE_NUMBER_XY:
                    fonts[INDICATOR_FONT_ROLE][attribute] += 1

        if not program["instructions"] or program["instructions"][0]["opcode"] != "call":
            continue
        prologue = ui_index.drawing_program(payload, program["instructions"][0]["target"])
        prologue_shape[tuple(item["opcode"] for item in prologue["instructions"])] += 1
        seen = []
        for item in prologue["instructions"]:
            if item["opcode"] == "attribute":
                seen.append(item["value"])
            elif item["opcode"] == "bitmap":
                background[(item["x"], item["y"], item["target"])] += 1
            elif item["opcode"] == "atom" and item["category"] == 0x73:
                prologue_atom[(item["operand"], item["category"])] += 1
            elif (item["opcode"] in ("text", "inline_text")
                    and (item["x"], item["y"]) == PAGES_WORD_XY and "target" in item):
                pages_word[item["target"]] += 1
        if seen:
            fonts[TITLE_FONT_ROLE][seen[0]] += 1

    chrome = _page_chrome(payload, sources, rejected)
    menu = _menu_parts(payload, ownership, fonts, rejected)
    for position, found in frames.items():
        if len(found) > 1:
            rejected["button_frame_disagrees"] += 1
    return {
        "button_frames": {
            position: found.most_common(1)[0][0]
            for position, found in sorted(frames.items()) if len(found) == 1
        },
        "fonts": {
            role: _agreed(found, f"{role}_font", rejected)
            for role, found in sorted(fonts.items())
        },
        "softkey_text": _agreed(softkey, "softkey_text", rejected),
        "pages_word": pages_word.most_common(1)[0][0] if pages_word else None,
        "background": _agreed(background, "background", rejected),
        "prologue_atom": _agreed(prologue_atom, "prologue_atom", rejected),
        "prologue_shape": prologue_shape.most_common(1)[0][0] if prologue_shape else None,
        "switch_selector": _agreed(switches, "page_selector", rejected),
        "page_chrome": chrome,
        "page_templates": {
            buttons: _agreed(found, f"template_for_{buttons}_buttons", rejected)
            for buttons, found in sorted(templates.items())
        },
        "menu": menu,
        "counts": {
            "command_pages": len(sources),
            "button_positions": len(frames),
            "page_sizes": len(templates),
        },
        "rejected": dict(rejected),
    }


def _shape(instructions: list[dict]) -> tuple:
    """A block's shape: what it draws, ignoring where it lives and what page it is on.

    The page counter's own text is left out, because it is the one thing that differs
    from page to page and is the reason the block is parameterised at all.
    """
    out = []
    for item in instructions:
        skip = {"offset"}
        if item["opcode"] in ("jump", "call"):
            skip.add("target")
        if (item["opcode"] in ("text", "inline_text")
                and item.get("y") == PAGE_NUMBER_XY[1]
                and item.get("x", 0xFF) < PAGE_NUMBER_RIGHT):
            # The counter's own text and its right-aligned x are what change per page.
            skip |= {"target", "glyphs", "x"}
        out.append(tuple((key, item[key]) for key in sorted(item) if key not in skip))
    return tuple(out)


def _page_chrome(payload: bytes, sources: list[dict], rejected: Counter) -> dict | None:
    """Return the softkey and page-counter blocks every command page draws.

    A page ends with a two-way switch: one arm labels the left softkey `Activities`,
    the other `Current Activity`, and both jump to a common tail carrying the `Devices`
    softkey and the page counter. All 28 and 52 command pages in the donors draw the
    identical shape from the identical shared strings, so it is a part of the interface
    rather than of any one screen.
    """
    shapes: Counter = Counter()
    examples: dict[tuple, dict] = {}
    for source in sources:
        program = ui_index.drawing_program(payload, source["program_offset"])
        switch = next(
            (item for item in program["instructions"] if item["opcode"] == "switch"), None)
        if switch is None or switch["ranges"] or len(switch["cases"]) != 2:
            rejected["page_without_a_two_way_switch"] += 1
            continue
        blocks = []
        tails = set()
        for _code, target in switch["cases"]:
            arm = ui_index.drawing_program(payload, target)["instructions"]
            blocks.append(arm)
            tails.update(
                item["target"] for item in arm if item["opcode"] == "jump")
        if len(tails) != 1:
            rejected["page_arms_do_not_share_a_tail"] += 1
            continue
        tail = ui_index.drawing_program(payload, next(iter(tails)))["instructions"]
        key = (tuple(_shape(arm) for arm in blocks), _shape(tail))
        shapes[key] += 1
        examples.setdefault(key, {
            "cases": [code for code, _target in switch["cases"]],
            "arms": blocks, "tail": tail,
        })
    if not shapes:
        return None
    key, agreed = shapes.most_common(1)[0]
    if len(shapes) > 1:
        rejected["page_chrome_disagrees"] += len(shapes) - 1
    chrome = examples[key]
    number = [
        index for index, item in enumerate(chrome["tail"])
        if item["opcode"] in ("text", "inline_text")
        and (item["x"], item["y"]) == PAGE_NUMBER_XY
    ]
    if len(number) != 1:
        rejected["page_tail_without_one_counter"] += 1
        return None
    return {
        "cases": chrome["cases"],
        "arms": chrome["arms"],
        "tail": chrome["tail"],
        "number_instruction": number[0],
        "pages": agreed,
    }


def _menu_parts(payload: bytes, ownership: dict, fonts: dict, rejected: Counter) -> dict:
    menus = ui_index.device_menus(payload, ownership)
    if not menus["menus"]:
        return {"template": None, "row_icons": [], "rows": 0}
    screens = ui_index.screen_slots(payload)
    templates: Counter = Counter()
    icons: Counter = Counter()
    rows = Counter()
    for menu in menus["menus"]:
        for slot in screens[menu["screen"]]["slots"]:
            templates[slot["template"]] += 1
            program = ui_index.drawing_program(payload, slot["program_offset"])
            drawn = menu_rows(payload, slot["program_offset"])
            rows[len(drawn)] += 1
            for row in drawn:
                fonts[MENU_ROW_FONT_ROLE][
                    row_attribute(payload, slot["program_offset"], row)] += 1
                icons[tuple(
                    (program["instructions"][index]["x"],
                     program["instructions"][index]["y"]
                     - ui_index.DEVICE_ROW_CENTERS[row["row"]],
                     program["instructions"][index]["target"])
                    for index in row["frames"])] += 1
    return {
        "template": _agreed(templates, "menu_template", rejected),
        # Row icons belong to the devices that used them; a generated row borrows one
        # rather than drawing an icon this image does not contain.
        "row_icons": [icon for icon, _count in icons.most_common()],
        "rows_per_page": _agreed(rows, "menu_rows_per_page", rejected),
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


def buttons(payload: bytes, program_offset: int) -> list[dict]:
    """Return the labelled buttons a command-screen slot draws, in drawing order.

    A button is a frame bitmap followed by the label instructions that name it. The
    frame's own position and width give the centre the native producer centred on.
    """
    program = ui_index.drawing_program(payload, program_offset)
    out: list[dict] = []
    attributes = []
    for index, item in enumerate(program["instructions"]):
        opcode = item["opcode"]
        if opcode == "switch":
            break
        if opcode == "attribute":
            attributes.append(item["value"])
        elif opcode == "bitmap":
            frame = ui_index._bitmap_resource(payload, item["target"])
            out.append({
                "index": len(out), "x": item["x"], "y": item["y"],
                "width": frame["width"], "height": frame["height"],
                "instruction": index, "labels": [],
            })
        elif opcode in ("text", "inline_text"):
            if not out:
                raise ValueError("this drawing program labels before its first button")
            out[-1]["labels"].append(index)
    if not out:
        raise ValueError("this drawing program draws no button frames")
    if len(attributes) != 1:
        raise ValueError(
            f"this drawing program sets {len(attributes)} font attributes before its "
            "selector; one is required to give every label the same font")
    for button in out:
        button["attribute"] = attributes[0]
    return out


# Device-menu rows are left-aligned at one fixed column rather than centred on a frame,
# and their lines sit 12 pixels apart, centred on the row band. Both donors draw one- and
# two-line rows only; a third line is refused rather than extrapolated.
MENU_LABEL_X = ui_index.DEVICE_LABEL_X


# A paged screen numbers each slot at one fixed spot and states the total in the
# prologue every slot calls. Single-slot screens draw neither. Both donors put these at
# the same coordinates on every screen that has them; the font attribute varies by
# screen and is read from the screen itself.
# The page number is right-aligned so it never runs into the "/" beside it: its right
# edge is 18 on all 28 and 52 command pages of the two broader donors, which is why a
# one-digit "1" sits at 13, a wider "4" at 12 and a two-digit "10" at 8. The prologue's
# total is left-aligned at 23 instead.
PAGE_NUMBER_XY = (13, 18)


PAGE_NUMBER_RIGHT = 18


def menu_rows(payload: bytes, program_offset: int) -> list[dict]:
    """Return the row bands a device-menu slot draws, in drawing order.

    A row is the frame bitmaps that open it plus the label instructions in its band.
    Which band a group belongs to comes from its label, so frames drawn for a row that
    is never labelled are not mistaken for a row.
    """
    program = ui_index.drawing_program(payload, program_offset)
    out: list[dict] = []
    current = None
    for index, item in enumerate(program["instructions"]):
        if item["opcode"] == "switch":
            break
        if item["opcode"] == "bitmap":
            if current is None or current["labels"]:
                current = {"frames": [], "labels": [], "row": None}
                out.append(current)
            current["frames"].append(index)
        elif item["opcode"] in ("text", "inline_text") and item["x"] == MENU_LABEL_X:
            row = ui_index.row_index(item["y"])
            if row is not None and current is not None:
                current["labels"].append(index)
                current["row"] = row
    return [item for item in out if item["labels"] and item["row"] is not None]


def row_attribute(payload: bytes, program_offset: int, row: dict) -> int:
    program = ui_index.drawing_program(payload, program_offset)
    attribute = None
    for index, item in enumerate(program["instructions"]):
        if item["opcode"] == "attribute":
            attribute = item["value"]
        if index == row["labels"][0]:
            break
    if attribute is None:
        raise ValueError("this menu slot sets no font attribute before its row labels")
    return attribute
