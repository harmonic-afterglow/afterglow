"""A configuration Afterglow builds passes the checks a write makes, for every remote it
builds for and every model of it: its header states its remote and nothing false - a
field the profile does not name is left for the remote to say, never written as "None",
which once made every 650 and 700 write ask whether the remote was the right one and
Flash a Configuration File refuse the file Afterglow had just made."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from afterglow import concord, ezhex, first_write, ir_signal, remotes

ROOT = Path(__file__).resolve().parents[1]


def _buildable():
    return [(profile.id, skin) for profile in remotes.load_all()
            if profile.buildable for skin in profile.skins]


def _build(tmp_path, remote, skin):
    from afterglow.build_service import ConfigBuildService
    out = tmp_path / f"{remote}-{skin}.ezhex"
    tv = {"schema": "afterglow-project-device/1", "id": "1", "label": "TV",
          "type": "Television", "mfr": "Test", "model": "TV",
          "commands": [["PowerToggle", "PowerToggle", "", "", None]],
          "signals": {"PowerToggle": ir_signal.protocol_signal(
              "nec1", {"address": 4, "command": 8})}}
    project = {"settings": {"remote": remote, "skin": skin, "out_file": str(out)},
               "devices": [tv], "activities": []}
    with contextlib.redirect_stdout(io.StringIO()):
        return ConfigBuildService(ROOT, lambda _m: None).build(project)


@pytest.mark.parametrize("remote, skin", _buildable())
def test_a_built_file_passes_the_checks_a_write_makes(tmp_path, remote, skin):
    profile = remotes.get(remote)
    path = Path(_build(tmp_path, remote, skin))
    header = ezhex.read(path.read_bytes()).header
    assert b">None<" not in header
    # the remote it is for, as it reports itself: any board where the profile names none
    live = {"arch": profile.arch, "skin": skin, "flash": profile.flash or "0x15:0x1C",
            "board": profile.board or "1.4.0", "software_type": profile.software_type or 0}
    assert concord.file_mismatches(path, live) == []
    first_write._artifact(path)
    # and another remote is still told apart
    other = next(p for p in remotes.load_all() if p.arch != profile.arch)
    assert concord.file_mismatches(path, {**live, "arch": other.arch, "skin": other.skin})
