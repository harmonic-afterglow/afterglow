"""The Harmony 800 backend: images read as the 800's firmware reads them.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

import struct
import zipfile

import pytest

from afterglow import ir_signal
from afterglow.backends.harmony_800 import (
    backend, geometry, gsgd, ir_lowering, key_test, lists, structures)
from afterglow.backends.harmony_800 import generate


def _nec(address, command):
    pulses = [9000, -4500]
    for byte in (address, address ^ 0xFF, command, command ^ 0xFF):
        for bit in range(8):
            pulses += [560, -1690] if (byte >> bit) & 1 else [560, -560]
    return ir_signal.waveform(pulses + [560, -40000], carrier_hz=38000)


PROJECT = {"devices": [
    {"label": "Living Room TV", "type": "Television",
     "signals": {name: _nec(4, n) for n, name in enumerate(
         ["PowerToggle", "VolumeUp", "VolumeDown", "Mute", "ChannelUp", "ChannelDown",
          "InputNext", "Menu", "DirectionUp", "DirectionDown", "Select", "Exit", "Netflix"])},
     "commands": [["VolumeUp", "Volume Up", "", "", "VolumeUp"]]},
    {"label": "Blu-ray Disc Player", "type": "DvdCd",
     "signals": {"PowerToggle": _nec(0x0A, 1), "Play": _nec(0x0A, 2)}},
]}


@pytest.fixture(scope="module")
def image():
    return generate.build(PROJECT)["image"]


@pytest.fixture(scope="module")
def empty():
    return generate.build({"devices": []})["image"]


def _u24(image, offset):
    return int.from_bytes(image[offset:offset + 3], "little") - gsgd.BASE


def _rows(image, offset):
    """A list as FUN_08017f1c reads it."""
    if image[offset]:
        return [struct.unpack_from("<HHB", image, offset + 1 + 5 * j)
                for j in range(image[offset])]
    count, at = (image[offset + 1], offset + 2) if image[offset + 1] else \
        (image[offset + 2], offset + 3)
    return [struct.unpack_from("<HHB", image, at + 6 * j + 1) for j in range(count)]


def _screens(image):
    s6 = gsgd.sections(image)[6]
    out = []
    for k in range(struct.unpack_from("<H", image, s6)[0]):
        trailer = _u24(image, s6 + 3 + 3 * k)
        slot = _u24(image, trailer + 6)
        out.append({"list": _u24(image, trailer + 1), "template": image[slot],
                    "keys": _u24(image, slot + 1), "program": _u24(image, slot + 4)})
    return out


def _objects(image):
    s11 = gsgd.sections(image)[11]
    out = []
    for i in range(struct.unpack_from("<H", image, s11)[0]):
        at = _u24(image, s11 + 2 + 3 * i)
        out.append([struct.unpack_from("<HB", image, at + 1 + 3 * j) for j in range(image[at])])
    return out


def _entered(image, operand, opcode, objects, seen=None):
    """The screens an instruction can enter, through objects and through selecting a
    context (`1F FFxx`), which runs that context's tag 1."""
    seen = set() if seen is None else seen
    if opcode == lists.SCREEN:
        return {operand}
    if opcode == 0x1F and operand >> 8 == 0xFF and operand & 0xFF < 0xF0:
        s10 = gsgd.sections(image)[10]
        context = operand & 0xFF
        if context >= image[s10] or ("context", context) in seen:
            return set()
        seen.add(("context", context))
        rows = _rows(image, _u24(image, s10 + 1 + 3 * context))
        return set().union(set(), *(_entered(image, o, c, objects, seen)
                                    for tag, o, c in rows if tag == 0x01))
    if opcode != lists.OBJECT or operand in seen:
        return set()
    seen.add(operand)
    return set().union(*(_entered(image, o, c, objects, seen) for o, c in objects[operand]))


def test_an_image_is_what_the_firmware_accepts(image, empty):
    for built in (image, empty):
        assert gsgd.validate(built)["ok"]
        assert built[:4] == b"GSGD" and built[-4:] == b"OGSA"
        assert built[0x63:0x67] == b"CHJL"
        assert len(set(gsgd.sections(built))) == gsgd.SECTION_COUNT
        assert built[gsgd.sections(built)[8]] == 0            # no radio commands


