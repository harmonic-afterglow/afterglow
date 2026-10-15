"""A saved project keeps its earlier versions, and the last one is reopened at start -
without the start depending on it still being there."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from afterglow import project_backups


@pytest.fixture
def project_file(tmp_path, monkeypatch):
    monkeypatch.setattr(project_backups.paths, "user_folder",
                        lambda kind: tmp_path / "Backups" if kind == "backups" else tmp_path)
    path = tmp_path / "living-room.json"
    path.write_text('{"version": 1}')
    return path


def test_the_version_a_save_replaces_is_kept(project_file):
    kept = project_backups.back_up(project_file)
    assert kept.read_text() == '{"version": 1}'
    assert kept.parent.name == "living-room"
    assert project_backups.back_up(project_file) is None, "the same version twice"


def test_only_the_last_versions_are_kept(project_file, monkeypatch):
    """With the clock standing still, as it does between saves on Windows: Windows CI
    named two backups alike and kept the wrong ones."""
    import datetime as real

    class Frozen(real.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 15, 8, 0, 0)

    monkeypatch.setattr(project_backups, "datetime", Frozen)
    monkeypatch.setattr(project_backups, "KEEP", 3)
    for n in range(5):
        project_file.write_text(json.dumps({"version": n}))
        project_backups.back_up(project_file)
    kept = project_backups.history(project_file)
    assert [json.loads(p.read_text())["version"] for p in kept] == [2, 3, 4]


def test_a_backup_that_cannot_be_made_does_not_stop_the_save(project_file, monkeypatch):
    def refuse(*_a):
        raise PermissionError("blocked")
    monkeypatch.setattr(project_backups.shutil, "copyfile", refuse)
    assert project_backups.back_up(project_file) is None


def test_an_opened_shareable_project_is_named_by_its_folder(tmp_path):
    assert project_backups.name_of(tmp_path / "Mancave" / "project.json") == "Mancave"


# the window
@pytest.fixture
def window(qapp_or_skip, monkeypatch):
    from PyQt6.QtCore import QSettings
    from afterglow.gui import app
    QSettings("Afterglow", "Afterglow").remove(app.LAST_PROJECT_KEY)
    win = app.MainWindow()
    yield win
    QSettings("Afterglow", "Afterglow").remove(app.LAST_PROJECT_KEY)


def _saved(window, path):
    window._write_project(path)
    return path


def test_saving_twice_keeps_the_first_version(window, tmp_path):
    path = _saved(window, tmp_path / "home.json")
    window.settings_tab.first_name.setText("Changed")
    window._write_project(path)
    [earlier] = project_backups.history(path)
    assert json.loads(earlier.read_text())["settings"].get("first_name") != "Changed"


def test_the_last_saved_project_is_reopened(window, tmp_path, qapp_or_skip):
    from afterglow.gui.app import MainWindow
    window.settings_tab.first_name.setText("Mark")
    path = _saved(window, tmp_path / "mancave.json")
    again = MainWindow()
    assert again.reopen_last_project()
    assert Path(again._project_path) == path
    assert again.project["settings"]["first_name"] == "Mark"


@pytest.mark.parametrize("damage", ["deleted", "not json", "not a project"])
def test_a_last_project_that_is_gone_or_broken_starts_empty(window, tmp_path, damage):
    from afterglow.gui.app import MainWindow
    path = _saved(window, tmp_path / "gone.json")
    if damage == "deleted":
        path.unlink()
    elif damage == "not json":
        path.write_text("{ half a file")
    else:
        path.write_text('["a list, not a project"]')
    again = MainWindow()
    assert again.reopen_last_project() is False
    assert again._project_path is None
    assert again.project.get("devices") == [] and again.project.get("activities") == []


def test_the_file_menu_has_its_shortcuts(window):
    keys = {a.text(): a.shortcut().toString() for a in
            window.menuBar().actions()[0].menu().actions() if a.text()}
    for name in ("New Project", "Open Project…", "Import .ezhex…", "Save Project",
                 "Save Project As…", "Export .ezhex…", "Exit"):
        assert keys[name], f"{name} has no shortcut"
