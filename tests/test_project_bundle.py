"""A shareable project builds on another machine exactly as it does on its owner's.

"Another machine" here is one with no installed protocols and none of the owner's files:
`ir_protocol.LIBRARY` points at an empty folder, and the bundle is opened somewhere new.
"""
from __future__ import annotations

import contextlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from afterglow import ezhex, ir_protocol, ir_signal, project_bundle


def _payload(path):
    raw = path.read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    return raw[start:start + size]


def _elsewhere(monkeypatch, tmp_path):
    empty = tmp_path / "no-protocols"
    empty.mkdir()
    monkeypatch.setattr(ir_protocol, "LIBRARY", empty)


def test_an_imported_project_with_pictures_builds_the_same_elsewhere(
        configs, unpacked, build, tmp_path, monkeypatch):
    from afterglow.importer import build_project
    with_pictures = [c for c in configs if any(
        name.startswith("userconfig/image/") and not name.endswith("/")
        for name in zipfile.ZipFile(io.BytesIO(_payload(c))).namelist())]
    if not with_pictures:
        pytest.skip("no real configuration with pictures")
    project = build_project(str(unpacked(with_pictures[0])))
    assert project.get("assets"), "the import should have kept its pictures"
    original = _payload(build(json.loads(json.dumps(project)), "here.ezhex"))

    bundle = tmp_path / f"shared{project_bundle.SUFFIX}"
    project_bundle.export(project, bundle)
    _elsewhere(monkeypatch, tmp_path)
    reopened = project_bundle.open_bundle(bundle, tmp_path / "friend")

    assert _payload(build(reopened, "there.ezhex")) == original
    assert all(str(tmp_path / "friend") in a["source"] for a in reopened["assets"])


def test_a_protocol_from_the_owners_library_travels_with_the_device(
        build, tmp_path, monkeypatch):
    project = {"settings": {"remote": "harmony-900", "out_file": "/home/me/tv.ezhex",
                            "template": "/home/me/old.ezhex"},
               "activities": [], "devices": [{
                   "schema": "afterglow-project-device/1", "id": "1", "label": "TV",
                   "type": "Television", "mfr": "T", "model": "M",
                   "commands": [["Power", "Power", "", "", None]],
                   "signals": {"Power": ir_signal.protocol_signal(
                       "nec1", {"address": 4, "command": 8})}}]}
    bundle = tmp_path / "tv.afterglow"
    notes = project_bundle.export(project, bundle)
    assert any("nec1" in note for note in notes)

    _elsewhere(monkeypatch, tmp_path)
    reopened = project_bundle.open_bundle(bundle, tmp_path / "friend")
    assert "nec1" in reopened["devices"][0]["portable_protocol_definitions"]
    assert "template" not in reopened["settings"]
    assert reopened["settings"]["out_file"] == "tv.ezhex"
    with contextlib.redirect_stdout(io.StringIO()):
        assert build(reopened).is_file()


def test_a_protocol_nobody_has_is_refused_at_export(tmp_path, monkeypatch):
    _elsewhere(monkeypatch, tmp_path)
    project = {"settings": {}, "activities": [], "devices": [{
        "label": "TV", "signals": {"Power": {"kind": "protocol", "protocol": "nec1"}}}]}
    with pytest.raises(project_bundle.BundleError, match="TV: nec1"):
        project_bundle.export(project, tmp_path / "x.afterglow")


def test_a_bundle_cannot_write_outside_its_folder(tmp_path):
    bundle = tmp_path / "evil.afterglow"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema": project_bundle.SCHEMA}))
        archive.writestr("project.json", json.dumps({"settings": {}, "devices": [],
            "activities": [], "assets": [{"name": "../../escaped.png", "source": "x"}]}))
        archive.writestr("assets/escaped.png", b"png")
        archive.writestr("../../escaped.png", b"png")
    project = project_bundle.open_bundle(bundle, tmp_path / "inside")
    assert (tmp_path / "inside" / "assets" / "escaped.png").read_bytes() == b"png"
    assert not (tmp_path / "escaped.png").exists()
    assert project["assets"][0]["name"] == "escaped.png"


def test_a_file_that_is_not_a_bundle_says_so(tmp_path):
    (tmp_path / "x.afterglow").write_bytes(b"not a zip")
    with pytest.raises(project_bundle.BundleError, match="not a shareable project"):
        project_bundle.open_bundle(tmp_path / "x.afterglow", tmp_path / "out")


def test_opening_a_bundle_twice_never_unpacks_over_the_first(
        qapp_or_skip, tmp_path, monkeypatch):
    from afterglow.gui import app as gui_app
    monkeypatch.setenv("AFTERGLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(gui_app.QMessageBox, "information", lambda *a, **k: None)
    bundle = tmp_path / "living-room.afterglow"
    project_bundle.export({"settings": {"remote": "harmony-900"}, "devices": [],
                           "activities": []}, bundle)
    window = gui_app.MainWindow()
    window.open_bundle(str(bundle))
    first = window._project_path
    window.open_bundle(str(bundle))
    assert first != window._project_path
    assert Path(first).parts[-2:] == ("living-room", "project.json")
    assert Path(window._project_path).parts[-2:] == ("living-room-2", "project.json")
