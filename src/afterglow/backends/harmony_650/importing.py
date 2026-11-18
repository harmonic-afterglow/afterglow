"""A Harmony One configuration read back as a project: what its devices and activities do.

Logitech's configurations and this backend's are built from the same parts, so they are
read the same way. A device's commands are named by the buttons that send them, its name
is its pages' title, and its power and inputs are the state variables section 0 names
(`<Label>_Power_2`, `<Label>_Input_<n>`), whose section-14 transitions send what changing
them takes. Objects are followed through to what they do: send a command, wait before a
device's next send, write a variable.

Text is read by the shape of its glyphs (labels.py). Logitech's builder splits a long
command name across a button's two lines without a space where the name has none -
"Power" over "Toggle" is PowerToggle - and this backend wraps at spaces, so the lines are
joined the way the image's own builder split them.

What cannot be read is not guessed: a command no button names keeps a numbered name.

Format reference: docs/harmony_650_700/gspm.md, docs/harmony_one/README.md
"""

from __future__ import annotations

import re
import struct
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from . import (
    activity_index, catalogue, command_index, gspm, ir_lowering, keys, labels, named_index,
    ui_index)

SEND, WAIT, WRITE, MODE, CONTEXT, SWITCH = "send", "wait", "write", "mode", "context", "switch"
OBJECT, COMMAND, DEVICE_OR_WAIT, ENTER_MODE = 0x7F, 0x7D, 0x7C, 0x7E
# A number into the accumulator, and the `1F` band that hands it to the number sender
LOAD_NUMBER, DIAL = 0x7A, 0xF3
SILENT = (0xFFFF, 0x07)          # the next write fires no transition
TESTS = (0x70, 0x71)
# A 650 page is four labels, one in each corner of the screen beside the key that
# presses it: top-left, top-right, bottom-left, bottom-right. A label's lines sit left of
# CORNER_SPLIT_X or right of it, above CORNER_SPLIT_Y or below it, between the title strip
# and the softkey (docs/harmony_650_700/gspm.md, "Pages").
CORNER_KEYS = tuple(keys.code(keys.SCREEN_KEYS[corner]) for corner in (
    "top-left", "top-right", "bottom-left", "bottom-right"))
CORNER_SPLIT_X, CORNER_SPLIT_Y = 40, 60
LABELS_TOP, LABELS_BOTTOM = 20, 108
TITLE_XY = (0, 2)
POWER_NAME = re.compile(r"^(?P<label>.+)_Power_2$")
INPUT_NAME = re.compile(r"^(?P<label>.+)_Input_(?P<count>\d+)$")
# Whether a smart TV's apps are up: Logitech's `<Label>_OnlinePower_2`, which a timer
# started at power-on sets after the apps' delay, and ours, `<Label>_Online_2`, which the
# first app after power-on sets after waiting the rest of that delay
# (devices.device_state_records).
ONLINE_NAME = re.compile(r"^(?P<label>.+)_Online(?P<power>Power)?_2$")
# A device's other states, as Logitech's database declares them beside power and input -
# `TV_Screen_8`, `TV_TVInput_3` on a Dutch 650's television - which its input writes:
# `<Label>_<state>_<values>`, the label a device's power or input variable has.
STATE_NAME = re.compile(r"^(?P<label>.+)_(?P<state>[A-Za-z][A-Za-z0-9]*)_(?P<count>\d+)$")
NOT_STATES = ("Power", "Input", "Online", "OnlinePower")
SET = "set"
# A transition taken from any value, as direct inputs have them.
ANY = (activity_index.ANY_STATE, 0xFFFD)


class Image:
    """One image's parts, read once: its objects, variables, screens and text."""

    def __init__(self, payload: bytes):
        self.payload = payload
        # A part that cannot be read is read as having nothing in it, and named: the
        # rest of the image still says what it can.
        self.unreadable: list[str] = []

        def part(name, read, empty):
            try:
                return read(payload)
            except (ValueError, IndexError, KeyError, struct.error) as exc:
                self.unreadable.append(f"{name}: {exc}")
                return empty
        self.objects = part("objects", command_index.objects, [])
        self.engine = part("state variables", activity_index.engine_records, [])
        records = part("names", lambda data: named_index.inspect(data)["records"], [])
        self.names = {record["id"]: record["name"] for record in records
                      if record.get("type") == 1 and record.get("name")}
        self.screens = part("screens", ui_index.screen_slots, [])
        self.text = part("text", labels.Text, None) or labels.Text.empty()
        self.groups = part("switch tables", switch_tables, [])
        self.templates = part("touch templates", ui_index.touch_templates, {})
        self.contexts = part("contexts", activity_index.contexts, [])
        self.number_senders = part("number senders", number_senders, [])
        # The variables a Logitech favourite writes: one whose transitions dial a number
        # through the number sender (`1F F3`), so writing it is the channel being sent.
        self.channel_variables = {
            index for index, record in enumerate(self.engine)
            if any(item["category"] == OBJECT and self._dials(item["operand"])
                   for item in record["transitions"])}

    def steps(self, index: int, depth: int = 12) -> list[tuple]:
        """What running object ``index`` always does, its nested objects followed:
        ``(send, command id, repeats)``, ``(wait, device, ms)``, ``(write, variable,
        value)``, ``(mode, ordinal)``, ``(context, ordinal)``, ``(switch, operand)``.
        An instruction a test guards is left out."""
        if depth < 0 or not 0 <= index < len(self.objects):
            return []
        atoms = self.objects[index]["atoms"]
        # a command object: the command, and its device with a repeat count
        if any(opcode == COMMAND for _operand, opcode in atoms):
            command = next(operand for operand, opcode in atoms if opcode == COMMAND)
            repeats = next((operand & 0xFF for operand, opcode in atoms
                            if opcode == DEVICE_OR_WAIT), 1)
            return [(SEND, command, repeats)]
        out = []
        guarded = False
        accumulator, silent = 0, False
        for operand, opcode in atoms:
            # a test decides whether the next instruction runs: what it guards is not
            # something the object always does
            if guarded:
                guarded = False
                continue
            if opcode in TESTS:
                guarded = True
                continue
            if opcode == LOAD_NUMBER:
                accumulator = operand
            elif opcode == 0x1F and operand >> 8 == DIAL:
                out += self.dial(accumulator, operand & 0xFF, depth)
            if (operand, opcode) == SILENT:
                silent = True
                continue
            if silent and opcode >= 0x80:      # a silent write fires no transition
                out.append((WRITE, opcode & 0x7F, operand))
            else:
                out += self.atom(operand, opcode, depth)
            silent = False
        return out

    def _dials(self, index: int, depth: int = 6) -> bool:
        """Whether object ``index`` runs the number sender, itself or in what it calls."""
        if depth < 0 or not 0 <= index < len(self.objects):
            return False
        return any((opcode == 0x1F and operand >> 8 == DIAL)
                   or (opcode == OBJECT and self._dials(operand, depth - 1))
                   for operand, opcode in self.objects[index]["atoms"])

    def dial(self, value: int, record: int, depth: int = 12) -> list[tuple]:
        """What the number sender sends for ``value`` with record ``record``, as the
        firmware runs it (Danny Bloe's harmony-explorations, config-format/state.md, "the
        number sender"): the base added, the digits at least ``minimum`` of them, the
        first instruction, the prefix once the number is long enough, a digit table per
        place - the first digit of several the first table, the last the last, the rest
        the middle one - and the last instruction."""
        if not 0 <= record < len(self.number_senders):
            return []
        sender = self.number_senders[record]
        digits = str(value + sender["base"]).zfill(sender["minimum"])
        flags = sender["flags"]
        threshold = 100 if flags & 4 else 10 if flags & 2 else 10000
        atoms = [sender["first"]]
        if value + sender["base"] >= threshold:
            atoms.append(sender["prefix"])
        for place, digit in enumerate(digits):
            table = (2 if place == len(digits) - 1 else 0 if place == 0 else 1)
            atoms.append(sender["tables"][table][int(digit)])
        atoms.append(sender["last"])
        out = []
        for atom in atoms:
            if atom is not None:
                out += self.atom(*atom, depth)
        return out

    def row(self, entry: dict) -> list[tuple]:
        """What a key register's or a context's row does: its own instruction, which is
        most often an object to run."""
        return self.atom(entry["operand"], entry["category"])

    def atom(self, operand: int, opcode: int, depth: int = 12) -> list[tuple]:
        if opcode == OBJECT:
            return self.steps(operand, depth - 1)
        if opcode == DEVICE_OR_WAIT:
            return [(WAIT, operand >> 8, (operand & 0xFF) * 100)]
        if opcode >= 0x80:
            variable = opcode & 0x7F
            write = [(WRITE, variable, operand)]
            # a favourite's channel: writing the variable dials it, so what its transition
            # sends is what the write does
            if variable in self.channel_variables:
                for item in self.engine[variable]["transitions"]:
                    if item["to"] == operand and item["category"] == OBJECT:
                        return write + self.steps(item["operand"], depth - 1)
            return write
        if opcode == ENTER_MODE:
            return [(MODE, operand)]
        if opcode == 0x1F and operand >> 8 == 0xFF:
            return [(CONTEXT, operand & 0xFF)]
        if opcode == 0x72:
            return [(SWITCH, operand)]
        return []

    def switch_targets(self, group: int) -> dict[int, list[int]]:
        """What a section-15 switch table opens for each value it switches on: the screens
        its case's drawing block enters, by value."""
        out = {}
        for value, block in self.groups[group]["cases"] if group < len(self.groups) else ():
            try:
                instructions = ui_index.drawing_program(self.payload, block)["instructions"]
            except ValueError:
                continue
            out[value] = [item["operand"] for item in instructions
                          if item["opcode"] == "atom" and item["category"] == ENTER_MODE]
        return out

    def page_text(self, program: int) -> list[dict]:
        try:
            return labels.screen_text(self.payload, program, self.text)
        except ValueError:
            return []

    def join(self, lines: list[str], words: bool = False) -> str:
        """A label's lines as the name they were split from. With ``words`` - a device's or
        an activity's name, on the Devices list or the Activities menu - the lines are
        words: "Sony" over "PS4" is "Sony PS4", where a command's "Power" over "Toggle"
        is "PowerToggle"."""
        if words:
            return " ".join(lines)
        out = ""
        for line in lines:
            if not out:
                out = line
            # a name broken where its words meet - "Power" over "Toggle" - as Logitech's
            # 700 pages and this backend's both draw one
            elif out[-1:].isalnum() and line[:1].isupper() and " " not in line \
                    and " " not in out:
                out += line
            else:
                out += " " + line
        return out


