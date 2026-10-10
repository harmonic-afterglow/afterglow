"""Building a Harmony One configuration without reading one.

Every other writer in this backend starts from somebody's image. These tests hold the
generator to starting from nothing: the only inputs are the scaffold's files, and the
output has to satisfy the same validator and the same readers a real configuration does.
"""

from __future__ import annotations

import struct

import pytest

from afterglow import ir_signal, paths
from afterglow.backends.harmony_one import (
    activity_index, assets, authoring, bitmap, command_index, compose, drawing,
    font_index, generate, gspm, key_index, named_index, scaffold, ui_index)


SCAFFOLD = paths.scaffolds("harmony-one")

# Activities, then Options and the screens carried behind it, then the device list.
CARRIED = generate.load_options()
HOME, OPTIONS = scaffold.SYSTEM_SCREENS, scaffold.SYSTEM_SCREENS + 1
MENU = HOME + 1 + ((1 + len(CARRIED["modes"])) if CARRIED else 0)


def test_a_configuration_can_be_built_from_nothing():
    image = generate.skeleton()

    report = gspm.validate(image)
    assert report["ok"] is True
    assert report["sections"] == gspm.SECTION_COUNT - 1
    assert image[:4] == gspm.MAGIC
    assert image[-4:] == b"PTYY"


def test_every_reader_parses_a_generated_configuration():
    """A generated image is only worth anything if the readers accept it as one."""
    image = generate.skeleton()

    assert named_index.inspect(image)["counts"]["records"] == 0
    assert command_index.inspect(image)["counts"]["devices"] == 0
    assert activity_index.contexts(image)
    assert activity_index.engine_records(image) == []
    assert len(ui_index.screen_slots(image)) == 1
    assert ui_index.touch_templates(image) == {}
    assert compose._overlay_roots(image) == []
    assert compose.read(image)["screens"]


def test_a_generated_configuration_has_the_shape_the_factory_image_has():
    """The counts a virgin remote ships with are the ones a generated image may use.

    Sections 13 and 15 hold records nobody has decoded. `Region_3.EZHex` in firmware
    54.2.5 counts zero of each, which is what makes them emittable without being
    understood, so a generated image must not quietly acquire any.
    """
    image = generate.skeleton()
    ranges = gspm.section_ranges(image)

    assert image[ranges[13][0]] == 0
    assert image[ranges[15][0]] == 0
    assert image[ranges[12][0]:ranges[12][0] + 2] == b"\x00\x00"
    assert image[ranges[5][0]] == 0
    for section, body in sorted(scaffold.CONSTANT_SECTIONS.items()):
        start, end = ranges[section]
        assert image[start:end] == body, f"section {section}"


def test_section_sixteen_indexes_section_fifteens_own_table():
    image = generate.skeleton()
    ranges = gspm.section_ranges(image)

    start = ranges[16][0]
    count = image[start]
    pointers = [
        int.from_bytes(image[start + 1 + 3 * i:start + 4 + 3 * i], "little") - gspm.BASE
        for i in range(count)
    ]
    tail = ranges[15][0] + 1

    assert count == len(scaffold.SECTION_16_OFFSETS)
    assert pointers == [tail + offset for offset in scaffold.SECTION_16_OFFSETS]
    assert all(ranges[15][0] <= p < ranges[15][1] for p in pointers)


def _scaffold_fonts_and_pictures():
    loaded = assets.load(SCAFFOLD)
    fonts = [f for f in loaded["fonts"].values() if f["height"] == 14]
    return loaded, fonts


def test_the_scaffolds_artwork_survives_into_a_generated_configuration():
    """The whole point of the scaffold: what is in the directory is what the remote draws."""
    loaded, fonts = _scaffold_fonts_and_pictures()
    models = [generate.font_from_scaffold(font) for font in fonts]

    image = generate.skeleton(fonts=models)

    assert gspm.validate(image)["ok"] is True
    written = font_index.fonts(image)
    assert len(written) == len(fonts)
    for source, target in zip(fonts, written):
        assert target["height"] == source["height"]
        for code, glyph in source["glyphs"].items():
            offset = target["glyphs"][code]["pointer"] - gspm.BASE
            assert bitmap.decode_glyph(image, offset)["rows"] == glyph["rows"]
    # A picture is placed when something draws it, and then exactly as the scaffold has it.
    configured = generate.configuration(THREE)
    drawn = {
        item["target"] for screen in ui_index.screen_slots(configured)
        for slot in screen["slots"]
        for program in (ui_index.drawing_program(configured, slot["program_offset"]),)
        for opening in (program["instructions"][0],)
        for instructions in (
            program["instructions"]
            + (ui_index.drawing_program(configured, opening["target"])["instructions"]
               if opening["opcode"] == "call" else []),)
        for item in instructions if item["opcode"] == "bitmap"}
    for role in ("backdrop", "button-frame/0", "row-frame", "row-icon/00"):
        item = loaded["pictures"][role]
        at = configured.find(item["body"])
        assert at in drawn
        assert bitmap.decode(configured, at)["rows"] == item["rows"]


def test_an_image_with_no_devices_boots_into_a_screen_that_draws():
    # Nothing clears the display, so a first screen that draws nothing leaves the boot
    # logo up and a remote that started looks like one that did not.
    image = generate.configuration({"devices": []})
    [slot] = ui_index.screen_slots(image)[scaffold.SYSTEM_SCREENS]["slots"]
    program = ui_index.drawing_program(image, slot["program_offset"])["instructions"]
    assert program[0]["opcode"] == "call"
    fragment = ui_index.drawing_program(image, program[0]["target"])["instructions"]
    assert [item["opcode"] for item in fragment[:1]] == ["bitmap"]
    assert any(item["opcode"] == "inline_text" for item in program)


