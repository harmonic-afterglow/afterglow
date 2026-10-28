"""A Harmony 900's RC5/RC6 commands become portable protocols, toggle bit and all.

An RC5/RC6 program declares its toggle bit twice: in the program (an element's toggle
position) and in `<Protocols>` as `ToggleBit1`. The importer used to keep such blocks
native "until that metadata has a portable representation", so every RC6 command - Xbox
360, Windows Media Center, the MCE keyboard - came in as a Code for the 900's own program
("backend-opaque"). A 900 rebuilt it; a tester's 1100 build of those devices stopped with
"a backend-opaque signal has nothing to play back" at every one.

The metadata has its portable form: `promote` carries the program's toggle position as
the portable `toggle` state, and a 900 build writes `ToggleBit1` back from the block it
assembles. In the donor configurations every declaration - RC6 at 14, two RC5 variants
at 1 - equals its block's position, and a rebuild from the promoted protocols gives the
same IrProto.bin and the same `<Protocols>`, with or without the carried metadata.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from afterglow import ir_signal, project_devices
from afterglow.backends.harmony_pk import backend, irproto, ssir_sequence
from afterglow.backends.harmony_pk.builder import assemble

# The RC6 program as a 900 configuration carries it, from an import.
RC6_BLOCK = json.loads(
    (Path(__file__).parent / "fixtures" / "native-rc6-mce-block.json").read_text())
XBOX_360_OK = "0x08002C0100000100FFC02F8C00"       # fields the RC6-MCE decoder refuses
MCE_KEYBOARD_BACK = "0x0800F40103000100FFC1EF7000"


def _native(code, name="OK", definition=RC6_BLOCK):
    native = {"format": "command-code", "code": code, "protocol_block_id": "6bd42e0eea79"}
    if definition is not None:
        native["protocol_definition"] = definition
    return ir_signal.backend_opaque({"harmony-pk": native}, name=name)


def _device(**signals):
    return {"id": "xbox", "label": "Xbox 360", "mfr": "Microsoft", "model": "Xbox 360",
            "commands": [[name, name, "", "", None] for name in signals],
            "signals": signals}


def test_a_saved_native_rc6_code_becomes_a_portable_protocol():
    device = _device(OK=_native(XBOX_360_OK), Back=_native(MCE_KEYBOARD_BACK, "Back"))
    assert backend.promote_native_signals(device) == 2
    for signal in device["signals"].values():
        assert signal["kind"] == "protocol"
    (definition,) = device["portable_protocol_definitions"].values()
    assert "toggle" in definition.get("state", {}), "the toggle bit is kept"


def test_opening_a_project_converts_them():
    project = {"settings": {"remote": "harmony-1100"},
               "devices": [_device(OK=_native(XBOX_360_OK))], "activities": []}
    project_devices.normalise_project(project)
    assert project["devices"][0]["signals"]["OK"]["kind"] == "protocol"


@pytest.mark.parametrize("code", [XBOX_360_OK, MCE_KEYBOARD_BACK])
def test_the_1100_plays_it_as_rc6_with_its_toggle(code):
    device = _device(OK=_native(code))
    backend.promote_native_signals(device)
    library = device["portable_protocol_definitions"]
    carrier, variants = ssir_sequence._renders(device["signals"]["OK"], library)
    assert carrier == 36200
    assert len(variants) == 2, "RC6 alternates its toggle bit between presses"
    first, second = (press for press, _hold in variants)
    assert first[:2] == second[:2] == [2632, -900], "the RC6 leader"
    assert first != second, "the two presses differ in the toggle bit"


def test_a_code_without_its_program_stays_native():
    device = _device(OK=_native(XBOX_360_OK, definition=None))
    assert backend.promote_native_signals(device) == 0
    with pytest.raises(ValueError, match="nothing to play back"):
        ssir_sequence._renders(device["signals"]["OK"], None)


def test_a_900_build_declares_the_toggle_bit_from_the_block():
    """Nothing carried - a device added fresh, or moved from another project - and the
    declaration still comes out as Logitech writes it."""
    payload = irproto.assemble(["6bd42e0eea79"], {"6bd42e0eea79": RC6_BLOCK})
    assert assemble._toggle_declarations(payload) == {
        0: '<CodeSequence index="0"><ToggleBit1>14</ToggleBit1></CodeSequence>'}


def test_the_1100_plays_a_ones_two_recordings_in_turn():
    signal = ir_signal.waveform([2632, -900, 441, -40000], carrier_hz=36200,
                                alternate={"pulses_us": [2632, -900, 882, -39559]})
    _carrier, variants = ssir_sequence._renders(signal, None)
    assert [press for press, _hold in variants] == [[2632, -900, 441, -40000],
                                                    [2632, -900, 882, -39559]]


def test_opening_a_project_saves_it_converted_and_keeps_the_old_one(
        qapp_or_skip, tmp_path, monkeypatch):
    """At launch the last project is reopened through the same path: a project saved with
    native-only commands is rewritten with portable ones, the old file in Backups."""
    from afterglow import project_backups
    from afterglow.qt.QtCore import QSettings
    from afterglow.gui import app
    monkeypatch.setattr(project_backups.paths, "user_folder",
                        lambda kind: tmp_path / "Backups" if kind == "backups" else tmp_path)
    QSettings("Afterglow", "Afterglow").remove(app.LAST_PROJECT_KEY)
    window = app.MainWindow()
    window._write_project(tmp_path / "living-room.json")
    saved = json.loads((tmp_path / "living-room.json").read_text())
    saved["settings"]["remote"] = "harmony-1100"
    saved["devices"] = [_device(OK=_native(XBOX_360_OK))]
    (tmp_path / "living-room.json").write_text(json.dumps(saved))
    try:
        window._load_project_file(tmp_path / "living-room.json")
        on_disk = json.loads((tmp_path / "living-room.json").read_text())
        assert on_disk["devices"][0]["signals"]["OK"]["kind"] == "protocol"
        (earlier,) = [path for path in project_backups.history(tmp_path / "living-room.json")
                      if "backend-opaque" in path.read_text()]
        assert earlier.exists()
        assert "Converted 1 command" in window.status.currentMessage()
    finally:
        QSettings("Afterglow", "Afterglow").remove(app.LAST_PROJECT_KEY)


def test_the_1100_ends_a_press_with_a_silent_release(tmp_path):
    """Logitech's PS3 adapter waits 6 s after Stop; the 1100 stores no release."""
    definition = {
        "schema": "afterglow-ir-protocol/1", "id": "test-stop-spacer",
        "modulation": {"kind": "carrier", "carrier_hz": 38_000}, "parameters": {},
        "bursts": {"key": [4000, -4500, 400, -50_000], "spacer": [-6_000_000]},
        "alphabets": {},
        "frames": {"key": {"segments": [{"burst": "key"}]},
                   "spacer": {"segments": [{"burst": "spacer"}]}},
        "transmission": {"press": [{"frame": "key"}], "hold": [{"frame": "key"}],
                         "release": [{"frame": "spacer"}]},
    }
    signal = ir_signal.protocol_signal("test-stop-spacer", {})
    _carrier, ((press, hold),) = ssir_sequence._renders(signal,
                                                        {"test-stop-spacer": definition})
    assert sum(map(abs, press)) == 4000 + 4500 + 400 + 50_000 + 6_000_000
    assert sum(map(abs, hold)) == 4000 + 4500 + 400 + 50_000


def test_the_1100_ends_a_press_with_a_keyboard_release(tmp_path):
    """An MCE keyboard key is a key frame, then a frame that releases every key. The
    1100 played only the key, so Win+1 was held and never fired; it works on a 900."""
    definition = {
        "schema": "afterglow-ir-protocol/1", "id": "test-key-up",
        "modulation": {"kind": "carrier", "carrier_hz": 36_000}, "parameters": {},
        "bursts": {"key": [2795, -270, 606, -74500], "up": [2795, -270, 303]},
        "alphabets": {},
        "frames": {"key": {"segments": [{"burst": "key"}]},
                   "up": {"segments": [{"burst": "up"}]}},
        "transmission": {"press": [{"frame": "key"}], "hold": [{"frame": "key"}],
                         "release": [{"frame": "up"}]},
    }
    signal = ir_signal.protocol_signal("test-key-up", {})
    _carrier, ((press, hold),) = ssir_sequence._renders(signal, {"test-key-up": definition})
    assert press == [2795, -270, 606, -74500, 2795, -270, 303, -40_000]
    assert hold == [2795, -270, 606, -74500]
