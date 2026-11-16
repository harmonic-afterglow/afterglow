"""The arch-14 backend - the Harmony 600, 650, 665 and 700: images read as their firmware
lays them out, and the scaffolds a build starts from. The 700 is the 650's body with a
battery: the same backend, its own profile and scaffold (49 firmware screens to the 650's
44, and charging pictures).

Logitech's own configurations are checked when the maintainer has them (configs/650/,
665/, 600/ and 700/), each read and rebuilt as the remote its header names, and skipped
otherwise.

Format reference: docs/harmony_650_700/gspm.md
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from afterglow import ezhex, payloads, paths, remotes
from afterglow.backends.harmony_650 import (
    assets, backend, bitmap, catalogue, command_index, drawing, firmware_screens, gspm, keys,
    importing, labels, platform_text, ui_index)

# builds whole images: deselect with -m "not slow" for a quick run
pytestmark = pytest.mark.slow


ROOT = Path(__file__).resolve().parents[1]
# the 665 is a 650 that says skin 75, and the 600 one that says 71 or 73: their
# configurations are the 650's. A 700's are its own remote's, on the same backend. A link
# is another name for a dump already here (650-favourites).
CONFIGS = sorted(path for folder in ("650", "665", "600", "700")
                 if (ROOT / "configs" / folder).is_dir()
                 for path in (ROOT / "configs" / folder).glob("*.ezhex")
                 if not path.is_symlink())

SCAFFOLD = paths.scaffolds("harmony-650")
# the firmware's own screens come first; a project's start after them
FIRMWARE = len(firmware_screens.load_system(SCAFFOLD)["screens"])


def _remote(path: Path):
    """The profile a configuration's header names: the 650's or the 700's."""
    header, _start, _size, _checksum = ezhex._split(path.read_bytes())
    return remotes.identify(header)


def _image(sections: list[bytes]) -> bytes:
    """A sealed arch-14 image holding ``sections`` in slot order after the header."""
    body = bytearray(b"GSPM" + bytes(4) + struct.pack("<I", gspm.HEADER_CONSTANT))
    body += bytes(4 * len(gspm.SLOT_SECTIONS))
    body += bytes(gspm.BUTTON_MAP_OFFSET - len(body)) + gspm.BUTTON_MAP_MAGIC + b"\x00"
    for slot, data in enumerate(sections):
        struct.pack_into("<I", body, 0x0C + 4 * slot, gspm.BASE + len(body))
        body += data
    return gspm.seal(bytes(body))


def test_the_eighteen_slots_are_read_as_the_ones_sections():
    image = _image([bytes([slot + 1]) for slot in range(len(gspm.SLOT_SECTIONS))])
    ranges = gspm.section_ranges(image)
    assert set(ranges) == set(range(20)) - set(gspm.ABSENT_SECTIONS)
    # slot 8 holds what the One numbers section 9, and the last slot its section 19
    assert image[ranges[9][0]] == 9 and image[ranges[19][0]] == 18


def test_an_image_based_where_the_one_is_based_is_refused():
    image = bytearray(_image([b"\x01"] * len(gspm.SLOT_SECTIONS)))
    struct.pack_into("<I", image, 8, 0x1600)
    with pytest.raises(ValueError, match="header constant"):
        gspm.validate(bytes(image))


def test_a_sized_picture_and_a_wide_switch_round_trip():
    image = bytearray(_image([b"\x00"] * len(gspm.SLOT_SECTIONS)))
    at = len(image)
    program = [
        {"opcode": "sized_bitmap", "x": 0, "y": 112, "reserved": "0000", "width": 128,
         "height": 16, "target": 0x40},
        {"opcode": "switch", "wide": True, "selector": 0x3D,
         "cases": [(0, at), (300, at)], "ranges": []},
        {"opcode": "end"},
    ]
    image += drawing.encode_program(program)
    read = ui_index.drawing_program(bytes(image), at)["instructions"]
    assert [item["opcode"] for item in read] == ["sized_bitmap", "switch", "end"]
    assert read[1]["cases"] == [(0, at), (300, at)]
    assert drawing.encode_program(read) == bytes(image[at:])


@pytest.mark.parametrize("remote, skin", [("harmony-650", 72), ("harmony-700", 66)])
def test_the_profile_names_its_remote_and_builds(remote, skin):
    profile = remotes.get(remote)
    assert (profile.arch, profile.skin) == (14, skin)
    assert profile.backend == "harmony-650"
    assert profile.buildable
    # a Favourites page, of names: Logitech never gave these remotes' favourites logos
    assert "favourites" in profile.interface["activity_pages"]
    assert profile.favourite_logos is False
    assert not profile.capabilities.get("touchscreen")
    assert profile.vocabulary["hard_keys"] == list(keys.COMMAND_KEYS)


def test_no_key_is_both_a_command_key_and_one_the_flow_owns():
    flow = set(keys.SCREEN_KEYS.values()) | {keys.CENTRE, keys.PAGE_LEFT, keys.PAGE_RIGHT,
                                             *keys.ACTIVITY_KEYS}
    assert not flow & set(keys.SCANS.values())
    assert len(set(keys.SCANS.values())) == len(keys.SCANS)


@pytest.mark.parametrize("remote, charging", [("harmony-650", 0), ("harmony-700", 4)])
def test_the_scaffold_loads_and_every_picture_fits_the_screen(remote, charging):
    loaded = assets.load(paths.scaffolds(remote))
    assert {"backdrop", "softkey", "title-bar"} <= set(loaded["pictures"])
    # a 650 runs on batteries and shows no charging; a 700 charges in four pictures
    assert [role for role in loaded["pictures"] if role.startswith("charging/")] == [
        f"charging/{n}" for n in range(charging)]
    for role, picture in loaded["pictures"].items():
        assert picture["width"] <= 128 and picture["height"] <= 128, role
    assert not loaded["notes"]
    assert all(font["glyphs"] for font in loaded["fonts"].values())


@pytest.mark.parametrize("remote, count", [("harmony-650", 44), ("harmony-700", 49)])
def test_the_firmware_screens_are_counted_and_every_word_is_in_the_catalogue(remote, count):
    folder = paths.scaffolds(remote)
    model = json.loads((folder / firmware_screens.SYSTEM_SCREENS_FILE).read_text("utf-8"))
    assert model["schema"] == firmware_screens.SYSTEM_SCHEMA
    assert len(model["screens"]) == count
    notices = model["notices"]
    assert set(notices.values()) <= set(catalogue.NOTICES)
    pictures = json.loads((folder / "assets.json").read_text("utf-8"))["pictures"]
    lines: dict[str, int] = {}
    for block in model["blocks"]:
        for item in block:
            if item["opcode"] in ("bitmap", "sized_bitmap"):
                assert item["target"]["picture"] in pictures
            if item["opcode"] == "label" and item["key"].startswith("screen-"):
                lines[item["key"]] = lines.get(item["key"], 0) + 1
    for key, drawn in lines.items():
        name = notices[key.split("-")[1]]
        assert len(catalogue.NOTICES[name].split("\n")) == drawn, key
    assert set(lines) == {f"screen-{n}" for n in notices}
    platform_text.render(firmware_screens.load_system(folder),
                         lambda text, font, room: ("41", 6 * len(text)))
    # nothing a firmware screen does is left behind, and its own variables are carried
    assert model["dropped_header_rows"] == 0
    # the platform's own variables, shared with the wiring: the battery notice flag and the
    # USB screen's state among them
    wiring = json.loads((folder / "platform" / "wiring.json").read_text("utf-8"))
    assert model["variables"] == wiring["variables"]
    assert {1, 3} <= {variable["limit"] for variable in model["variables"]}


