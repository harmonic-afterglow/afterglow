"""A generated Harmony One's activities, run the way the remote runs them.

The interpreter here follows the Harmony 800's (gspm.md): a write fires the variable's
transitions, selecting a context runs the old one's leave and the new one's enter (or its
tag 5 when it is already running), a switch runs the program its table gives the
variable's value. What reaches the infrared queue is logged as device and command.
"""
from __future__ import annotations

import struct

import pytest

from afterglow import ir_signal
from afterglow.backends.harmony_one import (
    activities, activity_index, command_index, generate, gspm, keys, ui_index)

ENTER, LEAVE, REFRESH = activity_index.ENTER, activity_index.LEAVE, activity_index.REFRESH


def _nec(address: int, command: int):
    pulses = [9000, -4500]
    for byte in (address, ~address & 0xFF, command, ~command & 0xFF):
        for bit in range(8):
            pulses += [560, -1690] if (byte >> bit) & 1 else [560, -560]
    return ir_signal.waveform(pulses + [560, -40000], carrier_hz=38000)


def _device(did, label, kind, address, slots, **extra):
    names = list(slots)
    return {"id": did, "label": label, "type": kind,
            "signals": {name: _nec(address, n + 1) for n, name in enumerate(names)},
            "commands": [[name, name, "", "", slots[name]] for name in names], **extra}


TV = _device("tv", "Living Room TV", "Television", 4, {
    "PowerOn": None, "PowerOff": None, "InputHdmi1": None, "InputHdmi2": None,
    "VolumeUp": "VolumeUp", "Mute": "VolumeMute", "ChannelUp": "ChannelUp",
    "Guide": "Guide", "Menu": "Menu", "Select": "Select", "1": "Number1", "2": "Number2"},
    power_on_cmd="PowerOn", power_off_cmd="PowerOff", power_delay=3000,
    inputs=[["HDMI1", "InputHdmi1"], ["HDMI2", "InputHdmi2"]])
AMP = _device("amp", "Receiver", "Amplifier", 11, {
    "Power": None, "VolumeUp": "VolumeUp", "Mute": "VolumeMute", "InputCd": None,
    "InputTv": None}, power_cmd="Power", power_delay=2000,
    inputs=[["CD", "InputCd"], ["TV", "InputTv"]])
PROJECT = {"devices": [TV, AMP], "activities": [
    {"id": "1", "label": "Watch TV", "type": "VirtualTelevisionN",
     "display": "tv", "volume": "amp", "control": "tv",
     "enter": [["input", "tv", "HDMI1"], ["input", "amp", "TV"]],
     "soft_buttons": [["Guide", "tv", "Guide"],
                      {"label": "Movie", "macro": [["command", "tv", "Menu"],
                                                   ["delay", "tv", 500],
                                                   ["command", "tv", "Select"]]}],
     "hard_macros": {"Info": [["number", "tv", "12"]]}},
    {"id": "2", "label": "Listen to Music", "type": "VirtualCdMulti",
     "volume": "amp", "control": "amp", "power_on_devices": ["amp"],
     "enter": [["input", "amp", "CD"]]},
]}


