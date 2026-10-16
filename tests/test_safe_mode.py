"""A remote in Safe Mode is still that remote.

A Harmony 900 in Safe Mode answers on USB (on port 3074; it runs no web server) and
reports software type 4 instead of 0. It can be read, and writing a configuration to it
is how it is brought back - so it must not be refused as an unknown remote, and a backup
read from it, which says 4 in its header too, must go back onto it, or onto the same
remote out of Safe Mode.
"""
from __future__ import annotations

from afterglow import concord, remotes

NORMAL = {"arch": 15, "skin": 61, "software_type": 0, "flash": "0x01:0x49",
          "board": "0.1.15", "model": "Harmony 900", "can_write": True}
SAFE = {**NORMAL, "software_type": 4}


def _file(tmp_path, software_type=0, name="b.ezhex"):
    header = ("<INFORMATION><INTENDEDVERSION><PROTOCOL>15</PROTOCOL><SKIN>61</SKIN>"
              "<FLASH>0x01:0x49</FLASH><BOARD>0.1.0</BOARD>"
              f"<SOFTWARETYPE>{software_type}</SOFTWARETYPE></INTENDEDVERSION>"
              "</INFORMATION>\r\n").encode()
    path = tmp_path / name
    path.write_bytes(header + b"PK\x03\x04" + bytes(32))
    return path


def test_the_900_in_safe_mode_is_the_900():
    profile = remotes.get("harmony-900")
    assert profile.matches(SAFE) and profile.in_safe_mode(SAFE)
    assert not profile.in_safe_mode(NORMAL)
    assert profile.identity_mismatches(SAFE, require_all=True) == []
    # another software type is still another thing
    assert not profile.matches({**NORMAL, "software_type": 3})


def test_a_configuration_goes_onto_a_remote_in_safe_mode(tmp_path):
    assert concord.file_mismatches(_file(tmp_path), SAFE) == []


def test_a_backup_read_in_safe_mode_goes_back_on(tmp_path):
    backup = _file(tmp_path, software_type=4)
    assert remotes.identify(backup.read_bytes()[:400]).id == "harmony-900"
    assert concord.file_mismatches(backup, SAFE) == []
    assert concord.file_mismatches(backup, NORMAL) == []
