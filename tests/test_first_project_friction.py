"""What a first-time user ran into making a project for the 900, One, 1100, 550 and 700:
a key's command was chosen before the user chose one and a step could not be changed once
added, a remote with no types offered an empty Type list, every project was saved as
"Projects", and the 900's and 1100's first build stopped for an owner's name the build
already has."""
from __future__ import annotations

import pytest

from afterglow import remotes


@pytest.fixture
def devices():
    return [{"id": "1", "label": "TV", "commands": [["-", "-"], ["PowerOn", "PowerOn"]]},
            {"id": "2", "label": "Amp", "commands": [["VolumeUp", "VolumeUp"]]}]


def test_the_command_picker_chooses_nothing_for_you(qapp_or_skip, devices):
    """A TV's first command is "-", the dash of a channel like 7-1: picked for the user,
    it read as "no command" and was sent all the same."""
    from afterglow.gui.macro import CommandPicker
    picker = CommandPicker(devices)
    assert picker.cmd_combo.currentData() is None
    assert not picker.ok.isEnabled()
    picker.cmd_combo.select_data("PowerOn")
    assert picker.ok.isEnabled()
    picker.accept()
    assert picker.result_cmd == ("1", "PowerOn", "Press")


def test_a_step_is_changed_in_its_place(qapp_or_skip, devices, monkeypatch):
    from afterglow.gui import macro
    editor = macro.MacroEditorWidget(devices, [["command", "1", "-", "Press"],
                                               ["delay", "1", 500]])

    def pick(self):
        assert self.cmd_combo.currentData() == "-"          # opened on the step's own
        self.dev_combo.select_data("2")
        self.cmd_combo.select_data("VolumeUp")
        self.mod_combo.setCurrentIndex(self.mod_combo.findData("Hold"))
        macro.CommandPicker.accept(self)
        return True
    monkeypatch.setattr(macro.CommandPicker, "exec", pick)
    editor._edit(0)
    assert editor.get_macro() == [("command", "2", "VolumeUp", "Hold"), ("delay", "1", 500)]


def test_a_cancelled_change_leaves_the_step(qapp_or_skip, devices, monkeypatch):
    from afterglow.gui import macro
    editor = macro.MacroEditorWidget(devices, [["delay", "1", 500]])
    monkeypatch.setattr(macro.DelayPicker, "exec", lambda self: False)
    editor._edit(0)
    assert editor.get_macro() == [("delay", "1", 500)]


def _typeless(monkeypatch):
    """The 900's profile with no device or activity types, as a remote whose menus
    draw no icons has (the 5xx), installed as `test-model`."""
    import dataclasses
    profile = remotes.get("harmony-900")
    bare = dataclasses.replace(
        profile, id="test-model",
        vocabulary={**profile.vocabulary, "device_types": {}, "activity_types": []})
    real = remotes.get
    monkeypatch.setattr(remotes, "get",
                        lambda pid, *a, **k: bare if pid == "test-model" else real(pid, *a, **k))
    return bare


def _project(remote):
    return {"devices": [{"id": "1", "label": "TV", "type": "Receiver", "commands": []}],
            "activities": [{"id": "10", "label": "Watch", "type": "VirtualGeneric"}],
            "settings": {"remote": remote}}


@pytest.mark.parametrize("remote, shown", [("test-model", False), ("harmony-900", True)])
def test_type_is_offered_only_where_the_remote_has_types(qapp_or_skip, monkeypatch,
                                                         remote, shown):
    """A remote with no types offered an empty Type list, and a device moved there from
    a 900 still said "Receiver". What a device or activity already has is kept."""
    from afterglow.gui.activity_wizard import ActivityIdentityPage
    from afterglow.gui.device_wizard import IdentityPage
    _typeless(monkeypatch)
    project = _project(remote)
    device = IdentityPage(project["devices"][0], project=project)
    assert device._form.isRowVisible(device.type_combo) is shown
    assert device.type_combo.currentData() == "Receiver" or not shown
    activity = ActivityIdentityPage(project["activities"][0], remote=remotes.get(remote))
    assert activity.layout().isRowVisible(activity.type_combo) is shown
    assert activity.type_combo.currentData() == "VirtualGeneric"


