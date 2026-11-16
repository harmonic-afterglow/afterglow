"""Saving says when it failed, and never leaves half a project behind."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def window(qapp_or_skip, monkeypatch):
    from afterglow.qt.QtWidgets import QMessageBox
    window_said = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda _parent, title, text, *a, **k: window_said.append(title))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from afterglow.gui.app import MainWindow
    win = MainWindow()
    win.said = window_said
    yield win
    win._dirty = False
    win.close()


def test_a_failed_save_is_said_and_keeps_the_previous_version(window, tmp_path, monkeypatch):
    path = tmp_path / "home.json"
    path.write_text('{"previous": true}', encoding="utf-8")
    window._dirty = True

    def full(self, *_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(type(path), "write_text", full)
    assert window._write_project(path) is False
    monkeypatch.undo()
    assert window.said == ["Save Failed"]
    assert window._dirty
    assert json.loads(path.read_text(encoding="utf-8")) == {"previous": True}
    assert [p.name for p in tmp_path.iterdir()] == ["home.json"]


def test_save_as_adds_the_extension(window, tmp_path, monkeypatch):
    from afterglow.gui import app
    monkeypatch.setattr(app.QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "home"), ""))
    window.save_project_as()
    assert window._project_path == str(tmp_path / "home.json")
    assert (tmp_path / "home.json").is_file()


def test_an_unexpected_error_is_put_in_front_of_the_owner(window):
    from afterglow.gui.app import _error_notice
    from afterglow.qt.QtWidgets import QMessageBox
    notice = _error_notice(window)
    notice("KeyError: 'x'")
    notice("KeyError: 'x'")
    boxes = [w for w in window.findChildren(QMessageBox) if w.isVisible()]
    assert len(boxes) == 1 and "Show log file" in boxes[0].text()
