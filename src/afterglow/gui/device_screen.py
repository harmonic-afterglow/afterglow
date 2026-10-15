"""A device's own page on the remote's screen: which of its commands get a button there,
in what order, and under what text.

Logitech's configurations put a chosen few of a device's commands on its page - 131 of the
144 devices in the donors - in an order of their own, often under other names, now and
then with a gap or one command twice. The page used to be made from the command list, so
an imported device came back with every command on it in alphabetical order. The page is
now the device's own `screen_buttons` (`project_devices.screen_buttons`), read from the
configuration and arranged here.

A device that has never been arranged keeps the page its labels make - every command with
text in "On screen as" - and nothing is written for it until something here changes.
"""
from __future__ import annotations

from typing import Callable

from ..qt.QtCore import Qt
from ..qt.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
                             QListWidget, QListWidgetItem, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWizardPage)

from .. import backends, project_devices
from .drag_rows import RowDragger, move_table_row
from .screen_preview import ScreenPreview

GAP_TEXT = "(gap)"


class DeviceScreenPage(QWizardPage):
    """Arrange the buttons on a device's page. `rows` gives the device's command rows as
    the Commands page has them now - `[name, label, ...]` - so a command added or renamed
    there is offered here, and a button whose command has gone is dropped."""

    def __init__(self, existing: dict, rows: Callable[[], list], parent=None,
                 remote=None):
        super().__init__(parent)
        self._rows = rows
        self._title = (existing or {}).get("label") or ""
        self._explicit = (existing or {}).get("screen_buttons") is not None
        self._loaded = list((existing or {}).get("screen_buttons") or [])
        self.setTitle("Screen")
        self.setSubTitle(
            "The buttons on this device's own page of the remote's screen, in the order "
            "they appear. A command left off still works on its key and in activities.")
        layout = QVBoxLayout(self)

        lists = QHBoxLayout()
        side = QVBoxLayout()
        side.addWidget(QLabel("<b>Commands</b>"))
        self.commands = QListWidget()
        self.commands.setToolTip("Double-click a command, or pick it and press Add, to "
                                 "give it a button.")
        self.commands.itemDoubleClicked.connect(lambda _item: self._add())
        side.addWidget(self.commands, 1)
        lists.addLayout(side, 2)

        buttons = QVBoxLayout()
        buttons.addStretch()
        self.add_btn = QPushButton("Add →")
        self.gap_btn = QPushButton("Add gap")
        self.gap_btn.setToolTip("An empty place between buttons, where the remote shows "
                                "nothing.")
        self.remove_btn = QPushButton("Remove")
        self.every_btn = QPushButton("Every command")
        self.every_btn.setToolTip("A button for every command, under its label.")
        self.clear_btn = QPushButton("Clear")
        for button in (self.add_btn, self.gap_btn, self.remove_btn, self.every_btn,
                       self.clear_btn):
            buttons.addWidget(button)
        buttons.addStretch()
        lists.addLayout(buttons)

        page = QVBoxLayout()
        page.addWidget(QLabel("<b>On the page</b>"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Button text", "Sends"])
        self.table.horizontalHeaderItem(0).setToolTip(
            "What the button says. Double-click to change it.")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                   QAbstractItemView.EditTrigger.SelectedClicked)
        self._filling = False
        self.table.itemChanged.connect(self._edited)
        page.addWidget(self.table, 1)
        hint = QLabel("Drag a button by its grip to move it.")
        hint.setStyleSheet("color: gray;")
        page.addWidget(hint)
        lists.addLayout(page, 3)

        # The page as the remote shows it, in the remote's own grid.
        grid = remote.screen_grid("device") if remote is not None else None
        self.preview = ScreenPreview(*(grid or (2, 3)), title=self._title)
        self.preview.setVisible(grid is not None)
        self.preview.picked.connect(self.table.selectRow)
        self.table.currentCellChanged.connect(
            lambda row, *_rest: self.preview.select(row))
        lists.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(lists, 1)
        # Only where the remote can leave a place empty; the One closes a gap up.
        self.gap_btn.setVisible(remote is None or backends.screen_gaps(remote))

        self.dragger = RowDragger(self.table, self._moved)
        self.add_btn.clicked.connect(self._add)
        self.gap_btn.clicked.connect(self._add_gap)
        self.remove_btn.clicked.connect(self._remove)
        self.every_btn.clicked.connect(self._every)
        self.clear_btn.clicked.connect(self._clear)
        self.refresh()

    # - What is shown --------------------------------------------------
    def _device(self) -> dict:
        """The device as far as its page goes: its commands now, and its own buttons
        if it has been given any."""
        device = {"commands": [list(row) for row in self._rows() if row and row[0]]}
        if self._explicit:
            device["screen_buttons"] = self._loaded
        return device

    def refresh(self):
        """Show the page and the commands as the device has them now."""
        device = self._device()
        self._fill(project_devices.screen_buttons(device))
        self.commands.clear()
        for row in device["commands"]:
            item = QListWidgetItem(str(row[0]))
            item.setData(Qt.ItemDataRole.UserRole,
                         str(row[1]) if len(row) > 1 and row[1] else str(row[0]))
            self.commands.addItem(item)

    def _fill(self, entries: list):
        self._filling = True
        self.table.setRowCount(0)
        for entry in entries:
            self._insert(self.table.rowCount(), entry)
        self._filling = False
        self.dragger.refresh_grips()
        self._show()

    def _show(self):
        """Draw the page as the table has it now."""
        self.preview.set_buttons([
            None if entry is None else (entry[1], entry[2] if len(entry) > 2 else None)
            for entry in self.entries()])

    def _insert(self, row: int, entry):
        filling, self._filling = self._filling, True     # no half-made row is read
        self.table.insertRow(row)
        if entry is None:
            text = QTableWidgetItem(GAP_TEXT)
            text.setFlags(text.flags() & ~Qt.ItemFlag.ItemIsEditable)
            text.setForeground(Qt.GlobalColor.gray)
            sends = QTableWidgetItem("")
            sends.setData(Qt.ItemDataRole.UserRole, None)
        else:
            text = QTableWidgetItem(entry[1])
            sends = QTableWidgetItem(entry[0])
            # the icon, which nothing here edits, rides along with the command
            sends.setData(Qt.ItemDataRole.UserRole, list(entry))
        sends.setFlags(sends.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, text)
        self.table.setItem(row, 1, sends)
        self._filling = filling

    def entries(self) -> list:
        """The page as `screen_buttons`: `[command, text(, icon)]`, or None for a gap."""
        out = []
        for row in range(self.table.rowCount()):
            entry = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            if entry is None:
                out.append(None)
                continue
            entry = list(entry)
            entry[1] = self.table.item(row, 0).text()
            out.append(entry)
        return out

    # - Changes ---------------------------------------------------------
    def _changed(self):
        """Once arranged here, the device keeps its page as it is now."""
        self._explicit = True
        self._loaded = self.entries()
        self.dragger.refresh_grips()
        self._show()

    def _edited(self, _item):
        if not self._filling:
            self._changed()

    def _place(self) -> int:
        """Where a new button goes: after the one picked, or at the end."""
        picked = self.table.currentRow()
        return picked + 1 if picked >= 0 and self.table.selectedItems() else \
            self.table.rowCount()

    def _add(self):
        item = self.commands.currentItem()
        if item is None:
            return
        row = self._place()
        self._insert(row, [item.text(), item.data(Qt.ItemDataRole.UserRole)])
        self.table.selectRow(row)
        self._changed()

    def _add_gap(self):
        row = self._place()
        self._insert(row, None)
        self.table.selectRow(row)
        self._changed()

    def _remove(self):
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self._changed()

    def _every(self):
        self._fill([[str(row[0]), str(row[1]) if len(row) > 1 and row[1] else str(row[0])]
                    for row in self._rows() if row and row[0]])
        self._changed()

    def _clear(self):
        self._fill([])
        self._changed()

    def _moved(self, from_row: int, to_row: int):
        self._filling = True
        move_table_row(self.table, from_row, to_row)
        self._filling = False
        self._changed()

    def load(self, device: dict):
        """Start again from another model's page - or from its labels, when it has none."""
        self._explicit = device.get("screen_buttons") is not None
        self._loaded = list(device.get("screen_buttons") or [])
        self.refresh()

    # - Out -------------------------------------------------------------
    def apply(self, spec: dict) -> None:
        """Write the page into `spec`, if it has one of its own."""
        if self._explicit:
            spec["screen_buttons"] = self.entries()
        else:
            spec.pop("screen_buttons", None)
