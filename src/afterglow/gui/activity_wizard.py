"""Add and edit an activity: devices, inputs and key mapping."""

import copy

from ..qt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem,
    QSplitter, QAbstractItemView, QHeaderView, QWizardPage
)
from ..qt.QtCore import Qt, QSize, pyqtSignal

from .macro import MacroEditorWidget, StartupEditor
from .project import (drop_retired_fields)
from .activity_buttons import FavouritesPage, ScreenButtonsPage
from .ui_helpers import (FilterCombo)

from .. import project_devices, vocabulary
from .symbols import icon as symbol
from .icons import icon as type_icon
from .activity_power import ActivityPowerPage, apply_plan
from .properties_editor import PropertiesEditor, PropertiesPage
from .keys_view import ASSIGNED, CHANGED, FREE, KeysViewChoice, RemoteKeys, legend
from .sections import SectionDialog, StepWizard
from .widgets import _new_act_id


DEFAULT_KEY = "Default"


def _does(macro, devices) -> str:
    """What a key does, as the Physical buttons page lists it. A key that sends one
    command says which - it is an ordinary assignment, and calling it a one-step macro
    left people asking what a step was."""
    if not macro:
        return DEFAULT_KEY
    names = {str(d["id"]): d.get("label", "?") for d in devices or []}
    if len(macro) == 1 and macro[0][0] == "command" and len(macro[0]) >= 3:
        step = macro[0]
        held = f"  (held {step[4]} ms)" if len(step) > 4 and step[4] else ""
        return f"{names.get(str(step[1]), step[1])} - {step[2]}{held}"
    return f"{len(macro)} steps"


def screen_page(devices, existing, profile):
    """The page for an activity's screen buttons: its tabs, on a remote whose activity
    screen is a set of them (the 1100), or its one page of buttons."""
    if getattr(profile, "activity_screens", None):
        from .activity_screens import ActivityTabsPage
        return ActivityTabsPage(devices, existing, remote=profile)
    return ScreenButtonsPage(devices, existing, remote=profile)


# "Custom / Other": what an activity without a type is shown as.
GENERIC_TYPE = "VirtualGeneric"


class ActivityWizard(StepWizard):
    def __init__(self, devices, parent=None, existing=None, taken_ids=None, remote=None,
                 activities=None):
        super().__init__("Add Activity" if not existing else "Edit Activity", parent)
        profile = vocabulary.for_remote(remote)
        self._taken_ids = list(taken_ids or [])
        self.devices = devices
        self.result_spec = None
        # the editor's own copy: no page edits the project's activity in place, so Cancel
        # leaves it as it was (the physical buttons' page once changed it directly)
        e = self._existing = copy.deepcopy(existing or {})

        self.identity = ActivityIdentityPage(
            e, remote=profile, holders=button_holders(activities, existing))
        self.roles = ActivityRolesPage(devices, e)
        self.favourites = FavouritesPage(devices, e, remote=profile)
        self.screen_buttons = screen_page(devices, e, profile)
        self.hard_buttons = ActivityHardButtonsPage(devices, e, remote=profile)
        self.startup = ActivityMacrosPage(devices, e)
        self.power_page = ActivityPowerPage(devices, e)
        self.advanced = PropertiesPage("activity", e.get("properties"),
                                       kind=e.get("type"), remote=profile)
        # Naming it, its devices and their inputs - of the pages this remote's profile
        # lists - and nothing more: the keys follow the devices, power follows them too,
        # and buttons and favourites are for Edit once the activity works. The other
        # pages are still built, from the activity as it is, so collecting from them
        # hands back what was there.
        pages = {"identity": ("Name it", self.identity), "roles": ("Its devices", self.roles),
                 "startup": ("Inputs", self.startup)}
        for name in profile.activity_pages:
            if name in pages:
                self.add_step(*pages[name])
        # What happens when the activity ends is for Edit: a new one needs its inputs.
        self.startup.for_adding()
        link_activity_key(self.identity, self.hard_buttons)
        link_favourites_button(self.favourites, self.screen_buttons, profile)

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
        main = getattr(page, "set_main_device", None)
        if main:
            main(self.roles.ctrl_combo.currentData())
        if page is self.hard_buttons:
            roles = self.roles
            page.set_roles(roles.disp_combo.currentData(), roles.vol_combo.currentData(),
                           roles.ctrl_combo.currentData())

    def _participating(self):
        roles = self.roles
        ids = [roles.disp_combo.currentData(), roles.vol_combo.currentData(),
               roles.ctrl_combo.currentData()]
        ids += list((roles.get_roles() or {}).values())
        return [i for i in dict.fromkeys(ids) if i]

    def accept(self):
        self.result_spec = self._collect()
        super().accept()

    def _collect(self):
        p0, p1, p3, p4 = self.identity, self.roles, self.favourites, self.screen_buttons
        # a remote whose favourites are one of its activity screens edits them there
        if getattr(p4, "favourites", None) is not None:
            p3 = p4.favourites
        p5, p6, p7 = self.hard_buttons, self.startup, self.advanced
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
        apply_button(spec, p0)
        spec["image_buttons"] = p3.get_buttons()
        confirm = p3.get_confirm()
        if confirm:
            spec["channel_confirm"] = confirm
        # The touchscreen buttons. These had no page at all, so an activity could not
        # be given one through the interface - the thing the manual asked for most.
        spec["hard_macros"]   = p5.get_hard_macros()
        spec["enter"] = p6.enter_macro.get_macro()
        spec["leave"] = p6.leave_macro.get_macro()
        spec["properties"] = p7.values()
        # after the properties: an activity's tabs are switched on by properties of it
        p4.apply(spec)
        apply_plan(spec, self.power_page.get_plan(), self.power_page.leave())
        self._assets = p3.get_assets()
        return spec