def number_senders(payload: bytes) -> list[dict]:
    """Section 17: how a favourite's number becomes digit codes, one record per device that
    takes a number - a count and a pointer per record, each record its flags, a base
    added to the number, a minimum of digits, the instructions sent first, last and as a
    prefix, and three tables of ten, the instruction per digit for the first, middle and
    last place. As Danny Bloe's harmony-explorations has it (config-format/state.md, "Base
    slot 16: the number sender", there numbered from 0); a zero instruction is none."""
    start, end = gspm.section_ranges(payload)[17]
    count = payload[start]
    if start + 1 + 3 * count > end:
        raise ValueError("section 17's pointers run past its end")

    def instruction(at):
        operand, opcode = struct.unpack_from("<HB", payload, at)
        return None if not (operand or opcode) else (operand, opcode)

    def pointer(at):
        return int.from_bytes(payload[at:at + 3], "little") - gspm.BASE
    out = []
    for index in range(count):
        at = pointer(start + 1 + 3 * index)
        if not 0 <= at <= len(payload) - 23:
            raise ValueError(f"number sender {index} lies outside the image")
        tables = []
        for field in (14, 17, 20):
            table = pointer(at + field)
            if not 0 <= table <= len(payload) - 30:
                raise ValueError(f"number sender {index}'s digit table lies outside the image")
            tables.append([instruction(table + 3 * digit) for digit in range(10)])
        out.append({"flags": payload[at], "base": int.from_bytes(payload[at + 1:at + 4], "little"),
                    "minimum": payload[at + 4], "first": instruction(at + 5),
                    "last": instruction(at + 8), "prefix": instruction(at + 11),
                    "tables": tables})
    return out


def switch_tables(payload: bytes) -> list[dict]:
    """Section 15's switch tables: ``{cases: [(value, block)], ranges: [(low, high,
    block)]}``, in table order, as a `0x72` instruction numbers them."""
    start, end = gspm.section_ranges(payload)[15]
    count = payload[start]
    out = []
    for index in range(count):
        at = int.from_bytes(payload[start + 1 + 3 * index:start + 4 + 3 * index],
                            "little") - gspm.BASE
        if not 0 <= at < len(payload) - 2:
            out.append({"cases": [], "ranges": []})
            continue
        # an arch-14 table counts its cases in a u16 after a 2 (docs/harmony_650_700/gspm.md,
        # "Switch tables")
        cases, cursor = [], at + 3
        for _case in range(struct.unpack_from("<H", payload, at + 1)[0]):
            value = struct.unpack_from("<H", payload, cursor)[0]
            block = int.from_bytes(payload[cursor + 2:cursor + 5], "little") - gspm.BASE
            cases.append((value, block))
            cursor += 5
        ranges = []
        for _range in range(payload[cursor]):
            low, high = struct.unpack_from("<HH", payload, cursor + 1)
            block = int.from_bytes(payload[cursor + 5:cursor + 8], "little") - gspm.BASE
            ranges.append((low, high, block))
            cursor += 7
        out.append({"cases": cases, "ranges": ranges})
    return out


def _button_label(items: list[dict], slot: int) -> list[str] | None:
    """The text drawn in corner ``slot`` (0 top-left, 1 top-right, 2 bottom-left,
    3 bottom-right), top line first."""
    return _corner_lines(items, (slot,))


def _corner_lines(items: list[dict], corners) -> list[str] | None:
    """The text drawn in any of ``corners``, top line first."""
    found = [item for corner in sorted(corners)
             for item in _corner_items(items, corner)]
    return [item["text"] for item in sorted(found, key=lambda item: item["y"])] or None


def _corner_items(items: list[dict], slot: int) -> list[dict]:
    right, bottom = slot % 2, slot // 2
    return [item for item in items
            if LABELS_TOP <= item["y"] < LABELS_BOTTOM
            and (item["x"] >= CORNER_SPLIT_X) == bool(right)
            and (item["y"] >= CORNER_SPLIT_Y) == bool(bottom)]


def button_positions(image: Image, slot: dict) -> dict[int, int]:
    """Which corner each of the keys beside the screen labels: the same four on every
    page, wherever the page draws its labels."""
    return {key: position for position, key in enumerate(CORNER_KEYS)}


def _touch_sends(image: Image, slot: dict) -> dict[int, int] | None:
    """A slot's buttons as ``{position: command id}`` when each button that sends sends
    one command of one device and does nothing else - a command page's shape; None
    otherwise. A zone that sends nothing - a switch, a navigation - is no button."""
    out = {}
    places = button_positions(image, slot)
    for entry in slot["entries"]:
        position = places.get(entry["key_code"])
        if position is None or entry["category"] != OBJECT:
            continue
        steps = image.steps(entry["operand"])
        if not any(step[0] == SEND for step in steps):
            continue
        if len(steps) != 1:
            return None
        out[position] = steps[0][1]
    if not out or len({command >> 8 for command in out.values()}) != 1:
        return None
    return out


def _navigation(image: Image, entry: dict) -> int | None:
    """The screen a row opens, when it opens one and sends nothing: Logitech's menu rows
    also write a variable of their own as they go."""
    if entry["category"] != OBJECT:
        return None
    steps = image.steps(entry["operand"])
    modes = [step[1] for step in steps if step[0] == MODE]
    if len(modes) != 1 or any(step[0] == SEND for step in steps):
        return None
    return modes[0]


SIDE_STRIPS = (keys.code(keys.PAGE_LEFT), keys.code(keys.PAGE_RIGHT))


def command_pages(image: Image) -> dict[int, list[int]]:
    """Each device's command pages, by device index: the screens another screen opens -
    its device-menu row - and those their side strips turn to, every one showing that
    device's commands only. A screen that also sends another device's - an activity's -
    is not one, nor one an activity starts on, though it send one device's alone: a
    Polish 600's "Telewizja", which a build's help answers return to."""
    started = {step[1] for context in image.contexts for row in context["rows"]
               if row["key_code"] == activity_index.ENTER
               for step in image.row(row) if step[0] == MODE}
    shape = {}
    for screen in image.screens:
        if screen["ordinal"] in started:
            continue
        sends = [_touch_sends(image, slot) for slot in screen["slots"]]
        if sends and all(sends):
            devices = {command >> 8 for item in sends for command in item.values()}
            if len(devices) == 1:
                shape[screen["ordinal"]] = devices.pop()
    out: dict[int, list[int]] = defaultdict(list)
    queue = []
    for screen in image.screens:
        for slot in screen["slots"]:
            for entry in slot["entries"]:
                if screen["ordinal"] not in shape:
                    target = _navigation(image, entry)
                    if target in shape:
                        queue.append(target)
    seen = set()
    while queue:
        ordinal = queue.pop(0)
        if ordinal in seen or ordinal >= len(image.screens):
            continue
        seen.add(ordinal)
        out[shape[ordinal]].append(ordinal)
        for slot in image.screens[ordinal]["slots"]:
            for entry in slot["entries"]:
                if entry["key_code"] in SIDE_STRIPS:
                    target = _navigation(image, entry)
                    if target in shape and shape[target] == shape[ordinal]:
                        queue.append(target)
    return {device: sorted(pages) for device, pages in out.items()}


def device_lists(image: Image) -> list[list[tuple[int, list[str] | None]]]:
    """Every Devices list: each row's opened page and its label's lines, page by page and
    corner by corner. Logitech draws one per activity, each in its own order."""
    places = {key: position for position, key in enumerate(CORNER_KEYS)}
    out = []
    for screen in image.screens:
        rows = []
        for slot in screen["slots"]:
            items = image.page_text(slot["program_offset"])
            if not any((item["x"], item["y"]) == TITLE_XY
                       and item["text"] in catalogue.every("devices.title")
                       for item in items) and not slot["entries"]:
                continue
            for position, entry in sorted((places[entry["key_code"]], entry)
                                          for entry in slot["entries"]
                                          if entry["key_code"] in places):
                opened = _navigation(image, entry)
                if opened is not None and all(opened != seen for seen, _ in rows):
                    rows.append((opened, _corner_lines(items, (position,))))
        if rows:
            out.append(rows)
    return out


def device_list_order(image: Image) -> tuple[list[int], dict[int, str]]:
    """The devices in the order the Devices list shows them, and the label of each device
    with no page of commands - a Wii, which Logitech lists with nothing to send - by the
    list whose rows open the most devices' pages. A row opens any of a device's pages:
    Logitech's lists open a television's second as often as its first."""
    pages = command_pages(image)
    owner = {ordinal: device for device, ordinals in pages.items() for ordinal in ordinals}
    best_order, best_rows = [], []
    for rows in device_lists(image):
        order = []
        for opened, _lines in rows:
            if opened in owner and owner[opened] not in order:
                order.append(owner[opened])
        if len(order) > len(best_order):
            best_order, best_rows = order, rows
    # A row opening a page of no device's is the one device with no pages, when there is
    # exactly one of each: its place and its label.
    unknown = [(opened, lines) for opened, lines in best_rows if opened not in owner]
    without = [device for device in range(_device_count(image)) if device not in pages]
    labels = {}
    if len(unknown) == 1 and len(without) == 1:
        (opened, lines), device = unknown[0], without[0]
        at = [opened for opened, _lines in best_rows].index(opened)
        best_order.insert(sum(1 for item, _ in best_rows[:at] if item in owner), device)
        if lines:
            labels[device] = image.join(lines, words=True)
    return best_order, labels


def device_row_labels(image: Image) -> dict[int, str]:
    """Each device's name as the Devices list shows it, by device index: what a page
    title cut short - "Flirc Media Pla.." - is the whole of."""
    pages = command_pages(image)
    owner = {ordinal: device for device, ordinals in pages.items() for ordinal in ordinals}
    out = {}
    for rows in device_lists(image):
        for opened, lines in rows:
            if opened in owner and lines:
                out.setdefault(owner[opened], image.join(lines, words=True))
    return out


def _same_title(title: str, label: str) -> bool:
    """Whether a page's title is ``label``, perhaps cut short to fit - which Logitech
    marks with "..": a title that is whole is that label only, so "Watch Smarthub" is not
    "Watch Smarthub Stereo"."""
    if not title.endswith(".."):
        return label == title
    title = title.removesuffix("..")
    return label == title or (title != "" and label.startswith(title) and len(title) >= 4)


