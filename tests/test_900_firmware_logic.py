"""A Harmony 900 configuration has to survive the remote's own Lua, not only our readers.

The remote builds its behaviour layer - devices, states, activities, Help, Remote info,
the RF service - by running Lua over the configuration at boot. A configuration every
reader here accepted crashed that Lua on a Harmony 900 (`State.lua` refuses a state with
neither values nor a range), and the remote lost Help, Remote info and its RF settings.
Nothing structural caught it, because the check that mattered is the remote's.

So these run the remote's own scripts. They are Logitech's and decompiled from its
firmware, so they are never part of this repository: point `AFTERGLOW_900_LUA` at the
folder holding them, or keep it as `lua_src/` beside the checkout. The stand-ins for the
remote's C services are ours, in `harmony_900_lua/`. Without the scripts or `lua5.1` the
tests skip, the way the real-configuration tests do.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from afterglow import ezhex

HERE = Path(__file__).resolve().parent
STUBS = HERE / "harmony_900_lua"
EVENTS = {
    "Help": "<Event><Payload><Name>Help</Name><Params><Id>-1</Id></Params></Payload></Event>",
    "RemoteInfoQuery": "<Event><Payload><Name>RemoteInfoQuery</Name></Payload></Event>",
    "RF:AvailableReceiversQuery":
        "<Event><Payload><Name>RF:AvailableReceiversQuery</Name></Payload></Event>",
}
PREFIX = "share__lua__5.1__ethanol__"


def _scripts() -> Path | None:
    candidates = [os.environ.get("AFTERGLOW_900_LUA"), HERE.parent / "lua_src",
                  HERE.parent.parent / "lua_src"]
    for folder in filter(None, candidates):
        folder = Path(folder)
        if (folder / f"{PREFIX}HAO.lua").is_file():
            return folder
    return None


@pytest.fixture(scope="module")
def remote_lua(tmp_path_factory):
    """A directory laid out the way the scripts `require` each other, or skip."""
    scripts, lua = _scripts(), shutil.which("lua5.1")
    if scripts is None or lua is None:
        pytest.skip("needs the Harmony 900's Lua scripts and lua5.1")
    root = tmp_path_factory.mktemp("remote")
    (root / "lua" / "lxp").mkdir(parents=True)
    for script in scripts.glob(f"{PREFIX}*.lua"):
        name = script.name[len(PREFIX):].removeprefix("objects__")
        (root / "lua" / name).symlink_to(script)
    shutil.copy(STUBS / "env_svc.lua", root / "lua" / "env_svc.lua")
    shutil.copy(STUBS / "lxp" / "lom.lua", root / "lua" / "lxp" / "lom.lua")
    shutil.copy(STUBS / "run.lua", root / "run.lua")
    return root, lua


def boot(remote_lua, config: Path, tmp_path: Path) -> dict[str, str]:
    """Boot the remote's Lua on a configuration and send it each touchscreen event."""
    root, lua = remote_lua
    tree = tmp_path / f"tree-{config.stem}"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(config), str(tree))
    result = subprocess.run([lua, "run.lua", str(tree), *EVENTS.values()], cwd=root,
                            capture_output=True, text=True, errors="replace", timeout=120)
    outcomes = {}
    for line in result.stderr.splitlines():
        name, _, rest = line.partition(" ")
        if name in ("BOOT", *EVENTS):
            outcomes[name] = rest
    return outcomes


def assert_answers(outcomes: dict[str, str], what: str):
    assert outcomes.get("BOOT") == "ok", f"{what}: the remote's Lua fails to load it: " \
        f"{outcomes.get('BOOT')}"
    for name in EVENTS:
        assert outcomes.get(name, "").startswith("ok"), \
            f"{what}: {name} gets no answer: {outcomes.get(name)}"


def test_the_harness_loads_every_real_configuration(remote_lua, configs, tmp_path):
    """The control: Logitech's own configurations boot and answer, or the harness is
    wrong and nothing else here means anything."""
    for config in configs:
        assert_answers(boot(remote_lua, config, tmp_path), config.name)


def test_a_rebuilt_real_configuration_still_boots(remote_lua, configs, tmp_path):
    from afterglow import build_service, importer

    for index, config in enumerate(configs):
        tree = tmp_path / f"import-{index}"
        out = tmp_path / f"rebuilt-{index}.ezhex"
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(str(config), str(tree))
            project = importer.build_project(str(tree))
            project["settings"].update(out_file=str(out), first_name="T", last_name="U")
            build_service.ConfigBuildService(tmp_path, lambda _m: None).build(project)
        assert_answers(boot(remote_lua, out, tmp_path), f"{config.name} rebuilt")


def _cycling(values):
    from afterglow import ir_signal

    def nec(command):
        return ir_signal.protocol_signal("nec1", {"address": 1, "command": command})
    cycle = {"next": ["Source"], **({"values": values} if values else {})}
    return {"settings": {}, "activities": [], "devices": [{
        "schema": "afterglow-project-device/1", "id": "1", "label": "Cello",
        "type": "Receiver", "mfr": "Test", "model": "Cycle",
        "commands": [["PowerToggle", "PowerToggle", "", "", None],
                     ["Source", "Source", "", "", None]],
        "signals": {"PowerToggle": nec(1), "Source": nec(2)},
        "inputs": [], "input_cycle": cycle}]}


@pytest.mark.parametrize("values", [["CD", "Tuner"], None])
def test_a_device_that_can_only_cycle_its_inputs_boots(remote_lua, build, tmp_path, values):
    """With its input names it is written as Logitech writes it; without them - a project
    from before they were kept - the cycle is left out rather than crash the remote."""
    assert_answers(boot(remote_lua, build(_cycling(values)), tmp_path), "cycling device")