def test_every_timer_a_generated_image_starts_is_in_section_13():
    # Opcode 0x1F bands EB and EA start and stop a section-13 timer by index; every
    # platform screen starts timer 3 while it is shown. An empty section 13 left those
    # starts reading past the end of the table.
    image = generate.configuration(THREE)
    start = gspm.section_ranges(image)[13][0]
    count = image[start]
    objects = command_index.objects(image)
    named = {value & 0xFF for item in objects for value, category in item["atoms"]
             if category == 0x1F and value >> 8 in (0xEA, 0xEB)}
    for screen in ui_index.screen_slots(image):
        head = int.from_bytes(image[screen["trailer_offset"] + 1:
                                    screen["trailer_offset"] + 4], "little") - gspm.BASE
        if image[head]:
            named |= {struct.unpack_from("<H", image, head + 2 + 4 * row)[0] & 0xFF
                      for row in range(image[head])
                      if image[head + 4 + 4 * row] == 0x1F
                      and image[head + 3 + 4 * row] in (0xEA, 0xEB)}
    assert named and max(named) < count
    for index in range(count):
        at = int.from_bytes(image[start + 1 + 3 * index:start + 4 + 3 * index],
                            "little") - gspm.BASE
        operand, opcode = struct.unpack_from("<HB", image, at + 4)
        assert opcode != 0x7F or operand < len(objects)


def test_a_generated_image_names_no_variable_or_context_it_does_not_have():
    # Opcodes from 0x80 write a section-14 variable, 0x70-0x72 test one, and 0x1F bands
    # FF/FE/FD select, push and pop a section-10 context. Platform handlers carried from a
    # donor used the donor's own, and menu rows wrote its variable 25.
    image = generate.configuration(THREE)
    variables = len(activity_index.engine_records(image))
    contexts = image[gspm.section_ranges(image)[10][0]]
    for item in command_index.objects(image):
        for value, category in item["atoms"]:
            if category >= 0x80:
                assert category & 0x7F < variables, item
            if category in (0x70, 0x71, 0x72):
                assert value & 0xFF < variables, item
            if category == 0x1F and value >> 8 in (0xFF, 0xFE, 0xFD) and value & 0xFF < 0xFC:
                assert value & 0xFF < contexts, item


def _softkeys(image, ordinal):
    """A screen's bottom-strip keys: ``key -> (screen it opens, label drawn)``."""
    objects = command_index.objects(image)
    [slot] = ui_index.screen_slots(image)[ordinal]["slots"]
    templates = ui_index.touch_templates(image)
    strip = {zone["key_code"] for zone in templates[slot["template"]]
             if zone["y"] == generate.SOFTKEY_LEFT_ZONE["y"]}
    texts = {}
    attribute = None
    for item in ui_index.drawing_program(image, slot["program_offset"])["instructions"]:
        if item["opcode"] == "attribute":
            attribute = item["value"]
        if item["opcode"] == "inline_text" and item["y"] == generate.SOFTKEYS["devices"][1][1]:
            texts[item["x"]] = attribute
    out = {}
    for entry in slot["entries"]:
        if entry["key_code"] in strip:
            [target] = [value for value, category in objects[entry["operand"]]["atoms"]
                        if category == 0x7E]
            out[entry["key_code"]] = target
    return out, texts


def test_the_hub_is_activities_devices_and_back_as_logitech_builds_it():
    # Every Logitech configuration boots into Activities, with Devices bottom right; the
    # device list has Activities bottom left; a device's pages have both. Testers could
    # not find their way back from a device when only a side strip led there.
    image = generate.configuration(THREE)
    fonts = generate.SOFTKEY_FONTS
    x = {name: xy[0] for name, (_text, xy) in generate.SOFTKEYS.items()}

    keys, texts = _softkeys(image, HOME)
    assert keys == {generate.SOFTKEY_RIGHT_KEY: MENU, 0x80 | generate.HOME_OPTIONS_TAG: OPTIONS}
    assert texts == {x["devices"]: fonts["devices"], x["options"]: fonts["options"]}
    keys, texts = _softkeys(image, OPTIONS)
    assert keys == {generate.MENU_ACTIVITIES_KEY: HOME}
    keys, texts = _softkeys(image, MENU)
    assert keys == {generate.MENU_ACTIVITIES_KEY: HOME}
    assert texts == {x["activities"]: fonts["activities"]}
    screens = ui_index.screen_slots(image)
    for ordinal in range(MENU + 1, len(screens)):
        keys, texts = _softkeys(image, ordinal)
        assert keys == {generate.PAGE_ACTIVITIES_KEY: HOME, generate.PAGE_DEVICES_KEY: MENU}
        assert texts == {x["activities"]: fonts["activities"], x["devices"]: fonts["devices"]}
    # the image boots into Activities, and that is what OK on a firmware notice opens
    start = gspm.section_ranges(image)[9][0]
    routine = command_index.objects(image)[struct.unpack_from("<H", image, start + 1)[0]]
    assert (HOME, generate.ENTER_MODE) in routine["atoms"]


