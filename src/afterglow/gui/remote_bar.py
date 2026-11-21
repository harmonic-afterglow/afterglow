"""Which remote the project is for: always on screen, changed only by migrating.

The remote is not a setting beside the backlight timeout. Every tab reads its vocabulary
from it, and changing it means re-reading the whole project against another remote's
profile, so it lives above the tabs and changing it goes through `afterglow.migrate`,
whose report is shown before anything is written.
"""
from __future__ import annotations

import re
from collections import OrderedDict

from ..qt.QtCore import Qt, pyqtSignal
from ..qt.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
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
            "Experimental: writing saves what is on the remote first, so it can be put "
            "back.")


class ChooseRemoteDialog(QDialog):
    """Pick a remote, by the model printed on it: every Harmony Logitech made is listed,
    the ones configurations can be built for first and the rest greyed, with a search
    over them. A remote sold under several names - the 600, 650 and 665 - is each of
    them, so a project knows which it is for (`chosen_skin`): a 600 is built grey."""

    def __init__(self, profiles, title: str, intro: str, parent=None,
                 selected: str | None = None, selected_skin: int | None = None,
                 known=None, exclude=None, preselect: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 480)
        layout = QVBoxLayout(self)
        text = QLabel(intro)
        text.setWordWrap(True)
        layout.addWidget(text)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search remotes")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        supported, others = _models(profiles, known)
        # the model the project is for already (profile id, skin): its profile's other
        # models stay offered - a 650 project can become a 600's
        if exclude is not None:
            from .. import remotes
            mine = remotes.model_name(remotes.get(exclude[0]), exclude[1])
            supported = [entry for entry in supported
                         if not (entry[1].id == exclude[0] and entry[0] == mine)]
        for name, profile, skin in supported:
            item = QListWidgetItem(f"{name} · {profile.status}")
            item.setData(256, profile.id)
            item.setData(257, skin)
            item.setToolTip(profile.notes or "")
            self.list.addItem(item)
        self._header = None
        if others:
            self._header = QListWidgetItem("Not supported yet")
            self._header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = self._header.font()
            font.setBold(True)
            self._header.setFont(font)
            self.list.addItem(self._header)
            for name in others:
                item = QListWidgetItem(name)
                item.setFlags(Qt.ItemFlag.NoItemFlags)       # shown, greyed, not chosen
                self.list.addItem(item)
        if preselect:
            self._select(selected, selected_skin)
        self.list.itemDoubleClicked.connect(
            lambda item: self.accept() if item.data(256) else None)
        layout.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # nothing chosen yet (preselect off): OK waits for a choice
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(self.list.currentItem() is not None
                      and bool(self.list.currentItem().data(256)))
        self.list.currentItemChanged.connect(
            lambda item, _old: ok.setEnabled(item is not None and bool(item.data(256))))

    def _choosable(self):
        return [self.list.item(i) for i in range(self.list.count())
                if self.list.item(i).data(256)]

    def _select(self, remote_id, skin) -> None:
        items = self._choosable()
        if not items:
            return
        exact = [item for item in items
                 if item.data(256) == remote_id and (skin is None or item.data(257) == skin)]
        self.list.setCurrentItem(exact[0] if exact else items[0])

    def _filter(self, text: str) -> None:
        """Show the remotes whose name has every word typed: "650", "harmony 7"."""
        words = text.casefold().split()
        shown_other = False
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item is self._header:
                continue
            hidden = not all(word in item.text().casefold() for word in words)
            item.setHidden(hidden)
            if not hidden and not item.data(256):
                shown_other = True
        if self._header is not None:
            self._header.setHidden(not shown_other)
        current = self.list.currentItem()
        if current is None or current.isHidden():
            visible = [item for item in self._choosable() if not item.isHidden()]
            if visible:
                self.list.setCurrentItem(visible[0])

    def chosen(self) -> str | None:
        item = self.list.currentItem()
        return item.data(256) if item and not item.isHidden() else None

    def chosen_skin(self) -> int | None:
        """The skin of the model picked: which of a remote's names it is."""
        item = self.list.currentItem()
        return item.data(257) if item and item.data(256) and not item.isHidden() else None


def _models(profiles, known=None) -> tuple[list, list[str]]:
    """([(model, profile, skin)] that can be chosen, [model] that cannot), by the skins
    Logitech numbered them with (remotes.models). A model of a profile in ``known`` but
    not offered - the project's own remote, when moving it - is in neither."""
    from .. import remotes
    names = {int(skin): entry.get("model") or "" for skin, entry in remotes.models().items()
             if str(skin).isdigit()}
    # Every skin its own entry, even where one profile builds several: folding entries
    # that came out with the same name hid the 510, which had no name of its own and was
    # listed - once - as the 515 it is built like.
    supported, seen = [], set()
    for profile in profiles:
        mine = []
        for skin in profile.skins:
            name = names.get(skin) or profile.model
            seen.add(name)
            mine.append((name, profile, skin))
        supported += sorted(mine, key=lambda entry: _natural(entry[0]))
    taken = {skin for profile in (known or profiles) for skin in profile.skins}
    taken_names = {names.get(skin) for skin in taken} | seen
    others = sorted({name for skin, name in names.items()
                     if skin not in taken and name and not name.isdigit()
                     and name not in taken_names},
                    key=_natural)
    return supported, others


def _natural(name: str) -> list:
    """Sorts "Harmony 600" before "Harmony 1100": its numbers as numbers."""
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", name)]


class MigrationDialog(QDialog):
    """What moving the project changes, grouped by what it changes it in."""

    WORDS = {"renamed": "Renamed", "substituted": "Changed", "removed": "Removed"}

    def __init__(self, source, target, report, parent=None, source_skin=None,
                 target_skin=None):
        super().__init__(parent)
        from .. import remotes
        # by the models chosen - "Harmony 650" - not the profile's "600 / 650 / 665"
        to = remotes.model_name(target, target_skin)
        self.setWindowTitle(f"Move to {to}")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        counts = {word: sum(row["change"] == key for row in report)
                  for key, word in self.WORDS.items()}
        start = remotes.model_name(source, source_skin) if source else "its remote"
        summary = f"Moving this project from {start} to {to}. "
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
