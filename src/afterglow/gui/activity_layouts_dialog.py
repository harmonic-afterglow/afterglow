"""An activity's Sound or Picture layout, in a window of its own.

On a remote with Sound and Picture keys (the 550's and 555's, the 688's;
`RemoteProfile.layout_kinds`), pressing one turns an activity's keys and screen over to
one device until it is pressed again: a few keys of that device (the amplifier's volume,
the TV's menu keys) and buttons of its own, every other key left to the activity
(afterglow.activity_layouts). The Activities tab lists both under each activity, and
each opens here: the device, the keys it takes over, and its screen buttons - one thing
at a time, so its keys are never mistaken for the activity's own.

The project keeps only what differs from Logitech's defaults (`activity_layouts.minimal`),
so a layout nobody changed follows the activity's Volume and Display.
"""
from __future__ import annotations

import copy
import re

from ..qt.QtCore import QObject, pyqtSignal
from ..qt.QtGui import QStandardItemModel
from ..qt.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
                             QWizardPage)

from .. import activity_layouts
from .sections import SectionDialog

# The parts of an activity its layouts' defaults go by.
_ROLES = ("display", "volume", "control", "power_on_devices")


class Layouts(QObject):
    """An activity's Sound and Picture layouts while one of them is being edited.

    The truth is what the project stores (``activity["layouts"]``, only differences);
    every view of a layout is resolved from it against the activity's devices, so a
    layout nobody changed follows the activity's Volume and Display."""

    changed = pyqtSignal()

    def __init__(self, devices, existing: dict, parent=None):
        super().__init__(parent)
        self.devices = list(devices or [])
        self._roles = {key: copy.deepcopy(existing.get(key)) for key in _ROLES}
        self.stored = copy.deepcopy(existing.get("layouts") or {})

    def activity(self, stored=None) -> dict:
        return dict(self._roles, layouts=self.stored if stored is None else stored)

    def resolved(self, stored=None) -> dict:
        return activity_layouts.resolve(self.activity(stored), self.devices)

    def layout(self, kind: str) -> dict | None:
        """The layout as the remote will have it - a copy to change and hand back - or
        None when the activity has none of this kind."""
        return copy.deepcopy(self.resolved().get(kind))

    def default_device(self, kind: str) -> str | None:
        return activity_layouts.default_device(self._roles, kind, self.devices)

    def _store(self, resolved: dict) -> None:
        self.stored = activity_layouts.minimal(self.activity(), self.devices, resolved)
        self.changed.emit()

    def set_layout(self, kind: str, layout: dict | None) -> None:
        resolved = self.resolved()
        if layout is None:
            resolved.pop(kind, None)
        else:
            resolved[kind] = layout
        self._store(resolved)

    def set_part(self, kind: str, field: str, value) -> None:
        """Change one part of a layout - its keys or its buttons - and keep the rest."""
        layout = self.layout(kind)
        if layout is not None:
            layout[field] = copy.deepcopy(value)
            self.set_layout(kind, layout)

    def set_device(self, kind: str, device_id: str | None) -> None:
        """Give the layout to another device - with that device's own defaults - or
        none, for an activity with no layout of this kind."""
        stored = dict(self.stored, **{kind: {"device": device_id}})
        self._store(self.resolved(stored))

    def reset(self, kind: str) -> None:
        """Logitech's layout again: the default device, keys and buttons."""
        stored = {k: v for k, v in self.stored.items() if k != kind}
        self._store(self.resolved(stored))

    def changed_from_default(self, kind: str) -> bool:
        return kind in self.stored

    def apply(self, spec: dict) -> None:
        """Write the layouts into ``spec``, the activity they are for."""
        if self.stored:
            spec["layouts"] = copy.deepcopy(self.stored)
        else:
            spec.pop("layouts", None)


def taking_part(activity: dict) -> list:
    """The devices an activity uses, in the order its Devices page names them."""
    ids = [activity.get("display"), activity.get("volume"), activity.get("control"),
           *(activity.get("roles") or {}).values(),
           *(activity.get("power_on_devices") or ())]
    out = []
    for did in ids:
        if did is not None and did not in out:
            out.append(did)
    return out


def summary(activity: dict, devices: list, kind: str) -> tuple[str, bool]:
    """What the Activities tab says of a layout: ("Receiver (default) - 3 keys", True),
    or ("none - no display in this activity", False) when there is none."""
    layout = activity_layouts.resolve(activity, devices, kinds=(kind,)).get(kind)
    changed = kind in (activity.get("layouts") or {})
    if layout is None:
        if changed:
            return "none", False
        return ("none - no display in this activity" if kind == "picture"
                else "none - no volume device in this activity"), False
    names = {d.get("id"): d.get("label") or str(d.get("id")) for d in devices}
    keys = len(layout["hard_macros"])
    buttons = len([b for b in layout["soft_buttons"] if b is not None])
    parts = [f"{names.get(layout['device'], layout['device'])} "
             + ("(changed)" if changed else "(default)"),
             f"{keys} key" + ("s" if keys != 1 else "")]
    if buttons:
        parts.append(f"{buttons} button" + ("s" if buttons != 1 else ""))
    return " - ".join(parts), True


def _key_name(key: str) -> str:
    """VolumeUp -> Volume Up, as a person says the key."""
    return re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", key)


