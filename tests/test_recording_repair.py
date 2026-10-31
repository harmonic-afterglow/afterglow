"""Recordings an older Afterglow put on an 1100 become their protocols again.

An 1100 keeps no protocols: a build renders each command into the sequences it plays,
and importing the remote reads them back as recordings. A tester's 900 devices, built
for the 1100 by 0.3.0-beta.5 and imported again, kept that release's renderings through
every later fix - 871 of 872 commands were exactly 0.3.0-beta.4's press with no release,
one was beta.5's press with its silent release, and Win+1 never worked. Opening the
project with the same devices saved elsewhere with their protocols repairs exactly those.
"""
from __future__ import annotations

import json
from copy import deepcopy

from afterglow import device_json, ir_signal, project_bundle, recording_repair
from afterglow.backends.harmony_pk import NAME, render_history

KEY_UP = {
    "schema": "afterglow-ir-protocol/1", "id": "test-key-up",
    "modulation": {"kind": "carrier", "carrier_hz": 36_000}, "parameters": {},
    "bursts": {"key": [2795, -270, 606, -74500], "up": [2795, -270, 303]},
    "alphabets": {},
    "frames": {"key": {"segments": [{"burst": "key"}]},
               "up": {"segments": [{"burst": "up"}]}},
    "transmission": {"press": [{"frame": "key"}], "hold": [{"frame": "key"}],
                     "release": [{"frame": "up"}]},
}
SILENT_UP = {**deepcopy(KEY_UP), "id": "test-silent-up",
             "bursts": {"key": [4000, -4500, 400, -50_000], "up": [-6_000_000]}}
LIBRARY = {"test-key-up": KEY_UP, "test-silent-up": SILENT_UP}
GENERATION = {generation.id: generation for generation in render_history.GENERATIONS}


def _keyboard(protocol="test-key-up", label="MCE Keyboard"):
    signal = ir_signal.protocol_signal(protocol, {})
    return {"id": "kbd", "label": label, "mfr": "Microsoft", "model": "MCE Keyboard",
            "commands": [["Win1", "Win1", "", "", None]], "signals": {"Win1": signal},
            "portable_protocol_definitions": {protocol: LIBRARY[protocol]}}


def _from_the_1100(device, generation, **change):
    """`device` as an 1100 built by `generation` gives it back."""
    out = {**deepcopy(device), **change}
    out.pop("portable_protocol_definitions")
    (pulses,) = render_history.presses(device["signals"]["Win1"], LIBRARY,
                                       GENERATION[generation])[:1]
    out["signals"] = {"Win1": ir_signal.waveform(
        pulses, name="Win1", carrier_hz=36_000,
        native={NAME: {"format": "device-sequence", "press": {}}})}
    return out


def test_an_old_rendering_becomes_its_protocol_again():
    saved = _keyboard()
    project = {"devices": [_from_the_1100(saved, "1100-render-press-only")]}
    assert recording_repair.repair(project, [saved]) == 1
    (device,) = project["devices"]
    assert device["signals"]["Win1"] == saved["signals"]["Win1"]
    assert device["portable_protocol_definitions"] == {"test-key-up": KEY_UP}
    (record,) = project["repairs"]
    assert record["rendering"] == "1100-render-press-only" and record["commands"] == 1
    assert recording_repair.repair(project, [saved]) == 0, "nothing left to repair"


def test_each_release_that_rendered_differently_is_known():
    saved = _keyboard("test-silent-up")
    project = {"devices": [_from_the_1100(saved, "1100-render-silent-release")]}
    assert recording_repair.repair(project, [saved]) == 1
    assert project["repairs"][0]["rendering"] == "1100-render-silent-release"


def test_a_rendering_from_this_release_is_still_repaired():
    """The current rendering is a generation too: a recording of it is still better as
    the protocol, which the next fix can render again."""
    saved = _keyboard()
    project = {"devices": [_from_the_1100(saved, "1100-render-release")]}
    assert recording_repair.repair(project, [saved]) == 1


