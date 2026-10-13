"""The editors ask for what people come to change, and say when to leave the rest alone.

Testers of the first beta found the device and activity dialogs hard to follow: adding
a TV walked through nine timing fields, a key that sends one command was listed as a
"1 step" macro, commands kept off the screen looked unnamed, and the One offered a
"Learn from remote" that could only fail. These pin the layout that replaced it.
"""
from __future__ import annotations

import logging

ONE = {"settings": {"remote": "harmony-one"}, "devices": [], "activities": []}
TV = {"id": "1", "label": "TV", "type": "Television"}


def test_the_device_editor_lists_the_seldom_sections_last(qapp_or_skip):
    from afterglow.gui.device_wizard import DeviceEditor
    from afterglow.gui.sections import SELDOM
    editor = DeviceEditor([], existing=TV, project=ONE)
    assert editor.section_names() == ["identity", "commands", "inputs", "timing",
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
