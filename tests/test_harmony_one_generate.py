"""Building a Harmony One configuration without reading one.

Every other writer in this backend starts from somebody's image. These tests hold the
generator to starting from nothing: the only inputs are the scaffold's files, and the
output has to satisfy the same validator and the same readers a real configuration does.
"""

from __future__ import annotations

import json
import struct

import pytest

from afterglow import ir_signal, paths
from afterglow import po
from afterglow.backends.harmony_one.catalogue import ENGLISH
from afterglow.backends.harmony_one import (
    activity_index, assets, bitmap, charging, command_index, devices, drawing, firmware_screens,
    font_index, generate, gspm, idle, key_index, named_index, pages, pictures, scaffold,
    structures, ui_index)


SCAFFOLD = paths.scaffolds("harmony-one")

# Activities, then Options and the screens carried behind it, then the charging screens,
# then the device list; the idle machine is built into the Options model's namespace.
_LOADED = assets.load(SCAFFOLD)
FONTS = [generate.font_from_scaffold(_LOADED["fonts"][role]) for role in sorted(_LOADED["fonts"])]
OPTIONS_MODEL = generate.options_model(FONTS, generate.build_stamp()[-1])
CHARGING = len(charging.roles(_LOADED["pictures"])) if OPTIONS_MODEL is not None else 0
CARRIED = (idle.attach(OPTIONS_MODEL, firmware_screens.load_system(), CHARGING)
           if OPTIONS_MODEL is not None else None)
HOME, OPTIONS = scaffold.SYSTEM_SCREENS, scaffold.SYSTEM_SCREENS + 1
MENU = HOME + 1 + ((1 + len(CARRIED["modes"])) if CARRIED else 0) + CHARGING


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
    assert ui_index.overlay_roots(image) == []


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
    for role in ("backdrop", "button-frame/0", "row-frame"):
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
    assert any(item["opcode"] == "bitmap" and (item["x"], item["y"]) == (0, 0)
               for item in fragment)
    assert any(item["opcode"] == "inline_text" for item in program)


def _texts(built, ordinal, page=0):
    """What a screen's page and its prologue write: ``[(attribute, x, y, text)]``, read
    with the character tables that build gave each font (generate.build)."""
    image, chars = built["image"], built["characters"]
    slot = ui_index.screen_slots(image)[ordinal]["slots"][page]
    program = ui_index.drawing_program(image, slot["program_offset"])["instructions"]
    out, attribute = [], None
    for item in (ui_index.drawing_program(image, program[0]["target"])["instructions"]
                 + program):
        if item["opcode"] == "attribute":
            attribute = item["value"]
        elif item["opcode"] in ("text", "inline_text"):
            out.append((attribute, item["x"], item["y"],
                        "".join(chars[attribute][code]
                                for code in bytes.fromhex(item["glyphs"]))))
    return out


