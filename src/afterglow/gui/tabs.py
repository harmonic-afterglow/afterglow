"""The four workflow tabs: Devices, Activities, Remote Settings and Flash."""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QFileDialog, QMessageBox, QScrollArea, QTextEdit,
    QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from .build_service import BuildWorker as ConfigBuildWorker
from .project import (mark_device_new, new_device_ids)

from .activity_wizard import ActivityEditor, ActivityWizard
from .icons import pixmap as type_pixmap
from .constants import user_files
from .device_wizard import DeviceEditor, DeviceWizard
from .rf_routing import rf_label, rf_set
from .widgets import bold, sep


class DeviceCard(QWidget):
    """Single device row displayed in the list."""
    def __init__(self, spec, on_edit, on_delete, parent=None, project=None):
        super().__init__(parent)
        self.spec = spec
        self.project = project
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        glyph = QLabel()
        glyph.setPixmap(type_pixmap(spec.get("type", ""), 34))
        glyph.setFixedWidth(42)
        layout.addWidget(glyph)

        info = QVBoxLayout()
        name_lbl = bold(spec.get("label","?"))
        from .constants import DEVICE_TYPE_LABELS
        kind = DEVICE_TYPE_LABELS.get(spec.get("type", ""), spec.get("type", ""))
        route = rf_label(project or {}, spec.get("id"))
        sub = (f"{spec.get('mfr','')} {spec.get('model','')}  ·  {kind}  ·  "
               f"{len(spec.get('commands', []))} commands  ·  {route}")
        sub_lbl  = QLabel(sub)
        sub_lbl.setStyleSheet("color: gray;")
        info.addWidget(name_lbl)
        info.addWidget(sub_lbl)

        edit_btn   = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        edit_btn.setFixedWidth(60)
        delete_btn.setFixedWidth(60)
        edit_btn.clicked.connect(on_edit)
        delete_btn.clicked.connect(on_delete)

        layout.addLayout(info, stretch=1)
        layout.addWidget(edit_btn)
        layout.addWidget(delete_btn)

class DevicesTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, project, templates, parent=None, source_preferences=None):
        super().__init__(parent)
        self.project   = project
        self.templates = templates
        self.source_preferences = source_preferences
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(bold("Devices", 11))
        top.addStretch()
        add_btn = QPushButton("+ Add Device")
        add_btn.clicked.connect(self.add_device)
        top.addWidget(add_btn)
        layout.addLayout(top)
        layout.addWidget(sep())

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.addStretch()
        self.scroll_area.setWidget(self.list_widget)
        layout.addWidget(self.scroll_area)

        self.refresh()

    def refresh(self):
        # Clear existing rows
        while self.list_layout.count() > 1:  # keep the trailing stretch
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, spec in enumerate(self.project["devices"]):
            card = DeviceCard(spec,
                              on_edit   = lambda _, idx=i: self.edit_device(idx),
                              on_delete = lambda _, idx=i: self.delete_device(idx),
                              project   = self.project)
            self.list_layout.insertWidget(self.list_layout.count()-1, card)
            self.list_layout.insertWidget(self.list_layout.count()-1, sep())

        if not self.project["devices"]:
            empty = QLabel("No devices yet. Click '+ Add Device' to get started.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: gray; padding: 20px;")
            self.list_layout.insertWidget(0, empty)

    def add_device(self):
        wiz = DeviceWizard(
            self.templates, self, project=self.project,
            source_preferences=self.source_preferences)
        if wiz.exec() and wiz.result_spec:
            mark_device_new(wiz.result_spec)
            self.project["devices"].append(wiz.result_spec)
            rf_set(self.project, wiz.result_spec.get("id"), wiz.rf_token())
            self.refresh()
            self.changed.emit()

    def edit_device(self, idx):
        spec = self.project["devices"][idx]
        wiz = DeviceEditor(
            self.templates, self, existing=spec, project=self.project,
            source_preferences=self.source_preferences)
        if wiz.exec() and wiz.result_spec:
            self.project["devices"][idx] = wiz.result_spec
            rf_set(self.project, wiz.result_spec.get("id"), wiz.rf_token())
            self.refresh()
            self.changed.emit()

    def delete_device(self, idx):
        lbl = self.project["devices"][idx].get("label","device")
        if QMessageBox.question(
            self, "Delete Device",
            f"Remove '{lbl}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            del self.project["devices"][idx]
            self.refresh()
            self.changed.emit()
class ActivityCard(QWidget):
    def __init__(self, spec, devices_by_id, on_edit, on_delete, parent=None):
        super().__init__(parent)
        self.spec = spec
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        disp_lbl = devices_by_id.get(spec.get("display",""), {}).get("label","?")
        ctrl_lbl = devices_by_id.get(spec.get("control",""), {}).get("label","?")
        atype    = spec.get("type","VirtualTelevisionN")

        glyph = QLabel()
        glyph.setPixmap(type_pixmap(atype, 34))
        glyph.setFixedWidth(42)
        layout.addWidget(glyph)

        info = QVBoxLayout()
        info.addWidget(bold(spec.get("label","?")))
        sub = QLabel(f"{atype}  ·  Display: {disp_lbl}  ·  Control: {ctrl_lbl}")
        sub.setStyleSheet("color: gray;")
        info.addWidget(sub)

        edit_btn   = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        edit_btn.setFixedWidth(60); delete_btn.setFixedWidth(60)
        edit_btn.clicked.connect(on_edit)
        delete_btn.clicked.connect(on_delete)

        layout.addLayout(info, stretch=1)
        layout.addWidget(edit_btn)
        layout.addWidget(delete_btn)
class ActivitiesTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(bold("Activities", 11))
        top.addStretch()
        add_btn = QPushButton("+ Add Activity")
        add_btn.clicked.connect(self.add_activity)
        top.addWidget(add_btn)
        layout.addLayout(top)
        layout.addWidget(sep())

        hint = QLabel("Activities group devices into one-touch tasks (e.g. 'Watch TV'). "
                       "Add your devices first, then create activities here.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.addStretch()
        self.scroll_area.setWidget(self.list_widget)
        layout.addWidget(self.scroll_area)

        self.refresh()

    def _by_id(self):
        return {d["id"]: d for d in self.project["devices"]}

    def refresh(self):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        by_id = self._by_id()
        for i, spec in enumerate(self.project["activities"]):
            card = ActivityCard(spec, by_id,
                                on_edit   = lambda _, idx=i: self.edit_activity(idx),
                                on_delete = lambda _, idx=i: self.delete_activity(idx))
            self.list_layout.insertWidget(self.list_layout.count()-1, card)
            self.list_layout.insertWidget(self.list_layout.count()-1, sep())

        if not self.project["activities"]:
            empty = QLabel("No activities yet. Click '+ Add Activity' to create one.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: gray; padding: 20px;")
            self.list_layout.insertWidget(0, empty)

    def add_activity(self):
        devs = self.project["devices"]
        if not devs:
            QMessageBox.information(self, "No Devices",
                                    "Add at least one device before creating an activity.")
            return
        wiz = ActivityWizard(devs, self,
                             taken_ids=[a.get("id") for a in self.project["activities"]])
        if wiz.exec() and wiz.result_spec:
            self.project["activities"].append(wiz.result_spec)
            self._keep_assets(wiz)
            self.refresh()
            self.changed.emit()

    def _keep_assets(self, dialog):
        """Record any picture a favourite uses, so the build copies it in.

        A favourite names its logo in the configuration; the file itself has to be put
        alongside. Without this the config referred to images that were never
        included, and the remote drew an empty favourite.
        """
        from pathlib import Path
        assets = self.project.setdefault("assets", [])
        known = {a.get("name") for a in assets}
        for path in getattr(dialog, "_assets", []) or []:
            name = Path(path).name
            if name not in known:
                assets.append({"source": str(path), "name": name})
                known.add(name)

    def edit_activity(self, idx):
        editor = ActivityEditor(self.project["devices"], self,
                                existing=self.project["activities"][idx])
        if editor.exec() and editor.result_spec:
            self.project["activities"][idx] = editor.result_spec
            self._keep_assets(editor)
            self.refresh()
            self.changed.emit()

    def delete_activity(self, idx):
        lbl = self.project["activities"][idx].get("label","activity")
        if QMessageBox.question(
            self, "Delete Activity",
            f"Remove '{lbl}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            del self.project["activities"][idx]
            self.refresh()
            self.changed.emit()
def remote_profiles():
    """Remotes the user may build for: the verified ones only.

    Only verified profiles ship (docs/harmony_pk/remote-identities.md says why), so this is every
    profile in the library; the filter stays as a guard for a locally added one.
    """
    from ..remotes import load_all
    return [p for p in load_all() if p.verified]


class SettingsTab(QWidget):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        layout = QVBoxLayout(self)
        layout.addWidget(bold("Remote Settings", 11))
        layout.addWidget(sep())

        form = QFormLayout()
        s = project.get("settings", {})

        # Which remote this config is for. Only verified profiles ship, so everything
        # offered here can actually be built and flashed.
        self.remote = QComboBox()
        for profile in remote_profiles():
            self.remote.addItem(profile.model, profile.id)
        idx = self.remote.findData(s.get("remote", "harmony-900"))
        self.remote.setCurrentIndex(idx if idx >= 0 else 0)

        self.out_file   = QLineEdit(s.get("out_file", ""))
        self.first_name = QLineEdit(s.get("first_name", ""))
        self.last_name  = QLineEdit(s.get("last_name", ""))
        for field, hint in ((self.out_file, "living-room.ezhex"),
                            (self.first_name, "your first name"),
                            (self.last_name, "your last name")):
            field.setPlaceholderText(hint)
        self.locale = QComboBox()
        locales = [
            ("English", "enu"), ("Spanish", "esp"), ("Russian", "rus"),
            ("German", "deu"), ("Dutch", "nld"), ("Danish", "dan"),
            ("Finnish", "fin"), ("Italian", "ita"), ("Swedish", "sve")
        ]
        for name, code in locales:
            self.locale.addItem(name, code)
            
        saved_locale = s.get("locale", "enu")
        idx = self.locale.findData(saved_locale)
        if idx >= 0:
            self.locale.setCurrentIndex(idx)

        form.addRow("Remote:", self.remote)
        form.addRow("Output .ezhex file:", self.out_file)
        form.addRow("First Name:", self.first_name)
        form.addRow("Last Name:", self.last_name)
        form.addRow("Language:", self.locale)

        # Blasters are paired with the remote, not with a device, so this lives here
        # rather than on a device's Edit page: pairing must not require a device first.
        blaster_row = QHBoxLayout()
        self.blaster_label = QLabel()
        self.blaster_label.setWordWrap(True)
        blaster_row.addWidget(self.blaster_label, 1)
        self.add_blaster_btn = QPushButton("Add blaster…")
        self.add_blaster_btn.setToolTip(
            "Pair a wireless blaster base with the remote, then read its address back")
        self.add_blaster_btn.clicked.connect(self._add_blaster)
        blaster_row.addWidget(self.add_blaster_btn)
        form.addRow("RF blasters:", blaster_row)
        self._refresh_blasters()

        # The remote's own preferences (platformconfig/system_*.dat). These are
        # writable: see `payloads.pk.mode_for` for why their file mode matters.
        from .. import preferences as prefs
        form.addRow(sep())
        heading = bold("Remote's own settings")
        form.addRow(heading)
        note = QLabel(
            "These are applied when you flash. The remote keeps its own copy, so a "
            "setting you change on the device under Options stays until the next flash "
            "overwrites it.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        form.addRow(note)

        self.prefs = {}
        for key in prefs.PREFERENCES:
            current = str(s.get(key, prefs.DEFAULTS.get(key, "")))
            choices = prefs.CHOICES.get(key)
            if choices:
                widget = QComboBox()
                for label, value in choices:
                    widget.addItem(label, value)
                idx = widget.findData(current)
                widget.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                widget = QSpinBox()          # numeric, so it cannot be given a non-number
                low, high = prefs.RANGES[key]
                widget.setRange(low, high)
                widget.setValue(int(current) if current.isdigit() else prefs.DEFAULTS[key])
            widget.setToolTip("Applied to the remote when you flash this configuration.")
            self.prefs[key] = widget
            form.addRow(QLabel(prefs.LABELS[key] + ":"), widget)

        layout.addLayout(form)
        layout.addStretch()

    def _refresh_blasters(self):
        from .rf_routing import rf_receivers
        receivers = rf_receivers(self.project)
        if receivers:
            self.blaster_label.setText(", ".join(
                f"Base {r.get('label')} ({r.get('mac')})" for r in receivers))
            self.blaster_label.setStyleSheet("")
        else:
            self.blaster_label.setText("None paired - devices can only use the "
                                       "remote's own front emitter.")
            self.blaster_label.setStyleSheet("color: gray;")

    def _add_blaster(self):
        from .rf_routing import add_receiver
        if add_receiver(self.project, self):
            self._refresh_blasters()

    def save(self):
        if "settings" not in self.project:
            self.project["settings"] = {}
        self.project["settings"]["remote"]      = self.remote.currentData()
        self.project["settings"]["out_file"]    = self.out_file.text().strip()
        self.project["settings"]["first_name"]  = self.first_name.text().strip()
        self.project["settings"]["last_name"]   = self.last_name.text().strip()
        self.project["settings"]["locale"]      = self.locale.currentData()
        for key, widget in getattr(self, "prefs", {}).items():
            self.project["settings"][key] = (
                widget.currentData() if hasattr(widget, "currentData")
                else str(widget.value()))
        # Clean up obsolete settings from old projects
        if "work_dir" in self.project["settings"]:
            del self.project["settings"]["work_dir"]

    REQUIRED = (("out_file", "Output .ezhex file"),
                ("first_name", "First name"),
                ("last_name", "Last name"))

    def missing(self):
        """Required settings the user has not filled in yet."""
        self.save()
        s = self.project.get("settings", {})
        return [label for key, label in self.REQUIRED if not str(s.get(key, "")).strip()]

    def refresh(self):
        s = self.project.get("settings", {})
        idx = self.remote.findData(s.get("remote", "harmony-900"))
        if idx >= 0:
            self.remote.setCurrentIndex(idx)
        self.out_file.setText(s.get("out_file", ""))
        self.first_name.setText(s.get("first_name", ""))
        self.last_name.setText(s.get("last_name", ""))
        
            
        idx = self.locale.findData(s.get("locale", "enu"))
        if idx >= 0:
            self.locale.setCurrentIndex(idx)

        self._refresh_blasters()
        # An imported config brings its own preferences; show those, not the defaults.
        from .. import preferences as prefs
        for key, widget in getattr(self, "prefs", {}).items():
            current = str(s.get(key, prefs.DEFAULTS.get(key, "")))
            if hasattr(widget, "currentData"):
                idx = widget.findData(current)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif current.isdigit():
                widget.setValue(int(current))


class UpdateTab(QWidget):
    flash_succeeded = pyqtSignal(object)  # ids flagged new in the configuration written

    def __init__(self, project, settings_tab, parent=None):
        super().__init__(parent)
        self.project  = project
        self.settings = settings_tab
        self.worker   = None
        self._building_new_device_ids = ()
        self._built_new_device_ids = ()
        layout = QVBoxLayout(self)

        layout.addWidget(bold("Flash", 11))
        layout.addWidget(sep())

        info = QLabel(
            "Build compiles your devices and activities into a .ezhex file, and Flash "
            "writes it to the remote. Read from Remote saves what is on the remote "
            "now - do that once before you change anything, and keep the file."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addWidget(sep())

        btn_row = QHBoxLayout()
        self.build_btn = QPushButton("Build Config")
        self.flash_btn = QPushButton("Flash to Remote")
        self.read_btn = QPushButton("Read from Remote")
        self.check_btn = QPushButton("Check Connection")
        self.flash_btn.setEnabled(False)
        self.build_btn.clicked.connect(self.build)
        self.flash_btn.clicked.connect(self.flash)
        self.read_btn.clicked.connect(self.read_from_remote)
        self.check_btn.clicked.connect(self.check_connection)
        for button in (self.build_btn, self.flash_btn, self.read_btn, self.check_btn):
            btn_row.addWidget(button)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Everything that touches the remote needs libconcord. Say so once, here,
        # rather than failing at the moment the user presses a button.
        from .. import concord
        if not concord.available():
            for button in (self.flash_btn, self.read_btn, self.check_btn):
                button.setEnabled(False)
                button.setToolTip("libconcord is not installed - see the README")
            note = QLabel("libconcord was not found, so the remote cannot be reached. "
                          "Building configurations still works.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #b26a00;")
            layout.addWidget(note)

        # Having libconcord is not the same as being able to reach the remote. The remote
        # waits for a DHCP lease on its USB network interface before it answers, and only
        # Linux automates that here. Say so before the user writes to hardware that has no
        # vendor recovery - a silent failure at that point is the worst place for one.
        #
        # The buttons stay enabled: this is a statement about what has been tried, not a
        # capability gate, and someone finding out that it works on macOS is exactly the
        # report this project wants.
        status, explanation = concord.link_support()
        if status != "tested":
            warning = QLabel(f"Reaching the remote is untested on this system. "
                             f"{explanation}")
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #b26a00;")
            layout.addWidget(warning)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Courier", 9))
        layout.addWidget(self.log_box)

    def build(self):
        # Required settings have no defaults on purpose, so ask rather than invent one.
        missing = self.settings.missing()
        if missing:
            QMessageBox.warning(
                self, "Missing settings",
                "Fill these in on the Remote Settings tab first:\n\n  • "
                + "\n  • ".join(missing))
            return
        self.log_box.clear()
        self.build_btn.setEnabled(False)
        self.flash_btn.setEnabled(False)
        self.progress.setVisible(True)
        self._building_new_device_ids = new_device_ids(self.project)

        self.worker = ConfigBuildWorker(user_files(), self.project)
        self.worker.log.connect(self.log_box.append)
        self.worker.success.connect(self._on_success)
        self.worker.failure.connect(self._on_failure)
        self.worker.start()

    def _on_success(self):
        self._built_new_device_ids = self._building_new_device_ids
        self.progress.setVisible(False)
        self.build_btn.setEnabled(True)
        self.flash_btn.setEnabled(True)

    def _on_failure(self, msg):
        self.progress.setVisible(False)
        self.build_btn.setEnabled(True)
        self.log_box.append(f"\nFAILED: build did not complete\n{msg}")

    def _busy(self, busy: bool):
        for button in (self.build_btn, self.flash_btn, self.read_btn, self.check_btn):
            button.setEnabled(not busy)
        self.progress.setVisible(busy)

    def _run(self, operation, **kwargs):
        """Start a remote operation on a worker thread and wire it to the log."""
        from .remote_ops import RemoteWorker
        self._warn_if_the_link_is_down()
        self._busy(True)
        self._worker = RemoteWorker(operation, self, **kwargs)
        self._worker.log.connect(self.log_box.append)
        self._worker.progress.connect(self._on_remote_progress)
        self._worker.done.connect(self._on_remote_done)
        return self._worker

    def _warn_if_the_link_is_down(self):
        """Say in the log that the Linux USB link is not up, then carry on regardless.

        Placed on every button rather than on Flash alone: identify and read need the
        link just as much, and "check connection" failing for this reason is the moment
        someone is most likely to be looking for a cause.

        Never blocks. The detection is inference from outside the helper, so a false
        positive has to cost one wrong line in a log rather than a refused operation -
        and the operation itself will say plainly enough whether it worked.
        """
        from PyQt6.QtCore import QSettings

        from .. import usb_link
        from .constants import USB_LINK_CHOICE_KEY

        choice = str(QSettings("Afterglow", "Afterglow").value(USB_LINK_CHOICE_KEY, ""))
        warning = usb_link.link_warning(choice)
        if warning:
            self.log_box.append(warning)

    def _on_remote_progress(self, stage, current, total):
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
            self.progress.setFormat(f"{stage} - %p%")
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat(stage)

    def _on_remote_done(self, ok, message):
        operation = getattr(getattr(self, "_worker", None), "operation", None)
        self._busy(False)
        self.progress.setRange(0, 0)
        self.progress.setFormat("")
        # Words, not glyphs. A tick and a cross differ by one character in a proportional
        # -to-monospace fallback and are indistinguishable to a screen reader, and on
        # Windows a console font may have neither. `append` decides between rich and plain
        # text by sniffing, and this has no markup in it, so embedded newlines survive as
        # line breaks - which the connection advice below depends on.
        self.log_box.append(("\nSUCCESS: " if ok else "\nFAILED: ") + message)
        if ok and operation == "write":
            self.flash_succeeded.emit(self._built_new_device_ids)
            # The file on disk still carries the one-time flags. Require a rebuild
            # before another flash so it cannot prompt for the same devices again.
            self.flash_btn.setEnabled(False)

    def check_connection(self):
        """Identify the attached remote. Reads nothing and changes nothing."""
        self.log_box.clear()
        self._run("identify").start()

    def read_from_remote(self):
        """Save the configuration currently on the remote. This is the way back."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the remote's current configuration",
            str(user_files() / "my-remote.ezhex"), "Harmony config (*.ezhex)")
        if not path:
            return
        self.log_box.clear()
        self._run("read", path=path).start()

    def flash(self):
        self.settings.save()
        out = self.project["settings"].get("out_file", "")
        out_path = Path(out) if out and Path(out).is_absolute() else user_files() / (out or "")
        if not out or not out_path.exists():
            QMessageBox.warning(self, "Nothing to flash",
                                f"{out_path.name or 'The output file'} does not exist "
                                "yet. Build the config first.")
            return
        answer = QMessageBox.question(
            self, "Flash to Remote",
            f"Write {out_path.name} to the remote?\n\n"
            "This replaces everything on it. If you have not saved the remote's "
            "current configuration, cancel and use Read from Remote first - "
            "there is no way to get it back afterwards.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.log_box.clear()
        self._run("write", path=str(out_path)).start()
