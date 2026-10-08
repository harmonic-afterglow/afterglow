"""Which remote the project is for: always on screen, changed only by migrating.

The remote is not a setting beside the backlight timeout. Every tab reads its vocabulary
from it, and changing it means re-reading the whole project against another remote's
profile, so it lives above the tabs and changing it goes through `afterglow.migrate`,
whose report is shown before anything is written.
"""
from __future__ import annotations

from collections import OrderedDict

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

STATUS_COLOURS = {"verified": "#2e7d32", "experimental": "#b26a00"}


def status_text(profile) -> str:
    return f"{profile.model} · {profile.status}"


class RemoteBar(QFrame):
    """The remote this project is built for, and the one way to change it."""

    change_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.addWidget(QLabel("Remote:"))
        self.name = QLabel()
        self.status = QLabel()
        self.note = QLabel()
        self.note.setStyleSheet("color: gray;")
        row.addWidget(self.name)
        row.addWidget(self.status)
        row.addWidget(self.note, 1)
        self.change = QPushButton("Change remote…")
        self.change.setToolTip(
            "Move this project to another remote. You see what changes before anything "
            "is saved, and the result is a new project file.")
        self.change.clicked.connect(self.change_requested)
        row.addWidget(self.change)

    def set_profile(self, profile) -> None:
        if profile is None:
            self.name.setText("<b>none chosen</b>")
            self.status.setText("")
            self.note.setText("Choose the remote this project is for.")
            return
        self.name.setText(f"<b>{profile.model}</b>")
        colour = STATUS_COLOURS.get(profile.status, "gray")
        self.status.setText(f"<span style='color:{colour}'>· {profile.status}</span>")
        self.note.setText(
            "" if profile.verified else
            "Configurations are written through a test write that backs the remote up "
            "first and checks the result.")


class ChooseRemoteDialog(QDialog):
    """Pick a remote that configurations can be built for."""

    def __init__(self, profiles, title: str, intro: str, parent=None,
                 selected: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 320)
        layout = QVBoxLayout(self)
        text = QLabel(intro)
        text.setWordWrap(True)
        layout.addWidget(text)
        self.list = QListWidget()
        for profile in profiles:
            item = QListWidgetItem(status_text(profile))
            item.setData(256, profile.id)
            item.setToolTip(profile.notes or "")
            self.list.addItem(item)
        if self.list.count():
            ids = [profile.id for profile in profiles]
            self.list.setCurrentRow(ids.index(selected) if selected in ids else 0)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self) -> str | None:
        item = self.list.currentItem()
        return item.data(256) if item else None


class MigrationDialog(QDialog):
    """What moving the project changes, grouped by what it changes it in."""

    WORDS = {"renamed": "Renamed", "substituted": "Changed", "removed": "Removed"}

    def __init__(self, source, target, report, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Move to {target.model}")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        counts = {word: sum(row["change"] == key for row in report)
                  for key, word in self.WORDS.items()}
        summary = (f"Moving this project from {source.model if source else 'its remote'} "
                   f"to {target.model}. ")
        summary += ("Everything carries over unchanged." if not report else
                    ", ".join(f"{n} {word.lower()}" for word, n in counts.items() if n)
                    + ". Review the list, then save the result as a new project; this "
                    "one stays as it is.")
        text = QLabel(summary)
        text.setWordWrap(True)
        layout.addWidget(text)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "What"])
        groups: OrderedDict[str, list] = OrderedDict()
        for row in report:
            groups.setdefault(row["subject"], []).append(row)
        for subject, rows in groups.items():
            parent_item = QTreeWidgetItem([subject, f"{len(rows)} change(s)"])
            for row in rows:
                child = QTreeWidgetItem([self.WORDS.get(row["change"], row["change"]),
                                         row["detail"]])
                child.setToolTip(1, row["detail"])     # long lists of keys run off the edge
                parent_item.addChild(child)
            self.tree.addTopLevelItem(parent_item)
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        self.tree.setVisible(bool(report))
        layout.addWidget(self.tree, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save = buttons.addButton("Save as new project…",
                                      QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