@pytest.mark.skipif(CARRIED is None, reason="the scaffold carries no Options screens")
def test_options_opens_date_and_time_sounds_and_sensitivity_as_upstairs_does():
    image = generate.configuration(THREE)
    objects = command_index.objects(image)
    screens = ui_index.screen_slots(image)
    ranges = gspm.section_ranges(image)
    variables = len(activity_index.engine_records(image))
    [slot] = screens[OPTIONS]["slots"]
    rows = {entry["key_code"]: objects[entry["operand"]]["atoms"] for entry in slot["entries"]}
    first = OPTIONS + 1
    assert rows[0xB0] == ((authoring.IR_OBJECT_KIND_FALLBACK, 0x75),
                          (first + CARRIED["entries"]["date-and-time"], 0x7E))
    assert rows[0xB2][-1] == (first + CARRIED["entries"]["screen-sensitivity"], 0x7E)
    # Screen Sounds runs a section-15 switch on one of the Options screens' own flags
    [(operand, opcode)] = rows[0xB1]
    assert opcode == 0x72
    assert operand >> 8 < image[ranges[15][0]]
    assert activity_index.PLATFORM_PROPERTIES <= operand & 0xFF < variables - 1
    # the carried screens lead nowhere but each other, Options and the hub
    for ordinal in range(first, MENU):
        for slot in screens[ordinal]["slots"]:
            for entry in slot["entries"]:
                if entry["category"] != 0x7F:
                    continue
                for value, category in objects[entry["operand"]]["atoms"]:
                    if category == 0x7E:
                        assert HOME <= value < MENU or value == MENU, (ordinal, value)
    # and section 16 still lands in section 15's platform table, after the switch tables
    start = ranges[15][0]
    tail = start + 1 + 3 * image[start]
    [count] = image[ranges[16][0]:ranges[16][0] + 1]
    pointers = [int.from_bytes(image[ranges[16][0] + 1 + 3 * k:ranges[16][0] + 4 + 3 * k],
                               "little") - gspm.BASE for k in range(count)]
    assert [at - tail for at in pointers] == list(scaffold.SECTION_16_OFFSETS)


def test_with_no_devices_the_device_list_is_still_there_and_says_so():
    image = generate.configuration({"devices": []})
    screens = ui_index.screen_slots(image)
    assert len(screens) == MENU + 1
    keys, _texts = _softkeys(image, HOME)
    assert keys[generate.SOFTKEY_RIGHT_KEY] == MENU
    keys, _texts = _softkeys(image, MENU)
    assert keys == {generate.MENU_ACTIVITIES_KEY: HOME}


def test_a_resized_button_frame_is_labelled_on_its_own_width():
    loaded = assets.load(SCAFFOLD)
    font = generate.font_from_scaffold(
        next(f for f in loaded["fonts"].values() if f["height"] == 14))
    narrow = generate.button_page(["Power"], [0x100], font, frame_width=61)
    wide = generate.button_page(["Power"], [0x100], font)
    [n] = [item for item in narrow if item["opcode"] == "inline_text"]
    [w] = [item for item in wide if item["opcode"] == "inline_text"]
    assert w["x"] - n["x"] == (generate.FRAME_WIDTH - 61) // 2


def test_a_picture_nothing_draws_is_left_out():
    # Logitech's builder places only what the configuration draws; every donor's pictures
    # are all reached. Three devices draw three of the fifteen row icons.
    loaded = assets.load(SCAFFOLD)
    configured = generate.configuration(THREE)
    assert configured.find(loaded["pictures"]["row-icon/02"]["body"]) >= 0
    assert configured.find(loaded["pictures"]["row-icon/14"]["body"]) < 0
    assert generate.skeleton(pictures={"unused": loaded["pictures"]["backdrop"]["body"]}) \
        == generate.skeleton()


def test_a_generated_font_still_draws_every_printable_character():
    loaded, fonts = _scaffold_fonts_and_pictures()
    models = [generate.font_from_scaffold(font) for font in fonts]

    image = generate.skeleton(fonts=models)

    for written in font_index.fonts(image):
        assert len(written["glyphs"]) == 95


def test_a_platform_table_of_the_wrong_size_is_refused():
    with pytest.raises(ValueError, match="section 15's table is 151"):
        generate.skeleton(tail=b"\x00" * 8)


def test_engine_records_are_emitted_as_given():
    """Section 14 holds no addresses, so a record is written exactly as it is modelled."""
    records = [
        {"initial": 0, "limit": 1, "padding": 0, "transitions": [
            {"flags": 0, "from": 0xFFFE, "to": 0, "operand": 3, "category": 0x7F}]},
        {"initial": 2, "limit": 23, "padding": 0, "transitions": []},
    ]

    image = generate.skeleton(engine=records)

    written = activity_index.engine_records(image)
    assert len(written) == len(records)
    for source, target in zip(records, written):
        assert target["initial"] == source["initial"]
        assert target["limit"] == source["limit"]
        assert target["padding"] == source["padding"]
        assert len(target["transitions"]) == len(source["transitions"])
        for a, b in zip(source["transitions"], target["transitions"]):
            assert (b["flags"], b["from"], b["to"], b["operand"], b["category"]) == (
                a["flags"], a["from"], a["to"], a["operand"], a["category"])


def test_the_clock_in_section_three_and_section_fourteen_agree():
    """The two places a Harmony One keeps the time have to hold the same time.

    Section 14's first seven properties are the clock - their limits are 59, 59, 23, 30,
    6, 11 and a year - and their initial values are section 3's timestamp fields. All
    five images measured agree on all seven, so a generated one must not drift.
    """
    fields = (26, 35, 22, 22, 7, 2023)

    image = generate.skeleton(
        stamp=authoring.stamp(*fields), engine=generate.clock_records(*fields))

    read = authoring.read_stamp(image)
    assert (read["second"], read["minute"], read["hour"], read["day"],
            read["month"], read["year"]) == fields
    assert read["weekday_agrees"] is True

    records = activity_index.engine_records(image)
    assert [r["limit"] for r in records[:6]] == list(generate.CLOCK_LIMITS)
    assert [r["initial"] for r in records[:7]] == [
        read["second"], read["minute"], read["hour"], read["day"],
        read["weekday"], read["month"], read["year"] - 2000]


def test_a_weekday_that_disagrees_with_its_date_is_refused():
    """A stored weekday contradicting its own date is what left this byte unexplained."""
    with pytest.raises(ValueError, match="disagrees with the date"):
        authoring.stamp(26, 35, 22, 22, 7, 2023, 5)


