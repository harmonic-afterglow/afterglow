"""Windows Security blocking Afterglow's folder is noticed, and named, at start."""
from __future__ import annotations

from afterglow import folder_access, paths


def test_a_writable_folder_can_be_saved_in_and_is_left_as_it_was(tmp_path):
    assert folder_access.can_save_in(tmp_path / "Afterglow")
    assert list((tmp_path / "Afterglow").iterdir()) == []


def test_a_folder_that_refuses_new_files_cannot(tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(folder_access.tempfile, "mkstemp", refuse)
    assert not folder_access.can_save_in(tmp_path)


def test_only_windows_is_asked_about(tmp_path, monkeypatch):
    monkeypatch.delenv("AFTERGLOW_HOME", raising=False)
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(folder_access, "can_save_in", lambda _folder: False)
    monkeypatch.setattr(folder_access.sys, "platform", "linux")
    assert folder_access.blocked_folder() is None
    monkeypatch.setattr(folder_access.sys, "platform", "win32")
    assert folder_access.blocked_folder() == tmp_path
    monkeypatch.setattr(folder_access, "can_save_in", lambda _folder: True)
    assert folder_access.blocked_folder() is None
