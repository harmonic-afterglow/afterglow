"""A project whose Off list still names a device it no longer has - left by a delete from
before deleting cleaned the Off list - built on the 900, which passes it over, and on no
other remote: "Off names device '92650900', which the project does not have", from a
tester's 900 project moved to a 525. Every builder now passes it over, and moving a
project to another remote takes it out and says so."""
from __future__ import annotations

import contextlib
import copy
import io
from pathlib import Path

import pytest

from afterglow import migrate
from test_harmony_one_activities import PROJECT

ROOT = Path(__file__).resolve().parents[1]


def _with_a_stale_off():
    project = copy.deepcopy(PROJECT)
    project["power_off_all"] = ["tv", "92650900", "amp"]
    return project


@pytest.mark.slow
@pytest.mark.parametrize("remote", ["harmony-900", "harmony-one", "harmony-650",
                                    "harmony-700", "harmony-800"])
def test_an_off_list_naming_a_gone_device_still_builds(tmp_path, remote):
    from afterglow.build_service import ConfigBuildService
    project = _with_a_stale_off()
    project["settings"] = {"remote": remote, "out_file": str(tmp_path / "out.ezhex")}
    with contextlib.redirect_stdout(io.StringIO()):
        built = ConfigBuildService(ROOT, lambda _m: None).build(project)
    assert Path(built).stat().st_size > 0


def test_moving_a_project_takes_a_gone_device_out_of_off_and_says_so():
    project = _with_a_stale_off()
    project["settings"] = {"remote": "harmony-900"}
    moved, report = migrate.migrate(project, "harmony-650")
    assert moved["power_off_all"] == ["tv", "amp"]
    assert project["power_off_all"] == ["tv", "92650900", "amp"]       # left as it was
    [row] = [row for row in report if row["subject"] == "Off"]
    assert row["change"] == "removed" and "1 device" in row["detail"]


def test_a_clean_off_list_is_not_mentioned():
    project = copy.deepcopy(PROJECT)
    project["power_off_all"] = ["tv", "amp"]
    project["settings"] = {"remote": "harmony-900"}
    _moved, report = migrate.migrate(project, "harmony-650")
    assert not [row for row in report if row["subject"] == "Off"]
