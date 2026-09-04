"""Add and edit an activity: devices, inputs and key mapping."""

import copy

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem,
    QSplitter, QAbstractItemView, QHeaderView, QWizard, QWizardPage
)
from PyQt6.QtCore import Qt, QSize

from .macro import MacroEditorWidget, StartupEditor
from .project import (drop_retired_fields)
from .activity_buttons import FavouritesPage, ScreenButtonsPage
from .ui_helpers import (FilterCombo)

from .constants import ACTIVITY_TYPES
from .icons import icon as type_icon
from .properties_editor import PropertiesEditor, PropertiesPage
from .widgets import _new_act_id


class ActivityWizard(QWizard):
    def __init__(self, devices, parent=None, existing=None, taken_ids=None):
        super().__init__(parent)
        self._taken_ids = list(taken_ids or [])
        self.setWindowTitle("Add Activity" if not existing else "Edit Activity")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(580, 400)
        self.devices = devices
        self.result_spec = None
        e = self._existing = existing or {}

        self.addPage(ActivityIdentityPage(e))
        self.addPage(ActivityRolesPage(devices, e))
        self.addPage(FavouritesPage(devices, e))
        self.addPage(ScreenButtonsPage(devices, e))
        self.addPage(ActivityHardButtonsPage(devices, e))
        self.addPage(ActivityMacrosPage(devices, e))
        self.addPage(PropertiesPage("activity", e.get("properties"),
                                    kind=e.get("type")))

    def initializePage(self, page_id):
        """Before a page is shown, tell it which devices this activity uses.

        Roles are chosen on page two, so everything after it can put those devices
        first - the ones the activity is actually built around.
        """
        super().initializePage(page_id)
        page = self.page(page_id)
        setter = getattr(page, "set_participating", None)
        if setter:
            setter(self._participating())

    def _participating(self):
        roles = self.page(self.pageIds()[1])
        ids = [roles.disp_combo.currentData(), roles.vol_combo.currentData(),
               roles.ctrl_combo.currentData()]
        ids += list((roles.get_roles() or {}).values())
        return [i for i in dict.fromkeys(ids) if i]

    def accept(self):
        self.result_spec = self._collect()
        super().accept()

    def _collect(self):
        ids = self.pageIds()
        p0, p1, p3, p4, p5, p6, p7 = (self.page(i) for i in ids[:7])
        # Everything the activity already said, including the parts no page here shows.
        spec = _carry_activity(self._existing)
        spec.update({
            "id":      p0.id_edit.text().strip() or _new_act_id(self._taken_ids),
            "label":   p0.label_edit.text().strip() or "New Activity",
            "type":    p0.type_combo.currentData(),
            "display": p1.disp_combo.currentData(),
            "control": p1.ctrl_combo.currentData(),
        })
        vol = p1.vol_combo.currentData()
        if vol and vol != spec["display"]:
            spec["volume"] = vol
        spec["roles"] = p1.get_roles()
        spec["image_buttons"] = p3.get_buttons()
        confirm = p3.get_confirm()
        if confirm:
            spec["channel_confirm"] = confirm
        # The touchscreen buttons. These had no page at all, so an activity could not
        # be given one through the interface - the thing the manual asked for most.
        spec["soft_buttons"]  = p4.get_buttons()
        spec["hard_macros"]   = p5.get_hard_macros()
        spec["enter"] = p6.enter_macro.get_macro()
        spec["leave"] = p6.leave_macro.get_macro()
        spec["properties"] = p7.values()
        self._assets = p3.get_assets()
        return spec


