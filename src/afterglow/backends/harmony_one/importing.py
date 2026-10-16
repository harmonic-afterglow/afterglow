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

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import re
import struct
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from . import (
    activity_index, bitmap, command_index, gspm, ir_lowering, keys, labels, named_index,
    ui_index)
from .pages import (
    BUTTON_POSITIONS, FRAME_WIDTH, MENU_FRAME_XY, MENU_ICON_XY, TITLE_XY)

SEND, WAIT, WRITE, MODE, CONTEXT, SWITCH = "send", "wait", "write", "mode", "context", "switch"
OBJECT, COMMAND, DEVICE_OR_WAIT, ENTER_MODE = 0x7F, 0x7D, 0x7C, 0x7E
TESTS = (0x70, 0x71)
# What a button's frame covers below its top: its label's lines sit within it.
BUTTON_HEIGHT = 50
POWER_NAME = re.compile(r"^(?P<label>.+)_Power_2$")
INPUT_NAME = re.compile(r"^(?P<label>.+)_Input_(?P<count>\d+)$")
# Whether a smart TV's apps are up: Logitech's `<Label>_OnlinePower_2`, which a timer
# started at power-on sets after the apps' delay, and ours, `<Label>_Online_2`, which the
# first app after power-on sets after waiting the rest of that delay
# (devices.device_state_records).
ONLINE_NAME = re.compile(r"^(?P<label>.+)_Online(?P<power>Power)?_2$")
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
        for operand, opcode in atoms:
            # a test decides whether the next instruction runs: what it guards is not
            # something the object always does
            if guarded:
                guarded = False
                continue
            if opcode in TESTS:
                guarded = True
                continue
            out += self.atom(operand, opcode, depth)
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
            return [(WRITE, opcode & 0x7F, operand)]
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

    def join(self, lines: list[str]) -> str:
        """A label's lines as the name they were split from."""
        out = ""
        for line in lines:
            if not out:
                out = line
            elif (self.text.logitech and out[-1:].isalnum() and line[:1].isupper()
                  and " " not in line):
                out += line
            else:
                out += " " + line
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
        cases, cursor = [], at + 2
        for _case in range(payload[at + 1]):
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


def _button_label(items: list[dict], slot: int) -> str | None:
    """The text drawn on button ``slot``'s frame, top line first."""
    left, top = BUTTON_POSITIONS[slot]
    inside = [item for item in items
              if left <= item["x"] < left + FRAME_WIDTH and top <= item["y"] < top + BUTTON_HEIGHT]
    return [item["text"] for item in sorted(inside, key=lambda item: item["y"])] or None


# Where the six buttons' touch zones sit, in the panel's raw units (y counts upwards):
# two columns and three rows, as every template draws them (options.py measured them).
ZONE_COLUMNS = (1257, 2422)
ZONE_ROWS = (3016, 2144, 1272)
ZONE_SLACK = 40


def button_positions(image: Image, slot: dict) -> dict[int, int]:
    """Which of the six button places each touch key of a slot is, from its zone's
    rectangle: Logitech numbers a page's zones its own way, so the key code says
    nothing about where the button is."""
    out = {}
    for zone in image.templates.get(slot["template"], []):
        column = next((index for index, x in enumerate(ZONE_COLUMNS)
                       if abs(zone["x"] - x) <= ZONE_SLACK), None)
        row = next((index for index, y in enumerate(ZONE_ROWS)
                    if abs(zone["y"] - y) <= ZONE_SLACK), None)
        if column is not None and row is not None:
            out[0x80 | zone["tag"]] = 2 * row + column
    return out


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


SIDE_STRIPS = (0xAE, 0xAF)


def command_pages(image: Image) -> dict[int, list[int]]:
    """Each device's command pages, by device index: the screens another screen opens -
    its device-menu row - and those their side strips turn to, every one showing that
    device's commands only. A screen that also sends another device's - an activity's -
    is not one."""
    shape = {}
    for screen in image.screens:
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


def _same_title(title: str, label: str) -> bool:
    """Whether a page's title is ``label``, perhaps cut short to fit."""
    title = title.removesuffix("..")
    return label == title or (title != "" and label.startswith(title)
                              and title != label and len(title) >= 4)


