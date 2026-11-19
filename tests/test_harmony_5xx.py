"""Reading a Harmony 5xx configuration (architecture 9) back as a project: the parts of the
arch-14 reader it differs in - its key tables, its drawing rows, its two-byte names - and
that nothing is built. Real configurations live in the git-ignored configs/ folder; the
tests that read them skip without them."""
from __future__ import annotations

import json
import re
import struct

import pytest

from afterglow import ezhex, importer, ir_signal, remotes
from afterglow.backends.harmony_555 import backend, importing, keys, ui_index

from conftest import donors_of

FIVES = ("harmony-510", "harmony-515", "harmony-520", "harmony-525", "harmony-550",
         "harmony-555", "harmony-xbox360")
PROFILES = [profile for profile in remotes.load_all() if profile.backend == "harmony-555"]


def test_every_5xx_profile_names_its_keys_by_scan_codes_its_grid_has():
    assert {profile.id for profile in PROFILES} >= {"harmony-525", "harmony-555"}
    for profile in PROFILES:
        scans = profile.vocabulary["hard_key_scans"]
        assert list(scans) == profile.hard_keys
        assert len(set(scans.values())) == len(scans)
        # no scan is a multiple of 8, and none is a key the firmware owns
        assert all(0 < scan < 64 and scan % 8 for scan in scans.values())
        assert not set(scans.values()) & set(keys.SCREEN_KEYS.values())
        assert not set(scans.values()) & {keys.PAGE_FORWARD, keys.PAGE_BACK, *keys.FLOW.values()}
        keys.Keypad.of(profile)


def test_the_550_and_the_555_name_one_scan_code_differently():
    pad = {profile.id: keys.Keypad.of(profile) for profile in PROFILES}
    # the bar above the d-pad: page keys on the 550, the layout switch on the 555
    assert pad["harmony-550"].name_of(keys.code(36)) == "PageUp"
    assert pad["harmony-555"].name_of(keys.code(36)) is None
    assert pad["harmony-525"].name_of(keys.code(37)) == "VolumeMute"
    assert pad["harmony-555"].by_name("VolumeMute") == keys.code(61)


def test_the_555s_keys_measured_on_the_remote():
    # a key test on a real 555: each key showed its own scan
    pad = keys.Keypad.of(remotes.get("harmony-555"))
    assert pad.by_name("Clear") == keys.code(19)
    assert pad.by_name("NumberEnter") == keys.code(25)
    assert pad.by_name("PrevChannel") == keys.code(58)
    assert keys.SCREEN_KEYS == {"top-left": 39, "top-right": 38,
                                "bottom-left": 31, "bottom-right": 30}


def test_a_key_the_firmware_owns_cannot_be_given_to_a_command():
    with pytest.raises(ValueError):
        keys.Keypad({"VolumeUp": keys.OFF})
    assert keys.Keypad().name_of(keys.code(keys.OFF)) == "Off"


def test_a_drawing_row_takes_one_byte_and_its_transfer_none():
    # 16 <row> selects a display row; 17 sends it; neither is a call or a return
    program = ui_index.drawing_program(bytes([0x16, 3, 0x17, 0x16, 4, 0x17, 0x00]), 0)
    assert [item["opcode"] for item in program["instructions"]] == \
        ["row", "transfer", "row", "transfer", "end"]
    assert program["instructions"][2]["value"] == 4
    assert program["stopped"] == "end"


def test_a_name_with_two_byte_letters_reads_whole():
    assert importing._wide("\x22\x04\x12\x04") == "ТВ"
    assert importing._wide("\x1c\x048\x04=\x048\x04-") == "Мини-"
    assert importing._wide("AV Receiver") == "AV Receiver"


def test_a_read_only_5xx_is_not_built_though_its_signals_could_be(tmp_path):
    profile = remotes.get("harmony-555")
    if profile.status == "read-only":
        with pytest.raises(remotes.NotBuildable):
            backend.build_project({"devices": [], "activities": []}, profile, None)
    signal = ir_signal.waveform([9000, -4500, 560, -40000], carrier_hz=38000)
    answer = backend.capability(signal, profile)
    assert answer["supported"] is True


def _configs():
    from pathlib import Path

    found = [Path(path) for remote in FIVES for path in donors_of(remote)]
    if not found:
        pytest.skip("no real Harmony 5xx configurations available")
    return found


def _import(path, tmp_path):
    source = tmp_path / "source"
    ezhex.unpack(str(path), str(source))
    return importer.import_result(source)


PLACEHOLDER = re.compile(r"^(Device|Activity) \d+$")


def test_every_5xx_configuration_imports_with_its_own_names(tmp_path):
    # a device or an activity keeps a numbered name only where nothing names it: no page,
    # no row on a list, no name in the name table - a device a decompiler appended
    for index, path in enumerate(_configs()):
        result = _import(path, tmp_path / str(index))
        project = result.project
        native = result.preservation["inventory"]["ownership"]["devices"]
        assert len(project["devices"]) == len(native), path
        image = importing.Image(ezhex.read(path.read_bytes()).payload)
        unnamed = [device["label"] for device in project["devices"]
                   if PLACEHOLDER.match(device["label"])]
        assert len(unnamed) <= len(native) - len(importing.command_pages(image)), path
        assert not [activity["label"] for activity in project["activities"]
                    if PLACEHOLDER.match(activity["label"])], path
        assert not any(note.startswith("could not read the image's screens")
                       for note in result.warnings), path


def test_a_command_on_a_key_is_named_by_that_key(tmp_path):
    named = 0
    for index, path in enumerate(_configs()):
        for device in _import(path, tmp_path / str(index)).project["devices"]:
            for name, keys_ in ((command[0], command[4]) for command in device["commands"]):
                for key in keys_ or ():
                    named += name == key
    assert named


def test_a_glyph_row_is_written_as_logitech_wrote_it():
    from afterglow.backends.harmony_555 import pixels

    def row(text):
        return [1 if character == "#" else 0 for character in text]
    # runs of five or more are runs, what lies between them literals, and a literal of
    # one colour a run after all
    assert pixels.glyph_row(row(".####.")).hex() == "559560"
    assert pixels.glyph_row(row("#####.")).hex() == "a460"
    assert pixels.glyph_row(row(".#.....")).hex() == "519064"
    assert pixels.glyph_row(row("...")).hex() == "62"
    rows = [row("..##.."), row(".#..#."), row("######")]
    assert ui_index.glyph_mask(pixels.encode_glyph(rows), 0)[0] == [bytes(r) for r in rows]


def test_a_picture_reads_back_as_it_was_written():
    from afterglow.backends.harmony_555 import pixels

    rows = [[(x + y) % 3 == 0 for x in range(13)] for y in range(5)]
    picture = pixels.decode_picture(pixels.encode_picture(rows), 0)
    assert (picture["width"], picture["height"]) == (13, 5)
    assert picture["rows"] == [[int(pixel) for pixel in row] for row in rows]


