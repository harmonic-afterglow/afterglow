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


def test_the_window_opens_with_two_verified_remotes_and_none_chosen(qapp_or_skip, monkeypatch):
    """The day a second remote is verified, a first start has no single default: the
    window has to open first, then ask which remote."""
    import dataclasses

    from afterglow import remotes
    from afterglow.gui import default_remote
    real = remotes.load_all
    monkeypatch.setattr(remotes, "load_all", lambda library=remotes.LIBRARY: [
        dataclasses.replace(p, status=remotes.VERIFIED) if p.id == "harmony-1100" else p
        for p in real(library)])
    monkeypatch.setattr(default_remote, "default_remote_id", lambda *_a: None)
    with pytest.raises(remotes.UnknownRemote):
        remotes.default()
    from afterglow.gui.app import MainWindow
    window = MainWindow()
    assert window.project["settings"].get("remote") is None
    window._dirty = False
    window.close()
