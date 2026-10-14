"""The experimental write path is recovery-backed and cannot leak into normal writes."""

from __future__ import annotations

from dataclasses import replace
import io
import json
from pathlib import Path
import re
import shutil
import zipfile

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


def _repacked(artifact, target, *, add=(), change=()):
    """`artifact` as a 900 or 1100 hands it back: unpacked onto its filesystem, then
    zipped up again - new bytes, with files it keeps itself (`add`) alongside."""
    raw = Path(artifact).read_bytes()
    header, start, size, _checksum = ezhex._split(raw)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw[start:start + size])) as source, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as remote:
        for name in reversed(source.namelist()):
            data = source.read(name)
            remote.writestr(name, data + b"<!-- -->" if name in change else data)
        for name in add:
            remote.writestr(name, b"\x01")
    payload = out.getvalue()
    header = re.sub(rb"<BINARYDATASIZE>\d+", b"<BINARYDATASIZE>%d" % len(payload), header)
    header = re.sub(rb"<CHECKSUM>\d+", b"<CHECKSUM>%d" % ezhex.checksum(payload), header)
    Path(target).write_bytes(header + payload)
    return target


def _read_back_from(tmp_path, prepared, writes, repacked):
    identity = {field: prepared["identity"].get(field)
                for field in first_write.IDENTITY_FIELDS}
    identity.update(model="Harmony 900", can_read=True, can_write=True)
    return lambda: FakeRemote(repacked, identity, writes)


KEPT = ("platformconfig/system_volume.dat", "userconfig/RamInitialise.bin")


def test_a_remote_that_packs_its_files_again_is_verified_by_what_it_holds(
        tmp_path, build, monkeypatch):
    artifact, _profile, _identity_data, writes, factory, report, prepared = \
        _prepared(tmp_path, build, monkeypatch)
    first_write.apply(report, ask=lambda _p: prepared["confirmation"], remote_factory=factory)
    repacked = _repacked(artifact, tmp_path / "remote.ezhex", add=KEPT)

    verified = first_write.readback(
        report, tmp_path / "readback.ezhex",
        remote_factory=_read_back_from(tmp_path, prepared, writes, repacked))

    assert verified["status"] == "readback-verified"
    assert verified["readback"]["payload_sha256"] != verified["artifact"]["payload_sha256"]
    assert verified["readback_comparison"]["matches"] is True
    assert verified["readback_comparison"]["kept_by_remote"] == list(KEPT)


def test_a_written_file_the_remote_does_not_hold_fails_the_readback(
        tmp_path, build, monkeypatch):
    artifact, _profile, _identity_data, writes, factory, report, prepared = \
        _prepared(tmp_path, build, monkeypatch)
    first_write.apply(report, ask=lambda _p: prepared["confirmation"], remote_factory=factory)
    repacked = _repacked(artifact, tmp_path / "remote.ezhex", add=KEPT,
                         change=("userconfig/UserConfiguration.xml",))

    with pytest.raises(first_write.FirstWriteError,
                       match="different: userconfig/UserConfiguration.xml"):
        first_write.readback(
            report, tmp_path / "readback.ezhex",
            remote_factory=_read_back_from(tmp_path, prepared, writes, repacked))
    data = json.loads(report.read_text())
    assert data["status"] == "written-awaiting-readback"
    assert data["readback_mismatch"]["comparison"]["matches"] is False


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


def test_restore_writes_back_only_the_captured_recovery(tmp_path, build, monkeypatch):
    """An experimental remote cannot go through the normal write path, so without this
    a tester whose remote misbehaved held a backup they could not put back."""
    _artifact, profile, _identity_data, writes, factory, report, prepared = \
        _prepared(tmp_path, build, monkeypatch)
    phrase = f"RESTORE {profile.id} {prepared['recovery']['sha256'][:12]}"

    with pytest.raises(first_write.FirstWriteError, match="nothing to restore"):
        first_write.restore(report, ask=lambda _p: phrase, remote_factory=factory)

    first_write.apply(report, ask=lambda _p: prepared["confirmation"],
                      remote_factory=factory)
    with pytest.raises(first_write.FirstWriteError, match="nothing was written"):
        first_write.restore(report, ask=lambda _p: "RESTORE", remote_factory=factory)

    restored = first_write.restore(report, ask=lambda _p: phrase, remote_factory=factory)
    assert restored["status"] == "restored"
    assert writes[-1] == Path(prepared["recovery"]["path"])