class _Remote:
    def __init__(self, image):
        self.image = image
        self.objects = command_index.objects(image)
        self.records = activity_index.engine_records(image)
        self.variables = {index: record["initial"] for index, record in enumerate(self.records)}
        self.contexts = activity_index.contexts(image)
        self.screens = ui_index.screen_slots(image)
        self.byte, self.mode, self.context, self.silent = 0, None, None, False
        self.sent, self.log = [], []

    def header(self, ordinal):
        trailer = self.screens[ordinal]["trailer_offset"]
        head = int.from_bytes(self.image[trailer + 1:trailer + 4], "little") - gspm.BASE
        return {self.image[head + 1 + 4 * row]:
                struct.unpack_from("<HB", self.image, head + 2 + 4 * row)
                for row in range(self.image[head])}

    def row(self, context, key):
        for row in self.contexts[context]["rows"]:
            if row["key_code"] == key:
                return row["operand"], row["category"]
        return None

    def group(self, group, value):
        at = int.from_bytes(self.image[gspm.section_ranges(self.image)[15][0] + 1 + 3 * group:
                                       gspm.section_ranges(self.image)[15][0] + 4 + 3 * group],
                            "little") - gspm.BASE + 1
        count = self.image[at]
        for k in range(count):
            case, = struct.unpack_from("<H", self.image, at + 1 + 5 * k)
            if case == value:
                return int.from_bytes(self.image[at + 3 + 5 * k:at + 6 + 5 * k],
                                      "little") - gspm.BASE
        at += 1 + 5 * count
        for k in range(self.image[at]):
            low, high = struct.unpack_from("<HH", self.image, at + 1 + 7 * k)
            if low <= value <= high:
                return int.from_bytes(self.image[at + 5 + 7 * k:at + 8 + 7 * k],
                                      "little") - gspm.BASE
        return None

    def run(self, *instructions):
        skip = False
        for operand, opcode in instructions:
            if skip:
                skip = False
                continue
            high, low = operand >> 8, operand & 0xFF
            if opcode == 0x7F:
                self.run(*self.objects[operand]["atoms"])
            elif opcode in (0x70, 0x71):
                value = self.variables.get(low, 0)
                held = [value == self.byte, value != self.byte, value < self.byte,
                        value > self.byte, value <= self.byte, value >= self.byte][high & 0xF]
                skip = held if high & 0x80 else not held
            elif opcode == 0x1F and high == 0xFB:
                self.byte = low
            elif opcode == 0x1F and high == 0xFF:
                self.select(low)
            elif opcode == 0x7D:
                self.sent.append((high, low))
            elif opcode == 0x7C:
                self.log.append(("wait", high, low))
            elif opcode == 0x72:
                program = self.group(high, self.variables.get(low, 0))
                if program is not None:
                    self.run(*[(item["operand"], item["category"]) for item in
                               ui_index.drawing_program(self.image, program)["instructions"]
                               if item["opcode"] == "atom"])
            elif opcode >= 0x80:
                self.write(opcode & 0x7F, operand)
            elif opcode == 0x7E:
                self.enter(operand)
            elif (operand, opcode) == (0xFFFF, 0x07):
                self.silent = True
            else:
                self.log.append((operand, opcode))

    def write(self, variable, value):
        old = self.variables.get(variable, 0)
        self.variables[variable] = value
        if self.silent:
            self.silent = False
            return
        for t in self.records[variable]["transitions"]:
            if t["to"] == value and (t["from"] == old or t["from"] == 0xFFFE
                                     or (t["from"] == 0xFFFD and old != value)):
                self.run((t["operand"], t["category"]))

    def select(self, context):
        if context == self.context:
            tags = [(context, REFRESH)]
        else:
            tags = ([(self.context, LEAVE)] if self.context is not None else []) + [
                (context, ENTER)]
            self.context = context
        for index, tag in tags:
            found = self.row(index, tag)
            if found:
                self.run(found)

    def enter(self, ordinal):
        self.mode = ordinal
        if 0x06 in self.header(ordinal):
            self.run(self.header(ordinal)[0x06])

    def touch(self, key):
        slot = self.screens[self.mode]["slots"][0]
        [entry] = [e for e in slot["entries"] if e["key_code"] == key]
        self.run((entry["operand"], entry["category"]))

    def press(self, key):
        """A physical key: the screen's own list first, then the running activity's
        context, then the events context - the stack every image pushes."""
        header = self.header(self.mode)
        if key in header:
            self.run(header[key])
            return
        for context in (self.context, generate.EVENT_CONTEXT):
            found = context is not None and self.row(context, key)
            if found:
                self.run(found)
                return


def _built():
    return generate.build(PROJECT)


def _command(name, device=0):
    """(device, ordinal) for a command, as lowered: commands are sorted by name."""
    names = sorted((PROJECT["devices"][device]["signals"]))
    return device, names.index(name)


@pytest.fixture(scope="module")
def remote():
    built = _built()
    return built


YES, NO = generate.FIRST_BUTTON_KEY + 4, generate.FIRST_BUTTON_KEY + 5


def _start(machine, row):
    """Start the activity on menu row ``row`` and tell the Remote Assistant it worked."""
    machine.enter(generate.scaffold.SYSTEM_SCREENS)
    machine.touch(generate.MENU_ROW_KEYS[row])
    machine.touch(YES)


def _fresh(built):
    machine = _Remote(built["image"])
    off = len(machine.contexts) - 1
    machine.select(off)            # as start-up leaves it: Off's context, nothing running
    machine.sent.clear()
    return machine


