"""`manual_startup` was ours, and it is gone.

No donor activity carries any property like it - the whole vocabulary across the six
donor configurations is HideModeControl, PowerOffUnusedDevices, ActivityStartPage,
TrainingWheels, MediaButtonMode and friends, none of them about manual power or input
handling. The builder only ever used the flag to suppress output and the importer never
read it back, so it never survived a flash-and-reread. What it produced, though - an
activity with no input switch and no power list - was permanent, and a power list is
something every real activity has.

So it is removed, and a project file that still has it is cleaned on load rather than
obeyed. These tests hold both halves of that.
"""


import pytest

# `gui.project` needs no Qt of its own, but importing any `afterglow.gui` submodule runs
# the package `__init__`, which imports `app` and therefore PyQt6. This import happens at
# collection, so a fixture cannot skip in time and the module errors instead.
pytest.importorskip("PyQt6.QtWidgets")

from afterglow.gui.project import (  # noqa: E402
    RETIRED_ACTIVITY_FIELDS, drop_retired_fields)


def test_an_old_project_is_cleaned_on_load():
    project = {"activities": [{"label": "Listen to Music", "manual_startup": True},
                              {"label": "Watch TV"}],
               "devices": []}
    cleaned = drop_retired_fields(project)
    assert "manual_startup" not in cleaned["activities"][0]
    assert cleaned["activities"][0]["label"] == "Listen to Music", "cleaned too much"


def test_cleaning_copes_with_a_project_that_has_no_activities():
    for project in ({}, {"activities": None}, {"activities": []}):
        assert drop_retired_fields(dict(project)) is not None


def test_nothing_still_reads_the_retired_fields():
    """The point of retiring rather than ignoring: no code may consult them again."""
    from pathlib import Path
    package = Path(__file__).resolve().parent.parent / "src" / "afterglow"
    for field in RETIRED_ACTIVITY_FIELDS:
        users = [p.relative_to(package) for p in package.rglob("*.py")
                 if field in p.read_text() and p.name != "project.py"]
        assert not users, f"{field} is retired but still read by {users}"


def test_the_flag_no_longer_changes_what_is_built(build, unpacked):
    """The behaviour it used to suppress - the input switch and the power list - now
    happens regardless, so a project carrying the flag builds the same as one without."""
    import xml.etree.ElementTree as ET

    def project(**extra):
        device = {"id": "40009001", "label": "TV", "type": "Television",
                  "commands": [["PowerOn", "On", "07", "01", None],
                               ["PowerOff", "Off", "07", "02", None]],
                  "inputs": [["HDMI 1", None]], "power_on_cmd": "PowerOn",
                  "power_off_cmd": "PowerOff"}
        activity = {"id": "50000001", "label": "Watch TV",
                    "type": "VirtualTelevisionN", "display": "40009001",
                    "control": "40009001", "input": ("40009001", "HDMI 1"), **extra}
        return {"devices": [device], "activities": [activity], "assets": []}

    plain = ET.parse(f'{unpacked(build(project()), "a")}'
                     "/userconfig/UserConfiguration.xml").getroot()
    flagged = ET.parse(f'{unpacked(build(project(manual_startup=True), "f"), "b")}'
                       "/userconfig/UserConfiguration.xml").getroot()

    def summary(root):
        activity = [a for a in root.findall("Activity")
                    if a.findtext("Presentation/Label") == "Watch TV"][0]
        return (ET.tostring(activity.find("EnterActions")),
                sorted(e.text for e in activity.findall("Power/On")))

    assert summary(plain) == summary(flagged)
    assert summary(plain)[1] == ["40009001"], "the power list went missing"
