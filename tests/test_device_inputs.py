"""A device's inputs and number entry can be set, and setting nothing changes nothing.

Logitech's configurations switch inputs directly, by stepping with one command, and take
channel numbers on the number keys; the builder writes all three. These cover the page
that sets them and what the builder does with an edit to a device that carries its real
state machine.
"""
from __future__ import annotations

import contextlib
import io
import re
import zipfile

import pytest

from afterglow import ezhex, ir_signal, project_devices


def _device(**extra):
    names = ["PowerToggle", "Input", "HDMI1", "HDMI2", "Enter"]
    return {"schema": "afterglow-project-device/1", "id": "1", "label": "TV",
            "type": "Television", "mfr": "T", "model": "M",
            "commands": [[n, n, "", "", None] for n in names],
            "signals": {n: ir_signal.protocol_signal("nec1", {"address": 1, "command": i})
                        for i, n in enumerate(names)}, **extra}


def _page(device):
    from afterglow.gui.device_inputs import DeviceInputsPage
    return DeviceInputsPage(device, lambda: [c[0] for c in device["commands"]])


def _states(path):
    raw = path.read_bytes()
    _h, start, size, _c = ezhex._split(raw)
    xml = zipfile.ZipFile(io.BytesIO(raw[start:start + size])).read(
        "userconfig/UserConfiguration.xml").decode()
    return re.findall(r"<State>.*?</State>", xml, re.S)


def test_an_untouched_page_changes_nothing(qapp_or_skip):
    device = _device(inputs=[["HDMI 1", "HDMI1"], ["Sat", ["Input", {"delay_ms": 500}]]],
                     numeric={"fixed": 2, "finish": "Enter", "digits": {}},
                     states=[{"id": "Input", "values": [], "actions": []}])
    spec = {key: value for key, value in device.items()}
    _page(device).apply(spec)
    assert spec == device


def test_an_input_can_be_ticked_as_the_tv_s_app_without_editing_the_inputs(qapp_or_skip):
    from PyQt6.QtCore import Qt
    device = _device(inputs=[["HDMI 1", "HDMI1"], ["Netflix", "HDMI2"]],
                     online_inputs=["Netflix"],
                     states=[{"id": "Input", "values": [], "actions": []}])
    page = _page(device)
    assert page.online_inputs() == ["Netflix"]          # as the catalogue gave it
    page.table.item(0, 2).setCheckState(Qt.CheckState.Checked)
    page.table.item(1, 2).setCheckState(Qt.CheckState.Unchecked)
    spec = dict(device)
    page.apply(spec)
    assert spec["online_inputs"] == ["HDMI 1"]
    # the imported Input state is kept: ticking an app is not an edit of the inputs
    assert "inputs_edited" not in spec


def test_a_device_that_steps_through_its_inputs_builds_with_them(qapp_or_skip, build):
    from afterglow.gui.device_inputs import CYCLE
    device = _device()
    page = _page(device)
    page.modes[CYCLE].setChecked(True)
    for _ in range(3):
        page._add_value()
    for index, name in enumerate(["TV", "HDMI 1", "HDMI 2"]):
        page.values.item(index).setText(name)
    page._select(page.next_combo, "Input")
    page.cycle_delay.setValue(800)
    assert page.problem() is None
    page.apply(device)

    assert device["input_cycle"] == {"values": ["TV", "HDMI 1", "HDMI 2"],
                                     "next": ["Input"], "delay_ms": 800}
    assert project_devices.input_names(device) == ["TV", "HDMI 1", "HDMI 2"]
    with contextlib.redirect_stdout(io.StringIO()):
        out = build({"devices": [device], "activities": []})
    [input_state] = [s for s in _states(out) if "<Id>Input</Id>" in s]
    assert ("<Value>TV</Value><Value>HDMI 1</Value><Value>HDMI 2</Value>"
            "<Delay>800</Delay><RelativeActions><NextAction>") in input_state