def test_an_activity_switches_its_devices_on_sets_their_inputs_and_shows_its_screen(remote):
    machine = _fresh(remote)
    _start(machine, 0)                                        # Watch TV
    assert machine.sent == [_command("PowerOn"), _command("Power", 1),
                            _command("InputHdmi1"), _command("InputTv", 1)]
    # the TV's power-on delay holds its next send back, a hundred tenths at a time
    assert ("wait", 0, 30) in machine.log
    texts = [machine.mode]
    assert machine.mode != generate.scaffold.SYSTEM_SCREENS
    # picking it again re-sends its inputs and nothing else, and asks nothing
    machine.sent.clear()
    machine.enter(generate.scaffold.SYSTEM_SCREENS)
    machine.touch(generate.MENU_ROW_KEYS[0])
    assert machine.sent == [_command("InputHdmi1"), _command("InputTv", 1)]
    assert machine.mode == texts[0]


def test_switching_activities_turns_off_what_the_next_one_does_not_use(remote):
    machine = _fresh(remote)
    _start(machine, 0)
    machine.sent.clear()
    machine.enter(generate.scaffold.SYSTEM_SCREENS)
    machine.touch(generate.MENU_ROW_KEYS[1])                  # Listen to Music
    machine.touch(YES)
    assert machine.sent == [_command("InputCd", 1), _command("PowerOff")]


def test_off_turns_everything_off_and_goes_back_to_the_activities_menu(remote):
    machine = _fresh(remote)
    _start(machine, 0)
    machine.sent.clear()
    machine.press(keys.code(keys.OFF))
    assert sorted(machine.sent) == sorted([_command("PowerOff"), _command("Power", 1)])
    assert machine.mode == generate.scaffold.SYSTEM_SCREENS


def test_the_keypad_follows_the_activity_roles_and_its_own_keys(remote):
    machine = _fresh(remote)
    _start(machine, 0)
    for name, expected in (("VolumeUp", [_command("VolumeUp", 1)]),
                           ("VolumeMute", [_command("Mute", 1)]),
                           ("ChannelUp", [_command("ChannelUp")]),
                           ("Info", [_command("1"), _command("2")])):
        machine.sent.clear()
        machine.press(keys.by_name(name))
        assert machine.sent == expected, name


def test_a_screen_button_sends_its_command_or_runs_its_macro(remote):
    machine = _fresh(remote)
    _start(machine, 0)
    machine.sent.clear()
    machine.touch(generate.FIRST_BUTTON_KEY)
    assert machine.sent == [_command("Guide")]
    machine.sent.clear()
    machine.touch(generate.FIRST_BUTTON_KEY + 1)
    assert machine.sent == [_command("Menu"), _command("Select")]
    assert ("wait", 0, 5) in machine.log


def test_help_resends_what_the_activity_set_but_never_a_toggle(remote):
    machine = _fresh(remote)
    _start(machine, 0)
    screen = machine.mode
    machine.sent.clear()
    machine.press(keys.code(keys.HELP))
    # the TV's own power-on and both inputs again; the receiver's toggle would turn it off
    assert machine.sent == [_command("PowerOn"), _command("InputHdmi1"),
                            _command("InputTv", 1)]
    # then the Remote Assistant asks whether that did it; Yes goes back to the activity
    machine.touch(YES)
    assert machine.mode == screen


def test_device_screens_bind_the_device_keys_and_return_to_the_running_activity(remote):
    machine = _fresh(remote)
    _start(machine, 0)
    activity_screen = machine.mode
    machine.touch(generate.PAGE_DEVICES_KEY)                  # the device list
    machine.touch(generate.MENU_ROW_KEYS[1])                  # the receiver
    machine.sent.clear()
    machine.press(keys.by_name("VolumeUp"))
    assert machine.sent == [_command("VolumeUp", 1)]
    machine.sent.clear()
    machine.press(keys.by_name("ChannelUp"))                  # the receiver has none
    assert machine.sent == []
    machine.touch(generate.PAGE_ACTIVITIES_KEY)
    assert machine.mode == activity_screen


def test_the_activities_key_opens_the_menu_and_goes_back_from_it(remote):
    machine = _fresh(remote)
    _start(machine, 0)
    activity_screen = machine.mode
    machine.press(keys.code(keys.ACTIVITIES))
    assert machine.mode == generate.scaffold.SYSTEM_SCREENS
    machine.press(keys.code(keys.ACTIVITIES))
    assert machine.mode == activity_screen


