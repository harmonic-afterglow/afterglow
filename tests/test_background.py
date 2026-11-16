"""Slow work runs off the interface thread, behind a dialog that can be cancelled: an
online catalogue's first answer froze the window for up to a minute."""
from __future__ import annotations

import threading

import pytest


def test_work_runs_on_another_thread_and_its_answer_comes_back(qapp_or_skip):
    from afterglow.gui import background
    here = threading.get_ident()
    assert background.call(None, "working", lambda: threading.get_ident()) != here


def test_an_error_in_the_work_is_raised_where_it_was_asked(qapp_or_skip):
    from afterglow.gui import background

    def broken():
        raise KeyError("an unexpected record")
    with pytest.raises(KeyError, match="unexpected record"):
        background.call(None, "working", broken)


def test_cancel_stops_the_wait_and_the_work_finishes_unseen(qapp_or_skip):
    from afterglow.qt.QtCore import QTimer
    from afterglow.qt.QtWidgets import QApplication, QProgressDialog

    from afterglow.gui import background
    release = threading.Event()

    def cancel():
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QProgressDialog):
                widget.canceled.emit()          # as its Cancel button does
    QTimer.singleShot(50, cancel)
    with pytest.raises(background.Cancelled):
        background.call(None, "waiting", lambda: release.wait(5), delay_ms=0)
    assert background._ABANDONED
    release.set()
    for worker in list(background._ABANDONED):
        worker.wait(2000)