def _listed(names: list[str]) -> str:
    """'A, B or C'."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def link_activity_key(identity: "ActivityIdentityPage",
                      buttons: "ActivityHardButtonsPage") -> None:
    """The identity page's Button and the activity key lit in the physical buttons'
    picture are one choice: changing either changes the other."""
    combo = identity.button_combo
    if combo is None:
        return
    buttons.holders = identity.holders
    buttons.show_activity_key(combo.currentData())
    combo.currentIndexChanged.connect(lambda _i: buttons.show_activity_key(combo.currentData()))
    buttons.activity_key_chosen.connect(
        lambda value: combo.setCurrentIndex(max(combo.findData(value), 0)))


def link_favourites_button(favourites, screen, profile) -> None:
    """On a remote whose activity screen opens its favourites with a button of its own,
    the screen page draws that button while the favourites page lists any."""
    label = getattr(profile, "favourites_button", None)
    if not label or not hasattr(screen, "follow_favourites"):
        return
    screen.follow_favourites(favourites.table.model(), label)


def button_holders(activities, editing=None) -> dict:
    """{activity key: label} of the activities other than ``editing`` that have one."""
    return {act["activity_button"]: act.get("label") or "another activity"
            for act in activities or []
            if act is not editing and act.get("activity_button")}


def apply_button(spec: dict, page: "ActivityIdentityPage") -> None:
    """The key the identity page chose for the activity, on a remote that has them."""
    if page.button_combo is None:
        return
    chosen = page.button_combo.currentData()
    if chosen:
        spec["activity_button"] = chosen
    else:
        spec.pop("activity_button", None)


def one_activity_a_button(activities: list, spec: dict) -> None:
    """The key ``spec`` took is no other activity's any more."""
    chosen = spec.get("activity_button")
    if chosen:
        for other in activities:
            if other is not spec and other.get("activity_button") == chosen:
                other.pop("activity_button", None)