def test_a_step_the_one_cannot_take_is_reported_and_a_missing_command_refused():
    project = {**PROJECT, "activities": [dict(PROJECT["activities"][0], enter=[
        ["input", "tv", "HDMI1"], ["state", "tv", "InputType", "Digital"]])]}
    planned = activities.plan(project, generate.lowered_devices(project))
    assert len(planned["skipped"]) == 1
    broken = {**PROJECT, "activities": [dict(PROJECT["activities"][0], soft_buttons=[
        ["Nothing", "tv", "NoSuchCommand"]])]}
    with pytest.raises(ValueError, match="NoSuchCommand"):
        activities.plan(broken, generate.lowered_devices(broken))


def test_every_charge_context_the_key_stack_can_select_is_there(remote):
    # `1F E8xx` puts context xx under 0xFC on the key stack, which the firmware looks up
    # before the screen itself (the Harmony 800's key lookup, gspm.md). Every one a build
    # selects must exist and only pass the battery events on, or a remote on USB would
    # look its keys up in an activity's context, or past the end of section 10.
    image = remote["image"]
    contexts = activity_index.contexts(image)
    chosen = {operand & 0xFF for item in command_index.objects(image)
              for operand, opcode in item["atoms"] if opcode == 0x1F and operand >> 8 == 0xE8}
    assert chosen == set(generate.CHARGE_CONTEXTS.values())
    for index in chosen:
        rows = contexts[index]["rows"]
        assert {row["key_code"] for row in rows} <= set(range(0x18, 0x1F))
        assert all(row["flags"] == 1 for row in rows)


def test_every_screen_draws_only_what_the_image_holds(remote):
    # A page program is built twice, measured and then written; a switch block made on the
    # second build was never laid out and pointed past the image.
    from afterglow.backends.harmony_one import drawing

    image = remote["image"]
    roots = [slot["program_offset"] for screen in ui_index.screen_slots(image)
             for slot in screen["slots"]]
    blocks = drawing.program_blocks(image, roots)
    assert all(0 <= at < len(image) for at in blocks)


def test_a_held_step_sends_one_record_held_that_long_and_shows_no_button():
    # Logitech's sequences can hold a command - a television that only turns off on a
    # two-second press. The One holds a code only while a key is down, so the build
    # writes the hold as a record of its own: the press, then repeats for that long.
    project = {**PROJECT, "activities": [dict(PROJECT["activities"][0], soft_buttons=[
        {"label": "Off", "macro": [["command", "tv", "PowerOff", "Press", 2000]]}])]}
    built = generate.build(project)
    machine = _fresh(built)
    _start(machine, 0)
    machine.sent.clear()
    machine.touch(generate.FIRST_BUTTON_KEY)
    [(device, ordinal)] = machine.sent
    assert device == 0 and ordinal == len(TV["signals"])          # a record of its own
    record = command_index.inspect(built["image"])["devices"][0]["commands"][ordinal]
    pulses = record["waveforms"]["press"]["pulses_us"]
    assert sum(abs(pulse) for pulse in pulses) >= 2_000_000
    # and no device page offers it: the image has the screens a plain press would give
    plain = {**PROJECT, "activities": [dict(PROJECT["activities"][0], soft_buttons=[
        {"label": "Off", "macro": [["command", "tv", "PowerOff"]]}])]}
    assert len(ui_index.screen_slots(built["image"])) == len(
        ui_index.screen_slots(generate.build(plain)["image"]))


def test_the_remote_assistant_asks_after_a_start_and_fixes_what_is_not_on(remote):
    # Logitech's Remote Assistant: after a start, did everything turn on? No asks about
    # each device and input in turn; No to one sends its power - a toggle too, since the
    # remote has just been told the device is off - and asks again.
    machine = _fresh(remote)
    machine.enter(generate.scaffold.SYSTEM_SCREENS)
    machine.touch(generate.MENU_ROW_KEYS[0])
    prompt = machine.mode
    machine.touch(NO)                       # not everything: is the TV on?
    first = machine.mode
    assert first != prompt
    machine.sent.clear()
    machine.touch(NO)                       # the TV is not on: its power, asked again
    assert machine.sent == [_command("PowerOn")] and machine.mode == first
    machine.touch(YES)                      # is the receiver on?
    machine.sent.clear()
    machine.touch(NO)
    assert machine.sent == [_command("Power", 1)]
    machine.touch(YES)                      # is the TV on HDMI1?
    machine.sent.clear()
    machine.touch(NO)
    assert machine.sent == [_command("InputHdmi1")]
    machine.touch(YES)
    machine.touch(YES)                      # the receiver's input: done
    # back on the activity's own first page, where its buttons are
    assert generate.FIRST_BUTTON_KEY in {
        e["key_code"] for e in machine.screens[machine.mode]["slots"][0]["entries"]}


