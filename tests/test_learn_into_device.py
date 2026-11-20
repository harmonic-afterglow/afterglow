"""A command learned off the original remote can be added to a device that already exists.

The Commands tab of the device editor has always had "Learn from remote…", but nothing
checked that a learned key survives the editor and reaches the remote: these drive the
editor with a capture standing in for libconcord and build the result.
"""
from __future__ import annotations

import contextlib
import io
import re
import zipfile

from afterglow import concord, ezhex, ir_signal


def _device():
    names = ["PowerToggle", "VolumeUp"]
    return {"schema": "afterglow-project-device/1", "id": "1", "label": "TV",
            "type": "Television", "mfr": "JVC", "model": "AV-32D201",
            "commands": [[n, n, "", "", None] for n in names],
            "signals": {n: ir_signal.protocol_signal("nec1", {"address": 3, "command": i})
                        for i, n in enumerate(names)}}


def _learn(editor, monkeypatch, name, capture):
    from afterglow.qt.QtWidgets import QInputDialog, QMessageBox

    from afterglow.gui import remote_ops
    monkeypatch.setattr(concord, "available", lambda: True)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (name, True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(remote_ops, "run_with_progress",
                        lambda *a, **k: (True, "", capture))
    editor.page_cmds._learn_command()


def test_a_key_learned_into_an_existing_device_is_built(qapp_or_skip, monkeypatch, build):
    from afterglow.gui.device_wizard import DeviceEditor
    capture = concord.learned_capture(38000, [900, 450] * 16 + [900, 20000], "ServiceMenu")
    device = _device()
    editor = DeviceEditor([], existing=device, project={"devices": [device]})
    _learn(editor, monkeypatch, "ServiceMenu", capture)
    spec = editor._collect()

    assert [c[0] for c in spec["commands"]] == ["PowerToggle", "VolumeUp", "ServiceMenu"]
    assert spec["signals"]["ServiceMenu"] == capture
    assert spec["signals"]["VolumeUp"] == device["signals"]["VolumeUp"]

    with contextlib.redirect_stdout(io.StringIO()):
        out = build({"devices": [spec], "activities": []})
    raw = out.read_bytes()
    _h, start, size, _c = ezhex._split(raw)
    payload = zipfile.ZipFile(io.BytesIO(raw[start:start + size]))
    xml = payload.read("userconfig/UserConfiguration.xml").decode()
    [command] = re.findall(r"<Command>(?:(?!</Command>).)*?<Name>ServiceMenu</Name>.*?"
                           r"</Command>", xml, re.S)
    assert "<Protocol>-1</Protocol>" in command          # a recorded capture
    assert any(name.endswith("SsIr.bin") for name in payload.namelist())


def test_learning_without_libconcord_says_why_instead_of_greying_out(qapp_or_skip,
                                                                     monkeypatch):
    from afterglow.qt.QtWidgets import QMessageBox

    from afterglow.gui.device_wizard import CommandsPage
    told = []
    monkeypatch.setattr(concord, "available", lambda: False)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[1]))
    page = CommandsPage(_device())
    assert page.learn_btn.isEnabled()
    page.learn_btn.click()
    assert told == ["Learning needs libconcord"]
    assert page.learned_captures() == {}


def test_a_key_is_learned_twice_and_the_two_compared():
    from afterglow.gui.device_wizard import same_capture
    one = {"carrier_hz": 38000, "pulses_us": [9000, -4500, 560, -560, 560, -40000]}
    near = {"carrier_hz": 38500, "pulses_us": [8900, -4450, 600, -540, 590, -90000]}
    other = {"carrier_hz": 38000, "pulses_us": [9000, -4500, 560, -1690, 560, -40000]}
    assert same_capture(one, near)                      # the trailing gap is not compared
    assert not same_capture(one, other)                 # a different bit
    assert not same_capture(one, dict(one, pulses_us=one["pulses_us"][:4]))


