"""An activity's Sound and Picture layouts, listed under it on the Activities tab and each
edited in a window of its own: the device, the keys it takes over, its screen buttons.
Edited on the activity's own button pages, its keys read as the activity's."""
from __future__ import annotations

import copy

import pytest

from afterglow import activity_layouts, project_devices, remotes

DEVICES = [
    {"id": "tv", "label": "TV", "type": "Television", "commands": [
        ["VolumeUp", "VolumeUp", "", "", "VolumeUp"], ["Mute", "Mute", "", "", "VolumeMute"],
        ["Select", "Select", "", "", "Select"], ["Guide", "Guide", "", "", "Guide"],
        ["Menu", "Menu", "", "", "Menu"]]},
    {"id": "amp", "label": "Receiver", "type": "AudioReceiver", "commands": [
        ["VolumeUp", "VolumeUp", "", "", "VolumeUp"],
        ["VolumeDown", "VolumeDown", "", "", "VolumeDown"],
        ["Mute", "Mute", "", "", "VolumeMute"]]},
    {"id": "dvd", "label": "DVD", "type": "DVD", "commands": [
        ["Select", "Select", "", "", "Select"]]},
]
WATCH = {"id": "1", "label": "Watch TV", "display": "tv", "volume": "amp", "control": "tv"}
MUSIC = {"id": "2", "label": "Listen to Music", "volume": "amp", "control": "amp"}


def _project(*activities, remote="harmony-555", skin=48):
    return {"devices": copy.deepcopy(DEVICES), "activities": copy.deepcopy(list(activities)),
            "settings": {"remote": remote, "skin": skin}}


@pytest.mark.parametrize("remote, kinds", [
    ("harmony-555", ("sound", "picture")), ("harmony-550", ("sound", "picture")),
    ("harmony-525", ()), ("harmony-900", ())])
def test_which_remotes_have_layouts(remote, kinds):
    assert remotes.get(remote).layout_kinds() == kinds


def test_a_skin_without_the_keys_has_none(monkeypatch):
    """The 688's 675 shares its profile but has no Sound and Picture keys."""
    import dataclasses
    profile = remotes.get("harmony-555")
    bare = dataclasses.replace(profile, interface={**profile.interface,
                                                   "skins_without_layouts": [48]})
    assert bare.layout_kinds(48) == ()
    assert bare.layout_kinds("48") == ()
    assert bare.layout_kinds(None) == ("sound", "picture")


def test_the_row_says_device_default_and_keys():
    from afterglow.gui.activity_layouts_dialog import summary
    assert summary(WATCH, DEVICES, "sound") == ("Receiver (default) - 3 keys", True)
    assert summary(MUSIC, DEVICES, "picture") == ("none - no display in this activity",
                                                  False)
    changed = dict(MUSIC, layouts={"picture": {"device": "tv"}})
    text, has = summary(changed, DEVICES, "picture")
    assert has and text.startswith("TV (changed)")


def _card_rows(card):
    return {kind: button.text() for kind, button in card.layout_buttons.items()}


def test_the_layouts_hang_under_their_activity(qapp_or_skip):
    from afterglow.gui.tabs import ActivitiesTab
    tab = ActivitiesTab(_project(WATCH, MUSIC))
    assert _card_rows(tab.cards.card(0)) == {"sound": "Edit", "picture": "Edit"}
    assert _card_rows(tab.cards.card(1)) == {"sound": "Edit", "picture": "Add"}


def test_no_layout_rows_on_a_remote_without_the_keys(qapp_or_skip):
    from afterglow.gui.tabs import ActivitiesTab
    tab = ActivitiesTab(_project(WATCH, remote="harmony-525", skin=None))
    assert _card_rows(tab.cards.card(0)) == {}


def test_picture_given_to_a_device_the_activity_does_not_use(qapp_or_skip):
    """No display, and still a use for the key: any device of the project, said to be
    outside the activity, with that device's own keys."""
    from afterglow.gui.activity_layouts_dialog import LayoutDialog
    dialog = LayoutDialog(MUSIC, DEVICES, "picture", remote=remotes.get("harmony-555"))
    assert dialog.layouts.layout("picture") is None
    assert not dialog.keys.table.isEnabled()
    dialog.device.setCurrentIndex(dialog.device.findData("tv"))
    dialog._device_chosen(dialog.device.currentIndex())
    assert "does not turn TV on" in dialog.note.text()
    assert dialog.keys.table.isEnabled()
    assert set(dialog.keys.macros) == {"Select", "Guide"}
    activity = copy.deepcopy(MUSIC)
    dialog.apply(activity)
    assert activity["layouts"] == {"picture": {"device": "tv"}}
    assert activity_layouts.resolve(activity, DEVICES)["picture"]["device"] == "tv"


