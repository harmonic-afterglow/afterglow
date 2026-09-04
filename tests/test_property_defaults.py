"""What "unset" means, and the one case where it is dangerous.

Read out of the remote's own behaviour layer rather than guessed. It reads exactly three
device properties - AlwaysOn, ManualPower, Scart - and three activity ones -
PowerOffUnusedDevices, PlayOnEnter, StopOnExit. Everything else in a <Properties> block
is for the touchscreen, and nothing in the configurations says what it does with a
missing one.

Two of the three device properties are read for their truth, so a missing one is simply
false. AlwaysOn is not: every place that acts on it compares `== false`, and in Lua
`nil == false` is false, not true. So a device without an AlwaysOn property is not
treated as "not always on" - it falls out of the power handling entirely and is never
switched on when an activity starts, nor off when it ends.

That is why the builder must always write it, and why this file exists.
"""
import xml.etree.ElementTree as ET

import pytest

from afterglow import properties as props

# The properties the remote's behaviour layer reads, and what a missing one does there.
ENGINE_READ = {
    ("device", "AlwaysOn"), ("device", "ManualPower"), ("device", "Scart"),
    ("activity", "PowerOffUnusedDevices"), ("activity", "PlayOnEnter"),
    ("activity", "StopOnExit"),
}


@pytest.fixture(scope="module")
def catalogue():
    return props.catalog()


def test_every_property_says_what_unset_does(catalogue):
    """The complaint this started from: "unset" alone tells a user nothing."""
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui.properties_editor import unset_text
    for scope in ("device", "activity"):
        for name in catalogue[scope]:
            text = unset_text(scope, name, catalogue)
            assert text != "unset", f"{scope}.{name} still says only 'unset'"
            assert text.startswith("unset - ")


def test_the_engine_read_properties_are_marked_as_such(catalogue):
    for scope in ("device", "activity"):
        for name, entry in catalogue[scope].items():
            expected = "remote" if (scope, name) in ENGINE_READ else "touchscreen"
            assert entry.get("read_by") == expected, f"{scope}.{name}"


def test_a_missing_always_on_is_not_described_as_false(catalogue):
    """The distinction that matters. Calling it "false" would be a comfortable lie."""
    entry = catalogue["device"]["AlwaysOn"]
    assert entry["when_absent"] != "false"
    assert "skipped" in entry["when_absent"]


def test_every_default_is_one_that_was_actually_observed(catalogue):
    """A default contradicting its own evidence is worse than none - IsNewDevice was
    recorded as false while every configuration that has it says true."""
    for scope in ("device", "activity"):
        for name, entry in catalogue[scope].items():
            observed = entry.get("observed")
            if not observed:
                assert entry["default_from"].startswith("inferred"), \
                    f"{scope}.{name} has no observations but claims a measured default"
                continue
            assert str(entry["default"]) == str(max(observed, key=observed.get)), \
                f"{scope}.{name}: default is not the value most often seen"


def test_applies_to_is_recorded_for_every_property(catalogue):
    """Which types a property belongs on - a Light has no disc count."""
    for scope in ("device", "activity"):
        for name, entry in catalogue[scope].items():
            applies = entry.get("applies_to")
            assert applies == "all" or isinstance(applies, list), f"{scope}.{name}"


def test_a_built_device_always_carries_always_on(build, unpacked):
    """The guarantee, checked in the output rather than in the code that writes it."""
    device = {"id": "40009001", "label": "TV", "type": "Television",
              "commands": [["PowerOn", "On", "07", "01", None]]}
    project = {"devices": [device], "activities": [], "assets": []}
    tree = unpacked(build(project), "always-on")
    root = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
    for element in root.findall("Device"):
        names = {p.attrib["name"] for p in element.findall("Properties/Property")}
        assert "AlwaysOn" in names, (
            "a device without AlwaysOn is skipped by the remote's power handling "
            "entirely - it would never be switched on by an activity")


def test_an_always_on_device_still_says_so(build, unpacked):
    device = {"id": "40009001", "label": "Apple TV", "type": "MediaCenterPC",
              "always_on": True,
              "commands": [["Menu", "Menu", "07", "01", None]]}
    tree = unpacked(build({"devices": [device], "activities": [], "assets": []}), "ao")
    root = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
    value = root.find('.//Device/Properties/Property[@name="AlwaysOn"]')
    assert value is not None and value.text == "true"


