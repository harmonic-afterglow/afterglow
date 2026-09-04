from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QDialog, QFormLayout, QComboBox,
    QDialogButtonBox, QLabel, QLineEdit, QSpinBox, QMessageBox,
    QRadioButton, QStackedWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator

from .ui_helpers import FilterCombo, order_by_participation

class CommandPicker(QDialog):
    def __init__(self, devices, parent=None, participating=None):
        super().__init__(parent)
        self.setWindowTitle("Add Command")
        self.devices = devices
        self.result_cmd = None

        layout = QFormLayout(self)
        # Filterable and bounded: a device with seventy commands opened a list taller
        # than the screen, and what you wanted was not always reachable.
        self.dev_combo = FilterCombo()
        self.dev_combo.setEditable(False)
        ordered, split = order_by_participation(devices, participating)
        self.dev_combo.set_items([(d.get("label", "?"), d["id"]) for d in ordered])
        if split:
            self.dev_combo.insertSeparator(split)

        self.cmd_combo = FilterCombo()
        # Press vs Hold. Real configs use Hold more often than Press - a volume key
        # that only ever sends Press steps one notch and stops.
        self.mod_combo = QComboBox()
        self.mod_combo.addItem("Press (a single tap)", "Press")
        self.mod_combo.addItem("Hold (repeat while held)", "Hold")
        layout.addRow("Device:", self.dev_combo)
        layout.addRow("Command:", self.cmd_combo)
        layout.addRow("Send as:", self.mod_combo)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)
        
        self.dev_combo.currentIndexChanged.connect(self._dev_changed)
        if self.dev_combo.count() > 0:
            self._dev_changed()
            
    def _dev_changed(self):
        device = next((d for d in self.devices
                       if d["id"] == self.dev_combo.currentData()), None)
        self.cmd_combo.set_items([(c[0], c[0]) for c in (device or {}).get("commands", [])])
                
    def accept(self):
        if self.dev_combo.currentData() and self.cmd_combo.currentData():
            self.result_cmd = (self.dev_combo.currentData(), self.cmd_combo.currentData(),
                               self.mod_combo.currentData())
            super().accept()


class StatePicker(QDialog):
    """Set one of a device's states - the input it is on, its power, anything it has.

    A television's input is often not a command but a state: sending the code for
    "HDMI 1" and telling the remote the television is now on HDMI 1 are different
    things, and only the second keeps the remote's tracking honest.
    """
    def __init__(self, devices, parent=None, participating=None):
        super().__init__(parent)
        self.setWindowTitle("Set a device state")
        self.devices = devices
        self.result_state = None

        layout = QFormLayout(self)
        self.dev_combo = FilterCombo()
        self.dev_combo.setEditable(False)
        ordered, split = order_by_participation(devices, participating)
        self.dev_combo.set_items([(d.get("label", "?"), d["id"]) for d in ordered])
        if split:
            self.dev_combo.insertSeparator(split)
        self.state_combo = FilterCombo()
        self.state_combo.setEditable(False)
        self.value_combo = FilterCombo()
        self.value_combo.setEditable(True)
        layout.addRow("Device:", self.dev_combo)
        layout.addRow("State:", self.state_combo)
        layout.addRow("Set to:", self.value_combo)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

        self.dev_combo.currentIndexChanged.connect(self._dev_changed)
        self.state_combo.currentIndexChanged.connect(self._state_changed)
        if self.dev_combo.count():
            self._dev_changed()

    def _device(self):
        return next((d for d in self.devices
                     if d["id"] == self.dev_combo.currentData()), None)

    def _dev_changed(self):
        self.state_combo.clear()
        device = self._device() or {}
        for state in device.get("states", []):
            self.state_combo.addItem(state.get("id", "?"), state.get("id"))
        if not device.get("states") and device.get("inputs"):
            self.state_combo.addItem("Input", "Input")
        self._state_changed()

    def _state_changed(self):
        self.value_combo.clear()
        device = self._device() or {}
        wanted = self.state_combo.currentData()
        for state in device.get("states", []):
            if state.get("id") != wanted:
                continue
            names = [a["name"] for a in state.get("actions", []) if a.get("name")]
            for value in names or state.get("values", []):
                self.value_combo.addItem(value, value)
            return
        for entry in device.get("inputs", []):
            self.value_combo.addItem(entry[0] if isinstance(entry, (list, tuple)) else entry)

    def accept(self):
        value = self.value_combo.currentText().strip()
        if self.dev_combo.currentData() and self.state_combo.currentData() and value:
            self.result_state = (self.dev_combo.currentData(),
                                 self.state_combo.currentData(), value)
            super().accept()

