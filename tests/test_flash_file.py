"""Flashing any configuration file: refused for another remote unless forced."""

from __future__ import annotations

import pytest

from afterglow import concord

H900 = {"arch": 15, "skin": 61, "software_type": 0, "flash": "0x01:0x49",
        "board": "0.1.15", "model": "Harmony 900", "can_write": True}
ONE = {"arch": 12, "skin": 54, "software_type": 0, "flash": "0x1f:0xc8",
       "board": "0.5.3", "model": "Harmony One", "can_write": True}


def _file(tmp_path, arch=15, skin=61, flash="0x01:0x49", board="0.1.0", name="b.ezhex"):
    header = (f"<INFORMATION><INTENDEDVERSION><PROTOCOL>{arch}</PROTOCOL><SKIN>{skin}"
              f"</SKIN><FLASH>{flash}</FLASH><BOARD>{board}</BOARD><SOFTWARETYPE>0"
              f"</SOFTWARETYPE></INTENDEDVERSION></INFORMATION>\r\n").encode()
    path = tmp_path / name
    path.write_bytes(header + b"PK\x03\x04" + bytes(32))
    return path


def test_a_backup_of_the_same_remote_matches(tmp_path):
    # Dumps say 0.1.0 while a live 900 reports its micro revision.
    assert concord.file_mismatches(_file(tmp_path), H900) == []


def test_a_remote_without_a_profile_matches_its_own_backup(tmp_path):
    # The flash id's case differs between file headers and the live remote.
    backup = _file(tmp_path, arch=12, skin=54, flash="0x1F:0xC8", board="0.5.0")
    assert concord.file_mismatches(backup, ONE) == []


def test_another_model_is_named(tmp_path):
    problems = concord.file_mismatches(_file(tmp_path), ONE)
    assert any(problem.startswith("arch:") for problem in problems)
    assert any(problem.startswith("skin:") for problem in problems)


def test_a_file_without_a_header_is_refused(tmp_path):
    path = tmp_path / "x.ezhex"
    path.write_bytes(b"PK\x03\x04" + bytes(32))
    assert concord.file_mismatches(path, H900) == ["it is not a Harmony configuration file"]


class _Remote(concord.Remote):
    """A Remote with no library: identity is fixed and applying records the call."""

    def __init__(self, identity):
        self._identity, self.applied = identity, []
        self.last_restart_error = None

    def identity(self, on_progress=None):
        return dict(self._identity)

    def _apply_config(self, path, on_progress=None, reset=True, force=False):
        self.applied.append((path.name, force))


def test_flash_refuses_another_remote_and_writes_nothing(tmp_path):
    remote = _Remote(ONE)
    with pytest.raises(concord.RemoteError, match="was not made for this Harmony One"):
        remote.flash_file(_file(tmp_path), force=False)
    assert remote.applied == []


def test_force_writes_it_anyway(tmp_path):
    remote = _Remote(ONE)
    remote.flash_file(_file(tmp_path), force=True)
    assert remote.applied == [("b.ezhex", True)]


def test_flash_writes_a_matching_backup(tmp_path):
    remote = _Remote(H900)
    remote.flash_file(_file(tmp_path))
    assert remote.applied == [("b.ezhex", False)]


def test_force_does_not_bypass_a_remote_that_cannot_be_written(tmp_path):
    remote = _Remote({**H900, "can_write": False})
    with pytest.raises(concord.RemoteError, match="does not support"):
        remote.flash_file(_file(tmp_path), force=True)
    assert remote.applied == []
