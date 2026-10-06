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
    from PyQt6.QtWidgets import QInputDialog, QMessageBox

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
    from PyQt6.QtWidgets import QMessageBox

    from afterglow.gui.device_wizard import CommandsPage
    told = []
    monkeypatch.setattr(concord, "available", lambda: False)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[1]))
    page = CommandsPage(_device())
    assert page.learn_btn.isEnabled()
    page.learn_btn.click()
    assert told == ["Learning needs libconcord"]
    assert page.learned_captures() == {}