def read_pages(image: Image, labels: dict[int, str] | None = None) -> dict[int, dict]:
    """Each device's command pages read: its title, each command's label, and the
    physical keys its pages bind, by device index, with ``buttons``: each button as
    ``(command, label)`` in the order the pages show them. Given the devices' ``labels``,
    a page titled otherwise - an activity's page showing one device's buttons - is not the
    device's."""
    labels = labels or {}
    out = {}
    for device, ordinals in command_pages(image).items():
        titles, names, bound, buttons = [], {}, {}, []
        page = 0
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
                for position, command in sorted((_touch_sends(image, slot) or {}).items()):
                    lines = _button_label(items, position)
                    if lines:
                        names.setdefault(command, image.join(lines))
                        # a place before this one with nothing in it was left empty
                        while len(buttons) < page * len(BUTTON_POSITIONS) + position:
                            buttons.append(None)
                        buttons.append((command, image.join(lines)))
            page += 1
            for entry in screen["header_entries"] + [
                    entry for slot in screen["slots"] for entry in slot["entries"]]:
                name = keys.name_of(entry["key_code"])
                if name is None or entry["category"] != OBJECT:
                    continue
                sends = [step for step in image.steps(entry["operand"]) if step[0] == SEND]
                if len(sends) == 1 and sends[0][1] >> 8 == device:
                    bound.setdefault(name, sends[0][1])
        out[device] = {"title": max(set(titles), key=titles.count) if titles else None,
                       "names": names, "keys": bound, "buttons": buttons}
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
    for record, device, kind in device_variables(image):
        _state(out[device], record, kind == "power", image, gates)
    return dict(out)


def _state(states: dict, record: dict, power, image: Image, gates=None):
    gates = gates or {}
    transitions = {(item["from"], item["to"]): item for item in record["transitions"]}

    def sent(item):
        if item is None or item["category"] != OBJECT:
            return [], 0
        steps = image.steps(item["operand"])
        return ([step[1] for step in steps if step[0] == SEND],
                sum(step[2] for step in steps if step[0] == WAIT))

    def sequence(item):
        """An input chosen in several steps - wake, step there, confirm - as its sends
        and waits."""
        return [(SEND, step[1]) if step[0] == SEND else (WAIT, step[2])
                for step in image.steps(item["operand"]) if step[0] in (SEND, WAIT)]
    if power:
        on, delay = sent(transitions.get((0, 1)))
        off, _wait = sent(transitions.get((1, 0)))
        if on and off:
            states["power"] = {"on": on[0], "off": off[0], "delay_ms": delay}
        return
    count = record["limit"] + 1
    direct = [item for item in record["transitions"] if item["from"] in ANY]
    if direct:
        chosen = [None] * count
        online, app = [], None
        for item in direct:
            if not 0 <= item["to"] < count:
                continue
            steps = sequence(item) if item["category"] == OBJECT else []
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
            # object, its 0x7C in tenths (Kāt's Hisense: InputDelay 1000, 10 there and on
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
            commands.append(None if not sends else sends[0][1] if steps == sends[:1]
                            else steps)
        states["inputs"] = {"direct": commands}
        if delay:
            states["inputs"]["delay_ms"] = delay
        if online and app:
            states["inputs"]["online"] = sorted(online)
            states["inputs"]["app_delay_ms"] = app
        return
    step = transitions.get((0, 1))
    if step is not None:
        commands, delay = sent(step)
        if commands:
            states["inputs"] = {"next": commands[0], "delay_ms": delay, "count": count}


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


def project_devices(image: Image, native: list[dict], notes: list[str] | None = None,
                    naming: dict | None = None) -> list[dict]:
    """The project's devices: ``native`` (command_index.portable_devices, every command
    with its waveform and a numbered name) given their names, power, inputs and keys.
    What could not be carried over is said in ``notes``; ``naming``, when given, is
    filled with each command id's device id and name, which activities refer to."""
    notes = [] if notes is None else notes
    named = variable_labels(image)
    pages = read_pages(image, named)
    states = read_states(image)
    out = []
    for device in native:
        index = device["native"]["harmony-one"]["device_index"]
        page = pages.get(index, {"title": None, "names": {}, "keys": {}, "buttons": []})
        state = states.get(index, {})
        ids = {signal["native"]["harmony-one"]["command_id"]: name
               for name, signal in device["signals"].items()}
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
                                if command not in same}, page, state, copies)
        names.update({command: names[twin] for command, twin in same.items()})
        slots = defaultdict(list)
        for key, command in page["keys"].items():
            slots[same.get(command, command)].append(key)
        signals = {names[command]: dict(device["signals"][old], name=names[command])
                   for command, old in ids.items() if command not in same}
        label = named.get(index) or page["title"] or device["label"]
        # A command the configuration's pages do not show - a press-only copy, a code
        # with no name, one on a key - keeps no label, so a rebuild leaves it off too.
        project = dict(device, label=label, signals=signals, commands=[
            [names[command], names[command] if command in page["names"] else "", "", "",
             sorted(slots[command]) or None]
            for command in ids if command not in same])
        # The pages as drawn: which buttons, in what order, under which names.
        project["screen_buttons"] = [
            None if button is None else [names[same.get(button[0], button[0])], button[1]]
            for button in page["buttons"]
            if button is None or same.get(button[0], button[0]) in names]
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