def test_the_day_and_month_of_a_stamp_count_from_zero():
    """Section 14's limits are 30 and 11, so twelve is not a month and 31 is not a day."""
    with pytest.raises(ValueError, match="month is outside its measured range of 0 to 11"):
        authoring.stamp(0, 0, 0, 0, 12, 2024)
    with pytest.raises(ValueError, match="day is outside its measured range of 0 to 30"):
        authoring.stamp(0, 0, 0, 31, 0, 2024)
    # and zero is a valid day and month, which the one-based reading refused
    assert authoring.stamp(0, 0, 0, 0, 0, 2024)


def _nec(address: int, command: int):
    """A plain NEC frame, ending in the gap the encoder requires."""
    pulses = [9000, -4500]
    for byte in (address, ~address & 0xFF, command, ~command & 0xFF):
        for bit in range(8):
            pulses += [560, -1690] if (byte >> bit) & 1 else [560, -560]
    return ir_signal.waveform(pulses + [560, -40000], carrier_hz=38000)


PROJECT = {"devices": [
    {"label": "Living Room TV", "signals": {
        "Power": _nec(0x04, 0x08), "VolumeUp": _nec(0x04, 0x10),
        "Mute": _nec(0x04, 0x0D)}},
    {"label": "Blu-ray", "signals": {
        "Power": _nec(0x0A, 0x01), "Play": _nec(0x0A, 0x02)}},
]}


def test_a_project_becomes_a_configuration_with_its_own_commands():
    devices = generate.lowered_devices(PROJECT)

    image = generate.skeleton(devices=devices)

    assert gspm.validate(image)["ok"] is True
    counts = command_index.inspect(image)["counts"]
    assert counts["devices"] == 2
    assert counts["declared_commands"] == 5
    assert counts["decoded_commands"] == 5
    assert counts["command_objects"] == 5
    assert counts["duplicate_command_objects"] == 0


def test_the_infrared_a_generated_configuration_holds_is_the_project_s_own():
    """Every pulse has to survive, because this is the part a device actually sees."""
    devices = generate.lowered_devices(PROJECT)

    image = generate.skeleton(devices=devices)

    portable = command_index.portable_devices(command_index.inspect(image))
    assert len(portable) == len(PROJECT["devices"])
    for index, (device, source) in enumerate(zip(portable, PROJECT["devices"])):
        signals = sorted(source["signals"].items())
        assert len(device["signals"]) == len(signals)
        for ordinal, (_name, signal) in enumerate(signals):
            got = device["signals"][f"Command {ordinal:02d}"]
            assert got["pulses_us"] == signal["pulses_us"]


def test_section_zero_names_state_variables_not_commands():
    # Every donor's section 0 is Root, State and the state variables by index; none names
    # a command, and a command's id would collide with a variable's.
    image = generate.configuration(STATEFUL)
    records = named_index.inspect(image)["records"]
    assert [(r["type"], r["id"], r["name"]) for r in records[:2]] == [
        (0, 0, "Root"), (0, 1, "State")]
    names = {r["name"]: r["id"] for r in records[2:]}
    variables = activity_index.engine_records(image)
    for name in ("Living_Room_TV_Power_2", "Living_Room_TV_Input_3",
                 "Receiver_Power_2", "Receiver_Input_4"):
        assert name in names
        assert names[name] < len(variables) - 1


STATEFUL = {"devices": [
    {"label": "Living Room TV", "power_on_cmd": "PowerOn", "power_off_cmd": "PowerOff",
     "power_delay": 5000,
     "inputs": [["HDMI 1", "InputHdmi1"], ["HDMI 2", "InputHdmi2"], ["TV", None]],
     "signals": {"PowerOn": _nec(4, 1), "PowerOff": _nec(4, 2),
                 "InputHdmi1": _nec(4, 3), "InputHdmi2": _nec(4, 4)}},
    {"label": "Receiver", "power_cmd": "Power", "power_delay": 12000,
     "input_cycle": {"values": ["CD", "DVD", "TV", "Tuner"], "next": ["InputNext"],
                     "delay_ms": 500},
     "signals": {"Power": _nec(9, 1), "InputNext": _nec(9, 2)}},
]}


def _command_ids(image, object_index):
    """The command ids an object sends, following calls."""
    objects = command_index.objects(image)
    out = []
    for value, category in objects[object_index]["atoms"]:
        if category == 0x7D:
            out.append(value)
        elif category == 0x7F:
            out += _command_ids(image, value)
    return out


def _waits(image, object_index):
    objects = command_index.objects(image)
    return [value for value, category in objects[object_index]["atoms"]
            if category == generate.WAIT]