@pytest.mark.parametrize("remote, shown", [("test-model", False), ("harmony-900", True)])
def test_a_device_row_names_a_type_only_where_there_are_types(qapp_or_skip, monkeypatch,
                                                              remote, shown):
    from afterglow.qt.QtWidgets import QLabel
    from afterglow.gui.tabs import DeviceCard
    _typeless(monkeypatch)
    project = _project(remote)
    card = DeviceCard(project["devices"][0], lambda *_: None, lambda *_: None,
                      project=project)
    texts = " ".join(label.text() for label in card.findChildren(QLabel))
    assert ("receiver" in texts.lower()) is shown


def test_a_new_project_is_suggested_a_name_after_its_remote(qapp_or_skip, monkeypatch):
    """It was "project.json", which the window names after its folder: "Projects"."""
    from afterglow.qt.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from afterglow.gui.app import MainWindow
    win = MainWindow()
    try:
        win.project.clear()
        win.project.update(_project("harmony-650"))
        win._project_path = None
        first = win._suggested_project_path()
        # a 650 project that names no model is the profile's "Harmony 600 / 650 / 665":
        # its slashes must not become folders
        assert first.name == "Harmony 600 - 650 - 665.json"
        assert first.parent.name == "Projects"
        first.write_text("{}")
        try:
            assert win._suggested_project_path().name == "Harmony 600 - 650 - 665 (2).json"
        finally:
            first.unlink()
    finally:
        win._dirty = False
        win.close()


def test_save_as_names_the_project_it_saved(qapp_or_skip, monkeypatch, tmp_path):
    """The title and status bar said "Untitled" and "Not saved yet" after a Save As."""
    from afterglow.qt.QtWidgets import QFileDialog, QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    target = tmp_path / "Harmony 650.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    from afterglow.gui.app import MainWindow
    win = MainWindow()
    try:
        win.project.clear()
        win.project.update(_project("harmony-650"))
        win._project_path = None
        win.save_project_as()
        assert target.is_file()
        assert win.windowTitle().startswith("Harmony 650.json")
        assert win.status.file.text() == "Harmony 650.json"
    finally:
        win._dirty = False
        win.close()


@pytest.mark.parametrize("remote", ["harmony-900", "harmony-1100"])
def test_the_owners_name_is_not_asked_for(qapp_or_skip, remote):
    """The build keeps the scaffold's "Harmony User" when the project names nobody."""
    from afterglow.gui.tabs import SettingsTab
    tab = SettingsTab({"devices": [], "activities": [], "settings": {"remote": remote}})
    assert tab.form.isRowVisible(tab.first_name)
    assert tab.missing() == []


def _window(monkeypatch):
    from afterglow.qt.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from afterglow.gui.app import MainWindow
    return MainWindow()


def test_change_remote_is_in_the_file_menu(qapp_or_skip, monkeypatch):
    """It was reached only by clicking the remote's name in the status bar."""
    win = _window(monkeypatch)
    try:
        called = []
        monkeypatch.setattr(win, "change_remote", lambda *a: called.append(a))
        [file_menu] = [a.menu() for a in win.menuBar().actions() if a.text() == "File"]
        [item] = [a for a in file_menu.actions() if a.text().startswith("Change Remote")]
        item.trigger()
        assert called == [()]
    finally:
        win._dirty = False
        win.close()


def test_another_project_starts_with_an_empty_flash_log(qapp_or_skip, monkeypatch):
    """The last build's log stayed - "Building for Harmony 900" after moving to a 550."""
    win = _window(monkeypatch)
    try:
        win.update_tab.log_box.append("Building for Harmony 900")
        win.project.clear()
        win.project.update(_project("harmony-650"))
        win._reload_tabs()
        assert win.update_tab.log_box.toPlainText() == ""
    finally:
        win._dirty = False
        win.close()


def test_change_remote_says_which_remote_and_chooses_none(qapp_or_skip, monkeypatch):
    """The list leaves the project's own remote out and highlighted the default one."""
    from afterglow.gui import app
    seen = {}

    class Dialog(app.ChooseRemoteDialog):
        def exec(self):
            seen["selected"] = self.list.currentItem()
            seen["intro"] = self.findChildren(app.QLabel)[0].text()
            return False
    monkeypatch.setattr(app, "ChooseRemoteDialog", Dialog)
    win = _window(monkeypatch)
    try:
        win.project.clear()
        win.project.update({**_project("harmony-650"),
                            "settings": {"remote": "harmony-650", "skin": 72}})
        win.change_remote()
        assert seen["selected"] is None
        assert seen["intro"].startswith("This project is for the Harmony 650.")
    finally:
        win._dirty = False
        win.close()


@pytest.mark.parametrize("remote, screen_page", [("harmony-650", True),
                                                 ("harmony-one", True),
                                                 ("no screen page", False)])