# the device library
# These three tests check invariants of device JSON, and they used to read a device
# library that shipped inside the package. That library moved to the user's own data
# directory, because a device map describes somebody's home and does not belong in a
# public repository - after which `glob` matched nothing and all three passed by
# iterating an empty dict. They were green and covering nothing.
#
# `skip_if_no_devices` makes that visible: with no devices present the run reports skips
# instead of passes, and with a user library present the invariants are checked again.
def library_devices():
    import glob
    import json
    from pathlib import Path

    from afterglow import paths

    # Path(...).name, not split("/"): glob returns backslash-separated paths on
    # Windows, where splitting on "/" yields the whole path as the key.
    found = {}
    for root in (paths.library("devices"), paths.user_library("devices")):
        for path in sorted(glob.glob(str(root / "*.json"))):
            found[Path(path).name] = json.load(open(path, encoding="utf-8"))
    return found


def skip_if_no_devices():
    devices = library_devices()
    if not devices:
        pytest.skip("no device library present - shipped devices moved to the user's "
                    "own data directory, so this invariant has nothing to check here")
    return devices


def test_every_library_device_states_always_on():
    """Not a tidiness rule. A device with no AlwaysOn is skipped by the remote's power
    handling, so a library entry that omits it ships a device that never switches on."""
    for name, device in skip_if_no_devices().items():
        assert "AlwaysOn" in (device.get("properties") or {}), name


def test_always_on_agrees_with_the_power_mode():
    """It is recorded twice - `power.mode` and the property - and the two saying
    different things would be worse than either alone. The property is derived."""
    for name, device in skip_if_no_devices().items():
        always = (device.get("power") or {}).get("mode") == "always_on"
        assert device["properties"]["AlwaysOn"] == ("true" if always else "false"), name


def test_the_library_does_not_invent_product_facts():
    """The line drawn when filling these in: how many discs a changer holds, or which
    input is its tuner, is a fact about the product. A default is not a substitute for
    knowing, so devices that never said are left saying nothing."""
    invented = {"NumDiscs", "NumCassettes", "NumLights", "TunerInput", "PvrType"}
    for name, device in skip_if_no_devices().items():
        for field in invented & set(device.get("properties") or {}):
            value = device["properties"][field]
            assert value, f"{name}: {field} present but empty"


# what the Advanced page offers
def editor(kind, values=None, scope="device"):
    from afterglow.gui.properties_editor import PropertiesEditor
    return PropertiesEditor(scope, values or {}, kind=kind)


def test_a_television_is_not_offered_a_disc_count(qapp_or_skip):
    """The complaint. A real television showed sixteen settings, four of which meant
    something; the rest were cassette slots, disc slots, lights and a recorder type,
    all reading "unset" as though twelve things had been left undone."""
    rows = set(editor("Television")._rows)
    for absurd in ("NumDiscs", "NumCassettes", "NumLights", "PvrType", "Dimmer",
                   "HasBands", "HasPresets", "OnScreenGuide", "MenuOnDevice"):
        assert absurd not in rows, f"a television was offered {absurd}"
    # AlwaysOn is deliberately absent: it is set on the Timing page, and having it
    # here as well was a second control that did nothing.
    assert {"ManualPower", "IsDisplayDevice", "TunerInput"} <= rows


def test_a_light_is_offered_its_own_settings(qapp_or_skip):
    rows = set(editor("Light")._rows)
    assert {"Dimmer", "NumLights"} <= rows
    assert "NumDiscs" not in rows and "TunerInput" not in rows


def test_a_donor_device_has_nothing_left_unset(qapp_or_skip):
    """Filtered by type, a configuration written by the original software fills every
    property that applies - so the page shows no gaps at all."""
    import contextlib
    import glob
    import io
    import tempfile
    from afterglow import ezhex
    from afterglow.importer import build_project
    from conftest import ROOT

    donors = sorted(glob.glob(str(ROOT / "configs" / "*" / "*.ezhex")))
    if not donors:
        pytest.skip("no donor configurations available")
    work = tempfile.mkdtemp()
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(donors[0], work)
        project = build_project(work)
    cat = props.catalog()["device"]
    for device in project["devices"]:
        page = editor(device.get("type"), device.get("properties"))
        unset = [n for n in page._rows
                 if n not in (device.get("properties") or {})
                 # SCART is the one property no configuration has ever contained, on any
                 # device, so it is genuinely absent rather than missing. Absence means
                 # false there and the remote is fine with it.
                 and cat.get(n, {}).get("observed")]
        assert not unset, f"{device['label']} ({device['type']}) still shows {unset}"


def test_a_property_the_type_does_not_use_is_still_shown_when_present(qapp_or_skip):
    """`applies_to` is measured from six configurations, not from the whole world.
    Filtering may never hide something a configuration actually carries."""
    rows = set(editor("Television", {"NumDiscs": "5"})._rows)
    assert "NumDiscs" in rows