def test_every_screen_is_titled_and_a_paged_one_says_which_page_it_is():
    # As the donors do: the title at (6,4), drawn before and after the backdrop, in the
    # screen kind's colour; a paged screen's total at (23,18) and "pages", and each page's
    # number right-aligned against the slash at (18,18). A single page draws no counter.
    project = {"devices": [
        {"label": "Television", "signals": {f"Key {n}": _nec(4, n) for n in range(8)}},
        {"label": "Amp", "signals": {"Power": _nec(11, 1)}}]}
    built = generate.build(project)
    home = _texts(built, HOME)
    assert home.count((10, 6, 4, ENGLISH("hub.activities-title"))) == 2
    assert (2, 6, 4, ENGLISH("options.title")) in _texts(built, OPTIONS)
    assert (3, 6, 4, ENGLISH("hub.devices-title")) in _texts(built, MENU)
    assert not any(y == 18 for _a, _x, y, _t in _texts(built, MENU))
    # the television's eight commands take two pages
    first, second = _texts(built, MENU + 1), _texts(built, MENU + 2)
    for index, page in enumerate((first, second)):
        assert (3, 6, 4, "Television") in page
        assert (4, 23, 18, "2") in page and (4, 18, 18, "/") in page
        assert any(text == "pages" and y == 18 for _a, _x, y, text in page)
        [(_a, x, _y, number)] = [t for t in page if t[2] == 18 and t[1] < 18]
        assert number == str(index + 1)
    assert not any(y == 18 for _a, _x, y, _t in _texts(built, MENU + 3))


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
             if zone["y"] == pages.SOFTKEY_LEFT_ZONE["y"]}
    texts = {}
    attribute = None
    for item in ui_index.drawing_program(image, slot["program_offset"])["instructions"]:
        if item["opcode"] == "attribute":
            attribute = item["value"]
        if item["opcode"] == "inline_text" and item["y"] == pages.SOFTKEYS["devices"][1]:
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
    fonts = pages.SOFTKEY_FONTS
    x = {name: xy[0] for name, xy in pages.SOFTKEYS.items()}

    keys, texts = _softkeys(image, HOME)
    assert keys == {pages.SOFTKEY_RIGHT_KEY: MENU, 0x80 | pages.HOME_OPTIONS_TAG: OPTIONS}
    assert texts == {x["devices"]: fonts["devices"], x["options"]: fonts["options"]}
    keys, texts = _softkeys(image, OPTIONS)
    assert keys == {pages.MENU_ACTIVITIES_KEY: HOME}
    keys, texts = _softkeys(image, MENU)
    assert keys == {pages.MENU_ACTIVITIES_KEY: HOME}
    assert texts == {x["activities"]: fonts["activities"]}
    screens = ui_index.screen_slots(image)
    for ordinal in range(MENU + 1, len(screens)):
        keys, texts = _softkeys(image, ordinal)
        assert keys == {pages.PAGE_ACTIVITIES_KEY: HOME, pages.PAGE_DEVICES_KEY: MENU}
        assert texts == {x["activities"]: fonts["activities"], x["devices"]: fonts["devices"]}
    # the image boots into Activities, and that is what OK on a firmware notice opens
    start = gspm.section_ranges(image)[9][0]
    routine = _run(image, struct.unpack_from("<H", image, start + 1)[0])
    assert (HOME, structures.ENTER_MODE) in routine


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
    assert rows[0xB0] == ((structures.IR_OBJECT_KIND_FALLBACK, 0x75),
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
    assert keys[pages.SOFTKEY_RIGHT_KEY] == MENU
    keys, _texts = _softkeys(image, MENU)
    assert keys == {pages.MENU_ACTIVITIES_KEY: HOME}


def test_a_resized_button_frame_is_labelled_on_its_own_width():
    loaded = assets.load(SCAFFOLD)
    font = generate.font_from_scaffold(
        next(f for f in loaded["fonts"].values() if f["height"] == 14))
    narrow = pages.button_page(["Power"], [0x100], font, frame_width=61)
    wide = pages.button_page(["Power"], [0x100], font)
    [n] = [item for item in narrow if item["opcode"] == "inline_text"]
    [w] = [item for item in wide if item["opcode"] == "inline_text"]
    assert w["x"] - n["x"] == (pages.FRAME_WIDTH - 61) // 2


def _row_icon(kind, name):
    """The row icon a build composes for a type, as the remote stores it."""
    manifest = assets.read_manifest(SCAFFOLD)
    bodies = {}
    role = pictures.row_icon(SCAFFOLD, manifest, bodies, kind, name)
    return role, bodies[role]


def test_a_device_row_shows_its_type_s_icon_on_the_row_frame():
    # The display has one-bit transparency, so a row icon carries the patch of the row
    # frame it covers, with the type's icon scaled and blended onto it. A device whose type
    # the scaffold has no icon for shows the generic one.
    project = {"devices": [dict(device, type=kind) for device, kind in zip(
        THREE["devices"], ("Television", "Amplifier", "NoSuchType"))]}
    configured = generate.configuration(project)
    for kind, wanted in (("Television", "row-icon/devices/Television"),
                         ("Amplifier", "row-icon/devices/Amplifier"),
                         ("NoSuchType", "row-icon/activities/VirtualGeneric")):
        role, body = _row_icon("devices", kind)
        assert role == wanted
        assert configured.find(body) >= 0
    # a corner the icon leaves alone is the frame's own pixel, under the icon's place
    frame = assets.load(SCAFFOLD)["pictures"]["row-frame"]["rows"]
    _role, body = _row_icon("devices", "Television")
    icon = bitmap.decode(body + b"\x00" * 8, 0)["rows"]
    dx = pages.MENU_ICON_XY[0][0] - pages.MENU_FRAME_XY[0][0]
    dy = pages.MENU_ICON_XY[0][1] - pages.MENU_FRAME_XY[0][1]
    assert icon[0][0] == frame[dy][dx]
    assert icon[-1][-1] == frame[dy + len(icon) - 1][dx + len(icon[0]) - 1]


def test_a_picture_nothing_draws_is_left_out():
    # Logitech's builder places only what the configuration draws; every donor's pictures
    # are all reached. Untyped devices draw the generic row icon and no other.
    configured = generate.configuration(THREE)
    assert configured.find(_row_icon("devices", None)[1]) >= 0
    assert configured.find(_row_icon("devices", "Television")[1]) < 0
    loaded = assets.load(SCAFFOLD)
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
        stamp=structures.stamp(*fields), engine=scaffold.clock_records(*fields))

    read = structures.read_stamp(image)
    assert (read["second"], read["minute"], read["hour"], read["day"],
            read["month"], read["year"]) == fields
    assert read["weekday_agrees"] is True

    records = activity_index.engine_records(image)
    assert [r["limit"] for r in records[:6]] == list(scaffold.CLOCK_LIMITS)
    assert [r["initial"] for r in records[:7]] == [
        read["second"], read["minute"], read["hour"], read["day"],
        read["weekday"], read["month"], read["year"] - 2000]


def test_a_weekday_that_disagrees_with_its_date_is_refused():
    """A stored weekday contradicting its own date is what left this byte unexplained."""
    with pytest.raises(ValueError, match="disagrees with the date"):
        structures.stamp(26, 35, 22, 22, 7, 2023, 5)


def test_the_day_and_month_of_a_stamp_count_from_zero():
    """Section 14's limits are 30 and 11, so twelve is not a month and 31 is not a day."""
    with pytest.raises(ValueError, match="month is outside its measured range of 0 to 11"):
        structures.stamp(0, 0, 0, 0, 12, 2024)
    with pytest.raises(ValueError, match="day is outside its measured range of 0 to 30"):
        structures.stamp(0, 0, 0, 31, 0, 2024)
    # and zero is a valid day and month, which the one-based reading refused
    assert structures.stamp(0, 0, 0, 0, 0, 2024)


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
    lowered = devices.lowered_devices(PROJECT)

    image = generate.skeleton(devices=lowered)

    assert gspm.validate(image)["ok"] is True
    counts = command_index.inspect(image)["counts"]
    assert counts["devices"] == 2
    assert counts["declared_commands"] == 5
    assert counts["decoded_commands"] == 5
    assert counts["command_objects"] == 5
    assert counts["duplicate_command_objects"] == 0