def test_a_key_changed_in_the_window_is_the_layouts(qapp_or_skip):
    """And the activity's own keys are left as they were."""
    from afterglow.gui.activity_layouts_dialog import LayoutDialog
    dialog = LayoutDialog(WATCH, DEVICES, "sound", remote=remotes.get("harmony-555"))
    page = dialog.keys
    assert page._says("Guide").startswith("The activity's")
    page.macros["Guide"] = [["command", "amp", "Mute"]]
    page._changed()
    activity = copy.deepcopy(WATCH)
    dialog.apply(activity)
    assert activity["layouts"]["sound"]["hard_macros"]["Guide"] == [
        ["command", "amp", "Mute"]]
    assert "hard_macros" not in activity


def test_no_sound_layout_and_back_to_default(qapp_or_skip):
    from afterglow.gui.activity_layouts_dialog import LayoutDialog
    dialog = LayoutDialog(WATCH, DEVICES, "sound", remote=remotes.get("harmony-555"))
    dialog._device_chosen(dialog.device.findData(None))
    assert dialog.layouts.layout("sound") is None
    assert dialog.reset.isEnabled()
    activity = copy.deepcopy(WATCH)
    dialog.apply(activity)
    assert activity["layouts"] == {"sound": {"device": None}}
    dialog.reset.click()
    dialog.apply(activity)
    assert "layouts" not in activity


def test_the_tab_keeps_what_the_window_saved(qapp_or_skip, monkeypatch):
    from afterglow.gui import activity_layouts_dialog
    from afterglow.gui.tabs import ActivitiesTab

    def save(self):
        self.layouts.set_device(self.kind, "tv")
        return True
    monkeypatch.setattr(activity_layouts_dialog.LayoutDialog, "exec", save)
    project = _project(MUSIC)
    tab = ActivitiesTab(project)
    seen = []
    tab.changed.connect(lambda: seen.append(1))
    tab.edit_layout(0, "picture")
    assert project["activities"][0]["layouts"] == {"picture": {"device": "tv"}}
    assert seen and _card_rows(tab.cards.card(0))["picture"] == "Edit"


def test_removing_the_device_a_layout_was_given_to():
    project = _project(dict(MUSIC, layouts={"picture": {"device": "dvd"}}))
    said = project_devices.remove_device(project, "dvd")
    assert "layouts" not in project["activities"][0]
    assert any("Picture layout" in line for line in said)


@pytest.mark.slow
def test_a_layout_on_a_device_outside_the_activity_builds(tmp_path):
    import contextlib
    import io
    from pathlib import Path
    from afterglow.build_service import ConfigBuildService
    from test_harmony_one_activities import PROJECT
    project = copy.deepcopy(PROJECT)
    tv = project["devices"][0]["id"]
    music = next(a for a in project["activities"] if not a.get("display"))
    music["layouts"] = {"picture": {"device": tv}}
    project["settings"] = {"remote": "harmony-555", "out_file": str(tmp_path / "o.ezhex")}
    root = Path(__file__).resolve().parents[1]
    with contextlib.redirect_stdout(io.StringIO()):
        built = ConfigBuildService(root, lambda _m: None).build(project)
    assert Path(built).stat().st_size > 0


def test_the_row_says_which_keys_its_counts_are():
    """"3 keys - 6 buttons" was not explained anywhere."""
    from afterglow.gui.activity_layouts_dialog import details
    said = details(WATCH, DEVICES, "sound")
    assert said.startswith("After Sound is pressed, it takes over: Volume Down")
    assert "Volume Mute" in said and "Volume Up" in said
    assert details(MUSIC, DEVICES, "picture") == "Picture does nothing in this activity."


def test_the_device_page_says_what_each_layout_takes_by_default(qapp_or_skip):
    """Picture taking the arrows, OK, Exit, Info and Guide surprised a tester; so did
    Sound taking the menu keys once Picture was given to the same device."""
    from afterglow.gui.activity_layouts_dialog import LayoutDialog
    sound = LayoutDialog(WATCH, DEVICES, "sound", remote=remotes.get("harmony-555"))
    assert "menu keys" in sound.device_page.subTitle()
    picture = LayoutDialog(WATCH, DEVICES, "picture", remote=remotes.get("harmony-555"))
    assert "the arrows, OK, Exit, Info and Guide" in picture.device_page.subTitle()