def test_options_turns_the_remote_assistant_off(remote):
    machine = _fresh(remote)
    options = generate.scaffold.SYSTEM_SCREENS + 1
    machine.enter(options)
    machine.touch(generate.MENU_ROW_KEYS[0])  # its first row, as in Logitech's Options
    machine.enter(generate.scaffold.SYSTEM_SCREENS)
    machine.touch(generate.MENU_ROW_KEYS[0])
    # straight to the activity: its buttons, no question
    assert generate.FIRST_BUTTON_KEY in {
        e["key_code"] for e in machine.screens[machine.mode]["slots"][0]["entries"]}


FAVOURITES = {**PROJECT, "activities": [dict(
    PROJECT["activities"][0], image_buttons=[["BBC One", "channel", "12", None],
                                             ["News", "channel", "2", None]],
    channel_confirm="Select")] + PROJECT["activities"][1:]}


def test_favourites_dial_their_channel_and_come_before_the_commands():
    project = {**FAVOURITES, "devices": [dict(TV, press_interkey=300), AMP]}
    machine = _fresh(generate.build(project))
    _start(machine, 0)
    favourites = machine.mode
    machine.sent.clear()
    machine.touch(generate.FIRST_BUTTON_KEY)             # BBC One: 1, 2, then Select
    assert machine.sent == [_command("1"), _command("2"), _command("Select")]
    assert ("wait", 0, 3) in machine.log                  # the TV's key delay between
    machine.touch(generate.PAGE_ACTIVITIES_KEY)           # Commands
    commands = machine.mode
    assert commands != favourites
    machine.sent.clear()
    machine.touch(generate.FIRST_BUTTON_KEY)
    assert machine.sent == [_command("Guide")]
    machine.touch(generate.PAGE_ACTIVITIES_KEY)           # Favorites
    assert machine.mode == favourites


def test_options_has_logitechs_two_pages_and_the_tutorial_teaches_without_doing(remote):
    # Logitech's Options: the Remote Assistant, the Tutorial and Date and Time, then
    # Screen Sounds and Screen Sensitivity, the side strips between them.
    machine = _fresh(remote)
    options = generate.scaffold.SYSTEM_SCREENS + 1
    machine.enter(options)
    machine.touch(generate.SIDE_NEXT_KEY)
    second = machine.mode
    assert second != options
    machine.touch(generate.SIDE_NEXT_KEY)
    assert machine.mode == options
    # the Tutorial, each page moved on by the key it teaches; Help and Off send nothing
    machine.touch(generate.MENU_ROW_KEYS[1])
    seen = [machine.mode]
    machine.touch(generate.SIDE_NEXT_KEY)                    # right arrow
    seen.append(machine.mode)
    machine.touch(generate.MENU_ROW_KEYS[2])                 # touch the first activity
    seen.append(machine.mode)
    machine.press(keys.code(keys.ACTIVITIES))
    seen.append(machine.mode)
    machine.touch(generate.SIDE_NEXT_KEY)
    seen.append(machine.mode)
    machine.sent.clear()
    machine.press(keys.code(keys.HELP))
    seen.append(machine.mode)
    machine.touch(generate.SIDE_NEXT_KEY)
    seen.append(machine.mode)
    machine.press(keys.code(keys.OFF))
    seen.append(machine.mode)
    assert machine.sent == [] and len(set(seen)) == len(generate.TUTORIAL)
    machine.touch(generate.SIDE_PREV_KEY)                    # back a page
    assert machine.mode == seen[-2]
    machine.press(keys.code(keys.OFF))
    machine.touch(generate.PAGE_DEVICES_KEY)                 # Exit
    assert machine.mode == generate.scaffold.SYSTEM_SCREENS  # nothing running: the menu