def test_the_infrared_a_generated_configuration_holds_is_the_project_s_own():
    """Every pulse has to survive, because this is the part a device actually sees."""
    lowered = devices.lowered_devices(PROJECT)

    image = generate.skeleton(devices=lowered)

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
            if category == devices.WAIT]


def test_a_device_s_power_and_inputs_are_state_variables_as_in_every_donor():
    image = generate.configuration(STATEFUL)
    names = {r["name"]: r["id"] for r in named_index.inspect(image)["records"]}
    variables = activity_index.engine_records(image)
    commands = {(device["label"], command["name"]): command["command_id"]
                for device in devices.lowered_devices(STATEFUL)
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
    assert _command_ids(image, inputs[(devices.TRANSITION_FROM_ANY, 1)]["operand"]) == [
        commands[("Living Room TV", "InputHdmi2")]]
    assert (inputs[(devices.TRANSITION_FROM_ANY, 2)]["operand"],
            inputs[(devices.TRANSITION_FROM_ANY, 2)]["category"]) == (0, 0)
    # stepping inputs: every ordered pair, "next" as many times as it takes
    stepping = transitions("Receiver_Input_4")
    assert len(stepping) == 4 * 3
    step = commands[("Receiver", "InputNext")]
    assert _command_ids(image, stepping[(3, 1)]["operand"]) == [step, step]
    assert _waits(image, stepping[(0, 1)]["operand"]) == [(1 << 8) | 5]


def test_section_five_points_into_section_four_in_a_generated_image_too():
    lowered = devices.lowered_devices(PROJECT)

    image = generate.skeleton(devices=lowered)

    start = gspm.section_ranges(image)[4][0]
    run = start + structures.COMMAND_INDEX_HEAD_SIZE
    for device in command_index.section5_layout(image):
        assert device["subtable"] == run
        run += len(structures.command_subtable(
            [command["record_offset"] for command in device["commands"]]))


def test_a_device_cannot_hold_more_commands_than_an_ordinal_can_name():
    crowded = {"devices": [{"label": "Too many", "signals": {
        f"Command {index}": _nec(1, index % 256) for index in range(256)}}]}

    with pytest.raises(ValueError, match="an ordinal is one byte"):
        devices.lowered_devices(crowded)


def _pressable(project=None):
    loaded = assets.load(SCAFFOLD)
    fonts = [generate.font_from_scaffold(font)
             for font in loaded["fonts"].values() if font["height"] == 14]
    pictures = {role: item["body"] for role, item in loaded["pictures"].items()}
    return generate.skeleton(
        devices=devices.lowered_devices(project or PROJECT),
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
                       if pages.FIRST_BUTTON_KEY <= code
                       < pages.FIRST_BUTTON_KEY + len(pages.BUTTON_POSITIONS)}
            assert buttons == keys


def test_a_label_wider_than_its_place_wraps_as_the_donors_wrap_one():
    # Two lines, 5 above and 6 below a button's baseline and 6 either side of a menu
    # row's, each still inside its frame; past two lines it is cut and marked.
    loaded = assets.load(SCAFFOLD)
    font = generate.font_from_scaffold(
        next(f for f in loaded["fonts"].values() if f["height"] == 14))
    widths, _codes = pages.measure(font)

    page = pages.button_page(["Sony BDP-S5000ES"], [0x100], font)
    texts = [item for item in page if item["opcode"] == "inline_text"]
    left, top = pages.BUTTON_POSITIONS[0]
    assert [item["y"] for item in texts] == [top + 15, top + 26]
    for item in texts:
        width = sum(widths[code] for code in bytes.fromhex(item["glyphs"]))
        assert left <= item["x"] and item["x"] + width <= left + pages.FRAME_WIDTH

    menu = pages.menu_page(["Samsung Home Theater System"], 0x100, [0x200], font)
    assert [item["y"] for item in menu if item["opcode"] == "inline_text"] == [51, 63]

    lines = pages.fit_label("Supercalifragilisticexpialidocious", font, 81)
    assert len(lines) == 2
    assert all(sum(widths[code] for code in line) <= 81 for line in lines)
    assert pages.fit_label("Power", font, 81) == [
        bytes(_codes[character] for character in "Power")]


def test_a_label_the_font_cannot_draw_is_refused_by_name():
    loaded = assets.load(SCAFFOLD)
    font = generate.font_from_scaffold(
        next(f for f in loaded["fonts"].values() if f["height"] == 14))

    with pytest.raises(ValueError, match="cannot draw"):
        pages.button_page(["café"], [0x100], font)


def test_each_command_object_is_followed_by_the_wrapper_a_key_binds_to():
    """The donors lay a command's object and its wrapper out as a pair, command by command.

    A key register row points at the wrapper, and the wrapper points at the command
    object just before it - the order `structures.device_objects` measured - rather than all
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
        assert wrapper[0] == (structures.IR_OBJECT_KIND_FALLBACK, 0x75)
        assert wrapper[1] == (row["operand"] - 1, 0x7F)


def _run(image, index) -> list[tuple[int, int]]:
    """An object's instructions in the order the remote runs them, every call expanded -
    a build keeps objects short by chaining them (layout.bounded_objects)."""
    atoms = {item["index"]: item["atoms"] for item in command_index.objects(image)}
    out = []
    for operand, category in atoms[index]:
        if category == structures.OBJECT_ATOM:
            out += _run(image, operand)
        else:
            out.append((operand, category))
    return out


def _configured(project=None):
    return generate.configuration(project or PROJECT)


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
    built = generate.build(PROJECT)
    image, charsets = built["image"], built["characters"]

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
    overlays = ui_index.overlay_roots(image)
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
    system = firmware_screens.load_system(SCAFFOLD)

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
        elif item["opcode"] == "inline_text" and item["y"] < pages.SOFTKEYS["devices"][1]:
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
        if entry["key_code"] not in pages.MENU_ROW_KEYS:
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
        if entry["key_code"] not in pages.MENU_ROW_KEYS:
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
        if entry["key_code"] not in (pages.SIDE_PREV_KEY, pages.SIDE_NEXT_KEY):
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
               if entry["key_code"] in pages.MENU_ROW_KEYS
               if entry["operand"] < len(objects))
    ]
    assert len(menu_ordinals) == 3
    for ordinal in menu_ordinals:
        navigation = _screen_navigations(image, ordinal)
        assert set(navigation) == {pages.SIDE_PREV_KEY, pages.SIDE_NEXT_KEY}
        assert all(target in menu_ordinals for target in navigation.values())


def test_a_device_with_more_than_six_commands_pages_and_the_pages_link_back():
    project = {"devices": [
        {"label": "Big", "signals": {f"C{i:02d}": _nec(4, i) for i in range(14)}}]}

    image = generate.configuration(project)
    bindings = key_index.inspect(image)["bindings"]

    device_pages = sorted({binding["screen"] for binding in bindings})
    assert len(device_pages) == 3          # 6 + 6 + 2
    # every command page reaches the next by its side strip, and they wrap round - the
    # last to the first, the first back to the last - as Logitech's own do
    for index, ordinal in enumerate(device_pages):
        navigation = _screen_navigations(image, ordinal)
        assert navigation[pages.SIDE_NEXT_KEY] == device_pages[(index + 1) % 3]
        assert navigation[pages.SIDE_PREV_KEY] == device_pages[(index - 1) % 3]
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
                             (_configured(), scaffold.SYSTEM_SCREENS, scaffold.USB_SCREEN)):
        start = gspm.section_ranges(image)[9][0]
        assert image[start] == 1 and image[start + 3] == structures.OBJECT_ATOM
        routine = tuple(_run(image, struct.unpack_from("<H", image, start + 1)[0]))
        if usb is None:
            assert routine == ((scaffold.PUSH_CONTEXT, 0x1F),
                               (scaffold.PUSH_CURRENT_MODE, 0x1F),
                               (home, structures.ENTER_MODE), scaffold.TIMER_UNIT)
            continue
        # with the idle layer, as every donor starts: the screen timer and flag resets,
        # then the events, 0xFE, the current mode, 0xFC and the key light on top, then
        # home, and Off's context selected last so nothing is running
        assert routine[0] == scaffold.TIMER_UNIT
        pushes = [value for value, category in routine
                  if category == 0x1F and value >> 8 == 0xFE]
        assert pushes == [scaffold.PUSH_CONTEXT | scaffold.EVENT_CONTEXT,
                          scaffold.PUSH_CONTEXT | 0xFE, scaffold.PUSH_CURRENT_MODE,
                          scaffold.PUSH_CONTEXT | 0xFC,
                          scaffold.PUSH_CONTEXT | scaffold.KEY_LIGHT_CONTEXT]
        selects = [value for value, category in routine
                   if category == 0x1F and value >> 8 == 0xFF]
        assert selects == [0xFF00 | (len(activity_index.contexts(image)) - 1)]
        assert routine.index((home, structures.ENTER_MODE)) > routine.index(
            (scaffold.PUSH_CONTEXT | scaffold.KEY_LIGHT_CONTEXT, 0x1F))
        # and last, the USB check: load 1, compare the USB flag, enter the USB screen
        assert routine[-3:] == ((scaffold.LOAD_ONE, 0x1F),
                                (scaffold.USB_CONNECTED, structures.COMPARE),
                                (usb, structures.ENTER_MODE))


class _Idle:
    """A generated image's instructions run the way the Harmony 800's interpreter runs
    them (gspm.md): an object's instructions in place, a failed test dropping the next
    one, `0x3F` band C0 setting a light channel, entering a mode running the shown
    screen's leave handler and then the new one's enter handler. What leaves the
    interpreter is kept: the level of every channel, the timers running, the variables,
    the screen shown and the ones pushed under it."""

    def __init__(self, image):
        self.image = image
        self.objects = command_index.objects(image)
        self.variables = {index: record["initial"] for index, record
                          in enumerate(activity_index.engine_records(image))}
        self.lights, self.timers, self.log = {}, set(), []
        self.byte = 0
        self.mode, self.stack = None, []

    def header(self, ordinal):
        """A screen's own list: ``key -> (operand, opcode)``."""
        trailer = ui_index.screen_slots(self.image)[ordinal]["trailer_offset"]
        head = int.from_bytes(self.image[trailer + 1:trailer + 4], "little") - gspm.BASE
        return {self.image[head + 1 + 4 * row]:
                struct.unpack_from("<HB", self.image, head + 2 + 4 * row)
                for row in range(self.image[head])}

    def timer(self, index):
        start = gspm.section_ranges(self.image)[13][0]
        at = int.from_bytes(self.image[start + 1 + 3 * index:start + 4 + 3 * index],
                            "little") - gspm.BASE
        return struct.unpack_from("<HB", self.image, at + 4)

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
                        value > self.byte, value <= self.byte,
                        value >= self.byte][high & 0x0F]
                skip = held if high & 0x80 else not held
            elif opcode == 0x1F and high == 0xFB:
                self.byte = low
            elif opcode == 0x1F and high == 0xF0:          # byte register := variable
                self.byte = self.variables.get(low, 0)
            elif opcode == 0x1F and high == 0xFA:          # byte register += low
                self.byte = (self.byte + low) & 0xFF
            elif opcode == 0x1F and high == 0xEE:          # variable := byte register
                self.variables[low] = self.byte
            elif opcode == 0x1F and high in (0xEB, 0xEA):
                (self.timers.add if high == 0xEB else self.timers.discard)(low)
            elif opcode == 0x3F and high >> 4 == 0xC:
                self.lights[(operand >> 4) & 0x1F] = (operand >> 1) & 7
            elif opcode >= 0x80:
                self.variables[opcode & 0x7F] = operand
            elif opcode == 0x7E:
                self.enter(operand)
            elif (operand, opcode) == (idle.PUSH_MODE, 0x07):
                self.stack.append(self.mode)
            elif (operand, opcode) == (idle.POP_MODE, 0x07):
                self.enter(self.stack.pop())
            else:
                self.log.append((operand, opcode))

    def enter(self, ordinal):
        if self.mode is not None and 0x07 in self.header(self.mode):
            self.run(self.header(self.mode)[0x07])
        self.mode = ordinal
        if 0x06 in self.header(ordinal):
            self.run(self.header(ordinal)[0x06])

    def lit(self):
        return {channel for channel, level in self.lights.items() if level}