class DelayPicker(QDialog):
    """How long to wait, and which device to hold up."""

    def __init__(self, devices, default_device=None, parent=None, participating=None):
        super().__init__(parent)
        self.setWindowTitle("Add a delay")
        self.result_delay = None

        layout = QFormLayout(self)
        self.ms = QSpinBox()
        self.ms.setRange(50, 30000)
        self.ms.setSingleStep(100)
        self.ms.setValue(1000)
        self.ms.setSuffix(" ms")
        layout.addRow("Wait:", self.ms)

        self.device = FilterCombo()
        self.device.setEditable(False)
        ordered, split = order_by_participation(devices, participating)
        self.device.set_items([(d.get("label", "?"), d["id"]) for d in ordered])
        if split:
            self.device.insertSeparator(split)
        if default_device:
            self.device.select_data(default_device)
        layout.addRow("Before the next command to:", self.device)

        note = QLabel("The remote holds up only this device; commands to others "
                      "carry on meanwhile.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        layout.addRow("", note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def accept(self):
        if self.device.currentData():
            self.result_delay = (self.device.currentData(), self.ms.value())
        super().accept()


class InputPicker(QDialog):
    """One device, one input."""

    # Argument order matches CommandPicker, StatePicker and DelayPicker on purpose:
    # it arrived here with `participating` second, and the first caller written against
    # the house style passed a widget as the participation list.
    def __init__(self, devices, parent=None, participating=None):
        super().__init__(parent)
        self.setWindowTitle("Input switch")
        self.devices = devices
        self.result_data = None
        layout = QFormLayout(self)

        self.device = FilterCombo()
        self.device.setEditable(False)
        ordered, split = order_by_participation(devices, participating)
        self.device.set_items([(d.get("label", "?"), d["id"]) for d in ordered])
        if split:
            self.device.insertSeparator(split)
        layout.addRow("Device:", self.device)

        self.value = FilterCombo()
        layout.addRow("Switch to:", self.value)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.device.currentIndexChanged.connect(self._device_changed)
        self._device_changed()

    def _device_changed(self):
        device = next((d for d in self.devices
                       if d["id"] == self.device.currentData()), None)
        if device is None:
            self.value.set_items([])
            return
        # The values the device's Input state can take. Its full command list is not
        # that, and offering it is how a receiver was set to "DSPSimulation".
        names = [(i[0] if isinstance(i, (list, tuple)) else i)
                 for i in (device.get("inputs") or [])]
        if names:
            self.value.lineEdit().setPlaceholderText("type to filter…")
            self.value.set_items([(n, n) for n in names])
        else:
            self.value.lineEdit().setPlaceholderText(
                "no inputs known for this device - showing all commands")
            self.value.set_items([(c[0], c[0]) for c in device.get("commands", [])])

    def accept(self):
        device_id, value = self.device.currentData(), self.value.currentData()
        if not device_id or not value:
            QMessageBox.warning(self, "Nothing chosen",
                                "Pick a device and the input to switch it to.")
            return
        self.result_data = (device_id, value)
        super().accept()


class MacroEditorWidget(QWidget):
    # Emitted once the sequence has actually changed - that is, after a row is
    # fully built. QTableWidget.insertRow fires rowsInserted *before* setItem, so
    # anything listening to the model sees a row whose data is still missing; doing
    # that took the interpreter down rather than raising.
    changed = pyqtSignal()

    def __init__(self, devices, existing_macro=None, parent=None, participating=None):
        super().__init__(parent)
        self.devices = devices
        self._participating = list(participating or [])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        btn_row = QHBoxLayout()
        self.add_input_btn = QPushButton("Set Input")
        self.add_cmd_btn = QPushButton("Add Command")
        self.add_state_btn = QPushButton("Set State")
        self.add_chan_btn = QPushButton("Dial Channel")
        self.add_del_btn = QPushButton("Add Delay")
        self.up_btn = QPushButton("Up")
        self.dn_btn = QPushButton("Down")
        self.rem_btn = QPushButton("Remove")

        for b in [self.add_input_btn, self.add_cmd_btn, self.add_state_btn,
                  self.add_chan_btn,
                  self.add_del_btn, self.up_btn, self.dn_btn, self.rem_btn]:
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Type", "Device", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        
        self.add_input_btn.clicked.connect(self._add_input)
        self.add_cmd_btn.clicked.connect(self._add_cmd)
        self.add_state_btn.clicked.connect(self._add_state)
        self.add_chan_btn.clicked.connect(self._add_channel)
        self.add_del_btn.clicked.connect(self._add_delay)
        self.rem_btn.clicked.connect(self._rem)
        self.up_btn.clicked.connect(self._up)
        self.dn_btn.clicked.connect(self._dn)
        
        if existing_macro:
            for m in existing_macro:
                if len(m) >= 3:
                    self._add_row(*m)

    LABELS = {"command": "Command", "state": "Set state", "delay": "Delay",
              "number": "Channel", "input": "Set input"}

    def _add_row(self, mtype, dev, val, extra=None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(self.LABELS.get(mtype, mtype)))
        dev_label = next((d.get("label", "?") for d in self.devices if d["id"] == dev), dev)
        self.table.setItem(r, 1, QTableWidgetItem(dev_label))

        if mtype == "delay":
            v_str = f"{val} ms"
        elif mtype == "state":
            v_str = f"{val} = {extra}"                  # state name = value
        elif mtype == "command" and extra and extra != "Press":
            v_str = f"{val}  ({extra.lower()})"
        else:
            v_str = str(val)
        self.table.setItem(r, 2, QTableWidgetItem(v_str))
        step = (mtype, dev, val) if extra is None else (mtype, dev, val, extra)
        self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, step)
        self.changed.emit()
        
    def load(self, steps):
        """Replace the steps shown - used when editing a button that already exists."""
        self.table.setRowCount(0)
        for step in steps or []:
            if len(step) >= 3:
                self._add_row(*step)
        self.changed.emit()

    def set_participating(self, ids):
        """Which devices this activity uses, so they are offered first."""
        self._participating = list(ids or [])

    def _add_input(self):
        """Switch a device to one of its inputs.

        An input switch is an ordinary startup step - the format writes it as a
        SetValue on the device's Input state, which is what `('input', dev, value)`
        means. It belongs in the same list as the other steps so the order between a
        switch and a delay stays visible.
        """
        dialog = InputPicker(self.devices, self, self._participating)
        if dialog.exec() and dialog.result_data:
            self._add_row("input", *dialog.result_data)

    def _add_cmd(self):
        dlg = CommandPicker(self.devices, self, self._participating)
        if dlg.exec() and dlg.result_cmd:
            dev, cmd, modifier = dlg.result_cmd
            self._add_row("command", dev, cmd, modifier)

    def _add_state(self):
        dlg = StatePicker(self.devices, self, self._participating)
        if dlg.exec() and dlg.result_state:
            dev, state, value = dlg.result_state
            self._add_row("state", dev, state, value)

    def _add_channel(self):
        if not self.devices:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Dial a channel")
        form = QFormLayout(dlg)
        dev_combo = FilterCombo()
        dev_combo.setEditable(False)
        for d in self.devices:
            dev_combo.addItem(d.get("label", "?"), d["id"])
        number = QLineEdit()
        number.setValidator(QIntValidator(0, 99999, dlg))
        number.setPlaceholderText("e.g. 101")
        form.addRow("Device:", dev_combo)
        form.addRow("Channel:", number)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() and number.text().strip():
            self._add_row("number", dev_combo.currentData(), number.text().strip())
            
    def _add_delay(self):
        """A pause, on a particular device.

        A delay is not global: the remote marks *that device* as busy and lets
        commands for other devices carry on. So a delay meant to separate two presses
        on the satellite box has to name the satellite box - attaching it to whichever
        device happened to be first in the list, as this did, produced a macro whose
        two commands fired back to back and a wait shown against the wrong name.

        The device therefore defaults to the one the previous step used, which is
        almost always what a pause is for, and stays editable.
        """
        if not self.devices:
            return
        dialog = DelayPicker(self.devices, self._previous_device(), self,
                             self._participating)
        if dialog.exec() and dialog.result_delay:
            device_id, ms = dialog.result_delay
            self._add_row("delay", device_id, ms)

    def _previous_device(self):
        """The device the last step acts on, if there is one."""
        for row in range(self.table.rowCount() - 1, -1, -1):
            step = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if step and len(step) > 1:
                return step[1]
        return None
            
    def _rem(self):
        for item in self.table.selectedItems():
            self.table.removeRow(item.row())
            break
        self.changed.emit()
            
    def _up(self):
        r = self.table.currentRow()
        if r > 0:
            self._swap(r, r - 1)
            self.table.selectRow(r - 1)
            
    def _dn(self):
        r = self.table.currentRow()
        if r >= 0 and r < self.table.rowCount() - 1:
            self._swap(r, r + 1)
            self.table.selectRow(r + 1)
            
    def _swap(self, r1, r2):
        t1 = self.table.takeItem(r1, 0)
        d1 = self.table.takeItem(r1, 1)
        v1 = self.table.takeItem(r1, 2)
        
        t2 = self.table.takeItem(r2, 0)
        d2 = self.table.takeItem(r2, 1)
        v2 = self.table.takeItem(r2, 2)
        
        self.table.setItem(r1, 0, t2)
        self.table.setItem(r1, 1, d2)
        self.table.setItem(r1, 2, v2)
        
        self.table.setItem(r2, 0, t1)
        self.table.setItem(r2, 1, d1)
        self.table.setItem(r2, 2, v1)
        
    def get_macro(self):
        out = []
        for r in range(self.table.rowCount()):
            cell = self.table.item(r, 0)
            step = cell.data(Qt.ItemDataRole.UserRole) if cell is not None else None
            if step:                       # a half-built row is not a step
                out.append(step)
        return out