class ActivityIdentityPage(QWizardPage):
    def __init__(self, existing, parent=None):
        super().__init__(parent)
        self.setTitle("Activity Name & Icon")
        self.setSubTitle("Give the activity a name and choose the icon that will "
                         "appear on the remote's screen.")
        layout = QFormLayout(self)

        self.label_edit = QLineEdit(existing.get("label",""))
        layout.addRow("Activity name:", self.label_edit)

        self.type_combo = QComboBox()
        self.type_combo.setIconSize(QSize(20, 20))
        types = list(ACTIVITY_TYPES)
        current = (existing.get("type") or "").strip()
        if current and current not in {t for _l, t in types}:
            types.insert(0, (f"{current} (from the imported config)", current))
        for label, atype in types:
            self.type_combo.addItem(type_icon(atype, 20), label, atype)
        if existing.get("type"):
            for i in range(self.type_combo.count()):
                if self.type_combo.itemData(i) == existing["type"]:
                    self.type_combo.setCurrentIndex(i); break
        layout.addRow("Activity type (icon):", self.type_combo)

        self.id_edit = QLineEdit(existing.get("id", ""))
        self.id_edit.setReadOnly(True)
        self.id_edit.setPlaceholderText("assigned automatically")
        self.id_edit.setStyleSheet("color: gray;")
        # Internal identity: activities and devices reference each other by id, and
        # editing one silently breaks every reference to it. Shown, never editable.
        layout.addRow("Activity ID:", self.id_edit)

# Which device types plausibly fill which role. A hint for ordering the lists, not a
# restriction: every device stays selectable, because somebody's setup will not match.
DISPLAY_TYPES = {"Television", "Projector", "Monitor", "TvDvd", "TvDvdVcr", "TvVcr",
                 "TvHdd", "MediaCenterPC", "Laptop", "Computer"}
VOLUME_TYPES = {"Receiver", "Amplifier", "AudioVideoSwitch", "Television", "Projector",
                "CdRadioCassette", "DvdVcrReceiver", "MediaCenterPC", "Monitor"}
# Anything that is not purely an output is a plausible thing to drive with the
# transport and channel keys.
NOT_CONTROL_TYPES = {"Light", "HomeAppliance", "ClimateControl", "Amplifier",
                     "AudioVideoSwitch"}


def suits_display(device) -> bool:
    return device.get("type") in DISPLAY_TYPES


def suits_volume(device) -> bool:
    return device.get("type") in VOLUME_TYPES


def suits_control(device) -> bool:
    return device.get("type") not in NOT_CONTROL_TYPES