def test_the_commands_page_says_where_the_device_page_is_arranged(qapp_or_skip, remote,
                                                                  screen_page):
    """It sent a 650's owner to a Screen page the 650 did not have then; a remote with
    none is told its page is the labelled commands in order."""
    import json
    from afterglow.gui.device_wizard import CommandsPage
    if remote == "no screen page":
        data = json.loads(remotes.profile_path("harmony-650").read_text())
        data["interface"]["device_pages"].remove("screen")
        profile = remotes._from_json(data)
    else:
        profile = remotes.get(remote)
    page = CommandsPage({"id": "1", "commands": []}, remote=profile)
    assert ("Screen page" in page.subTitle()) is screen_page


def test_an_activity_row_names_its_volume_device(qapp_or_skip):
    """A receiver an activity turns up was nowhere on its row: after a move it read as
    lost. Shown only when it is not the display's own volume."""
    from afterglow.qt.QtWidgets import QLabel
    from afterglow.gui.tabs import ActivityCard
    devices = {"tv": {"label": "TV"}, "amp": {"label": "Receiver"}}

    def text(spec):
        card = ActivityCard(spec, devices, lambda *_: None, lambda *_: None)
        return " ".join(label.text() for label in card.findChildren(QLabel))
    assert "Volume: Receiver" in text({"label": "Watch", "display": "tv", "volume": "amp",
                                       "control": "tv"})
    assert "Volume" not in text({"label": "Watch", "display": "tv", "volume": "tv"})


def test_a_row_has_edit_and_a_menu_for_the_rest(qapp_or_skip):
    """Edit, Delete and Find model side by side on every row were too many buttons:
    Edit stays, the rest are in the row's menu - Delete too, when it is the only one."""
    from afterglow.qt.QtWidgets import QPushButton
    from afterglow.gui.tabs import ActivityCard, DeviceCard
    deleted = []
    card = ActivityCard({"label": "Watch"}, {}, lambda *_: None,
                        lambda *_: deleted.append(1))
    # Edit is a pencil, named for a screen reader and on hover
    assert not card.findChildren(QPushButton)
    assert card.edit.toolTip() == "Edit" and card.edit.text() == ""
    assert not card.edit.icon().isNull()
    assert [a.text() for a in card.menu.actions()] == ["Delete"]
    card.menu.actions()[0].trigger()
    assert deleted == [1]
    project = _project("harmony-one")
    device = DeviceCard(project["devices"][0], lambda *_: None, lambda *_: None,
                        project=project, on_find=lambda *_: None)
    assert [a.text() for a in device.menu.actions()] == ["Find model...", "Delete"]


def test_a_row_with_no_icon_leaves_no_room_for_one(qapp_or_skip, monkeypatch):
    from afterglow.qt.QtWidgets import QLabel
    from afterglow.gui.tabs import DeviceCard
    _typeless(monkeypatch)
    project = _project("test-model")
    card = DeviceCard(project["devices"][0], lambda *_: None, lambda *_: None,
                      project=project)
    assert not [label for label in card.findChildren(QLabel) if label.width() == 42
                or label.minimumWidth() == 42]


def test_another_device_keeps_the_command_it_also_has(qapp_or_skip):
    """A step moved from the receiver's Mute to the TV's had to have Mute found again
    among sixty commands."""
    from afterglow.gui.macro import CommandPicker
    devices = [{"id": "amp", "label": "Amp", "commands": [["Mute", "Mute"]]},
               {"id": "tv", "label": "TV", "commands": [["Input", "Input"], ["Mute", "Mute"]]},
               {"id": "dvd", "label": "DVD", "commands": [["Play", "Play"]]}]
    picker = CommandPicker(devices, preset=("amp", "Mute", "Press"))
    picker.dev_combo.select_data("tv")
    assert picker.cmd_combo.currentData() == "Mute" and picker.ok.isEnabled()
    picker.dev_combo.select_data("dvd")
    assert picker.cmd_combo.currentData() is None and not picker.ok.isEnabled()


def test_removing_a_device_says_where_to_choose_another():
    """It said "its control device (choose another)", and offered no choice."""
    from afterglow import project_devices
    project = {"devices": [{"id": "tv"}, {"id": "dvd"}], "activities": [
        {"label": "Watch", "display": "tv", "control": "dvd"}]}
    [line] = project_devices.remove_device(project, "dvd")
    assert "play, channels and menus go to" in line
    assert "Devices page" in line
