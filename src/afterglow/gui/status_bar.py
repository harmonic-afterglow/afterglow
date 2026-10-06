"""The strip along the bottom of the window: what the project is, and whether it is saved.

Laid out like an editor's status bar - short fields on the right, each one a flat
button that does the obvious thing when clicked - so the state of the project is always
in view without taking room from the tabs. Messages that come and go (a save, a moved
library) appear on the left.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QStatusBar, QToolButton

from .remote_bar import STATUS_COLOURS

UNSAVED_COLOUR = "#b26a00"


def _field(tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setAutoRaise(True)                  # flat until hovered, like KWrite's
    button.setToolTip(tooltip)
    return button


class ProjectStatusBar(QStatusBar):
    """Remote, contents, file and saved state, each clickable."""

    remote_clicked = pyqtSignal()
    contents_clicked = pyqtSignal()
    file_clicked = pyqtSignal()
    saved_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.contents = _field("Devices and activities in this project")
        self.file = _field("Open the folder this project is saved in")
        self.remote = _field("The remote this project is for. Click to move the "
                             "project to another remote - you see every change first.")
        self.saved = _field("Click to save")
        for button, signal in ((self.contents, self.contents_clicked),
                               (self.file, self.file_clicked),
                               (self.remote, self.remote_clicked),
                               (self.saved, self.saved_clicked)):
            button.clicked.connect(signal)
            self.addPermanentWidget(button)

    def show_project(self, project: dict, path, profile, dirty: bool) -> None:
        devices = len(project.get("devices") or [])
        activities = len(project.get("activities") or [])
        self.contents.setText(f"{devices} device{'s' * (devices != 1)} · "
                              f"{activities} activit{'ies' if activities != 1 else 'y'}")

        if path:
            self.file.setText(Path(path).name if Path(path).name != "project.json"
                              else f"{Path(path).parent.name}/project.json")
            self.file.setToolTip(f"{path}\nClick to open its folder")
            self.file.setEnabled(True)
        else:
            self.file.setText("Not saved yet")
            self.file.setToolTip("This project has no file yet")
            self.file.setEnabled(False)

        if profile is None:
            self.remote.setText("No remote chosen")
            self.remote.setStyleSheet("")
        else:
            self.remote.setText(f"{profile.model} · {profile.status}")
            colour = STATUS_COLOURS.get(profile.status)
            self.remote.setStyleSheet(f"color: {colour};" if colour and
                                      not profile.verified else "")

        if dirty:
            self.saved.setText("Unsaved changes")
            self.saved.setStyleSheet(f"color: {UNSAVED_COLOUR}; font-weight: bold;")
            self.saved.setToolTip("Click to save (Ctrl+S)")
        elif not path:
            self.saved.setText("New project")     # nothing in it yet worth nagging about
            self.saved.setStyleSheet("")
            self.saved.setToolTip("Click to save (Ctrl+S)")
        else:
            self.saved.setText("Saved")
            self.saved.setStyleSheet("")
            self.saved.setToolTip("Everything is saved")
