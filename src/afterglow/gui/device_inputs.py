"""How a device is switched between its inputs, and how it takes channel numbers.

Logitech's configurations do this three ways, and the builder can write all of them:
each input reached by its own command, inputs stepped through with one button in a known
order, and channel numbers typed on the number keys. Across 18 Harmony 900 configurations
56 main Input states are direct and 10 step, and 59 of 141 devices take numbers. None of
it could be set here: a device got whatever the catalogue said, and one added by hand got
nothing - which for a television that only has an "Input" button meant no activity could
ever switch it to the right source.

A device imported from a configuration carries its real state machine. Edited here, its
Input state is regenerated from what is shown (`inputs_edited`) and every other state is
kept as it was; untouched, nothing about it changes.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QWizardPage,
)

NONE, DIRECT, CYCLE = "none", "direct", "cycle"
NO_COMMAND = "(none)"
# An input reached by a sequence or through another state is kept as it is; it is shown
# but not offered for editing, because one command cannot say what it does.
KEPT = "(kept as imported)"


def _row_command(selection) -> str | None:
    return selection if isinstance(selection, str) else None


class DeviceInputsPage(QWizardPage):
    def __init__(self, existing: dict, commands, parent=None):
        """`commands` returns the device's command names as they are right now."""
        super().__init__(parent)
        self.setTitle("Inputs")
        self.setSubTitle("How this device is switched to an input, and how it takes "
                         "channel numbers.")
        self._commands = commands
        self.inputs_touched = self.numeric_touched = False
        layout = QVBoxLayout(self)

        self.mode_group = QButtonGroup(self)
        self.modes = {}
        for mode, text in ((NONE, "It has no inputs to switch"),
                           (DIRECT, "Each input has its own command"),
                           (CYCLE, "One command steps through the inputs in order")):
            button = QRadioButton(text)
            self.modes[mode] = button
            self.mode_group.addButton(button)
            layout.addWidget(button)
        self.mode_group.buttonToggled.connect(self._mode_changed)

        # each input its own command
        self.direct = QWidget()
        direct = QVBoxLayout(self.direct)
        direct.setContentsMargins(20, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Input", "Command"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._touch_inputs)
        direct.addWidget(self.table)
        row = QHBoxLayout()
        for text, slot in (("Add input", self._add_direct), ("Remove", self._remove_direct)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch()
        direct.addLayout(row)
        layout.addWidget(self.direct)

        # one command steps
        self.cycle = QWidget()
        cycle = QFormLayout(self.cycle)
        cycle.setContentsMargins(20, 0, 0, 0)
        self.values = QListWidget()
        self.values.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.values.model().rowsMoved.connect(self._touch_inputs)
        self.values.itemChanged.connect(self._touch_inputs)
        buttons = QHBoxLayout()
        for text, slot in (("Add", self._add_value), ("Remove", self._remove_value)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()
        values = QVBoxLayout()
        values.addWidget(self.values)
        values.addLayout(buttons)
        explain = QLabel("In the order one press moves through them. The remote counts "
                         "presses to reach an input, so the order has to be the device's.")
        explain.setWordWrap(True)
        explain.setStyleSheet("color: gray;")
        values.addWidget(explain)
        cycle.addRow("Inputs:", values)
        self.next_combo, self.prev_combo = QComboBox(), QComboBox()
        for combo in (self.next_combo, self.prev_combo):
            combo.currentIndexChanged.connect(self._touch_inputs)
        cycle.addRow("Next input:", self.next_combo)
        cycle.addRow("Previous input:", self.prev_combo)
        self.cycle_delay = QSpinBox()
        self.cycle_delay.setRange(0, 10000)
        self.cycle_delay.setSuffix(" ms")
        self.cycle_delay.valueChanged.connect(self._touch_inputs)
        cycle.addRow("Wait between presses:", self.cycle_delay)
        layout.addWidget(self.cycle)

        # channel numbers
        numbers = QGroupBox("Channel numbers")
        form = QFormLayout(numbers)
        self.numeric = QCheckBox("Takes channel numbers on its number keys")
        self.numeric.toggled.connect(self._touch_numeric)
        form.addRow(self.numeric)
        self.fixed = QSpinBox()
        self.fixed.setRange(0, 6)
        self.fixed.setSpecialValueText("as typed")
        self.fixed.setToolTip("Pad to this many digits: with 2, channel 7 is sent as 07")
        self.fixed.valueChanged.connect(self._touch_numeric)
        form.addRow("Always send this many digits:", self.fixed)
        self.finish = QComboBox()
        self.finish.currentIndexChanged.connect(self._touch_numeric)
        form.addRow("Then press:", self.finish)
        self.numeric_note = QLabel()
        self.numeric_note.setWordWrap(True)
        self.numeric_note.setStyleSheet("color: gray;")
        form.addRow(self.numeric_note)
        layout.addWidget(numbers)
        layout.addStretch()

        self.load(existing or {})

    # filling the page from a device or a catalogue entry
    def load(self, device: dict) -> None:
        self._loading = True
        self.refresh_commands()
        inputs = device.get("inputs") or []
        cycle = device.get("input_cycle") or {}
        direct = [pair for pair in inputs if len(pair) == 2 and pair[1]]
        mode = DIRECT if direct else CYCLE if cycle else DIRECT if inputs else NONE
        self.modes[mode].setChecked(True)
        self.table.setRowCount(0)
        for name, selection in (inputs if mode == DIRECT else []):
            self._append_direct(name, selection)
        self.values.clear()
        for name in cycle.get("values") or ([pair[0] for pair in inputs]
                                              if mode == CYCLE else []):
            self._append_value(name)
        self._select(self.next_combo, (cycle.get("next") or [None])[0])
        self._select(self.prev_combo, (cycle.get("previous") or [None])[0])
        self.cycle_delay.setValue(int(cycle.get("delay_ms") or 0))

        numeric = device.get("numeric")
        self.numeric.setChecked(bool(numeric))
        spec = numeric if isinstance(numeric, dict) else {}
        self.fixed.setValue(int(spec.get("fixed") or 0))
        self._select(self.finish, spec.get("finish") if isinstance(spec.get("finish"), str)
                     else None)
        imported = isinstance(numeric, dict) and "digits" in numeric
        self.numeric_note.setText(
            "Imported with its own digit actions; those are kept unless you change "
            "something here." if imported else "")
        self.inputs_touched = self.numeric_touched = False
        self._loading = False
        self._show_mode()

    def refresh_commands(self) -> None:
        """Offer the device's commands as they stand on the Commands page now."""
        names = list(dict.fromkeys(self._commands() or []))
        for combo in (self.next_combo, self.prev_combo, self.finish):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(NO_COMMAND, None)
            for name in names:
                combo.addItem(name, name)
            self._select(combo, current)
            combo.blockSignals(False)
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 1)
            if isinstance(widget, QComboBox):
                current = widget.currentData()
                widget.blockSignals(True)
                widget.clear()
                for name in names:
                    widget.addItem(name, name)
                self._select(widget, current)
                widget.blockSignals(False)

    @staticmethod
    def _select(combo, value):
        index = combo.findData(value) if value is not None else 0
        if index < 0 and value is not None:          # a command this list does not have
            combo.addItem(value, value)
            index = combo.count() - 1
        combo.setCurrentIndex(max(index, 0))

    # direct
    def _append_direct(self, name, selection):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        command = _row_command(selection)
        if selection is not None and command is None:
            kept = QTableWidgetItem(KEPT)
            kept.setData(256, selection)
            kept.setFlags(kept.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, kept)
            return
        combo = QComboBox()
        for option in dict.fromkeys(self._commands() or []):
            combo.addItem(option, option)
        self._select(combo, command)
        combo.currentIndexChanged.connect(self._touch_inputs)
        self.table.setCellWidget(row, 1, combo)

    def _add_direct(self):
        self._append_direct(f"Input {self.table.rowCount() + 1}", "")
        self._touch_inputs()

    def _remove_direct(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self._touch_inputs()

    # cycle
    def _append_value(self, name):
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.values.addItem(item)

    def _add_value(self):
        self._append_value(f"Input {self.values.count() + 1}")
        self._touch_inputs()

    def _remove_value(self):
        if self.values.currentRow() >= 0:
            self.values.takeItem(self.values.currentRow())
            self._touch_inputs()

    # what changed
    def _mode(self):
        return next(mode for mode, button in self.modes.items() if button.isChecked())

    def _mode_changed(self, *_):
        self._show_mode()
        self._touch_inputs()

    def _show_mode(self):
        mode = self._mode()
        self.direct.setVisible(mode == DIRECT)
        self.cycle.setVisible(mode == CYCLE)

    def _touch_inputs(self, *_):
        if not getattr(self, "_loading", False):
            self.inputs_touched = True

    def _touch_numeric(self, *_):
        if not getattr(self, "_loading", False):
            self.numeric_touched = True
        enabled = self.numeric.isChecked()
        self.fixed.setEnabled(enabled)
        self.finish.setEnabled(enabled)

    # the result
    def direct_inputs(self) -> list[list]:
        out = []
        for row in range(self.table.rowCount()):
            name = (self.table.item(row, 0) or QTableWidgetItem("")).text().strip()
            widget = self.table.cellWidget(row, 1)
            selection = (widget.currentData() if isinstance(widget, QComboBox)
                         else (self.table.item(row, 1).data(256)
                               if self.table.item(row, 1) else None))
            if name:
                out.append([name, selection])
        return out

    def cycle_spec(self) -> dict:
        out = {"values": [self.values.item(i).text().strip()
                          for i in range(self.values.count())
                          if self.values.item(i).text().strip()]}
        if self.next_combo.currentData():
            out["next"] = [self.next_combo.currentData()]
        if self.prev_combo.currentData():
            out["previous"] = [self.prev_combo.currentData()]
        if self.cycle_delay.value():
            out["delay_ms"] = self.cycle_delay.value()
        return out

    def apply(self, spec: dict) -> None:
        """Write what was changed here into a device spec; leave the rest alone."""
        if self.inputs_touched:
            mode = self._mode()
            spec["inputs"] = self.direct_inputs() if mode == DIRECT else []
            if mode == CYCLE:
                spec["input_cycle"] = self.cycle_spec()
            else:
                spec.pop("input_cycle", None)
            if spec.get("states"):
                spec["inputs_edited"] = True
        if self.numeric_touched:
            if not self.numeric.isChecked():
                spec.pop("numeric", None)
            elif self.fixed.value() or self.finish.currentData():
                spec["numeric"] = {
                    **({"fixed": self.fixed.value()} if self.fixed.value() else {}),
                    **({"finish": self.finish.currentData()}
                       if self.finish.currentData() else {})}
            else:
                spec["numeric"] = True

    def initializePage(self):
        self.refresh_commands()

    def validatePage(self) -> bool:
        problem = self.problem()
        if problem:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Inputs", problem)
        return problem is None

    def problem(self) -> str | None:
        """Why the inputs as shown could not be written, if they could not."""
        if self._mode() == CYCLE and self.inputs_touched:
            cycle = self.cycle_spec()
            if not cycle.get("next") and not cycle.get("previous"):
                return "Choose the command that steps to the next input."
            if not cycle["values"]:
                return ("List the inputs in the order the device steps through them: "
                        "the remote counts presses to reach one, and cannot without them.")
        return None