def test_a_device_s_power_and_inputs_are_state_variables_as_in_every_donor():
    image = generate.configuration(STATEFUL)
    names = {r["name"]: r["id"] for r in named_index.inspect(image)["records"]}
    variables = activity_index.engine_records(image)
    commands = {(device["label"], command["name"]): command["command_id"]
                for device in generate.lowered_devices(STATEFUL)
                for command in device["commands"]}

    def transitions(name):
        return {(t["from"], t["to"]): t for t in variables[names[name]]["transitions"]}

    # power: off sends PowerOff; on sends PowerOn and waits 5.0 s for device 0
    tv = transitions("Living_Room_TV_Power_2")
    assert _command_ids(image, tv[(1, 0)]["operand"]) == [
        commands[("Living Room TV", "PowerOff")]]
    assert _command_ids(image, tv[(0, 1)]["operand"]) == [
        commands[("Living Room TV", "PowerOn")]]
    assert _waits(image, tv[(0, 1)]["operand"]) == [(0 << 8) | 50]
    # a toggle sends the same command both ways; 12 s waits as 10 s + 2 s, as donors do
    receiver = transitions("Receiver_Power_2")
    toggle = commands[("Receiver", "Power")]
    assert _command_ids(image, receiver[(1, 0)]["operand"]) == [toggle]
    assert _waits(image, receiver[(0, 1)]["operand"]) == [(1 << 8) | 100, (1 << 8) | 20]
    # direct inputs: from any value to each, sending its command; none for "TV"
    inputs = transitions("Living_Room_TV_Input_3")
    assert variables[names["Living_Room_TV_Input_3"]]["limit"] == 2
    assert _command_ids(image, inputs[(generate.TRANSITION_FROM_ANY, 1)]["operand"]) == [
        commands[("Living Room TV", "InputHdmi2")]]
    assert (inputs[(generate.TRANSITION_FROM_ANY, 2)]["operand"],
            inputs[(generate.TRANSITION_FROM_ANY, 2)]["category"]) == (0, 0)
    # stepping inputs: every ordered pair, "next" as many times as it takes
    stepping = transitions("Receiver_Input_4")
    assert len(stepping) == 4 * 3
    step = commands[("Receiver", "InputNext")]
    assert _command_ids(image, stepping[(3, 1)]["operand"]) == [step, step]
    assert _waits(image, stepping[(0, 1)]["operand"]) == [(1 << 8) | 5]


def test_section_five_points_into_section_four_in_a_generated_image_too():
    devices = generate.lowered_devices(PROJECT)

    image = generate.skeleton(devices=devices)

    start = gspm.section_ranges(image)[4][0]
    run = start + authoring.COMMAND_INDEX_HEAD_SIZE
    for device in authoring.section5_layout(image):
        assert device["subtable"] == run
        run += len(authoring.command_subtable(
            [command["record_offset"] for command in device["commands"]]))


def test_a_device_cannot_hold_more_commands_than_an_ordinal_can_name():
    crowded = {"devices": [{"label": "Too many", "signals": {
        f"Command {index}": _nec(1, index % 256) for index in range(256)}}]}

    with pytest.raises(ValueError, match="an ordinal is one byte"):
        generate.lowered_devices(crowded)


def _pressable(project=None):
    loaded = assets.load(SCAFFOLD)
    fonts = [generate.font_from_scaffold(font)
             for font in loaded["fonts"].values() if font["height"] == 14]
    pictures = {role: item["body"] for role, item in loaded["pictures"].items()}
    return generate.skeleton(
        devices=generate.lowered_devices(project or PROJECT),
        fonts=fonts, pictures=pictures)


def test_every_generated_command_is_bound_to_a_button():
    """A command nothing can press is not in the configuration in any useful sense."""
    image = _pressable()

    bindings = key_index.inspect(image)["bindings"]
    commanded = {binding["command_id"] for binding in bindings}

    assert len(bindings) == 5
    assert commanded == {0x000, 0x001, 0x002, 0x100, 0x101}


def test_a_page_draws_a_backdrop_before_its_buttons():
    """Nothing in the format clears the screen, so a page that draws none shows the last."""
    image = _pressable()

    for screen in ui_index.screen_slots(image):
        for slot in screen["slots"]:
            program = ui_index.drawing_program(image, slot["program_offset"])
            # As in every donor, a page program opens by calling its mode's fragment,
            # which draws the backdrop.
            opening = program["instructions"][0]
            if opening["opcode"] == "call":
                program = ui_index.drawing_program(image, opening["target"])
            first = next(item for item in program["instructions"]
                         if item["opcode"] == "bitmap")
            picture = bitmap.decode(image, first["target"])
            assert (first["x"], first["y"]) == (0, 0)
            assert (picture["width"], picture["height"]) == (176, 220)


def test_a_page_has_a_touch_zone_for_each_button_and_no_more():
    """A zone for a button the page does not draw would answer a press with nothing."""
    image = _pressable()

    templates = ui_index.touch_templates(image)
    for screen in ui_index.screen_slots(image):
        for slot in screen["slots"]:
            keys = {entry["key_code"] for entry in slot["entries"]}
            zones = {zone["key_code"] for zone in templates[slot["template"]]}
            buttons = {code for code in zones
                       if generate.FIRST_BUTTON_KEY <= code
                       < generate.FIRST_BUTTON_KEY + len(generate.BUTTON_POSITIONS)}
            assert buttons == keys


def test_a_label_wider_than_its_place_wraps_as_the_donors_wrap_one():
    # Two lines, 5 above and 6 below a button's baseline and 6 either side of a menu
    # row's, each still inside its frame; past two lines it is cut and marked.
    loaded = assets.load(SCAFFOLD)
    font = generate.font_from_scaffold(
        next(f for f in loaded["fonts"].values() if f["height"] == 14))
    widths, _codes = generate._measure(font)

    page = generate.button_page(["Sony BDP-S5000ES"], [0x100], font)
    texts = [item for item in page if item["opcode"] == "inline_text"]
    left, top = generate.BUTTON_POSITIONS[0]
    assert [item["y"] for item in texts] == [top + 15, top + 26]
    for item in texts:
        width = sum(widths[code] for code in bytes.fromhex(item["glyphs"]))
        assert left <= item["x"] and item["x"] + width <= left + generate.FRAME_WIDTH

    menu = generate.menu_page(["Samsung Home Theater System"], 0x100, [0x200], font)
    assert [item["y"] for item in menu if item["opcode"] == "inline_text"] == [51, 63]

    lines = generate.fit_label("Supercalifragilisticexpialidocious", font, 81)
    assert len(lines) == 2
    assert all(sum(widths[code] for code in line) <= 81 for line in lines)
    assert generate.fit_label("Power", font, 81) == [
        bytes(_codes[character] for character in "Power")]


