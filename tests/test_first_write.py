"""The experimental write path is recovery-backed and cannot leak into normal writes."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from afterglow import ezhex, first_write, remotes


def _project():
    return {
        "settings": {},
        "activities": [],
        "devices": [{
            "schema": "afterglow-device/2",
            "id": "1",
            "label": "Synthetic receiver",
            "type": "Receiver",
            "mfr": "Test",
            "model": "Fixture",
            "commands": [["Power", "Power", "1", "2", None]],
            "signals": {
                "Power": {
                    "schema": "afterglow-ir-signal/1",
                    "kind": "protocol",
                    "protocol": "nec1",
                    "parameters": {"address": 1, "command": 2},
                    "name": "Power",
                },
            },
        }],
    }


def _identity(artifact):
    header, *_rest = ezhex._split(Path(artifact).read_bytes())
    return {
        **remotes.identity_of(header),
        "model": "Harmony 900",
        "firmware": "7.8",
        "can_read": True,
        "can_write": True,
    }


class FakeRemote:
    def __init__(self, source, identity, writes):
        self.source = Path(source)
        self._identity = identity
        self.writes = writes
        self.last_restart_error = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def identity(self):
        return dict(self._identity)

    def save_config(self, target):
        shutil.copyfile(self.source, target)

    def _authorize_experimental_config(self, path, expected_identity):
        assert expected_identity == {
            field: self._identity.get(field) for field in first_write.IDENTITY_FIELDS}

    def _apply_config(self, path):
        self.writes.append(Path(path))


def _prepared(tmp_path, build, monkeypatch):
    artifact = build(_project())
    profile = replace(remotes.get("harmony-900"), status=remotes.EXPERIMENTAL)
    identity = _identity(artifact)
    writes = []
    factory = lambda: FakeRemote(artifact, identity, writes)
    monkeypatch.setattr(first_write.ezhex, "profile_of", lambda _path: profile)
    monkeypatch.setattr(first_write.remotes, "get", lambda _id: profile)
    report = tmp_path / "first-write.json"
    result = first_write.prepare(
        artifact, tmp_path / "recovery.ezhex", report, remote_factory=factory)
    return artifact, profile, identity, writes, factory, report, result


def test_prepare_captures_two_recoveries_and_a_native_change_report(
        tmp_path, build, monkeypatch):
    _artifact_path, _profile, _identity_data, writes, _factory, _report, result = \
        _prepared(tmp_path, build, monkeypatch)

    assert result["status"] == "prepared"
    assert Path(result["recovery"]["path"]).is_file()
    assert Path(result["recovery_copy"]["path"]).is_file()
    assert result["recovery"]["sha256"] == result["recovery_copy"]["sha256"]
    assert result["artifact"]["validation"]["native"]["ok"] is True
    assert result["changes"]["kind"] == "pk-entry-sha256"
    assert writes == []


def test_apply_requires_the_report_specific_confirmation(tmp_path, build, monkeypatch):
    _artifact_path, _profile, _identity_data, writes, factory, report, _result = \
        _prepared(tmp_path, build, monkeypatch)

    with pytest.raises(first_write.FirstWriteError, match="nothing was written"):
        first_write.apply(report, ask=lambda _prompt: "WRITE something else", remote_factory=factory)
    assert writes == []


def test_changed_artifact_is_refused_before_confirmation(tmp_path, build, monkeypatch):
    artifact, _profile, _identity_data, writes, factory, report, _result = \
        _prepared(tmp_path, build, monkeypatch)
    artifact.write_bytes(artifact.read_bytes() + b"changed")

    with pytest.raises(first_write.FirstWriteError, match="bytes outside"):
        first_write.apply(report, ask=lambda _prompt: pytest.fail("must not prompt"),
                          remote_factory=factory)
    assert writes == []


def test_apply_then_readback_closes_the_report(tmp_path, build, monkeypatch):
    artifact, _profile, _identity_data, writes, factory, report, prepared = \
        _prepared(tmp_path, build, monkeypatch)

    written = first_write.apply(
        report, ask=lambda _prompt: prepared["confirmation"], remote_factory=factory)
    assert written["status"] == "written-awaiting-readback"
    assert writes == [Path(artifact).resolve()]

    verified = first_write.readback(
        report, tmp_path / "readback.ezhex", remote_factory=factory)
    assert verified["status"] == "readback-verified"
    assert (verified["readback"]["payload_sha256"]
            == verified["artifact"]["payload_sha256"])


def test_uncertain_write_is_never_automatically_retried(tmp_path, build, monkeypatch):
    _artifact_path, _profile, _identity_data, writes, _factory, report, prepared = \
        _prepared(tmp_path, build, monkeypatch)

    class InterruptedRemote(FakeRemote):
        def _apply_config(self, path):
            raise RuntimeError("USB disappeared")

    artifact = prepared["artifact"]["path"]
    identity = {field: prepared["identity"].get(field)
                for field in first_write.IDENTITY_FIELDS}
    identity.update(model="Harmony 900", can_read=True, can_write=True)
    factory = lambda: InterruptedRemote(artifact, identity, writes)
    with pytest.raises(first_write.FirstWriteError, match="do not apply again"):
        first_write.apply(
            report, ask=lambda _prompt: prepared["confirmation"], remote_factory=factory)

    assert json.loads(report.read_text())["status"] == "write-outcome-unknown"
    with pytest.raises(first_write.FirstWriteError, match="not 'prepared'"):
        first_write.apply(
            report, ask=lambda _prompt: pytest.fail("must not prompt"),
            remote_factory=factory)


def test_normal_write_guard_still_refuses_an_experimental_profile(
        tmp_path, build, monkeypatch):
    from afterglow import concord

    artifact = build(_project())
    profile = replace(remotes.get("harmony-900"), status=remotes.EXPERIMENTAL)
    monkeypatch.setattr(remotes, "identify", lambda _header: profile)

    with pytest.raises(concord.RemoteError, match="experimental"):
        concord.Remote._verify_intended_for(artifact, _identity(artifact))
