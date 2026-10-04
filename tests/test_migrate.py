"""Moving a project to another remote keeps what that remote can do and lists the rest.

The target here is a made-up remote cut down from the Harmony 900's profile - fewer keys,
no touchscreen, no RF, no remote-kept settings, fewer types, an IR backend that cannot
send NEC - so every kind of loss happens at once and each has to be reported.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from afterglow import ir_signal, migrate, remotes


def _small_remote(**changes):
    data = json.loads((remotes.LIBRARY / "harmony-900.json").read_text())
    data.update(id="small", model="Small Remote", status="experimental",
                identity={"arch": 15, "skin": 99})
    data["capabilities"] = {"hard_keys": True}
    vocabulary = data["vocabulary"]
    vocabulary["hard_keys"] = ["VolumeUp", "VolumeDown", "Menu", "SkipForward"]
    vocabulary["hard_key_layout"] = []
    vocabulary["device_types"] = {"Television": "Television",
                                  "HomeAppliance": "Home appliance"}
    vocabulary["activity_types"] = [["Watch TV", "VirtualTelevisionN"],
                                    ["Custom", "VirtualGeneric"]]
    data["properties"]["device"].pop("Dimmer")
    profile = remotes._from_json(data)
    return replace(profile, **changes) if changes else profile


def _nec(command):
    return ir_signal.protocol_signal("nec1", {"address": 1, "command": command})


def _project():
    return {
        "settings": {"remote": "harmony-900", "rf": {
            "receivers": [{"label": "1", "mac": "00:04:20:e0:00:0b:82:7b"}],
            "assign": {"2": "1:0"}}, "sound": "1", "first_name": "A"},
        "devices": [
            {"schema": "afterglow-project-device/1", "id": "1", "label": "TV",
             "type": "Television", "mfr": "T", "model": "M",
             "commands": [["VolumeUp", "VolumeUp", "", "", "VolumeUp"],
                          ["Next", "Next", "", "", "Skip"],
                          ["Guide", "Guide", "", "", "Guide"]],
             "signals": {"VolumeUp": _nec(1), "Next": _nec(2), "Guide": _nec(3)},
             "properties": {"IsDisplayDevice": "true", "PressPreSilence": "0"}},
            {"schema": "afterglow-project-device/1", "id": "2", "label": "Lamp",
             "type": "Light", "mfr": "T", "model": "L",
             "commands": [["On", "On", "", "", None]], "signals": {"On": _nec(4)},
             "properties": {"Dimmer": "false"}},
        ],
        "activities": [{
            "id": "10", "label": "Watch", "type": "VirtualDvd", "display": "1",
            "control": "1", "hard_macros": {"Guide": [["command", "1", "Guide"]],
                                            "Menu": [["command", "1", "Next"]]},
            "soft_buttons": [["Lamp on", "2", "On"]], "bound_keys": ["Guide", "Menu"]}],
    }


def _changes(report, subject):
    return [row for row in report if row["subject"] == subject]


def test_the_original_project_is_left_as_it_was():
    project = _project()
    before = deepcopy(project)
    migrated, _report = migrate.migrate(project, _small_remote())
    assert project == before
    assert migrated["settings"]["remote"] == "small"


def test_every_loss_is_in_the_report():
    migrated, report = migrate.migrate(_project(), _small_remote())
    tv, watch = migrated["devices"][0], migrated["activities"][0]

    # an old key name is renamed first, so it survives under the name the remote uses
    assert [row["change"] for row in _changes(report, "Physical keys")] == ["renamed"]
    assert tv["commands"][1][4] == "SkipForward"
    # a key the remote does not have loses its binding, and says so
    assert tv["commands"][2][4] is None
    assert "Guide" not in watch["hard_macros"] and watch["bound_keys"] == ["Menu"]
    # types it lacks fall back to the most generic one it has
    assert migrated["devices"][1]["type"] == "HomeAppliance"
    assert watch["type"] == "VirtualGeneric"
    # no touchscreen, no RF, no remote-kept settings
    assert "soft_buttons" not in watch
    assert migrated["settings"]["rf"] == "front"
    assert "sound" not in migrated["settings"] and migrated["settings"]["first_name"] == "A"
    # a property the source has and the target lacks goes; one nobody catalogues stays
    assert "Dimmer" not in migrated["devices"][1]["properties"]
    assert tv["properties"]["PressPreSilence"] == "0"
    assert {row["change"] for row in report} == {"renamed", "substituted", "removed"}
    assert all(row["detail"] for row in report)


def test_commands_the_target_cannot_send_go_with_whatever_sends_them():
    target = _small_remote(infrared={"native_protocols": [], "waveform": None},
                           capabilities={"hard_keys": True, "touchscreen": True})
    migrated, report = migrate.migrate(_project(), target)
    assert all(not device["signals"] for device in migrated["devices"])
    assert all(not device["commands"] for device in migrated["devices"])
    watch = migrated["activities"][0]
    assert watch["hard_macros"] == {} and watch["soft_buttons"] == []
    lost = [row["detail"] for row in report if row["detail"].startswith("command ")]
    assert len(lost) == 4


def test_a_remote_that_cannot_be_built_for_is_refused():
    with pytest.raises(remotes.NotBuildable):
        migrate.migrate(_project(), _small_remote(status=remotes.READ_ONLY))


def test_migrating_to_the_same_remote_changes_nothing_a_user_made(configs, unpacked):
    """A real imported project moved to the remote it came from is the identity."""
    from afterglow.importer import build_project
    project = build_project(str(unpacked(configs[0])))
    migrated, report = migrate.migrate(project, remotes.get("harmony-900"))
    assert report == []
    assert migrated == project


# the interface
def test_the_remote_is_shown_above_the_tabs_and_not_set_on_one(qapp_or_skip):
    from afterglow.gui.remote_bar import RemoteBar
    from afterglow.gui.tabs import SettingsTab
    assert not hasattr(SettingsTab({"settings": {}}), "remote")
    bar = RemoteBar()
    bar.set_profile(remotes.get("harmony-900"))
    assert "Harmony 900" in bar.name.text() and "verified" in bar.status.text()
    bar.set_profile(_small_remote())
    assert "experimental" in bar.status.text() and "test write" in bar.note.text()


def test_the_review_lists_every_change_by_what_it_happens_to(qapp_or_skip):
    from afterglow.gui.remote_bar import MigrationDialog
    _migrated, report = migrate.migrate(_project(), _small_remote())
    dialog = MigrationDialog(remotes.get("harmony-900"), _small_remote(), report)
    shown = sum(dialog.tree.topLevelItem(i).childCount()
                for i in range(dialog.tree.topLevelItemCount()))
    assert shown == len(report)
    assert dialog.save.text() == "Save as new project…"