class ActivityRolesPage(QWizardPage):
    def __init__(self, devices, existing, parent=None):
        super().__init__(parent)
        self.setTitle("Device Roles")
        self.setSubTitle("Which device is the screen (Display)? "
                         "Which one handles channel/transport buttons (Control)?")
        layout = QFormLayout(self)
        dev_ids = [d["id"] for d in devices]

        def make_combo(field, suits):
            """Devices that can plausibly fill this role first, the rest after.

            Nothing is hidden - an unusual setup is still a setup, and the type of a
            device is a hint rather than a rule. But offering a set of blinds as the
            screen with no distinction is how a role gets filled by whatever happened
            to be first in the list.
            """
            combo = FilterCombo()
            combo.setEditable(False)
            likely = [d for d in devices if suits(d)]
            unlikely = [d for d in devices if not suits(d)]
            combo.set_items([(d.get("label", "?"), d["id"]) for d in likely + unlikely])
            # A real separator, so it cannot be chosen. The first version was an
            # ordinary entry carrying no device, which was selectable and would have
            # cleared the role.
            if likely and unlikely:
                combo.insertSeparator(len(likely))
            value = existing.get(field)
            if value in dev_ids:
                combo.select_data(value)
            return combo

        self.disp_combo = make_combo("display", suits_display)
        self.ctrl_combo = make_combo("control", suits_control)
        self.vol_combo  = make_combo("volume", suits_volume)

        layout.addRow("Display / Video output:", self.disp_combo)
        layout.addRow("Control (channels/transport):", self.ctrl_combo)
        layout.addRow("Volume (defaults to Display):", self.vol_combo)
        
        layout.addRow(QLabel(""))
        layout.addRow(QLabel("<b>Other devices this activity uses</b>"))
        explain = QLabel(
            "A device listed here is part of the activity: the remote powers it on "
            "and shows it among the activity's devices. A device that is only driven "
            "by a button still works, but will not appear in that list. "
            "PASSTHROUGH is the usual name for something in the signal chain, like an "
            "amplifier the sound passes through.")
        explain.setWordWrap(True)
        explain.setStyleSheet("color: gray;")
        layout.addRow(explain)

        self.extra_roles_layout = QVBoxLayout()
        self.extra_roles_rows = []

        def add_extra_role_row(r_name="", r_dev=None):
            row = QHBoxLayout()
            name_edit = QLineEdit(r_name)
            name_edit.setPlaceholderText("Role name")
            # Kept narrow: a role name is one short word, and letting it stretch
            # squeezed the device picker next to it down to nothing.
            name_edit.setMaximumWidth(170)
            dev_combo = FilterCombo()
            dev_combo.setEditable(False)
            # Rebuilt from `devices`, not from a pair of parallel lists that no longer
            # exist - this crashed the moment the button was pressed.
            dev_combo.set_items([("(none)", None)]
                                + [(d.get("label", "?"), d["id"]) for d in devices])
            if r_dev:
                dev_combo.select_data(r_dev)

            del_btn = QPushButton("x")
            del_btn.setFixedWidth(30)
            
            row.addWidget(name_edit)
            row.addWidget(dev_combo, 1)          # the picker gets the spare width
            row.addWidget(del_btn)
            
            row_widget = QWidget()
            row_widget.setLayout(row)
            self.extra_roles_layout.addWidget(row_widget)
            
            row_data = {"widget": row_widget, "name": name_edit, "dev": dev_combo}
            self.extra_roles_rows.append(row_data)
            
            del_btn.clicked.connect(lambda: self._remove_extra_role(row_data))
            
        extra_roles = existing.get("roles", {})
        for r_name, r_dev in extra_roles.items():
            add_extra_role_row(r_name, r_dev)
            
        self._add_extra_role_row = add_extra_role_row
        self.add_role_btn = QPushButton("+ Add another device")
        self.add_role_btn.clicked.connect(lambda: add_extra_role_row())
        # PASSTHROUGH is the only extra role any real configuration uses, so it gets a
        # button rather than making the user remember how to spell it.
        self.add_passthrough_btn = QPushButton("+ Passthrough device")
        self.add_passthrough_btn.setToolTip(
            "For something the signal passes through - an amplifier or a switch that "
            "must be on and listed with the activity, but is not its screen, volume "
            "or control.")
        self.add_passthrough_btn.clicked.connect(
            lambda: add_extra_role_row("PASSTHROUGH"))

        buttons = QHBoxLayout()
        buttons.addWidget(self.add_passthrough_btn)
        buttons.addWidget(self.add_role_btn)
        buttons.addStretch()

        layout.addRow(self.extra_roles_layout)
        layout.addRow(buttons)
        
    def _remove_extra_role(self, row_data):
        row_data["widget"].deleteLater()
        self.extra_roles_rows.remove(row_data)

    def get_roles(self):
        roles = {}
        for row in self.extra_roles_rows:
            name = row["name"].text().strip()
            dev = row["dev"].currentData()
            if name and dev:
                roles[name] = dev
        return roles
