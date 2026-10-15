"""The Harmony 1100's activity screen: up to four tabs, each turned on by a property.

The remote's own Flash UI (main-ui-group.swf, firmware 63.7.7) loads a tab only when the
activity says `ControlGroup_<tab>` is True; with none set, the activity shows no screen.
Activities Afterglow made carried none. See afterglow-research/harmony-1100.md.
"""
from __future__ import annotations

import contextlib
import copy
import io
import xml.etree.ElementTree as ET

import pytest

from conftest import entries_of


def _props(act):
    from afterglow import remotes
    from afterglow.backends.harmony_pk.builder.activities import _act_props
    xml = _act_props(act, remotes.get("harmony-1100"))
    return {p.get("name"): p.text for p in ET.fromstring(xml)}


def _tabs(props):
    return sorted(name[len("ControlGroup_"):] for name, value in props.items()
                  if value == "True" and name.startswith("ControlGroup_")
                  and name != "ControlGroup_HardButtons")


@pytest.mark.parametrize("kind, tabs", [
    ("VirtualGeneric", ["Misc", "Numbers", "Transport"]),
    ("VirtualDvd", ["Discs", "Misc", "Numbers", "Transport"]),
    ("VirtualGameConsole", ["GameController", "Misc", "Numbers", "Transport"]),
    ("VirtualPvr", ["Favorites", "Misc", "Numbers", "Transport"]),
    ("VirtualRadioSimple", ["Misc", "Numbers"]),
    # a type Logitech's configurations never used gets a generic activity's tabs
    ("VirtualTiVo", ["Misc", "Numbers", "Transport"]),
])
def test_a_new_activity_gets_the_tabs_logitech_gives_its_type(kind, tabs):
    assert _tabs(_props({"type": kind})) == tabs


def test_the_activity_s_own_say_wins_and_an_imported_one_is_left_alone():
    assert "Discs" not in _tabs(_props({"type": "VirtualDvd",
                                        "properties": {"ControlGroup_Discs": "False"}}))
    assert _props({"type": "VirtualDvd", "properties_complete": True,
                   "properties": {"ActivityStartPage": "Numbers"}}) == {
        "ActivityStartPage": "Numbers"}


def test_the_900_s_activities_are_not_given_tabs():
    from afterglow import remotes
    from afterglow.backends.harmony_pk.builder.activities import _act_props
    xml = _act_props({"type": "VirtualDvd"}, remotes.get("harmony-900"))
    assert "Transport" not in xml and "ControlGroup_Misc" not in xml


def _imported(config, unpacked):
    from afterglow import importer
    with contextlib.redirect_stdout(io.StringIO()):
        return importer.build_project(str(unpacked(config)))


def test_editing_nothing_changes_nothing(qapp_or_skip, configs_1100, unpacked):
    """Opening an imported activity, or one from an older project, and saving it."""
    from afterglow import remotes
    from afterglow.gui.activity_wizard import ActivityEditor
    profile = remotes.get("harmony-1100")
    project = _imported(configs_1100[0], unpacked)
    older = {"id": "9", "label": "Old", "type": "VirtualGeneric",
             "soft_buttons": [["Go", project["devices"][0]["id"], "PowerOn"], None]}
    for act in project["activities"] + [older]:
        spec = ActivityEditor(project["devices"], existing=copy.deepcopy(act),
                              remote=profile)._collect()
        for key in ("screen_groups", "soft_buttons"):
            assert spec.get(key) == act.get(key), (act["label"], key)
        for name, value in (act.get("properties") or {}).items():
            assert spec["properties"].get(name) == value, (act["label"], name)


def test_a_place_set_on_a_tab_is_what_the_remote_is_given(qapp_or_skip, configs_1100,
                                                           unpacked, tmp_path):
    from afterglow import remotes
    from afterglow.build_service import ConfigBuildService
    from afterglow.gui.activity_wizard import ActivityEditor
    project = _imported(configs_1100[0], unpacked)
    act = next(a for a in project["activities"] if a.get("type") == "VirtualDvd")
    device = project["devices"][0]
    editor = ActivityEditor(project["devices"], existing=copy.deepcopy(act),
                            remote=remotes.get("harmony-1100"))
    page = editor.p3b
    page.set_slot("Transport", "FrameAdvance",
                  {"label": "Slow", "device": device["id"],
                   "command": device["commands"][0][0]})
    page._shown["Discs"].setChecked(False)
    spec = editor._collect()
    assert spec["properties"]["ControlGroup_Discs"] == "False"
    project["activities"] = [spec if a["id"] == act["id"] else a
                             for a in project["activities"]]
    out = tmp_path / "out.ezhex"
    project["settings"].update(out_file=str(out), first_name="T", last_name="U")
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(tmp_path, lambda _m: None).build(project)
    zip_file = entries_of(out)
    root = ET.fromstring(zip_file.read(next(
        n for n in zip_file.namelist() if n.endswith("UserConfiguration.xml"))))
    built = next(a for a in root.findall("Activity") if a.findtext("Id") == act["id"])
    slow = [b for g in built.findall("Presentation/ControlGroup")
            if g.get("name") == "Transport" for b in g.findall("Button")
            if b.get("name") == "FrameAdvance"]
    assert [b.findtext("Label") for b in slow] == ["Slow"]
    assert {p.get("name"): p.text for p in built.findall("Properties/Property")}[
        "ControlGroup_Discs"] == "False"


def test_favourites_game_controller_and_discs_share_a_corner(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_screens import ActivityTabsPage
    page = ActivityTabsPage([], {"type": "VirtualDvd"}, remote=remotes.get("harmony-1100"))
    assert page._shown["Discs"].isChecked()
    page._shown["GameController"].setChecked(True)
    assert not page._shown["Discs"].isChecked()
    assert page.start.findData("Discs") < 0


def test_the_game_pad_is_the_main_device_s(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_screens import ActivityTabsPage
    profile = remotes.get("harmony-1100")
    tab = next(t for t in profile.activity_screens["tabs"] if t["group"] == "GameController")
    for model, top, note in (("PlayStation 3", "Triangle", False), ("Xbox 360", "Y", False),
                             ("Switch", "Y", True)):
        page = ActivityTabsPage([{"id": "1", "model": model}],
                                {"type": "VirtualGameConsole", "control": "1"},
                                remote=profile)
        rows, warning = page._layout(tab)
        assert rows[0][1] == top and bool(warning) is note
