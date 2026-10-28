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

from ..qt.QtCore import Qt
from ..qt.QtWidgets import (
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



def _first_command(steps) -> str | None:
    """The command a step list sends first: a name, or a held `{"command": ...}`."""
    for step in steps or []:
        if isinstance(step, str):
            return step
        if isinstance(step, dict) and isinstance(step.get("command"), str):
            return step["command"]
    return None

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
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Input", "Command", "App"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # A smart TV's apps (Netflix) answer only a while after it comes on: the remote
        # waits the Timing section's "Apps ready after switching on" before the first after
        # power-on. Not an edit of the inputs, so an imported Input state stays as it was.
        self.table.horizontalHeaderItem(2).setToolTip(
            "One of the TV's own apps, such as Netflix: after the TV comes on, the remote "
            "waits until its apps are ready before choosing it.")
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
    def take_power(self, power: QWidget):
        """Show the device's power commands at the top: switching a device on and
        choosing its input are what an activity does with it, so they sit together."""
        self.setTitle("Power & inputs")
        self.setSubTitle("How this device is switched on and off, how it is switched "
                         "to an input, and how it takes channel numbers.")
        box = QGroupBox("Power")
        layout = QVBoxLayout(box)
        layout.addWidget(power)
        explain = QLabel("Separate on and off commands let an activity switch the "
                         "device on without switching an already-on one off. A device "
                         "with one power button has only a toggle.")
        explain.setWordWrap(True)
        explain.setStyleSheet("color: gray;")
        layout.addWidget(explain)
        self.layout().insertWidget(0, box)
        heading = QLabel("<b>Inputs</b>")
        self.layout().insertWidget(1, heading)

    def load(self, device: dict) -> None:
        self._loading = True
        self.refresh_commands()
        inputs = device.get("inputs") or []
        cycle = device.get("input_cycle") or {}
        self._online = set(device.get("online_inputs") or [])
        direct = [pair for pair in inputs if len(pair) == 2 and pair[1]]
        mode = DIRECT if direct else CYCLE if cycle else DIRECT if inputs else NONE
        self.modes[mode].setChecked(True)
        self.table.setRowCount(0)
        # An input no command selects is its name alone - `["Input 3"]`, as an imported
        # Harmony One has them - and shows with no command.
        for entry in (inputs if mode == DIRECT else []):
            self._append_direct(entry[0], entry[1] if len(entry) > 1 else None)
        self.values.clear()
        for name in cycle.get("values") or ([pair[0] for pair in inputs]
                                              if mode == CYCLE else []):
            self._append_value(name)
        # A step may be more than a command: the archive starts a Panasonic TV's with a
        # one-second wait (`[{"delay_ms": 1000}, "TvVideo"]`), and putting that dict in
        # the list crashed Add Device. The list shows the command; the steps are kept
        # as they came unless another command is chosen.
        self._cycle_steps = {key: list(cycle.get(key) or [])
                             for key in ("next", "previous")}
        self._select(self.next_combo, _first_command(self._cycle_steps["next"]))
        self._select(self.prev_combo, _first_command(self._cycle_steps["previous"]))
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

    def follow(self, renames: dict) -> dict:
        """{a name the choices here may still show: the command's name now}, for
        commands renamed on the Commands page since they were last offered."""
        applied = getattr(self, "_renamed", {})
        current = {}
        for original, now in (renames or {}).items():
            last = applied.get(original, original)
            if last != now:
                current[last] = now
            applied[original] = now
        self._renamed = applied
        return current

    def refresh_commands(self, renames: dict | None = None) -> None:
        """Offer the device's commands as they stand on the Commands page now - keeping
        each choice on its command when that was renamed there."""
        moved = self.follow(renames)
        names = list(dict.fromkeys(self._commands() or []))
        for combo in (self.next_combo, self.prev_combo, self.finish):
            current = combo.currentData()
            current = moved.get(current, current)
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
                current = moved.get(current, current)
                widget.blockSignals(True)
                widget.clear()
                widget.addItem(NO_COMMAND, None)
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
        app = QTableWidgetItem()
        app.setFlags((app.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                     & ~Qt.ItemFlag.ItemIsEditable)
        app.setCheckState(Qt.CheckState.Checked if name in getattr(self, "_online", ())
                          else Qt.CheckState.Unchecked)
        self.table.setItem(row, 2, app)
        command = _row_command(selection)
        if selection is not None and command is None:
            kept = QTableWidgetItem(KEPT)
            kept.setData(256, selection)
            kept.setFlags(kept.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, kept)
            return
        combo = QComboBox()
        # "(none)" first: an input without a command must not take the first one
        combo.addItem(NO_COMMAND, None)
        for option in dict.fromkeys(self._commands() or []):
            combo.addItem(option, option)
        self._select(combo, command)
        combo.currentIndexChanged.connect(self._touch_inputs)
        self.table.setCellWidget(row, 1, combo)

    def _add_direct(self):
        self._append_direct(f"Input {self.table.rowCount() + 1}", None)
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

    def _touch_inputs(self, item=None, *_):
        # ticking App is not an edit of the inputs
        if isinstance(item, QTableWidgetItem) and item.column() == 2:
            return
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

    def online_inputs(self) -> list[str]:
        """The inputs ticked as the TV's apps."""
        out = []
        for row in range(self.table.rowCount()):
            name = (self.table.item(row, 0) or QTableWidgetItem("")).text().strip()
            app = self.table.item(row, 2)
            if name and app is not None and app.checkState() == Qt.CheckState.Checked:
                out.append(name)
        return out

    def cycle_spec(self) -> dict:
        out = {"values": [self.values.item(i).text().strip()
                          for i in range(self.values.count())
                          if self.values.item(i).text().strip()]}
        steps = getattr(self, "_cycle_steps", {})
        for key, combo in (("next", self.next_combo), ("previous", self.prev_combo)):
            command = combo.currentData()
            if command:
                kept = steps.get(key) or []
                out[key] = kept if _first_command(kept) == command else [command]
        if self.cycle_delay.value():
            out["delay_ms"] = self.cycle_delay.value()
        return out

    def apply(self, spec: dict) -> None:
        """Write what was changed here into a device spec; leave the rest alone."""
        online = self.online_inputs() if self._mode() == DIRECT else []
        if online:
            spec["online_inputs"] = online
        else:
            spec.pop("online_inputs", None)
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
            from ..qt.QtWidgets import QMessageBox
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