def test_a_label_the_font_cannot_draw_is_refused_by_name():
    loaded = assets.load(SCAFFOLD)
    font = generate.font_from_scaffold(
        next(f for f in loaded["fonts"].values() if f["height"] == 14))

    with pytest.raises(ValueError, match="cannot draw"):
        generate.button_page(["café"], [0x100], font)


def test_each_command_object_is_followed_by_the_wrapper_a_key_binds_to():
    """The donors lay a command's object and its wrapper out as a pair, command by command.

    A key register row points at the wrapper, and the wrapper points at the command
    object just before it - the order `authoring.device_objects` measured - rather than all
    the command objects first and every wrapper after them.
    """
    image = _pressable()

    objects = command_index.objects(image)
    for binding in key_index.inspect(image)["bindings"]:
        row = next(
            entry for screen in ui_index.screen_slots(image) for slot in screen["slots"]
            for entry in slot["entries"] if entry["key_code"] == binding["key_code"]
            and entry["operand"] < len(objects))
        wrapper = objects[row["operand"]]["atoms"]
        assert wrapper[0] == (authoring.IR_OBJECT_KIND_FALLBACK, 0x75)
        assert wrapper[1] == (row["operand"] - 1, 0x7F)


def _configured(project=None):
    return generate.configuration(project or PROJECT)


def _charsets():
    """Each font's characters by code, in attribute order - the order a build emits."""
    loaded = assets.load(SCAFFOLD)
    return [{code: glyph["char"] for code, glyph in loaded["fonts"][role]["glyphs"].items()}
            for role in sorted(loaded["fonts"])]


def _drawn_text(image, program_offset, charsets):
    attribute, out = 0, []
    for item in ui_index.drawing_program(image, program_offset)["instructions"]:
        if item["opcode"] == "attribute":
            attribute = item["value"]
        elif item["opcode"] in ("inline_text", "text") and "glyphs" in item:
            out.append("".join(charsets[attribute].get(code, "?")
                               for code in bytes.fromhex(item["glyphs"])))
    return out


def test_a_generated_configuration_carries_the_firmware_s_own_screens():
    """The first forty ordinals are the firmware's, and a build has to fill them.

    Among them are the screens the remote would use to say it had rejected the
    configuration it was given, so leaving them out is not an option for a first write.
    """
    image = _configured()
    charsets = _charsets()

    screens = ui_index.screen_slots(image)
    text = [_drawn_text(image, screen["slots"][0]["program_offset"], charsets)
            for screen in screens[:scaffold.SYSTEM_SCREENS]]

    assert gspm.validate(image)["ok"] is True
    assert text[0][0] == "The battery level is low!"
    assert text[29] == ["Invalid", "Configuration"]
    assert text[36] == ["Configuration", "Corrupted"]


def test_the_owner_s_screens_start_where_the_firmware_s_end():
    image = _configured()

    screens = ui_index.screen_slots(image)
    objects = command_index.objects(image)
    bindings = key_index.inspect(image)["bindings"]

    # The first owned screen is Activities and the device list follows it; its rows
    # navigate rather than command, so the first command binding is one ordinal later.
    menu = screens[MENU]
    assert any(
        _is_menu_row(objects[entry["operand"]]["atoms"])
        for slot in menu["slots"] for entry in slot["entries"])
    assert bindings
    assert min(binding["screen"] for binding in bindings) == MENU + 1


def test_ok_on_a_firmware_notice_opens_the_first_owned_screen():
    """The donor's OK leads into its own interface; a build's leads into the build's."""
    image = _configured()
    objects = command_index.objects(image)

    screens = ui_index.screen_slots(image)
    for ordinal in (0, 9):
        rows = [entry for slot in screens[ordinal]["slots"] for entry in slot["entries"]]
        assert rows, f"screen {ordinal} has no OK binding"
        for row in rows:
            atoms = objects[row["operand"]]["atoms"]
            assert (scaffold.SYSTEM_SCREENS, 0x7E) in atoms


def test_the_status_bar_the_firmware_s_screens_queue_is_there():
    image = _configured()
    overlays = compose._overlay_roots(image)
    objects = command_index.objects(image)

    screens = ui_index.screen_slots(image)[:scaffold.SYSTEM_SCREENS]
    roots = [slot["program_offset"] for screen in screens for slot in screen["slots"]]
    queued = {item["operand"] for block in drawing.program_blocks(image, roots).values()
              for item in block if item["opcode"] == "atom" and item["category"] == 0x7F}

    assert len(overlays) == 4
    assert queued
    for index in queued:
        for value, category in objects[index]["atoms"]:
            if category == 0x73:
                assert value < len(overlays)


def test_firmware_screens_keep_their_templates_and_pages_come_after():
    image = _configured()
    system = generate.load_system(SCAFFOLD)

    screens = ui_index.screen_slots(image)
    platform = {slot["template"] for screen in screens[:scaffold.SYSTEM_SCREENS]
                for slot in screen["slots"]}
    owned = {slot["template"] for screen in screens[scaffold.SYSTEM_SCREENS:]
             for slot in screen["slots"]}
    templates = ui_index.touch_templates(image)

    assert platform <= set(range(len(system["templates"])))
    assert min(owned) >= len(system["templates"])
    for index, zones in enumerate(system["templates"]):
        assert [{key: zone[key] for key in ("tag", "x", "width", "y", "height")}
                for zone in templates[index]] == zones


def test_a_page_draws_its_labels_in_the_font_that_measured_them():
    image = _configured()
    manifest = assets.read_manifest(SCAFFOLD)
    button = sorted(assets.load(SCAFFOLD)["fonts"]).index(manifest["font_roles"]["button"])

    screen = ui_index.screen_slots(image)[MENU]
    program = ui_index.drawing_program(image, screen["slots"][0]["program_offset"])
    attribute = None
    for item in program["instructions"]:
        if item["opcode"] == "attribute":
            attribute = item["value"]
        # the softkeys along the bottom are in fonts of their own
        elif item["opcode"] == "inline_text" and item["y"] < generate.SOFTKEYS["devices"][1][1]:
            assert attribute == button