def _payload(path: Path) -> bytes:
    raw = path.read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    return raw[start:start + size]


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_a_configuration_reads_and_every_drawing_block_re_encodes(path):
    payload = _payload(path)
    gspm.validate(payload)
    roots = [slot["program_offset"] for screen in ui_index.screen_slots(payload)
             for slot in screen["slots"]]
    roots += list(ui_index.section12_programs(payload).values())
    blocks = drawing.program_blocks(payload, roots)
    for offset, instructions in blocks.items():
        encoded = drawing.encode_program(instructions)
        assert payload[offset:offset + len(encoded)] == encoded, hex(offset)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_every_command_of_a_configuration_has_its_object(path):
    report = command_index.inspect(_payload(path))
    # a command may have a second object of its own: Logitech's copy of an input sent
    # with the device's input delay (`7C dd0A`), as two of a Dutch 650's TV inputs have
    counts = report["counts"]
    assert counts["command_objects"] - counts["duplicate_command_objects"] == \
        counts["declared_commands"]
    assert "command_without_object" not in report["rejected"]


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_every_picture_of_a_configuration_round_trips(path):
    payload = _payload(path)
    start, end = gspm.section_ranges(payload)[19]
    assert payload[start:start + 2] == b"\x00\x00"       # no touch templates
    at = start + 2
    while at < end:
        picture = bitmap.decode(payload, at)
        assert bitmap.encode(picture["rows"], mode=picture["mode"]) == \
            payload[at:at + picture["size"]]
        at += picture["size"]
    assert at == end


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_every_glyph_a_configuration_draws_reads(path):
    payload = _payload(path)
    text = labels.Text(payload)
    for screen in ui_index.screen_slots(payload):
        for slot in screen["slots"]:
            labels.screen_text(payload, slot["program_offset"], text)
    assert text.unknown == 0


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_every_command_record_of_a_configuration_decodes(path):
    counts = command_index.inspect(_payload(path))["counts"]
    # a command that sends silence - Logitech's stand-in for a device it does not reach by
    # infrared, a Sony PS4's power off - is counted, not decoded
    assert counts["decoded_commands"] + counts["silent_commands"] == \
        counts["declared_commands"]


def _used_objects(reader) -> set[int]:
    """Every object something runs: a screen's or a context's row, another object, a
    variable's transition, a switch table's case."""
    out = set()
    for screen in reader.screens:
        out |= {entry["operand"] for entry in screen["header_entries"]
                + [entry for slot in screen["slots"] for entry in slot["entries"]]
                if entry["category"] == 0x7F}
    out |= {row["operand"] for context in reader.contexts for row in context["rows"]
            if row["category"] == 0x7F}
    out |= {operand for item in reader.objects for operand, opcode in item["atoms"]
            if opcode == 0x7F}
    out |= {item["operand"] for record in reader.engine for item in record["transitions"]
            if item["category"] == 0x7F}
    image = reader.payload
    for table in importing.switch_tables(image):
        for _value, block in table["cases"]:
            out |= {item["operand"] for item in ui_index.drawing_program(image, block)
                    ["instructions"] if item["opcode"] == "atom" and item["category"] == 0x7F}
    return out

@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_a_configuration_imports_its_devices_by_name(path, tmp_path):
    payloads.get("blob").unpack(_payload(path), str(tmp_path))
    result = backend.import_project(str(tmp_path), _remote(path),
                                    {"name": path.stem})
    devices = result.project["devices"]
    assert devices and all(device["label"] for device in devices)
    assert not any("could not read" in note for note in result.warnings)
    # every command is named by a page, a key or a power or input state; the help flow's
    # placeholder is not a device's, and is said to be left out
    # - but a device no page or key shows, a Sony PS4 that Logitech lists without any,
    # has nothing to be named by
    # - nor a command nothing in the image sends: ten of a Foxtel's on a 650, whose
    # objects no key, page, activity or sequence runs
    used = _used_objects(importing.Image(_payload(path)))
    assert not [name for device in devices for name, signal in device["signals"].items()
                if name.startswith("Command ")
                and any(entry[1] or entry[4] for entry in device["commands"])
                and set(signal["native"]["harmony-650"]["object_indexes"]) & used]
    assert all("placeholder" in note for note in result.warnings)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_a_devices_power_on_delay_is_its_delay_variable(path, tmp_path):
    payload = _payload(path)
    image = importing.Image(payload)
    delays = {name.split("_")[1]: record["initial"] * 100 for record in image.engine
              if (name := image.names.get(record["property_id"], "")).startswith("PowerOnDelay_")}
    payloads.get("blob").unpack(payload, str(tmp_path))
    devices = backend.import_project(str(tmp_path), _remote(path),
                                     {"name": path.stem}).project["devices"]
    powered = [device for device in devices
               if device.get("power_cmd") or device.get("power_on_cmd")]
    assert powered
    # each powered device's delay is one of the configuration's delay variables
    assert all(device["power_delay"] in delays.values() for device in powered)
    assert any(device["power_delay"] for device in powered)
    # and every device has the wait before the next one, which a delay variable holds
    assert all(device.get("inter_device_delay") is not None for device in devices)


@pytest.fixture(scope="module")
def empty_image():
    from afterglow.backends.harmony_650 import compose
    return compose.build({"devices": []}, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]


def test_a_project_with_nothing_builds_an_image_every_reader_reads(empty_image, tmp_path):
    from afterglow.backends.harmony_650 import activity_index, font_index, named_index
    gspm.validate(empty_image)
    screens = ui_index.screen_slots(empty_image)
    # the firmware's screens at their ordinals, then the Activities menu, the Devices list,
    # All Off's "Turning system off" and the welcome tour's pages
    from afterglow.backends.harmony_650.compose import TOUR
    assert len(screens) == FIRMWARE + 3 + len(TOUR)
    assert len(font_index.fonts(empty_image)) == len(json.loads(
        (SCAFFOLD / "assets.json").read_text("utf-8"))["fonts"])
    names = [record["name"] for record in named_index.inspect(empty_image)["records"]]
    assert names[:2] == ["Root", "State"] and any(n.startswith("CurrentActivityState")
                                                  for n in names)
    roots = [slot["program_offset"] for screen in screens for slot in screen["slots"]]
    for offset, instructions in drawing.program_blocks(empty_image, roots).items():
        encoded = drawing.encode_program(instructions)
        assert empty_image[offset:offset + len(encoded)] == encoded
    records = activity_index.engine_records(empty_image)
    count, narrow, wide, again = struct.unpack_from(
        "<HHHH", empty_image, gspm.section_ranges(empty_image)[14][0])
    assert (count, narrow + wide, again) == (len(records), len(records), narrow)
    # every variable past the narrow ones is the wide kind, and none before
    assert all(record["limit"] > 0xFF for record in records[narrow:])
    payloads.get("blob").unpack(empty_image, str(tmp_path))
    result = backend.import_project(str(tmp_path), remotes.get("harmony-650"), {"name": "t"})
    assert result.project["devices"] == [] and result.project["activities"] == []


def test_an_empty_image_lays_out_the_same_twice():
    from afterglow.backends.harmony_650 import compose
    project = {"devices": []}
    assert compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"] == \
        compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]


def _nec(address: int, command: int) -> dict:
    from afterglow import ir_signal
    pulses = [9000, -4500]
    for byte in (address, address ^ 0xFF, command, command ^ 0xFF):
        for bit in range(8):
            pulses += [560, -1690] if (byte >> bit) & 1 else [560, -560]
    return ir_signal.waveform(pulses + [560, -40000], carrier_hz=38000)


TV = ("PowerToggle", "PowerOn", "PowerOff", "VolumeUp", "VolumeDown", "VolumeMute",
      "ChannelUp", "InputHdmi1", "InputHdmi2", "Menu", "Netflix", "DirectionUp", "Select")
KEYED = ("VolumeUp", "VolumeDown", "VolumeMute", "ChannelUp", "Menu", "DirectionUp", "Select")
DEVICES = {"devices": [
    {"label": "Living Room TV", "type": "Television",
     "signals": {name: _nec(4, n) for n, name in enumerate(TV)},
     "commands": [[name, "", "", "", name] for name in KEYED]},
    {"label": "Blu-ray Disc Player", "type": "DvdCd",
     "signals": {"PowerToggle": _nec(10, 1), "Play": _nec(10, 2), "Eject": _nec(10, 3)},
     "commands": [["Play", "", "", "", "Play"]]}]}


