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
    props = _props({"type": kind})
    assert _tabs(props) == tabs
    # and opens where Logitech's do: on Transport, or Numbers where it has none
    assert props["ActivityStartPage"] == ("Transport" if "Transport" in tabs
                                          else "Numbers")


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
    page.show_screen("Discs", False)
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
    assert page.top_right.currentData() == "Discs"
    page.show_screen("GameController", True)
    assert page.top_right.currentData() == "GameController"
    assert not page.is_shown("Discs")
    assert page.start.findData("Discs") < 0
    page.show_screen("GameController", False)
    assert page.top_right.currentData() is None


def test_the_game_pad_is_the_main_device_s(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_screens import ActivityTabsPage
    profile = remotes.get("harmony-1100")
    tab = next(t for t in profile.activity_screens["tabs"] if t["group"] == "GameController")
    for model, top, note in (("PlayStation 3", "Triangle", False), ("Xbox 360", "Y", False),
                             ("Switch", None, True)):
        page = ActivityTabsPage([{"id": "1", "model": model}],
                                {"type": "VirtualGameConsole", "control": "1"},
                                remote=profile)
        rows, warning = page._layout(tab)
        assert (rows[0][1] if rows else None) == top and bool(warning) is note


def test_the_editor_shows_the_defaults_and_can_empty_or_restore_a_place(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_screens import ActivityTabsPage
    tv = _device("2", ["Play", "Pause", "1"])
    tv["label"] = "TV"
    page = ActivityTabsPage([tv, _device("3", ["Play"])],
                            {"type": "VirtualGeneric", "control": "2"},
                            remote=remotes.get("harmony-1100"))
    play = next(b for b in page._slots if b.group == "Transport" and b.slot == "Play")
    assert play.text() == "Play\n(Play)"
    page.set_slot("Transport", "Play", {"blank": True})
    assert play.text() == "Play\n(nothing)" and not play.isFlat()   # bordered: still settable
    page.set_slot("Transport", "Play", {"device": "3", "command": "Play"})
    assert play.text() == "Play\n3: Play"
    page.set_slot("Transport", "Play", None)
    assert play.text() == "Play\n(Play)" and "TV: Play" in play.toolTip()
    page.set_main_device("3")
    assert "3: Play" in play.toolTip()
    spec = {}
    page.set_slot("Transport", "Pause", {"blank": True})
    page.apply(spec)
    assert spec["screen_groups"] == [["Transport", [{"blank": True, "slot": "Pause"}]]]


def _built_places(act, devices):
    """{group: {place: ActionId}} of an activity as the builder writes it."""
    from afterglow import remotes
    from afterglow.backends.harmony_pk.builder.activities import _gen_activity
    by_id = {device["id"]: device for device in devices}
    xml, _lists = _gen_activity(dict({"id": "7", "label": "A"}, **act), by_id,
                                remotes.get("harmony-1100"))
    return {group.get("name"): {button.get("name"): button.findtext("ActionId")
                                for button in group.findall("Button")}
            for group in ET.fromstring(xml).findall("Presentation/ControlGroup")
            if group.get("name") != "HardButtons"}


def _device(ident, names, model=""):
    return {"id": ident, "label": ident, "model": model,
            "commands": [[name, name, "00", "00", None] for name in names]}


DVD = _device("2", ["Play", "Pause", "Stop", "ChapterNext", "ChapterPrev", "SlowForward",
                    "1", "2", "0", "NextDisc"])


def test_a_new_activity_s_fixed_places_come_from_its_main_device():
    """As Logitech's software filled them: the main device's command for each place,
    by the place's name or one it is known by - ChapterNext on Skip forward, 1 on 1."""
    places = _built_places({"type": "VirtualDvd", "control": "2", "display": "2"}, [DVD])
    assert places["Transport"] == {"Play": "2_Play_Hold", "Pause": "2_Pause_Hold",
                                   "Stop": "2_Stop_Hold", "SkipForward": "2_ChapterNext_Hold",
                                   "SkipBack": "2_ChapterPrev_Hold",
                                   "FrameAdvance": "2_SlowForward_Hold"}
    assert places["Numbers"] == {"Number1": "2_1_Hold", "Number2": "2_2_Hold",
                                 "Number0": "2_0_Hold"}
    assert places["Discs"] == {"DiscNext": "2_NextDisc_Hold"}


def test_a_default_on_a_screen_that_draws_labels_has_one():
    """Discs draws its buttons' labels; a place filled there without one is blank."""
    from afterglow import remotes
    from afterglow.backends.harmony_pk.builder.activities import _gen_activity
    xml, _lists = _gen_activity({"id": "7", "label": "A", "type": "VirtualDvd",
                                 "control": "2", "display": "2"}, {"2": DVD},
                                remotes.get("harmony-1100"))
    discs = next(g for g in ET.fromstring(xml).findall("Presentation/ControlGroup")
                 if g.get("name") == "Discs")
    assert [b.findtext("Label") for b in discs.findall("Button")] == ["Next Disc"]
    transport = next(g for g in ET.fromstring(xml).findall("Presentation/ControlGroup")
                     if g.get("name") == "Transport")
    assert all(not b.findtext("Label") for b in transport.findall("Button"))


def test_what_the_owner_set_wins_over_a_default():
    act = {"type": "VirtualDvd", "control": "2", "display": "2",
           "properties": {"ControlGroup_Numbers": "False"},
           "screen_groups": [["Transport", [
               {"slot": "Play", "device": "2", "command": "Pause"},
               {"slot": "Stop", "blank": True}]]]}
    places = _built_places(act, [DVD])
    assert places["Transport"]["Play"] == "2_Pause_Hold"
    assert "Stop" not in places["Transport"]           # emptied: the remote dims it
    assert places["Transport"]["Pause"] == "2_Pause_Hold"
    assert "Numbers" not in places                     # a screen it does not show


def test_an_older_activity_keeps_its_buttons_and_gains_the_fixed_places():
    from afterglow import remotes
    from afterglow.backends.harmony_pk.builder.activities import _gen_activity
    act = {"id": "7", "label": "A", "type": "VirtualGeneric", "control": "2",
           "display": "2", "soft_buttons": [["Go", "2", "Stop"], None, ["On", "2", "Play"]]}
    xml, _lists = _gen_activity(act, {"2": DVD}, remotes.get("harmony-1100"))
    groups = {g.get("name"): g for g in ET.fromstring(xml).findall("Presentation/ControlGroup")}
    assert [(b.findtext("Label"), b.findtext("Position"))
            for b in groups["Misc"].findall("Button")] == [("Go", "0"), ("On", "2")]
    assert _built_places(act, [DVD])["Transport"]["Play"] == "2_Play_Hold"


def test_an_imported_activity_is_given_nothing():
    places = _built_places({"type": "VirtualDvd", "control": "2", "display": "2",
                            "properties_complete": True,
                            "properties": {"ControlGroup_Transport": "True"}}, [DVD])
    assert places == {}


def test_the_game_pad_is_filled_only_where_the_remote_draws_one():
    pad = ["A", "B", "X", "Y", "Triangle", "Square", "Circle"]
    act = {"type": "VirtualGameConsole", "control": "3", "display": "3"}
    xbox = _built_places(act, [_device("3", pad, "Xbox 360")])["GameController"]
    assert set(xbox) == {"A", "B", "X", "Y"}
    ps = _built_places(act, [_device("3", pad, "PS3")])["GameController"]
    assert set(ps) == {"Triangle", "Square", "Circle", "X"}
    assert "GameController" not in _built_places(act, [_device("3", pad, "Switch")])


def test_side_buttons_change_places_by_dragging(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_screens import ActivityTabsPage
    page = ActivityTabsPage([_device("2", ["Guide"])],
                            {"type": "VirtualGeneric", "control": "2"},
                            remote=remotes.get("harmony-1100"))
    page.set_slot("Transport", "SideBarLeft1", {"label": "Guide", "device": "2",
                                                "command": "Guide"})
    page.swap_slots("Transport", "SideBarLeft1", "SideBarRight3")
    assert page.slot_entry("Transport", "SideBarLeft1") is None
    assert page.slot_entry("Transport", "SideBarRight3")["label"] == "Guide"
    spec = {}
    page.apply(spec)
    assert dict(spec["screen_groups"])["Transport"] == [
        {"label": "Guide", "device": "2", "command": "Guide", "slot": "SideBarRight3"}]


def test_no_two_favourites_share_a_number():
    """The remote keeps favourites by number: two alike would both run the last."""
    from afterglow.backends.harmony_pk.builder.activities import _favourite_numbers
    favourites = [("News", "command", ("2", "Guide"), "a.png"),
                  ("News", "macro", [["delay", "2", 100]], "b.png"),
                  ("5", "command", ("2", "Info"), None),
                  ("BBC", "channel", 5, "c.png"),
                  ("BBC", "channel", 101, "d.png")]
    assert _favourite_numbers(favourites) == ["News", "News 2", "5 2", "5", "101"]


def test_an_activity_with_favourites_shows_them():
    """The 1100 shows favourites only on the top-right screen; a DVD activity would
    put Discs there, and its favourites would never be seen."""
    favourite = [("BBC", "channel", 1, None)]
    tabs = _tabs(_props({"type": "VirtualDvd", "image_buttons": favourite}))
    assert "Favorites" in tabs and "Discs" not in tabs
    # the owner's own choice of that corner still wins
    assert "Favorites" not in _tabs(_props({
        "type": "VirtualDvd", "image_buttons": favourite,
        "properties": {"ControlGroup_Favorites": "False", "ControlGroup_Discs": "True"}}))


def test_the_1100_edits_favourites_on_its_top_right_screen(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_wizard import ActivityEditor
    profile = remotes.get("harmony-1100")
    assert "favourites" not in profile.activity_pages
    act = {"id": "9", "label": "TV", "type": "VirtualGeneric", "control": "2",
           "display": "2", "image_buttons": [["BBC", "channel", 1, None]]}
    editor = ActivityEditor([_device("2", ["1", "Guide"])], existing=act, remote=profile)
    page = editor.p3b
    assert page.top_right.currentData() == "Favorites"
    assert page._favourites_warning.text() == ""
    page.favourites._add_row("News", "command", ("2", "Guide"), None)
    spec = editor._collect()
    assert [entry[0] for entry in spec["image_buttons"]] == ["BBC", "News"]
    page.show_screen("Discs", True)
    assert page._favourites_warning.text().startswith("This activity has 2 favourites")


def test_a_side_bar_offers_only_the_icons_it_can_draw(qapp_or_skip):
    """The 1100's side bars load icons from the firmware's small set; one only the
    large set has draws nothing there."""
    from afterglow import remotes
    from afterglow.gui.icon_picker import IconPicker, available
    if not available():
        pytest.skip("needs the button artwork")
    small = remotes.get("harmony-1100").activity_screens["side_bar_icons"]
    picker = IconPicker(None, only=small)
    offered = {picker.list.item(row).text() for row in range(picker.list.count())}
    assert offered and offered <= set(available())
    assert {name.lower() for name in offered} <= {name.lower() for name in small}
    assert len(offered) < len(available())


def test_the_number_pad_is_always_on():
    """The remote's activity screen falls back to the number pad whenever the screen it
    should open is not there; with Numbers off that is a screen it never loaded, and a
    tester's Watch Roku and Play Xbox 360 stayed a blank blue screen. Logitech never
    turns it off - so it is on, also for an activity read back from an older build."""
    switched_off = {"type": "VirtualGeneric",
                    "properties": {"ControlGroup_Numbers": "False"}}
    assert "Numbers" in _tabs(_props(switched_off))
    imported = {"type": "VirtualGeneric", "properties_complete": True,
                "properties": {"ControlGroup_HardButtons": "True",
                               "ControlGroup_Numbers": "False",
                               "ControlGroup_Transport": "False",
                               "ControlGroup_GameController": "True"}}
    assert _tabs(_props(imported)) == ["GameController", "Numbers"]


def test_the_editor_does_not_offer_to_hide_the_number_pad(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_screens import ActivityTabsPage
    page = ActivityTabsPage([_device("2", ["Play"])],
                            {"type": "VirtualGeneric", "control": "2",
                             "properties": {"ControlGroup_Numbers": "False"}},
                            remote=remotes.get("harmony-1100"))
    try:
        box = page._shown["Numbers"]
        assert box.isChecked() and not box.isEnabled()
        assert page._shown["Transport"].isEnabled(), "Transport stays the owner's choice"
    finally:
        # Gone before Qt is: a parentless page left for the end of the session was
        # torn down after the application and crashed the run.
        from afterglow.qt.QtWidgets import QApplication
        page.deleteLater()
        QApplication.processEvents()