def read_pages(image: Image, labels: dict[int, str] | None = None) -> dict[int, dict]:
    """Each device's command pages read: its title, each command's label, and the
    physical keys its pages bind, by device index. Given the devices' ``labels``, a page
    titled otherwise - an activity's page showing one device's buttons - is not the
    device's."""
    labels = labels or {}
    out = {}
    for device, ordinals in command_pages(image).items():
        titles, names, bound = [], {}, {}
        for ordinal in ordinals:
            screen = image.screens[ordinal]
            titled = [item["text"] for slot in screen["slots"]
                      for item in image.page_text(slot["program_offset"])
                      if (item["x"], item["y"]) == TITLE_XY]
            if device in labels and titled and not any(
                    _same_title(title, labels[device]) for title in titled):
                continue
            for slot in screen["slots"]:
                items = image.page_text(slot["program_offset"])
                titles += [item["text"] for item in items if (item["x"], item["y"]) == TITLE_XY]
                # in the order the pages show them: page by page, corner by corner
                for position, command in sorted((_touch_sends(image, slot) or {}).items()):
                    lines = _button_label(items, position)
                    if lines:
                        names.setdefault(command, image.join(lines))
            for entry in screen["header_entries"] + [
                    entry for slot in screen["slots"] for entry in slot["entries"]]:
                name = keys.name_of(entry["key_code"])
                if name is None or entry["category"] != OBJECT:
                    continue
                sends = [step for step in image.steps(entry["operand"]) if step[0] == SEND]
                if len(sends) == 1 and sends[0][1] >> 8 == device:
                    bound.setdefault(name, sends[0][1])
        out[device] = {"title": max(dict.fromkeys(titles), key=titles.count) if titles else None,
                       "names": names, "keys": bound}
    return out


def _variable_device(transitions, image: Image) -> int | None:
    """The device a state variable drives: the one its transitions send to."""
    devices = {step[1] >> 8 for item in transitions if item["category"] == OBJECT
               for step in image.steps(item["operand"]) if step[0] == SEND}
    return devices.pop() if len(devices) == 1 else None


def device_variables(image: Image) -> list[tuple[dict, int, str]]:
    """Each device's named state variables: ``(record, device index, "power" or
    "input")``. A variable that sends nothing - inputs no command selects - belongs to
    the device whose other variable has its label."""
    found, by_label, pending = [], {}, []
    for record in image.engine:
        name = image.names.get(record["property_id"])
        if not name:
            continue
        power, inputs = POWER_NAME.match(name), INPUT_NAME.match(name)
        if not (power or inputs):
            continue
        label = (power or inputs)["label"]
        kind = "power" if power else "input"
        device = _variable_device(record["transitions"], image)
        if device is None:
            pending.append((record, label, kind))
            continue
        by_label[label] = device
        found.append((record, device, kind))
    found += [(record, by_label[label], kind) for record, label, kind in pending
              if label in by_label]
    # the device's other states: named with a label one of its power or input has
    for record in image.engine:
        name = image.names.get(record["property_id"]) or ""
        match = STATE_NAME.match(name)
        if (match and match["label"] in by_label and match["state"] not in NOT_STATES
                and int(match["count"]) == record["limit"] + 1):
            found.append((record, by_label[match["label"]], f"state:{match['state']}"))
    return found


def timers(payload: bytes) -> list[tuple[int, int, int]]:
    """Section 13's timers: ``(seconds, operand, opcode)`` each, by number."""
    start = gspm.section_ranges(payload)[13][0]
    out = []
    for number in range(payload[start]):
        at = int.from_bytes(payload[start + 1 + 3 * number:start + 4 + 3 * number],
                            "little") - gspm.BASE
        out.append((int.from_bytes(payload[at + 1:at + 4], "little"),
                    int.from_bytes(payload[at + 4:at + 6], "little"), payload[at + 6]))
    return out


# MyHarmony's remote settings, in the wiring (gspm.md, "Remote settings"): how long the
# screen stays lit is the duration of the first timer whose list opens `1F E910`; the
# tilt sensor is armed by `3F F101`, which a configuration with it off never runs
GLOW_START, TILT_ON = (0xE910, 0x1F), (0xF101, 0x3F)


def remote_settings(image: Image) -> dict[str, str]:
    """The screen's lit time (``backlight``, seconds) and whether picking the remote up
    wakes it (``tilt``), as a project's settings hold them."""
    out = {}
    try:
        timer_list = timers(image.payload)
    except (KeyError, ValueError, IndexError):
        timer_list = []
    for seconds, operand, opcode in timer_list:
        atoms = image.objects[operand]["atoms"] if opcode == OBJECT \
            and 0 <= operand < len(image.objects) else []
        if tuple(atoms[:1]) == (GLOW_START,):
            out["backlight_timeout"] = str(seconds)
            break
    if image.objects:
        out["tilt"] = "on" if any(TILT_ON in item["atoms"] for item in image.objects) \
            else "off"
    # the Remote Assistant: on when a start can go to its note (gspm.md, "Remote
    # Assistant"); Logitech's compiles with it off hold none
    if image.screens:
        titles = catalogue.every("assistant.title")
        out["remote_assistant"] = any(
            item["text"] in titles for screen in image.screens
            for slot in screen["slots"] for item in image.page_text(slot["program_offset"]))
    language = drawn_language(image)
    if language:
        out["locale"] = language
    return out


# What an import takes as a language: at least this many of its own words drawn.
LANGUAGE_EVIDENCE = 5


