"""libconcord is never handed a user's own path.

Its C `fopen` reads a path in the Windows ANSI code page, not UTF-8, so a Documents
folder under an accented user name - or a localised or OneDrive-redirected one - failed
every "Read from Remote" with "OS-level error related to file operations" (error 14)
while the Desktop worked. It now reads and writes a staged file in a folder it can open,
and Python moves the file to wherever the user asked.
"""
from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from afterglow import concord


class FakeLib:
    """Just enough of libconcord: it records every path it is given."""

    def __init__(self):
        self.paths = []

    def read_config_from_remote(self, blob, size, _callback, _arg):
        data = (ctypes.c_uint8 * 4)(*b"GSPM")
        ctypes.cast(blob, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)))[0] = \
            ctypes.cast(data, ctypes.POINTER(ctypes.c_uint8))
        ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32))[0] = 4
        self._keep = data
        return 0

    def write_config_to_file(self, _blob, _size, path, _binary):
        self.paths.append(path)
        Path(path.decode()).write_bytes(b"<INFORMATION/>written")
        return 0

    def delete_blob(self, _blob):
        pass


def _remote():
    remote = object.__new__(concord.Remote)
    remote.lib = FakeLib()
    return remote


def test_a_dump_reaches_a_folder_libconcord_could_not_open(tmp_path):
    folder = tmp_path / "Документы" / "Afterglow"
    folder.mkdir(parents=True)
    target = folder / "my-remote.ezhex"
    remote = _remote()

    remote.save_config(target)

    assert target.read_bytes() == b"<INFORMATION/>written"
    [given] = remote.lib.paths
    assert "Документы".encode() not in given
    assert not Path(given.decode()).exists(), "the staged file is cleaned up"


def test_a_folder_windows_refuses_says_what_to_do(tmp_path, monkeypatch):
    def refuse(_source, _target):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(concord.shutil, "move", refuse)
    with pytest.raises(concord.RemoteError, match="choose another folder"):
        _remote().save_config(tmp_path / "x.ezhex")
