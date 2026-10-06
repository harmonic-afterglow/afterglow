"""What the interface shows is the remote's profile's to say, and nothing is assumed.

Models differ in more than their keys and properties: one has no activities, another no
RF blasters, another keeps different settings files. A profile's `interface` section
names the tabs, editor pages, settings rows and languages its remote has, its
`preferences` section defines the remote's own settings, and a profile that does not say
is refused rather than given the Harmony 900's answer.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from afterglow import preferences, remotes


def _900_json() -> dict:
    return json.loads((remotes.LIBRARY / "harmony-900.json").read_text())


def _profile(**interface_changes) -> remotes.RemoteProfile:
    data = _900_json()
    data.update(id="test-model", model="Test Model", identity={"arch": 15, "skin": 99})
    data["interface"].update(interface_changes)
    return remotes._from_json(data)


# the profile has to say
def test_a_profile_without_an_interface_is_refused():
    data = _900_json()
    del data["interface"]
    with pytest.raises(ValueError, match="no interface section"):
        remotes._from_json(data)


@pytest.mark.parametrize("key", ["tabs", "device_pages", "activity_pages", "settings",
                                 "languages"])
def test_every_part_of_the_interface_is_required(key):
    data = _900_json()
    del data["interface"][key]
    with pytest.raises(ValueError, match=key):
        remotes._from_json(data)


def test_an_unknown_page_is_refused_not_ignored():
    data = _900_json()
    data["interface"]["device_pages"].append("telepathy")
    with pytest.raises(ValueError, match="telepathy"):
        remotes._from_json(data)


def test_a_page_nothing_works_without_cannot_be_left_out():
    data = _900_json()
    data["interface"]["device_pages"].remove("commands")
    with pytest.raises(ValueError, match="commands"):
        remotes._from_json(data)


def test_preferences_offered_and_defined_agree():
    data = _900_json()
    data["preferences"] = {}
    with pytest.raises(ValueError, match="defines none"):
        remotes._from_json(data)
    data = _900_json()
    data["interface"]["settings"].remove("preferences")
    with pytest.raises(ValueError, match="does not offer them"):
        remotes._from_json(data)


def test_every_shipped_profile_describes_its_interface():
    """Loading drops a broken profile with a warning; none of ours may be one."""
    shipped = {path.stem for path in remotes.LIBRARY.glob("*.json")} - {"models"}
    assert {profile.id for profile in remotes.load_all()} == shipped


def test_the_interface_survives_a_round_trip_through_json():
    profile = remotes.get("harmony-900")
    again = remotes._from_json(profile.to_json())
    assert again.tabs == profile.tabs
    assert again.device_pages == profile.device_pages
    assert again.activity_pages == profile.activity_pages
    assert again.preferences == profile.preferences


# the interface follows it
@pytest.fixture
def remote(monkeypatch):
    """Install a test profile under the id `test-model`."""
    installed = {}
    real_get = remotes.get

    def get(profile_id, *args, **kwargs):
        if profile_id == "test-model":
            return installed["profile"]
        return real_get(profile_id, *args, **kwargs)
    monkeypatch.setattr(remotes, "get", get)

    def install(profile):
        installed["profile"] = profile
        return {"settings": {"remote": "test-model"}, "devices": [], "activities": []}
    return install


def test_a_remote_without_activities_has_no_activities_tab(qapp_or_skip, remote):
    from afterglow.gui.app import MainWindow
    window = MainWindow()
    project = remote(_profile(tabs=["devices", "settings", "flash"]))
    window.project.clear()
    window.project.update(project)
    window._reload_tabs()
    visible = {window.tabs.tabText(i) for i in range(window.tabs.count())
               if window.tabs.isTabVisible(i)}
    assert visible == {"Devices", "Remote Settings", "Flash"}
    window._dirty = False


def test_the_device_editor_shows_only_the_listed_pages(qapp_or_skip, remote):
    from afterglow.gui.device_wizard import DeviceEditor
    project = remote(_profile(device_pages=["identity", "commands"]))
    editor = DeviceEditor([], existing={"id": "1", "label": "TV"}, project=project)
    assert [editor.tabs.tabText(i) for i in range(editor.tabs.count())] == \
        ["Identity", "Commands"]


def test_a_hidden_page_keeps_what_the_device_had(qapp_or_skip, remote):
    """Leaving the Timing page out must not reset the device's timing."""
    from afterglow import ir_signal
    from afterglow.gui.device_wizard import DeviceEditor
    project = remote(_profile(device_pages=["identity", "commands"]))
    device = {"schema": "afterglow-project-device/1", "id": "1", "label": "TV",
              "type": "Television", "mfr": "T", "model": "M",
              "commands": [["PowerToggle", "PowerToggle", "", "", None]],
              "signals": {"PowerToggle": ir_signal.protocol_signal(
                  "nec1", {"address": 1, "command": 1})},
              "power_delay": 4321, "press_presilence": 250}
    spec = DeviceEditor([], existing=device, project=project)._collect()
    assert spec["power_delay"] == 4321 and spec["press_presilence"] == 250