def _other_ink(stream: bytes) -> bool:
    """Whether a glyph draws with pixel value 0, the second ink (a run of kind 8, or a
    literal's 00): Logitech's 550 demo loop alone does."""
    cursor = 1
    while stream[cursor]:
        end = cursor + 1 + (stream[cursor] & 0x1F)
        cursor += 1
        while cursor < end:
            kind, count = stream[cursor] >> 4, (stream[cursor] & 0x0F) + 1
            cursor += 1
            if kind == ui_index.OTHER_INK:
                return True
            if kind == ui_index.LITERAL:
                size = (2 * count + 7) // 8
                bits = int.from_bytes(stream[cursor:cursor + size], "big")
                if any((bits >> (8 * size - 2 * (index + 1))) & 3 == 0
                       for index in range(count)):
                    return True
                cursor += size
    return False


def test_every_glyph_logitech_wrote_encodes_back_to_its_own_bytes():
    from afterglow.backends.harmony_555 import font_index, gspm, pixels

    same = differ = second_ink = 0
    for path in _configs():
        payload = ezhex.read(path.read_bytes()).payload
        for font in font_index.fonts(payload):
            for glyph in font["glyphs"].values():
                offset = glyph["pointer"] - gspm.BASE
                rows, size = ui_index.glyph_mask(payload, offset)
                encoded = pixels.encode_glyph(rows)
                assert ui_index.glyph_mask(encoded, 0)[0] == rows
                if _other_ink(payload[offset:offset + size]):
                    second_ink += 1         # drawn in an ink a build never writes
                elif encoded == payload[offset:offset + size]:
                    same += 1
                else:
                    differ += 1
    # the one configuration harmony-decompiler wrote itself carries its own encoder's
    # glyphs; every glyph of Logitech's comes back byte for byte
    assert differ * 1000 <= same
    assert second_ink <= 25         # the 550 demo loop's, counted, never compared


def _readable(payload: bytes, tmp_path) -> dict:
    """What an image says as a project, without the offsets that say where it is."""
    from afterglow import payloads

    def scrub(item):
        if isinstance(item, dict):
            return {key: scrub(value) for key, value in item.items()
                    if "offset" not in key and key not in ("evidence", "record_prefix")}
        if isinstance(item, list):
            return [scrub(value) for value in item]
        return item
    source = tmp_path / "source"
    payloads.get("blob").unpack(payload, str(source))
    result = backend.import_project(str(source), remotes.get("harmony-555"), {})
    return scrub(result.project)


def test_bytes_inserted_anywhere_between_structures_move_every_pointer(tmp_path):
    from afterglow.backends.harmony_555 import gspm, relocate

    for index, path in enumerate(_configs()[:4]):
        payload = ezhex.read(path.read_bytes()).payload
        before = _readable(payload, tmp_path / f"{index}-before")
        ranges = gspm.section_ranges(payload)
        screens = ranges[6][0]
        after_index = screens + 3 + 3 * int.from_bytes(payload[screens:screens + 2], "little")
        for spot, at in enumerate((0x61, after_index, ranges[19][0] + 2, len(payload) - 6)):
            moved = relocate.insert(payload, at, bytes(range(37)))
            gspm.validate(moved)
            assert _readable(moved, tmp_path / f"{index}-{spot}") == before, (path, hex(at))


def test_an_arch9_switch_table_counts_its_cases_in_a_byte():
    from afterglow.backends.harmony_555 import gspm, relocate

    # 02, one case: value 0 -> the block at 0x20 (an empty drawing program); no ranges
    payload = bytearray(0x40)
    payload[0x10:0x18] = bytes([2, 1, 0, 0]) + (gspm.BASE + 0x20).to_bytes(3, "little") + b"\x00"
    census = relocate.Census.__new__(relocate.Census)
    census.payload, census.fields, census.walked_programs = bytes(payload), {}, set()
    census._switch_table(0x10)
    assert census.fields == {0x14: 0x20}


# -- building: the platform

def _built(project=None):
    from afterglow.backends.harmony_555 import generate
    return generate.build(project or {}, stamp_fields=(48, 27, 21, 27, 9, 2020))


def test_an_empty_project_builds_the_platform_and_reads_back():
    from afterglow.backends.harmony_555 import gspm, relocate, render

    image = _built()
    gspm.validate(image)
    relocate.pointers(image)                        # every pointer lands in the image
    read = importing.Image(image)
    assert not read.unreadable
    assert len(read.screens) == 52
    fonts = render.Fonts(image)
    for ordinal, screen in enumerate(read.screens):
        for page in range(len(screen["slots"])):
            render.screen(image, ordinal, page, fonts)
    texts = [item["text"] for screen in read.screens for slot in screen["slots"]
             for item in read.page_text(slot["program_offset"])]
    assert "Stopping Activity" in texts and "Devices" in texts
    assert read.text.unknown == 0


def test_the_platform_is_logitechs_empty_555_wired_and_worded_alike():
    """The scaffold's model, built with no household, is the configuration it was read from:
    every variable, context, object, switch table, name and key list, and every line of
    text."""
    from afterglow.backends.harmony_555 import ui_index as ui

    from pathlib import Path

    donors = [Path(path) for path in donors_of("harmony-555")
              if Path(path).name.startswith("09-")]
    if not donors:
        pytest.skip("Logitech's empty 555 is not in configs/5xx")
    donor = importing.Image(ezhex.read(donors[0].read_bytes()).payload)
    built = importing.Image(_built())

    def wiring(image):
        return ([(r["initial"], r["limit"], [(t["from"], t["to"], t["operand"], t["category"])
                                             for t in r["transitions"]]) for r in image.engine],
                [[(r["key_code"], r["operand"], r["category"]) for r in c["rows"]]
                 for c in image.contexts],
                [item["atoms"] for item in image.objects],
                [[(value, ui.drawing_program(image.payload, block)["instructions"])
                  for value, block in group["cases"]] for group in image.groups],
                image.names)

    def screens(image):
        return str([([(e["key_code"], e["operand"], e["category"]) for e in s["header_entries"]],
                     [([(e["key_code"], e["operand"], e["category"]) for e in slot["entries"]],
                       [(t["attribute"], t["y"], t["text"])
                        for t in image.page_text(slot["program_offset"])])
                      for slot in s["slots"]]) for s in image.screens])

    def offsetless(value):
        return re.sub(r"'offset': \d+, ", "", str(value))

    assert offsetless(wiring(built)) == offsetless(wiring(donor))
    # the menu's title, which Logitech cut to fit its own font, is kept whole
    assert screens(built) == screens(donor).replace("Choose an activi..", "Choose an activity")


# -- building: devices

def _nec(address: int, command: int) -> list[int]:
    pulses = [9000, -4500]
    for byte in (address, address ^ 0xFF, command, command ^ 0xFF):
        for bit in range(8):
            pulses += [560, -1690 if byte >> bit & 1 else -560]
    return pulses + [560, -40000]


