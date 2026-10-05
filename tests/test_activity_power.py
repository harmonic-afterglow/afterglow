"""An activity's power plan can be set, and editing one never changes it unasked."""
from __future__ import annotations

DEVICES = [{"id": str(i), "label": name} for i, name in
           enumerate(["TV", "Receiver", "Player", "Subwoofer", "Lamp"], start=1)]


def test_a_new_activity_follows_its_roles(qapp_or_skip):
    from afterglow.gui.activity_power import ActivityPowerPage, apply_plan
    page = ActivityPowerPage(DEVICES, {})
    page.set_participating(["1", "2", "3"])
    assert page.get_plan() is None
    spec = {"power_on_devices": ["x"], "power_off_devices": ["y"]}
    apply_plan(spec, page.get_plan())
    assert "power_on_devices" not in spec and "power_off_devices" not in spec


def test_an_imported_plan_comes_back_exactly_as_it_was(qapp_or_skip):
    """Order included: Logitech's lists are kept in the order the configuration had."""
    from afterglow.gui.activity_power import ActivityPowerPage
    existing = {"power_on_devices": ["3", "1"], "power_off_devices": ["5", "2", "4"]}
    page = ActivityPowerPage(DEVICES, existing)
    assert page.get_plan() == (["3", "1"], ["5", "2", "4"])


def test_a_plan_naming_only_what_goes_off_switches_the_rest_on(qapp_or_skip):
    from afterglow.gui.activity_power import ActivityPowerPage
    page = ActivityPowerPage(DEVICES, {"power_off_devices": ["4", "5"]})
    assert page.get_plan() == (["1", "2", "3"], ["4", "5"])


def test_taking_control_lets_a_device_be_switched_and_reordered(qapp_or_skip):
    from afterglow.gui.activity_power import ActivityPowerPage
    page = ActivityPowerPage(DEVICES, {})
    page.set_participating(["1", "2"])
    page.follow.setChecked(False)
    # the subwoofer joins, then starts first
    page.table.cellWidget(3, 1).setCurrentIndex(0)
    assert page.get_plan()[0] == ["1", "2", "4"]
    page.table.selectRow(2)
    page._move(-1)
    page.table.selectRow(1)
    page._move(-1)
    assert page.get_plan() == (["4", "1", "2"], ["3", "5"])


def test_an_explicit_plan_that_switches_nothing_on_is_honoured(build):
    """`or` treated an empty list as no plan and powered the roles anyway."""
    import io
    import re
    import zipfile
    from afterglow import ezhex, ir_signal

    def device(device_id):
        return {"schema": "afterglow-project-device/1", "id": device_id,
                "label": f"D{device_id}", "type": "Television", "mfr": "T", "model": "M",
                "commands": [["PowerToggle", "PowerToggle", "", "", None]],
                "signals": {"PowerToggle": ir_signal.protocol_signal(
                    "nec1", {"address": 1, "command": int(device_id)})}}
    project = {"devices": [device("1"), device("2")], "activities": [{
        "id": "1001", "label": "Dark", "type": "VirtualGeneric", "display": "1",
        "control": "1", "power_on_devices": [], "power_off_devices": ["1", "2"]}]}
    raw = build(project).read_bytes()
    _h, start, size, _c = ezhex._split(raw)
    xml = zipfile.ZipFile(io.BytesIO(raw[start:start + size])).read(
        "userconfig/UserConfiguration.xml").decode()
    power = re.search(r"<Label>Dark</Label>.*?<Power>(.*?)</Power>", xml, re.S).group(1)
    assert "<On>" not in power and power.count("<Off>") == 2
