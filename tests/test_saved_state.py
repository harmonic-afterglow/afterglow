"""Whether the project is saved is always visible, and edits anywhere count.

Typing in Remote Settings changed the project without marking it unsaved: the tab
only copied its fields into the project when saving, so the window never heard of the
edit, and closing did not ask. The window now keeps the saved state itself, shows it in
its title and in the status bar, and asks before anything replaces unsaved work.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def window(qapp_or_skip, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from afterglow.gui.app import MainWindow
    win = MainWindow()
    yield win
    win._dirty = False
    win.close()


def test_a_new_window_is_untitled_and_clean(window):
    assert window.windowTitle() == "Untitled[*] — Afterglow"
    assert not window.isWindowModified()
    assert window.status.saved.text() == "New project"


def test_typing_in_remote_settings_marks_the_project_unsaved(window):
    from PyQt6.QtTest import QTest
    QTest.keyClicks(window.settings_tab.first_name, "Ann")
    assert window.isWindowModified()
    assert window.status.saved.text() == "Unsaved changes"


def test_changing_a_remote_preference_marks_it_unsaved(window):
    from PyQt6.QtWidgets import QSpinBox
    spin = next(w for w in window.settings_tab.prefs.values() if isinstance(w, QSpinBox))
    spin.setValue(spin.value() + 1 if spin.value() < spin.maximum() else spin.minimum())
    assert window.isWindowModified()


def test_reloading_the_fields_from_the_project_is_not_an_edit(window):
    window.project["settings"]["backlight_level"] = "30"
    window._reload_tabs()
    assert not window.isWindowModified()


def test_saving_clears_it_and_names_the_file(window, tmp_path):
    from PyQt6.QtTest import QTest
    QTest.keyClicks(window.settings_tab.last_name, "Lee")
    window._project_path = str(tmp_path / "den.json")
    window.save_project()
    assert not window.isWindowModified()
    assert window.windowTitle() == "den.json[*] — Afterglow"
    assert window.status.saved.text() == "Saved"
    assert window.status.file.text() == "den.json"
    assert '"last_name": "Lee"' in (tmp_path / "den.json").read_text()


def test_a_new_project_asks_before_throwing_unsaved_work_away(window, monkeypatch):
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QMessageBox
    QTest.keyClicks(window.settings_tab.first_name, "Ann")
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: (
        asked.append(a[1]), QMessageBox.StandardButton.Cancel)[1])
    window.new_project()
    assert asked == ["Unsaved Changes"]
    assert window.settings_tab.first_name.text() == "Ann"     # still there


def test_the_status_bar_shows_the_remote_and_what_is_in_the_project(window):
    window.project["devices"].append({"id": "1", "label": "TV"})
    window._mark_dirty()
    assert window.status.remote.text() == "Harmony 900 · verified"
    assert window.status.contents.text() == "1 device · 0 activities"


def test_clicking_the_remote_offers_to_change_it(window, monkeypatch):
    called = []
    monkeypatch.setattr(window, "change_remote", lambda *a: called.append(True))
    window.status.remote_clicked.disconnect()
    window.status.remote_clicked.connect(window.change_remote)
    window.status.remote.click()
    assert called == [True]