def _command_names(ids: dict[int, str], page: dict, state: dict,
                   copies: dict[int, str] | None = None) -> dict[int, str]:
    """Each command's name: its button's label, else the key it is bound to, else the
    command it is a press-only copy of, else the part it plays in the device's power or
    inputs, else its numbered name. Two commands never share one."""
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
    inputs = state.get("inputs") or {}
    if "next" in inputs:
        roles[inputs["next"]] = "InputNext"
    for value, command in enumerate(inputs.get("direct") or []):
        if isinstance(command, int):
            roles.setdefault(command, f"Input{value + 1}")
    out, used = {}, set()
    # the drawn names first, so a key's or a role's name never takes a button's own
    for source in (page["names"], by_key, copies or {}, roles, ids):
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
    power = state.get("power")
    if power:
        if power["on"] == power["off"]:
            out["power_cmd"] = names[power["on"]]
        else:
            out["power_on_cmd"], out["power_off_cmd"] = names[power["on"]], names[power["off"]]
        out["power_delay"] = power["delay_ms"]
    inputs = state.get("inputs")
    if inputs and "direct" in inputs:
        out["inputs"] = []
        for value, chosen in enumerate(inputs["direct"]):
            if chosen is None:
                out["inputs"].append([f"Input {value + 1}"])
            elif isinstance(chosen, list):
                # a sequence, as the project's inputs take one: commands and waits
                out["inputs"].append([f"Input {value + 1}", [
                    names[item] if kind == SEND else {"delay_ms": item}
                    for kind, item in chosen]])
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
                        rows[targets[0]] = places[entry["key_code"]] // 2
                if not rows:
                    continue
                items = self.image.page_text(slot["program_offset"])
                for context, row in rows.items():
                    top = BUTTON_POSITIONS[2 * row][1]
                    lines = [item["text"] for item in sorted(items, key=lambda item: item["y"])
                             if top <= item["y"] < top + BUTTON_HEIGHT + 4 and item["x"] > 40]
                    if lines:
                        out.setdefault(context, " ".join(lines))
        return out

    def command(self, command_id: int) -> tuple[str, str] | None:
        return self.naming.get(command_id)

    def macro(self, steps: list[tuple]) -> list[list] | None:
        """Sends and waits as a project's macro steps; None when they do anything else
        a macro cannot say."""
        out = []
        for step in steps:
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
            if listed:
                extra["power_off_all"] = listed
        return activities, extra

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
        out = {"id": str(ordinal), "label": label, "type": None,
               "power_on_devices": list(dict.fromkeys(on)),
               "enter": inputs + (self.macro(steps) or []),
               "leave": self.macro([step for step in hooks.get(activity_index.LEAVE, [])
                                    if step[0] in (SEND, WAIT)]) or []}
        out.update(self.key_fields(hooks))
        out["display"] = self._display(on, inputs) or out["control"]
        out.update(self.screens(label))
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
        control = max(set(others), key=others.count) if others else volume
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
        pages = 0                     # pages of buttons so far, for where a gap falls
        for screen in self.image.screens:
            for slot in screen["slots"]:
                items = self.image.page_text(slot["program_offset"])
                if not any((item["x"], item["y"]) == TITLE_XY and item["text"] == label
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
                on_page = False
                for position, steps in sorted(found or ()):
                    lines = _button_label(items, position)
                    macro = self.macro(steps)
                    if not macro:
                        continue
                    text = " ".join(lines) if lines else None
                    # a button that dials a channel is a favourite, named or with a logo;
                    # one with a logo and no name is too
                    if self._channel(macro) or text is None:
                        logo = None if text else self._logo(slot, position)
                        favourites.append((text, macro, logo))
                    else:
                        # a place before this one with nothing in it was left empty
                        while len(buttons) < pages * len(BUTTON_POSITIONS) + position:
                            buttons.append(None)
                        buttons.append([text, *macro[0][1:]] if _plain_send(macro)
                                       else {"label": text, "macro": macro})
                        on_page = True
                pages += on_page
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
        return result

    def _logo(self, slot: dict, position: int) -> list[list] | None:
        """The logo a favourite's button draws, as rows of RGBA pixels. Logitech draws it
        over the button's frame as a picture of its own; this backend composes it onto
        the frame, so its centred box (pictures.LOGO_BOX) is the logo."""
        from .pictures import LOGO_BOX

        place = BUTTON_POSITIONS[position]
        try:
            drawn = [item for item in ui_index.drawing_program(
                self.image.payload, slot["program_offset"])["instructions"]
                if item["opcode"] == "bitmap" and (item["x"], item["y"]) == place]
            pictures = [bitmap.decode(self.image.payload, item["target"]) for item in drawn]
        except ValueError:
            return None
        if not pictures:
            return None
        rows = _rgba(pictures[-1])
        # Logitech draws the plain button, then the button again with the logo on it.
        # The button is taken out - against the configuration's own when it is drawn
        # first, else against this scaffold's - and the logo's box kept: a build puts it
        # back on the button, and a logo that kept its button had it twice.
        if len(pictures) > 1:
            rows = without_frame(rows, _rgba(pictures[0]), OWN_FRAME_TOLERANCE)
        else:
            rows = without_frame(rows, _button_frame(position))
        width, height = len(rows[0]), len(rows)
        left, top = (width - LOGO_BOX[0]) // 2, (height - LOGO_BOX[1]) // 2
        if left < 0 or top < 0:
            return rows if len(pictures) > 1 else None
        return [row[left:left + LOGO_BOX[0]] for row in rows[top:top + LOGO_BOX[1]]]

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

    def _digit(self, device_id: str, name: str) -> str | None:
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


# How far a pixel of a logo drawn onto its button may be from the button and still be the
# button: the One dithers a picture's colours, so even the configuration's own button
# differs from the one under the logo by up to 9 steps; this scaffold's, by more.
OWN_FRAME_TOLERANCE = 10
FRAME_TOLERANCE = 24
# A logo drawn onto the frame is told from a picture of its own by the edge of its box,
# where a logo seldom reaches: most of that is the frame, or it is not there at all.
FRAME_EDGE_SHARE = 0.6


def without_frame(rows: list[list[tuple]], frame,
                  tolerance: int = FRAME_TOLERANCE) -> list[list[tuple]]:
    """A favourite's picture with the button behind its logo taken out.

    Where the picture is the button `frame` - rows of RGBA, the same size - and reached
    from the picture's edge through more of the button, those pixels become transparent:
    a blue logo on a blue button keeps the blue inside it, which is near the button's
    colour but is the logo's. Only when it is that button: most of the edge of the logo's
    box, where a logo seldom reaches, has to match, so a picture on another button, a
    theme's or a hand-made one, is left as it is."""
    from .pictures import LOGO_BOX

    if frame is None or len(frame) != len(rows) or len(frame[0]) != len(rows[0]):
        return rows

    def same(a, b):
        return a[3] and b[3] and max(abs(a[i] - b[i]) for i in range(3)) <= tolerance

    width, height = len(rows[0]), len(rows)
    left, top = (width - LOGO_BOX[0]) // 2, (height - LOGO_BOX[1]) // 2
    edge = [(x, y) for y in range(top, top + LOGO_BOX[1]) for x in range(left, left + LOGO_BOX[0])
            if x in (left, left + 1, left + LOGO_BOX[0] - 2, left + LOGO_BOX[0] - 1)
            or y in (top, top + 1, top + LOGO_BOX[1] - 2, top + LOGO_BOX[1] - 1)]
    matching = sum(same(rows[y][x], frame[y][x]) for x, y in edge)
    if matching < FRAME_EDGE_SHARE * len(edge):
        return rows
    # a pixel already clear counts as the button: the picture's rounded edge is, and
    # the way in from the outside starts there
    button = [[not pixel[3] or same(pixel, under) for pixel, under in zip(row, frame_row)]
              for row, frame_row in zip(rows, frame)]
    # the button: what matches it and joins the picture's edge through more that does
    pending = [(x, y) for y in range(height) for x in range(width)
               if (x in (0, width - 1) or y in (0, height - 1)) and button[y][x]]
    reached = set(pending)
    while pending:
        x, y = pending.pop()
        for near in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            nx, ny = near
            if 0 <= nx < width and 0 <= ny < height and near not in reached \
                    and button[ny][nx]:
                reached.add(near)
                pending.append(near)
    out = [[(0, 0, 0, 0) if (x, y) in reached else pixel for x, pixel in enumerate(row)]
           for y, row in enumerate(rows)]
    # The logo's drop shadow was drawn onto the button too: next to it, pixels that are
    # the button darkened alike in red, green and blue. Each becomes the shadow it was -
    # black, as clear as it let the button through - so it falls on any button.
    # A drop shadow falls below the logo, so it is looked for upward from the button
    # under it: a blue logo's dark edge at its sides is the logo's.
    above_button = [(x, y) for y in range(height) for x in range(width)
                    if (x, y) not in reached and (x, y + 1) in reached]
    for x, y in sorted(_shadow_reach(above_button, reached, width, height),
                       key=lambda point: -point[1]):
        shade = _shade(rows[y][x], frame[y][x])
        below = out[y + 1][x] if y + 1 < height else (0, 0, 0, 0)
        # a shadow climbs up from the button without a gap: the logo ends it
        if shade is not None and (below[3] == 0 or below[:3] == (0, 0, 0)):
            out[y][x] = (0, 0, 0, shade)
    return out


SHADOW_DEPTH = 6          # how far into the logo a shadow is looked for, in pixels


def _shadow_reach(start, reached, width, height):
    """The pixels up to SHADOW_DEPTH above the button that was taken out, while each is
    still a shadow - a logo's own colour stops the climb."""
    seen = set()
    for x, y in start:
        for step in range(SHADOW_DEPTH):
            if y - step < 0 or (x, y - step) in reached:
                break
            seen.add((x, y - step))
    return seen


def _shade(pixel, under) -> int | None:
    """How opaque a black shadow must be to make `under` look like `pixel`; None when
    `pixel` is not `under` darkened alike in every channel - a colour of the logo's."""
    if not pixel[3] or not under[3]:
        return None
    ratios = [pixel[i] / under[i] for i in range(3) if under[i] >= 24]
    if not ratios or max(ratios) >= 0.97 or max(ratios) - min(ratios) > 0.12:
        return None
    if any(pixel[i] > under[i] + 6 for i in range(3)):
        return None
    return round((1 - sum(ratios) / len(ratios)) * 255)


@lru_cache(maxsize=None)
def _button_frame(position: int):
    """This scaffold's favourite button for a place, as rows of RGBA; None without one."""
    from ... import imaging, paths
    from . import assets

    directory = paths.scaffolds("harmony-one")
    pictures = assets.read_manifest(directory)["pictures"]
    for role in (f"activity/button-frame/{position}", f"button-frame/{position}"):
        if role in pictures:
            data = (directory / pictures[role]["file"]).read_bytes()
            return tuple(tuple(row) for row in imaging.decode(data)["rows"])
    return None


def _rgba(picture: dict) -> list[list[tuple]]:
    return [[(0, 0, 0, 0) if pixel is None else (*pixel, 255) for pixel in row]
            for row in picture["rows"]]


def fingerprint(rows: list[list[tuple]]) -> str:
    """An icon's pixels as a fingerprint: the same icon is the same in any image."""
    import hashlib

    return hashlib.sha256(bytes([len(rows[0]), len(rows)]) + b"".join(
        bytes(pixel) for row in rows for pixel in row)).hexdigest()


def menu_icons(image: Image) -> list[dict]:
    """Every device-menu and Activities-menu row's icon: ``{kind, key, label, icon,
    frame, at, fingerprint}``, ``key`` the device index or the activity's context.
    Read once per image: the types and the theme are both read from it."""
    if getattr(image, "_menu_icons", None) is None:
        image._menu_icons = _menu_icons(image)
    return image._menu_icons


def _menu_icons(image: Image) -> list[dict]:
    pages = {ordinal: device for device, ordinals in command_pages(image).items()
             for ordinal in ordinals}
    out, seen = [], set()
    for screen in image.screens:
        for slot in screen["slots"]:
            places = button_positions(image, slot)
            rows = {}
            for entry in slot["entries"]:
                position = places.get(entry["key_code"])
                if position is None or position % 2:
                    continue
                steps = image.row(entry)
                contexts = [step[1] for step in steps if step[0] == CONTEXT]
                target = _navigation(image, entry)
                if contexts:
                    rows[position // 2] = ("activity", contexts[0])
                elif target in pages:
                    rows[position // 2] = ("device", pages[target])
            if not rows:
                continue
            try:
                program = ui_index.drawing_program(image.payload, slot["program_offset"])
                drawn = {(item["x"], item["y"]): item["target"]
                         for item in program["instructions"] if item["opcode"] == "bitmap"}
            except ValueError:
                continue
            items = image.page_text(slot["program_offset"])
            for row, (kind, key) in rows.items():
                if (kind, key) in seen or MENU_ICON_XY[row] not in drawn \
                        or MENU_FRAME_XY[row] not in drawn:
                    continue
                try:
                    icon = _rgba(bitmap.decode(image.payload, drawn[MENU_ICON_XY[row]]))
                    frame = _rgba(bitmap.decode(image.payload, drawn[MENU_FRAME_XY[row]]))
                except ValueError:
                    continue
                seen.add((kind, key))
                top = MENU_FRAME_XY[row][1]
                label = " ".join(item["text"] for item in sorted(items, key=lambda item: item["y"])
                                 if top <= item["y"] < top + BUTTON_HEIGHT + 4 and item["x"] > 40)
                out.append({"kind": kind, "key": key, "label": label, "icon": icon,
                            "frame": frame, "fingerprint": fingerprint(icon),
                            "at": (MENU_ICON_XY[row][0] - MENU_FRAME_XY[row][0],
                                   MENU_ICON_XY[row][1] - MENU_FRAME_XY[row][1])})
    return out


def _known_icons() -> dict[str, dict[str, str]]:
    """Logitech's row icons by fingerprint, with their types (platform/type-icons.json)."""
    import json

    from ... import paths

    path = paths.scaffolds("harmony-one") / TYPE_ICONS_FILE
    if not path.is_file():
        return {"devices": {}, "activities": {}}
    data = json.loads(path.read_text("utf-8"))
    if data.get("schema") != TYPE_ICONS_SCHEMA:
        raise ValueError(f"{path} declares {data.get('schema')!r}, not {TYPE_ICONS_SCHEMA!r}")
    return {"devices": data.get("devices", {}), "activities": data.get("activities", {})}


@lru_cache(maxsize=2)
def _own_icons(kind: str) -> dict[str, str]:
    """This scaffold's type icons as a build draws them on a menu row - composed on the
    row frame, then stored in the remote's colours: their fingerprints, with their
    types."""
    from ... import paths
    from . import assets, row_icons
    from .pictures import ROW_ICON_SIZE, _composed

    directory = paths.scaffolds("harmony-one")
    manifest = assets.read_manifest(directory)
    frame = ("activity/row-frame" if kind == "activities"
             and "activity/row-frame" in manifest["pictures"] else "row-frame")
    if frame not in manifest["pictures"]:
        return {}
    at = (MENU_ICON_XY[0][0] - MENU_FRAME_XY[0][0], MENU_ICON_XY[0][1] - MENU_FRAME_XY[0][1])
    out = {}
    for path in sorted((directory / row_icons.ICONS_DIR / kind).glob("*.png")):
        body = _composed(directory, manifest, frame, at, ROW_ICON_SIZE, kind, path.stem)
        out.setdefault(fingerprint(_rgba(bitmap.decode(body, 0))), path.stem)
    return out


DEFAULT, CUSTOM = "default", "custom"
# How much of a menu row's frame has to be this scaffold's for the image to wear
# Logitech's own look: the One dithers its pictures, so not every pixel matches.
THEME_MATCH = 0.9


def read_theme(image: Image) -> str | None:
    """Whether the image wears Logitech's own look - the one this scaffold builds - or
    a theme of someone's: DEFAULT or CUSTOM, by its menu rows' frame; None when it has
    no menu row to tell by."""
    from ... import imaging, paths
    from . import assets

    directory = paths.scaffolds("harmony-one")
    pictures = assets.read_manifest(directory)["pictures"]
    for row in menu_icons(image):
        role = ("activity/row-frame" if row["kind"] == "activity"
                and "activity/row-frame" in pictures else "row-frame")
        if role not in pictures:
            continue
        ours = imaging.decode((directory / pictures[role]["file"]).read_bytes())["rows"]
        theirs = row["frame"]
        if len(ours) != len(theirs) or len(ours[0]) != len(theirs[0]):
            return CUSTOM
        pixels = [(a, b) for row_a, row_b in zip(theirs, ours) for a, b in zip(row_a, row_b)]
        alike = sum(a[3] == b[3] and (not a[3] or max(abs(a[i] - b[i]) for i in range(3))
                                      <= FRAME_TOLERANCE) for a, b in pixels)
        return DEFAULT if alike >= THEME_MATCH * len(pixels) else CUSTOM
    return None


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
