"""The window opens whatever its surroundings: a Documents folder nothing can be written
to (Windows' Controlled folder access does this on a first start) used to raise out of
the window's constructor, before the dialog written to explain it could appear."""
from __future__ import annotations

import os
import sys

import pytest


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                    reason="needs a folder its owner cannot write")
def test_the_window_opens_with_an_unwritable_documents_folder(
        qapp_or_skip, tmp_path, monkeypatch):
    locked = tmp_path / "Documents"
    locked.mkdir()
    locked.chmod(0o500)
    monkeypatch.setenv("AFTERGLOW_HOME", str(locked / "Afterglow"))
    try:
        from afterglow.gui.app import MainWindow
        window = MainWindow()
        window._dirty = False
        window.close()
    finally:
        locked.chmod(0o700)
