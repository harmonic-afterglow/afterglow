"""Which devices an activity switches on, in what order, and which it switches off.

The builder has always taken `power_on_devices` and `power_off_devices`, and imported
activities kept theirs, but nothing let anyone set them: a new activity powered its
display, volume and control devices and switched everything else off. That is right
until it is not - a subwoofer on its own power, a projector that must be up before the
receiver, a light that should stay as it is.

Every device ends up in one list or the other: all 18 Logitech configurations measured
list every device in every activity, and the builder adds any device left out to the
off list. So the choice offered is on or off, never "leave alone"; a device the remote
must never switch is marked AlwaysOn on its own Timing page, which the remote honours
whatever an activity says.
"""
from __future__ import annotations

from copy import deepcopy

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWizardPage, QAbstractItemView, QHeaderView,
)

ON, OFF = "on", "off"


class ActivityPowerPage(QWizardPage):
    def __init__(self, devices, existing, parent=None):
        super().__init__(parent)
        self.setTitle("Power")
        self.setSubTitle("Which devices this activity switches on - in the order they "
                         "start - and which it switches off.")
        self.devices = {str(d["id"]): d for d in devices}
        self._participating: list[str] = []
        # The order an imported plan switches things off in is kept as it was.
        self._off_order = [str(d) for d in existing.get("power_off_devices") or []]
        # Until someone changes something here, the plan is handed back exactly as it
        # came in - even a shape this page would not produce itself.
        self._original = (deepcopy(existing.get("power_on_devices")),
                          deepcopy(existing.get("power_off_devices")))
        self._touched = False
        layout = QVBoxLayout(self)

        self.follow = QCheckBox("Follow the roles: switch on the devices this activity "
                                "uses, switch the rest off")
        manual = bool(existing.get("power_on_devices") or existing.get("power_off_devices"))
        self.follow.setChecked(not manual)
        self.follow.toggled.connect(self._follow_toggled)
        layout.addWidget(self.follow)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Device", "When the activity starts"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

        order = QHBoxLayout()
        self.up = QPushButton("Start earlier")
        self.down = QPushButton("Start later")
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        order.addWidget(self.up)
        order.addWidget(self.down)
        order.addStretch()
        layout.addLayout(order)
        note = QLabel("Devices switched on start from the top down. A device marked "
                      "Always on (on its Timing page) is never switched by the remote, "
                      "whatever is chosen here.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        if manual:
            # Every device is on or off, so an imported plan that names only what goes
            # off switches everything else on.
            if existing.get("power_on_devices") is not None:
                on = [str(d) for d in existing["power_on_devices"]]
            else:
                off = {str(d) for d in existing.get("power_off_devices") or []}
                on = [d for d in self.devices if d not in off]
            self._fill(on)
        else:
            self._fill(self._from_roles())
        self._follow_toggled(self.follow.isChecked())

    # what the roles imply
    def set_participating(self, ids):
        self._participating = [str(i) for i in ids if i]
        if self.follow.isChecked():
            self._fill(self._from_roles())

    def _from_roles(self):
        return [i for i in self._participating if i in self.devices]

    # the table: switched-on devices first, in order, then the rest
    def _fill(self, on_ids):
        on = [i for i in dict.fromkeys(on_ids) if i in self.devices]
        rest = sorted((i for i in self.devices if i not in on),
                      key=lambda i: (self._off_order.index(i) if i in self._off_order
                                     else len(self._off_order)))
        self.table.setRowCount(0)
        for device_id in on + rest:
            device = self.devices[device_id]
            row = self.table.rowCount()
            self.table.insertRow(row)
            label = device.get("label") or device_id
            if device.get("always_on"):
                label += "  (always on)"
            item = QTableWidgetItem(label)
            item.setData(256, device_id)
            self.table.setItem(row, 0, item)
            choice = QComboBox()
            choice.addItem("Switch on", ON)
            choice.addItem("Switch off", OFF)
            choice.setCurrentIndex(0 if device_id in on else 1)
            choice.currentIndexChanged.connect(self._regroup)
            self.table.setCellWidget(row, 1, choice)

    def _rows(self):
        return [(self.table.item(r, 0).data(256),
                 self.table.cellWidget(r, 1).currentData())
                for r in range(self.table.rowCount())]

    def _regroup(self, *_):
        """Keep switched-on devices together at the top, in the order they had."""
        self._touched = True
        self._fill([device_id for device_id, state in self._rows() if state == ON])

    def _move(self, step):
        rows = self._rows()
        row = self.table.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < len(rows) or rows[row][1] != ON \
                or rows[target][1] != ON:
            return
        self._touched = True
        on = [device_id for device_id, state in rows if state == ON]
        on[row], on[target] = on[target], on[row]
        self._fill(on)
        self.table.selectRow(target)

    def _follow_toggled(self, follow):
        if self.sender() is self.follow:
            self._touched = True
        if follow:
            self._fill(self._from_roles())
        for widget in (self.table, self.up, self.down):
            widget.setEnabled(not follow)

    # the result
    def get_plan(self):
        """None to follow the roles, else (devices switched on in order, the rest)."""
        if self.follow.isChecked():
            return None
        if not self._touched and self._original != (None, None):
            on, off = self._original
            return (on if on is not None else
                    [d for d, state in self._rows() if state == ON], off or [])
        rows = self._rows()
        return ([d for d, state in rows if state == ON],
                [d for d, state in rows if state == OFF])


def apply_plan(spec: dict, plan) -> None:
    """Write a power plan into an activity spec, or clear it to follow the roles."""
    if plan is None:
        spec.pop("power_on_devices", None)
        spec.pop("power_off_devices", None)
        return
    spec["power_on_devices"], spec["power_off_devices"] = plan