def test_opening_the_page_does_not_write_anything(qapp_or_skip):
    """A setting shown at its default is shown, not adopted. Otherwise looking at a
    device would add a dozen properties the original software never wrote for it."""
    for kind in ("Television", "Light", "Receiver", "DvdCd", "MediaCenterPC"):
        page = editor(kind, {"AlwaysOn": "false"})
        assert page.values() == {"AlwaysOn": "false"}, kind


def test_changing_a_default_does_write_it(qapp_or_skip):
    """The other half: touching it must take effect."""
    page = editor("Television")
    page._rows_widgets = None
    from PyQt6.QtWidgets import QCheckBox
    box = page.findChildren(QCheckBox)[0]
    box.setChecked(not box.isChecked())
    assert page.values(), "changing a control wrote nothing"


# telling the two power settings apart
def test_each_power_setting_says_what_it_is_without_the_other(catalogue):
    """They sound like the same setting and are read by different parts of the remote:
    AlwaysOn by the power handling, which takes the device out of it; ManualPower only
    to decide whether to ask the user rather than try.

    Each description has to carry that on its own. Written against each other - "unlike
    Manual power..." - they fail whoever reads one of them in isolation, which on an
    alphabetical page is everyone.
    """
    always = catalogue["device"]["AlwaysOn"]["description"]
    manual = catalogue["device"]["ManualPower"]["description"]
    assert "keep this device switched on" in always
    assert "no way to switch" in manual
    assert "Manual power" not in always and "Always on" not in manual, \
        "the descriptions lean on each other"


# one setting, one control
def test_always_on_is_not_offered_twice(qapp_or_skip):
    """It had a checkbox on the Timing page and a row here, and this was the copy that
    did nothing: the builder derives the property from the Timing checkbox, so whatever
    was chosen here was overwritten on the way out."""
    for kind in ("Television", "Light", "Receiver"):
        assert "AlwaysOn" not in editor(kind)._rows, kind


def test_a_hidden_property_is_still_written_back(qapp_or_skip):
    """Not offering a row must not mean dropping the value. For AlwaysOn that would be
    the worst possible outcome: a device with no AlwaysOn is skipped by the remote's
    power handling entirely."""
    carried = {"AlwaysOn": "true", "IsNewDevice": "true", "ManualPower": "True",
               "TunerInput": "Tuner"}
    page = editor("Television", carried)
    assert "AlwaysOn" not in page._rows and "IsNewDevice" not in page._rows
    assert page.values() == carried


def test_manual_power_is_still_editable(qapp_or_skip):
    """It has no control anywhere else, so this is where it lives."""
    assert "ManualPower" in editor("Television")._rows


# what the builder is allowed to decide
def test_a_devices_own_manual_power_survives_a_build(build, unpacked):
    """The builder imposed ManualPower=false on every device, discarding what the
    device said. donor-2's Roku and shade controller are both True, and every rebuild
    quietly returned them to false - the remote would then try to switch a device that
    has no power command instead of asking the user."""
    device = {"id": "40009001", "label": "Roku", "type": "DvdCd",
              "properties": {"ManualPower": "True"},
              "commands": [["Select", "Select", "07", "01", None]]}
    tree = unpacked(build({"devices": [device], "activities": [], "assets": []}), "mp")
    value = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot().find(
        './/Device/Properties/Property[@name="ManualPower"]')
    assert value is not None and value.text == "True"


def test_a_device_that_says_nothing_still_gets_manual_power(build, unpacked):
    """It stays a default - every donor device carries it, so every built one should."""
    device = {"id": "40009001", "label": "TV", "type": "Television",
              "commands": [["PowerOn", "On", "07", "01", None]]}
    tree = unpacked(build({"devices": [device], "activities": [], "assets": []}), "mp2")
    value = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot().find(
        './/Device/Properties/Property[@name="ManualPower"]')
    assert value is not None and value.text == "false"


def test_always_on_still_comes_from_the_timing_checkbox(build, unpacked):
    """The property is derived from `always_on`, so the two cannot drift apart even if
    a project carries a contradictory value."""
    device = {"id": "40009001", "label": "Apple TV", "type": "MediaCenterPC",
              "always_on": True, "properties": {"AlwaysOn": "false"},
              "commands": [["Menu", "Menu", "07", "01", None]]}
    tree = unpacked(build({"devices": [device], "activities": [], "assets": []}), "ao2")
    value = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot().find(
        './/Device/Properties/Property[@name="AlwaysOn"]')
    assert value is not None and value.text == "true"
