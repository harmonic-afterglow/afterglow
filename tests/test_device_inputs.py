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