def _device(label: str, address: int, names: list[str], keyed: dict | None = None) -> dict:
    keyed = keyed or {}
    return {
        "schema": "afterglow-project-device/1", "id": f"test-{address}", "label": label,
        "type": "Television",
        "commands": [[name, name, "", "", keyed.get(name)] for name in names],
        "signals": {name: {"schema": "afterglow-ir-signal/1", "kind": "waveform",
                           "name": name, "carrier_hz": 38000,
                           "pulses_us": _nec(address, index)}
                    for index, name in enumerate(names)},
    }


def _project(devices):
    return {"devices": devices, "activities": [], "settings": {"remote": "harmony-555"}}


def _imported(image: bytes, tmp_path) -> dict:
    from afterglow import payloads

    source = tmp_path / "built"
    payloads.get("blob").unpack(image, str(source))
    return backend.import_project(str(source), remotes.get("harmony-555"), {}).project


def test_a_device_builds_its_commands_keys_and_pages_and_reads_back(tmp_path):
    from afterglow.backends.harmony_555 import render

    names = ["PowerToggle", "VolumeUp", "VolumeDown", "InputHdmi1", "InputHdmi2",
             "SleepTimer", "PictureMode"]
    keyed = {"VolumeUp": ["VolumeUp"], "VolumeDown": ["VolumeDown"]}
    project = _project([_device("Television", 0x20, names, keyed),
                        _device("Receiver", 0x40, ["PowerOn", "PowerOff"])])
    image = _built(project)
    read = importing.Image(image)
    assert not read.unreadable and read.text.unknown == 0
    back = _imported(image, tmp_path)
    assert [device["label"] for device in back["devices"]] == ["Television", "Receiver"]
    for made, source in zip(back["devices"], project["devices"]):
        assert set(made["signals"]) == set(source["signals"])
        for name, signal in source["signals"].items():
            assert made["signals"][name]["pulses_us"] == signal["pulses_us"]
            # the carrier is stored as a period in nanoseconds: it reads back to the hertz
            assert abs(made["signals"][name]["carrier_hz"] - signal["carrier_hz"]) <= 1
        assert {row[0]: row[4] for row in made["commands"] if row[4]} == {
            name: keys_ for name, keys_ in (source["commands"][i][0::4]
                                            for i in range(len(source["commands"])))
            if keys_}
    # the Devices screen lists both; a device's pages show its unkeyed commands, four a page
    devices_page = next(s for s in read.screens if any(
        t["text"] == "Devices" for t in read.page_text(s["slots"][0]["program_offset"])))
    drawn = [t["text"] for t in read.page_text(devices_page["slots"][0]["program_offset"])]
    assert "Television" in drawn and "Receiver" in drawn
    at = next(i for i, s in enumerate(read.screens) if s["slots"] and [
        t["text"] for t in read.page_text(s["slots"][0]["program_offset"])][:1] == ["Television"])
    assert len(read.screens[at]["slots"]) == 2
    for page in range(2):
        render.screen(image, at, page)


def test_infrared_is_spelled_from_mark_led_symbols_a_device_shares():
    from afterglow.backends.harmony_555 import infrared, ir_lowering

    signal = {"schema": "afterglow-ir-signal/1", "kind": "waveform", "name": "x",
              "carrier_hz": 38000, "pulses_us": _nec(0x20, 0x10)}
    waveform = ir_lowering.lower(signal).press_waveform
    parts = infrared.chunks(infrared.words_of(waveform))
    assert not parts[0][0] & infrared.MARK               # the lead-in, a chunk of its own
    assert all(part[0] & infrared.MARK for part in parts[1:])
    assert sum(parts, ()) == tuple(infrared.words_of(waveform))
    dictionary = infrared.Dictionary()
    table, first = dictionary.spell(waveform)
    again = dictionary.spell(ir_lowering.lower(dict(signal, pulses_us=_nec(0x20, 0x11)))
                             .press_waveform)
    # a second code of the same device adds no symbol a bit pattern already has
    assert again[0] == table and len(dictionary.tables[0]) == len(set(parts))


def test_a_symbol_table_past_255_is_read_whatever_its_count_byte_says():
    """Logitech's compiler wrote an Xbox 360's factory demo table of 287 symbols with the
    count byte 31; its commands name symbols up to 255, which the remote plays."""
    from afterglow.backends.harmony_555 import command_index, gspm, infrared

    symbols = [infrared.symbol((0x8000 | 500 + index, 300)) for index in range(287)]
    at, offset = [], 0
    for blob in symbols:
        at.append(offset)
        offset += len(blob)
    table_at = offset
    table = bytes([287 & 0xFF]) + b"".join(
        (gspm.BASE + address).to_bytes(3, "little") for address in at)
    body_at = table_at + len(table)
    payload = b"".join(symbols) + table + infrared.body(gspm.BASE + table_at, [3, 200])
    words = command_index._expand(payload + b"\0" * 8, body_at)
    assert struct.unpack("<5H", words) == (0x8000 | 503, 300, 0x8000 | 700, 300, 0)


# -- building: activities

def _household():
    television = _device("Television", 0x20,
                         ["PowerOn", "PowerOff", "InputHdmi1", "InputHdmi2", "VolumeUp",
                          "VolumeDown", "ChannelUp"],
                         {"VolumeUp": ["VolumeUp"], "VolumeDown": ["VolumeDown"],
                          "ChannelUp": ["ChannelUp"]})
    television.update(power_on_cmd="PowerOn", power_off_cmd="PowerOff", power_delay=2500,
                      inputs=[["InputHdmi1", "InputHdmi1"], ["InputHdmi2", "InputHdmi2"]])
    player = _device("Player", 0x40, ["PowerToggle", "Play", "Stop", "Menu"],
                     {"Play": ["Play"], "Stop": ["Stop"], "Menu": ["Menu"]})
    player.update(power_cmd="PowerToggle", power_delay=1000)
    activities = [
        {"id": "1", "label": "Watch TV", "power_on_devices": [television["id"]],
         "enter": [["input", television["id"], "InputHdmi1"]],
         "control": television["id"], "volume": television["id"],
         "display": television["id"]},
        {"id": "2", "label": "Watch a Film",
         "power_on_devices": [television["id"], player["id"]],
         "enter": [["input", television["id"], "InputHdmi2"],
                   ["command", player["id"], "Play"]],
         "leave": [["command", player["id"], "Stop"]],
         "control": player["id"], "volume": television["id"],
         "display": television["id"],
         "soft_buttons": [["Menu", player["id"], "Menu"]]},
    ]
    return {"devices": [television, player], "activities": activities,
            "settings": {"remote": "harmony-555"}}