# one sequence, two ways of looking at it
#
# Most activities do one plain thing when they start: switch a device or two to the
# right input and let each device's own timings settle it. A step list is more than
# that needs. But the moment a sequence has a wait, or sends a command, a table of
# inputs cannot say what it does - and the failure mode to avoid is the one that has
# already cost this project six separate bugs: a view that quietly drops what it cannot
# show.
#
# So Simple is offered only when it can represent the sequence completely. Otherwise it
# is disabled and says why. It is never a lossy view of a richer thing.

SIMPLE_KIND = "input"

_KIND_NAMES = {"command": "a command", "delay": "a wait", "state": "a state change",
               "number": "a channel"}


def can_be_simple(steps) -> bool:
    """Whether a plain table of input switches says everything this sequence does."""
    return all(step and step[0] == SIMPLE_KIND for step in steps or [])


def why_not_simple(steps) -> str:
    """What is in the way, in the words the interface should use."""
    kinds = [step[0] for step in steps or [] if step and step[0] != SIMPLE_KIND]
    if not kinds:
        return ""
    names = sorted({_KIND_NAMES.get(k, k) for k in kinds})
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"Advanced only - this sequence also has {listed}."


class SimpleStartupList(QWidget):
    """Just the inputs: which device switches to what, one row each."""

    def __init__(self, devices, steps=None, parent=None, participating=None):
        super().__init__(parent)
        self.devices = devices
        self._participating = list(participating or [])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.add_btn = QPushButton("Add input switch…")
        self.rem_btn = QPushButton("Remove")
        row.addWidget(self.add_btn)
        row.addWidget(self.rem_btn)
        row.addStretch()
        layout.addLayout(row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Device", "Switch to"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        self.add_btn.clicked.connect(self._add)
        self.rem_btn.clicked.connect(self._remove)
        self.load(steps)

    def set_participating(self, ids):
        self._participating = list(ids or [])

    def _add_row(self, device_id, value):
        r = self.table.rowCount()
        self.table.insertRow(r)
        label = next((d.get("label", "?") for d in self.devices
                      if d["id"] == device_id), device_id)
        self.table.setItem(r, 0, QTableWidgetItem(label))
        self.table.setItem(r, 1, QTableWidgetItem(str(value)))
        self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, (device_id, value))

    def _add(self):
        dialog = InputPicker(self.devices, self, self._participating)
        if dialog.exec() and dialog.result_data:
            self._add_row(*dialog.result_data)

    def _remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def load(self, steps):
        self.table.setRowCount(0)
        for step in steps or []:
            if step and step[0] == SIMPLE_KIND:
                self._add_row(step[1], step[2])

    def get_macro(self):
        return [(SIMPLE_KIND, *self.table.item(r, 0).data(Qt.ItemDataRole.UserRole))
                for r in range(self.table.rowCount())]


