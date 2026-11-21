"""What a first-time user and a tester ran into with the 5xx: its settings (the theme
and the language) could not be reached, it offered an empty Type list, a 900 project
moved to a 525 would not build, the key left of 0 was dropped on the way to and from the
other remotes, its Timing page offered a wait it does not build, and two buttons could
be cut to the same label with nothing said."""
from __future__ import annotations

import contextlib
import copy
import io
from pathlib import Path

import pytest

from afterglow import migrate, remotes
from test_harmony_one_activities import PROJECT

ROOT = Path(__file__).resolve().parents[1]
FIVE_XX = ["harmony-515", "harmony-520", "harmony-525", "harmony-550", "harmony-555",
           "harmony-xbox360"]


@pytest.mark.parametrize("remote", FIVE_XX)
def test_a_5xx_has_remote_settings_for_what_it_declares(remote):
    profile = remotes.get(remote)
    assert "settings" in profile.tabs
    assert {"theme", "language", "output_file"} <= set(profile.settings_fields)


@pytest.mark.parametrize("remote", FIVE_XX)
def test_a_5xx_offers_no_wait_it_does_not_build(remote):
    """The apps' wait after a TV comes on: offered, then "not built for this remote"."""
    assert "app_power_delay" not in remotes.get(remote).interface["timing"]


def test_a_550_offers_no_type(qapp_or_skip):
    from afterglow.gui.device_wizard import IdentityPage
    project = {"devices": [], "activities": [], "settings": {"remote": "harmony-550"}}
    page = IdentityPage({"id": "1", "type": "Receiver"}, project=project)
    assert not page._form.isRowVisible(page.type_combo)
    assert page.type_combo.currentData() == "Receiver"           # kept


@pytest.mark.parametrize("source, target, key", [
    ("harmony-650", "harmony-525", "NumberStar"), ("harmony-650", "harmony-555", "Clear"),
    ("harmony-525", "harmony-555", "Clear"), ("harmony-555", "harmony-515", "NumberStar"),
    ("harmony-525", "harmony-one", "NumberPlus"), ("harmony-555", "harmony-900", "NumberPlus")])
def test_the_key_left_of_0_keeps_its_command(source, target, key):
    """NumberPlus on the One, 650, 700 and 900, NumberStar on the 515, 525 and Xbox 360,
    Clear on the 555: one key, and a command on it was dropped moving between them."""
    held = {"harmony-650": "NumberPlus", "harmony-525": "NumberStar",
            "harmony-555": "Clear"}[source]
    project = {"settings": {"remote": source}, "activities": [],
               "devices": [{"id": "tv", "label": "TV", "commands": [
                   ["Clear", "Clear", "", "", held]]}]}
    moved, report = migrate.migrate(project, target)
    assert moved["devices"][0]["commands"][0][4] == key
    assert not [row for row in report if row["change"] == "removed"]


@pytest.mark.slow
@pytest.mark.parametrize("remote", ["harmony-525", "harmony-555"])
def test_an_off_list_naming_a_gone_device_still_builds(tmp_path, remote):
    from afterglow.build_service import ConfigBuildService
    project = copy.deepcopy(PROJECT)
    project["power_off_all"] = ["tv", "92650900", "amp"]
    project["settings"] = {"remote": remote, "out_file": str(tmp_path / "out.ezhex")}
    with contextlib.redirect_stdout(io.StringIO()):
        built = ConfigBuildService(ROOT, lambda _m: None).build(project)
    assert Path(built).stat().st_size > 0


@pytest.mark.slow
def test_a_label_cut_to_fit_and_two_alike_are_said(tmp_path):
    from afterglow.build_service import ConfigBuildService
    project = copy.deepcopy(PROJECT)
    tv = project["devices"][0]
    tv["commands"] = [[name, label, *rest] for name, label, *rest in tv["commands"]]
    for row in tv["commands"]:
        if row[0] in ("InputHdmi1", "InputHdmi2"):
            row[1] = row[0].replace("InputHdmi", "InputComponentHdmi")
    project["settings"] = {"remote": "harmony-525", "out_file": str(tmp_path / "out.ezhex")}
    logs: list[str] = []
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(ROOT, logs.append).build(project)
    said = "\n".join(logs)
    assert "'InputComponentHdmi1' is cut short" in said
    assert "look the same on the screen" in said