def test_activities_build_and_read_back_as_the_project_has_them(tmp_path):
    project = _household()
    image = _built(project)
    read = importing.Image(image)
    assert not read.unreadable and read.text.unknown == 0
    back = _imported(image, tmp_path)
    ids = {made["id"]: source["id"] for made, source in zip(back["devices"],
                                                            project["devices"])}

    def same(value):
        if isinstance(value, list):
            return [same(item) for item in value]
        if isinstance(value, dict):
            return {key: same(item) for key, item in value.items()}
        return ids.get(value, value)

    assert [a["label"] for a in back["activities"]] == ["Watch TV", "Watch a Film"]
    for made, source in zip(back["activities"], project["activities"]):
        made = same(made)
        assert sorted(made["power_on_devices"]) == sorted(source["power_on_devices"])
        assert made["enter"] == source["enter"]
        assert made.get("leave", []) == source.get("leave", [])
        for role in ("control", "volume", "display"):
            assert made[role] == source[role]
    film = same(back["activities"][1])
    assert [button[:3] for button in film["soft_buttons"]] == [["Menu", "test-64", "Menu"]]
    television, player = back["devices"]
    assert (television["power_on_cmd"], television["power_off_cmd"]) == ("PowerOn", "PowerOff")
    assert television["power_delay"] == 2500
    assert [name for name, _command in television["inputs"]] == ["InputHdmi1", "InputHdmi2"]
    assert player["power_cmd"] == "PowerToggle"


def test_an_activity_starts_as_logitechs_do():
    """Its key set answers the start, the re-pick and the leave; the start shows Starting,
    switches power, sets inputs and the activity state, then passes the battery check on
    its way to the activity's screen."""
    from afterglow.backends.harmony_555 import generate

    image = generate.Image(_household(), generate.Path(generate.__file__).parents[2]
                           / "scaffolds" / "harmony-555", (0, 0, 12, 16, 10, 2026))
    image.build()
    state = image._named("CurrentActivityState")
    assert image.variables[state]["initial"] == image.variables[state]["limit"] == 2
    film = image.contexts[-1]
    rows = {row["key_code"]: row for row in film["rows"]}
    assert {generate.START, generate.AGAIN, generate.LEAVE} <= set(rows)
    start = image.objects[rows[generate.START]["operand"]]
    assert start[0][1] == generate.SCREEN
    assert (1, generate.WRITE | state) in start
    texts = [line["text"] for line in image.screens[start[0][0]]["pages"][0]["lines"]]
    assert texts[:2] == ["Starting", "Watch a Film"]
    assert not image.skipped


def test_a_build_is_refused_while_the_profile_is_read_only_and_wrapped_once_it_is_not(
        tmp_path):
    import dataclasses

    from afterglow import backends, build_service

    profile = remotes.get("harmony-555")
    context = backends.BuildContext(root=tmp_path, log=lambda _m: None,
                                    find_scaffold=build_service.find_scaffold,
                                    find_theme=lambda *_a: None)
    project = dict(_household(), settings={"remote": "harmony-555",
                                           "out_file": str(tmp_path / "home.EZHex")})
    if profile.status == "read-only":
        with pytest.raises(Exception):
            backend.build_project(project, profile, context)
    trying = dataclasses.replace(profile, status="experimental")
    result = backend.build_project(project, trying, context)
    raw = result.artifact.read_bytes()
    container = ezhex.read(raw)
    assert importing.Image(container.payload).screens
    header, *_rest = ezhex._split(raw)
    assert remotes.identify(header).id == "harmony-555"
    # a model with no platform of its own, read or derived, is refused, not given the 555's
    bare = tmp_path / "bare"
    bare.mkdir()
    nowhere = dataclasses.replace(context, find_scaffold=lambda *_a: str(bare))
    with pytest.raises(ValueError, match="platform"):
        backend.build_project(project, trying, nowhere)


def test_a_zero_reads_back_as_a_zero_and_a_split_label_as_its_name(tmp_path):
    """Galmuri draws 0 as O, so a build slashes its zero; and a label too long for one
    line is split only where an import joins it back into the same name."""
    names = ["GP0 and GP1 OFF", "ChannelSelect", "Picture Mode 2", "InputHdmi1"]
    project = _project([_device("Switcher", 0x30, names)])
    back = _imported(_built(project), tmp_path)
    assert set(back["devices"][0]["signals"]) == set(names)


def _empty_image():
    from afterglow import paths
    from afterglow.backends.harmony_555 import generate
    return generate.Image({"settings": {"remote": "harmony-555"}},
                          paths.scaffolds("harmony-555"), (48, 27, 21, 27, 9, 2020))


def test_a_word_breaks_after_its_hyphen_as_logitechs_help_and_labels_break_it():
    """Logitech's Help fills a line up to a word's hyphen ("Now is the BD-" over
    "Panasonic off?") and its labels break there too ("AUX-" over "Eingang"), the first
    line as long as fits ("Watch a" over "DVD"); an import joins them back with no
    space, where a hyphen standing alone keeps its own ("Watch DVD -")."""
    image = _empty_image()
    assert image.wrap("Now is the BD-Panasonic off?") == ["Now is the BD-", "Panasonic off?"]
    assert image.wrap("Now is the Klimasteuerung off?") == [
        "Now is the", "Klimasteuerung off?"]
    assert image.corner_lines("AUX-Eingang") == ["AUX-", "Eingang"]
    assert image.corner_lines("BD-Panasonic", words=True) == ["BD-", "Panasonic"]
    assert image.corner_lines("Watch a DVD", words=True) == ["Watch a", "DVD"]
    assert importing.join_lines(["AUX-", "Eingang"]) == "AUX-Eingang"
    assert importing.join_lines(["BD-", "Panasonic"], words=True) == "BD-Panasonic"
    assert importing.join_lines(["Watch DVD -", "XBOX"], words=True) == "Watch DVD - XBOX"
    assert importing.join_text(["Now is the BD-", "Panasonic off?"]) == \
        "Now is the BD-Panasonic off?"


def test_a_soft_hyphen_breaks_a_translations_long_word_and_a_line_break_a_label():
    """A soft hyphen is drawn as "-" only where the word breaks there; a "\\n" in a
    label starts its second line."""
    image = _empty_image()
    lines = image.wrap("Ist die Home\u00adEntertainment\u00adAnlage an?")
    assert lines == ["Ist die Home-", "EntertainmentAnlage", "an?"]
    assert image.wrap("Kurz\u00adwort") == ["Kurzwort"]
    assert image.corner_lines("Wohn\u00adzimmerlicht") == ["Wohn-", "zimmerlicht"]
    assert image.corner_lines("Licht\naus") == ["Licht", "aus"]


def test_a_device_with_a_hyphen_reads_back_from_helps_question(tmp_path):
    project = _household()
    project["devices"][0]["label"] = "Yamaha RX-A3010 Receiver"
    back = _imported(_built(project), tmp_path)
    assert back["devices"][0]["label"] == "Yamaha RX-A3010 Receiver"


