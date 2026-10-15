"""A Harmony 1100 configuration has to survive the remote's own Lua, not only our readers.

The 1100 builds its behaviour layer from the configuration at boot, as the 900 does, with
scripts of its own that are less forgiving: its State.lua lacks the nil checks the 900's
gained, so a state the 900 shrugs off stops the 1100 (afterglow-research/harmony-1100.md).
These boot the remote's scripts on each configuration and start every activity.

The scripts are Logitech's, from firmware 63.7.7 (Region 12, share/lua/5.1/ethanol), and
are never part of this repository: point `AFTERGLOW_1100_LUA` at a folder holding them, or
keep it as `lua_src_1100/` beside the checkout. The stand-ins for the remote's services
are ours: the 900's (`harmony_900_lua/`) and the luasocket the 1100 also asks for
(`harmony_1100_lua/`). Without the scripts or `lua5.1` the tests skip.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from afterglow import ezhex

HERE = Path(__file__).resolve().parent
PREFIX = "share__lua__5.1__ethanol__"


def _scripts() -> Path | None:
    for folder in filter(None, (os.environ.get("AFTERGLOW_1100_LUA"),
                                HERE.parent / "lua_src_1100",
                                HERE.parent.parent / "lua_src_1100")):
        if (Path(folder) / f"{PREFIX}HAO.lua").is_file():
            return Path(folder)
    return None


@pytest.fixture(scope="module")
def remote_lua(tmp_path_factory):
    scripts, lua = _scripts(), shutil.which("lua5.1")
    if scripts is None or lua is None:
        pytest.skip("needs the Harmony 1100's Lua scripts and lua5.1")
    root = tmp_path_factory.mktemp("remote1100")
    (root / "lua" / "lxp").mkdir(parents=True)
    (root / "lua" / "socket").mkdir()
    for script in scripts.glob(f"{PREFIX}*.lua"):
        (root / "lua" / script.name[len(PREFIX):].removeprefix("objects__")).symlink_to(
            script)
    shutil.copy(HERE / "harmony_900_lua" / "env_svc.lua", root / "lua" / "env_svc.lua")
    shutil.copy(HERE / "harmony_900_lua" / "lxp" / "lom.lua", root / "lua" / "lxp" / "lom.lua")
    shutil.copy(HERE / "harmony_1100_lua" / "socket" / "http.lua",
                root / "lua" / "socket" / "http.lua")
    shutil.copy(HERE / "harmony_1100_lua" / "run.lua", root / "run.lua")
    return root, lua


def run(remote_lua, config: Path, tmp_path: Path) -> dict[str, str]:
    """Boot the 1100's Lua on a configuration and start each of its activities."""
    root, lua = remote_lua
    tree = tmp_path / f"tree-{config.stem}"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(config), str(tree))
    xml = (tree / "userconfig" / "UserConfiguration.xml").read_text(errors="replace")
    ids = [i for i in re.findall(r"<Activity><Id>(-?\d+)</Id>", xml) if i != "-1"]
    result = subprocess.run([lua, "run.lua", str(tree), *ids], cwd=root,
                            capture_output=True, text=True, errors="replace", timeout=120)
    out = {}
    for line in result.stderr.splitlines():
        name, _, rest = line.partition(" ")
        if name == "BOOT" or name in ids:
            out[name] = rest
    return out


def assert_runs(outcomes: dict, what: str):
    assert outcomes.get("BOOT") == "ok", f"{what}: the 1100's Lua fails to load it: " \
        f"{outcomes.get('BOOT')}"
    for name, outcome in outcomes.items():
        assert outcome.startswith("ok"), f"{what}: activity {name}: {outcome}"


def test_the_harness_runs_every_real_configuration(remote_lua, configs_1100, tmp_path):
    """The control: Logitech's own configurations boot, and every activity starts and
    sends something, or the harness is wrong and nothing else here means anything."""
    for config in configs_1100:
        outcomes = run(remote_lua, config, tmp_path)
        assert_runs(outcomes, config.name)
        assert all(int(rest.split()[1]) > 0 for name, rest in outcomes.items()
                   if name != "BOOT")


def test_a_rebuilt_real_configuration_still_runs(remote_lua, configs_1100, tmp_path):
    from afterglow import build_service, importer
    for index, config in enumerate(configs_1100):
        tree, out = tmp_path / f"import-{index}", tmp_path / f"rebuilt-{index}.ezhex"
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(str(config), str(tree))
            project = importer.build_project(str(tree))
            project["settings"].update(out_file=str(out), first_name="T", last_name="U")
            build_service.ConfigBuildService(tmp_path, lambda _m: None).build(project)
        before, after = run(remote_lua, config, tmp_path), run(remote_lua, out, tmp_path)
        assert_runs(after, f"{config.name} rebuilt")
        # each activity starts the same number of commands as Logitech's did
        assert after == before, config.name


def test_a_project_made_here_runs(remote_lua, configs_1100, tmp_path):
    """New activities - with the tabs a new one is now given - over imported devices."""
    from afterglow import build_service, importer
    tree, out = tmp_path / "import", tmp_path / "made.ezhex"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(configs_1100[0]), str(tree))
        project = importer.build_project(str(tree))
    tv = project["devices"][0]
    project["activities"] = [
        {"id": "70000001", "label": "Watch", "type": "VirtualGeneric",
         "display": tv["id"], "control": tv["id"],
         "soft_buttons": [["Go", tv["id"], tv["commands"][0][0]], None]},
        {"id": "70000002", "label": "Disc", "type": "VirtualDvd",
         "display": tv["id"], "control": tv["id"]}]
    project["settings"].update(out_file=str(out), first_name="T", last_name="U")
    with contextlib.redirect_stdout(io.StringIO()):
        build_service.ConfigBuildService(tmp_path, lambda _m: None).build(project)
    assert_runs(run(remote_lua, out, tmp_path), "made here")
