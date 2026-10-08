"""Every Harmony 1100 is recognised and backed up: both skins and both board revisions.

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


@pytest.mark.parametrize("skin,board", [(62, "0.3.0"), (63, "0.3.0"), (62, "0.5.0"),
                                        (63, "0.5.0")])
def test_every_1100_is_the_1100(skin, board):
    profile = remotes.identify(_header(skin, board))
    assert profile.id == "harmony-1100"
    identity = {"arch": 11, "skin": skin, "flash": "0x01:0x49", "board": board,
                "software_type": 0}
    assert profile.identity_mismatches(identity, require_all=True) == []


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