def test_devices_build_and_come_back_with_their_commands_and_keys(tmp_path):
    from afterglow.backends.harmony_650 import compose
    image = compose.build(DEVICES, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    gspm.validate(image)
    counts = command_index.inspect(image)["counts"]
    assert counts["decoded_commands"] == counts["declared_commands"] == len(TV) + 3
    # the Devices list and each device's pages after the firmware's screens and the menu
    text = labels.Text(image)
    for screen in ui_index.screen_slots(image):
        for slot in screen["slots"]:
            labels.screen_text(image, slot["program_offset"], text)
    assert text.unknown == 0
    payloads.get("blob").unpack(image, str(tmp_path))
    result = backend.import_project(str(tmp_path), remotes.get("harmony-650"), {"name": "t"})
    assert not result.warnings
    for read, source in zip(result.project["devices"], DEVICES["devices"], strict=True):
        assert read["label"] == source["label"]
        # a name drawn across two lines - "Power" over "Toggle" - is joined back
        assert sorted(read["signals"]) == sorted(source["signals"])
        bound = {entry[0]: entry[4] for entry in read["commands"] if entry[4]}
        assert bound == {entry[0]: [entry[4]] for entry in source["commands"]}


def _household() -> dict:
    project = json.loads(json.dumps(DEVICES))
    tv, player = project["devices"]
    tv.update(id="tv", power_on_cmd="PowerOn", power_off_cmd="PowerOff", power_delay=2000,
              inputs=[["InputHdmi1", "InputHdmi1"], ["InputHdmi2", "InputHdmi2"]],
              inter_device_delay=300)
    player.update(id="bd", power_cmd="PowerToggle", power_delay=5000)
    project["activities"] = [
        {"label": "Watch TV", "display": "tv", "control": "tv", "volume": "tv",
         "input": ["tv", "InputHdmi1"],
         "soft_buttons": [["Netflix", "tv", "Netflix"], ["Menu", "tv", "Menu"]]},
        {"label": "Watch a Movie", "display": "tv", "control": "bd", "volume": "tv",
         "power_on_devices": ["tv", "bd"], "input": ["tv", "InputHdmi2"],
         "enter": [["command", "bd", "Play"]], "soft_buttons": [["Eject", "bd", "Eject"]]}]
    return project


def test_activities_build_and_come_back_as_the_project_has_them(tmp_path):
    from afterglow.backends.harmony_650 import compose
    project = _household()
    built = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))
    assert built["skipped"] == []
    payloads.get("blob").unpack(built["image"], str(tmp_path))
    result = backend.import_project(str(tmp_path), remotes.get("harmony-650"), {"name": "t"})
    assert not result.warnings
    tv, player = result.project["devices"]
    assert (tv["power_on_cmd"], tv["power_off_cmd"], tv["power_delay"]) == (
        "PowerOn", "PowerOff", 2000)
    assert (player["power_cmd"], player["power_delay"]) == ("PowerToggle", 5000)
    assert [entry[1] for entry in tv["inputs"]] == ["InputHdmi1", "InputHdmi2"]
    # each device's wait before the next, its own or the default
    assert (tv["inter_device_delay"], player["inter_device_delay"]) == (300, 500)
    watch, movie = result.project["activities"]
    assert (watch["label"], movie["label"]) == ("Watch TV", "Watch a Movie")
    assert watch["power_on_devices"] == [tv["id"]]
    assert watch["enter"] == [["input", tv["id"], "InputHdmi1"]]
    assert movie["power_on_devices"] == [tv["id"], player["id"]]
    assert movie["enter"] == [["input", tv["id"], "InputHdmi2"],
                              ["command", player["id"], "Play"]]
    assert (movie["control"], movie["volume"]) == (player["id"], tv["id"])
    assert watch["soft_buttons"] == [["Netflix", tv["id"], "Netflix"],
                                     ["Menu", tv["id"], "Menu"]]
    assert movie["soft_buttons"] == [["Eject", player["id"], "Eject"]]
    # Off turns off every device with a power command, which is what no list says
    assert "power_off_all" not in result.project