class ActivityIdentityPage(QWizardPage):
    def __init__(self, existing, parent=None, remote=None, holders=None):
        super().__init__(parent)
        # {activity key: the label of the other activity it starts now}
        self.holders = dict(holders or {})
        self.setTitle("Activity")
        typed = bool(list(vocabulary.activity_types(remote)))
        # A remote with no activity types (a 5xx) draws no icon and has no type to choose.
        self.setSubTitle("The name the remote shows for this activity"
                         + (", and its icon." if typed else "."))
        layout = QFormLayout(self)

        self.label_edit = QLineEdit(existing.get("label",""))
        self.label_edit.setPlaceholderText("e.g. Watch TV")
        layout.addRow("Name:", self.label_edit)

        self.type_combo = QComboBox()
        self.type_combo.setIconSize(QSize(20, 20))
        types = list(vocabulary.activity_types(remote))
        current = (existing.get("type") or "").strip()
        if current and current not in {t for _l, t in types}:
            types.insert(0, (f"{current} (from the imported config)", current))
        for label, atype in types:
            self.type_combo.addItem(type_icon(atype, 20, vocabulary.for_remote(remote)),
                                    label, atype)
        # An activity without a type opens as "Custom / Other", never as whatever the
        # list happens to start with - saving it for any other reason would set that.
        wanted = existing.get("type") or GENERIC_TYPE
        for i in range(self.type_combo.count()):
            if self.type_combo.itemData(i) == wanted:
                self.type_combo.setCurrentIndex(i); break
        layout.addRow("Type:", self.type_combo)
        # kept, not shown: an activity's own type stays in the combo and is saved as it was
        layout.setRowVisible(self.type_combo, typed)

        # The key that starts it, on a remote with Watch TV, Watch a Movie and Listen to
        # Music (the 650 and 700): as MyHarmony's "Customize Activity Buttons", one
        # activity a key - choosing one another activity has moves it here
        self.button_combo = None
        buttons = vocabulary.for_remote(remote).activity_buttons
        if buttons:
            self.button_combo = QComboBox()
            self.button_combo.addItem("None", None)
            for label, value in buttons:
                holder = self.holders.get(value)
                self.button_combo.addItem(
                    f'{label} (now starts "{holder}")' if holder else label, value)
            chosen = existing.get("activity_button")
            if not existing.get("id") and "activity_button" not in existing:
                # a new activity takes the first key no activity has, as the remote's own
                # setup did; said here, so the key is never bound without the editor showing it
                chosen = next((value for _label, value in buttons
                               if value not in self.holders), None)
            at = self.button_combo.findData(chosen)
            self.button_combo.setCurrentIndex(max(at, 0))
            self.button_combo.setToolTip(
                "The button above the screen that starts this activity. Each button "
                "starts one activity; choosing one another activity uses moves it here.")
            layout.addRow("Button:", self.button_combo)
            # a key another activity has can still be chosen: saving takes it from that one
            self.button_warning = QLabel()
            self.button_warning.setWordWrap(True)
            self.button_warning.setStyleSheet("color: #b35c00;")
            layout.addRow("", self.button_warning)
            self.button_combo.currentIndexChanged.connect(self._warn_button)
            self._warn_button()

        self.id_edit = QLineEdit(existing.get("id", ""))
        self.id_edit.setReadOnly(True)
        self.id_edit.setPlaceholderText("assigned automatically")
        self.id_edit.setStyleSheet("color: gray;")
        # Internal identity: activities and devices reference each other by id, and
        # editing one silently breaks every reference to it. Shown, never editable.
        layout.addRow("Activity ID:", self.id_edit)
        layout.setRowVisible(self.id_edit, False)    # nobody needs to see it

    def _warn_button(self, *_args):
        """Say so when the chosen key starts another activity now."""
        value = self.button_combo.currentData()
        holder = self.holders.get(value)
        label = self.button_combo.currentText().split(" (now starts")[0]
        self.button_warning.setText(
            f'{label} starts "{holder}" now. Saving moves it to this '
            f'activity, and "{holder}" will have no button.' if holder else "")
        self.button_warning.setVisible(bool(holder))


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
        self.setTitle("Devices")
        self.setSubTitle("Which device shows the picture, which one the volume keys "
                         "turn, and which one the play, channel and menu keys drive. "
                         "These decide what the remote's keys do in this activity.")
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
            # "(none)" first: an activity need not have every role - Logitech's own
            # configurations leave Display out of a radio activity, and one has only
            # passthrough devices. Without it the first device was shown instead, and
            # saving the editor quietly gave the activity that device as its screen.
            combo.set_items([("(none)", None)]
                            + [(d.get("label", "?"), d["id"]) for d in likely + unlikely])
            # A real separator, so it cannot be chosen. The first version was an
            # ordinary entry carrying no device, which was selectable and would have
            # cleared the role.
            if likely and unlikely:
                combo.insertSeparator(1 + len(likely))
            value = existing.get(field)
            combo.select_data(value if value in dev_ids else None)
            return combo

        self.disp_combo = make_combo("display", suits_display)
        self.ctrl_combo = make_combo("control", suits_control)
        self.vol_combo  = make_combo("volume", suits_volume)

        layout.addRow("You watch on:", self.disp_combo)
        layout.addRow("Volume goes to:", self.vol_combo)
        layout.addRow("Play, channels and menus go to:", self.ctrl_combo)
        self.vol_combo.setToolTip("Left at (none), the volume keys go to the device "
                                  "you watch on.")
        
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

            del_btn = QPushButton(symbol("delete"), "")
            del_btn.setToolTip("Take this device out of the activity")
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
        self.add_role_btn = QPushButton(symbol("add"), "Add another device")
        self.add_role_btn.clicked.connect(lambda: add_extra_role_row())
        # PASSTHROUGH is the only extra role any real configuration uses, so it gets a
        # button rather than making the user remember how to spell it.
        self.add_passthrough_btn = QPushButton(symbol("add"), "Passthrough device")
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
        self.setWindowTitle(f"What '{slot_name}' does")
        self.resize(500, 400)
        layout = QVBoxLayout(self)
        self.macro_edit = MacroEditorWidget(devices, existing_macro, self)
        layout.addWidget(self.macro_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
class ActivityHardButtonsPage(QWizardPage):
    # the activity key (a 650's "TV", "Movie", "Music") clicked in the picture, or None
    # when the one it had is clicked again; the identity page's Button follows it
    activity_key_chosen = pyqtSignal(object)

    def __init__(self, devices, existing, parent=None, remote=None):
        super().__init__(parent)
        self.setTitle("Physical buttons")
        self.setSubTitle("A key left at Default does what the activity's devices "
                         "suggest: volume and mute go to the volume device, the rest "
                         "to the one that plays and changes channels. Give a key "
                         "something else to do only when that is wrong.")
        self.devices = devices
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addStretch()
        self.view_choice = KeysViewChoice()
        top.addWidget(self.view_choice)
        layout.addLayout(top)

        # The picture: the remote, the keys this activity changes tinted, and those
        # keys listed beside it.
        self.picture = QWidget()
        picture = QHBoxLayout(self.picture)
        picture.setContentsMargins(0, 0, 0, 0)
        self.keys_view = RemoteKeys(remote)
        self.keys_view.key_clicked.connect(self._edit_slot)
        # the keys that start an activity, by the label the picture knows them by
        self._activity_keys = dict(vocabulary.for_remote(remote).activity_buttons)
        self._activity_key = None
        self.keys_view.fixed_clicked.connect(self._activity_key_clicked)
        picture.addWidget(self.keys_view, 3)
        side = QVBoxLayout()
        side.addWidget(QLabel("<b>Changed in this activity</b>"))
        self.changed_list = QListWidget()
        self.changed_list.itemDoubleClicked.connect(
            lambda item: self._edit_slot(item.data(Qt.ItemDataRole.UserRole)))
        side.addWidget(self.changed_list, 1)
        back = QPushButton("Back to default")
        back.clicked.connect(self._reset_listed)
        side.addWidget(back)
        hint = QLabel("Click a key to change what it does. Hover over a key to see "
                      "what it sends."
                      + (" Click " + _listed(list(self._activity_keys)) + " to start "
                         "this activity with it." if self._activity_keys else ""))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        side.addWidget(hint)
        side.addWidget(legend([(CHANGED, "Its own action"), (FREE, "Default")]
                              + ([(ASSIGNED, "Starts this activity")]
                                 if self._activity_keys else [])))
        picture.addLayout(side, 2)
        layout.addWidget(self.picture, 1)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Button", "Does"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        
        # Every physical key this remote has, from its profile. This was a fixed list of
        # nineteen, so Guide, Info, the transport keys and the rest could not be given an
        # activity's own action at all (GitHub #5). A key an imported activity already
        # binds is kept even if the profile does not name it, so editing cannot drop it.
        self.macros = existing.get("hard_macros", {})
        # what a key left at Default sends, from the activity's devices (set_roles)
        self.defaults = project_devices.default_keys(
            devices, display=existing.get("display"), volume=existing.get("volume"),
            control=existing.get("control"))
        self.slots = list(vocabulary.hard_keys(remote))
        self.slots += [key for key in self.macros if key not in self.slots]
        # As they sit on the remote, top to bottom, when it has been drawn.
        drawn = self.keys_view.keys()
        self.slots.sort(key=lambda k: drawn.index(k) if k in drawn else len(drawn))
        
        for slot in self.slots:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, self._key_item(slot))
            self.table.setItem(r, 1, QTableWidgetItem(self._says(slot)))
            
        self.table.itemDoubleClicked.connect(self._edit_macro)
        
        edit_btn = QPushButton("Change…")
        edit_btn.clicked.connect(self._edit_btn_clicked)
        clear_btn = QPushButton("Back to default")
        clear_btn.clicked.connect(self._clear_btn_clicked)
        
        self.table_buttons = QWidget()
        row = QHBoxLayout(self.table_buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit_btn)
        row.addWidget(clear_btn)
        row.addStretch()
        layout.addWidget(self.table_buttons)
        self.view_choice.changed.connect(self._show_picture)
        self._show_picture(self.view_choice.is_picture())

    def _key_item(self, slot):
        """A key's row: its name as people say it, its configuration name behind."""
        item = QTableWidgetItem(self.keys_view.label(slot))
        item.setData(Qt.ItemDataRole.UserRole, slot)
        return item

    def _slot(self, row):
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _default(self, slot) -> str:
        """What a key left at Default sends: the device and command the activity's
        devices route it to, or plain Default when they route it nowhere."""
        target = self.defaults.get(slot)
        if not target:
            return DEFAULT_KEY
        names = {str(d["id"]): d.get("label", "?") for d in self.devices or []}
        return f"{DEFAULT_KEY}: {names.get(target[0], target[0])} - {target[1]}"

    def _says(self, slot) -> str:
        macro = self.macros.get(slot)
        return _does(macro, self.devices) if macro else self._default(slot)

    def set_roles(self, display, volume, control):
        """The activity's devices, as its Devices page has them now: what each key left
        at Default sends follows them."""
        self.defaults = project_devices.default_keys(
            self.devices, display=display, volume=volume, control=control)
        for row, slot in enumerate(self.slots):
            self.table.setItem(row, 1, QTableWidgetItem(self._says(slot)))
        if self.picture.isVisible():
            self.refresh_picture()

    def _show_picture(self, picture):
        self.picture.setVisible(picture)
        self.table.setVisible(not picture)
        self.table_buttons.setVisible(not picture)
        if picture:
            self.refresh_picture()

    def refresh_picture(self):
        label = self.keys_view.label
        self.keys_view.set_states({
            key: ((CHANGED if self.macros.get(key) else FREE),
                  f"{label(key)}: " + self._says(key))
            for key in self.keys_view.keys()})
        self.changed_list.clear()
        for slot in self.slots:
            if self.macros.get(slot):
                item = QListWidgetItem(
                    f"{label(slot)}: {_does(self.macros[slot], self.devices)}")
                item.setData(Qt.ItemDataRole.UserRole, slot)
                self.changed_list.addItem(item)

    def _row_of(self, slot):
        return self.slots.index(slot)

    def show_activity_key(self, value):
        """Light the activity key this activity is on (a profile value, or None)."""
        self._activity_key = value
        label = next((label for label, item in self._activity_keys.items()
                      if item == value), None)
        holders = getattr(self, "holders", {})

        def says(name):
            if name == label:
                holder = holders.get(value)
                return (f'{name}: starts this activity (saving takes it from '
                        f'"{holder}")' if holder else f"{name}: starts this activity")
            holder = holders.get(self._activity_keys[name])
            return (f'{name}: starts "{holder}" - click to move it to this activity'
                    if holder else f"{name}: click to start this activity with it")
        self.keys_view.set_choices({name: says(name) for name in self._activity_keys}, label)

    def _activity_key_clicked(self, label):
        value = self._activity_keys.get(label)
        chosen = None if value == self._activity_key else value
        self.show_activity_key(chosen)
        self.activity_key_chosen.emit(chosen)

    def _edit_slot(self, slot):
        """Change what a key does, from the picture."""
        if slot not in self.slots:              # a key the profile does not list
            self.slots.append(slot)
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, self._key_item(slot))
            self.table.setItem(r, 1, QTableWidgetItem(self._default(slot)))
        self.keys_view.select(slot)
        self._edit_macro(self.table.item(self._row_of(slot), 0))

    def _reset_listed(self):
        item = self.changed_list.currentItem()
        if item is None:
            return
        slot = item.data(Qt.ItemDataRole.UserRole)
        self.macros.pop(slot, None)
        self.table.setItem(self._row_of(slot), 1, QTableWidgetItem(self._default(slot)))
        self.refresh_picture()

    def _edit_btn_clicked(self):
        r = self.table.currentRow()
        if r >= 0:
            self._edit_macro(self.table.item(r, 0))

    def _clear_btn_clicked(self):
        r = self.table.currentRow()
        if r >= 0:
            slot = self._slot(r)
            if slot in self.macros:
                del self.macros[slot]
            self.table.setItem(r, 1, QTableWidgetItem(self._default(slot)))

    def _edit_macro(self, item):
        r = item.row()
        slot = self._slot(r)
        dlg = HardButtonMacroDialog(self.devices, self.keys_view.label(slot),
                                    self.macros.get(slot, []), self)
        if dlg.exec():
            macro = dlg.macro_edit.get_macro()
            if macro:
                self.macros[slot] = macro
                self.table.setItem(r, 1, QTableWidgetItem(_does(macro, self.devices)))
            else:
                if slot in self.macros:
                    del self.macros[slot]
                self.table.setItem(r, 1, QTableWidgetItem(self._default(slot)))
        self.refresh_picture()

    def get_hard_macros(self):
        return self.macros