@pytest.mark.skipif(CARRIED is None, reason="the scaffold carries no Options screens")
def test_every_key_lights_the_keypad_and_usb_comes_and_goes_as_upstairs_does():
    # The keypad lights only when the configuration lights it: every key runs the key
    # light on its way down the stack (a pass-through row, flags bit 0), and the event
    # context shows the USB screen on plugging in and goes back on unplugging.
    image = generate.configuration(THREE)
    contexts = activity_index.contexts(image)
    # the image's own (the normal charge context), the events, the key light, the USB and
    # low battery charge contexts, and Off's (no activities here)
    assert len(contexts) == 6
    keys = contexts[scaffold.KEY_LIGHT_CONTEXT]
    assert keys["form"] == "long"
    # every physical key, and the two codes below them both donors wake on: 0x17, the
    # remote being picked up, and 0x30
    assert {row["key_code"] for row in keys["rows"]} == {
        code for code in scaffold.MODE_ZERO_EVENTS if code >= 0x80} | {idle.MOTION, 0x30}
    assert {row["flags"] for row in keys["rows"]} == {1}
    [wake] = {(row["operand"], row["category"]) for row in keys["rows"]
              if row["key_code"] >= 0x80}
    rows = {row["key_code"]: (row["operand"], row["category"]) for row in keys["rows"]}
    assert rows[0x30] == wake
    machine = _Idle(image)
    machine.run(rows[idle.MOTION])
    assert machine.lights[idle.SCREEN] == idle.SCREEN_LEVEL
    assert all(machine.lights[channel] == idle.KEY_LEVEL for channel in idle.KEYPAD)
    events = {row["key_code"]: (row["operand"], row["category"])
              for row in contexts[scaffold.EVENT_CONTEXT]["rows"]}
    # the firmware's events - charging's among them - and the two keys the flow owns:
    # Activities and Off
    assert set(events) == {0x10, 0x19, 0x25, 0x26, 0x27, 0x2D, 0xAE, 0xAF,
                           idle.CHARGING_STOPPED, idle.CHARGING_STARTED,
                           idle.CHARGING_PROBLEM, idle.BATTERY_UP, 0x80 | 34, 0x80 | 37}

    machine = _Idle(image)
    machine.run(wake)
    # the screen backlight at 6, the keypad at 1, and the off and poll timers
    assert machine.lights[idle.SCREEN] == idle.SCREEN_LEVEL
    assert all(machine.lights[channel] == idle.KEY_LEVEL for channel in idle.KEYPAD)
    assert len(machine.timers) == 1          # the poll; the off timer waits for AWAKE
    machine.variables[idle.AWAKE] = 1
    machine.run(wake)
    assert len(machine.timers) == 2

    # plugging in remembers the screen and shows the USB one; unplugging goes back
    machine = _Idle(image)
    machine.enter(MENU)
    machine.run(events[0x26])
    assert (machine.mode, machine.stack) == (scaffold.USB_SCREEN, [MENU])
    machine.run(events[0x27])
    assert (machine.mode, machine.stack) == (MENU, [])
    # left by hand, the USB screen is no longer shown, and unplugging stays put
    machine.run(events[0x26])
    machine.enter(HOME)
    machine.run(events[0x27])
    assert (machine.mode, machine.stack) == (HOME, [MENU])