def test_the_activity_editor_shows_only_the_listed_pages(qapp_or_skip, remote):
    from afterglow.gui.activity_wizard import ActivityEditor
    profile = _profile(activity_pages=["identity", "roles", "power"])
    remote(profile)
    editor = ActivityEditor([], existing={"id": "1001", "label": "Watch"}, remote=profile)
    assert [editor.tabs.tabText(i) for i in range(editor.tabs.count())] == \
        ["Identity", "Roles", "Power"]


def test_the_activity_wizard_collects_by_page_not_by_position(qapp_or_skip, remote):
    """It used to take the first seven pages in order, so leaving one out would have
    read the wrong page's values."""
    from afterglow.gui.activity_wizard import ActivityWizard
    profile = _profile(activity_pages=["identity", "roles"])
    remote(profile)
    existing = {"id": "1001", "label": "Watch", "hard_macros": {"Menu": [["command", "1",
                                                                         "Menu"]]}}
    wizard = ActivityWizard([], existing=existing, remote=profile)
    assert len(wizard.pageIds()) == 2
    assert wizard._collect()["hard_macros"] == existing["hard_macros"]


def test_remote_settings_show_only_what_the_remote_has(qapp_or_skip, remote):
    from afterglow.gui.tabs import SettingsTab
    data = _900_json()
    data.update(id="test-model", model="Test Model", identity={"arch": 15, "skin": 99})
    data["interface"]["settings"] = ["output_file", "language", "preferences"]
    data["interface"]["languages"] = [["Deutsch", "deu"]]
    data["preferences"] = {"volume": {"file": "system_volume.dat", "label": "Volume",
                                      "default": "5", "range": [0, 20]}}
    tab = SettingsTab(remote(remotes._from_json(data)))
    assert not tab.form.isRowVisible(tab.first_name)
    assert not tab.form.isRowVisible(tab.blaster_row)
    assert [tab.locale.itemText(i) for i in range(tab.locale.count())] == ["Deutsch"]
    assert list(tab.prefs) == ["volume"]
    assert tab.prefs["volume"].value() == 5


def test_changing_the_remote_rebuilds_its_settings(qapp_or_skip, remote):
    from afterglow.gui.tabs import SettingsTab
    project = remote(replace(_profile(), id="test-model"))
    tab = SettingsTab(project)
    assert "theme" in tab.prefs
    project["settings"]["remote"] = "harmony-900"
    data = _900_json()
    data.update(id="test-model", identity={"arch": 15, "skin": 99})
    data["preferences"] = {"volume": {"file": "system_volume.dat", "label": "Volume",
                                      "default": "5", "range": [0, 20]}}
    remote(remotes._from_json(data))
    project["settings"]["remote"] = "test-model"
    tab._profile_id = None                       # as a migration to another id would
    tab.refresh()
    assert list(tab.prefs) == ["volume"]


def test_a_build_writes_only_the_preferences_its_remote_defines(tmp_path):
    profile = _profile()
    (tmp_path / "platformconfig").mkdir()
    written = preferences.apply(str(tmp_path), {"theme": "2", "volume": "9"}, profile)
    assert written == ["system_theme.dat"]


# one remote, several skin numbers
def test_a_remote_sold_under_another_skin_number_is_the_same_remote():
    data = _900_json()
    data["identity"]["other_skins"] = [64]
    profile = remotes._from_json(data)
    assert profile.skins == (61, 64)
    assert profile.matches({"arch": 15, "skin": 64})
    assert not profile.matches({"arch": 15, "skin": 65})
    assert remotes._from_json(profile.to_json()).skins == (61, 64)
