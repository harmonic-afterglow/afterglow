"""The Flash tab's test write walks first_write in order and never offers a step early."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from afterglow import first_write, remotes
from test_first_write import FakeRemote, _identity, _project


def _finish(dialog, qapp):
    dialog._step.wait()
    qapp.processEvents()


def _report(folder, status):
    (folder / "test-write.json").write_text(json.dumps({
        "schema": first_write.SCHEMA, "status": status, "profile": "harmony-900",
        "confirmation": "WRITE x", "recovery": {"sha256": "0" * 64}}))


def _enabled(dialog):
    return {name for name, button in (
        ("backup", dialog.backup_btn), ("write", dialog.write_btn),
        ("verify", dialog.verify_btn), ("restore", dialog.restore_btn))
        if button.isEnabled()}


@pytest.mark.parametrize("status, offered", [
    (None, {"backup"}),
    ("prepared", {"write"}),
    ("write-outcome-unknown", {"verify", "restore"}),
    ("written-awaiting-readback", {"verify", "restore"}),
    ("readback-verified", {"restore"}),
    ("restore-outcome-unknown", {"restore"}),
])
def test_each_step_is_offered_only_when_it_is_next(qapp_or_skip, tmp_path, status, offered):
    from afterglow.gui.test_write import TestWriteDialog
    if status:
        _report(tmp_path, status)
    dialog = TestWriteDialog(tmp_path, tmp_path / "candidate.ezhex")
    assert _enabled(dialog) == offered


def test_a_resumed_attempt_cannot_back_up_again(qapp_or_skip, tmp_path):
    """A resumed test has no candidate, and a second backup would overwrite the first."""
    from afterglow.gui.test_write import TestWriteDialog
    assert _enabled(TestWriteDialog(tmp_path, None)) == set()


def test_a_whole_test_write_through_the_dialog(qapp_or_skip, tmp_path, build, monkeypatch):
    from afterglow.gui import test_write
    artifact = build(_project())
    profile = replace(remotes.get("harmony-900"), status=remotes.EXPERIMENTAL)
    writes = []
    factory = lambda: FakeRemote(artifact, _identity(artifact), writes)
    monkeypatch.setattr(first_write.ezhex, "profile_of", lambda _path: profile)
    monkeypatch.setattr(first_write.remotes, "get", lambda _id: profile)
    phrases = []
    monkeypatch.setattr(test_write.QInputDialog, "getText",
                        lambda _parent, _title, _text: (phrases[-1], True))

    dialog = test_write.TestWriteDialog(tmp_path, artifact, remote_factory=factory)
    dialog.back_up()
    _finish(dialog, qapp_or_skip)
    assert dialog.status() == "prepared" and writes == []

    phrases.append(first_write._load_report(dialog.report)[1]["confirmation"])
    dialog.write()
    _finish(dialog, qapp_or_skip)
    assert dialog.status() == "written-awaiting-readback"

    dialog.verify()
    _finish(dialog, qapp_or_skip)
    assert dialog.status() == "readback-verified"

    data = first_write._load_report(dialog.report)[1]
    phrases.append(f"RESTORE {profile.id} {data['recovery']['sha256'][:12]}")
    dialog.restore()
    _finish(dialog, qapp_or_skip)
    assert dialog.status() == "restored"
    assert [path.name for path in writes] == [artifact.name, "backup.ezhex"]
