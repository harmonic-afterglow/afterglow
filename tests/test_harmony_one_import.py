"""Reading a Harmony One configuration back into a project.

A generated image is the test bed: what was put in is known, so what is read back can be
compared field by field. Logitech's own configurations are read the same way; the ones
the maintainer has are checked when present (configs/one/), and skipped otherwise.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from afterglow.backends.harmony_one import generate, labels, ui_index

from test_harmony_one_activities import PROJECT

ROOT = Path(__file__).resolve().parents[1]
ONE_CONFIGS = sorted((ROOT / "configs" / "one").glob("*.ezhex")) if (
    ROOT / "configs" / "one").is_dir() else []


@pytest.fixture(scope="module")
def built():
    return generate.build(PROJECT)


def _all_text(image) -> tuple[set[str], labels.Text]:
    text = labels.Text(image)
    out = set()
    for screen in ui_index.screen_slots(image):
        for slot in screen["slots"]:
            out |= {item["text"] for item in labels.screen_text(
                image, slot["program_offset"], text)}
    return out, text


def test_every_label_a_build_draws_reads_back_by_the_shape_of_its_glyphs(built):
    # Each font slot numbers its own characters from 1, so a code means nothing across
    # fonts; the glyphs' shapes are what say which character each is.
    drawn, text = _all_text(built["image"])
    assert text.unknown == 0
    for device in PROJECT["devices"]:
        assert device["label"] in drawn
        # a command on a key is not on the device's pages, as on Logitech's
        keyed = {entry[0] for entry in device.get("commands") or [] if entry[4]}
        assert {name for name in device["signals"]
                if len(name) < 9 and name not in keyed} <= drawn
    assert {"Watch TV", "Listen to Music"} <= drawn


def test_a_shape_two_characters_share_is_the_one_the_image_has_no_other_code_for():
    # Logitech's faces draw a capital I and a small l alike in some sizes; the image gives
    # each character one code, so the code another font reads as l leaves the other one I.
    fonts, shared = labels.read_fonts([{7: "l", 8: "Il"}, {7: "Il", 8: "Il"}])
    assert fonts == [{7: "l", 8: "I"}, {7: "l", 8: "I"}]
    assert shared == {7: "l"}
    # with nothing to tell them apart, it stays unread rather than guessed
    fonts, _shared = labels.read_fonts([{8: "Il"}])
    assert fonts == [{}]


@pytest.mark.parametrize("path", ONE_CONFIGS, ids=lambda path: path.name)
def test_a_logitech_configuration_s_text_reads_back_whatever_its_glyph_layout(path, tmp_path):
    from afterglow import ezhex

    ezhex.unpack(str(path), str(tmp_path))
    drawn, text = _all_text((tmp_path / "payload.bin").read_bytes())
    assert text.unknown == 0
    assert drawn


def _imported(image: bytes, tmp_path) -> dict:
    """Import an image as the app does: through its container and the backend."""
    from afterglow import ezhex, importer, payloads, remotes

    profile = remotes.get("harmony-one")
    source = tmp_path / "source"
    payloads.get(profile.payload).unpack(image, str(source))
    (source / ".ezhex_header").write_bytes(ezhex.header_for_profile(profile))
    return importer.import_result(source).project


def test_a_device_comes_back_with_its_names_power_inputs_and_keys(built, tmp_path):
    project = _imported(built["image"], tmp_path)
    tv, amp = project["devices"]
    assert (tv["label"], amp["label"]) == ("Living Room TV", "Receiver")
    # every command a page shows is named by its button; one on a key is on no page, as
    # on Logitech's, and is named by its key; held codes have no button
    keyed = {entry[0]: entry[4] for entry in PROJECT["devices"][0]["commands"] if entry[4]}
    source = {keyed.get(name, name) for name in PROJECT["devices"][0]["signals"]}
    assert source <= set(tv["signals"])
    assert (tv["power_on_cmd"], tv["power_off_cmd"], tv["power_delay"]) == (
        "PowerOn", "PowerOff", 3000)
    assert (amp["power_cmd"], amp["power_delay"]) == ("Power", 2000)
    assert [command for _name, command in tv["inputs"]] == ["InputHdmi1", "InputHdmi2"]
    assert [command for _name, command in amp["inputs"]] == ["InputCd", "InputTv"]
    # a device page's physical keys, as the project's hard slots
    slots = {entry[0]: entry[4] for entry in tv["commands"]}
    assert slots["VolumeUp"] == ["VolumeUp"]
    assert slots["VolumeMute"] == ["VolumeMute"]
    assert slots["Number1"] == ["Number1"]
    assert slots["PowerOn"] is None
    # and only what a page shows keeps a label
    labels = {entry[0]: entry[1] for entry in tv["commands"]}
    assert (labels["Guide"], labels["PowerOn"], labels["Number1"]) == ("", "PowerOn", "")


def test_an_activity_comes_back_with_what_it_turns_on_sets_binds_and_shows(built, tmp_path):
    project = _imported(built["image"], tmp_path)
    tv, amp = (device["id"] for device in project["devices"])
    watch, music = project["activities"]
    assert (watch["label"], music["label"]) == ("Watch TV", "Listen to Music")
    assert watch["power_on_devices"] == [tv, amp]
    assert watch["enter"] == [["input", tv, "InputHdmi1"], ["input", amp, "InputTv"]]
    assert (watch["control"], watch["volume"]) == (tv, amp)
    # the keys the roles route, and the one bound on purpose
    assert {"VolumeUp", "Guide", "Info"} <= set(watch["bound_keys"])
    assert watch["hard_macros"] == {"Info": [["command", tv, "Number1"],
                                             ["command", tv, "Number2"]]}
    assert watch["soft_buttons"] == [
        ["Guide", tv, "Guide"],
        {"label": "Movie", "macro": [["command", tv, "Menu"], ["delay", tv, 500],
                                     ["command", tv, "Select"]]}]
    assert music["power_on_devices"] == [amp]
    assert music["enter"] == [["input", amp, "InputCd"]]


def test_a_favourite_channel_comes_back_dialled_and_confirmed(tmp_path):
    from test_harmony_one_activities import AMP, FAVOURITES, TV

    project = {**FAVOURITES, "devices": [dict(TV, press_interkey=300), AMP]}
    imported = _imported(generate.build(project)["image"], tmp_path)
    watch = imported["activities"][0]
    assert watch["image_buttons"] == [["BBC One", "channel", "12", None],
                                      ["News", "channel", "2", None]]
    assert watch["channel_confirm"] == "Select"
    assert imported["devices"][0]["press_interkey"] == 300


def _comparable(project: dict) -> dict:
    # a build numbers commands in name order, so a command renamed after its key moves
    return {
        "devices": [{key: sorted(device[key]) if key == "commands" else device.get(key)
                     for key in (
            "label", "commands", "power_cmd", "power_on_cmd", "power_off_cmd", "power_delay",
            "inputs", "input_cycle", "press_interkey")} for device in project["devices"]],
        "activities": [{key: value for key, value in activity.items() if key != "id"}
                       for activity in project["activities"]],
    }


def test_a_project_read_back_builds_the_project_it_was_read_from(built, tmp_path):
    # What an import reads is what a build of it writes: reading that build back gives
    # the same project again.
    first = _imported(built["image"], tmp_path / "first")
    second = _imported(generate.build(first)["image"], tmp_path / "second")
    assert _comparable(second) == _comparable(first)


def test_a_favourite_s_logo_is_saved_and_composes_back_the_same(tmp_path):
    # A favourite with a logo and no name: its logo is saved to the owner's logos folder
    # and the project names it there, so building the import draws the same button.
    from afterglow import imaging, paths
    from afterglow.backends.harmony_one import importing
    from test_harmony_one_activities import FAVOURITES

    logo = tmp_path / "star.png"
    logo.write_bytes(imaging.encode(
        [[(255, 200, 0, 255) if (x - 15) ** 2 + (y - 15) ** 2 < 150 else (0, 0, 0, 0)
          for x in range(30)] for y in range(30)]))
    project = {**FAVOURITES, "activities": [dict(
        FAVOURITES["activities"][0], image_buttons=[["Star", "channel", "12", str(logo)]],
        channel_confirm="Select")] + FAVOURITES["activities"][1:]}
    first = generate.build(project)["image"]
    imported = _imported(first, tmp_path / "first")
    [[name, kind, number, image]] = imported["activities"][0]["image_buttons"]
    assert (kind, number) == ("channel", "12")
    assert (paths.logos_dir() / image).is_file()
    second = generate.build(imported)["image"]

    def drawn(image):
        reader = importing.Image(image)
        return [picture for screen in reader.screens for slot in screen["slots"]
                for picture in [importing.Activities(reader, [], {}, [])._logo(slot, 0)]
                if picture and any(item["text"] == "Watch TV"
                                   for item in reader.page_text(slot["program_offset"]))]
    assert drawn(second) and drawn(second)[0] == drawn(first)[0]


def test_a_held_step_comes_back_held_as_long(tmp_path):
    # A held step is a record of its own - the code repeated for the hold - which reads
    # back as its command held that long, not as a command of its own.
    project = {**PROJECT, "activities": [dict(PROJECT["activities"][0], soft_buttons=[
        {"label": "Quieter", "macro": [["command", "amp", "VolumeUp", "Press", 1500]]}])]}
    imported = _imported(generate.build(project)["image"], tmp_path)
    amp = imported["devices"][1]["id"]
    [button] = imported["activities"][0]["soft_buttons"]
    assert button == {"label": "Quieter", "macro": [["command", amp, "VolumeUp", "Press", 1500]]}
    assert not any(name.startswith("Command ") for name in imported["devices"][1]["signals"])


def test_an_input_chosen_in_several_steps_is_sent_and_read_back_whole(tmp_path):
    # Some devices choose an input in steps - wake, step there, confirm - which a project
    # gives as the input's sequence, as the other remotes' builders take it.
    from test_harmony_one_activities import AMP, TV

    amp = dict(AMP, inputs=[["CD", ["Power", {"delay_ms": 500}, "InputCd"]],
                            ["TV", "InputTv"]])
    project = {**PROJECT, "devices": [TV, amp]}
    imported = _imported(generate.build(project)["image"], tmp_path)
    assert imported["devices"][1]["inputs"] == [
        ["Input 1", ["Power", {"delay_ms": 500}, "InputCd"]], ["InputTv", "InputTv"]]
    # and building the import sends the same sequence again
    again = _imported(generate.build(imported)["image"], tmp_path / "again")
    assert again["devices"][1]["inputs"] == imported["devices"][1]["inputs"]


def test_a_type_is_read_from_the_icon_its_menu_row_draws(built, tmp_path):
    project = _imported(built["image"], tmp_path)
    assert [device["type"] for device in project["devices"]] == ["Television", "Amplifier"]
    assert [activity["type"] for activity in project["activities"]] == [
        "VirtualTelevisionN", "VirtualCdMulti"]


def test_an_imported_one_is_learned_into_the_library_even_with_inputs_without_commands(
        tmp_path):
    # An input no command selects is `[name]` alone, which a project may hold; learning the
    # import into the library refused the whole configuration over it.
    from afterglow import library
    from test_harmony_one_activities import AMP, TV

    tv = dict(TV, inputs=[["HDMI1", "InputHdmi1"], ["Antenna"]])
    imported = _imported(generate.build({**PROJECT, "devices": [tv, AMP]})["image"], tmp_path)
    learned = library.learn(imported, tmp_path, library=tmp_path / "library")
    assert learned


def test_an_activity_s_display_is_the_device_it_switches_on_that_shows_a_picture(tmp_path):
    # the receiver is the control; the television is still what is watched
    project = {**PROJECT, "activities": [dict(PROJECT["activities"][0], control="amp")]}
    imported = _imported(generate.build(project)["image"], tmp_path)
    tv = imported["devices"][0]["id"]
    assert imported["activities"][0]["display"] == tv


def test_a_build_s_look_alikes_are_read_in_their_own_font_not_by_other_fonts_codes(tmp_path):
    # A build numbers each font's characters from 1, so a code another font reads alone
    # says nothing about this one: "One" in a title once read "ane", and "PwrOff" "Pwrwff".
    from test_harmony_one_activities import _nec

    names = ("PwrOff", "PwrOn", "Xbox360Guide", "View", "A", "B")
    project = {"devices": [{"id": "x", "label": "Xbox One", "type": "GameConsole",
                            "signals": {name: _nec(9, n) for n, name in enumerate(names)},
                            "commands": [[name, name, "", "", None] for name in names]}]}
    imported = _imported(generate.build(project)["image"], tmp_path)
    [device] = imported["devices"]
    assert device["label"] == "Xbox One"
    assert set(names) <= set(device["signals"])