def test_help_in_an_activity_asks_about_each_device_it_switches_on_and_each_input():
    from afterglow.backends.harmony_555 import generate

    image = generate.Image(_household(), generate.Path(generate.__file__).parents[2]
                           / "scaffolds" / "harmony-555", (0, 0, 12, 16, 10, 2026))
    image.build()
    film = image.contexts[-1]
    rows = {row["key_code"]: row for row in film["rows"]}
    help_row = rows[keys.code(keys.HELP)]
    assert help_row["category"] == generate.SCREEN

    def text(ordinal):
        return " ".join(line["text"] for line in image.screens[ordinal]["pages"][0]["lines"]
                        if line["attribute"] != generate.SOFTKEY)

    def answer(ordinal, code):
        return next(key for key in image.screens[ordinal]["pages"][0]["keys"]
                    if key[0] == code)
    entry = help_row["operand"]
    assert text(entry) == "Did that fix the problem?"
    shown = dict((code, operand) for code, operand, _category in image.screens[entry]["keys"])
    assert generate.SHOWN in shown                   # it sends everything again as it appears
    home = answer(entry, generate.YES_KEY)[1]          # Yes: back to the activity's screen
    asked, at = [], answer(entry, generate.NO_KEY)[1]   # No: the first question
    while at != home:
        asked.append(text(at))
        at = answer(at, generate.YES_KEY)[1]           # yes, it is: the next question
    assert asked == ["Is the Television on?", "Is the Player on?",
                     "Is the Television set to the InputHdmi2 input?"]


def test_sound_and_picture_are_an_activitys_own_screens_rebinding_its_layouts_keys():
    from afterglow.backends.harmony_555 import generate

    image = generate.Image(_household(), generate.Path(generate.__file__).parents[2]
                           / "scaffolds" / "harmony-555", (0, 0, 12, 16, 10, 2026))
    image.build()
    home = image.activity_screens[1]
    sound, picture = keys.code(37), keys.code(36)

    def goes(screen, code):
        row = next(row for row in image.screens[screen]["keys"] if row[0] == code)
        assert row[2] == generate.SCREEN
        return row[1]

    heard = goes(home, sound)
    assert image.screens[heard]["pages"][0]["lines"][0]["text"] == "Watch a Film (Sound)"
    # the television plays the sound: its volume, and nothing of the player's
    bound = {row[0] for row in image.screens[heard]["keys"]} - {sound, picture}
    assert bound == {keys.code(50), keys.code(51)}          # Volume down and up
    assert goes(heard, sound) == home
    seen = goes(home, picture)
    assert goes(heard, picture) == seen and goes(seen, sound) == heard


def test_sound_and_picture_on_a_devices_own_screen_open_its_layouts_and_come_back():
    from afterglow.backends.harmony_555 import generate

    image = generate.Image(_household(), generate.Path(generate.__file__).parents[2]
                           / "scaffolds" / "harmony-555", (0, 0, 12, 16, 10, 2026))
    image.build()
    sound, picture = keys.code(37), keys.code(36)

    def goes(screen, code):
        row = next(row for row in image.screens[screen]["keys"] if row[0] == code)
        assert row[2] == generate.SCREEN
        return row[1]

    def title(screen):
        return image.screens[screen]["pages"][0]["lines"][0]["text"]

    for device in image.devices:
        home = device["screen"]
        heard, seen = goes(home, sound), goes(home, picture)
        assert title(heard) == f"{device['label']} (Sound)"
        assert title(seen) == f"{device['label']} (Picture)"
        assert goes(heard, sound) == home and goes(seen, picture) == home
        assert goes(heard, picture) == seen and goes(seen, sound) == heard
        assert sum(1 for row in image.screens[home]["keys"] if row[0] == sound) == 1


def test_a_devices_own_sound_and_picture_show_only_its_settings_as_logitechs_do():
    """Logitech's show a device's sound or picture settings, most often none - not the
    device's every command again."""
    from afterglow.backends.harmony_555 import generate

    project = _household()
    tv = project["devices"][0]
    tv["commands"] += [["Surround", "Surround", "", "", None],
                       ["Aspect", "Aspect", "", "", None]]
    tv["signals"].update(Surround=tv["signals"]["InputHdmi1"],
                         Aspect=tv["signals"]["InputHdmi2"])
    image = generate.Image(project, generate.Path(generate.__file__).parents[2]
                           / "scaffolds" / "harmony-555", (0, 0, 12, 16, 10, 2026))
    image.build()
    sound, picture = keys.code(37), keys.code(36)

    def shown(device, code):
        screen = next(row[1] for row in image.screens[device["screen"]]["keys"]
                      if row[0] == code)
        return [[line["text"] for line in page["lines"][1:]]
                for page in image.screens[screen]["pages"]]
    television, player = image.devices
    assert shown(television, sound) == [["Surround"]]
    assert shown(television, picture) == [["Aspect"]]
    assert shown(player, sound) == [[]] and shown(player, picture) == [[]]


def test_the_line_between_a_pages_rows_is_drawn_only_under_a_bottom_row():
    """Logitech draws a page of one or two buttons on the plain backdrop."""
    from afterglow.backends.harmony_555 import generate

    image = generate.Image(_household(), generate.Path(generate.__file__).parents[2]
                           / "scaffolds" / "harmony-555", (0, 0, 12, 16, 10, 2026))
    image.build()
    backdrop = {count: image.page("T", ["x"] * count, 0, 1)["backdrop"]
                for count in range(5)}
    assert backdrop == {0: generate.PLAIN, 1: generate.PLAIN, 2: generate.PLAIN,
                        3: "page", 4: "page"}
    assert image.page("T", ["x", None, None, "y"], 0, 1)["backdrop"] == "page"


def _film_context(read, play: int):
    """The context whose start sends the Player's Play."""
    for context in read.contexts:
        rows = {row["key_code"]: row for row in context["rows"]}
        if 0x01 in rows and any(step[0] == importing.SEND and step[1] == play
                                for step in read.row(rows[0x01])):
            return rows
    raise AssertionError("no activity starts the film")


def test_an_activity_chosen_again_runs_its_steps_in_order_all_but_a_last_play(tmp_path):
    project = _household()
    tv, player = (device["id"] for device in project["devices"])
    film = project["activities"][1]
    film["enter"] = [["command", player, "Menu"], ["input", tv, "InputHdmi2"],
                     ["command", player, "Play"]]
    from afterglow.backends.harmony_555 import generate

    made = generate.Image(project, generate.Path(generate.__file__).parents[2]
                          / "scaffolds" / "harmony-555", (48, 27, 21, 27, 9, 2020))
    image = made.build()
    command = {c["name"]: c["command_id"] for c in made.devices[1]["commands"]}
    back = _imported(image, tmp_path)
    ids = {made["id"]: source["id"] for made, source in zip(back["devices"],
                                                            project["devices"])}
    # the steps read back in their order, an input between two commands
    assert [[step[0], ids[step[1]], step[2]] for step in back["activities"][1]["enter"]] \
        == film["enter"]
    read = importing.Image(image)
    rows = _film_context(read, command["Play"])
    again = [step for step in read.row(rows[0x05])
             if step[0] in (importing.SEND, importing.WRITE)]
    # Menu, then the input, and not Play
    assert [step[1] for step in again if step[0] == importing.SEND] == [command["Menu"]]
    assert [step[0] for step in again][-1] == importing.WRITE


