"""The editors ask for what people come to change, and say when to leave the rest alone.

Testers of the first beta found the device and activity dialogs hard to follow: adding
a TV walked through nine timing fields, a key that sends one command was listed as a
"1 step" macro, commands kept off the screen looked unnamed, and the One offered a
"Learn from remote" that could only fail. These pin the layout that replaced it.
"""
from __future__ import annotations

import logging

import pytest

ONE = {"settings": {"remote": "harmony-one"}, "devices": [], "activities": []}
TV = {"id": "1", "label": "TV", "type": "Television"}


def test_the_device_editor_lists_the_seldom_sections_last(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceEditor
    from afterglow.gui.sections import SELDOM
    editor = DeviceEditor([], existing=TV, project=ONE)
    assert editor.section_names() == ["identity", "commands", "screen", "inputs", "timing",
                                      "search"]
    rows = [editor.list.item(i).text().strip() for i in range(editor.list.count())]
    assert rows.index(SELDOM) == rows.index("Timing") - 1
    assert editor.current_section() == "identity"     # not the model search


def test_power_is_chosen_with_the_inputs(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceEditor
    editor = DeviceEditor([], existing=TV, project=ONE)
    assert editor.page_cmds.power_box.parent() is not None
    assert editor.page_inputs.isAncestorOf(editor.page_cmds.power_box)


def test_adding_a_device_is_finding_it_and_naming_it(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceWizard
    wizard = DeviceWizard([], project=ONE)
    assert [wizard.page(i) for i in wizard.pageIds()] == [
        wizard.page_search, wizard.page_identity, wizard.page_cmds]
    wizard.restart()
    wizard.next()                          # past the search, to naming
    assert wizard.currentPage() is wizard.page_identity
    assert wizard.nextId() == -1           # done: the commands came with the model


def test_the_one_offers_no_learning(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceEditor, DeviceWizard
    editor = DeviceEditor([], existing=TV, project=ONE)
    assert editor.page_cmds.learn_btn.isHidden()
    modes = DeviceWizard([], project=ONE).page_search.search_type
    assert "learn" not in [modes.itemData(i) for i in range(modes.count())]
    nine = DeviceEditor([], existing=TV, project={"settings": {"remote": "harmony-900"}})
    assert not nine.page_cmds.learn_btn.isHidden()


def test_the_code_columns_wait_to_be_asked_for(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceEditor
    commands = DeviceEditor([], existing=TV, project=ONE).page_cmds
    assert commands.table.isColumnHidden(2) and commands.table.isColumnHidden(3)
    commands.show_codes.setChecked(True)
    assert not commands.table.isColumnHidden(2)


def test_adding_an_activity_is_its_name_devices_and_inputs(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_wizard import ActivityWizard
    wizard = ActivityWizard([TV], remote=remotes.get("harmony-one"))
    assert [wizard.page(i) for i in wizard.pageIds()] == [
        wizard.identity, wizard.roles, wizard.startup]


def test_the_activity_editor_matches_the_device_editor(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_wizard import ActivityEditor
    editor = ActivityEditor([TV], existing={"id": "1001", "label": "Watch"},
                            remote=remotes.get("harmony-one"))
    assert editor.section_names() == ["identity", "roles", "startup", "screen_buttons",
                                      "favourites", "hard_buttons", "power"]


def test_a_key_says_what_it_sends():
    from afterglow.gui.activity_wizard import _does
    devices = [TV]
    assert _does([], devices) == "Default"
    assert _does([["command", "1", "SmartHub"]], devices) == "TV · SmartHub"
    assert _does([["command", "1", "Exit", None, 3000]], devices) == \
        "TV · Exit  (held 3000 ms)"
    assert _does([["command", "1", "A"], ["delay", None, 500]], devices) == "2 steps"


def test_the_log_file_takes_what_went_wrong(tmp_path, monkeypatch):
    from afterglow import applog, paths
    monkeypatch.setenv("AFTERGLOW_HOME", str(tmp_path))
    paths.app_dir.cache_clear()
    for handler in list(applog.LOG.handlers):
        applog.LOG.removeHandler(handler)
    try:
        written = applog.setup()
        applog.LOG.warning("learn failed: unknown error")
        for handler in applog.LOG.handlers:
            handler.flush()
        assert written == tmp_path / "afterglow.log"
        assert "unknown error" in written.read_text(encoding="utf-8")
    finally:
        for handler in list(applog.LOG.handlers):
            handler.close()
            applog.LOG.removeHandler(handler)
        paths.app_dir.cache_clear()
        import sys
        import threading
        sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
    assert logging.getLogger("afterglow") is applog.LOG


def test_the_wizards_list_their_steps_like_the_editors_list_sections(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_wizard import ActivityWizard
    from afterglow.gui.device_wizard import DeviceWizard
    device = DeviceWizard([], project=ONE)
    shown = [device.steps.item(i).text() for i in range(device.steps.count())
             if not device.steps.item(i).isHidden()]
    assert shown == ["1. Find it", "2. Name it"]     # no commands step unless learning
    assert device.page_identity.mfr_edit.isHidden()
    activity = ActivityWizard([TV], remote=remotes.get("harmony-one"))
    assert activity.step_labels() == ["1. Name it", "2. Its devices", "3. Inputs"]
    assert activity.startup.leave_box.isHidden()      # what happens at the end is for Edit


# The remote as a picture
def _with_commands():
    from afterglow import ir_signal
    signal = ir_signal.protocol_signal("nec1", {"address": 1, "command": 1})
    return {**TV, "schema": "afterglow-project-device/1", "mfr": "T", "model": "M",
            "commands": [["VolumeUp", "", "", "", "VolumeUp"], ["Netflix", "", "", "", None]],
            "signals": {"VolumeUp": signal, "Netflix": signal}}


@pytest.mark.parametrize("model", ["harmony-one", "harmony-900", "harmony-1100"])
def test_every_key_is_on_the_drawing(model):
    from afterglow import remotes
    profile = remotes.get(model)
    art = profile.hard_key_art
    assert art["svg"].is_file()
    assert set(art["keys"]) == set(profile.hard_keys)
    assert set(profile.vocabulary["hard_key_labels"]) == set(profile.hard_keys)
    # all of it the remote's own: in its folder, none in the profile
    assert art["svg"].parent == profile.folder
    assert "hard_key_art" not in profile.vocabulary


def test_the_picture_shows_which_keys_send_and_which_commands_have_none(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceEditor
    from afterglow.gui.keys_view import ASSIGNED, FREE
    commands = DeviceEditor([], existing=_with_commands(), project=ONE).page_cmds
    commands.refresh_picture()
    states = commands.keys_view._states
    assert states["VolumeUp"] == (ASSIGNED, "Volume +: sends VolumeUp")
    assert states["Menu"][0] == FREE
    assert [commands.unplaced.item(i).text() for i in range(commands.unplaced.count())] \
        == ["Netflix"]


def test_picking_a_command_and_clicking_a_key_puts_it_there(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceEditor
    commands = DeviceEditor([], existing=_with_commands(), project=ONE).page_cmds
    commands.refresh_picture()
    commands.unplaced.setCurrentRow(0)                   # Netflix
    commands._key_clicked("VolumeUp")                   # the key VolumeUp was on
    rows = {row[0]: row[4] for row in commands.get_commands()}
    assert rows == {"VolumeUp": None, "Netflix": "VolumeUp"}
    commands._place("VolumeUp", None)                   # "Nothing"
    assert all(row[4] is None for row in commands.get_commands())


def test_the_activity_picture_lists_the_keys_it_changes(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_wizard import ActivityEditor
    from afterglow.gui.keys_view import CHANGED, FREE
    editor = ActivityEditor([TV], existing={"id": "1001", "label": "Watch", "hard_macros": {
        "Menu": [["command", "1", "SmartHub"]]}}, remote=remotes.get("harmony-one"))
    keys = editor.p4
    keys.refresh_picture()
    assert keys.keys_view._states["Menu"] == (CHANGED, "Menu: TV · SmartHub")
    assert keys.keys_view._states["Exit"][0] == FREE
    keys.changed_list.setCurrentRow(0)
    keys._reset_listed()
    assert keys.get_hard_macros() == {}
    assert keys.changed_list.count() == 0


def test_a_remote_without_a_drawing_gets_its_keys_as_a_grid(qapp_or_skip):
    from dataclasses import replace

    from afterglow import remotes
    from afterglow.gui.keys_view import RemoteKeys
    nine = remotes.get("harmony-900")
    undrawn = RemoteKeys(replace(nine, art=None))           # no art.json in its folder
    assert not undrawn.has_picture()
    assert set(undrawn.keys()) == {cell["key"] for cell in nine.hard_key_layout
                                   if cell["key"]}


def test_the_1100_ring_lights_by_quarter_around_its_ok(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.keys_view import RemoteKeys
    view = RemoteKeys(remotes.get("harmony-1100"))
    ok = view._keys["Select"]
    for direction in ("DirectionUp", "DirectionDown", "DirectionLeft", "DirectionRight"):
        overlap = view._keys[direction].intersected(ok).boundingRect()
        assert overlap.width() * overlap.height() < 1, direction
    assert set(view._fixed) == {"Off", "Activities"}


def test_a_key_lights_its_own_part_of_the_drawn_button(qapp_or_skip):
    """The volume rocker is one outline in the drawing; each half is its own key."""
    from afterglow import remotes
    from afterglow.gui.keys_view import RemoteKeys
    view = RemoteKeys(remotes.get("harmony-one"))
    up, down = view._keys["VolumeUp"], view._keys["VolumeDown"]
    assert up.boundingRect().bottom() <= down.boundingRect().top() + 0.5
    assert not up.intersected(down).boundingRect().height() > 0.5
    # the d-pad's up arm, not the whole cross
    arm = view._keys["DirectionUp"].boundingRect()
    assert arm.width() < 20 and arm.height() < 20
    assert set(view._fixed) == {"Activities", "Help"}


def test_keys_are_named_as_people_say_them():
    from afterglow import remotes
    one = remotes.get("harmony-one")
    assert [one.key_label(k) for k in ("VolumeUp", "Select", "UpArrow", "SkipBack")] == \
        ["Volume +", "OK", "Page up", "Replay"]
    assert remotes.get("harmony-1100").key_label("UpArrow") == "Left smart button"
    assert one.key_label("InputHdmi1") == "Input Hdmi 1"      # one no profile names


def test_the_physical_buttons_list_reads_top_to_bottom_in_plain_names(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_wizard import ActivityEditor
    editor = ActivityEditor([TV], existing={"id": "1001", "label": "Watch"},
                            remote=remotes.get("harmony-one"))
    keys = editor.p4
    assert keys.table.item(0, 0).text() == "Page up"
    assert keys._slot(0) == "UpArrow"
    assert keys.slots[-1] == "NumberEnter" or keys.slots[-2:] == ["Number0", "NumberEnter"]


def test_the_900_colour_keys_show_their_colours():
    """Drawn black in the guide, so nobody could tell which was which."""
    import xml.etree.ElementTree as ET

    from afterglow import remotes
    svg = ET.parse(remotes.get("harmony-900").hard_key_art["svg"]).getroot()
    marks = next(g for g in svg.iter() if g.get("id") == "afterglow-marks")
    fills = [path.get("fill") for path in marks]
    assert fills == ["#e0302b", "#2fa84f", "#f2c230", "#2f6fd6"]      # red green yellow blue


def test_the_list_views_key_picker_is_the_remote_drawing(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.keys_view import ASSIGNED, CHANGED, FREE
    from afterglow.gui.widgets import RemotePickerDialog
    picker = RemotePickerDialog("VolumeUp", {"Menu": "Menu"}, remote=remotes.get("harmony-one"),
                                command="Louder")
    assert picker.keys.has_picture()
    states = picker.keys._states
    assert states["VolumeUp"] == (ASSIGNED, "Volume +: Louder")
    assert states["Menu"] == (CHANGED, "Menu: Menu")
    assert states["Exit"][0] == FREE
    picker._pick(None)                                    # "No key"
    assert picker.chosen is None


def test_a_key_is_lit_inside_its_own_outline_not_its_box(qapp_or_skip):
    """The 800's guide draws each outline as many short strokes, so no closed outline
    holds a key: its face - the white inside the strokes - is what lights, so the rounded
    corners of its box stay out."""
    from afterglow import remotes
    from afterglow.gui.keys_view import RemoteKeys
    from afterglow.qt.QtCore import QPointF
    profile = remotes.get("harmony-800")
    view = RemoteKeys(profile)
    assert view.has_picture() and set(view.keys()) == set(profile.hard_keys)
    for key in ("Info", "Guide", "Record", "TV"):
        x, y, w, h = profile.hard_key_art["keys"][key]
        face = view._keys[key]
        box = face.boundingRect()
        assert x - 0.3 <= box.left() and box.right() <= x + w + 0.3, key
        # the corners of the box are not the key's
        assert not face.contains(QPointF(x + 0.2, y + 0.2)), key
        assert face.contains(QPointF(x + 1.0, y + h / 2)), key      # beside its label
    assert {"Off", "Numbers", "Activities", "Help", "Mouse"} == set(view._fixed)