def test_it_starts_on_the_hub_and_reaches_every_device(image):
    objects, screens = _objects(image), _screens(image)
    s9 = gsgd.sections(image)[9]
    assert image[s9] == 1
    operand, opcode = struct.unpack_from("<HB", image, s9 + 1)
    hub = 40
    assert hub in _entered(image, operand, opcode, objects)
    devices_softkey = [r for r in _rows(image, screens[hub]["keys"]) if r[0] == 0xC031]
    [(_tag, menu_object, _c)] = devices_softkey
    [menu] = _entered(image, menu_object, lists.OBJECT, objects)
    targets = set().union(*(_entered(image, o, c, objects)
                            for _t, o, c in _rows(image, screens[menu]["keys"])))
    assert len(targets & {s for s in range(len(screens))}) >= 3   # two devices and back
    # past the last device page is the light test - a page for each LED, a touch moving on -
    # then the key test, which names every code it answers
    [(_tag, strip, _c)] = [r for r in _rows(image, screens[menu]["keys"]) if r[0] == 0xC02F]
    [light] = _entered(image, strip, lists.OBJECT, objects)
    page = light
    for led in key_test.LEDS:
        enter = [o for tag, o, c in _rows(image, screens[page]["list"]) if tag == 0x06]
        lit = [operand for operand, opcode in objects[enter[0]]
               if opcode == 0x3F and operand >> 8 == 0xC0 and operand & 0x0E]
        assert [(operand & 0xFF) >> 4 for operand in lit] == [led]
        [(_t, nxt, _c)] = [r for r in _rows(image, screens[page]["list"]) if r[0] == 0xC07F]
        [page] = _entered(image, nxt, lists.OBJECT, objects)
    test = page
    assert test == light + len(key_test.LEDS)
    answered = {tag for tag, _o, _c in _rows(image, screens[test]["list"])}
    assert {0xC000, 0xC02B, 0xC07E, 0xC400} <= answered
    assert len(_rows(image, screens[test]["list"])) <= 255
    assert len(screens) == light + key_test.screen_count()


def test_every_ir_send_names_a_command_whose_waveforms_are_the_ones_lowered(image):
    sections = gsgd.sections(image)
    s5 = sections[5]
    assert image[s5] == len(PROJECT["devices"])
    for index, device in enumerate(PROJECT["devices"]):
        table = _u24(image, s5 + 1 + 3 * index)
        names = sorted(device["signals"])
        assert struct.unpack_from("<H", image, table + 1)[0] == len(names)
        for ordinal, name in enumerate(names):
            record = _u24(image, table + 3 + 3 * ordinal) - 11
            lowered = ir_lowering.lower(device["signals"][name])
            press = _u24(image, record + 16)
            assert image[press:press + len(lowered.press_waveform)] == lowered.press_waveform
    sends = [(operand >> 8, operand & 0xFF) for atoms in _objects(image)
             for operand, opcode in atoms if opcode == lists.IR_SEND]
    assert sends
    for device, ordinal in sends:
        table = _u24(image, s5 + 1 + 3 * device)
        assert ordinal < struct.unpack_from("<H", image, table + 1)[0]


# Operand lengths of the 800's drawing VM (FUN_08013c1c).
def _walk(image, start, calls=0, ops=None):
    at = start
    for _ in range(4000):
        op = image[at]
        if ops is not None:
            ops.add(op)
        if op == 0x00:
            return
        if op == 0x17:
            return
        if op == 0x01:
            x, y, w, h, _c = struct.unpack_from("<5H", image, at + 1)
            assert x + w <= 240 and y + h <= 320, (hex(at), x, y, w, h)
            at += 11
        elif op in (0x02, 0x04):
            x, y = struct.unpack_from("<HH", image, at + 1)
            assert x < 240 and y < 320, (hex(at), x, y)
            if op == 0x02:
                picture = _u24(image, at + 5)
                _mode, width, height = struct.unpack_from("<BHH", image, picture)
                assert x + width <= 240 and y + height <= 320, (hex(at), x, y, width, height)
            at += 8
        elif op == 0x05:
            x, y = struct.unpack_from("<HH", image, at + 1)
            assert x < 240 and y < 320, (hex(at), x, y)
            at += 5
            while image[at]:
                at += 2 if image[at] & 0x80 else 1
            at += 1
        elif op == 0x10:
            at += 2
        elif op == 0x11:
            at += 4
        elif op == 0x12:
            cases = image[at + 2]
            ranges = image[at + 3 + 4 * cases]
            at += 4 + 4 * cases + 5 * ranges
        elif op == 0x14:
            return _walk(image, _u24(image, at + 1), calls, ops)
        elif op == 0x16:
            if calls < 2:
                _walk(image, _u24(image, at + 1), calls + 1, ops)
            at += 4
        else:
            raise AssertionError(f"opcode {op:#x} at {at:#x}")
    raise AssertionError(f"program at {start:#x} does not end")


