"""A device taken out of a project takes what points at it along, and says what; and the
900's and 1100's builder refuses a project naming a device or command that is not there,
as the other remotes' do, instead of writing a key that does nothing."""
from __future__ import annotations

import contextlib
import copy
import io
from pathlib import Path

import pytest

from afterglow import ir_signal, project_devices
from afterglow.backends.harmony_pk.builder import references

ROOT = Path(__file__).resolve().parents[1]


def _device(did, label, *names):
    return {"schema": "afterglow-project-device/1", "id": did, "label": label,
            "type": "Television", "mfr": "Test", "model": label,
            "commands": [[name, name, "", "", None] for name in names],
            "signals": {name: ir_signal.protocol_signal(
                "nec1", {"address": 4, "command": 8 + i}) for i, name in enumerate(names)}}


def _household():
    tv = _device("tv", "TV", "PowerToggle", "InputHdmi1", "VolumeUp")
    bd = _device("bd", "Blu-ray", "PowerToggle", "Play", "Pause", "Select")
    tv["power_cmd"] = bd["power_cmd"] = "PowerToggle"
    movie = {"id": "a1", "label": "Watch a Movie", "type": "VirtualDvd",
             "display": "tv", "control": "bd", "volume": "tv",
             "enter": [["input", "tv", "HDMI1"], ["command", "bd", "Play"]],
             "hard_macros": {"Red": [["command", "bd", "Pause"]],
                             "Green": [["command", "tv", "VolumeUp"],
                                       ["command", "bd", "Pause"]]},
             "soft_buttons": [{"label": "Play", "device": "bd", "command": "Play"},
                              ["Louder", "tv", "VolumeUp"],
                              {"label": "Both", "macro": [["command", "bd", "Play"]]}],
             "image_buttons": [["Pause it", "command", ["bd", "Pause"], None],
                               ["BBC", "channel", "101", None]],
             "channel_confirm": "Select",
             "power_on_devices": ["tv", "bd"]}
    tv_only = {"id": "a2", "label": "Watch TV", "display": "tv", "control": "tv"}
    return {"settings": {"remote": "harmony-900"}, "devices": [tv, bd],
            "activities": [movie, tv_only], "power_off_all": ["tv", "bd"]}


def test_removing_a_device_takes_what_points_at_it_and_says_so():
    project = _household()
    said = project_devices.remove_device(copy.deepcopy(project), "bd")
    assert said == project_devices.remove_device(project, "bd")
    assert len(said) == 1 and said[0].startswith("Watch a Movie: ")
    assert [d["id"] for d in project["devices"]] == ["tv"]
    assert project["power_off_all"] == ["tv"]
    movie, tv_only = project["activities"]
    assert movie["control"] is None and "channel_confirm" not in movie
    assert movie["enter"] == [["input", "tv", "HDMI1"]]
    assert movie["hard_macros"] == {"Green": [["command", "tv", "VolumeUp"]]}
    # a button's place stays, empty, so the ones after it stay where they were
    assert movie["soft_buttons"] == [None, ["Louder", "tv", "VolumeUp"]]
    assert movie["image_buttons"] == [["BBC", "channel", "101", None]]
    assert movie["power_on_devices"] == ["tv"]
    assert tv_only == {"id": "a2", "label": "Watch TV", "display": "tv", "control": "tv"}
    references.check(project["devices"], project["activities"])


def test_a_device_nothing_uses_goes_quietly():
    project = _household()
    project["activities"].pop(0)
    assert project_devices.remove_device(project, "bd") == []


@pytest.mark.parametrize("spoil, says", [
    (lambda p: p["devices"].pop(1), "names device 'bd', which the project does not have"),
    (lambda p: p["devices"][0].update(power_cmd="Nope"), "sends 'Nope' to 'TV'"),
    (lambda p: p["activities"][0]["soft_buttons"].__setitem__(
        0, {"label": "Nothing", "device": "bd", "command": None}), "sends no command"),
    (lambda p: p["activities"][0]["hard_macros"].__setitem__(
        "Blue", [["command", "tv", "Missing"]]), "Blue key sends 'Missing'"),
    (lambda p: p["activities"][0]["image_buttons"].append(["Empty", "channel", "", None]),
     "favourite 'Empty' has no channel number"),
])
def test_the_pk_builder_refuses_what_points_at_nothing(spoil, says):
    project = _household()
    references.check(project["devices"], project["activities"])
    spoil(project)
    with pytest.raises(ValueError, match=says):
        references.check(project["devices"], project["activities"])


@pytest.mark.parametrize("remote", ["harmony-900", "harmony-1100"])
def test_a_900_or_1100_build_with_a_deleted_device_is_refused(tmp_path, remote):
    from afterglow.build_service import ConfigBuildService
    project = _household()
    project["settings"] = {"remote": remote, "out_file": str(tmp_path / "out.ezhex")}
    project["devices"].pop(1)
    with contextlib.redirect_stdout(io.StringIO()), \
            pytest.raises(ValueError, match="which the project does not have"):
        ConfigBuildService(ROOT, lambda _m: None).build(project)


def test_the_dialogs_take_no_button_or_favourite_that_sends_nothing(qapp_or_skip, monkeypatch):
    from afterglow.gui import activity_buttons
    warned = []
    monkeypatch.setattr(activity_buttons.QMessageBox, "warning",
                        lambda _parent, title, _text: warned.append(title))
    silent = {"id": "x", "label": "Lamp", "commands": []}
    button = activity_buttons.ScreenButtonDialog([silent])
    button.label_edit.setText("Nothing")
    button.accept()
    assert getattr(button, "result_data", None) is None
    assert warned == ["Nothing to send"]
    favourite = activity_buttons.FavouriteDialog(_household()["devices"])
    favourite.label_edit.setText("BBC")
    favourite.action.kind.select_data("channel")
    favourite.action.channel.setText("")
    favourite.accept()
    assert warned == ["Nothing to send"] * 2
    favourite.action.channel.setText("101")
    favourite.accept()
    assert favourite.result_data == ("BBC", "channel", "101", "")


def test_a_delay_written_as_text_is_read_as_a_number():
    device = _device("tv", "TV", "PowerToggle")
    device.update(power_delay="500", input_delay=250.0)
    cleaned = project_devices.clean(device)
    assert cleaned["power_delay"] == 500 and cleaned["input_delay"] == 250
    device["power_delay"] = "half a second"
    with pytest.raises(ValueError, match="power_delay is 'half a second'"):
        project_devices.clean(device)