def test_screen_buttons_keep_their_corners_and_an_empty_page(tmp_path):
    project = _household()
    player = project["devices"][1]["id"]
    buttons = [None, ["Menu", player, "Menu"], None, None, None, None, None, None,
               ["Stop", player, "Stop"]]
    project["activities"][1]["soft_buttons"] = buttons
    back = _imported(_built(project), tmp_path)
    made = back["activities"][1]["soft_buttons"]
    assert [entry and entry[0] for entry in made] == [entry and entry[0]
                                                      for entry in buttons]


def test_a_code_with_no_hold_keeps_the_count_logitech_sent_it_with(tmp_path):
    project = _project([_device("Television", 0x20, ["PowerOn", "Red"])])
    project["devices"][0]["signals"]["Red"]["native"] = {"harmony-555": {"sends": 3}}
    image = _built(project)
    read = importing.Image(image)
    counts = {atoms[0][0]: atoms[1][0] & 0xFF for atoms in
              (obj["atoms"] for obj in read.objects)
              if len(atoms) == 2 and atoms[0][1] == 0x7D and atoms[1][1] == 0x7C}
    assert counts == {0x0000: 1, 0x0001: 3}
    back = _imported(image, tmp_path)
    assert back["devices"][0]["signals"]["Red"]["native"]["harmony-555"]["sends"] == 3


def test_once_everything_is_off_the_activities_menu_shows():
    read = importing.Image(_built(_household()))

    def titles(screens):
        return [read.page_text(read.screens[s]["slots"][0]["program_offset"])[0]["text"]
                for s in screens if read.screens[s]["slots"]]
    for context in read.contexts:
        rows = {row["key_code"]: row for row in context["rows"]}
        if 0x01 not in rows:
            continue
        steps = read.row(rows[0x01])
        shown = titles([step[1] for step in steps if step[0] == importing.MODE])
        if shown == ["Stopping Activity"]:
            for key in (0x01, 0x05):
                opened = [title for step in read.row(rows[key]) if step[0] == importing.SWITCH
                          for screens in read.switch_targets(step[1] >> 8).values()
                          for title in titles(screens)]
                assert "Choose an activity" in opened
            return
    raise AssertionError("no idle context")


@pytest.mark.parametrize("remote", ["harmony-555", "harmony-550", "harmony-515"])
def test_off_and_start_up_end_in_the_menu_never_in_the_welcome_tour(remote):
    # the empty platform goes on from Off's battery check into "Welcome to your remote.";
    # Logitech's households end there in the menu, and so must a build: a 550 showed
    # the welcome screen after every Off
    from afterglow import paths
    from afterglow.backends.harmony_555 import generate, graft

    project = dict(_household(), settings={"remote": remote})
    image = generate.Image(project, generate.Path(paths.scaffolds(remote)),
                           (0, 0, 12, 16, 10, 2026))
    roles = image._roles()
    menu = roles["menu_table"] << 8 | roles["location"]
    payload = image.build()
    view, read = graft.image_view(payload), importing.Image(payload)

    def reached(starts):
        screens, switches, seen, todo = set(), set(), set(), list(starts)
        while todo:
            operand, category = todo.pop()
            if category == generate.SCREEN:
                screens.add(operand)
            elif category == generate.SWITCH:
                switches.add(operand)
            elif category == generate.OBJECT and operand not in seen:
                seen.add(operand)
                todo += view.objects[operand]
        titles = {read.page_text(read.screens[s]["slots"][0]["program_offset"])[0]["text"]
                  for s in screens if read.screens[s]["slots"]}
        return titles, switches
    rows = {key: (operand, category) for key, operand, category in view.contexts[view.idle]}
    for starts in ([rows[0x01]], [rows[0x05]], view.lead):
        titles, switches = reached(starts)
        assert not any(title.startswith("Welcome") for title in titles), (remote, titles)
        assert menu in switches


def _questions(read):
    """Every Yes/No screen's question, joined, with what its No sends and where Help goes."""
    out = []
    for screen in read.screens:
        for slot in screen["slots"][:1]:
            text = importing.join_text([item["text"]
                                        for item in read.page_text(slot["program_offset"])
                                        if item["text"] not in ("Yes", "No")])
            no = next((e for e in slot["entries"] if e["key_code"] == 0x9E), None)
            if no is not None:
                shown = next((e for e in screen["header_entries"] if e["key_code"] == 0x06),
                             None)
                out.append((text, [s[1] for s in read.row(no) if s[0] == importing.SEND],
                            [s[1] for s in read.row(shown) if s[0] == importing.SEND]
                            if shown else None))
    return out


def test_help_never_sends_a_power_toggle_as_it_appears_and_asks_after_off():
    from afterglow.backends.harmony_555 import generate

    made = generate.Image(_household(), generate.Path(generate.__file__).parents[2]
                          / "scaffolds" / "harmony-555", (48, 27, 21, 27, 9, 2020))
    read = importing.Image(made.build())
    tv, player = ({c["name"]: c["command_id"] for c in device["commands"]}
                  for device in made.devices)
    asked = _questions(read)
    shown = [sent for text, _no, sent in asked if sent is not None]
    # the Player's power is a toggle: sending it again would switch it off
    assert all(player["PowerToggle"] not in sent for sent in shown)
    assert any(tv["PowerOn"] in sent for sent in shown)
    # once everything is off: is each device off, and No sends its off code
    off = {text: no for text, no, _sent in asked if text.endswith(" off?")}
    assert off["Is the Television off?"] == [tv["PowerOff"]]
    assert off["Is the Player off?"] == [player["PowerToggle"]]
    entry = next(sent for text, _no, sent in asked
                 if sent is not None and tv["PowerOff"] in sent)
    assert player["PowerToggle"] not in entry


