"""Settings > Flash a configuration file: write any .ezhex, such as a backup, as is.

The same as `concordance -C file`. A file made for a different remote is refused unless
"Force" is ticked, as `--force` does there.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                             QVBoxLayout)

from .remote_ops import run_with_progress

TITLE = "Flash a configuration file"


class FlashFileDialog(QDialog):
    def __init__(self, parent=None, start: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self._start = start or Path.home()
        layout = QVBoxLayout(self)
        intro = QLabel("Writes a configuration file onto the remote exactly as it is - "
                       "for example a backup, to put the remote back how it was. It "
                       "replaces everything on the remote.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("Choose a .ezhex file")
        self.path.textChanged.connect(self._update)
        browse = QPushButton("Choose…")
        browse.clicked.connect(self._choose)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self.force = QCheckBox("Force - write it even if it was made for a different "
                               "remote")
        layout.addWidget(self.force)
        warning = QLabel("Only for files you know are right. A configuration for another "
                         "model can leave the remote unable to start.")
        warning.setWordWrap(True)
        warning.setStyleSheet("color: gray;")
        layout.addWidget(warning)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Flash")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._update()

    def _choose(self):
        name, _ = QFileDialog.getOpenFileName(
            self, "Choose a configuration file", str(self._start),
            "Harmony configuration (*.ezhex *.EZHex);;All files (*)")
        if name:
            self.path.setText(name)

    def _update(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            Path(self.path.text().strip()).is_file())

    def chosen(self) -> tuple[Path, bool]:
        return Path(self.path.text().strip()), self.force.isChecked()


def flash_file_dialog(parent, start: Path | None = None) -> None:
    dialog = FlashFileDialog(parent, start)
    if not dialog.exec():
        return
    path, force = dialog.chosen()
    question = (f"Write {path.name} onto the remote? Everything on it now is replaced."
                + ("\n\nForce is on: it is written even if it was made for a different "
                   "remote." if force else "")
                + "\n\nDo not unplug the remote until it has finished.")
    answer = QMessageBox.warning(
        parent, TITLE, question,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel)
    if answer != QMessageBox.StandardButton.Yes:
        return
    ok, message, _result = run_with_progress(
        parent, "flash", TITLE, f"Writing {path.name}. Do not unplug the remote.",
        path=str(path), force=force)
    if ok:
        QMessageBox.information(parent, TITLE, message)
    else:
        QMessageBox.critical(parent, TITLE, message)