def test_the_activity_keys_start_the_first_activities_and_the_rest_say_there_is_none():
    from afterglow.backends.harmony_650 import compose
    image = compose.build(_household(), stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    reader = importing.Image(image)
    acts = importing.Activities(reader, [], {}, [])
    starts = acts.starts()
    bound = {}
    for context in reader.contexts:
        for row in context["rows"]:
            if row["key_code"] in [keys.code(key) for key in keys.ACTIVITY_KEYS]:
                bound.setdefault(row["key_code"], reader.row(row))
    first, second, third = (keys.code(key) for key in keys.ACTIVITY_KEYS)
    assert bound[first] == [("context", starts[0])]
    assert bound[second] == [("context", starts[1])]
    assert all(step[0] == "mode" for step in bound[third][-1:])


def test_each_activity_key_starts_the_activity_that_names_it():
    """A project that says which activity key starts which activity - "Movie", "TV" or
    "Music", as an import reads Logitech's - gets them so; a key no activity names says to
    add one. A 700's "Watch Roku" on Watch a Movie stays there."""
    from afterglow.backends.harmony_650 import compose
    project = _household()
    project["activities"][1]["activity_button"] = "Movie"
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    reader = importing.Image(image)
    acts = importing.Activities(reader, [], {}, [])
    starts = acts.starts()
    bound = {}
    for context in reader.contexts:
        for row in context["rows"]:
            if row["key_code"] in [keys.code(key) for key in keys.ACTIVITY_KEYS]:
                bound.setdefault(row["key_code"], reader.row(row))
    movie, tv, music = (keys.code(keys.ACTIVITY_BUTTONS[name])
                        for name in ("Movie", "TV", "Music"))
    assert bound[movie] == [("context", starts[1])]
    assert all(step[0] == "mode" for step in bound[tv][-1:])
    assert all(step[0] == "mode" for step in bound[music][-1:])
    assert acts.activity_buttons() == {starts[1]: "Movie"}


def test_more_activities_opens_the_menu_with_an_activity_running():
    """More Activities switches on CurrentLocation, which is only ever 0 - the Activities
    menu - as Logitech's: starting an activity does not make it go back to that activity."""
    from afterglow.backends.harmony_650 import compose
    image = compose.build(_household(), stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    reader = importing.Image(image)
    tables = importing.switch_tables(image)
    names = {record["property_id"]: reader.names.get(record["property_id"])
             for record in reader.engine}
    [location] = [number for number, name in names.items() if name == "CurrentLocation_1"]
    switches = [operand >> 8 for item in reader.objects for operand, opcode in item["atoms"]
                if opcode == 0x72 and operand & 0xFF == location]
    assert switches
    menu = FIRMWARE
    for group in switches:
        [(value, block)] = tables[group]["cases"]
        assert value == 0
        assert [(item["operand"], item["category"])
                for item in ui_index.drawing_program(image, block)["instructions"]
                if item["opcode"] == "atom"] == [(menu, 0x7E)]
    writes = [operand for item in reader.objects for operand, opcode in item["atoms"]
              if opcode == 0x80 | location]
    assert writes == []


def test_every_page_with_a_sending_mark_redraws_it_as_sending_starts_and_stops():
    """The firmware raises `2D` as its sending flag changes; a page that queues a corner
    program binds `2D` to it, as Logitech's do, or the mark shows only on a redraw."""
    from afterglow.backends.harmony_650 import compose
    image = compose.build(_household(), stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    reader = importing.Image(image)
    checked = 0
    for ordinal, screen in enumerate(reader.screens[FIRMWARE:],
                                     FIRMWARE):
        program = ui_index.drawing_program(image, screen["slots"][0]["program_offset"])
        queued = [item["operand"] for item in program["instructions"]
                  if item["opcode"] == "atom" and item["category"] == 0x73]
        corners = [operand for operand in queued if operand in (1, 2, 3)]
        if corners:
            redraw = [(entry["operand"], entry["category"])
                      for entry in screen["header_entries"] if entry["key_code"] == 0x2D]
            assert redraw == [(corners[0], 0x73)], ordinal
            checked += 1
    assert checked > 5


def test_the_backend_builds_a_household_into_an_ezhex(tmp_path):
    import dataclasses

    from afterglow import backends
    from afterglow.backends.contracts import BuildContext

    profile = remotes.get("harmony-650")
    context = BuildContext(root=tmp_path, log=lambda _line: None,
                           find_scaffold=lambda _id, _root: None)
    project = {**_household(), "settings": {"out_file": "mine"}}
    # experimental, as the profile ships - and read-only, nothing would be built
    result = backends.for_profile(profile).build_project(project, profile, context)
    with pytest.raises(remotes.NotBuildable):
        read_only = dataclasses.replace(profile, status="read-only")
        backends.for_profile(read_only).build_project(project, read_only, context)
    raw = result.artifact.read_bytes()
    header, start, size, checksum = ezhex._split(raw)
    assert remotes.identify(header).id == "harmony-650"
    assert checksum == ezhex.checksum(raw[start:start + size])
    gspm.validate(raw[start:start + size])
    assert result.changes == {"skipped": []}


def _by_label(project: dict) -> dict:
    """A project as what it does, every device named by its label - a rebuild numbers
    devices in the Devices list's order, so their ids are not kept - and every signal
    less where it sat in the image."""
    labels = {device["id"]: device["label"] for device in project["devices"]}
    text = json.dumps(project, default=str)
    for device_id, label in labels.items():
        text = text.replace(json.dumps(device_id), json.dumps(label))
    out = json.loads(text)
    loosened = {}
    for device in out["devices"]:
        device.pop("id"), device.pop("native", None)
        # the inter-key delay lives in the codes Help sends to fix a device, so one Help
        # never asks about - with no power or inputs of its own, as a Dutch 650's fan
        # imports - keeps it only in the project
        if not any(device.get(field) for field in (
                "power_cmd", "power_on_cmd", "inputs", "input_cycle")):
            device.pop("press_interkey", None)
        # A key's own command is on no page of a build, as on 314 of the 317 key commands
        # of the configurations measured; a Samsung's Info, Guide and Menu on the 650 are
        # the three Logitech drew.
        for entry in device["commands"]:
            own = [key for key in entry[4] or () if keys.is_own_command(key, entry[0])]
            if own:
                entry[1] = ""
                # and a rebuild's import names it after the key - a TCL's "Mute", drawn
                # on its page on a 665, comes back as "VolumeMute": the same code there
                if entry[0] != own[0] and own[0] not in device["signals"]:
                    device["signals"][own[0]] = dict(device["signals"].pop(entry[0]),
                                                     name=own[0])
                    entry[0] = own[0]
        # a device no page or key names - a Sony PS4 - has numbered names, numbered by
        # where its codes sit, which a rebuild may move: compared by order, as they are
        if not any(entry[1] or entry[4] for entry in device["commands"]):
            order = sorted(device["signals"])
            device["signals"] = {f"#{at}": dict(device["signals"][name], name=f"#{at}")
                                 for at, name in enumerate(order)}
            device["commands"] = [[f"#{at}", *entry[1:]] for at, entry in enumerate(
                sorted(device["commands"]))]
        # a named device's commands nothing names - ten of a Foxtel's on a 650, which
        # nothing sends - are numbered by where they sit, which a rebuild moves: compared
        # by their codes
        loose = sorted((name for name in device["signals"] if name.startswith("Command ")),
                       key=lambda name: json.dumps({**device["signals"][name], "name": "",
                                                    "native": None}, sort_keys=True))
        if loose and len(loose) < len(device["signals"]):
            renamed = {name: f"~{at}" for at, name in enumerate(loose)}
            # and wherever an activity or the device's own states send one
            loosened[device["label"]] = renamed
            device["signals"] = {renamed.get(name, name):
                                 dict(signal, name=renamed.get(name, name))
                                 for name, signal in device["signals"].items()}
            for entry in device["commands"]:
                entry[0] = renamed.get(entry[0], entry[0])
        # the pages' commands in their order; the rest, which no page shows, in any
        drawn = [entry for entry in device["commands"] if entry[1]]
        device["commands"] = drawn + sorted(entry for entry in device["commands"]
                                            if not entry[1])
        for signal in device["signals"].values():
            signal.pop("native", None)
    def loosen(item, label=None):
        # a step or a button names its device then its command: [kind, device, name, ...]
        if isinstance(item, list):
            if len(item) >= 3 and isinstance(item[1], str) and item[1] in loosened \
                    and isinstance(item[2], str):
                item[2] = loosened[item[1]].get(item[2], item[2])
            for part in item:
                loosen(part, label)
        elif isinstance(item, dict):
            for key, value in item.items():
                if label in loosened and isinstance(value, str) and key != "label":
                    item[key] = loosened[label].get(value, value)
                else:
                    loosen(value, label)
    for activity in out["activities"]:
        activity.pop("id")
        loosen(activity)
    for device in out["devices"]:
        for field in ("input_cycle", "inputs"):
            if field in device:
                loosen(device[field], device["label"])
    return out


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_a_configuration_imported_builds_and_imports_the_same(path, tmp_path):
    from afterglow.backends.harmony_650 import compose
    payloads.get("blob").unpack(_payload(path), str(tmp_path / "first"))
    first = backend.import_project(str(tmp_path / "first"), _remote(path),
                                   {"name": "rt"}).project
    first = json.loads(json.dumps(first, default=str))
    built = compose.build(first, directory=paths.scaffolds(_remote(path).id),
                          stamp_fields=(0, 0, 12, 0, 0, 2026))
    assert built["skipped"] == []
    payloads.get("blob").unpack(built["image"], str(tmp_path / "second"))
    second = backend.import_project(str(tmp_path / "second"), _remote(path),
                                    {"name": "rt"})
    assert not second.warnings
    assert _by_label(json.loads(json.dumps(second.project, default=str))) == _by_label(first)


def _references_out_of_range(image: bytes) -> list:
    """Every instruction naming something the image does not have: an object, a screen, a
    context, a switch table, a section-12 program, a timer or a variable - wherever an
    instruction sits: objects, contexts, screens' and pages' key lists, what pages queue,
    switch cases, timers, the start-up list, mode 0's list and variables' transitions. Nothing on the remote checks one: a donor's
    variable number carried into a build hung a 650 at its logo, the store writing past its
    end (docs/harmony_650_700/gspm.md, "Building an image")."""
    ranges = gspm.section_ranges(image)
    variables = struct.unpack_from("<H", image, ranges[14][0])[0]
    reader = importing.Image(image)
    screens = len(reader.screens)
    contexts = image[ranges[10][0]]
    groups = image[ranges[15][0]]
    timers = image[ranges[13][0]]
    objects = len(reader.objects)
    rows = [(atom, f"object {index}") for index, item in enumerate(reader.objects)
            for atom in item["atoms"]]
    rows += [((row["operand"], row["category"]), f"context {context['ordinal']}")
             for context in reader.contexts for row in context["rows"]]
    programs = image[ranges[12][0]] | image[ranges[12][0] + 1] << 8
    for ordinal, screen in enumerate(reader.screens):
        entries = screen["header_entries"] + [entry for slot in screen["slots"]
                                              for entry in slot["entries"]]
        rows += [((entry["operand"], entry["category"]), f"screen {ordinal}")
                 for entry in entries]
        # what a page's program queues: its corner program among them
        rows += [((item["operand"], item["category"]), f"screen {ordinal}'s program")
                 for slot in screen["slots"]
                 for item in ui_index.drawing_program(image, slot["program_offset"])["instructions"]
                 if item["opcode"] == "atom"]
    for number, table in enumerate(importing.switch_tables(image)):
        for _value, block in table["cases"]:
            rows += [((item["operand"], item["category"]), f"switch {number}")
                     for item in ui_index.drawing_program(image, block)["instructions"]
                     if item["opcode"] == "atom"]
    rows += [((operand, opcode), f"timer {number}")
             for number, (_seconds, operand, opcode) in enumerate(importing.timers(image))]
    start = ranges[9][0]
    rows += [((int.from_bytes(image[start + 1 + 3 * k:start + 3 + 3 * k], "little"),
               image[start + 3 + 3 * k]), "the start-up list") for k in range(image[start])]
    zero = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC)
    rows += [(struct.unpack_from("<HB", image, zero + 2 + 4 * k), "mode 0")
             for k in range(image[zero])]
    rows += [((item["operand"], item["category"]), f"variable {record['property_id']}")
             for record in reader.engine for item in record["transitions"]]
    out = []
    for (operand, category), where in rows:
        bad = None
        if category == 0x7F and operand >= objects:
            bad = "object"
        elif category == 0x7E and operand >= screens:
            bad = "screen"
        elif category == 0x1F and operand >> 8 == 0xFF and operand & 0xFF >= contexts:
            bad = "context"
        elif category == 0x1F and operand >> 8 in (0xEA, 0xEB) and operand & 0xFF >= timers:
            bad = "timer"
        elif category == 0x72 and operand >> 8 >= groups:
            bad = "switch table"
        elif category == 0x73 and operand & 0xFF >= programs:
            bad = "screen program"
        variable = (category & 0x7F if category >= 0x80
                    else operand & 0xFF if category in (0x70, 0x71, 0x72)
                    else operand & 0xFF if category == 0x1F and operand >> 8 in (0xED, 0xEE)
                    else None)
        if variable is not None and variable >= variables:
            bad = "variable"
        if bad:
            out.append((where, bad, hex(operand), hex(category)))
    return out


@pytest.mark.parametrize("project", [{"devices": []}, DEVICES, "household"],
                         ids=["empty", "devices", "household"])
def test_a_build_names_nothing_it_does_not_have(project):
    from afterglow.backends.harmony_650 import compose
    project = _household() if project == "household" else project
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert _references_out_of_range(image) == []


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_a_configuration_and_its_rebuild_name_nothing_they_do_not_have(path, tmp_path):
    from afterglow.backends.harmony_650 import compose
    assert _references_out_of_range(_payload(path)) == []
    payloads.get("blob").unpack(_payload(path), str(tmp_path))
    project = backend.import_project(str(tmp_path), _remote(path),
                                     {"name": "rt"}).project
    project = json.loads(json.dumps(project, default=str))
    image = compose.build(project, directory=paths.scaffolds(_remote(path).id),
                          stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert _references_out_of_range(image) == []


def test_devices_returns_to_the_running_activity():
    """Devices, from the menu, an activity's screen or a device's Back, goes through a switch
    on the running activity, as Logitech's does: to that activity's own Devices list, whose
    centre key returns to it, or with none running to the list that returns to the menu."""
    from afterglow.backends.harmony_650 import compose
    image = compose.build(_household(), stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    reader = importing.Image(image)
    tables = importing.switch_tables(image)
    centre = keys.code(keys.CENTRE)

    def centre_of(ordinal):
        return next(reader.row(entry) for entry in reader.screens[ordinal]["header_entries"]
                    if entry["key_code"] == centre)

    def opened(block):
        return [item["operand"] for item in ui_index.drawing_program(image, block)["instructions"]
                if item["opcode"] == "atom" and item["category"] == 0x7E]
    menu = FIRMWARE
    [(kind, operand)] = centre_of(menu)
    assert kind == "switch"
    cases = dict(tables[operand >> 8]["cases"])
    acts = importing.Activities(reader, [], {}, [])
    state = acts.state
    assert operand & 0xFF == state
    starts = acts.starts()
    for index, _context in enumerate(starts):
        [listed] = opened(cases[index])
        # the activity's list goes back to the activity's screen, which names it
        [(_mode, back)] = centre_of(listed)
        titles = [item["text"] for slot in reader.screens[back]["slots"]
                  for item in reader.page_text(slot["program_offset"]) if item["y"] == 2]
        assert _household()["activities"][index]["label"] in titles
    [idle] = opened(cases[len(starts)])
    assert centre_of(idle) == [("mode", menu)]


def test_help_asks_about_each_device_and_input_of_the_running_activity():
    """Help in an activity, as Logitech's 650 and 700 run it: "Attempting to fix the
    problem..." sends the activity's commands again as it is entered, then "Did that fix the
    problem?"; No asks about each device it powers, then its input, Yes goes home. Off asks
    whether each device is off."""
    from afterglow.backends.harmony_650 import compose
    project = _household()
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert _references_out_of_range(image) == []
    reader = importing.Image(image)

    def text(ordinal):
        return " ".join(item["text"] for slot in reader.screens[ordinal]["slots"]
                        for item in reader.page_text(slot["program_offset"])
                        if item["y"] < 60)

    def answer(ordinal, code):
        [entry] = [entry for slot in reader.screens[ordinal]["slots"]
                   for entry in slot["entries"] if entry["key_code"] == code]
        return [step[1] for step in reader.row(entry) if step[0] == importing.MODE]

    attempts = [step[1] for context in reader.contexts for row in context["rows"]
                if row["key_code"] == compose.HELP for step in reader.row(row)]
    assert len(attempts) == 3
    labels = {device["id"]: device["label"] for device in project["devices"]}
    off, _watch, movie = attempts   # Off's context comes before the activities'
    [entered] = [entry for entry in reader.screens[movie]["header_entries"]
                 if entry["key_code"] == compose.ENTERED]
    [check] = [step[1] for step in reader.row(entered) if step[0] == importing.MODE]
    assert text(check) == "Did that fix the problem?"
    [home] = answer(check, compose.ANSWER_YES)
    asked, [ordinal] = [], answer(check, compose.ANSWER_NO)
    while ordinal != home:
        asked.append(text(ordinal))
        [again] = answer(ordinal, compose.ANSWER_NO)
        assert text(again) == "Now i" + asked[-1][1:]
        [ordinal] = answer(ordinal, compose.ANSWER_YES)
    assert asked == [f"Is the {labels['tv']} on?", f"Is the {labels['bd']} on?",
                     f"Is the {labels['tv']} set to the InputHdmi2 input?"]
    assert text(off + 2) == f"Is the {labels['tv']} off?"


def _run_object(reader, index: int, variables: dict, state: dict | None = None) -> dict:
    """Run object ``index`` as the 650 and 700 run Help's delay steps (gspm.md, "Help
    held"): `7A` loads the accumulator, `79` adds, `6E` takes the remainder, `1F EFvv`/`EDvv`
    load and store a variable, `1F FBnn` loads the byte register, `70`/`71` test a variable
    against the accumulator/byte register - guarding the next instruction - or with test 7
    take the accumulator off it; anything else is not arithmetic."""
    state = {"acc": 0, "byte": 0} if state is None else state
    tests = {1: lambda a, b: a != b, 2: lambda a, b: a < b, 3: lambda a, b: a > b}
    skip = False
    for operand, opcode in reader.objects[index]["atoms"]:
        if skip:
            skip = False
            continue
        if opcode == 0x7F:
            _run_object(reader, operand, variables, state)
        elif opcode == 0x7A:
            state["acc"] = operand
        elif opcode == 0x79:
            state["acc"] = (state["acc"] + operand) & 0xFFFF
        elif opcode == 0x6E:
            state["acc"] %= operand
        elif opcode == 0x1F and operand >> 8 == 0xEF:
            state["acc"] = variables.get(operand & 0xFF, 0)
        elif opcode == 0x1F and operand >> 8 == 0xED:
            variables[operand & 0xFF] = state["acc"]
        elif opcode == 0x1F and operand >> 8 == 0xFB:
            state["byte"] = operand & 0xFF
        elif opcode in (0x70, 0x71):
            test, variable = operand >> 8, operand & 0xFF
            against = state["acc"] if opcode == 0x70 else state["byte"]
            if test == 7:
                variables[variable] = variables.get(variable, 0) - against
            else:
                skip = not tests[test](variables.get(variable, 0), against)
    return variables


def test_help_held_changes_a_devices_delays_as_logitechs_do():
    """Help held: "Delay Fixing", then a device and its delay. - and + step the power-on
    delay a whole second at a time between 1 and 45 s and the inter-device one half a
    second between 0 and 2 s - a delay off a step is rounded down to one first, then
    stepped; Done copies it to the device's own variable, which its power-on waits on."""
    from afterglow.backends.harmony_650 import compose
    project = _household()
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert _references_out_of_range(image) == []
    reader = importing.Image(image)

    def mode(atoms):
        return [step[1] for step in atoms if step[0] == importing.MODE]

    def key(ordinal, code, slot=0):
        [entry] = [entry for entry in reader.screens[ordinal]["slots"][slot]["entries"]
                   if entry["key_code"] == code]
        return entry

    def header(ordinal, code):
        [entry] = [entry for entry in reader.screens[ordinal]["header_entries"]
                   if entry["key_code"] == code]
        return entry

    held = {mode(reader.row(row))[0] for context in reader.contexts
            for row in context["rows"] if row["key_code"] == compose.HELP_HELD}
    [warning] = held
    [select] = mode(reader.row(key(warning, compose.ANSWER_YES)))
    top_left = keys.code(keys.SCREEN_KEYS["top-left"])
    [menu] = mode(reader.row(key(select, top_left)))      # the first device: the TV
    [change] = mode(reader.row(key(menu, compose.ANSWER_NO)))
    entry = key(change, top_left)
    [power] = mode(reader.row(entry))
    names = {record["property_id"]: reader.names.get(record["property_id"])
             for record in reader.engine}
    delay = next(number for number, name in names.items()
                 if name == "PowerOnDelay_1_65278")
    variables = {delay: 20}
    _run_object(reader, entry["operand"], variables)
    edit = next(number for number, value in variables.items()
                if number != delay and value == 20)
    minus, plus = (key(power, code)["operand"] for code in (compose.ANSWER_NO,
                                                             compose.ANSWER_YES))
    for start, pressed, expected in ((30, minus, 20), (20, minus, 10), (15, minus, 10),
                                     (10, minus, 10), (15, plus, 20), (440, plus, 450),
                                     (450, plus, 450)):
        assert _run_object(reader, pressed, {edit: start})[edit] == expected
    done = header(power, keys.code(keys.CENTRE))
    variables = _run_object(reader, done["operand"], {edit: 70, delay: 20})
    assert variables[delay] == 70
    assert mode(reader.row(done)) == [change]
    # the inter-device delay: half a second at a time, 0 to 2 s
    entry = key(change, compose.ANSWER_NO)
    [inter] = mode(reader.row(entry))
    minus, plus = (key(inter, code)["operand"] for code in (compose.ANSWER_NO,
                                                             compose.ANSWER_YES))
    inter_edit = next(atom[0] & 0xFF for atom in reader.objects[entry["operand"]]["atoms"]
                      if atom[1] == 0x1F and atom[0] >> 8 == 0xED)
    for start, pressed, expected in ((10, minus, 5), (5, minus, 0), (0, minus, 0),
                                     (7, plus, 10), (20, plus, 20)):
        assert _run_object(reader, pressed, {inter_edit: start})[inter_edit] == expected


def test_a_toggling_rc5_device_builds_both_states_and_reads_them_back(tmp_path):
    """RC5 flips a bit on every press. Logitech writes such a command as a 34-byte record,
    waveform mode 2, with a second set of waveforms the remote sends on every other press -
    a 665's 67 Media Center and Xbox commands - and a build does the same."""
    from afterglow import ir_signal
    from afterglow.backends.harmony_650 import compose
    project = _household()
    player = project["devices"][1]
    player["signals"] = {name: ir_signal.protocol_signal("rc5-13", {"code": 0x140 + number})
                         for number, name in enumerate(sorted(player["signals"]))}
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert _references_out_of_range(image) == []
    devices = command_index.inspect(image)["devices"]
    toggling = [command for device in devices for command in device["commands"]
                if command["waveform_mode"] == 2]
    assert len(toggling) == len(player["signals"])
    for command in toggling:
        first = command["waveforms"]["press"]["pulses_us"]
        other = command["alternate_waveforms"]["press"]["pulses_us"]
        assert first != other, "the two presses differ in the toggle bit"
    payloads.get("blob").unpack(image, str(tmp_path))
    read = backend.import_project(str(tmp_path), remotes.get("harmony-650"), {"name": "t"})
    assert not read.warnings
    _tv, back = read.project["devices"]
    assert all(signal.get("alternate") for signal in back["signals"].values())


def test_a_menu_input_builds_and_comes_back(tmp_path):
    """Logitech's menu inputs, as a tester's Soniq television has them on a 650:
    Source, Up or Down whichever is fewer presses, then OK, each code a second apart."""
    from afterglow.backends.harmony_650 import compose
    names = ("PowerToggle", "Source", "DirectionUp", "DirectionDown", "OK")
    tv = {"id": "tv", "label": "Soniq TV", "type": "Television",
          "signals": {name: _nec(3, number) for number, name in enumerate(names)},
          "commands": [[name, name, "", "", None] for name in names],
          "power_cmd": "PowerToggle", "power_delay": 3000,
          "input_cycle": {"values": ["DTV", "AV", "HDMI 1", "HDMI 2", "Media"],
                          "start": ["Source"], "next": ["DirectionUp"],
                          "previous": ["DirectionDown"], "finish": ["OK"],
                          "delay_ms": 1000}}
    image = compose.build({"devices": [tv]}, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert _references_out_of_range(image) == []
    payloads.get("blob").unpack(image, str(tmp_path))
    [read] = backend.import_project(str(tmp_path), remotes.get("harmony-650"),
                                    {"name": "t"}).project["devices"]
    cycle = read["input_cycle"]

    def listed(value):          # a step, or a list of them: the format takes either
        return value if isinstance(value, list) else [value]
    assert (cycle["start"], listed(cycle["next"]), listed(cycle["previous"]),
            cycle["finish"], cycle["delay_ms"], len(cycle["values"])) == (
        ["Source"], ["DirectionUp"], ["DirectionDown"], ["OK"], 1000, 5)

def test_the_backlight_time_and_tilt_sensor_build_and_come_back(tmp_path):
    """MyHarmony's Remote Backlight Settings: how long the screen stays lit, a timer of
    the wiring, and whether picking the remote up wakes it, the `3F F101` arming the
    tilt sensor. Unset, the donor's: 20 seconds and on, as Logitech's default."""
    from afterglow.backends.harmony_650 import compose

    def read(settings):
        project = dict(DEVICES, settings=settings)
        image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
        folder = tmp_path / str(len(list(tmp_path.iterdir())))
        payloads.get("blob").unpack(image, str(folder))
        read = backend.import_project(str(folder), remotes.get("harmony-650"),
                                      {"name": "t"}).project["settings"]
        return read.get("backlight_timeout"), read.get("tilt")
    assert read({}) == ("20", "on")
    assert read({"backlight_timeout": "7", "tilt": "off"}) == ("7", "off")


def test_the_remote_assistant_follows_a_start_until_it_is_turned_off(tmp_path):
    """Logitech's Remote Assistant: after a start, `1F FB00` and `[71 80vv, 7E note,
    7E screen]` - its note while variable vv is 0, which "Turn off Assistant" makes 1.
    Off in the settings, no note and no variable."""
    from afterglow.backends.harmony_650 import compose

    def built(on):
        project = _household()
        project["settings"] = {"remote_assistant": on}
        image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
        assert _references_out_of_range(image) == []
        folder = tmp_path / str(on)
        payloads.get("blob").unpack(image, str(folder))
        read = backend.import_project(str(folder), remotes.get("harmony-650"), {"name": "t"})
        reader = importing.Image(image)
        notes = [screen for screen in reader.screens if any(
            item["text"] == "Remote Assistant"
            for item in reader.page_text(screen["slots"][0]["program_offset"]))]
        return read.project, reader, notes
    project, reader, notes = built(True)
    assert project["settings"]["remote_assistant"] is True
    assert len(notes) == len(project["activities"]) == 2
    # "Turn off Assistant" writes 1 and goes on to the activity
    [row] = notes[0]["slots"][0]["entries"]
    steps = reader.row(row)
    assert steps[0][0] == "write" and steps[0][2] == 1 and steps[-1][0] == "mode"
    project, reader, notes = built(False)
    assert project["settings"]["remote_assistant"] is False and notes == []


def test_an_activity_fills_its_page_arrows_and_disc_skips_as_logitechs_compiler(tmp_path):
    """Logitech's activity key map, from its control device: the page arrows its pad
    when it has nothing there, and on a disc player whose Channel up runs its pad, Channel
    up and down its skips (harmony-explorations, compiler.md, "An activity's key map")."""
    from afterglow.backends.harmony_650 import compose
    project = _household()
    player = project["devices"][1]
    for number, name in enumerate(("DirectionUp", "SkipForward", "SkipBack"), start=10):
        player["signals"][name] = _nec(10, number)
    player["commands"] += [["DirectionUp", "", "", "", ["DirectionUp", "ChannelUp"]],
                           ["SkipForward", "", "", "", "SkipForward"],
                           ["SkipBack", "", "", "", "SkipBack"]]
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    payloads.get("blob").unpack(image, str(tmp_path))
    read = backend.import_project(str(tmp_path), remotes.get("harmony-650"),
                                  {"name": "t"}).project
    watch, movie = read["activities"]
    tv, bd = watch["power_on_devices"][0], movie["power_on_devices"][1]
    assert watch["hard_macros"]["UpArrow"] == [["command", tv, "DirectionUp"]]
    # the player's pad code, whatever its two keys have it read back as
    [pad] = [entry[0] for device in read["devices"] if device["id"] == bd
             for entry in device["commands"] if "DirectionUp" in (entry[4] or ())]
    assert movie["hard_macros"]["UpArrow"] == [["command", bd, pad]]
    assert movie["hard_macros"]["ChannelUp"] == [["command", bd, "SkipForward"]]
    assert movie["hard_macros"]["ChannelDown"] == [["command", bd, "SkipBack"]]


def test_the_welcome_tour_runs_once_after_a_write_unless_a_build_skips_it():
    """Logitech's tour (650-a, the one dump that shows it): the wiring's third entry list
    marks it started and enters its first page, each page going on with the key it names;
    skipped, as MyHarmony compiles every sync after the first, it calls the tour's exit."""
    from afterglow.backends.harmony_650 import backend as built_by, compose

    def built(welcome):
        project = _household()
        project["settings"] = {"welcome": welcome}
        image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
        assert _references_out_of_range(image) == []
        reader = importing.Image(image)
        pages = [screen["ordinal"] for screen in reader.screens if any(
            "Welcome to your" in item["text"]
            for item in reader.page_text(screen["slots"][0]["program_offset"]))]
        entered = [index for index, item in enumerate(reader.objects)
                   for operand, opcode in item["atoms"] if opcode == 0x7E and operand in pages]
        return image, reader, pages, entered
    image, reader, pages, entered = built("always")
    assert len(pages) == 1 and len(entered) == 1
    # Welcome goes on with the right arrow, and the next page back with the left
    [first] = pages
    assert [(row["key_code"], reader.row(row)) for row in reader.screens[first]["header_entries"]] \
        == [(0xA3, [("mode", first + 1)])]
    assert built_by.afterglow_built(image) is True
    _image, _reader, pages, entered = built("never")
    assert pages == [] and entered == []


def test_favourite_channels_build_and_come_back(tmp_path):
    """An activity's favourites: a "Favorite Channels" button first on its page opens
    them, "Commands" first among them goes back, and each dials its channel."""
    from afterglow.backends.harmony_650 import compose
    project = _household()
    tv = project["devices"][0]
    for digit in range(10):
        tv["signals"][f"Number{digit}"] = _nec(4, 40 + digit)
        tv["commands"].append([f"Number{digit}", "", "", "", f"Number{digit}"])
    project["activities"][0]["image_buttons"] = [
        ["BBC One", "channel", "101", None], ["Channel 7", "channel", "7", None]]
    built = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))
    assert built["skipped"] == []
    assert _references_out_of_range(built["image"]) == []
    payloads.get("blob").unpack(built["image"], str(tmp_path))
    watch = backend.import_project(str(tmp_path), remotes.get("harmony-650"),
                                   {"name": "t"}).project["activities"][0]
    assert watch["image_buttons"] == [["BBC One", "channel", "101", None],
                                      ["Channel 7", "channel", "7", None]]
    assert [button[0] for button in watch["soft_buttons"]] == ["Netflix", "Menu"]


FAVOURITES_650 = ROOT / "configs" / "650" / "650-favourites-backup.ezhex"


@pytest.mark.skipif(not FAVOURITES_650.exists(), reason="the favourites dump (650-favourites)")
def test_logitechs_favourite_channels_read_as_the_channels_they_dial(tmp_path):
    """A tester's 650 with MyHarmony favourites: each favourite writes a channel
    variable, whose change loads its number and runs section 17's number sender - his
    Humax's at least three digits, so channel 1 goes out as 0, 0, 1."""
    payloads.get("blob").unpack(_payload(FAVOURITES_650), str(tmp_path))
    project = backend.import_project(str(tmp_path), remotes.get("harmony-650"),
                                     {"name": "t"}).project
    [humax] = [item for item in project["activities"] if item["label"] == "Humax"]
    assert [entry[:3] for entry in humax["image_buttons"]] == [
        ["Channel 0", "channel", "0"], ["one", "channel", "001"],
        ["Channel 002", "channel", "002"], ["3", "channel", "003"], ["101", "channel", "101"]]


def test_a_devices_inter_key_delay_holds_the_codes_help_sends(tmp_path):
    """MyHarmony's inter-key delay is how long each code Help's answers send to fix a
    device is held: a tester's Soniq dumped at 200, 100 and 0 ms holds them 2, 1 and
    0 tenths. A build holds them so and an import reads it back."""
    from afterglow.backends.harmony_650 import compose
    from test_harmony_one_import import _interkey_project
    image = compose.build(_interkey_project(_nec),
                          stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert _references_out_of_range(image) == []
    payloads.get("blob").unpack(image, str(tmp_path))
    devices = backend.import_project(str(tmp_path), remotes.get("harmony-650"),
                                     {"name": "t"}).project["devices"]
    assert {device["label"]: device.get("press_interkey") for device in devices} == {
        "Soniq TV": 300, "Receiver": 0}

def test_a_devices_other_states_build_and_come_back(tmp_path):
    """Logitech's two-level input, as a Dutch 650's television has it: an input sets the
    device's `Screen` - a route to each value - and its `TVInput` - stepped through - and
    power goes off in two codes. A build writes them as variables of their own, and an
    import reads them back as the project said them (corpus_provider's `control_states`)."""
    from afterglow.backends.harmony_650 import compose
    names = ("PowerOn", "PowerOff", "Exit", "TV", "Netflix", "Apps", "VolumeUp")
    tv = {"id": "tv", "label": "TV", "type": "Television",
          "signals": {name: _nec(7, n) for n, name in enumerate(names)},
          "commands": [["VolumeUp", "", "", "", "VolumeUp"]],
          "power_on_cmd": "PowerOn", "power_off_cmd": "Exit", "power_delay": 3000,
          "power_off_steps": ["Exit", "PowerOff"],
          "control_states": [
              {"id": "Screen", "values": ["1", "2", "3"],
               "select": {"1": {"steps": ["TV", {"delay_ms": 2000}]},
                          "2": {"steps": ["Netflix"]}, "3": {"steps": ["Apps"]}}},
              {"id": "TVInput", "values": ["1", "2", "3"], "next": ["TV"]}],
          "inputs": [["Input 1", [{"set": "Screen", "to": "1"}, {"set": "TVInput", "to": "1"}]],
                     ["Input 2", [{"set": "Screen", "to": "1"}, {"set": "TVInput", "to": "3"}]],
                     ["Input 3", [{"set": "Screen", "to": "2"}]]]}
    image = compose.build({"devices": [tv]}, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert _references_out_of_range(image) == []
    payloads.get("blob").unpack(image, str(tmp_path))
    [read] = backend.import_project(str(tmp_path), remotes.get("harmony-650"),
                                    {"name": "t"}).project["devices"]
    assert read["power_off_steps"] == ["Exit", "PowerOff"]
    assert read["inputs"] == [[name, steps] for name, steps in tv["inputs"]]
    assert read["control_states"] == [
        {"id": "Screen", "values": ["1", "2", "3"],
         "select": {"1": {"steps": ["TV", {"delay_ms": 2000}]}, "2": {"steps": ["Netflix"]},
                    "3": {"steps": ["Apps"]}}},
        {"id": "TVInput", "values": ["1", "2", "3"], "next": ["TV"]}]



def test_a_600_is_built_in_its_own_grey_look_and_light_levels():
    """The Harmony 600 runs the 650's firmware program with a grey screen: a build stating
    skin 71 or 73 takes the 600's pictures and light levels (scaffolds/harmony-600, from a
    Polish 600's configuration) and everything else from the 650's scaffold."""
    from afterglow.backends.harmony_650 import assets, compose
    look = json.loads((paths.scaffolds("harmony-600") / "look.json").read_text("utf-8"))
    grey, _notes = assets.load_pictures(paths.scaffolds("harmony-600"),
                                        {"backdrop": look["pictures"]["backdrop"]})

    profile = remotes.get("harmony-650")
    assert profile.looks == {71: "harmony-600", 73: "harmony-600"}

    def built(skin):
        project = dict(_household(), settings={"skin": skin} if skin else {})
        return compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026),
                             look=profile.looks.get(skin))["image"]
    for skin in (71, 73):
        image = built(skin)
        assert _references_out_of_range(image) == []
        assert image[gspm.section_ranges(image)[1][0] + compose.SECTION1_SKIN] == skin
        assert grey["backdrop"]["body"] in image
        # a light's four levels, 1, 3, 5 and 32 where a 650's are 10, 20, 8 and 32
        assert bytes.fromhex("012c00040100030005002000") in image
    image = built(None)
    assert grey["backdrop"]["body"] not in image
    assert bytes.fromhex("012c00040a00140008002000") in image


def test_the_665_is_the_650_under_another_skin(tmp_path):
    """Logitech's own spec pages give the 650 and the 665 one model number, N-10003, and a
    665's configuration is a 650's but for its skin, 75 for 72 - in its header and in
    section 1. One profile lists both, and a build for a 665 says 75 in both places."""
    import dataclasses

    from afterglow import backends
    from afterglow.backends.contracts import BuildContext
    from afterglow.backends.harmony_650 import compose

    profile = remotes.get("harmony-650")
    assert "650" in profile.model and "665" in profile.model
    assert profile.skins == (72, 75, 71, 73, 74)
    for skin in (72, 75):
        header = (f"<INFORMATION><INTENDEDVERSION><PROTOCOL>14</PROTOCOL><SKIN>{skin}</SKIN>"
                  "<FLASH>0x15:0x1C</FLASH><BOARD>1.2.0</BOARD><SOFTWARETYPE>0</SOFTWARETYPE>"
                  "</INTENDEDVERSION></INFORMATION>\r\n").encode()
        assert remotes.identify(header).id == "harmony-650"
    project = {**_household(), "settings": {"skin": 75, "out_file": "665"}}
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    assert image[gspm.section_ranges(image)[1][0] + compose.SECTION1_SKIN] == 75
    promoted = dataclasses.replace(profile, status="experimental")
    context = BuildContext(root=tmp_path, log=lambda _line: None,
                           find_scaffold=lambda _id, _root: None)
    raw = backends.for_profile(promoted).build_project(project, promoted, context) \
        .artifact.read_bytes()
    header, start, size, _checksum = ezhex._split(raw)
    assert remotes.identity_of(header)["skin"] == 75
    assert raw[start:start + size][gspm.section_ranges(raw[start:start + size])[1][0] + 2] == 75
    with pytest.raises(ValueError, match="skin 66"):
        backends.for_profile(promoted).build_project(
            {**project, "settings": {"skin": 66}}, promoted, context)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.name)
def test_a_configurations_firmware_screens_read_as_their_words(path):
    """Readable is not enough: a reader that took a 700's "problem" for "probgem" read
    every glyph. The firmware's screens say the catalogue's words, so each must read
    back as them exactly - but on a configuration in another language, whose screens
    mostly do not (a Dutch 650's), which says nothing about this."""
    payload = _payload(path)
    text = labels.Text(payload)
    screens = ui_index.screen_slots(payload)
    notices = firmware_screens.load_system(paths.scaffolds(_remote(path).id))["notices"]
    pairs = []
    for number, name in notices.items():
        number, words = int(number), catalogue.NOTICES[name]
        if number >= len(screens) or not screens[number]["slots"]:
            continue
        drawn = [item["text"] for item in labels.screen_text(
            payload, screens[number]["slots"][0]["program_offset"], text)]
        for line in words.split("\n"):
            pairs.append((line, line in drawn, drawn))
    if sum(found for _line, found, _drawn in pairs) * 2 < len(pairs):
        pytest.skip("its firmware screens are in another language")
    assert [(line, drawn) for line, found, drawn in pairs if not found] == []


def test_a_700_builds_on_its_own_scaffold_and_reads_back_as_a_650_does(tmp_path):
    """The 700 is data for the arch-14 backend: a build for it takes the 700's scaffold -
    its 49 firmware screens, where the project's own start - and says skin 66; the same
    household reads back from it as from a 650's."""
    from afterglow import backends
    from afterglow.backends.contracts import BuildContext
    from afterglow.backends.harmony_650.compose import TOUR

    read = {}
    for remote in ("harmony-650", "harmony-700"):
        profile = remotes.get(remote)
        context = BuildContext(root=tmp_path, log=lambda _line: None,
                               find_scaffold=lambda name, _root: paths.scaffolds(name))
        project = {**_household(), "settings": {"out_file": remote}}
        raw = backends.for_profile(profile).build_project(project, profile, context) \
            .artifact.read_bytes()
        header, start, size, _checksum = ezhex._split(raw)
        assert remotes.identify(header).id == remote
        image = raw[start:start + size]
        firmware = len(firmware_screens.load_system(paths.scaffolds(remote))["screens"])
        assert len(ui_index.screen_slots(image)) >= firmware + 3 + len(TOUR)
        assert _references_out_of_range(image) == []
        payloads.get("blob").unpack(image, str(tmp_path / remote))
        result = backend.import_project(str(tmp_path / remote), profile, {"name": "t"})
        assert result.project["settings"].pop("remote") == remote
        read[remote] = _by_label(json.loads(json.dumps(result.project, default=str)))
    assert read["harmony-700"] == read["harmony-650"]


@pytest.mark.parametrize("gone, left", [("harmony-650", "harmony-700"),
                                        ("harmony-700", "harmony-650")])
def test_either_arch14_remote_can_be_removed_alone(monkeypatch, gone, left):
    """A remote of this backend is its profile and its scaffold: with one taken away, an
    image is still read against the other's (both carry the same fonts and shapes)."""
    from afterglow.backends.harmony_650 import scaffold as arch14

    everything = remotes.load_all()
    monkeypatch.setattr(remotes, "load_all", lambda *_args: [
        profile for profile in everything if profile.id != gone])
    assert arch14.default_directory() == paths.scaffolds(left)
    monkeypatch.setattr(remotes, "load_all", lambda *_args: [
        profile for profile in everything if profile.backend != arch14.BACKEND])
    with pytest.raises(FileNotFoundError):
        arch14.default_directory()