def test_a_key_held_for_longer_still_matches_and_keeps_the_frames_both_sent():
    # A tester's One learned a key as three frames, then two: the key sends its frame
    # again while it is held, so the presses differ only in how long it was held.
    from afterglow.gui.device_wizard import common_capture, same_capture
    frame = [9000, -4500] + [560, -560, 560, -1690] * 16 + [560, -40000]
    three = {"carrier_hz": 38145, "pulses_us": frame * 3}
    two = {"carrier_hz": 38150, "pulses_us": frame * 2}
    assert same_capture(three, two)
    assert common_capture(three, two)["pulses_us"] == frame * 2
    assert common_capture(two, three)["pulses_us"] == frame * 2
    # let go part-way through the third frame: the two whole ones are kept
    assert common_capture(three, {"carrier_hz": 38000,
                                  "pulses_us": frame * 2 + frame[:20]})["pulses_us"] \
        == frame * 2
    # a different first frame is still a different code
    other = list(frame)
    other[5] = -560
    assert not same_capture(three, {"carrier_hz": 38145, "pulses_us": other * 3})
    # a press that caught only part of a frame is not the code
    assert not same_capture(three, {"carrier_hz": 38938, "pulses_us": frame[:40]})


def test_two_presses_that_differ_are_not_kept(qapp_or_skip, monkeypatch):
    from afterglow.gui import device_wizard, remote_ops
    from afterglow.qt.QtWidgets import QInputDialog, QMessageBox
    device = _device()
    editor = device_wizard.DeviceEditor([], existing=device, project={"devices": [device]})
    first = concord.learned_capture(38000, [900, 450] * 16 + [900, 20000], "X")
    second = concord.learned_capture(38000, [900, 1350] * 16 + [900, 20000], "X")
    presses = iter([first, second])
    monkeypatch.setattr(concord, "available", lambda: True)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("X", True)))
    monkeypatch.setattr(remote_ops, "run_with_progress",
                        lambda *a, **k: (True, "", next(presses)))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: asked.append(a[1]) or QMessageBox.StandardButton.Cancel))
    editor.page_cmds._learn_command()
    assert asked == ["The two presses differ"]
    assert "X" not in [row[0] for row in editor.page_cmds.get_commands()]


def test_a_learned_key_a_known_protocol_renders_is_kept_as_that_protocol():
    # A tester's key came in as three 34-pair frames: Samsung32, held a little.
    from afterglow import ir_protocol, ir_signal
    from afterglow.gui.device_wizard import learned_signal
    sent = ir_signal.protocol_signal("samsung32", {"address": 7, "command": 2}, name="Up")
    frame = ir_protocol.render(sent)["pulses_us"]
    capture = concord.learned_capture(38145, [abs(p) for p in frame * 3], "Up")
    kept = learned_signal(capture)
    assert kept["kind"] == "protocol"
    assert (kept["protocol"], kept["parameters"]) == ("samsung32", sent["parameters"])
    noise = concord.learned_capture(38000, [900, 450, 300, 1200, 700, 20000], "X")
    assert learned_signal(noise) == noise


def test_the_learned_box_says_protocol_or_waveform(qapp_or_skip, monkeypatch):
    from afterglow import ir_protocol, ir_signal
    from afterglow.gui import device_wizard, remote_ops
    from afterglow.qt.QtWidgets import QInputDialog, QMessageBox
    sent = ir_signal.protocol_signal("samsung32", {"address": 7, "command": 2}, name="Up")
    frame = ir_protocol.render(sent)["pulses_us"]
    presses = iter([concord.learned_capture(38145, [abs(p) for p in frame * 3], "Up"),
                    concord.learned_capture(38150, [abs(p) for p in frame * 2], "Up")])
    told = []
    monkeypatch.setattr(concord, "available", lambda: True)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Up", True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    monkeypatch.setattr(remote_ops, "run_with_progress",
                        lambda *a, **k: (True, "", next(presses)))
    page = device_wizard.CommandsPage(_device())
    page.learn_btn.click()
    assert told == ["Learning was successful. Saved as protocol."]
    assert page.learned_captures()["Up"]["protocol"] == "samsung32"