class HardButtonMacroDialog(QDialog):
    def __init__(self, devices, slot_name, existing_macro, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Macro for '{slot_name}' button")
        self.resize(500, 400)
        layout = QVBoxLayout(self)
        self.macro_edit = MacroEditorWidget(devices, existing_macro, self)
        layout.addWidget(self.macro_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
class ActivityHardButtonsPage(QWizardPage):
    def __init__(self, devices, existing, parent=None):
        super().__init__(parent)
        self.setTitle("Physical buttons")
        self.setSubTitle("Map device commands onto the remote's own buttons. Left "
                         "empty, they do whatever your chosen devices already do.")
        self.devices = devices
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Button", "Macro Steps"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        
        self.slots = ["Menu", "VolumeUp", "VolumeDown", "VolumeMute", "DirectionUp", "DirectionDown", 
                      "DirectionLeft", "DirectionRight", "Select", "Number1", "Number2", "Number3", 
                      "Number4", "Number5", "Number6", "Number7", "Number8", "Number9", "Number0"]
                      
        self.macros = existing.get("hard_macros", {})
        
        for slot in self.slots:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(slot))
            macro = self.macros.get(slot, [])
            self.table.setItem(r, 1, QTableWidgetItem(f"{len(macro)} steps" if macro else "Default"))
            
        self.table.itemDoubleClicked.connect(self._edit_macro)
        
        edit_btn = QPushButton("Edit Selected Button Macro")
        edit_btn.clicked.connect(self._edit_btn_clicked)
        clear_btn = QPushButton("Clear Override")
        clear_btn.clicked.connect(self._clear_btn_clicked)
        
        row = QHBoxLayout()
        row.addWidget(edit_btn)
        row.addWidget(clear_btn)
        layout.addLayout(row)

    def _edit_btn_clicked(self):
        r = self.table.currentRow()
        if r >= 0:
            self._edit_macro(self.table.item(r, 0))

    def _clear_btn_clicked(self):
        r = self.table.currentRow()
        if r >= 0:
            slot = self.table.item(r, 0).text()
            if slot in self.macros:
                del self.macros[slot]
            self.table.setItem(r, 1, QTableWidgetItem("Default"))

    def _edit_macro(self, item):
        r = item.row()
        slot = self.table.item(r, 0).text()
        dlg = HardButtonMacroDialog(self.devices, slot, self.macros.get(slot, []), self)
        if dlg.exec():
            macro = dlg.macro_edit.get_macro()
            if macro:
                self.macros[slot] = macro
                self.table.setItem(r, 1, QTableWidgetItem(f"{len(macro)} steps"))
            else:
                if slot in self.macros:
                    del self.macros[slot]
                self.table.setItem(r, 1, QTableWidgetItem("Default"))

    def get_hard_macros(self):
        return self.macros
class ActivityMacrosPage(QWizardPage):
    def __init__(self, devices, existing, parent=None):
        super().__init__(parent)
        self.setTitle("Startup & Shutdown Macros")
        self.setSubTitle(
            "What happens when this activity starts, and when it ends. Simple is a\n"
            "list of inputs to switch; Advanced adds commands, waits and channels.")
        
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        enter_w = QWidget()
        el = QVBoxLayout(enter_w)
        el.addWidget(QLabel("<b>On Activity Start:</b>"))
        # The whole startup sequence, in order, including the input switches. They used
        # to be hidden here and edited on a page of their own, which is why an activity
        # whose only startup step was a switch showed an empty box and looked wiped.
        #
        # `input` is the older spelling of "one more switch, always last" - the builder
        # appends it after everything in `enter` - so a project saved before this change
        # is read by putting it back where the builder would have put it.
        enter = list(existing.get("enter") or [])
        pair = existing.get("input")
        if pair:
            enter.append(["input", pair[0], pair[1]])
        self.enter_macro = StartupEditor(devices, enter)
        el.addWidget(self.enter_macro)
        splitter.addWidget(enter_w)
        
        leave_w = QWidget()
        ll = QVBoxLayout(leave_w)
        ll.addWidget(QLabel("<b>On Activity Leave:</b>"))
        self.leave_macro = StartupEditor(devices, existing.get("leave", []))
        ll.addWidget(self.leave_macro)
        splitter.addWidget(leave_w)

        layout.addWidget(splitter)

    def set_participating(self, ids):
        """Both macro editors offer this activity's own devices first."""
        for editor in (self.enter_macro, self.leave_macro):
            editor.set_participating(ids)


# Keys the activity editors rewrite from scratch every time, which have to be cleared
# before the old spec is carried forward or a stale one contradicts what the pages show.
#
# The first three are written only when there is something to say: drop the last input
# switch, or the confirm key, and an old value left underneath would quietly come back.
#
# `channels` is different - the favourites page loads `channels` and `image_buttons`
# into one table and returns them all as `image_buttons`, while the builder *appends*
# `channels` onto `image_buttons`. Carrying it would show every favourite twice.
_ACTIVITY_REWRITTEN = ("volume", "input", "channel_confirm", "channels")


def _carry_activity(base: dict) -> dict:
    """The starting point for an activity spec: everything it already said.

    The same rule as the device editors, and it was broken here in the same way. What
    was being lost is the power plan - `power_on_devices` and `power_off_devices`, the
    ordered lists of what an activity switches on and off. When they are absent the
    builder falls back to the three role devices, so an activity imported from a real
    configuration that also woke a subwoofer or a power conditioner quietly stopped
    doing so the first time anybody edited its name.
    """
    spec = copy.deepcopy(base or {})
    for key in _ACTIVITY_REWRITTEN:
        spec.pop(key, None)
    # Carrying everything forward must not resurrect a field that has been retired: a
    # project written by an older version still has them, and "carry what you do not
    # understand" is the right default only for fields nobody has decided about.
    return drop_retired_fields({"activities": [spec]})["activities"][0]


class ActivityEditor(QDialog):
    def __init__(self, devices, parent=None, existing=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Activity")
        self.resize(660, 600)
        self.result_spec  = None
        e = self._existing = existing or {}
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self.p0 = ActivityIdentityPage(e)
        self.p1 = ActivityRolesPage(devices, e)
        self.p3 = FavouritesPage(devices, e)
        self.p3b = ScreenButtonsPage(devices, e)
        self.p4 = ActivityHardButtonsPage(devices, e)
        self.p5 = ActivityMacrosPage(devices, e)

        self.tabs.addTab(self.p0, "Identity")
        self.tabs.addTab(self.p1, "Roles")
        self.tabs.addTab(self.p3, "Favourites")
        self.tabs.addTab(self.p3b, "Commands")
        self.tabs.addTab(self.p4, "Physical buttons")
        self.tabs.addTab(self.p5, "Startup / Shutdown")
        self.p6 = PropertiesEditor("activity", (existing or {}).get("properties"),
                                   kind=(existing or {}).get("type"))
        self.tabs.addTab(self.p6, "Advanced")
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.tabs.currentChanged.connect(self._share_participation)
        self._share_participation()

    def _participating(self):
        ids = [self.p1.disp_combo.currentData(), self.p1.vol_combo.currentData(),
               self.p1.ctrl_combo.currentData()]
        ids += list((self.p1.get_roles() or {}).values())
        return [i for i in dict.fromkeys(ids) if i]

    def _share_participation(self, *_):
        """Tell every tab which devices this activity uses, so they list those first."""
        taking_part = self._participating()
        for tab in (self.p3, self.p3b, self.p4, self.p5):
            setter = getattr(tab, "set_participating", None)
            if setter:
                setter(taking_part)

    def accept(self):
        self.result_spec = self._collect()
        super().accept()

    def _collect(self):
        p0, p1, p3 = self.p0, self.p1, self.p3
        screen, p4, p5, p6 = self.p3b, self.p4, self.p5, self.p6
        # As above: editing an activity must not cost it what this dialog cannot show.
        spec = _carry_activity(self._existing)
        spec.update({
            "id":      p0.id_edit.text().strip(),
            "label":   p0.label_edit.text().strip() or "New Activity",
            "type":    p0.type_combo.currentData(),
            "display": p1.disp_combo.currentData(),
            "volume":  p1.vol_combo.currentData(),
            "control": p1.ctrl_combo.currentData(),
            "roles":   p1.get_roles(),
        })
        spec["image_buttons"] = p3.get_buttons()
        confirm = p3.get_confirm()
        if confirm:
            spec["channel_confirm"] = confirm
        # The touchscreen buttons. These had no page at all, so an activity could not
        # be given one through the interface - the thing the manual asked for most.
        spec["soft_buttons"]  = screen.get_buttons()
        spec["hard_macros"]   = p4.get_hard_macros()
        spec["enter"] = p5.enter_macro.get_macro()
        spec["leave"] = p5.leave_macro.get_macro()
        spec["properties"] = p6.values()
        self._assets = p3.get_assets()
        return spec
