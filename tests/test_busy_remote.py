"""While Afterglow talks to the remote, the window stays open and the project stays in it:
closing tore the worker thread down part-way through a write, and a remote stopped
part-way through one shows an error until it is written again."""
from __future__ import annotations

import pytest


class _Running:
    """A worker as the window sees one: under way, doing ``operation``."""

    def __init__(self, operation):
        self.operation = operation

    def isRunning(self):
        return True


@pytest.fixture
def window(qapp_or_skip, monkeypatch):
    from afterglow.qt.QtWidgets import QMessageBox
    said = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda _parent, title, text, *a, **k: said.append(text))
    from afterglow.gui.app import MainWindow
    win = MainWindow()
    win.said = said
    yield win
    win.update_tab._worker = None
    win._dirty = False
    win.close()


@pytest.mark.parametrize("operation, says", [("write", "writing"), ("read", "talking")])
def test_the_window_stays_while_the_remote_is_busy(window, operation, says):
    from afterglow.qt.QtGui import QCloseEvent
    window.update_tab._worker = _Running(operation)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert says in window.said[-1]
    # nor is the project replaced under it
    project = dict(window.project)
    window.new_project()
    window.change_remote("harmony-one")
    assert window.project == project
    window.update_tab._worker = None
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