def test_a_step_that_waits_before_its_command_opens_and_keeps_its_wait(qapp_or_skip):
    """The archive starts a Panasonic CT27SF22's input step with a one-second wait,
    `[{"delay_ms": 1000}, "Input"]`; listing that dict as a command crashed Add Device.
    The command is shown, and the wait kept unless another command is picked."""
    cycle = {"values": ["TV", "Video 1"], "next": [{"delay_ms": 1000}, "Input"]}
    page = _page(_device(input_cycle=cycle))
    assert page.next_combo.currentData() == "Input"
    page.inputs_touched = True
    device = _device(input_cycle=cycle)
    page.apply(device)
    assert device["input_cycle"]["next"] == [{"delay_ms": 1000}, "Input"]
    page._select(page.next_combo, "Enter")
    page.apply(device)
    assert device["input_cycle"]["next"] == ["Enter"]


def test_a_step_command_without_its_inputs_is_refused(qapp_or_skip):
    from afterglow.gui.device_inputs import CYCLE
    page = _page(_device())
    page.modes[CYCLE].setChecked(True)
    page._select(page.next_combo, "Input")
    assert "order" in page.problem()


def test_number_entry_can_be_set(qapp_or_skip):
    device = _device()
    page = _page(device)
    page.numeric.setChecked(True)
    page.fixed.setValue(3)
    page._select(page.finish, "Enter")
    page.apply(device)
    assert device["numeric"] == {"fixed": 3, "finish": "Enter"}


def test_editing_an_imported_device_regenerates_only_its_input_state(
        qapp_or_skip, configs, unpacked, build):
    """Every other state comes back byte for byte; the Input state is what was shown."""
    from afterglow.gui.device_inputs import DIRECT
    from afterglow.importer import build_project
    project = build_project(str(unpacked(configs[0])))
    device = next((d for d in project["devices"] if any(
        s.get("id") == "Input" for s in d.get("states") or [])
        and any(s.get("id") != "Input" for s in d.get("states") or [])), None)
    if device is None:
        pytest.skip("no imported device with an Input state beside others")
    with contextlib.redirect_stdout(io.StringIO()):
        before = _states(build(project, "before.ezhex"))
    page = _page(device)
    page.modes[DIRECT].setChecked(True)
    page.table.setRowCount(0)
    page._append_direct("Only input", device["commands"][0][0])
    page._touch_inputs()
    page.apply(device)
    assert device["inputs_edited"] is True
    with contextlib.redirect_stdout(io.StringIO()):
        after = _states(build(project, "after.ezhex"))

    changed = [s for s in after if s not in before]
    assert len(changed) == 1 and "<Value>Only input</Value>" in changed[0]
    assert len(after) == len(before)


def test_an_imported_device_that_steps_opens_as_stepping(configs, unpacked):
    from afterglow.importer import build_project
    stepping = []
    for index, config in enumerate(configs):
        for device in build_project(str(unpacked(config, f"i{index}")))["devices"]:
            if device.get("input_cycle"):
                stepping.append(device)
    if not stepping:
        pytest.skip("no imported device that steps through its inputs")
    for device in stepping:
        cycle = device["input_cycle"]
        assert cycle["values"] and (cycle.get("next") or cycle.get("previous"))
        assert project_devices.input_names(device)


def test_an_input_no_command_selects_opens_with_none_and_stays_so(qapp_or_skip):
    """An imported Harmony One writes such an input as its name alone, `["Input 3"]`;
    the page took every input as a pair and the device editor crashed opening it. The
    row shows no command - not the device's first, which saving would have set."""
    from afterglow.gui.device_inputs import NO_COMMAND
    device = _device(inputs=[["HDMI 1", "HDMI1"], ["Input 2"]])
    page = _page(device)
    assert page.table.rowCount() == 2
    assert page.table.cellWidget(1, 1).currentText() == NO_COMMAND
    spec = dict(device)
    page.apply(spec)
    assert spec["inputs"] == device["inputs"]               # untouched, unchanged
    page._add_direct()
    assert page.table.cellWidget(2, 1).currentText() == NO_COMMAND
    page.apply(spec)
    assert spec["inputs"] == [["HDMI 1", "HDMI1"], ["Input 2", None], ["Input 3", None]]