def test_help_asks_after_a_state_an_input_sets_and_names_survive_the_round_trip(
        tmp_path):
    project = _household()
    tv = project["devices"][0]
    tv["inputs"] = [["HDMI 1", "InputHdmi1"], ["Living room", [{"set": "Screen", "to": "Wide"}]]]
    tv["control_states"] = [{"id": "Screen", "values": ["Normal", "Wide"],
                             "select": {"Normal": {"steps": ["InputHdmi1"]},
                                        "Wide": {"steps": ["InputHdmi2"]}}}]
    project["activities"][0]["enter"] = [["input", tv["id"], "HDMI 1"]]
    project["activities"][1]["enter"] = [["input", tv["id"], "Living room"]]
    image = _built(project)
    texts = [text for text, _no, _sent in _questions(importing.Image(image))]
    assert "Is the Television set to the HDMI 1 input?" in texts
    assert "Is the Television Screen set to Wide?" in texts
    back = _imported(image, tmp_path)
    assert [entry[0] for entry in back["devices"][0]["inputs"]][:1] == ["HDMI 1"]
    assert "Wide" in back["devices"][0]["control_states"][0]["values"]


def test_a_build_too_large_leaves_out_afterglows_extras_and_says_so(monkeypatch):
    from afterglow.backends.harmony_555 import generate, gspm

    directory = generate.Path(generate.__file__).parents[2] / "scaffolds" / "harmony-555"
    stamp = (48, 27, 21, 27, 9, 2020)
    whole = len(generate.build_fitting(_household(), directory, stamp)[1])
    lean = generate.Image(_household(), directory, stamp)
    lean.left_out = set(generate.LEAN[-1])
    leanest = len(lean.build())
    assert leanest < whole
    monkeypatch.setattr(gspm, "MAX_SAFE_SIZE", leanest + 1)
    image, payload = generate.build_fitting(_household(), directory, stamp)
    assert len(payload) == leanest
    assert [note for note in image.skipped if "fits the remote" in note]
    monkeypatch.setattr(gspm, "MAX_SAFE_SIZE", leanest)
    with pytest.raises(generate.TooLarge):
        generate.build_fitting(_household(), directory, stamp)


@pytest.mark.parametrize("path", [path for remote in ("harmony-555", "harmony-550")
                                  for path in donors_of(remote)])
def test_a_households_sound_and_picture_layouts_import_as_logitech_drew_them(path, tmp_path):
    from afterglow import activity_layouts, payloads

    raw = open(path, "rb").read()
    profile = remotes.identify(ezhex._split(raw)[0])
    payload = ezhex.read(raw).payload
    source = tmp_path / "source"
    payloads.get("blob").unpack(payload, str(source))
    project = backend.import_project(str(source), profile, {}).project
    # each layout screen whose title is whole, by title: the keys it binds are the keys
    # the imported project's layouts rebind, no more and no fewer
    image = importing.Image(payload, keys.Keypad.of(profile))
    drawn = {}
    for screen in image.screens:
        if screen["slots"]:
            items = image.page_text(screen["slots"][0]["program_offset"])
            title = next((item["text"] for item in items if importing._is_title(item)), "")
            drawn.setdefault(title, screen)
    checked = 0
    for activity in project["activities"]:
        resolved = activity_layouts.resolve(activity, project["devices"])
        for kind in activity_layouts.KINDS:
            screen = drawn.get(f"{activity['label']} ({activity_layouts.TITLES[kind]})")
            if screen is None:
                continue
            bound = {image.keypad.name_of(entry["key_code"])
                     for entry in screen["header_entries"]} - {None}
            assert set(resolved[kind]["hard_macros"]) == bound, (activity["label"], kind)
            checked += 1
        if "picture" in resolved:
            assert activity["display"] == resolved["picture"]["device"]
    if not checked:
        pytest.skip("no whole layout title to check by")


def test_a_model_without_layout_keys_builds_none():
    from afterglow.backends.harmony_555 import generate

    project = dict(_household(), settings={"remote": "harmony-525"})
    image = generate.Image(project, generate.Path(generate.__file__).parents[2]
                           / "scaffolds" / "harmony-555", (0, 0, 12, 16, 10, 2026))
    image.build()
    assert not any(any(title.endswith(("(Sound)", "(Picture)"))
                       for title in [page["lines"][0]["text"] for page in screen["pages"]])
                   for screen in image.screens if screen["pages"][0]["lines"])


@pytest.mark.parametrize("remote, absent, added", [
    ("harmony-525", {58, 61}, set()), ("harmony-520", {27, 33, 34, 35, 58, 61}, set()),
    ("harmony-550", set(), set()), ("harmony-xbox360", set(), {59, 60}),
    ("harmony-515", {58, 61}, set())])
def test_a_derived_model_builds_on_the_555s_platform_with_its_own_skin_and_keys(
        remote, absent, added):
    from afterglow import paths
    from afterglow.backends.harmony_555 import generate, gspm, relocate

    project = dict(_household(), settings={"remote": remote})
    image = generate.Image(project, generate.Path(paths.scaffolds(remote)),
                           (0, 0, 12, 16, 10, 2026))
    payload = image.build()
    gspm.validate(payload)
    relocate.pointers(payload)
    assert payload[gspm.section_ranges(payload)[1][0] + 2] in remotes.get(remote).skins
    read = importing.Image(payload)
    assert not read.unreadable
    idle = {row["key_code"] & 0x7F for row in read.contexts[2]["rows"]
            if row["key_code"] & 0x80}
    platform = {row[1] & 0x7F for row in generate.load_json(
        generate.Path(paths.scaffolds("harmony-555")), generate.WIRING_FILE,
        generate.WIRING_SCHEMA)["contexts"][2]["rows"] if row[1] & 0x80}
    assert idle == (platform - absent) | added
    # a device's screen binds every key the model has, its new ones too
    television = image.screens[image.devices[0]["screen"]]
    assert {code & 0x7F for code, _operand, _category in television["keys"]} == (
        idle - {keys.PAGE_FORWARD, keys.PAGE_BACK, *keys.FLOW.values(),
                *keys.FIRMWARE_ONLY})


def test_a_remote_sold_under_another_skin_keeps_its_own_and_no_other(tmp_path):
    from afterglow.backends.harmony_555 import generate, gspm

    def skin_of(payload):
        return payload[gspm.section_ranges(payload)[1][0] + generate.SKIN_AT]
    # a 552 is a 555 under skin 51: its project says so, and its build writes it
    project = dict(_household(), settings={"remote": "harmony-555", "skin": 51})
    image = _built(project)
    assert skin_of(image) == 51
    assert _imported(image, tmp_path)["settings"]["skin"] == 51
    # a skin the remote is not sold under is never written: a project moved elsewhere
    assert skin_of(_built(dict(project, settings={"remote": "harmony-555",
                                                  "skin": 22}))) == 48
    assert skin_of(_built(_household())) == 48


def test_the_515s_platform_is_the_555s_with_its_own_key_handling_grafted():
    from afterglow import paths
    from afterglow.backends.harmony_555 import generate, graft

    empty = graft.image_view(generate.build({"settings": {"remote": "harmony-515"}},
                                            directory=paths.scaffolds("harmony-515")))
    # every key of the global key set has an object of its own, as the 515's and 510's
    presses = [row for row in empty.contexts[2] if row[0] & 0x80]
    assert len({operand for _key, operand, _category in presses}) == len(presses)
    # and the sleep timer is its own: twenty seconds, where the 555's is two hours
    roles = {graft.timer_role(empty, timer): timer[1] for timer in empty.timers}
    assert roles["sleep"] == 20


