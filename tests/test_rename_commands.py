"""A command renamed in the device editor keeps its code, and is followed everywhere.

A tester renamed two commands imported from a MyHarmony configuration and Save did
nothing: the code was looked up under the new name, found nothing, and the device was
refused for "missing signals" - in the log only. The power choice, inputs, page and the
activities using it also kept the old name.
"""
from __future__ import annotations

WAVE = {"schema": "afterglow-ir-signal/1", "kind": "waveform", "carrier_hz": 38000,
        "pulses_us": [9000, -4500, 560, -560, 560, -40000], "name": "Power"}


def _device():
    return {"schema": "afterglow-project-device/1", "id": "7", "label": "Switch",
            "type": "AudioVideoSwitch", "mfr": "", "model": "",
            "commands": [["Power", "Power", "", "", None], ["Input1", "", "", "", None]],
            "signals": {"Power": dict(WAVE), "Input1": dict(WAVE, name="Input1")},
            "power_cmd": "Power", "inputs": [["HDMI 1", "Input1"]],
            "screen_buttons": [["Power", "Power"]]}


def test_a_renamed_command_keeps_its_code_and_its_place(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceEditor
    project = {"settings": {"remote": "harmony-one"}, "devices": [_device()],
               "activities": []}
    editor = DeviceEditor([], existing=project["devices"][0], project=project)
    table = editor.page_cmds.table
    table.item(0, 0).setText("Hdmi 6x2 Power")
    table.item(1, 0).setText("HDMI One")
    spec = editor._collect()                      # used to raise "missing signals"
    assert spec["signals"]["Hdmi 6x2 Power"]["pulses_us"] == WAVE["pulses_us"]
    assert "Power" not in spec["signals"]
    assert spec["power_cmd"] == "Hdmi 6x2 Power"
    assert spec["inputs"] == [["HDMI 1", "HDMI One"]]
    assert spec["screen_buttons"][0][0] == "Hdmi 6x2 Power"
    assert editor.renames() == {"Power": "Hdmi 6x2 Power", "Input1": "HDMI One"}


def test_the_activities_follow_a_renamed_command():
    from afterglow import project_devices
    device = _device()
    activity = {"id": "1001", "label": "Watch",
                "enter": [["command", "7", "Power"], ["command", "8", "Power"]],
                "hard_macros": {"Menu": [["command", "7", "Input1"]]},
                "soft_buttons": [{"label": "P", "device": "7", "command": "Power"},
                                 ["In", "7", "Input1"]],
                "image_buttons": [["Ch", "command", ["7", "Power"], None]]}
    project_devices.rename_commands(device, {"Power": "On/Off"}, [activity])
    assert activity["enter"] == [["command", "7", "On/Off"], ["command", "8", "Power"]]
    assert activity["soft_buttons"][0]["command"] == "On/Off"
    assert activity["image_buttons"][0][2] == ["7", "On/Off"]
    assert activity["hard_macros"]["Menu"] == [["command", "7", "Input1"]]


def test_save_says_why_a_device_cannot_be_saved(qapp_or_skip, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from afterglow.gui import device_wizard
    project = {"settings": {"remote": "harmony-one"}, "devices": [_device()],
               "activities": []}
    editor = device_wizard.DeviceEditor([], existing=project["devices"][0], project=project)
    said = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda parent, title, text, *a: said.append(text)))
    monkeypatch.setattr(editor, "_collect", lambda: (_ for _ in ()).throw(
        ValueError("missing signals for ['X']")))
    editor.accept()
    assert said and "missing signals" in said[0]
    assert editor.result_spec is None


def test_a_command_is_copied_from_another_device_with_its_code(qapp_or_skip):
    """A model's database entry lacked a button the tester's other device had."""
    from afterglow.gui.device_wizard import DeviceEditor
    other = dict(_device(), id="8", label="Old TV",
                 commands=[["Picture", "Picture", "", "", None]],
                 signals={"Picture": dict(WAVE, name="Picture")})
    project = {"settings": {"remote": "harmony-one"}, "devices": [_device(), other],
               "activities": []}
    editor = DeviceEditor([], existing=project["devices"][0], project=project)
    commands = editor.page_cmds
    assert not commands.copy_btn.isHidden()
    commands.copy_commands([("Picture", other["signals"]["Picture"]),
                            ("Power", other["signals"]["Picture"])])   # a name it has
    spec = editor._collect()
    assert spec["signals"]["Picture"]["pulses_us"] == WAVE["pulses_us"]
    assert "Power (2)" in spec["signals"] and spec["signals"]["Power"] == WAVE