def drawn_language(image: Image) -> str | None:
    """The translation whose own words the image draws most - five at least - by its
    gettext code; None for English, or text no translation here knows."""
    languages = {code: catalogue.load(code) for code in catalogue.translations()}
    if not languages or not image.screens:
        return None
    drawn = {item["text"] for screen in image.screens for slot in screen["slots"]
             for item in image.page_text(slot["program_offset"])}
    plain = [message for message in catalogue.MESSAGES
             if not message.brace_format and message.plural is None]
    english = {catalogue.ENGLISH(message.context) for message in plain}
    scores = {code: len(drawn & ({words(message.context) for message in plain} - english))
              for code, words in languages.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= LANGUAGE_EVIDENCE else None


def online_gates(image: Image) -> dict[int, dict]:
    """Each smart TV's apps' gate, by its variable's number: ``{"ours": bool,
    "timer_ms": the delay a Logitech timer sets it after, or None}``."""
    gates = {}
    for number, record in enumerate(image.engine):
        name = image.names.get(record["property_id"])
        match = name and ONLINE_NAME.match(name)
        if match:
            gates[number] = {"ours": not match["power"], "timer_ms": None}
    try:
        found = timers(image.payload)
    except (ValueError, IndexError, KeyError):
        found = []
    for seconds, operand, opcode in found:
        if opcode >= 0x80 and opcode & 0x7F in gates and operand == 1:
            gates[opcode & 0x7F]["timer_ms"] = seconds * 1000
    return gates


def _gate(image: Image, index: int, gates: dict, depth: int = 6):
    """The wait an object holds back behind a test on an apps' gate - ``(variable, ms)``
    - or None: the instruction a test guards, with what it waits."""
    if depth < 0 or not 0 <= index < len(image.objects):
        return None
    atoms = image.objects[index]["atoms"]
    for at, (operand, opcode) in enumerate(atoms):
        if opcode in TESTS and operand & 0xFF in gates and at + 1 < len(atoms):
            guarded = image.atom(*atoms[at + 1])
            return operand & 0xFF, sum(step[2] for step in guarded if step[0] == WAIT)
        if opcode == OBJECT:
            found = _gate(image, operand, gates, depth - 1)
            if found:
                return found
    return None


def read_states(image: Image) -> dict[int, dict]:
    """Each device's power and inputs, from its named variables' transitions, with
    every command as its id: ``{"power": {...}, "inputs": {...}}`` by device index."""
    out: dict[int, dict] = defaultdict(dict)
    gates = online_gates(image)
    found = device_variables(image)
    # a device's other states, by variable: what its input's writes to them mean
    others = {record["property_id"]: kind.split(":", 1)[1] for record, _device, kind in found
              if kind.startswith("state:")}
    for record, device, kind in found:
        if kind.startswith("state:"):
            state = _control_state(record, image, others)
            if state:
                out[device].setdefault("control", []).append(
                    {"id": kind.split(":", 1)[1], **state})
            continue
        _state(out[device], record, kind == "power", image, gates, others)
        # the delay before the next device, which every transition of the device's waits
        for item in record["transitions"]:
            between = _delay_variable(image, item, INTER_DEVICE_DELAY)
            if between is not None:
                out[device].setdefault("inter_device_ms", between)
                break
    _unpowered_delay(image, out)
    return dict(out)


def help_holds(image: Image) -> dict[int, dict[int, Counter]]:
    """How long each code an answer sends before it shows the next screen is held
    (`7C`'s low byte, in tenths), by device and command: Help's "No" sending a device's
    power or input again. The commonest over a device's own commands is its inter-key
    delay, MyHarmony's 0 to 1000 ms - a tester's 650 Soniq television dumped at 200,
    100 and 0 ms holds them 2, 1 and 0; 1 is an ordinary press. Logitech's help
    placeholder, which every first question sends and which is no device's, is filed
    under one device: the caller counts only the device's real commands."""
    holds: dict[int, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for item in image.objects:
        atoms = item["atoms"]
        if not atoms or atoms[-1][1] != ENTER_MODE:
            continue
        for operand, opcode in atoms:
            if opcode != OBJECT or not 0 <= operand < len(image.objects):
                continue
            inner = image.objects[operand]["atoms"]
            commands = [value for value, kind in inner if kind == COMMAND]
            held = [value for value, kind in inner if kind == DEVICE_OR_WAIT]
            if len(commands) == 1 and held:
                holds[commands[0] >> 8][commands[0]][held[-1] & 0xFF] += 1
    return holds


def _unpowered_delay(image: Image, states: dict) -> None:
    """The inter-device delay of the devices no transition names it for - a switch with
    no power or inputs of its own - when it is the one delay left, or the delays left are
    all one value: every device has one, each named for Logitech's id of the device."""
    ids = {}
    for variable, name in image.names.items():
        if INTER_DEVICE_DELAY.match(name):
            ids[name.split("_")[1]] = variable
    initial = {record["property_id"]: record["initial"] for record in image.engine}
    by_value = {}
    for variable in ids.values():
        by_value.setdefault(initial.get(variable, 0) * DELAY_UNIT_MS, []).append(variable)
    used = Counter(state["inter_device_ms"] for state in states.values()
                   if "inter_device_ms" in state)
    left = [variable for variable in ids.values()]
    for value, count in used.items():
        for variable in by_value.get(value, [])[:count]:
            left.remove(variable)
    devices = range(_device_count(image))
    without = [device for device in devices
               if "inter_device_ms" not in states.get(device, {})]
    # Help's delay screens say whose each is: a device's Change Delay screen, titled with
    # its name, loads its own delays to edit - a 650's Apple TV and Flirc, which neither
    # power nor inputs name, have 0 and 500 ms
    if without:
        named = delay_screen_variables(image)
        labels = {device: page["title"] for device, page in read_pages(image).items()
                  if page["title"]}
        labels.update(device_list_order(image)[1])
        for device in list(without):
            label = labels.get(device)
            found = [variables for title, variables in named.items()
                     if label and _same_title(title, label)]
            if len(found) == 1 and found[0] in left:
                states.setdefault(device, {})["inter_device_ms"] = \
                    initial.get(found[0], 0) * DELAY_UNIT_MS
                left.remove(found[0])
                without.remove(device)
    if len(left) == 1 and len(without) == 1:
        states.setdefault(without[0], {})["inter_device_ms"] = \
            initial.get(left[0], 0) * DELAY_UNIT_MS
    elif len(left) == len(without) and len({initial.get(item, 0) for item in left}) == 1:
        # several, all the same - a Dutch 650's TV copies and fan, 500 ms each - so which
        # is whose does not matter
        for device in without:
            states.setdefault(device, {})["inter_device_ms"] = \
                initial.get(left[0], 0) * DELAY_UNIT_MS


def delay_screen_variables(image: Image, kind=None) -> dict[str, int]:
    """The delay variable each device's Help delay screens edit - its inter-device delay,
    or with ``kind`` POWER_ON_DELAY its power-on delay - by the title of the screen that
    loads it (`1F EFvv`): Logitech titles a device's delay menus with its name, from x 3
    on the title strip."""
    kind = kind or INTER_DEVICE_DELAY
    names = {variable: name for variable, name in image.names.items()}
    out = {}
    for screen in image.screens:
        for slot in screen["slots"][:1]:
            loaded = set()
            pending = [entry["operand"] for entry in slot["entries"]
                       if entry["category"] == OBJECT]
            seen = set()
            while pending:
                index = pending.pop()
                if index in seen or not 0 <= index < len(image.objects):
                    continue
                seen.add(index)
                for operand, opcode in image.objects[index]["atoms"]:
                    if opcode == OBJECT:
                        pending.append(operand)
                    elif opcode == 0x1F and operand >> 8 == 0xEF:
                        loaded.add(operand & 0xFF)
            inter = [variable for variable in loaded
                     if kind.match(names.get(variable, ""))]
            if len(inter) != 1:
                continue
            titles = [item["text"] for item in image.page_text(slot["program_offset"])
                      if item["y"] == TITLE_XY[1] and item["x"] < 60]
            if titles:
                out.setdefault(titles[0], inter[0])
    return out


def _device_count(image: Image) -> int:
    start, _end = gspm.section_ranges(image.payload)[5]
    return image.payload[start]


def _sequence(image: Image, item: dict, others: dict) -> list[tuple]:
    """What a transition does, as an input or a state's route says it: its sends, its
    waits, and its writes to the device's other states, ``(SET, state, value)``."""
    if item["category"] >= 0x80:
        variable = item["category"] & 0x7F
        return [(SET, others[variable], item["operand"])] if variable in others else []
    if item["category"] != OBJECT:
        return []
    out = []
    for step in image.steps(item["operand"]):
        if step[0] == SEND:
            out.append((SEND, step[1]))
        elif step[0] == WAIT:
            out.append((WAIT, step[2]))
        elif step[0] == WRITE and step[1] in others:
            out.append((SET, others[step[1]], step[2]))
    return out


def _control_state(record: dict, image: Image, others: dict) -> dict | None:
    """One of a device's other states: ``{"count", "select": {value: steps}}`` when each
    value is reached from any other, as Logitech's routes are, or ``{"count", "next":
    steps}`` when values are stepped through, each pair's transition that many steps."""
    count = record["limit"] + 1
    direct = {item["to"]: _sequence(image, item, others) for item in record["transitions"]
              if item["from"] in ANY and 0 <= item["to"] < count}
    if direct:
        return {"count": count, "select": {value: steps for value, steps in direct.items()
                                           if steps}}
    pairs = {(item["from"], item["to"]): _sequence(image, item, others)
             for item in record["transitions"]}
    unit = pairs.get((0, 1))
    if unit and all(steps == unit * ((target - source) % count)
                    for (source, target), steps in pairs.items()):
        return {"count": count, "next": unit}
    return {"count": count} if not pairs else None


def _state(states: dict, record: dict, power, image: Image, gates=None, others=None):
    gates = gates or {}
    others = others or {}
    transitions = {(item["from"], item["to"]): item for item in record["transitions"]}

    def sent(item):
        if item is None or item["category"] != OBJECT:
            return [], 0
        steps = image.steps(item["operand"])
        return ([step[1] for step in steps if step[0] == SEND],
                sum(step[2] for step in steps if step[0] == WAIT))

    def sequence(item):
        """An input chosen in several steps - wake, step there, confirm, set another of
        the device's states - as its sends, waits and writes."""
        return _sequence(image, item, others)
    if power:
        on, delay = sent(transitions.get((0, 1)))
        off, _wait = sent(transitions.get((1, 0)))
        if on and off:
            states["power"] = {"on": on[0], "off": off[0],
                               "delay_ms": delay or _delay_variable(image, transitions.get((0, 1)))}
            # off in several codes, a Dutch 650's television's two
            if len(off) > 1:
                states["power"]["off_steps"] = off
        return
    count = record["limit"] + 1
    direct = [item for item in record["transitions"] if item["from"] in ANY]
    if direct:
        chosen = [None] * count
        online, app = [], None
        for item in direct:
            if not 0 <= item["to"] < count:
                continue
            steps = sequence(item)
            gate = _gate(image, item["operand"], gates) if item["category"] == OBJECT else None
            if gate:
                # an app: what waits before its first send belongs to the gate
                online.append(item["to"])
                while steps and steps[0][0] == WAIT:
                    steps.pop(0)
                variable, held = gate
                app = (gates[variable]["timer_ms"] or held if not gates[variable]["ours"]
                       else held + states.get("power", {}).get("delay_ms", 0))
            # Logitech's configurations carry the input delay in the input's own command
            # object, its 0x7C in tenths (the living room's Hisense: InputDelay 1000, 10 there and on
            # no other command): the code held that long, which keeps the device busy as
            # long (gspm.md, probe BO). Ours is a wait after the send. Either way the next
            # command comes that much later, which is what the input delay says.
            sends = [step for step in image.steps(item["operand"]) if step[0] == SEND] \
                if item["category"] == OBJECT else []
            if len(sends) == 1 and sends[0][2] > 1 and steps and steps[-1][0] == SEND:
                steps = steps + [(WAIT, sends[0][2] * 100)]
            chosen[item["to"]] = steps
        # The wait after an input's sends that most inputs have is the device's input
        # delay (the archive's InputDelay): taken off each, it is said once.
        trailing = Counter(steps[-1][1] for steps in chosen
                           if steps and steps[-1][0] == WAIT)
        delay = trailing.most_common(1)[0][0] if trailing else 0
        if delay and trailing[delay] * 2 < sum(1 for steps in chosen if steps):
            delay = 0
        commands = []
        for steps in chosen:
            if delay and steps and steps[-1] == (WAIT, delay):
                steps = steps[:-1]
            sends = [step for step in steps if step[0] == SEND]
            commands.append(None if not steps else sends[0][1] if steps == sends[:1]
                            else steps)
        states["inputs"] = {"direct": commands}
        if delay:
            states["inputs"]["delay_ms"] = delay
        if online and app:
            states["inputs"]["online"] = sorted(online)
            states["inputs"]["app_delay_ms"] = app
        return
    stepping = _stepping(transitions, image, count)
    if stepping:
        states["inputs"] = stepping


def _stepping(transitions: dict, image: Image, count: int) -> dict | None:
    """Inputs reached by stepping, from the transitions between them: "next" as many times
    as it takes, or "previous" where that is the shorter way round, between a "start"
    and a "finish" - Logitech's menu inputs (`InputType` 4): a 650's Soniq television
    goes from its first input to its seventh with Source, Down three times, OK. The
    plainest reading that fits every transition: no start or finish, then one, then more.
    The input delay is how long each code is held (`7C` in tenths, as Logitech writes
    it) or the wait after it (as a build does)."""
    sends, waited = {}, {}
    for (source, target), item in transitions.items():
        if source == target or item["category"] != OBJECT:
            continue
        steps = image.steps(item["operand"])
        sends[(source, target)] = [step for step in steps if step[0] == SEND]
        waited[(source, target)] = sum(step[2] for step in steps if step[0] == WAIT)
    if not sends or not all(sends.values()):
        return None
    codes = {pair: [step[1] for step in steps] for pair, steps in sends.items()}
    shortest = min(len(sequence) for sequence in codes.values())
    for around in range(shortest):
        for begin in range(around + 1):
            end = around - begin
            start = codes[next(iter(codes))][:begin]
            finish = codes[next(iter(codes))][len(codes[next(iter(codes))]) - end:]
            ahead, behind = Counter(), Counter()
            for (source, target), sequence in codes.items():
                middle = sequence[begin:len(sequence) - end]
                if (sequence[:begin] != start or sequence[len(sequence) - end:] != finish
                        or not middle or len(set(middle)) != 1):
                    break
                if len(middle) == (target - source) % count:
                    ahead[middle[0]] += 1
                elif len(middle) == (source - target) % count:
                    behind[middle[0]] += 1
                else:
                    break
            else:
                if not ahead:
                    continue
                forward = ahead.most_common(1)[0][0]
                held = Counter(step[2] for steps in sends.values() for step in steps)
                pressed = sum(len(steps) for steps in sends.values())
                delay = (held.most_common(1)[0][0] * 100 if held.most_common(1)[0][0] > 1
                         else round(sum(waited.values()) / pressed))
                out = {"next": forward, "delay_ms": delay, "count": count}
                backward = [code for code in behind if code != forward]
                if backward:
                    out["previous"] = backward[0]
                if start:
                    out["start"] = start
                if finish:
                    out["finish"] = finish
                return out
    return None


POWER_ON_DELAY = re.compile(r"^PowerOnDelay_\d+_\d+$")
INTER_DEVICE_DELAY = re.compile(r"^InterDeviceDelay_\d+_\d+$")
DELAY_UNIT_MS = 100


def _delay_variable(image: Image, item: dict | None, name=POWER_ON_DELAY):
    """A delay held in a variable, as an arch-14 configuration keeps it: the transition
    switches on its device's `PowerOnDelay_<id>` or `InterDeviceDelay_<id>`, whose case
    waits that many tenths of a second, so the remote's delay screens can change it.
    The power-on delay is 0 without one; the inter-device delay is None."""
    if item is None or item["category"] != OBJECT:
        return 0 if name is POWER_ON_DELAY else None
    initial = {record["property_id"]: record["initial"] for record in image.engine}
    # every switch the transition can reach, a guarded one too: the wait before the next
    # device is behind a test of whether there is one
    pending, seen = [item["operand"]], set()
    while pending:
        index = pending.pop()
        if index in seen or not 0 <= index < len(image.objects):
            continue
        seen.add(index)
        for operand, opcode in image.objects[index]["atoms"]:
            if opcode == OBJECT:
                pending.append(operand)
            elif opcode == 0x72 and name.match(image.names.get(operand & 0xFF, "")):
                return initial.get(operand & 0xFF, 0) * DELAY_UNIT_MS
    return 0 if name is POWER_ON_DELAY else None


def variable_labels(image: Image) -> dict[int, str]:
    """Each device's label as its state variables are named - `Living_Room_TV_Power_2`
    is the Living Room TV - by device index."""
    out = {}
    for record in image.engine:
        name = image.names.get(record["property_id"])
        match = name and (POWER_NAME.match(name) or INPUT_NAME.match(name))
        device = match and _variable_device(record["transitions"], image)
        if match and device is not None:
            out.setdefault(device, match["label"].replace("_", " "))
    return out


# What Logitech's help flow sends where it "tries to turn a device on": a frame of its own
# Logitech 32-bit protocol carrying 0 - a 4000/4500 lead and 24 zero bits, sent once or
# more - which no device in Logitech's database answers to. It is filed under whichever
# device the help is about, so it is not that device's command (docs/harmony_650_700/gspm.md,
# "The help flow's placeholder").
PLACEHOLDER_FRAME = [4000, -4500] + [400, -1000] * 24 + [400, -50000]


def is_help_placeholder(signal: dict) -> bool:
    """Whether ``signal`` is the help flow's placeholder frame, once or repeated."""
    pulses = signal.get("pulses_us") or []
    frame = len(PLACEHOLDER_FRAME)
    return (bool(pulses) and len(pulses) % frame == 0
            and all(pulses[at:at + frame] == PLACEHOLDER_FRAME
                    for at in range(0, len(pulses), frame)))


def project_devices(image: Image, native: list[dict], notes: list[str] | None = None,
                    naming: dict | None = None) -> list[dict]:
    """The project's devices: ``native`` (command_index.portable_devices, every command
    with its waveform and a numbered name) given their names, power, inputs and keys.
    What could not be carried over is said in ``notes``; ``naming``, when given, is
    filled with each command id's device id and name, which activities refer to."""
    notes = [] if notes is None else notes
    named = variable_labels(image)
    # a device with no page of commands is named by its Devices list row
    named = {**device_list_order(image)[1], **named}
    pages = read_pages(image, named)
    states = read_states(image)
    rows = device_row_labels(image)
    helped = help_holds(image)
    # the power variables that send nothing, by label: a device Logitech keeps on
    powered_by_title = delay_screen_variables(image, POWER_ON_DELAY)
    initial = {record["property_id"]: record["initial"] for record in image.engine}
    unswitched = {match["label"]: record for record in image.engine
                  if (match := POWER_NAME.match(image.names.get(record["property_id"]) or ""))
                  and not record["transitions"]}
    bound = activity_keys(image)
    # the digit each code the number sender's tables send stands for (section 17)
    sent_digits = {}
    for sender in image.number_senders:
        for table in sender["tables"]:
            for digit, atom in enumerate(table):
                for step in image.atom(*atom) if atom else ():
                    if step[0] == SEND:
                        sent_digits.setdefault(step[1], str(digit))
    out = []
    for device in native:
        index = device["native"]["harmony-650"]["device_index"]
        page = pages.get(index, {"title": None, "names": {}, "keys": {}})
        state = states.get(index, {})
        ids = {signal["native"]["harmony-650"]["command_id"]: name
               for name, signal in device["signals"].items()
               if not is_help_placeholder(signal)}
        if len(ids) < len(device["signals"]):
            notes.append(f"{named.get(index) or page['title'] or device['label']!r}: Logitech's "
                         "help placeholder, a code no device answers to, was left out")
        # its inter-key delay: how long Help's answers hold its own codes
        held = Counter()
        for command, counts in helped.get(index, {}).items():
            if command in ids:
                held.update(counts)
        if held and held.most_common(1)[0][0] != 1:
            state = {**state, "interkey_ms": held.most_common(1)[0][0] * 100}
        # a device kept on - MyHarmony's "always on": its power variable sends nothing and
        # only Help, asking whether it is on, sends its power - a Dutch 650's fan
        title = (named.get(index) or page["title"] or "").replace(" ", "_")
        if "power" not in state and title in unswitched:
            sent = Counter({command: sum(counts.values())
                            for command, counts in helped.get(index, {}).items()
                            if command in ids})
            if sent:
                toggle = sent.most_common(1)[0][0]
                # its power-on delay, which no transition waits on, from its delay screen
                label = named.get(index) or page["title"] or ""
                found = [variable for screen_title, variable in powered_by_title.items()
                         if label and _same_title(screen_title, label)]
                delay = (initial.get(found[0], 0) * DELAY_UNIT_MS if len(found) == 1
                         else None)
                state = {**state, "power": {"on": toggle, "off": toggle, "delay_ms": delay},
                         "always_on": True}
        # A command a button or a key names is one of the device's own; the copies of
        # one that Logitech keeps for power, inputs and held steps are found against them.
        known = dict(page["names"])
        for key, command in sorted(page["keys"].items()):
            known.setdefault(command, key)
        same = _duplicates(device["signals"], ids, known)
        holds = _held_copies(device["signals"], ids, known)
        same.update({command: twin for command, (twin, _ms) in holds.items()})
        copies = _press_copies(device["signals"], ids, known)
        names = _command_names({command: name for command, name in ids.items()
                                if command not in same}, page, state, copies, bound,
                               sent_digits)
        names.update({command: names[twin] for command, twin in same.items()})
        slots = defaultdict(list)
        for key, command in page["keys"].items():
            slots[same.get(command, command)].append(key)
        signals = {names[command]: dict(device["signals"][old], name=names[command])
                   for command, old in ids.items() if command not in same}
        # its name: as its variables or the Devices list give it, else its pages' title -
        # but not a title cut short (".."), where the list's row has the whole name
        label = named.get(index) or page["title"] or device["label"]
        if label.endswith("..") and rows.get(index) and not rows[index].endswith(".."):
            label = rows[index]
        # A command the configuration's pages do not show - a press-only copy, a code
        # with no name, one on a key - keeps no label, so a rebuild leaves it off too.
        # The pages' commands come first, in the order the pages show them.
        drawn = [command for command in page["names"] if command in ids]
        order = drawn + [command for command in ids if command not in page["names"]]
        project = dict(device, label=label, signals=signals, commands=[
            [names[command], names[command] if command in page["names"] else "", "", "",
             sorted(slots[command]) or None]
            for command in order if command not in same])
        # kept on only where what Help sends is a power toggle: a television's copies
        # that only Help's Off asks after send PowerOff, which is no way to turn one on
        if state.get("always_on") and "Toggle" not in names[state["power"]["on"]]:
            state = {key: value for key, value in state.items()
                     if key not in ("power", "always_on")}
        project.update(_state_fields(state, names))
        if naming is not None:
            naming.update({command: (project["id"], name) for command, name in names.items()})
            # a held step's own record is its twin held, which is how a project says it
            naming.update({command: (project["id"], names[twin], held)
                           for command, (twin, held) in holds.items()})
        out.append(project)
    return out


def _signature(signal: dict) -> str:
    return repr({key: value for key, value in signal.items()
                 if key not in ("name", "native", "provenance")})


def _press(signal: dict) -> tuple:
    """What a command sends once: its pulses up to where its repeat starts."""
    intro = (signal.get("sections") or {}).get("intro_pulses")
    pulses = signal.get("pulses_us") or []
    return signal.get("carrier_hz"), tuple(pulses[:intro] if intro else pulses)


def _duplicates(signals: dict, ids: dict[int, str], drawn: dict[int, str]) -> dict[int, int]:
    """Commands no button names that send exactly what a named one sends - Logitech
    keeps a record of its own for a power or input command - each with its twin."""
    named = {}
    for command in drawn:
        if command in ids:
            named.setdefault(_signature(signals[ids[command]]), command)
    return {command: named[_signature(signals[name])] for command, name in ids.items()
            if command not in drawn and _signature(signals[name]) in named}


def _press_copies(signals: dict, ids: dict[int, str], drawn: dict[int, str]) -> dict[int, str]:
    """Commands no button names that send once what a named one sends while held -
    Logitech's power and input records are such copies - named after their twin."""
    named = {}
    for command in drawn:
        if command in ids:
            named.setdefault(_press(signals[ids[command]]), drawn[command])
    return {command: f"{named[_press(signals[name])]} (press)"
            for command, name in ids.items()
            if command not in drawn and _press(signals[name]) in named}


def _frame(signal: dict) -> tuple[list[int], list[int]]:
    """A command's press, and the frame it repeats while held: its repeat section, or the
    press again for a code without one."""
    pulses = list(signal.get("pulses_us") or [])
    sections = signal.get("sections") or {}
    intro = sections.get("intro_pulses")
    if not intro:
        return pulses, pulses
    repeat = pulses[intro:intro + (sections.get("repeat_pulses") or 0)]
    return pulses[:intro], repeat or pulses[:intro]


def _held_copies(signals: dict, ids: dict[int, str], drawn: dict[int, str]) -> dict[int, tuple]:
    """Commands no button names that are a named command held: its press, then its
    repeat frame over and over, then a gap - a held step's record (ir_lowering.held) - each
    with its twin and the milliseconds it was held for."""
    out = {}
    for command, name in ids.items():
        if command in drawn:
            continue
        pulses = list(signals[name].get("pulses_us") or [])
        if signals[name].get("sections") or len(pulses) < 4:
            continue
        for twin in drawn:
            if twin not in ids:
                continue
            press, frame = _frame(signals[ids[twin]])
            if not press or signals[ids[twin]].get("carrier_hz") != signals[name].get(
                    "carrier_hz") or pulses[:len(press)] != press:
                continue
            rest, frames = pulses[len(press):], 0
            while rest[:len(frame)] == frame and len(rest) >= len(frame):
                rest, frames = rest[len(frame):], frames + 1
            if not frames or rest not in ([], [-ir_lowering.RELEASE_GAP_US]):
                continue
            before = sum(abs(pulse) for pulse in press + frame * (frames - 1))
            after = before + sum(abs(pulse) for pulse in frame)
            # the hold that lowers to exactly this record, as a round number when one does
            held = next((ms for ms in range(before // 1000 + 1, after // 1000 + 1)
                         if ms % 100 == 0), after // 1000)
            out[command] = (twin, held)
            break
    return out


def activity_keys(image: Image) -> dict[int, str]:
    """What an activity calls each command, by command id: the key whose row sends that
    one command and nothing else - PrevChannel's own code, on a Dutch 650, which no
    device page shows - else the label of a button that does."""
    out = {}
    for context in image.contexts:
        for row in sorted(context["rows"], key=lambda row: row["key_code"]):
            name = keys.name_of(row["key_code"])
            steps = image.row(row)
            if name and len(steps) == 1 and steps[0][0] == SEND:
                out.setdefault(steps[0][1], name)
    # then the label of an activity's button that sends it alone - a Cisco box's Search,
    # on a 700's "Watch TV Stereo" screen and nowhere else
    pages = {ordinal for ordinals in command_pages(image).values() for ordinal in ordinals}
    places = {key: position for position, key in enumerate(CORNER_KEYS)}
    for ordinal, screen in enumerate(image.screens):
        if ordinal in pages:
            continue
        for slot in screen["slots"]:
            items = None
            for entry in slot["entries"]:
                steps = image.row(entry) if entry["key_code"] in places else []
                if len(steps) != 1 or steps[0][0] != SEND or steps[0][1] in out:
                    continue
                items = items if items is not None else image.page_text(slot["program_offset"])
                lines = _button_label(items, places[entry["key_code"]])
                if lines:
                    out[steps[0][1]] = image.join(lines)
    return out


def _command_names(ids: dict[int, str], page: dict, state: dict,
                   copies: dict[int, str] | None = None,
                   bound: dict[int, str] | None = None,
                   digits: dict[int, str] | None = None) -> dict[int, str]:
    """Each command's name: its button's label, else the key it is bound to on its
    device's pages, else the command it is a press-only copy of, else the part it plays
    in the device's power, inputs or other states, else the digit the number sender
    sends it for (``digits``), else the key an activity binds it to, else its numbered
    name. Two commands never share one."""
    by_key = {}
    for key, command in sorted(page["keys"].items()):
        by_key.setdefault(command, key)
    roles = {}
    power = state.get("power")
    if power:
        if power["on"] == power["off"]:
            roles[power["on"]] = "PowerToggle"
        else:
            roles[power["on"]], roles[power["off"]] = "PowerOn", "PowerOff"
        for extra in (power.get("off_steps") or [])[1:]:
            roles.setdefault(extra, "PowerOff")
    inputs = state.get("inputs") or {}
    if "next" in inputs:
        roles[inputs["next"]] = "InputNext"
    # a command only another of the device's states sends is named for its place there:
    # `Screen2`, `TVInputNext`
    for other in state.get("control") or []:
        for value, steps in sorted((other.get("select") or {}).items()):
            sends = [step[1] for step in steps if step[0] == SEND]
            if len(sends) == 1:
                roles.setdefault(sends[0], f"{other['id']}{value + 1}")
        sends = [step[1] for step in other.get("next") or [] if step[0] == SEND]
        if len(sends) == 1:
            roles.setdefault(sends[0], f"{other['id']}Next")
    for value, command in enumerate(inputs.get("direct") or []):
        if isinstance(command, int):
            roles.setdefault(command, f"Input{value + 1}")
    out, used = {}, set()
    # the drawn names first, so a key's or a role's name never takes a button's own
    numbers = {command: f"Number{digit}" for command, digit in (digits or {}).items()}
    for source in (page["names"], by_key, copies or {}, roles, numbers, bound or {}, ids):
        for command in ids:
            if command in out or command not in source:
                continue
            name, number = source[command], 2
            while name in used:
                name, number = f"{source[command]} ({number})", number + 1
            out[command] = name
            used.add(name)
    return out


def _state_fields(state: dict, names: dict[int, str]) -> dict:
    """A device's power and inputs in the project's fields (generate.device_states reads
    them back)."""
    out = {}
    if state.get("interkey_ms") is not None:
        out["press_interkey"] = state["interkey_ms"]
    if state.get("always_on"):
        out["always_on"] = True
    power = state.get("power")
    if power:
        if power["on"] == power["off"]:
            out["power_cmd"] = names[power["on"]]
        else:
            out["power_on_cmd"], out["power_off_cmd"] = names[power["on"]], names[power["off"]]
        if power["delay_ms"] is not None:         # a device kept on names none
            out["power_delay"] = power["delay_ms"]
        if power.get("off_steps"):
            out["power_off_steps"] = [names[command] for command in power["off_steps"]]
    if state.get("inter_device_ms") is not None:
        out["inter_device_delay"] = state["inter_device_ms"]
    inputs = state.get("inputs")
    if inputs and "direct" in inputs:
        out["inputs"] = []
        for value, chosen in enumerate(inputs["direct"]):
            if chosen is None:
                out["inputs"].append([f"Input {value + 1}"])
            elif isinstance(chosen, list):
                # a sequence, as the project's inputs take one: commands, waits and the
                # device's other states set
                out["inputs"].append([f"Input {value + 1}", _project_steps(chosen, names)])
            else:
                out["inputs"].append([names[chosen].removesuffix(" (press)"), names[chosen]])
        if inputs.get("delay_ms"):
            out["input_delay"] = inputs["delay_ms"]
        if inputs.get("online"):
            out["online_inputs"] = [out["inputs"][value][0] for value in inputs["online"]]
            out["app_power_delay"] = inputs["app_delay_ms"]
    elif inputs:
        out["input_cycle"] = {"next": names[inputs["next"]], "delay_ms": inputs["delay_ms"],
                              "values": [f"Input {value + 1}"
                                         for value in range(inputs["count"])]}
        if inputs.get("previous") is not None:
            out["input_cycle"]["previous"] = names[inputs["previous"]]
        for key in ("start", "finish"):
            if inputs.get(key):
                out["input_cycle"][key] = [names[code] for code in inputs[key]]
    # the device's other states, as Logitech's database declares them (corpus_provider,
    # `_archive_states`): values, a route to each, or the steps to the next
    control = []
    for other in state.get("control") or []:
        entry = {"id": other["id"],
                 "values": [str(value + 1) for value in range(other["count"])]}
        if other.get("select"):
            entry["select"] = {str(value + 1): {"steps": _project_steps(steps, names)}
                               for value, steps in sorted(other["select"].items())}
        if other.get("next"):
            entry["next"] = _project_steps(other["next"], names)
        control.append(entry)
    if control:
        out["control_states"] = control
    return out


def _project_steps(steps, names: dict[int, str]) -> list:
    """Steps as a project's device-local ones: a command's name, ``{"delay_ms"}``, and
    ``{"set", "to"}`` for another of the device's states, its values named 1 upwards."""
    out = []
    for step in steps:
        if step[0] == SEND:
            out.append(names[step[1]])
        elif step[0] == WAIT:
            out.append({"delay_ms": step[1]})
        else:
            out.append({"set": step[1], "to": str(step[2] + 1)})
    return out


# --- activities


def _plain_send(macro: list[list]) -> bool:
    """Whether a macro is one command, sent once - what a key or a button binds as is."""
    return len(macro) == 1 and macro[0][0] == "command" and len(macro[0]) == 3

VOLUME_KEYS = ("VolumeUp", "VolumeDown", "VolumeMute")
# Device types that show the picture, as the activity editor offers them for Display.
DISPLAY_TYPES = {"Television", "Projector", "Monitor", "TvDvd", "TvDvdVcr", "TvVcr", "TvHdd",
                 "MediaCenterPC", "Laptop", "Computer"}
FLOW_KEYS = ("Activities", "Off", "Help")
OFF_KEY = keys.by_name("Off")
DIGIT_KEYS = {f"Number{digit}": str(digit) for digit in range(10)}


class Activities:
    """An image's activities read back, with the devices as the project has them
    (project_devices) and ``naming``, each command id's device id and name."""

    def __init__(self, image: Image, devices: list[dict], naming: dict, notes: list[str],
                 logos: Path | None = None):
        self.image = image
        # where a favourite's logo is saved, as a PNG a project names (pictures.logo_file)
        self.logos = logos
        self.devices = devices
        self.naming = naming
        self.notes = notes
        self.ids = [device["id"] for device in devices]
        self.variables = {record["property_id"]: (device, kind)
                          for record, device, kind in device_variables(image)}
        self.state = next((variable for variable, name in image.names.items()
                           if name.startswith("CurrentActivityState")), None)
        self.contexts = {context["ordinal"]: context for context in image.contexts}
        # a device's own pages, which an activity's are not even when they share a name -
        # a Dutch 650's fan, device and activity both "Ventilator."
        self.device_pages = {ordinal for ordinals in command_pages(image).values()
                             for ordinal in ordinals}
        self.device_labels = {device.get("label") for device in devices}
        # what a key, a button or an activity does that a project cannot say, and so is
        # left out: told in the notes rather than dropped unseen
        self.left_out: Counter = Counter()

    def hooks(self, context: dict) -> dict[int, list[tuple]]:
        """A context's rows, as what each does, by key code."""
        return {row["key_code"]: self.image.row(row) for row in context["rows"]}

    def off_context(self) -> int | None:
        """The context Off selects: every image binds the Off key once to select it."""
        rows = [row for context in self.contexts.values() for row in context["rows"]]
        rows += [row for screen in self.image.screens for row in screen["header_entries"]]
        for row in rows:
            if row["key_code"] == OFF_KEY:
                targets = [step[1] for step in self.image.row(row) if step[0] == CONTEXT]
                if targets:
                    return targets[0]
        return None

    def starts(self) -> list[int]:
        """The contexts that start an activity - their enter writes which one runs -
        in the order the Activities menu lists them, then any it does not."""
        if self.state is None:
            return []
        off = self.off_context()
        found = {}
        for ordinal, context in self.contexts.items():
            enter = self.hooks(context).get(activity_index.ENTER, [])
            values = [step[2] for step in enter if step[0] == WRITE and step[1] == self.state]
            if values and ordinal != off:
                found[ordinal] = values[0]
        listed = [ordinal for ordinal in self.menu_rows() if ordinal in found]
        return listed + sorted((ordinal for ordinal in found if ordinal not in listed),
                               key=found.get)

    def menu_rows(self) -> dict[int, str]:
        """Each activity's row in the Activities menu, by context: the label drawn on it."""
        out = {}
        for screen in self.image.screens:
            for slot in screen["slots"]:
                places = button_positions(self.image, slot)
                rows = {}
                for entry in slot["entries"]:
                    targets = [step[1] for step in self.image.row(entry) if step[0] == CONTEXT]
                    if targets and entry["key_code"] in places:
                        rows.setdefault(targets[0], set()).add(places[entry["key_code"]])
                if not rows:
                    continue
                items = self.image.page_text(slot["program_offset"])
                # a menu row spans a page's width - both keys of a side open it - and
                # its label is centred across them
                # top to bottom, as the menu shows them
                for context, positions in sorted(rows.items(), key=lambda row: min(row[1])):
                    lines = _corner_lines(items, positions)
                    if lines:
                        out.setdefault(context, self.image.join(lines, words=True))
        return out

    def command(self, command_id: int) -> tuple[str, str] | None:
        return self.naming.get(command_id)

    def macro(self, steps: list[tuple]) -> list[list] | None:
        """Sends and waits as a project's macro steps; None when they do anything else
        a macro cannot say."""
        out = []
        for step in steps:
            if step[0] == WRITE and step[1] not in self.variables \
                    and step[1] not in self.image.channel_variables:
                # a state of its own - an activity's channel mode - not a device's power
                # or input, which the project says another way, nor a favourite's channel,
                # whose transition dials the digits the steps that follow already carry
                name = self.image.names.get(step[1]) or f"variable {step[1]}"
                self.left_out[f"a write to {name}"] += 1
            if step[0] == SEND and self.command(step[1]):
                device, name, *held = self.command(step[1])
                if not held and step[2] > 1:
                    # Logitech holds a code by repeating it: the device field's count
                    held = [self._held_ms(device, name, step[2])]
                out.append(["command", device, name] + (["Press", held[0]] if held else []))
            elif step[0] == WAIT and step[1] < len(self.ids):
                if out and out[-1][0] == "delay" and out[-1][1] == self.ids[step[1]]:
                    out[-1][2] += step[2]
                else:
                    out.append(["delay", self.ids[step[1]], step[2]])
            elif step[0] in (SEND, WAIT):
                self.left_out["a command or wait no device has"] += 1
                return None
        return out

    def _held_ms(self, device_id: str, name: str, repeats: int) -> int:
        """How long a code sent ``repeats`` times lasts, to the nearest 100 ms."""
        device = next(item for item in self.devices if item["id"] == device_id)
        press, frame = _frame(device["signals"][name])
        total = sum(abs(pulse) for pulse in press + frame * (repeats - 1)) / 1000
        return max(100, round(total / 100) * 100)

    def read(self) -> tuple[list[dict], dict]:
        """The project's activities, and its settings for Off."""
        labels_ = self.menu_rows()
        activities = [self.activity(ordinal, labels_.get(ordinal)) for ordinal in self.starts()]
        extra = {}
        off = self.off_context()
        if off is not None and off in self.contexts:
            # Off as a list of devices; Logitech's turns off whatever is on, by tests,
            # which is every device with a power command - what a project without a list
            # gets - so nothing is said for it
            enter = self.hooks(self.contexts[off]).get(activity_index.ENTER, [])
            listed = [self.ids[self.variables[step[1]][0]] for step in enter
                      if step[0] == WRITE and step[2] == 0
                      and self.variables.get(step[1], (None, ""))[1] == "power"]
            # a list of every device with power is what no list says, as a build writes it
            powered = {self.ids[device] for device, kind in self.variables.values()
                       if kind == "power"}
            if listed and set(listed) != powered:
                extra["power_off_all"] = listed
        if self.left_out:
            self.notes.append("left out, as a project cannot say them: " + ", ".join(
                f"{what} ({count})" for what, count in sorted(self.left_out.items())))
        return activities, extra

    def ensured(self, home: int, on: list[str]) -> list[str]:
        """``on`` with the devices the activity's Help asks to be turned on by hand - a
        device with no power command, which no write says the activity uses: Help's
        note "Ensure the X is on.", with only OK, whose Exit goes to the activity's
        screen ``home``. Each goes after the device the question before it asks about."""
        screens = self.image.screens
        on = list(on)

        def bound(ordinal, where):
            entries = (screens[ordinal]["slots"][0]["entries"] if where == "soft"
                       else screens[ordinal]["header_entries"])
            return {entry["key_code"]: self.image.row(entry) for entry in entries
                    if entry["category"]}
        for ordinal, screen in enumerate(screens):
            if not screen["slots"]:
                continue
            soft = bound(ordinal, "soft")
            if set(soft) != {0xA2} or bound(ordinal, "header").get(0x99) != [(MODE, home)]:
                continue
            text = " ".join(item["text"] for item in self.image.page_text(
                screen["slots"][0]["program_offset"]))
            named = [device for device in self.devices
                     if device.get("label") and device["label"] in text
                     and not device.get("power_on_cmd") and not device.get("power_cmd")]
            if not named or len(soft[0xA2]) != 1 or soft[0xA2][0][0] != MODE:
                continue
            device = max(named, key=lambda item: len(item["label"]))["id"]
            if device in on:
                continue
            # the question whose Yes comes here, and the device its No powers
            before = None
            for other, item in enumerate(screens):
                answers = bound(other, "soft") if item["slots"] else {}
                if (answers.get(0xA2) or [None])[-1] != (MODE, ordinal):
                    continue
                # the device its No sends to, or whose state its answers write
                sent = [(self.naming.get(step[1]) or (None,))[0]
                        for step in answers.get(0x89, []) if step[0] == SEND]
                written = [self.ids[self.variables[step[1]][0]]
                           for steps in answers.values() for step in steps
                           if step[0] == WRITE and step[1] in self.variables]
                before = next(iter(sent + written), None)
                break
            on.insert(on.index(before) + 1 if before in on else 0, device)
        return on

    def activity(self, ordinal: int, label: str | None) -> dict:
        hooks = self.hooks(self.contexts[ordinal])
        enter = hooks.get(activity_index.ENTER, [])
        on, inputs, steps = [], [], []
        for step in enter:
            if step[0] == WRITE and step[1] in self.variables:
                device, kind = self.variables[step[1]]
                if kind == "power" and step[2] == 1:
                    on.append(self.ids[device])
                elif kind == "input" and (self.devices[device].get("inputs")
                                          or self.devices[device].get("input_cycle")):
                    # a device whose inputs could not be read has none to set (its note
                    # says why)
                    inputs.append(["input", self.ids[device], self._input_name(device, step[2])])
            elif step[0] in (SEND, WAIT):
                steps.append(step)
        label = label or f"Activity {ordinal}"
        shown = [step[1] for step in enter if step[0] == MODE]
        on = self.ensured(shown[-1], list(dict.fromkeys(on))) if shown else on
        out = {"id": str(ordinal), "label": label, "type": None,
               "power_on_devices": list(dict.fromkeys(on)),
               "enter": inputs + (self.macro(steps) or []),
               "leave": self.macro([step for step in hooks.get(activity_index.LEAVE, [])
                                    if step[0] in (SEND, WAIT)]) or []}
        out.update(self.key_fields(hooks))
        button = self.activity_buttons().get(ordinal)
        if button:
            out["activity_button"] = button
        out["display"] = self._display(on, inputs) or out["control"]
        out.update(self.screens(label))
        # favourites dial on the activity's control device: one that names none takes the
        # device its favourites dial (a Polish 600's TV)
        dialled = out.pop("channel_device", None)
        if dialled and not out.get("control"):
            out["control"] = dialled
        return out

    def activity_buttons(self) -> dict[int, str]:
        """The activity key that starts each activity, by its context: "Movie", "TV" or
        "Music" (keys.ACTIVITY_BUTTONS)."""
        names = {keys.code(scan): name for name, scan in keys.ACTIVITY_BUTTONS.items()}
        out = {}
        for context in self.image.contexts:
            for row in context["rows"]:
                if row["key_code"] in names:
                    for step in self.image.row(row):
                        if step[0] == CONTEXT:
                            out.setdefault(step[1], names[row["key_code"]])
        return out

    def _display(self, on: list[str], inputs: list[list]) -> str | None:
        """The device an activity watches: one it switches on that shows a picture,
        else the first it sets an input on."""
        types = {device["id"]: device.get("type") for device in self.devices}
        shown = [device for device in on if types.get(device) in DISPLAY_TYPES]
        if shown:
            return shown[0]
        return inputs[0][1] if inputs else None

    def _input_name(self, device: int, value: int) -> str:
        inputs = self.devices[device].get("inputs") or []
        if 0 <= value < len(inputs):
            return inputs[value][0]
        cycle = self.devices[device].get("input_cycle") or {}
        values = cycle.get("values") or []
        return values[value] if 0 <= value < len(values) else f"Input {value + 1}"

    def key_fields(self, hooks: dict[int, list[tuple]]) -> dict:
        """The keys an activity binds: its roles, and the keys its roles do not route."""
        bound = {}
        for code, steps in hooks.items():
            name = keys.name_of(code)
            if name is None or name in FLOW_KEYS:
                continue
            macro = self.macro(steps)
            if macro:
                bound[name] = macro
        sends = {name: macro[0][1:] for name, macro in bound.items() if _plain_send(macro)}
        volume = next((sends[name][0] for name in VOLUME_KEYS if name in sends), None)
        others = [device for name, (device, _command) in sends.items()
                  if name not in VOLUME_KEYS]
        control = max(dict.fromkeys(others), key=others.count) if others else volume
        routed = self._routed(volume, control)
        out = {"control": control, "volume": volume, "display": control,
               "bound_keys": sorted(bound)}
        macros = {name: macro for name, macro in bound.items()
                  if not _plain_send(macro) or routed.get(name) != tuple(macro[0][1:])}
        if macros:
            out["hard_macros"] = macros
        return out

    def _routed(self, volume, control) -> dict[str, tuple[str, str]]:
        """What the roles route by themselves (activities.py): volume keys to the volume
        device, every other key its control device has a command on."""
        slots = {}
        for device in self.devices:
            for name, _label, _a, _b, keys_ in device["commands"]:
                for key in keys_ or ():
                    slots.setdefault((device["id"], key), name)
        out = {}
        for key in VOLUME_KEYS:
            if (volume, key) in slots:
                out[key] = (volume, slots[(volume, key)])
        for (device, key), name in slots.items():
            if device == control:
                out.setdefault(key, (device, name))
        return out

    def screens(self, label: str) -> dict:
        """An activity's on-screen buttons and favourites: the pages titled with its name
        whose buttons send and do nothing else."""
        buttons, favourites = [], []
        if not hasattr(self, "_titles"):
            self._titles = {item["text"] for screen in self.image.screens
                            for slot in screen["slots"]
                            for item in self.image.page_text(slot["program_offset"])
                            if (item["x"], item["y"]) == TITLE_XY}
            self._names = set(self.menu_rows().values())

        def titled(title: str) -> bool:
            # a title cut short is the activity's, unless another's name fits it too and
            # this one's own pages show its name whole - a name that fits is never cut:
            # "Watch Smarthu.." is "Watch Smarthub Stereo", not "Watch Smarthub"
            if not _same_title(title, label):
                return False
            if title.endswith("..") and label in self._titles:
                return not any(other != label and _same_title(title, other)
                               for other in self._names)
            return True
        for ordinal, screen in enumerate(self.image.screens):
            # a device's own pages, when the activity has the device's name
            if ordinal in self.device_pages and any(
                    _same_title(label, device) or _same_title(device, label)
                    for device in self.device_labels if device):
                continue
            for slot in screen["slots"]:
                items = self.image.page_text(slot["program_offset"])
                # a title too long for the strip is cut - "AV Receiver & T.."
                if not any((item["x"], item["y"]) == TITLE_XY and titled(item["text"])
                           for item in items):
                    continue
                places = button_positions(self.image, slot)
                found = []
                for entry in slot["entries"]:
                    position = places.get(entry["key_code"])
                    if position is None:
                        continue
                    steps = self.image.row(entry)
                    if not any(step[0] == SEND for step in steps):
                        continue
                    if any(step[0] == MODE for step in steps):
                        found = None
                        break
                    found.append((position, steps))
                for position, steps in sorted(found or ()):
                    lines = _button_label(items, position)
                    macro = self.macro(steps)
                    if not macro:
                        continue
                    text = self.image.join(lines) if lines else None
                    # a button that dials a channel is a favourite, named or with a logo;
                    # one with a logo and no name is too
                    if self._channel(macro) or text is None:
                        logo = None if text else self._logo(slot, position)
                        favourites.append((text, macro, logo))
                    else:
                        buttons.append([text, *macro[0][1:]] if _plain_send(macro)
                                       else {"label": text, "macro": macro})
        out = {"soft_buttons": buttons}
        if favourites:
            out.update(self.favourites(favourites))
        return out

    def _channel(self, macro: list[list]) -> tuple[str, str | None] | None:
        """A macro that dials digits - with waits between - and perhaps confirms: its
        number and the confirming command; None for any other macro."""
        digits, confirm = "", None
        for step in macro:
            if step[0] != "command":
                continue
            digit = self._digit(step[1], step[2])
            if digit is not None and confirm is None:
                digits += digit
            elif confirm is None:
                confirm = step[2]
            else:
                return None
        return (digits, confirm) if digits else None

    def favourites(self, entries: list[tuple[str | None, list, list | None]]) -> dict:
        """Favourites: a channel when it dials, else the command or macro it runs, with
        its logo saved when there is somewhere to save it. One with no name is named by
        what it sends."""
        out, confirm, lost = [], None, 0
        for number, (text, macro, picture) in enumerate(entries, start=1):
            channel = self._channel(macro)
            if channel:
                name = text or f"Channel {channel[0]}"
            elif _plain_send(macro):
                name = text or macro[0][2]
            else:
                name = text or f"Favourite {number}"
            image = self._save_logo(name, picture) if picture else None
            lost += picture is not None and image is None
            if channel and channel[1] in (None, confirm or channel[1]):
                confirm = confirm or channel[1]
                out.append([name, "channel", channel[0], image])
                self._interkey(macro)
            elif _plain_send(macro):
                out.append([name, "command", macro[0][1:], image])
            else:
                out.append([name, "macro", macro, image])
        if lost:
            self.notes.append(f"{lost} favourite(s) were imported without their logos")
        result = {"image_buttons": out}
        if confirm:
            result["channel_confirm"] = confirm
        dialled = [step[1] for _text, macro, _picture in entries if self._channel(macro)
                   for step in macro if step[0] == "command"]
        if dialled:
            result["channel_device"] = dialled[0]
        return result

    def _logo(self, slot: dict, position: int) -> list[list] | None:
        """The logo a favourite's button draws: none on a 650, whose favourites are
        labels in a page's corners."""
        return None

    def _save_logo(self, name: str, rows: list[list]) -> str | None:
        """Save a logo into the logos folder; the name a project gives it there."""
        from ... import imaging

        if self.logos is None:
            return None
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "favourite"
        target, number = self.logos / f"{stem}.png", 2
        while target.exists():
            target, number = self.logos / f"{stem}-{number}.png", number + 1
        try:
            self.logos.mkdir(parents=True, exist_ok=True)
            target.write_bytes(imaging.encode(rows))
        except OSError:
            return None
        from ... import paths
        try:
            return target.relative_to(paths.logos_dir()).as_posix()
        except ValueError:
            return str(target)

    def _interkey(self, macro: list[list]):
        """The wait between a device's digits, as its project field (press_interkey)."""
        for step in macro:
            if step[0] == "delay":
                device = next((item for item in self.devices if item["id"] == step[1]), None)
                if device is not None:
                    device.setdefault("press_interkey", step[2])
                return

    def _sent_digits(self) -> dict[tuple[str, str], str]:
        """The digit each number sender's tables send, by device id and command name:
        what a digit is when no key or name says so - a Polish 600's TV, whose digits
        are on no key and named by nothing but their place in the table."""
        if not hasattr(self, "_digits"):
            self._digits = {}
            for sender in self.image.number_senders:
                for table in sender["tables"]:
                    for digit, atom in enumerate(table):
                        for step in self.image.atom(*atom) if atom else ():
                            named = self.command(step[1]) if step[0] == SEND else None
                            if named:
                                self._digits.setdefault(tuple(named[:2]), str(digit))
        return self._digits

    def _digit(self, device_id: str, name: str) -> str | None:
        found = self._sent_digits().get((device_id, name))
        if found is not None:
            return found
        # Logitech's number sender sends a digit's one-block copy, which is read as its
        # key's command "(press)"
        name = name.removesuffix(" (press)")
        if name in DIGIT_KEYS:
            return DIGIT_KEYS[name]
        device = next((item for item in self.devices if item["id"] == device_id), None)
        for entry in (device or {}).get("commands") or []:
            if entry[0] == name:
                for key in entry[4] or ():
                    if key in DIGIT_KEYS:
                        return DIGIT_KEYS[key]
        return name if len(name) == 1 and name.isdigit() else None


# --- types, from the icons the menus draw

TYPE_ICONS_FILE = "platform/type-icons.json"
TYPE_ICONS_SCHEMA = "afterglow-harmony-one-type-icons/1"


def _rgba(picture: dict) -> list[list[tuple]]:
    return [[(0, 0, 0, 0) if pixel is None else (*pixel, 255) for pixel in row]
            for row in picture["rows"]]


def fingerprint(rows: list[list[tuple]]) -> str:
    """An icon's pixels as a fingerprint: the same icon is the same in any image."""
    import hashlib

    return hashlib.sha256(bytes([len(rows[0]), len(rows)]) + b"".join(
        bytes(pixel) for row in rows for pixel in row)).hexdigest()


def menu_icons(image: Image) -> list[dict]:
    """Every menu row's icon: none on a 650, whose device and activity menus are labels
    in a page's corners, so no row's type is read from a picture."""
    return []


def _known_icons() -> dict[str, dict[str, str]]:
    """Logitech's row icons by fingerprint, with their types (platform/type-icons.json)."""
    import json


    path = _default_scaffold() / TYPE_ICONS_FILE
    if not path.is_file():
        return {"devices": {}, "activities": {}}
    data = json.loads(path.read_text("utf-8"))
    if data.get("schema") != TYPE_ICONS_SCHEMA:
        raise ValueError(f"{path} declares {data.get('schema')!r}, not {TYPE_ICONS_SCHEMA!r}")
    return {"devices": data.get("devices", {}), "activities": data.get("activities", {})}


@lru_cache(maxsize=2)
def _own_icons(kind: str) -> dict[str, str]:
    """This scaffold's type icons as a build draws them on a menu row: none, as a 700's
    rows draw no icon."""
    return {}


def read_types(image: Image) -> dict[tuple[str, int], str]:
    """Each menu row's type, by ``(kind, key)``: a Logitech icon the scaffold knows, or
    one of this scaffold's icons as this backend draws it. A row whose icon is neither
    has no type read for it."""
    known = _known_icons()
    out = {}
    for row in menu_icons(image):
        kind = "devices" if row["kind"] == "device" else "activities"
        found = known[kind].get(row["fingerprint"]) or _own_icons(kind).get(row["fingerprint"])
        if found is not None:
            out[(row["kind"], row["key"])] = found
    return out


def _default_scaffold():
    from .scaffold import default_directory
    return default_directory()