def details(activity: dict, devices: list, kind: str) -> str:
    """The row's tooltip: the keys the layout takes over and the buttons it shows, which
    its counts stand for."""
    layout = activity_layouts.resolve(activity, devices, kinds=(kind,)).get(kind)
    title = activity_layouts.TITLES[kind]
    if layout is None:
        return f"{title} does nothing in this activity."
    keys = sorted(layout["hard_macros"], key=lambda k: (k not in activity_layouts.VOLUME_KEYS,
                                                        k))
    out = [f"After {title} is pressed, it takes over: "
           + (", ".join(_key_name(k) for k in keys) if keys else "no keys")]
    buttons = [b for b in layout["soft_buttons"] if b is not None]
    if buttons:
        names = [(b.get("label") if isinstance(b, dict) else b[0]) or "?" for b in buttons]
        out.append("and shows on the screen: " + ", ".join(names))
    return "\n".join(out)


# What each layout takes over by default, as Logitech's software chose.
DEFAULT_KEYS = {
    "sound": "Volume up, Volume down and Mute - and the menu keys (the arrows, OK, Menu "
             "and Exit) too when the same device also shows the picture, as a TV playing "
             "its own sound does",
    "picture": "the arrows, OK, Exit, Info and Guide",
}


class _DevicePage(QWizardPage):
    """Which device the layout is for, or none; Default for Logitech's choice."""

    def __init__(self, title: str, activity_label: str, parent=None):
        super().__init__(parent)
        self.setTitle("Device")
        self.setSubTitle(
            f"Pressing {title} in {activity_label} turns some keys and the screen over "
            f"to one device until {title} is pressed again. By default it is the "
            + ("activity's volume device." if title == "Sound" else
               "activity's display; an activity with none has no Picture layout.")
            + f" It takes over {DEFAULT_KEYS[title.lower()]}, where the device has "
              f"commands for them; every other key does what it does in the activity.")
        form = QFormLayout(self)
        row = QHBoxLayout()
        self.device = QComboBox()
        self.device.setMinimumContentsLength(20)
        row.addWidget(self.device)
        self.reset = QPushButton("Default")
        self.reset.setToolTip(f"The {title} layout as Logitech's software gave it: the "
                              f"activity's own device, its keys and its buttons")
        row.addWidget(self.reset)
        row.addStretch()
        form.addRow("Device:", row)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray;")
        form.addRow("", self.note)


class LayoutDialog(SectionDialog):
    """One layout of one activity, as the activity editor looks: its device, the keys it
    takes over and its screen buttons, each a section."""

    def __init__(self, activity: dict, devices: list, kind: str, remote=None,
                 parent=None):
        self.kind = kind
        self.title = activity_layouts.TITLES[kind]
        self.activity_label = activity.get("label") or "Activity"
        super().__init__(f"{self.activity_label} - {self.title}", parent)
        from .activity_buttons import ScreenButtonsPage
        from .activity_wizard import ActivityHardButtonsPage
        self.devices = list(devices or [])
        self.ours = taking_part(activity)
        self.layouts = Layouts(self.devices, activity, self)

        self.device_page = _DevicePage(self.title, self.activity_label)
        self.device = self.device_page.device
        self.reset = self.device_page.reset
        self.note = self.device_page.note
        self.device.activated.connect(self._device_chosen)
        self.reset.clicked.connect(lambda: self.layouts.reset(kind))
        self.keys = ActivityHardButtonsPage(self.devices, activity, remote=remote,
                                            layout=(self.layouts, kind))
        self.buttons = ScreenButtonsPage(self.devices, activity, remote=remote,
                                         layout=(self.layouts, kind))
        self.buttons.set_participating(self.ours)
        self.add_section("device", "Device", self.device_page)
        self.add_section("keys", "Keys", self.keys)
        self.add_section("buttons", "Screen buttons", self.buttons)

        self.layouts.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        """The device list and Default as the layout is now."""
        layout = self.layouts.layout(self.kind)
        current = layout["device"] if layout else None
        default = self.layouts.default_device(self.kind)
        names = {d.get("id"): d.get("label") or str(d.get("id")) for d in self.devices}
        self.device.blockSignals(True)
        self.device.clear()
        self.device.addItem(f"No {self.title} layout", None)
        for did in self.ours:
            if did in names:
                self.device.addItem(names[did] + ("  (default)" if did == default else ""),
                                    did)
        others = [did for did in names if did not in self.ours]
        if others:
            self.device.insertSeparator(self.device.count())
            self.device.addItem("Not in this activity:", "-")
            model = self.device.model()
            if isinstance(model, QStandardItemModel):
                model.item(self.device.count() - 1).setEnabled(False)
            for did in others:
                self.device.addItem(names[did], did)
        self.device.setCurrentIndex(max(0, self.device.findData(current)))
        self.device.blockSignals(False)
        self.reset.setEnabled(self.layouts.changed_from_default(self.kind))
        if current is not None and current not in self.ours:
            self.note.setText(f"{self.activity_label} does not turn "
                              f"{names.get(current, current)} on; {self.title} only "
                              f"sends to it.")
        elif current is None:
            self.note.setText(f"{self.title} does nothing in this activity. Choose a "
                              f"device to give it a layout.")
        else:
            self.note.setText("")
        self.note.setVisible(bool(self.note.text()))

    def _device_chosen(self, index):
        chosen = self.device.itemData(index)
        if chosen == "-":
            self.refresh()
            return
        self.layouts.set_device(self.kind, chosen)

    def apply(self, activity: dict) -> None:
        """Write the layouts into the activity."""
        self.layouts.apply(activity)
