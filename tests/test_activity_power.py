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
    assert page._orderable(2) and not page._orderable(3)    # off has no order
    page._dragged(2, 0)                                    # dragged to the top
    assert page.get_plan() == (["4", "1", "2"], ["3", "5"])
    page._dragged(0, 3)                                    # not below what goes off
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


def test_a_device_can_be_left_as_it_is(qapp_or_skip):
    """Asked for by a tester: an activity that neither switches a device on nor off."""
    from afterglow.gui.activity_power import LEAVE, ActivityPowerPage, apply_plan
    page = ActivityPowerPage(DEVICES, {})
    page.set_participating(["1", "2"])
    page.follow.setChecked(False)
    leave = page.table.cellWidget(4, 1)
    leave.setCurrentIndex(leave.findData(LEAVE))
    spec = {}
    apply_plan(spec, page.get_plan(), page.leave())
    assert spec["power_leave_devices"] == [DEVICES[4]["id"]]
    assert DEVICES[4]["id"] not in spec["power_on_devices"] + spec["power_off_devices"]
    again = ActivityPowerPage(DEVICES, spec)              # and it opens that way
    assert again.leave() == [DEVICES[4]["id"]]
    apply_plan(spec, None)                                # following the roles again
    assert "power_leave_devices" not in spec


def test_a_device_left_as_it_is_is_in_neither_list_of_a_built_activity(build):
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
    activity = {"id": "1001", "label": "Watch", "type": "VirtualGeneric", "display": "1",
                "control": "1", "power_on_devices": ["1"], "power_off_devices": [],
                "power_leave_devices": ["3"]}
    project = {"devices": [device("1"), device("2"), device("3")], "activities": [activity]}
    raw = build(project).read_bytes()
    _h, start, size, _c = ezhex._split(raw)
    xml = zipfile.ZipFile(io.BytesIO(raw[start:start + size])).read(
        "userconfig/UserConfiguration.xml").decode()
    power = re.search(r"<Label>Watch</Label>.*?<Power>(.*?)</Power>", xml, re.S).group(1)
    assert power == "<On>1</On><Off>2</Off>"          # 3 neither on nor off

    from afterglow.backends.harmony_one import activities, generate
    one = dict(project, settings={"remote": "harmony-one"})
    planned = activities.plan(one, generate.lowered_devices(one))["activities"][0]
    assert planned["on"] == [0] and planned["off"] == [1]