def test_every_page_draws_inside_the_800s_display(image):
    for screen in _screens(image):
        _walk(image, screen["program"])


def _first_draw(image, at, depth=0):
    """The first thing a program puts on the display, following its calls."""
    while True:
        op = image[at]
        if op == 0x16 and depth < 3:
            first = _first_draw(image, _u24(image, at + 1), depth + 1)
            if first is not None:
                return first
            at += 4
        elif op == 0x10:
            at += 2
        elif op in (0x04, 0x05, 0x01, 0x02):
            return op, at
        elif op == 0x11:
            at += 4
        else:
            return None


def test_every_page_clears_the_display_with_a_picture(image):
    """The drawing VM's rectangle writes without selecting the LCD, so after any picture it
    draws nothing (gsgd.md, "Drawing"): the screens this backend builds begin with the
    full-screen backdrop, as every Logitech image's do, and draw no rectangle."""
    for k, screen in enumerate(_screens(image)):
        ops = set()
        _walk(image, screen["program"], ops=ops)
        assert 0x01 not in ops, k
        first = _first_draw(image, screen["program"])
        if first is None:
            continue
        op, at = first
        assert op != 0x01, (k, hex(at))
        if op == 0x02:
            picture = _u24(image, at + 5)
            _mode, width, height = struct.unpack_from("<BHH", image, picture)
            assert struct.unpack_from("<HH", image, at + 1) == (0, 0) and (width, height) == (240, 320), k


def _firmware_checksum(image):
    """The checksum as the 800's firmware takes it (FUN_0800efd0 / FUN_0800f144): every
    byte before the stored checksum, an odd last one into the low lane."""
    end = struct.unpack_from("<I", image, 4)[0] - gsgd.BASE - 2
    value = 0x4321
    for offset in range(0, end - end % 2, 2):
        value ^= image[offset] | image[offset + 1] << 8
    if end % 2:
        value ^= image[end - 1]
    return value


def test_the_firmware_takes_the_checksum_an_image_stores(image, empty):
    for built in (image, empty):
        assert (len(built) - 6) % 2 == 0
        assert _firmware_checksum(built) == struct.unpack_from("<H", built, len(built) - 6)[0]
    # an odd length is the case the firmware reads differently from Concordance
    assert gsgd.checksum(b"\x01\x02\x03", 3) == (0x21 ^ 0x01 ^ 0x03, 0x43 ^ 0x02)


# What the 800's firmware posts as an event (gsgd.md, "Events"), the codes a mode or
# context answers, and 0x30, which Logitech's own image answers.
EVENTS_800 = set(range(0x17, 0x2F)) | {0x30, 0x31, 0x32, 0x33, 0x34, 0x01, 0x02, 0x05, 0x06, 0x07}


def _contexts(image):
    s10 = gsgd.sections(image)[10]
    return [_u24(image, s10 + 1 + 3 * c) for c in range(image[s10])]


def test_every_event_answered_is_one_the_800_posts(image):
    lists = [s["list"] for s in _screens(image)] + [s["keys"] for s in _screens(image)]
    for at in lists + _contexts(image):
        tags = [tag for tag, _o, _c in _rows(image, at)]
        assert len(tags) == len(set(tags)), hex(at)
        events = {tag for tag in tags if tag < 0x100}
        assert events <= EVENTS_800, sorted(map(hex, events - EVENTS_800))
    # the One's USB in is the 800's 0x2B; the One's 0x26 is a charger report there
    assert structures.tag(0x26) == 0x2B and structures.tag(0x0F) == 0x20