def test_an_uncertain_restore_may_be_repeated(tmp_path, build, monkeypatch):
    """Unlike a test write: putting the remote's own configuration back is the fix."""
    _artifact, profile, _identity_data, writes, factory, report, prepared = \
        _prepared(tmp_path, build, monkeypatch)
    first_write.apply(report, ask=lambda _p: prepared["confirmation"],
                      remote_factory=factory)
    phrase = f"RESTORE {profile.id} {prepared['recovery']['sha256'][:12]}"

    class Interrupted(FakeRemote):
        def _apply_config(self, path):
            raise RuntimeError("USB disappeared")

    identity = {f: prepared["identity"].get(f) for f in first_write.IDENTITY_FIELDS}
    identity.update(can_read=True, can_write=True)
    with pytest.raises(first_write.FirstWriteError, match="restore again"):
        first_write.restore(report, ask=lambda _p: phrase, remote_factory=lambda:
                            Interrupted(prepared["artifact"]["path"], identity, writes))
    assert json.loads(report.read_text())["status"] == "restore-outcome-unknown"
    assert first_write.restore(
        report, ask=lambda _p: phrase, remote_factory=factory)["status"] == "restored"


def test_a_tampered_recovery_is_not_written(tmp_path, build, monkeypatch):
    _artifact, profile, _identity_data, writes, factory, report, prepared = \
        _prepared(tmp_path, build, monkeypatch)
    first_write.apply(report, ask=lambda _p: prepared["confirmation"],
                      remote_factory=factory)
    recovery = Path(prepared["recovery"]["path"])
    recovery.write_bytes(recovery.read_bytes() + b"x")
    with pytest.raises(first_write.FirstWriteError):
        first_write.restore(report, ask=lambda _p: pytest.fail("must not prompt"),
                            remote_factory=factory)
    assert writes == [Path(prepared["artifact"]["path"]).resolve()]


def _one_build(tmp_path, label, name):
    """A Harmony One configuration built from one synthetic device named `label`."""
    import contextlib
    import io

    from afterglow.build_service import ConfigBuildService
    project = _project()
    project["devices"][0]["label"] = label
    out = tmp_path / name
    project["settings"] = {"remote": "harmony-one", "out_file": str(out)}
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(Path(__file__).resolve().parents[1], lambda _m: None).build(
            project)
    return out


class OneRemote(FakeRemote):
    """Reads back what was last written to it, as a remote does."""

    def save_config(self, target):
        shutil.copyfile(self.writes[-1] if self.writes else self.source, target)


def test_test_write_runs_through_on_the_harmony_one(tmp_path):
    """Its backup step ended in "backend 'harmony-one' cannot produce a change report":
    the One had nothing to say what a write changes, so Write was never offered."""
    on_remote = _one_build(tmp_path, "Old receiver", "on-remote.ezhex")
    artifact = _one_build(tmp_path, "New receiver", "new.ezhex")
    header, *_rest = ezhex._split(Path(artifact).read_bytes())
    identity = {**remotes.identity_of(header), "model": "Harmony One",
                "can_read": True, "can_write": True}
    writes = []
    factory = lambda: OneRemote(on_remote, identity, writes)
    report = tmp_path / "first-write.json"

    prepared = first_write.prepare(artifact, tmp_path / "backup.ezhex", report,
                                   remote_factory=factory)
    changes = prepared["changes"]
    assert changes["kind"] == "gspm-section-sha256"
    assert changes["changed"]                       # the device's name is in it somewhere
    written = first_write.apply(report, ask=lambda _p: prepared["confirmation"],
                                remote_factory=factory)
    assert written["status"] == "written-awaiting-readback"
    verified = first_write.readback(report, tmp_path / "readback.ezhex",
                                    remote_factory=factory)
    assert verified["status"] == "readback-verified"


def test_every_remote_written_by_test_write_can_say_what_a_write_changes():
    from afterglow import backends
    for profile in remotes.load_all():
        if profile.status == remotes.EXPERIMENTAL:
            assert callable(getattr(backends.for_profile(profile), "compare_payloads",
                                    None)), profile.id