@pytest.mark.skipif(CARRIED is None, reason="the scaffold carries no Options screens")
def test_each_screen_lights_its_zones_and_a_key_brings_them_back():
    # A screen lights the keypad zones upstairs' screen of its kind lights, and records
    # them; when the off timer has darkened everything, the next key brings back exactly
    # those. Leaving the screen darkens them and forgets them.
    image = generate.configuration(THREE)
    machine = _Idle(image)
    wake = activity_index.contexts(image)[scaffold.KEY_LIGHT_CONTEXT]["rows"][0]
    wake = (wake["operand"], wake["category"])
    keypad = {idle.SCREEN, *idle.KEYPAD}
    off_timer = _off_timer(image)
    machine.variables[idle.AWAKE] = 1
    screens = {"activities": HOME, "options": OPTIONS, "devices": MENU,
               "commands": MENU + 1}
    for kind, ordinal in screens.items():
        zones = set(idle.SCREEN_ZONES[kind])
        machine.enter(ordinal)
        assert machine.lit() & set(range(idle.ZONES)) == zones, kind
        machine.run(machine.timer(off_timer))
        assert not machine.lit(), kind
        machine.run(wake)
        assert machine.lit() == keypad | zones, kind
        machine.run(machine.header(ordinal)[0x07])
        machine.mode = None
        assert machine.lit() == keypad, kind
        machine.run(machine.timer(off_timer), wake)
        assert machine.lit() == keypad, kind