def test_a_genuine_recording_is_kept():
    saved = _keyboard()
    recorded = _from_the_1100(saved, "1100-render-press-only")
    recorded["signals"]["Win1"]["pulses_us"][2] += 30        # learned, not rendered
    project = {"devices": [recorded]}
    assert recording_repair.repair(project, [saved]) == 0
    assert project["devices"][0]["signals"]["Win1"]["kind"] == "waveform"
    assert "repairs" not in project


def test_only_the_same_device_is_asked():
    saved = _keyboard()
    other = {**_from_the_1100(saved, "1100-render-press-only"),
             "label": "Fan", "mfr": "Honeywell", "model": "HY-280"}
    project = {"devices": [other]}
    assert recording_repair.repair(project, [saved]) == 0


def test_the_same_device_is_found_by_label_when_its_model_differs():
    saved = _keyboard()
    renamed = _from_the_1100(saved, "1100-render-press-only", mfr="", model="")
    assert recording_repair.repair({"devices": [renamed]}, [saved]) == 1


def test_a_recording_with_no_protocol_anywhere_is_kept():
    saved = _keyboard()
    project = {"devices": [_from_the_1100(saved, "1100-render-press-only")]}
    assert recording_repair.repair(project, []) == 0


def test_the_protocols_are_found_in_the_library_and_other_projects(tmp_path):
    library, projects = tmp_path / "Library", tmp_path / "Projects"
    (library / "devices").mkdir(parents=True)
    (projects / "unpacked").mkdir(parents=True)
    saved = _keyboard()
    spec = {"schema": device_json.PORTABLE_SCHEMA, "manufacturer": "Microsoft",
            "model": "MCE Keyboard", "names": ["MCE Keyboard"], "type": "Misc",
            "commands": [{"name": "Win1", "label": "Win1",
                          "signal": saved["signals"]["Win1"]}],
            "portable_protocol_definitions": {"test-key-up": KEY_UP}}
    device_json.save(spec, library / "devices" / "mce-keyboard.json")
    (projects / "unpacked" / "project.json").write_text(json.dumps({"devices": [saved]}))
    (projects / "broken.json").write_text("{")
    found = recording_repair.sources(library, projects)
    assert len(found) == 2
    for source in found:
        project = {"devices": [_from_the_1100(saved, "1100-render-press-only")]}
        assert recording_repair.repair(project, [source]) == 1


def test_a_shared_project_says_which_version_wrote_it(tmp_path):
    from afterglow import __version__
    project = {"settings": {"remote": "harmony-1100"}, "devices": [], "activities": []}
    project_bundle.export(project, tmp_path / "p.afterglow")
    opened = project_bundle.open_bundle(tmp_path / "p.afterglow", tmp_path / "p")
    assert opened["saved_by"] == __version__
    assert "saved_by" not in project, "the open project is left as it was"


def test_opening_a_project_repairs_it_and_saves(qapp_or_skip, tmp_path, monkeypatch):
    from afterglow import __version__, project_backups
    from afterglow.gui import app
    from afterglow.qt.QtCore import QSettings
    monkeypatch.setattr(project_backups.paths, "user_folder",
                        lambda kind: tmp_path / "Backups" if kind == "backups" else tmp_path)
    saved = _keyboard()
    monkeypatch.setattr(recording_repair, "sources", lambda *args: [saved])
    QSettings("Afterglow", "Afterglow").remove(app.LAST_PROJECT_KEY)
    window = app.MainWindow()
    path = tmp_path / "living-room.json"
    window._write_project(path)
    project = json.loads(path.read_text())
    project["settings"]["remote"] = "harmony-1100"
    project["devices"] = [_from_the_1100(saved, "1100-render-press-only")]
    path.write_text(json.dumps(project))
    try:
        window._load_project_file(path)
        on_disk = json.loads(path.read_text())
        assert on_disk["devices"][0]["signals"]["Win1"]["kind"] == "protocol"
        assert on_disk["saved_by"] == __version__
        assert on_disk["repairs"][0]["rendering"] == "1100-render-press-only"
        assert "Repaired 1 command" in window.status.currentMessage()
    finally:
        QSettings("Afterglow", "Afterglow").remove(app.LAST_PROJECT_KEY)
