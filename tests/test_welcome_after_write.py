"""A welcome after a write, and telling our own builds from Logitech's.

The app decides per write whether a remote is welcomed: the first time Afterglow writes
it (what it holds is not an Afterglow build) or as a project says. The 900 runs its
first-time setup - the remote test over every device, then Logitech's walkthrough - on
the start after a write whose User block says FirstTimeDownload; the 1100 has no such
setup, so its builds never carry it.
"""
from __future__ import annotations

import contextlib
import io
import zipfile
import xml.etree.ElementTree as ET

import pytest

from afterglow import backends, ezhex, ir_signal

from conftest import ROOT

built = backends.get("harmony-pk").afterglow_built


def _build(tmp_path, remote, **settings):
    from afterglow.build_service import ConfigBuildService
    out = tmp_path / f"{remote}.ezhex"
    tv = {"schema": "afterglow-project-device/1", "id": "1", "label": "TV",
          "type": "Television", "mfr": "Test", "model": "TV",
          "commands": [["PowerToggle", "PowerToggle", "", "", None]],
          "signals": {"PowerToggle": ir_signal.protocol_signal(
              "nec1", {"address": 4, "command": 8})}}
    project = {"settings": {"remote": remote, "out_file": str(out), **settings},
               "devices": [tv], "activities": []}
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(ROOT, lambda _m: None).build(project)
    return out.read_bytes()


def _user(raw):
    payload = ezhex.read(raw).payload
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return ET.fromstring(archive.read("userconfig/UserConfiguration.xml")).find("User")


def _with_user_id(raw, user_id):
    """`raw`'s payload with another account's User id, as Logitech's server wrote it."""
    source = zipfile.ZipFile(io.BytesIO(ezhex.read(raw).payload))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "userconfig/UserConfiguration.xml":
                data = data.replace(b"<User><Id>10000000</Id>",
                                    f"<User><Id>{user_id}</Id>".encode())
            target.writestr(item, data)
    return out.getvalue()


@pytest.mark.parametrize("remote", ["harmony-900", "harmony-1100"])
def test_an_afterglow_build_is_known_as_ours(tmp_path, remote):
    raw = _build(tmp_path, remote)
    assert built(raw) is True
    assert built(ezhex.read(raw).payload) is True, "the zip alone, as a region read gives"


@pytest.mark.parametrize("remote", ["harmony-900", "harmony-1100"])
def test_logitechs_configuration_is_not(tmp_path, remote):
    assert built(_with_user_id(_build(tmp_path, remote), 8623687)) is False


def test_what_cannot_be_read_is_neither():
    assert built(b"") is None
    assert built(b"PK\x03\x04 not a zip") is None
    assert built(b"<INFORMATION>broken") is None


def test_the_900_is_welcomed_when_the_write_says_so(tmp_path):
    first = _user(_build(tmp_path, "harmony-900", welcome="always"))
    assert first.findtext("Properties/Property[@name='FirstTimeDownload']") == "True"
    for welcome in ("never", "first", None):
        again = _user(_build(tmp_path, "harmony-900", welcome=welcome))
        assert again.find("Properties/Property[@name='FirstTimeDownload']") is None


def test_the_1100_has_no_first_time_setup_to_run(tmp_path):
    user = _user(_build(tmp_path, "harmony-1100", welcome="always"))
    assert user.find("Properties/Property[@name='FirstTimeDownload']") is None


TRAINING_WHEELS = "Properties/Property[@name='TrainingWheels']"


@pytest.mark.parametrize("setting, shown", [(None, "True"), (False, "False"),
                                            ("false", "False"), ("true", "True")])
def test_the_1100s_remote_assistant_is_what_the_project_says(tmp_path, setting, shown):
    """The 1100 sets its Remote Assistant from TrainingWheels on the first start after a
    write - on when it is missing - and overwrites its own preference file with it, so
    the choice has to be in the configuration. "false" is how a project kept it while
    it was one of the remote's preferences."""
    settings = {} if setting is None else {"remote_assistant": setting}
    user = _user(_build(tmp_path, "harmony-1100", **settings))
    assert user.findtext(TRAINING_WHEELS) == shown


def test_the_900_keeps_its_remote_assistant_off(tmp_path):
    user = _user(_build(tmp_path, "harmony-900", remote_assistant=True))
    assert user.findtext(TRAINING_WHEELS) == "False"