@pytest.mark.skipif(CARRIED is None, reason="the scaffold carries no Options screens")
def test_the_idle_machine_is_generated_and_options_names_only_its_zones():
    # The scaffold carries Options and nothing of upstairs' idle layer: no light
    # instruction, no event or key-light handler. Its screens name the zones they light,
    # and the build resolves every such name to an object of its own.
    assert "idle" not in OPTIONS_MODEL
    text = json.dumps(OPTIONS_MODEL)
    assert '"zones"' in text
    for atoms in OPTIONS_MODEL["objects"]:
        for operand, category in atoms:
            assert not (category == 0x3F and isinstance(operand, int)
                        and operand >> 12 == 0xC), atoms
    assert '"zones"' not in json.dumps(CARRIED)


def _off_timer(image):
    """The timer a key starts only while AWAKE is set: the one that darkens the keypad."""
    machine = _Idle(image)
    wake = activity_index.contexts(image)[scaffold.KEY_LIGHT_CONTEXT]["rows"][0]
    machine.run((wake["operand"], wake["category"]))
    polling = set(machine.timers)
    machine.variables[idle.AWAKE] = 1
    machine.run((wake["operand"], wake["category"]))
    [timer] = machine.timers - polling
    return timer


@pytest.mark.skipif(CARRIED is None, reason="the scaffold carries no Options screens")
def test_start_up_clears_the_zones_before_it_enters_activities():
    # Entering a screen records its zones; start-up clears the records, so it enters
    # the first screen last, as upstairs does - else the first timeout lost them.
    image = generate.configuration(THREE)
    machine = _Idle(image)
    start = gspm.section_ranges(image)[9][0]
    [entry] = [struct.unpack_from("<HB", image, start + 1)]
    machine.run(entry)
    assert machine.mode == HOME
    machine.run(machine.timer(_off_timer(image)))
    assert not machine.lit()
    wake = activity_index.contexts(image)[scaffold.KEY_LIGHT_CONTEXT]["rows"][0]
    machine.variables[idle.AWAKE] = 1
    machine.run((wake["operand"], wake["category"]))
    assert machine.lit() & set(range(idle.ZONES)) == set(idle.SCREEN_ZONES["activities"])


def test_section_fourteen_holds_the_clock_the_platform_and_a_terminator():
    # The factory image holds nineteen records: seven clock properties that carry into one
    # another, eleven platform properties, and the terminator. A probe holding the clock
    # alone, with no carries, hung the remote on its boot logo.
    image = _configured()
    records = activity_index.engine_records(image)
    shape = activity_index.engine_shape(image)

    # the Options screens' own flags sit between the platform's and the terminator, and
    # the activity counter after them
    carried = len(CARRIED["variables"]) if CARRIED else 0
    assert len(records) == activity_index.PLATFORM_PROPERTIES + carried + bool(CARRIED) + 1
    assert shape["terminator"] is not None
    assert [(r["initial"], r["limit"]) for r in shape["platform"]] == list(
        scaffold.PLATFORM_RECORDS)
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
    assert image[at:at + 7] == structures.object_body([(0xF203, 0x1F), (0xF204, 0x1F)])


def test_mode_zero_list_follows_the_button_count_as_in_every_user_configuration():
    # The firmware reads mode 0's list at a fixed place after LWJL; a count with no
    # entries had it read the first objects as key bindings, and no probe booted.
    image = generate.configuration(PROJECT)
    at = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC)
    assert image[at] == scaffold.HOUSEHOLD_BUTTONS
    entries = image[at + 1:at + 1 + 4 * scaffold.HOUSEHOLD_BUTTONS]
    assert entries == scaffold.mode_zero_list()
    for position in range(scaffold.HOUSEHOLD_BUTTONS):
        code, target, opcode = struct.unpack_from("<BHB", entries, 4 * position)
        assert (target, opcode) == (position, structures.OBJECT_ATOM)
        assert code == scaffold.MODE_ZERO_EVENTS[position]


def test_objects_0_to_54_are_mode_zeros_handlers():
    image = generate.configuration(PROJECT)
    start, _ = gspm.section_ranges(image)[11]
    pointers = [int.from_bytes(image[start + 2 + 3 * i:start + 5 + 3 * i], "little")
                - gspm.BASE for i in range(scaffold.HOUSEHOLD_BUTTONS)]
    events = set(scaffold.MODE_ZERO_EVENT_AT.values())
    for index, at in enumerate(pointers):
        body = image[at:at + 1 + 3 * image[at]]
        if index in events:
            # Enter, leave and redraw call the platform's own mode 0 handlers.
            assert body[0] == 1 and body[3] == structures.OBJECT_ATOM
            assert struct.unpack_from("<H", body, 1)[0] >= scaffold.HOUSEHOLD_BUTTONS
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
        assert tags.count(scaffold.ENTER) == 1 and tags.count(scaffold.LEAVE) == 1, ordinal