def test_lights_name_the_800s_channels(image):
    """Every light is an LED (0-6) or the backlight (7), which is only ever turned to the
    level the idle layer wakes it to or off when it times out."""
    lights = []
    for atoms in _objects(image):
        lights += [operand for operand, opcode in atoms
                   if opcode == 0x3F and 0xC000 <= operand <= 0xCFFF]
    assert lights
    for operand in lights:
        channel, level = (operand & 0xFF) >> 4, (operand >> 1) & 7
        assert operand >> 8 == 0xC0 and channel <= 7, hex(operand)
        if channel == 7:
            assert level in (0, 6), hex(operand)
    assert any((operand & 0xFF) >> 4 == 7 and (operand >> 1) & 7 == 6 for operand in lights)


def test_lists_and_zones_speak_the_800s_dialect():
    assert structures.tag(0xB0) == 0xC030 and structures.tag(0x2E) == 0x2E
    assert structures.tag(0xC405) == 0xC405
    assert structures.key_register([]) == b"\x00\x00\x00"
    assert structures.key_register([(0xB0, 7, 0x7F)]) == b"\x01\x30\xc0\x07\x00\x7f"
    strip = geometry.touch_zone({"x": 765, "width": 492, "y": 1400, "height": 2000, "tag": 0x2E})
    assert (strip["x"], strip["width"], strip["y"], strip["height"]) == (0, 240, 505, 1011)
    zone = geometry.pixels(6, 38, 114, 50, 0x30)
    assert zone["x"] == 277
    assert abs(zone["y"] + zone["height"] - (2020 - 38 * 1790 / 320)) <= 1


def test_a_build_is_the_configuration_concordance_sends(tmp_path, image):
    path = backend.configuration_file(image, tmp_path / "harmony800.EZHex")
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == ["Description.xml", "Result.EzHex"]
        assert archive.read("Result.EzHex") == image
        xml = archive.read("Description.xml").decode()
    low, high = gsgd.checksum(image, len(image) - 6)
    assert f'SIZE="{len(image)}"' in xml and 'PATH="/cfg/usercfg"' in xml
    assert f'EXPECTEDVALUE="0x{(high << 8) | low:04x}"' in xml and "<SKIN>86</SKIN>" in xml
    assert backend.read_configuration_file(path) == image


def test_the_profile_is_experimental_never_verified_without_hardware():
    from afterglow import remotes
    profile = remotes.get("harmony-800")
    assert profile.status == "experimental" and profile.backend == "harmony-800"
    profile.require_buildable()


def test_the_status_bar_draws_inside_the_display_too(image):
    s12 = gsgd.sections(image)[12]
    overlays = struct.unpack_from("<H", image, s12)[0]
    assert overlays
    for index in range(overlays):
        _walk(image, _u24(image, s12 + 2 + 3 * index))


WATCHING = {"devices": [
    {"id": "1", "label": "TV", "type": "Television",
     "signals": {name: _nec(4, n) for n, name in enumerate(
         ["PowerOn", "PowerOff", "InputHdmi1"] + [str(digit) for digit in range(10)])},
     # the digits on the number keys, as a catalogue device has them: off its pages
     "commands": [[str(digit), str(digit), "", "", f"Number{digit}"] for digit in range(10)]},
    {"id": "2", "label": "Console", "type": "GameConsole",
     "signals": {"PowerToggle": _nec(0x0A, 1), "A": _nec(0x0A, 2)}},
], "activities": [
    {"id": "1001", "label": "Play", "type": "VirtualGameConsole", "display": "1",
     "control": "2", "volume": "1", "soft_buttons": [["A", "2", "A"]]},
]}