THREE = {"devices": [
    {"label": "Living Room TV", "signals": {"Power": _nec(4, 8), "Vol +": _nec(4, 16)}},
    {"label": "Blu-ray", "signals": {"Power": _nec(10, 1), "Play": _nec(10, 2)}},
    {"label": "Amplifier", "signals": {"Power": _nec(11, 1)}}]}




def _is_menu_row(atoms):
    """A device row: the device's kind (0x75), then the screen it opens (0x7E)."""
    return [category for _value, category in atoms] == [0x75, 0x7E]


def test_the_device_menu_is_behind_the_activities_screen():
    image = generate.configuration(THREE)

    screens = ui_index.screen_slots(image)
    objects = command_index.objects(image)
    menu = screens[MENU]

    targets = []
    for entry in menu["slots"][0]["entries"]:
        if entry["key_code"] not in generate.MENU_ROW_KEYS:
            continue
        atoms = objects[entry["operand"]]["atoms"]
        assert _is_menu_row(atoms)
        # Donor rows also write their own variable 25 with `(1, 0x99)`; this image has
        # no variable 25, so its rows must not.
        assert not any(category >= 0x80 for _value, category in atoms)
        targets += [value for value, category in atoms if category == 0x7E]
    # one row per device, each opening a screen after the menu
    assert len(targets) == len(THREE["devices"])
    assert all(target > MENU for target in targets)


def test_a_menu_row_opens_that_device_s_own_command_page():
    image = generate.configuration(THREE)

    screens = ui_index.screen_slots(image)
    objects = command_index.objects(image)
    bindings = key_index.inspect(image)["bindings"]
    device_of_screen = {}
    for binding in bindings:
        # a command id's high byte is its device
        device_of_screen.setdefault(binding["screen"], binding["command_id"] >> 8)

    menu = screens[MENU]
    opened = []
    for entry in sorted(menu["slots"][0]["entries"], key=lambda e: e["key_code"]):
        if entry["key_code"] not in generate.MENU_ROW_KEYS:
            continue
        target = next(value for value, category in objects[entry["operand"]]["atoms"]
                      if category == 0x7E)
        opened.append(device_of_screen[target])
    # the three rows open three distinct devices, each its own page
    assert len(set(opened)) == len(THREE["devices"])


def test_a_notice_ok_button_opens_the_activities_screen():
    image = generate.configuration(THREE)
    objects = command_index.objects(image)

    for ordinal in (0, 9):
        rows = [entry for slot in ui_index.screen_slots(image)[ordinal]["slots"]
                for entry in slot["entries"]]
        for row in rows:
            assert (scaffold.SYSTEM_SCREENS, 0x7E) in objects[row["operand"]]["atoms"]


def _screen_navigations(image, ordinal):
    """The side-strip navigation targets (0xae/0xaf) of one screen, by key."""
    objects = command_index.objects(image)
    out = {}
    for entry in ui_index.screen_slots(image)[ordinal]["slots"][0]["entries"]:
        if entry["key_code"] not in (generate.SIDE_PREV_KEY, generate.SIDE_NEXT_KEY):
            continue
        targets = [value for value, category in objects[entry["operand"]]["atoms"]
                   if category == 0x7E]
        if targets:
            out[entry["key_code"]] = targets[0]
    return out


def test_more_than_three_devices_spread_across_paged_menus():
    project = {"devices": [
        {"label": f"Device {n}", "signals": {"Power": _nec(n % 200 + 1, 1)}}
        for n in range(7)]}

    image = generate.configuration(project)

    assert gspm.validate(image)["ok"] is True
    # three menu pages (3 + 3 + 1 devices), each linking to the next in a cycle
    screens = ui_index.screen_slots(image)
    objects = command_index.objects(image)
    menu_ordinals = [
        ordinal for ordinal in range(MENU, len(screens))
        if any(_is_menu_row(objects[entry["operand"]]["atoms"])
               for entry in screens[ordinal]["slots"][0]["entries"]
               if entry["key_code"] in generate.MENU_ROW_KEYS
               if entry["operand"] < len(objects))
    ]
    assert len(menu_ordinals) == 3
    for ordinal in menu_ordinals:
        navigation = _screen_navigations(image, ordinal)
        assert set(navigation) == {generate.SIDE_PREV_KEY, generate.SIDE_NEXT_KEY}
        assert all(target in menu_ordinals for target in navigation.values())


def test_a_device_with_more_than_six_commands_pages_and_the_pages_link_back():
    project = {"devices": [
        {"label": "Big", "signals": {f"C{i:02d}": _nec(4, i) for i in range(14)}}]}

    image = generate.configuration(project)
    bindings = key_index.inspect(image)["bindings"]

    device_pages = sorted({binding["screen"] for binding in bindings})
    assert len(device_pages) == 3          # 6 + 6 + 2
    # every command page reaches the next by its side strip, the last back to the menu
    menu = MENU
    for index, ordinal in enumerate(device_pages):
        following = _screen_navigations(image, ordinal)[generate.SIDE_NEXT_KEY]
        expected = device_pages[index + 1] if index + 1 < len(device_pages) else menu
        assert following == expected
    # and no command is lost: 14 across the three pages
    assert len(bindings) == 14