class StartupEditor(QWidget):
    """A sequence, shown simply when that is honest and in full when it is not.

    Stands in for MacroEditorWidget and keeps its interface (`load`, `get_macro`,
    `set_participating`), so the pages using it do not care which view is on screen.
    Only one view is ever live: the other is filled from it when the toggle is thrown,
    which is what keeps this from becoming two half-editors over one list again.
    """

    def __init__(self, devices, steps=None, parent=None, participating=None):
        super().__init__(parent)
        steps = list(steps or [])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.simple_btn = QRadioButton("Simple")
        self.advanced_btn = QRadioButton("Advanced")
        self.reason = QLabel("")
        self.reason.setStyleSheet("color: gray;")
        row.addWidget(self.simple_btn)
        row.addWidget(self.advanced_btn)
        row.addWidget(self.reason, 1)
        layout.addLayout(row)

        self.simple = SimpleStartupList(devices, steps, participating=participating)
        self.advanced = MacroEditorWidget(devices, steps, participating=participating)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.simple)
        self.stack.addWidget(self.advanced)
        layout.addWidget(self.stack)

        # Which view opens is decided by the activity, not by a remembered preference:
        # a straightforward one never has to see a step list, and a complicated one is
        # never shown a view that cannot describe it.
        self._show(simple=can_be_simple(steps))
        self.simple_btn.toggled.connect(self._toggled)
        self.advanced.changed.connect(self._refresh_availability)

    # the toggle
    def _show(self, simple: bool):
        button = self.simple_btn if simple else self.advanced_btn
        for b in (self.simple_btn, self.advanced_btn):
            b.blockSignals(True)
        button.setChecked(True)
        for b in (self.simple_btn, self.advanced_btn):
            b.blockSignals(False)
        self.stack.setCurrentWidget(self.simple if simple else self.advanced)
        self._refresh_availability()

    def _toggled(self, simple_now: bool):
        """Carry the sequence across, so the view that appears shows what was there."""
        if simple_now:
            steps = self.advanced.get_macro()
            # Refused in code, not merely greyed out. Disabling a radio button stops a
            # user clicking it and nothing else - setChecked still works - so relying on
            # that alone left the one path where somebody's three-second projector delay
            # could be silently dropped.
            if not can_be_simple(steps):
                self._show(simple=False)
                return
            self.simple.load(steps)
            self.stack.setCurrentWidget(self.simple)
        else:
            self.advanced.load(self.simple.get_macro())
            self.stack.setCurrentWidget(self.advanced)

    def _refresh_availability(self, *_):
        """Simple is selectable only while it can say everything the sequence does."""
        steps = self.get_macro()
        allowed = can_be_simple(steps)
        self.simple_btn.setEnabled(allowed or self.stack.currentWidget() is self.simple)
        self.reason.setText("" if allowed else why_not_simple(steps))

    # the interface the pages use
    def load(self, steps):
        steps = list(steps or [])
        self.simple.load(steps)
        self.advanced.load(steps)
        self._show(simple=can_be_simple(steps))

    def get_macro(self):
        return self.stack.currentWidget().get_macro()

    def set_participating(self, ids):
        self.simple.set_participating(ids)
        self.advanced.set_participating(ids)