def _press(machine, image, ordinal, page, key):
    """Run what ``key`` does on one page of a screen."""
    for entry in ui_index.screen_slots(image)[ordinal]["slots"][page]["entries"]:
        if entry["key_code"] == key:
            machine.run((entry["operand"], structures.OBJECT_ATOM))
            return
    raise AssertionError(f"screen {ordinal} page {page} binds no key {key:#04x}")


def test_date_and_time_offers_the_build_year_and_sets_the_clock_through_its_pickers():
    # Built in 2028, a leap year: Year offers 2027 to 2029; 2028 leads to the leap Month
    # screen, whose February leads to 29 days; then hour, minute and the afternoon.
    built = generate.build(THREE, stamp_fields=(0, 0, 0, 0, 0, 2028))
    image = built["image"]
    model = generate.options_model(FONTS, 2028)
    first = OPTIONS + 1
    year = first + model["entries"]["date-and-time"]
    texts = [t for _a, _x, _y, t in _texts(built, year)]
    assert [t for t in texts if t.isdigit()] == ["2027", "2028", "2029"]
    machine = _Idle(image)
    machine.enter(year)
    _press(machine, image, year, 0, 0xB1)                    # 2028
    assert machine.variables[6] == 28
    month = machine.mode
    _press(machine, image, month, 0, 0xB1)                   # February
    assert machine.variables[5] == 1
    day = machine.mode
    assert len(ui_index.screen_slots(image)[day]["slots"]) == 5      # 29 days, six a page
    _press(machine, image, day, 4, 0xB4)                     # the 29th
    assert machine.variables[3] == 28
    hour = machine.mode
    _press(machine, image, hour, 1, 0xB3)                    # 9:00
    assert machine.variables[2] == 9
    minute = machine.mode
    _press(machine, image, minute, 9, 0xB5)                  # 59
    assert machine.variables[1] == 59
    _press(machine, image, machine.mode, 0, 0xB1)            # PM
    assert machine.variables[2] == 21
    assert machine.mode == OPTIONS
    # the year before is not a leap year: its February has 28 days
    machine.enter(year)
    _press(machine, image, year, 0, 0xB0)
    _press(machine, image, machine.mode, 0, 0xB1)
    last = [t for _a, _x, y, t in _texts(built, machine.mode, 4) if y != 18]
    assert "28" in last and "29" not in last


def test_the_options_screens_draw_their_text_from_the_catalogue():
    # Nothing of a donor's language: every word on the Options screens is the catalogue's.
    from afterglow.backends.harmony_one import catalogue

    built = generate.build(THREE)
    image = built["image"]
    model = generate.options_model(FONTS, generate.build_stamp()[-1])
    words = {message.text for message in catalogue.MESSAGES} | {
        message.plural for message in catalogue.MESSAGES if message.plural}
    for index in range(len(model["modes"])):
        ordinal = OPTIONS + 1 + index
        for page in range(len(ui_index.screen_slots(image)[ordinal]["slots"])):
            for _a, _x, _y, text in _texts(built, ordinal, page):
                assert text in words or text == "/" or text.replace(":", "").isdigit(), text


def test_the_firmware_s_screens_carry_no_words_of_their_own():
    # The scaffold keeps their pictures and logic; every word is a label the build draws
    # from platform_text's table, so no donor's text or language rides along.
    from afterglow.backends.harmony_one import platform_text

    system = firmware_screens.load_system()
    items = [item for block in system["blocks"] for item in block]
    assert not [item for item in items if item["opcode"] in ("text", "inline_text")]
    labels = [item for item in items if item["opcode"] == "label"]
    assert labels and all(platform_text.text(item, ENGLISH) for item in labels)


def test_the_firmware_s_screens_and_clock_draw_the_table_s_words():
    from afterglow.backends.harmony_one import platform_text

    built = generate.build(THREE)
    assert [t for _a, _x, _y, t in _texts(built, 1)] == [ENGLISH("system.screen.1")]
    message = _texts(built, 10)
    assert (2, 6, 4, ENGLISH("system.message", number=0)) in message
    # centred, as the donors centred them
    for attribute, x, _y, words in message:
        if words == ENGLISH("system.screen.10").split("\n")[0]:
            widths, codes = pages.measure(FONTS[attribute])
            width = sum(widths[codes[c]] for c in words)
            assert x == (platform_text.SCREEN_WIDTH - width) // 2


def test_every_font_slot_numbers_its_glyphs_the_build_s_own_way():
    # With every word drawn by the build, the codes are the build's: printable ASCII from
    # code 1 in every slot, rather than each donor font's own sparse table.
    from afterglow.backends.harmony_one import faces

    for role, font in _LOADED["fonts"].items():
        assert {code: item["char"] for code, item in font["glyphs"].items()} == dict(
            enumerate(faces.REPERTOIRE, start=1)), role


def test_the_translation_template_lists_every_word_a_build_draws():
    # locale/harmony-one.pot is written from the catalogue (tools/harmony_one_pot.py);
    # a word changed without rewriting it would leave translators a stale template.
    from afterglow.backends.harmony_one import catalogue

    shipped = (catalogue.LOCALE_DIR / f"{catalogue.DOMAIN}.pot").read_text("utf-8")
    assert shipped == catalogue.template()


