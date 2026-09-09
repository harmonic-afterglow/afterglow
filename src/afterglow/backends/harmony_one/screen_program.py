"""Emit the drawing program that names a Harmony One command screen's buttons.

A cloned screen reaches the right commands but draws the labels of the screen it was
copied from. Replacing those labels needs the layout the native producer used, and that
layout is read from the image rather than assumed: each button's own frame bitmap gives
the column centre, and the image's own font gives every glyph's width. Everything the
program does besides labelling - its prologue call, button frames, selector and chrome -
is copied byte for byte, so a rewrite changes only what it was asked to change.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import glyph_codec, gspm, ui_index


# Measured against every button label on both broader donors: label lines sit 11 pixels
# apart, centred 20 pixels below the button frame's top edge, rounded half up.
LABEL_BASELINE = 20
LINE_SPACING = 11
INLINE_TEXT = 0x05


def glyph_widths(payload: bytes, attribute: int) -> dict[int, int]:
    """Return the drawn width of every glyph code in one section-7 font attribute."""
    if isinstance(attribute, bool) or not isinstance(attribute, int):
        raise ValueError("a font attribute must be an integer")
    start, end = gspm.section_ranges(payload)[7]
    count = struct.unpack_from("<H", payload, start)[0]
    if start + 2 + 3 * count > end:
        raise ValueError("section 7 font index exceeds its section")
    if not 0 <= attribute < count:
        raise ValueError(f"the image declares no font attribute {attribute}")
    field = start + 2 + 3 * attribute
    font = int.from_bytes(payload[field:field + 3], "little") - gspm.BASE
    if not 0 <= font + 3 <= len(payload):
        raise ValueError(f"font {attribute} pointer falls outside the image")
    glyphs = struct.unpack_from("<H", payload, font + 1)[0]
    if font + 3 + 3 * glyphs > len(payload):
        raise ValueError(f"font {attribute} glyph index is truncated")
    out = {}
    for index in range(glyphs):
        at = font + 3 + 3 * index
        absolute = int.from_bytes(payload[at:at + 3], "little")
        if absolute:
            out[index + 1] = ui_index._glyph_shape(payload, absolute - gspm.BASE)["width"]
    return out


def drawable(widths: dict[int, int], report: dict) -> str:
    """Return the characters one font attribute can actually draw, in order."""
    return "".join(sorted(
        character for code, character in report["code_to_character"].items()
        if code in widths))


def _encode(line: str, report: dict, widths: dict[int, int]) -> bytes:
    """Encode a label line, refusing characters this font has no glyph for.

    A font indexes the image's repertoire sparsely: it carries only the glyphs the
    labels of that image happen to need. Knowing a character's code is not enough to
    draw it, so the font, not the repertoire, is the limit on a new label.
    """
    glyphs = glyph_codec.encode(line, report)
    missing = sorted({
        report["code_to_character"][code] for code in set(glyphs) - set(widths)
    })
    if missing:
        raise ValueError(
            "this font cannot draw " + ", ".join(repr(item) for item in missing)
            + f"; it draws only {drawable(widths, report)!r}")
    return glyphs


def line_offsets(lines: int) -> list[int]:
    """Return each label line's offset below the button frame's top edge."""
    if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
        raise ValueError("a button label needs at least one line")
    # Held doubled so the half-pixel centre of an even line count stays exact.
    top = 2 * LABEL_BASELINE - (lines - 1) * LINE_SPACING
    return [(top + 2 * index * LINE_SPACING + 1) // 2 for index in range(lines)]


def _instruction_bytes(payload: bytes, program: dict) -> list[bytes]:
    # Slots finish at `end` and the prologues they call finish at `return`; both are
    # single bytes, so either closes a program whose instructions can all be measured.
    if program["stopped"] not in ("end", "return"):
        raise ValueError(
            "a rewritable drawing program must finish at end or return, not "
            + program["stopped"])
    offsets = [item["offset"] for item in program["instructions"]]
    bounds = offsets[1:] + [offsets[-1] + 1]
    return [payload[start:stop] for start, stop in zip(offsets, bounds)]


def _rewrite(payload: bytes, program_offset: int, changes: dict[int, bytes]) -> bytes:
    """Replace whole instructions by index and copy every other one verbatim."""
    bodies = _instruction_bytes(
        payload, ui_index.drawing_program(payload, program_offset))
    for index, body in changes.items():
        bodies[index] = body
    return b"".join(bodies)


def _text_instruction(x: int, y: int, glyphs: bytes) -> bytes:
    return bytes([INLINE_TEXT, x, y]) + glyphs + b"\x00"


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


def _label_instructions(widths: dict[int, int], button: dict, lines: list[bytes]) -> bytes:
    out = bytearray()
    for glyphs, offset in zip(lines, line_offsets(len(lines))):
        width = sum(widths[code] for code in glyphs)
        if width > button["width"]:
            raise ValueError(
                f"a {width} pixel label does not fit the {button['width']} pixel button "
                f"frame at ({button['x']}, {button['y']})")
        if offset >= button["height"]:
            raise ValueError("a label line falls below the button frame")
        x = (2 * button["x"] + button["width"] - width) // 2
        out += _text_instruction(x, button["y"] + offset, glyphs)
    return bytes(out)


def render(payload: bytes, program_offset: int, labels: list, *,
           page_number: int | None = None, call_target: int | None = None) -> bytes:
    """Rebuild a command-screen program with new labels and everything else verbatim.

    ``labels`` gives one entry per button in drawing order, each a string or a sequence
    of lines. Every button must be named: one that fires a new command while still
    drawing the previous device's name is worse than a program this refuses to build.
    """
    drawn = buttons(payload, program_offset)
    if len(labels) != len(drawn):
        raise ValueError(
            f"this screen draws {len(drawn)} buttons and {len(labels)} were named")
    report = glyph_codec.inspect(payload)
    if report.get("error"):
        raise ValueError(report["error"])
    widths = glyph_widths(payload, drawn[0]["attribute"])

    changes = {}
    for button, label in zip(drawn, labels):
        lines = [label] if isinstance(label, str) else list(label)
        if not lines or not all(isinstance(line, str) and line for line in lines):
            raise ValueError("every button label must be one or more non-empty strings")
        if not button["labels"]:
            raise ValueError(
                f"the button frame at ({button['x']}, {button['y']}) draws no label, so "
                "there is no evidence of where its label belongs")
        # The new lines take the place of the first old one, which keeps them after the
        # font attribute the native producer sets between the first frame and its label.
        changes[button["labels"][0]] = _label_instructions(
            widths, button, [_encode(line, report, widths) for line in lines])
        for index in button["labels"][1:]:
            changes[index] = b""
    if page_number is not None:
        changes.update(_counter_change(
            payload, program_offset, PAGE_NUMBER_XY, page_number, report))
    if call_target is not None:
        changes[0] = _call_instruction(payload, program_offset, call_target)
    return _rewrite(payload, program_offset, changes)


def _counter_change(payload: bytes, program_offset: int, position: tuple[int, int],
                    value: int, report: dict) -> dict[int, bytes]:
    counter = page_indicator(payload, program_offset, position, report)
    if counter is None:
        raise ValueError(
            f"this program draws no page counter at {position}, so there is no evidence "
            "of how this screen numbers its pages")
    widths = glyph_widths(payload, counter["attribute"])
    return {counter["instruction"]: _text_instruction(
        *position, _encode(str(value), report, widths))}


def screen_title(payload: bytes, prologue_offset: int,
                 report: dict | None = None) -> str | None:
    """Return the title a prologue draws, or None when it draws none."""
    report = glyph_codec.inspect(payload) if report is None else report
    program = ui_index.drawing_program(payload, prologue_offset)
    drawn = {
        glyph_codec.decode(bytes.fromhex(item["glyphs"]), report)
        for item in program["instructions"]
        if item["opcode"] in ("text", "inline_text")
        and (item["x"], item["y"]) == TITLE_XY
    }
    if not drawn:
        return None
    if len(drawn) > 1:
        raise ValueError(f"this prologue draws {len(drawn)} different titles")
    return next(iter(drawn))


def render_prologue(payload: bytes, prologue_offset: int, *,
                    title: str | None = None, total: int | None = None) -> bytes:
    """Rebuild a prologue with a new title, a new page total, or both.

    Both donors draw the title twice in every prologue that has one, always agreeing,
    so both copies are rewritten together.
    """
    report = glyph_codec.inspect(payload)
    if report.get("error"):
        raise ValueError(report["error"])
    program = ui_index.drawing_program(payload, prologue_offset)
    changes: dict[int, bytes] = {}
    if title is not None:
        attribute = None
        copies = []
        for index, item in enumerate(program["instructions"]):
            if item["opcode"] == "attribute":
                attribute = item["value"]
            elif (item["opcode"] in ("text", "inline_text")
                    and (item["x"], item["y"]) == TITLE_XY):
                copies.append((index, attribute))
        if not copies:
            raise ValueError("this prologue draws no title to replace")
        for index, attribute in copies:
            if attribute is None:
                raise ValueError("a title is drawn before any font attribute is set")
            widths = glyph_widths(payload, attribute)
            glyphs = _encode(title, report, widths)
            width = sum(widths[code] for code in glyphs)
            if TITLE_XY[0] + width > DISPLAY_WIDTH:
                raise ValueError(
                    f"a {width} pixel title runs past the {DISPLAY_WIDTH} pixel display")
            changes[index] = _text_instruction(*TITLE_XY, glyphs)
    if total is not None:
        changes.update(_counter_change(
            payload, prologue_offset, PAGE_TOTAL_XY, total, report))
    return _rewrite(payload, prologue_offset, changes)


def key_button_order(payload: bytes, template: int, key_codes) -> list[int]:
    """Order key codes the way the slot's touch zones are read on screen.

    Key registers do not store their entries in reading order, so the key a label
    belongs to is established through section-19 geometry: content zones sort by
    descending Y then ascending X, which is the order the frames are drawn in.
    """
    zones = ui_index.touch_templates(payload).get(template)
    if zones is None:
        raise ValueError(f"section 19 declares no touch template {template}")
    positions = {
        zone["key_code"]: (-zone["y"], zone["x"])
        for zone in zones if zone["tag"] not in ui_index.SIDE_STRIP_TAGS
    }
    missing = sorted(set(key_codes) - set(positions))
    if missing:
        raise ValueError(
            f"touch template {template} has no content zone for key "
            + ", ".join(f"{code:#04x}" for code in missing))
    return sorted(key_codes, key=lambda code: positions[code])


def labelled(payload: bytes, program_offset: int, report: dict | None = None) -> list[list[str]]:
    """Return the label lines each button currently draws, in drawing order."""
    report = glyph_codec.inspect(payload) if report is None else report
    program = ui_index.drawing_program(payload, program_offset)
    return [
        [glyph_codec.decode(
            bytes.fromhex(program["instructions"][index]["glyphs"]), report)
         for index in button["labels"]]
        for button in buttons(payload, program_offset)
    ]


# Device-menu rows are left-aligned at one fixed column rather than centred on a frame,
# and their lines sit 12 pixels apart, centred on the row band. Both donors draw one- and
# two-line rows only; a third line is refused rather than extrapolated.
MENU_LABEL_X = ui_index.DEVICE_LABEL_X
MENU_LINE_SPACING = 12
MENU_MAX_LINES = 2
# The width the drawing reader already enforces on a glyph or bitmap row.
DISPLAY_WIDTH = 176


def menu_line_offsets(lines: int) -> list[int]:
    """Return each menu-row line's offset from the centre of its row band."""
    if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
        raise ValueError("a menu row needs at least one line")
    if lines > MENU_MAX_LINES:
        raise ValueError(
            f"no donor draws a {lines} line device-menu row; at most "
            f"{MENU_MAX_LINES} are established")
    top = -(lines - 1) * MENU_LINE_SPACING
    return [(top + 2 * index * MENU_LINE_SPACING) // 2 for index in range(lines)]


def _menu_row_instructions(program: dict, row: int) -> tuple[list[int], int | None]:
    found = []
    attribute = None
    seen = None
    for index, item in enumerate(program["instructions"]):
        if item["opcode"] == "attribute":
            seen = item["value"]
        elif (item["opcode"] in ("text", "inline_text")
                and item["x"] == MENU_LABEL_X
                and ui_index.row_index(item["y"]) == row):
            found.append(index)
            if attribute is None:
                attribute = seen
    return found, attribute


def menu_row_labels(payload: bytes, program_offset: int,
                    report: dict | None = None) -> dict[int, list[str]]:
    """Return the label lines each device-menu row of one slot draws."""
    report = glyph_codec.inspect(payload) if report is None else report
    program = ui_index.drawing_program(payload, program_offset)
    out = {}
    for row in range(len(ui_index.DEVICE_ROW_CENTERS)):
        found, _attribute = _menu_row_instructions(program, row)
        if found:
            out[row] = [
                glyph_codec.decode(
                    bytes.fromhex(program["instructions"][index]["glyphs"]), report)
                for index in found
            ]
    return out


def render_menu_row(payload: bytes, program_offset: int, row: int, label) -> bytes:
    """Rebuild a device-menu slot's program with one row renamed, the rest verbatim."""
    lines = [label] if isinstance(label, str) else list(label)
    if not lines or not all(isinstance(line, str) and line for line in lines):
        raise ValueError("a menu row label must be one or more non-empty strings")
    report = glyph_codec.inspect(payload)
    if report.get("error"):
        raise ValueError(report["error"])

    program = ui_index.drawing_program(payload, program_offset)
    found, attribute = _menu_row_instructions(program, row)
    if not found:
        raise ValueError(
            f"this menu slot draws no label in row {row}, so there is no evidence of "
            "where one belongs")
    if attribute is None:
        raise ValueError("this menu slot sets no font attribute before its row labels")
    widths = glyph_widths(payload, attribute)

    centre = ui_index.DEVICE_ROW_CENTERS[row]
    drawn = bytearray()
    for line, offset in zip(lines, menu_line_offsets(len(lines))):
        glyphs = _encode(line, report, widths)
        width = sum(widths[code] for code in glyphs)
        if MENU_LABEL_X + width > DISPLAY_WIDTH:
            raise ValueError(
                f"a {width} pixel row label runs past the {DISPLAY_WIDTH} pixel display")
        drawn += _text_instruction(MENU_LABEL_X, centre + offset, glyphs)

    changes = {found[0]: bytes(drawn)}
    for index in found[1:]:
        changes[index] = b""
    return _rewrite(payload, program_offset, changes)


# A paged screen numbers each slot at one fixed spot and states the total in the
# prologue every slot calls. Single-slot screens draw neither. Both donors put these at
# the same coordinates on every screen that has them; the font attribute varies by
# screen and is read from the screen itself.
PAGE_NUMBER_XY = (13, 18)
PAGE_TOTAL_XY = (23, 18)
# Both donors draw a screen's title here, twice per prologue and always agreeing.
TITLE_XY = (6, 4)


def _fixed_text(program: dict, position: tuple[int, int]) -> tuple[int, int] | None:
    attribute = None
    for index, item in enumerate(program["instructions"]):
        if item["opcode"] == "attribute":
            attribute = item["value"]
        elif (item["opcode"] in ("text", "inline_text")
                and (item["x"], item["y"]) == position):
            return index, attribute
    return None


def page_indicator(payload: bytes, program_offset: int, position: tuple[int, int],
                   report: dict | None = None) -> dict | None:
    """Return the counter drawn at ``position``, or None when the screen draws none."""
    program = ui_index.drawing_program(payload, program_offset)
    found = _fixed_text(program, position)
    if found is None:
        return None
    index, attribute = found
    if attribute is None:
        raise ValueError("a page counter is drawn before any font attribute is set")
    report = glyph_codec.inspect(payload) if report is None else report
    return {
        "instruction": index,
        "attribute": attribute,
        "text": glyph_codec.decode(
            bytes.fromhex(program["instructions"][index]["glyphs"]), report),
    }


def render_page_counter(payload: bytes, program_offset: int,
                        position: tuple[int, int], value: int) -> bytes:
    """Rebuild a program with one page counter renumbered and the rest verbatim."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("a page counter counts from one")
    counter = page_indicator(payload, program_offset, position)
    if counter is None:
        raise ValueError(
            f"this program draws no page counter at {position}, so there is no evidence "
            "of how this screen numbers its pages")
    report = glyph_codec.inspect(payload)
    widths = glyph_widths(payload, counter["attribute"])
    glyphs = _encode(str(value), report, widths)
    return _rewrite(payload, program_offset, {
        counter["instruction"]: _text_instruction(*position, glyphs),
    })


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


def render_menu_page(payload: bytes, program_offset: int, labels: dict[int, object], *,
                     page_number: int | None = None,
                     call_target: int | None = None) -> bytes:
    """Rebuild a menu slot drawing exactly the rows named, in band order.

    A band the slot does not draw today is given the frames of a row it does, moved by
    the distance between the two band centres, so the new row carries another device's
    icon in the right place - both donors draw every one of their 102 rows with its
    frames at the same offsets from its band centre, and every page in band order; a band that is named no longer is dropped whole,
    frames included, so a page never shows a device frame with no name under it. Every
    instruction outside the row band and the page counter is copied verbatim.
    """
    rows = menu_rows(payload, program_offset)
    if not rows:
        raise ValueError("this program draws no device-menu rows to rebuild")
    if not labels:
        raise ValueError("a device-menu page must keep at least one row")
    bands = sorted(labels)
    if bands[0] < 0 or bands[-1] >= len(ui_index.DEVICE_ROW_CENTERS):
        raise ValueError(
            f"a device menu draws {len(ui_index.DEVICE_ROW_CENTERS)} row bands")
    report = glyph_codec.inspect(payload)
    if report.get("error"):
        raise ValueError(report["error"])

    program = ui_index.drawing_program(payload, program_offset)
    by_band = {row["row"]: row for row in rows}
    attribute = _row_attribute(payload, program_offset, rows[0])
    widths = glyph_widths(payload, attribute)
    body = bytearray()
    for position, band in enumerate(bands):
        centre = ui_index.DEVICE_ROW_CENTERS[band]
        source = by_band.get(band, rows[0])
        origin = ui_index.DEVICE_ROW_CENTERS[source["row"]]
        for index in source["frames"]:
            instruction = program["instructions"][index]
            body += (b"\x02"
                     + bytes([instruction["x"], centre + instruction["y"] - origin])
                     + (gspm.BASE + instruction["target"]).to_bytes(3, "little"))
        if not position:
            body += bytes([0x10, attribute])
        label = labels[band]
        lines = [label] if isinstance(label, str) else list(label)
        if not lines or not all(isinstance(line, str) and line for line in lines):
            raise ValueError("a menu row label must be one or more non-empty strings")
        for line, offset in zip(lines, menu_line_offsets(len(lines))):
            glyphs = _encode(line, report, widths)
            width = sum(widths[code] for code in glyphs)
            if MENU_LABEL_X + width > DISPLAY_WIDTH:
                raise ValueError(
                    f"a {width} pixel row label runs past the {DISPLAY_WIDTH} pixel "
                    "display")
            body += _text_instruction(MENU_LABEL_X, centre + offset, glyphs)

    region = sorted(
        {index for row in rows for index in row["frames"] + row["labels"]}
        | {index for index, item in enumerate(program["instructions"])
           if item["opcode"] == "attribute" and index < rows[-1]["labels"][-1]})
    changes = {index: b"" for index in region}
    changes[region[0]] = bytes(body)
    if page_number is not None:
        changes.update(_counter_change(
            payload, program_offset, PAGE_NUMBER_XY, page_number, report))
    if call_target is not None:
        changes[0] = _call_instruction(payload, program_offset, call_target)
    return _rewrite(payload, program_offset, changes)


def _row_attribute(payload: bytes, program_offset: int, row: dict) -> int:
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


def _call_instruction(payload: bytes, program_offset: int, target: int) -> bytes:
    program = ui_index.drawing_program(payload, program_offset)
    if not program["instructions"] or program["instructions"][0]["opcode"] != "call":
        raise ValueError("this slot program does not open with a prologue call")
    absolute = gspm.BASE + target
    if target < 0 or absolute >= 1 << 24:
        raise ValueError("a prologue pointer does not fit in 24 bits")
    return b"\x16" + absolute.to_bytes(3, "little")



def render_call(payload: bytes, program_offset: int, target: int) -> bytes:
    """Rebuild a slot program calling a different prologue, everything else verbatim."""
    return _rewrite(payload, program_offset, {
        0: _call_instruction(payload, program_offset, target),
    })
