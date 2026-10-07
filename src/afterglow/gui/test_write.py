"""The Flash tab's write for a remote whose support is still experimental.

The normal flash refuses an experimental profile, and should: nobody has yet shown that a
configuration built for it boots. Testing one is how that changes, so the interface walks
through `afterglow.first_write` rather than around it - back the remote up, write after an
explicit confirmation, read back what landed, and put the backup back at any point after.

Every step is one call into `first_write`, which owns the safety rules; this module is the
order the buttons unlock in and the words around them. An attempt lives in its own folder
with its report, so an interrupted test is resumed from that report rather than retried.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout,
)

from .. import first_write

REPORT = "test-write.json"


class _Step(QThread):
    """Run one blocking `first_write` call off the interface thread."""

    finished_with = pyqtSignal(bool, object)      # succeeded, report or error text

    def __init__(self, call, parent=None):
        super().__init__(parent)
        self.call = call

    def run(self):
        try:
            self.finished_with.emit(True, self.call())
        except Exception as exc:                  # every failure is reported, none lost
            self.finished_with.emit(False, f"{type(exc).__name__}: {exc}")


def new_attempt(root: Path, profile_id: str) -> Path:
    """A fresh folder for one test write, named so attempts sort by time."""
    folder = Path(root) / "test-writes" / (
        f"{profile_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    folder.mkdir(parents=True, exist_ok=False)
    return folder


class TestWriteDialog(QDialog):
    def __init__(self, folder: Path, artifact: Path | None = None, parent=None,
                 remote_factory=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.report = self.folder / REPORT
        self.artifact = artifact
        self._remote = {} if remote_factory is None else {"remote_factory": remote_factory}
        self._step = None
        self.setWindowTitle("Test write")
        self.resize(640, 520)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "This remote's support is experimental, so the configuration is written the "
            "careful way. Afterglow first saves what is on the remote now, twice; asks you "
            "to confirm; writes; then reads the remote back to prove what landed. If the "
            "remote misbehaves afterwards, Restore puts your own configuration back.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        where = QLineEdit(str(self.folder))
        where.setReadOnly(True)
        row = QHBoxLayout()
        row.addWidget(QLabel("Files for this test:"))
        row.addWidget(where, 1)
        layout.addLayout(row)

        steps = QHBoxLayout()
        self.backup_btn = QPushButton("1. Back up the remote")
        self.write_btn = QPushButton("2. Write")
        self.verify_btn = QPushButton("3. Read back and verify")
        self.restore_btn = QPushButton("Restore my backup")
        self.backup_btn.clicked.connect(self.back_up)
        self.write_btn.clicked.connect(self.write)
        self.verify_btn.clicked.connect(self.verify)
        self.restore_btn.clicked.connect(self.restore)
        for button in (self.backup_btn, self.write_btn, self.verify_btn):
            steps.addWidget(button)
        steps.addStretch()
        steps.addWidget(self.restore_btn)
        layout.addLayout(steps)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Courier", 9))
        layout.addWidget(self.log, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self._show_state()

    # state
    def status(self) -> str | None:
        if not self.report.is_file():
            return None
        try:
            return first_write._load_report(self.report)[1].get("status")
        except first_write.FirstWriteError:
            return "unreadable"

    def _show_state(self, busy: bool = False):
        status = self.status()
        self.backup_btn.setEnabled(not busy and status is None and self.artifact is not None)
        self.write_btn.setEnabled(not busy and status == "prepared")
        self.verify_btn.setEnabled(not busy and status in {
            "write-started", "write-outcome-unknown", "written-awaiting-readback"})
        self.restore_btn.setEnabled(not busy and status in first_write.RESTORABLE)

    def _run(self, call, then):
        from .usb_driver import offer_before_operation
        offer_before_operation(self)
        self._show_state(busy=True)
        self._step = _Step(call, self)
        self._step.finished_with.connect(lambda ok, result: self._done(ok, result, then))
        self._step.start()

    def _done(self, ok, result, then):
        if ok:
            then(result)
        else:
            self.log.append(f"\nFAILED: {result}")
        self._show_state()

    # the steps
    def back_up(self):
        self.log.append("Saving what is on the remote now, then making a second copy...")
        self._run(lambda: first_write.prepare(
            self.artifact, self.folder / "backup.ezhex", self.report, **self._remote),
            self._backed_up)

    def _backed_up(self, data):
        changes = data.get("changes") or {}
        self.log.append(f"Backed up to {data['recovery']['path']}")
        self.log.append(f"and {data['recovery_copy']['path']}")
        summary = {key: value for key, value in changes.items()
                   if not isinstance(value, (list, dict))}
        if summary:
            self.log.append("What the write changes: " + ", ".join(
                f"{key} {value}" for key, value in summary.items()))
        for key, value in changes.items():
            if isinstance(value, list) and value:
                self.log.append(f"  {key}: {len(value)}")
        self.log.append("\nNext: Write.")

    def _confirm(self, phrase: str, what: str) -> str | None:
        typed, ok = QInputDialog.getText(
            self, what, f"To go ahead, type exactly:\n\n{phrase}")
        return typed.strip() if ok else None

    def write(self):
        phrase = first_write._load_report(self.report)[1]["confirmation"]
        typed = self._confirm(phrase, "Write to the remote")
        if typed is None:
            return
        self.log.append("\nWriting. Do not unplug the remote...")
        self._run(lambda: first_write.apply(
            self.report, ask=lambda _prompt: typed, **self._remote), self._written)

    def _written(self, data):
        if data.get("restart_warning"):
            self.log.append(f"(the remote dropped off USB while restarting: "
                            f"{data['restart_warning']})")
        self.log.append(
            "Written. Let the remote finish restarting and reappear, then press "
            "Read back and verify. Do not write again.")

    def verify(self):
        target = self.folder / f"readback-{datetime.now().strftime('%H%M%S')}.ezhex"
        self.log.append("\nReading the remote back...")
        self._run(lambda: first_write.readback(self.report, target, **self._remote),
                  self._verified)

    def _verified(self, data):
        self.log.append(
            "Verified: the remote holds exactly the configuration that was written.\n"
            "Now check it on the remote itself - does it start, do the screens and "
            "buttons work? Please report what you find. If anything is wrong, press "
            "Restore my backup.")

    def restore(self):
        data = first_write._load_report(self.report)[1]
        phrase = f"RESTORE {data['profile']} {data['recovery']['sha256'][:12]}"
        typed = self._confirm(phrase, "Restore your backup")
        if typed is None:
            return
        self.log.append("\nWriting your backup back. Do not unplug the remote...")
        self._run(lambda: first_write.restore(
            self.report, ask=lambda _prompt: typed, **self._remote), self._restored)

    def _restored(self, _data):
        self.log.append("Your own configuration is back on the remote.")

    def reject(self):
        if self._step is not None and self._step.isRunning():
            QMessageBox.information(
                self, "Test write", "Wait for the current step to finish first.")
            return
        super().reject()