def test_the_keypad_sends_the_digits_of_a_device_that_has_them():
    from afterglow.backends.harmony_800 import activities, devices
    lowered = devices.lowered_devices(WATCHING)
    [act] = activities.plan(WATCHING, lowered)["activities"]
    # the console has no digits, so the keypad is the display's, 1-9 then -, 0, Enter
    labels = [label for label, _steps in act["numbers"]]
    assert labels == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "+", "0", "E"]
    # the TV has neither + nor Enter: those keys are drawn and send nothing
    assert [steps is None for _label, steps in act["numbers"]].count(True) == 2
    assert {steps[0][1] for _label, steps in act["numbers"] if steps} == {0}
    assert generate.build(WATCHING)["image"]


def test_the_keypad_fits_the_display_without_overlaps():
    from afterglow.backends.harmony_800 import pages
    boxes = [(x, y, x + pages.NUMPAD_WIDTH, y + pages.NUMPAD_HEIGHT)
             for x, y in pages.NUMPAD_POSITIONS]
    assert len(boxes) == 12
    for left, top, right, bottom in boxes:
        assert 0 <= left and right <= 240 and pages.HEADER_HEIGHT <= top
        assert bottom <= pages.SOFTKEY_BAR_TOP
    for index, a in enumerate(boxes):
        for b in boxes[index + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_a_paged_screen_draws_its_page_number_before_a_closing_switch():
    from afterglow.backends.harmony_800 import screens

    class Layout:
        def __init__(self):
            self.programs = []
            self.pending_programs = self.programs

        def template(self, zones):
            return 0

        def program_sizes(self, builds, prologue):
            return [0] * len(builds)

        def mode(self, header, flag, pages):
            return [[0, 1]]

    font = {"glyphs": {code: {"width": 6, "char": char}
                       for code, char in enumerate("0123456789/ pages", 1)}}
    fonts = [font] * 18
    words = type("Words", (), {"plural": lambda self, word, n: "pages"})()
    owned = screens.Screens(Layout(), fonts=fonts, words=words, roles={"backdrop"},
                            label=0, softkey_fonts={}, handlers=lambda kind: [])
    switch = {"opcode": "switch", "selector": 1, "cases": [], "ranges": []}
    owned.owned([], [], lambda picture, prologue: [switch, {"opcode": "end"}], "options",
                "pages", (0, 2))
    _at, program, _prologue = owned.layout.programs[-1]
    drawn = program(lambda role: 0, 0)
    assert drawn[-2:] == [dict(switch, native=True), {"opcode": "end", "native": True}]
    assert any(item["opcode"] == "inline_text" for item in drawn[:-2])


def test_a_device_with_digits_has_a_keypad_and_so_do_its_activities(monkeypatch):
    from afterglow.backends.harmony_800 import devices, keypad, keys
    # the TV's digits are on its number keys, so off its pages - and still its keypad's
    [tv, _console] = devices.lowered_devices(WATCHING)
    assert [label for label, command in keypad.digits(tv) if command] == \
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
    # a keypad screen for the TV and one for the activity that changes channels on it
    with_keypads = len(_screens(generate.build(WATCHING)["image"]))
    with monkeypatch.context() as patch:
        patch.setattr(keypad, "digits", lambda device: [])
        assert with_keypads == len(_screens(generate.build(WATCHING)["image"])) + 2
    # the 123 key opens them - bound once even where a device key had it
    assert keys.NUMBERS == 0x1B
    assert gsgd.validate(generate.build(WATCHING)["image"])["ok"]


def test_a_build_reads_back_as_the_project_it_was_built_from(tmp_path):
    import json
    from afterglow import remotes
    project = {**WATCHING, "settings": {"remote": "harmony-800", "out_file": "/tmp/x.EZHex"}}
    # as a read off the remote arrives: the image as the payload of an unpacked tree
    (tmp_path / "payload.bin").write_bytes(generate.build(project)["image"])
    result = backend.import_project(tmp_path, remotes.get("harmony-800"), {})
    expected = json.loads(json.dumps(project))
    assert result.project["devices"] == expected["devices"]
    assert result.project["activities"] == expected["activities"]
    # where it was written is the building machine's business, not the configuration's
    assert "out_file" not in result.project["settings"]


def test_a_configuration_afterglow_did_not_build_is_refused():
    from afterglow.backends.harmony_800 import mark
    image = bytearray(generate.build(WATCHING)["image"])
    trailer = len(image) - 6 - mark.TRAILER.size     # before the checksum and OGSA
    unmarked = bytearray(image)
    unmarked[trailer:trailer + 16] = bytes(16)
    with pytest.raises(mark.NotAfterglow, match="not made by Afterglow"):
        mark.read(bytes(unmarked))
    damaged = bytearray(image)
    damaged[trailer - 1] ^= 0xFF                      # the project's last byte
    with pytest.raises(mark.NotAfterglow, match="damaged"):
        mark.read(bytes(damaged))


def test_the_key_table_is_the_800s_and_keeps_clear_of_the_touch_zones():
    from afterglow import remotes
    from afterglow.backends.harmony_800 import keys, pages
    # one key per code, each a code the front panel sends (0x01-0x23)
    assert len(set(keys.SCANS.values())) == len(keys.SCANS) == 35
    assert all(0x01 <= scan <= 0x23 for scan in keys.SCANS.values())
    touch = {pages.FIRST_BUTTON_KEY, pages.PAGE_ACTIVITIES_KEY, pages.PAGE_DEVICES_KEY,
             pages.SIDE_PREV_KEY, pages.SIDE_NEXT_KEY, pages.MENU_OPTIONS_KEY,
             pages.MENU_DEVICES_KEY, pages.SOFTKEY_RIGHT_KEY}
    assert not touch & {keys.code(scan) for scan in keys.SCANS.values()}
    # the profile offers exactly the keys that send a device's commands
    assert sorted(remotes.get("harmony-800").hard_keys) == sorted(keys.COMMAND_KEYS)
    assert {"Off", "Activities", "Help", "Numbers", "Mouse"}.isdisjoint(keys.COMMAND_KEYS)


def test_a_digit_on_a_key_the_800_lacks_still_leaves_its_page_but_a_red_key_does_not():
    from afterglow.backends.harmony_800 import devices
    tv = WATCHING["devices"][0]
    project = {"devices": [{**tv, "signals": {**tv["signals"], "Red": tv["signals"]["1"]},
                            "commands": [*tv["commands"], ["Red", "Red", "", "", "Red"]]}],
               "activities": []}
    [tv] = devices.lowered_devices(project)
    shown = {command["name"]: not command.get("hidden") for command in tv["commands"]}
    assert shown.get("1") is False          # on the keypad
    assert shown.get("Red") is True         # the 800 has no Red key


def test_each_of_the_ones_zones_lights_the_800_led_in_its_place():
    from afterglow.backends.harmony_800 import idle
    for zone, led in ((0, 0), (1, 0), (2, 1), (3, 1), (4, 2), (5, 2), (6, 3), (7, 3)):
        assert idle.zone_light(zone, idle.KEY_LEVEL) == idle.light(led, idle.TOUCH_LEVEL)
        assert idle.zone_light(zone, 0) == idle.light(led, 0)


def test_the_checksum_folds_to_the_byte_at_a_time_sum_odd_ends_included():
    import random
    from afterglow.backends.harmony_800 import gsgd
    data = bytes(random.Random(8).randrange(256) for _ in range(4099))
    for end in (0, 1, 2, 3, 1000, 4097, 4099):
        low, high = gsgd.CHECKSUM_SEED
        for offset in range(0, end - end % 2, 2):
            low, high = low ^ data[offset], high ^ data[offset + 1]
        if end % 2:
            low ^= data[end - 1]
        assert gsgd.checksum(data, end) == (low, high)


def test_a_write_is_reported_section_by_section():
    image = generate.build(WATCHING)["image"]
    other = generate.build({**WATCHING, "activities": WATCHING["activities"][:1]})["image"]
    same = backend.compare_payloads(image, image, None)
    assert same["changed"] == [] and same["unchanged"] == 20
    assert backend.compare_payloads(image, other, None)["changed"]


def test_the_800_is_offered_for_building_with_its_picture():
    from afterglow import remotes
    profile = remotes.get("harmony-800")
    assert profile.buildable and not profile.verified
    assert not profile.can("ir_learning")
    assert profile.hard_key_art["svg"].is_file()
    assert set(profile.hard_key_art["keys"]) == set(profile.hard_keys)