def test_section_nine_is_the_key_registers_back_to_back_between_seven_and_ten():
    # Every Logitech image keeps section 9 between 7 and 10 and walks register by register
    # to exactly where section 10 begins. A probe that pointed section 9 at a scattered
    # first register, ahead of section 0, hung the remote on its boot logo.
    for image in (generate.skeleton(), _configured()):
        ranges = gspm.section_ranges(image)
        starts = [ranges[index][0] for index in sorted(ranges)]
        assert starts == sorted(starts)
        start, end = ranges[9]
        # The section's own start-up list comes first, `u8 count; {u16, u8}[count]`.
        walked, at = set(), start + 1 + 3 * image[start]
        while at < end:
            walked.add(at)
            at += 1 + 4 * image[at]
        assert at == end
        registers = {
            slot["key_register_offset"]
            for screen in ui_index.screen_slots(image) for slot in screen["slots"]}
        assert registers <= walked


def test_section_nine_opens_with_the_list_that_starts_the_image():
    # The factory image and all four household ones open section 9 with one 0x7F call,
    # and every probe that lacked it failed to boot: the firmware read the first page
    # register as this list. The factory's routine pushes its context, enters its home
    # screen, and shows USB CONNECTED when variable 0x10 is set.
    for image, home, usb in ((generate.skeleton(), 0, None),
                             (_configured(), scaffold.SYSTEM_SCREENS, generate.USB_SCREEN)):
        start = gspm.section_ranges(image)[9][0]
        assert image[start] == 1 and image[start + 3] == generate.OBJECT_ATOM
        atoms = {item["index"]: item["atoms"] for item in command_index.objects(image)}
        routine = atoms[struct.unpack_from("<H", image, start + 1)[0]]
        assert routine[:4] == ((generate.PUSH_CONTEXT, 0x1F),
                               (generate.PUSH_CURRENT_MODE, 0x1F),
                               (home, generate.ENTER_MODE), generate.BACKLIGHT)
        if usb is None:
            assert len(routine) == 4
            continue
        load, call = atoms[routine[4][0]]
        assert load == (generate.LOAD_ONE, 0x1F) and call[1] == generate.OBJECT_ATOM
        assert atoms[call[0]] == ((generate.USB_CONNECTED, generate.COMPARE),
                                  (usb, generate.ENTER_MODE))


def test_section_fourteen_holds_the_clock_the_platform_and_a_terminator():
    # The factory image holds nineteen records: seven clock properties that carry into one
    # another, eleven platform properties, and the terminator. A probe holding the clock
    # alone, with no carries, hung the remote on its boot logo.
    image = _configured()
    records = activity_index.engine_records(image)
    shape = activity_index.engine_shape(image)

    # the Options screens' own flags sit between the platform's and the terminator
    carried = len(CARRIED["variables"]) if CARRIED else 0
    assert len(records) == activity_index.PLATFORM_PROPERTIES + carried + 1
    assert shape["terminator"] is not None
    assert [(r["initial"], r["limit"]) for r in shape["platform"]] == list(
        generate.PLATFORM_RECORDS)
    carries = {index: [(row["operand"], row["category"]) for row in record["transitions"]]
               for index, record in enumerate(records[:7]) if record["transitions"]}
    assert carries[1] == [(0xF202, 0x1F)]
    assert carries[3] == [(0xF205, 0x1F)]
    assert carries[5] == [(0xF206, 0x1F)]
    [(hour_object, category)] = carries[2]
    assert category == 0x7F
    start = gspm.section_ranges(image)[11][0]
    at = int.from_bytes(image[start + 2 + 3 * hour_object:start + 5 + 3 * hour_object],
                        "little") - gspm.BASE
    assert image[at:at + 7] == generate.object_body([(0xF203, 0x1F), (0xF204, 0x1F)])


def test_mode_zero_list_follows_the_button_count_as_in_every_user_configuration():
    # The firmware reads mode 0's list at a fixed place after LWJL; a count with no
    # entries had it read the first objects as key bindings, and no probe booted.
    image = generate.configuration(PROJECT)
    at = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC)
    assert image[at] == generate.HOUSEHOLD_BUTTONS
    entries = image[at + 1:at + 1 + 4 * generate.HOUSEHOLD_BUTTONS]
    assert entries == generate.mode_zero_list()
    for position in range(generate.HOUSEHOLD_BUTTONS):
        code, target, opcode = struct.unpack_from("<BHB", entries, 4 * position)
        assert (target, opcode) == (position, generate.OBJECT_ATOM)
        assert code == generate.MODE_ZERO_EVENTS[position]


def test_objects_0_to_54_are_mode_zeros_handlers():
    image = generate.configuration(PROJECT)
    start, _ = gspm.section_ranges(image)[11]
    pointers = [int.from_bytes(image[start + 2 + 3 * i:start + 5 + 3 * i], "little")
                - gspm.BASE for i in range(generate.HOUSEHOLD_BUTTONS)]
    events = set(generate.MODE_ZERO_EVENT_AT.values())
    for index, at in enumerate(pointers):
        body = image[at:at + 1 + 3 * image[at]]
        if index in events:
            # Enter, leave and redraw call the platform's own mode 0 handlers.
            assert body[0] == 1 and body[3] == generate.OBJECT_ATOM
            assert struct.unpack_from("<H", body, 1)[0] >= generate.HOUSEHOLD_BUTTONS
        else:
            assert body == bytes([3]) + bytes(9)


def test_every_mode_has_an_enter_and_a_leave_handler_and_mode_0_is_the_lwjl_list():
    image = generate.configuration(THREE)
    screens = ui_index.screen_slots(image)
    head = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC)
    for ordinal, screen in enumerate(screens):
        at = int.from_bytes(image[screen["trailer_offset"] + 1:screen["trailer_offset"] + 4],
                            "little") - gspm.BASE
        if ordinal == 0:
            assert at == head
        tags = [image[at + 1 + 4 * row] for row in range(image[at])]
        assert tags.count(generate.ENTER) == 1 and tags.count(generate.LEAVE) == 1, ordinal