class ActivityMacrosPage(QWizardPage):
    def __init__(self, devices, existing, parent=None):
        super().__init__(parent)
        self.setTitle("Inputs, startup and shutdown")
        self.setSubTitle(
            "Which input each device switches to when the activity starts - usually "
            "all it needs. Switch to Advanced to add commands, waits or a channel, "
            "or to do something when the activity ends.")
        
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
        
        leave_w = self.leave_box = QWidget()
        ll = QVBoxLayout(leave_w)
        ll.addWidget(QLabel("<b>On Activity Leave:</b>"))
        self.leave_macro = StartupEditor(devices, existing.get("leave", []))
        ll.addWidget(self.leave_macro)
        splitter.addWidget(leave_w)

        layout.addWidget(splitter)

    def for_adding(self):
        """Only the start: which input each device switches to."""
        self.leave_box.setVisible(False)
        self.setTitle("Inputs")
        self.setSubTitle("Which input each device switches to when the activity "
                         "starts. Commands, waits, a channel and what happens when it "
                         "ends can be added later with Edit.")

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


# The editor's sections, in the order they are listed, by the names a profile's
# `interface.activity_pages` uses; the last ones follow the devices unless changed.
ACTIVITY_SECTIONS = (
    ("identity", "Activity", False), ("roles", "Devices", False),
    ("startup", "Inputs & startup", False), ("screen_buttons", "Screen buttons", False),
    ("favourites", "Favourites", False), ("hard_buttons", "Physical buttons", True),
    ("power", "Power", True), ("advanced", "Advanced", True))


