"""Every Harmony 1100 is recognised and backed up: all three skins and board revisions.

A tester's 1100 reported skin 63 on board 0.5.0, where the profile knew only board
0.3.0, so it was "not supported"; and Test write's backup check demanded the 900's
ActionLists.xml, which no 1100 configuration has.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from afterglow import concord, remotes
from afterglow.backends.harmony_pk import backend


def _header(skin=63, board="0.5.0"):
    return (f"<INFORMATION><INTENDEDVERSION><PROTOCOL>11</PROTOCOL><SKIN>{skin}</SKIN>"
            f"<FLASH>0x01:0x49</FLASH><BOARD>{board}</BOARD><SOFTWARETYPE>0</SOFTWARETYPE>"
            f"</INTENDEDVERSION></INFORMATION>\r\n").encode()


@pytest.mark.parametrize("skin", [62, 63, 64])
@pytest.mark.parametrize("board", ["0.0.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0"])
def test_every_1100_is_the_1100(skin, board):
    profile = remotes.identify(_header(skin, board))
    assert profile.id == "harmony-1100"
    identity = {"arch": 11, "skin": skin, "flash": "0x01:0x49", "board": board,
                "software_type": 0}
    assert profile.identity_mismatches(identity, require_all=True) == []


def test_the_skin_64_1100_on_board_0_4_is_written(tmp_path):
    """Issue #10: an 1100 reporting skin 64 on board 0.4.14 was refused - "skin is 64
    (expected 63); board is 0.4.14 (expected 0.3.0)". Logitech's own software had written
    it a skin-64, board-0.4.0 configuration in 2018, and firmware 64.7.7 is 63.7.7 with
    only the skin number changed. A build from a new project names skin 63 and board
    0.3.0, and has to go onto it."""
    path = tmp_path / "built.ezhex"
    path.write_bytes(_header(63, "0.3.0") + b"PK\x03\x04" + bytes(32))
    live = {"arch": 11, "skin": 64, "flash": "0x01:0x49", "board": "0.4.14",
            "software_type": 0}
    assert concord.file_mismatches(path, live) == []
    assert concord.Remote._verify_intended_for(path, live, allow_experimental=True).id \
        == "harmony-1100"


def test_a_remote_libconcord_cannot_name_is_named_by_its_profile():
    live = {"model": "Unknown", "arch": 11, "skin": 64, "flash": "0x01:0x49",
            "board": "0.4.14", "software_type": 0}
    assert concord._model_name(live) == "Harmony 1100"
    assert concord._model_name({**live, "model": "Harmony 1100"}) == "Harmony 1100"
    assert concord._model_name({**live, "skin": 65}) == "Unknown", "no guessing"


def test_no_skin_65_is_assumed():
    """Logitech's server has no firmware for 65 at any version, so nothing says it is
    an 1100."""
    with pytest.raises(remotes.UnknownRemote):
        remotes.identify(_header(65, "0.3.0"))


def test_a_board_it_has_never_seen_is_still_refused():
    with pytest.raises(remotes.UnknownRemote, match="Harmony 1100"):
        remotes.identify(_header(63, "0.9.0"))


def test_a_build_for_one_board_may_go_onto_the_other(tmp_path):
    # A new project's build names the profile's board; the remote may be the other one.
    path = tmp_path / "built.ezhex"
    path.write_bytes(_header(63, "0.3.0") + b"PK\x03\x04" + bytes(32))
    live = {"arch": 11, "skin": 63, "flash": "0x01:0x49", "board": "0.5.12",
            "software_type": 0}
    assert concord.file_mismatches(path, live) == []
    assert concord.Remote._verify_intended_for(path, live, allow_experimental=True).id \
        == "harmony-1100"


def _pk(names):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name in names:
            archive.writestr(name, b"<Root/>" if name.endswith(".xml") else b"\0" * 8)
    return out.getvalue()


def test_an_1100_backup_needs_no_action_lists_file():
    payload = _pk(["userconfig/UserConfiguration.xml", "userconfig/SsIr.bin",
                   "userconfig/SsRf.bin", "userconfig/RamInitialise.bin"])
    assert backend.validate_payload(payload, remotes.get("harmony-1100"))["ok"]


def test_the_900_still_needs_its_action_lists():
    payload = _pk(["userconfig/UserConfiguration.xml", "userconfig/SsIr.bin"])
    with pytest.raises(ValueError, match="ActionLists.xml"):
        backend.validate_payload(payload, remotes.get("harmony-900"))


@pytest.mark.parametrize("board", ["0.0.15", "0.2.14"])
def test_the_older_1100_boards_take_a_write(tmp_path, board):
    """Firmware 7.6 remotes report board 0.0 (a 2010 skin 62) and 0.2 (issue #13), and
    were refused - "board is 0.2.14 (expected 0.3.0)". A new project's build goes on."""
    path = tmp_path / "built.ezhex"
    path.write_bytes(_header(63, "0.3.0") + b"PK\x03\x04" + bytes(32))
    live = {"arch": 11, "skin": 63, "flash": "0x01:0x49", "board": board,
            "software_type": 0}
    assert concord.file_mismatches(path, live) == []
    assert concord.Remote._verify_intended_for(path, live, allow_experimental=True).id \
        == "harmony-1100"