def test_a_515_or_510_household_differs_from_the_derived_platform_only_where_a_household_does():
    from afterglow import paths
    from afterglow.backends.harmony_555 import generate, graft

    minis = [path for path in _configs() if (lambda p: p[gspm_skin(p)])(
        ezhex.read(path.read_bytes()).payload) in (67, 68)]
    if not minis:
        pytest.skip("no 515 or 510 configuration in configs/")
    empty = graft.image_view(generate.build({"settings": {"remote": "harmony-515"}},
                                            directory=paths.scaffolds("harmony-515")))
    places = {tuple(place) for place in json.loads(
        (generate.Path(paths.scaffolds("harmony-555")) / graft.HOUSEHOLD_FILE)
        .read_text("utf-8"))["places"]}
    for path in minis:
        household = graft.image_view(ezhex.read(path.read_bytes()).payload)
        assert graft.changed_places(empty, household) <= places, path.name


def gspm_skin(payload: bytes) -> int:
    from afterglow.backends.harmony_555 import generate, gspm
    return gspm.section_ranges(payload)[1][0] + generate.SKIN_AT


def _image(project):
    """An image of ``project`` before it is laid out, its notes and timers to look at."""
    from pathlib import Path

    from afterglow import paths
    from afterglow.backends.harmony_555 import generate

    return generate.Image(project, Path(paths.scaffolds("harmony-555")),
                          (48, 27, 21, 27, 9, 2020))


def test_the_backlight_time_is_the_owners_and_nothing_else_is_a_setting(tmp_path):
    # the backlight's timer (the one that turns the light off) holds the owner's time; a
    # 5xx lights with the Glow key, so there is no wake-when-picked-up to set
    project = _household()
    project["settings"]["backlight_timeout"] = "13"
    settings = _imported(_built(project), tmp_path / "set")["settings"]
    assert settings["backlight_timeout"] == "13"
    assert "tilt" not in settings
    assert _imported(_built(_household()), tmp_path / "plain")["settings"][
        "backlight_timeout"] != "13"


def test_a_backlight_time_out_of_range_keeps_the_remotes_own_and_says_so():
    project = _household()
    project["settings"]["backlight_timeout"] = "500"
    image = _image(project)
    before = list(image.timers)
    image.place_backlight()
    assert image.timers == before
    assert any("backlight timeout '500'" in note for note in image.skipped)


def test_every_5xx_household_reads_its_backlight_from_its_backlight_timer(tmp_path):
    for number, path in enumerate(_configs()):
        settings = _import(path, tmp_path / str(number)).project["settings"]
        if "demo" in path.name:
            continue
        # Logitech's software offered these; the Minis all keep 10
        assert settings.get("backlight_timeout") in ("5", "10", "15", "20"), path.name
        assert "tilt" not in settings, path.name


def test_no_5xx_import_makes_favourites_a_digit_button_stays_a_button(tmp_path):
    # no 5xx has favourite channels: a button that sends digits is one like any other
    for number, path in enumerate(_configs()):
        project = _import(path, tmp_path / str(number)).project
        for activity in project["activities"]:
            assert not activity.get("image_buttons") and not activity.get("channels"), \
                (path.name, activity["label"])


def test_a_projects_favourites_become_buttons_that_dial_their_channels(tmp_path):
    project = _household()
    digits = [str(digit) for digit in range(10)]
    project["devices"][0] = _device("Television", 0x20, [
        *(command[0] for command in project["devices"][0]["commands"]), *digits],
        {"VolumeUp": ["VolumeUp"], "VolumeDown": ["VolumeDown"]})
    project["devices"][0].update(
        power_on_cmd="PowerOn", power_off_cmd="PowerOff",
        inputs=[["InputHdmi1", "InputHdmi1"], ["InputHdmi2", "InputHdmi2"]])
    watch = project["activities"][0]
    watch["soft_buttons"] = [["Up", watch["control"], "ChannelUp"]]
    watch["channels"] = [["News", "12", None], ["Sport", "7", "Logos/sport.png"]]
    image = _image(project)
    back = _imported(image.build(), tmp_path)
    buttons = back["activities"][0]["soft_buttons"]
    assert buttons[0][0] == "Up"
    by_label = {entry["label"] if isinstance(entry, dict) else entry[0]: entry
                for entry in buttons if entry}
    news = by_label["News"]
    sent = [step[2] for step in news["macro"] if step[0] == "command"]
    assert sent == ["1", "2"]
    assert by_label["Sport"][2] == "7"
    assert any("1 favourite(s) shown by name" in note for note in image.skipped)


def test_every_5xx_edits_its_keys_and_screen_and_the_two_with_the_keys_their_layouts():
    """Each 5xx's activity has the Screen buttons and Physical buttons pages - labels
    alone, four to a screen - and the 550's and 555's Sound and Picture layouts too."""
    from afterglow import remotes
    for model in ("550", "555", "525", "515", "520", "xbox360"):
        profile = remotes.get(f"harmony-{model}")
        assert {"screen_buttons", "hard_buttons"} <= set(profile.activity_pages), model
        assert not profile.screen_icons and profile.screen_grid("activity") == (2, 2)
        layout_keys = (profile.vocabulary or {}).get("layout_key_scans")
        assert profile.activity_layouts == bool(layout_keys), model


@pytest.mark.parametrize("remote", ["harmony-520", "harmony-525", "harmony-550",
                                    "harmony-555", "harmony-515", "harmony-xbox360"])
def test_a_household_saved_through_every_editor_page_builds_byte_for_byte_the_same(
        qapp_or_skip, tmp_path, remote):
    """Opening each device and activity of a real configuration and saving it unchanged
    must not change what is built: the pages carry what they do not show."""
    import copy
    from pathlib import Path

    from afterglow import paths
    from afterglow.backends.harmony_555 import generate
    from afterglow.gui.activity_wizard import ActivityEditor
    from afterglow.gui.device_wizard import DeviceEditor

    found = sorted(donors_of(remote))
    if not found:
        pytest.skip(f"no real {remote} configuration available")
    project = _import(Path(found[0]), tmp_path).project

    def built(project):
        return generate.build(project, directory=paths.scaffolds(remote),
                              stamp_fields=(0, 0, 12, 16, 10, 2026))
    saved = copy.deepcopy(project)
    for at, device in enumerate(saved["devices"]):
        saved["devices"][at] = DeviceEditor([], existing=device, project=saved)._collect()
    profile = remotes.for_project(saved)
    for at, activity in enumerate(saved["activities"]):
        saved["activities"][at] = ActivityEditor(
            saved["devices"], existing=activity, remote=profile,
            activities=saved["activities"])._collect()
    assert built(saved) == built(project)
