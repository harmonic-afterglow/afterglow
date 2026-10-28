"""Which devices an activity switches on, in what order, and which it switches off.

The builder has always taken `power_on_devices` and `power_off_devices`, and imported
activities kept theirs, but nothing let anyone set them: a new activity powered its
display, volume and control devices and switched everything else off. That is right
until it is not - a subwoofer on its own power, a projector that must be up before the
receiver, a light that should stay as it is.

Every device ends up in one list or the other in all 18 Logitech configurations
measured, and the builder adds any device left out to the off list. A device can also be
left as it is - in neither list (`power_leave_devices`) - for one an activity must not
touch, which a tester asked for: no Logitech configuration has one, and whether each
remote then leaves it alone is for hardware to confirm. A device the remote must never
switch at all is marked AlwaysOn in its Timing, which the remote honours whatever an
activity says.
"""
from __future__ import annotations

from copy import deepcopy

from ..qt.QtWidgets import (
    QCheckBox, QComboBox, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWizardPage, QAbstractItemView, QHeaderView,
)

from .drag_rows import RowDragger, moved_list

ON, OFF, LEAVE = "on", "off", "leave"


class ActivityPowerPage(QWizardPage):
    def __init__(self, devices, existing, parent=None):
        super().__init__(parent)
        self.setTitle("Power")
        self.setSubTitle("Which devices this activity switches on - in the order they "
                         "start - which it switches off, and which it leaves as they are.")
        self.devices = {str(d["id"]): d for d in devices}
        self._participating: list[str] = []
        # The order an imported plan switches things off in is kept as it was.
        self._off_order = [str(d) for d in existing.get("power_off_devices") or []]
        # Until someone changes something here, the plan is handed back exactly as it
        # came in - even a shape this page would not produce itself.
        self._original = (deepcopy(existing.get("power_on_devices")),
                          deepcopy(existing.get("power_off_devices")))
        self._touched = False
        # Devices this activity leaves as they are, neither switched on nor off.
        self._leave = {str(d) for d in existing.get("power_leave_devices") or []}
        layout = QVBoxLayout(self)

        self.follow = QCheckBox("Follow the roles: switch on the devices this activity "
                                "uses, switch the rest off")
        manual = bool(existing.get("power_on_devices") or existing.get("power_off_devices")
                      or existing.get("power_leave_devices"))
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
        # Only the devices switched on have an order: they are dragged by their grip.
        self.dragger = RowDragger(self.table, self._dragged, movable=self._orderable)

        note = QLabel("Devices switched on start from the top down; drag one by its grip "
                      "to start it earlier or later. A device marked Always on (in its "
                      "Timing) is never switched by the remote, whatever is chosen here.")
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
            # neither: a device the activity does not touch, as it was before
            choice.addItem("Leave as it is", LEAVE)
            choice.setCurrentIndex(0 if device_id in on
                                   else 2 if device_id in self._leave else 1)
            choice.currentIndexChanged.connect(self._regroup)
            self.table.setCellWidget(row, 1, choice)
        if hasattr(self, "dragger"):
            self.dragger.refresh_grips()

    def _rows(self):
        return [(self.table.item(r, 0).data(256),
                 self.table.cellWidget(r, 1).currentData())
                for r in range(self.table.rowCount())]

    def _regroup(self, *_):
        """Keep switched-on devices together at the top, in the order they had."""
        self._touched = True
        self._leave = {device_id for device_id, state in self._rows() if state == LEAVE}
        self._fill([device_id for device_id, state in self._rows() if state == ON])

    def _orderable(self, row):
        """Switched on, and chosen here rather than following the roles."""
        choice = self.table.cellWidget(row, 1)
        return (not self.follow.isChecked() and choice is not None
                and choice.currentData() == ON)

    def _dragged(self, from_row, to_row):
        """A switched-on device moved among the others switched on."""
        rows = self._rows()
        on = [device_id for device_id, state in rows if state == ON]
        if not (from_row < len(on) and to_row < len(on)):
            return
        self._touched = True
        self._fill(moved_list(on, from_row, to_row))
        self.table.selectRow(to_row)

    def _follow_toggled(self, follow):
        if self.sender() is self.follow:
            self._touched = True
        if follow:
            self._fill(self._from_roles())
        self.table.setEnabled(not follow)
        self.dragger.refresh_grips()

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


    def leave(self) -> list[str]:
        """The devices this activity leaves as they are - with its plan, not the roles."""
        if self.follow.isChecked():
            return []
        return [device_id for device_id, state in self._rows() if state == LEAVE]


def apply_plan(spec: dict, plan, leave=()) -> None:
    """Write a power plan into an activity spec, or clear it to follow the roles. The
    devices it leaves as they are go in neither list, and in `power_leave_devices`."""
    spec.pop("power_leave_devices", None)
    if plan is None:
        spec.pop("power_on_devices", None)
        spec.pop("power_off_devices", None)
        return
    leave = [str(device) for device in leave or ()]
    on, off = plan
    spec["power_on_devices"] = [d for d in on if str(d) not in leave]
    spec["power_off_devices"] = [d for d in off if str(d) not in leave]
    if leave:
        spec["power_leave_devices"] = leave