class ActivityEditor(SectionDialog):
    def __init__(self, devices, parent=None, existing=None, remote=None, activities=None):
        super().__init__("Edit Activity", parent)
        profile = vocabulary.for_remote(remote)
        self.result_spec  = None
        # the editor's own copy: no page edits the project's activity in place, so Cancel
        # leaves it as it was (the physical buttons' page once changed it directly)
        e = self._existing = copy.deepcopy(existing or {})

        self.p0 = ActivityIdentityPage(
            e, remote=profile, holders=button_holders(activities, existing))
        self.p1 = ActivityRolesPage(devices, e)
        self.p3 = FavouritesPage(devices, e, remote=profile)
        self.p3b = screen_page(devices, e, profile)
        self.p4 = ActivityHardButtonsPage(devices, e, remote=profile)
        self.p5 = ActivityMacrosPage(devices, e)

        self.power = ActivityPowerPage(devices, e)
        self.p6 = PropertiesEditor("activity", (existing or {}).get("properties"),
                                   kind=(existing or {}).get("type"), remote=profile)
        # Only the sections this remote's profile lists; see ActivityWizard.
        pages = {"identity": self.p0, "roles": self.p1, "favourites": self.p3,
                 "screen_buttons": self.p3b, "hard_buttons": self.p4,
                 "startup": self.p5, "power": self.power, "advanced": self.p6}
        for name, label, seldom in ACTIVITY_SECTIONS:
            if name in profile.activity_pages:
                self.add_section(name, label, pages[name], seldom=seldom)
        link_activity_key(self.p0, self.p4)
        link_favourites_button(self.p3, self.p3b, profile)
        self._share_participation()

    def section_shown(self, _name):
        self._share_participation()

    def _participating(self):
        ids = [self.p1.disp_combo.currentData(), self.p1.vol_combo.currentData(),
               self.p1.ctrl_combo.currentData()]
        ids += list((self.p1.get_roles() or {}).values())
        return [i for i in dict.fromkeys(ids) if i]

    def _share_participation(self, *_):
        """Tell every tab which devices this activity uses, so they list those first."""
        taking_part = self._participating()
        for tab in (self.p3, self.p3b, self.p4, self.p5, self.power):
            setter = getattr(tab, "set_participating", None)
            if setter:
                setter(taking_part)
        main = getattr(self.p3b, "set_main_device", None)
        if main:
            main(self.p1.ctrl_combo.currentData())
        self.p4.set_roles(self.p1.disp_combo.currentData(), self.p1.vol_combo.currentData(),
                          self.p1.ctrl_combo.currentData())

    def accept(self):
        self.result_spec = self._collect()
        super().accept()

    def _collect(self):
        p0, p1, p3 = self.p0, self.p1, self.p3
        screen, p4, p5, p6 = self.p3b, self.p4, self.p5, self.p6
        # a remote whose favourites are one of its activity screens edits them there
        if getattr(screen, "favourites", None) is not None:
            p3 = screen.favourites
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
        apply_button(spec, p0)
        spec["image_buttons"] = p3.get_buttons()
        confirm = p3.get_confirm()
        if confirm:
            spec["channel_confirm"] = confirm
        # The touchscreen buttons. These had no page at all, so an activity could not
        # be given one through the interface - the thing the manual asked for most.
        spec["hard_macros"]   = p4.get_hard_macros()
        spec["enter"] = p5.enter_macro.get_macro()
        spec["leave"] = p5.leave_macro.get_macro()
        spec["properties"] = p6.values()
        # after the properties: an activity's tabs are switched on by properties of it
        screen.apply(spec)
        apply_plan(spec, self.power.get_plan(), self.power.leave())
        self._assets = p3.get_assets()
        return spec