def _queue_peak(image) -> tuple[int, str]:
    """The deepest any handler drives the instruction queue, run as the Harmony 800 runs
    it: an object's atoms go to the head all at once, a write puts its transition there, a
    switch its program's atoms; a test may drop the next, so both ways are followed."""
    from afterglow.backends.harmony_one import gspm as _gspm

    objects = [item["atoms"] for item in command_index.objects(image)]
    records = activity_index.engine_records(image)
    groups_at = _gspm.section_ranges(image)[15][0]
    machine = _Remote(image)

    def group_programs(group):
        at = int.from_bytes(image[groups_at + 1 + 3 * group:groups_at + 4 + 3 * group],
                            "little") - _gspm.BASE + 1
        return [int.from_bytes(image[at + 3 + 5 * k:at + 6 + 5 * k], "little") - _gspm.BASE
                for k in range(image[at])]

    def peak(first):
        best, work, steps = 1, [([first], False)], 0
        while work and steps < 5000:
            queue, silent = work.pop()
            while queue and steps < 5000:
                steps += 1
                best = max(best, len(queue))
                operand, opcode = queue.pop(0)
                if opcode == 0x7F:
                    queue[:0] = list(objects[operand])
                elif opcode in (0x70, 0x71) and queue:
                    work.append((queue[1:], silent))
                elif opcode == 0x72:
                    for program in group_programs(operand >> 8):
                        work.append(([(i["operand"], i["category"]) for i in
                                      ui_index.drawing_program(image, program)["instructions"]
                                      if i["opcode"] == "atom"] + queue, silent))
                    queue = []
                elif (operand, opcode) == (0xFFFF, 0x07):
                    silent = True
                elif opcode >= 0x80:
                    if not silent and (opcode & 0x7F) < len(records):
                        fired = [(t["operand"], t["category"])
                                 for t in records[opcode & 0x7F]["transitions"]
                                 if t["to"] == operand]
                        queue[:0] = fired[:1]
                    silent = False
                best = max(best, len(queue))
        return best

    starts = [(f"context {c['ordinal']} key {r['key_code']:#x}", (r["operand"], r["category"]))
              for c in activity_index.contexts(image) for r in c["rows"]]
    for mode, screen in enumerate(machine.screens):
        starts += [(f"mode {mode} key {key:#x}", value)
                   for key, value in machine.header(mode).items()]
        starts += [(f"mode {mode} touch {e['key_code']:#x}", (e["operand"], e["category"]))
                   for slot in screen["slots"] for e in slot["entries"]]
    return max((peak(first), where) for where, first in starts)


def test_no_handler_queues_deeper_than_logitechs_own(remote):
    # The queue holds 40 instructions and drops the rest without a word; a long sequence
    # hung a One for good. No handler in the three household donors queues more than 16,
    # so a build keeps its objects short enough to stay there - even for a big project.
    devices = [dict(TV, id=f"tv{n}", label=f"TV {n}") for n in range(15)]
    big = {"devices": devices, "activities": [
        {"id": str(n), "label": f"Activity {n}", "type": "VirtualTelevisionN",
         "display": f"tv{n}", "volume": f"tv{n}", "control": f"tv{n}",
         "power_on_devices": [f"tv{k}" for k in range(15)],
         "enter": [["input", f"tv{k}", "HDMI2"] for k in range(15)]
         + [["command", "tv0", "Menu"], ["delay", "tv0", 300]] * 6,
         "image_buttons": [[f"Ch {k}", "channel", "121212", None] for k in range(8)],
         "soft_buttons": [{"label": "Long", "macro": [["command", "tv0", "Guide"]] * 20}]}
        for n in range(6)]}
    for image in (remote["image"], generate.build(big)["image"]):
        depth, where = _queue_peak(image)
        assert depth <= 16, where


def test_a_slot_holds_more_than_127_characters_with_two_byte_codes():
    # A code past 0x7F takes two bytes, the first with its high bit set, as the Harmony
    # 800's text VM reads them - so a project in Korean or Chinese is not stopped at 127
    # different characters in one font. A second byte may be zero.
    from afterglow.backends.harmony_one import drawing

    syllables = [chr(0xAC00 + 7 * n) for n in range(200)]      # 200 Hangul syllables
    labels = ["".join(syllables[k:k + 8]) for k in range(0, 200, 8)]
    project = {"devices": [dict(TV, id=f"d{n}", label=label)
                           for n, label in enumerate(labels)]}
    built = generate.build(project)
    image = built["image"]
    assert max(len(table) for table in built["characters"]) > 127
    drawn = set()
    for screen in ui_index.screen_slots(image):
        for slot in screen["slots"]:
            for block in drawing.program_blocks(image, [slot["program_offset"]]).values():
                attribute = 0
                for item in block:
                    if item["opcode"] == "attribute":
                        attribute = item["value"]
                    elif item["opcode"] == "inline_text":
                        codes = drawing.glyph_codes(bytes.fromhex(item["glyphs"]))
                        drawn.add("".join(built["characters"][attribute].get(code, "?")
                                          for code in codes))
    # every device row's name reads back whole, wrapped or not
    assert all(any(label.startswith(text) or text in label for text in drawn if text)
               for label in labels)
    assert any(code > 0x7F for table in built["characters"] for code in table)