def test_a_project_s_language_picks_its_catalogue_and_english_fills_the_gaps(
        tmp_path, monkeypatch):
    # settings.locale is the Logitech code the other remotes read; "fin" finds fi.po. A
    # word it translates is drawn translated, one it does not stays English, and a notice
    # translated into more lines is centred on the space the English took.
    from afterglow.backends.harmony_one import catalogue

    (tmp_path / "fi.po").write_text("\n".join([
        'msgid ""', 'msgstr ""', '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"', "",
        'msgctxt "hub.activities-title"', 'msgid "My Activities"', 'msgstr "Toiminnot"', "",
        'msgctxt "system.screen.1"', 'msgid "USB Connected"',
        'msgstr "USB"', '"\\n"', '"kytketty"', ""]), "utf-8")
    monkeypatch.setattr(catalogue, "LOCALE_DIR", tmp_path)
    project = dict(THREE, settings={"locale": "fin"})
    built = generate.build(project)
    home = [t for _a, _x, y, t in _texts(built, HOME) if y == 4]
    assert home == ["Toiminnot", "Toiminnot"]
    assert (3, 6, 4, ENGLISH("hub.devices-title")) in _texts(built, MENU)
    usb = [(y, t) for _a, _x, y, t in _texts(built, 1)]
    assert [t for _y, t in usb] == ["USB", "kytketty"]
    english = [y for _a, _x, y, _t in _texts(generate.build(THREE), 1)]
    assert usb[0][0] < english[0] < usb[1][0]


def test_english_is_a_catalogue_in_step_with_the_words_a_build_draws(tmp_path, monkeypatch):
    # en.po lists every message with its English; rewriting it from the catalogue changes
    # nothing, and a project with no language reads it - so editing it rewords the remote.
    from afterglow.backends.harmony_one import catalogue

    shipped = (catalogue.LOCALE_DIR / "en.po").read_text("utf-8")
    assert catalogue.english_catalogue(shipped) == shipped
    assert len(po.parse(shipped).messages) == len(catalogue.MESSAGES)
    (tmp_path / "en.po").write_text(shipped.replace(
        'msgstr "My Activities"', 'msgstr "Things To Do"'), "utf-8")
    monkeypatch.setattr(catalogue, "LOCALE_DIR", tmp_path)
    home = [t for _a, _x, y, t in _texts(generate.build(THREE), HOME) if y == 4]
    assert home == ["Things To Do", "Things To Do"]


def test_each_font_slot_carries_only_the_characters_its_image_draws():
    # As Logitech's builder did: a slot holds the glyphs its own text uses, numbered from
    # 1, rather than the whole repertoire - the clock's font draws digits and weekday
    # letters, not the alphabet.
    image = generate.configuration(THREE)
    counts = [len(font["glyphs"]) for font in font_index.fonts(image)]
    assert max(counts) < len(generate.catalogue.characters(ENGLISH))
    clock = font_index.fonts(image)[17]["glyphs"]
    assert 10 <= len(clock) < 40


def test_a_device_page_shows_what_no_key_sends_and_a_device_all_on_keys_keeps_its_page():
    # As Logitech's pages: a key's own command is pressed there - VolumeUp on VolumeUp, 1 on
    # Number1 - while one put on a key in its place, Return on Exit, keeps its button; one
    # with no label - an import's press-only copy or nameless code - is on no page.
    from afterglow.backends.harmony_one import hub

    lowered = devices.lowered_devices({"devices": [
        {"label": "TV", "signals": {name: _nec(4, n) for n, name in enumerate(
            ("Netflix", "VolumeUp", "Code 7", "Guide", "1", "Return"))},
         "commands": [["Netflix", "Netflix", "", "", None],
                      ["VolumeUp", "VolumeUp", "", "", ["VolumeUp"]],
                      ["Code 7", "", "", "", None], ["Guide", "Guide", "", "", None],
                      ["1", "1", "", "", ["Number1"]], ["Return", "Return", "", "", ["Exit"]]]},
        {"label": "Amp", "signals": {"VolumeUp": _nec(11, 1)},
         "commands": [["VolumeUp", "VolumeUp", "", "", ["VolumeUp"]]]}]})
    bodies = {role: item["body"] for role, item in _LOADED["pictures"].items()}
    shown = hub.device_pages(lowered, pages.frames(bodies), set(bodies), FONTS[0])
    assert [[command["name"] for command in page] for page in shown[0]] == [
        ["Guide", "Netflix", "Return"]]
    assert shown[1] == [[]]


def test_the_remote_assistant_asks_after_an_input_by_the_name_a_person_reads():
    from afterglow.project_devices import input_label

    assert [input_label(name) for name in (
        "InputHdmi1", "InputTv", "InputComponent", "InputVideo2", "HDMI 1", "Netflix")] == [
        "HDMI 1", "TV", "Component", "Video 2", "HDMI 1", "Netflix"]
    tv = {"id": "tv", "label": "TV", "signals": {"PowerOn": _nec(4, 1), "PowerOff": _nec(4, 2),
                                                 "InputHdmi1": _nec(4, 3)},
          "power_on_cmd": "PowerOn", "power_off_cmd": "PowerOff",
          "inputs": [["InputHdmi1", "InputHdmi1"]]}
    built = generate.build({"devices": [tv], "activities": [
        {"id": "1", "label": "Watch", "type": "VirtualTelevisionN", "display": "tv",
         "control": "tv", "power_on_devices": ["tv"],
         "enter": [["input", "tv", "InputHdmi1"]]}]})
    from afterglow.backends.harmony_one import labels

    image = built["image"]
    text = labels.Text(image)
    drawn = {item["text"] for screen in ui_index.screen_slots(image)
             for slot in screen["slots"]
             for item in labels.screen_text(image, slot["program_offset"], text)}
    # "Is the TV set to the HDMI 1 input?", as Logitech's Help asks
    assert any(line.endswith("set to the HDMI 1") for line in drawn)
    assert not any("set to" in line and "InputHdmi1" in line for line in drawn)
