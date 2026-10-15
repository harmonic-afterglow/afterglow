"""The main window: menu bar, tabs, project load and save."""

import sys
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLabel,
    QMainWindow, QMessageBox, QRadioButton, QTabWidget, QVBoxLayout
)
from PyQt6.QtCore import QRectF, QSettings, QSize, Qt, QUrl
from PyQt6.QtGui import (QAction, QDesktopServices, QIcon, QIconEngine,
                         QPainter, QPixmap)
from PyQt6.QtSvg import QSvgRenderer

from .project import new_project as empty_project

from .constants import USB_LINK_ASK_KEY, USB_LINK_CHOICE_KEY, user_files, user_folder
from .project import drop_retired_fields, retire_new_devices
from .rf_routing import rf_receivers
from .source_settings import SourcePreferences, SourceSettingsDialog
from .remote_bar import ChooseRemoteDialog, MigrationDialog
from .status_bar import ProjectStatusBar
from .tabs import (
    ActivitiesTab, DevicesTab, SettingsTab, UpdateTab, project_remote, remote_profiles)
from .widgets import load_repo_templates


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Afterglow")
        self.resize(900, 600)

        from .default_remote import default_remote_id
        self.project   = empty_project(default_remote_id())
        from .. import paths
        from .activity_buttons import previous_prepared_dir
        # Earlier versions kept the library and logos in application data. Brought into
        # Documents/Afterglow once, here, before anything reads them.
        self._adopted = paths.adopt_previous_library(previous_prepared_dir())
        paths.prepare_user_folders()
        paths.user_library("devices").mkdir(parents=True, exist_ok=True)
        from .. import themes
        self._adopted += themes.seed_examples()
        self.templates = load_repo_templates(paths.user_library())
        self.source_preferences = SourcePreferences.load()
        self._project_path = None
        self._dirty = False

        # Build tabs
        self.tabs = QTabWidget()
        # Pages of the window, not a box inside it: no frame of their own. macOS keeps its
        # centred segmented tabs, which document mode would turn into a flat strip;
        # there the title bar's own line is what goes (`_join_title_bar`).
        self.tabs.setDocumentMode(sys.platform != "darwin")
        # Clicks and Ctrl+Tab switch tabs. Taking keyboard focus as well only had Breeze
        # and Oxygen underline the current tab's name from the moment the window opened.
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.devices_tab = DevicesTab(
            self.project, self.templates, source_preferences=self.source_preferences)
        self.activities_tab = ActivitiesTab(self.project)
        self.settings_tab = SettingsTab(self.project)
        self.update_tab   = UpdateTab(self.project, self.settings_tab)

        self.tabs.addTab(self.devices_tab,    "Devices")
        self.tabs.addTab(self.activities_tab, "Activities")
        self.tabs.addTab(self.settings_tab,   "Remote Settings")
        self.tabs.addTab(self.update_tab,     "Flash")

        self.devices_tab.changed.connect(self.activities_tab.refresh)
        self.devices_tab.changed.connect(self._mark_dirty)
        self.activities_tab.changed.connect(self._mark_dirty)
        self.settings_tab.changed.connect(self._mark_dirty)
        self.update_tab.flash_succeeded.connect(self._retire_flashed_devices)
        self.update_tab.migrate_requested.connect(self.change_remote)

        self.setCentralWidget(self.tabs)
        # What the project is and whether it is saved, along the bottom. The remote is
        # there too: every tab follows it, and clicking it migrates the whole project.
        self.status = ProjectStatusBar()
        self.status.remote_clicked.connect(self.change_remote)
        self.status.contents_clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.devices_tab))
        self.status.file_clicked.connect(self._open_project_folder)
        self.status.saved_clicked.connect(self.save_project)
        self.setStatusBar(self.status)
        self._setup_menu()
        self._show_state()
        self._show_tabs()
        for note in self._adopted:
            self.status.showMessage(note[0].upper() + note[1:], 15000)

    # Menu bar
    def _setup_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")

        def _act(text, slot, shortcut=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            return a

        # Written out rather than QKeySequence.StandardKey, which is empty for some keys
        # on some platforms (Quit, on several Linux desktops). Qt shows Ctrl as Cmd on
        # macOS, so these are the usual keys there too.
        file_menu.addAction(_act("New Project",       self.new_project,     "Ctrl+N"))
        file_menu.addAction(_act("Open Project…",     self.open_project,    "Ctrl+O"))
        file_menu.addAction(_act("Import .ezhex…",    self.import_ezhex,    "Ctrl+I"))
        file_menu.addAction(_act("Save Project",      self.save_project,    "Ctrl+S"))
        file_menu.addAction(_act("Save Project As…",  self.save_project_as, "Ctrl+Shift+S"))
        file_menu.addAction(_act("Export Shareable Project…", self.export_bundle,
                                 "Ctrl+Shift+E"))
        file_menu.addAction(_act("Export .ezhex…", self.export_ezhex, "Ctrl+E"))
        file_menu.addAction(_act("Show Earlier Versions…", self.show_backups))
        file_menu.addSeparator()
        file_menu.addAction(_act("Exit", self.close, "Ctrl+Q"))

        settings_menu = mb.addMenu("Settings")
        settings_menu.addAction(_act("Device Sources…", self.configure_sources))
        # Only where there is a link to set up. The startup offer stops asking after a
        # failure or a "don't ask again", and without a way back that would be a
        # one-way door - somebody who dismissed the password prompt once could never
        # reach it again.
        from .. import usb_link
        if usb_link.applicable():
            settings_menu.addAction(_act("Remote connection…", self.setup_usb_link))
        from .. import windows_driver
        if windows_driver.applicable():
            settings_menu.addAction(_act("Remote connection…", self.usb_driver))
        settings_menu.addAction(_act("Flash a Configuration File…", self.flash_file))
        if len(remote_profiles()) > 1:
            settings_menu.addAction(_act("Default Remote…", self.choose_default_remote))

        help_menu = mb.addMenu("Help")
        help_menu.addAction(_act("Connecting a Remote…", lambda: connection_help(self)))
        help_menu.addAction(_act("Show log file", self._show_log))
        help_menu.addAction(_act("About", self._about))

    def setup_usb_link(self):
        """Re-open the startup offer on demand, whatever was answered before."""
        _usb_link_offer(self, forced=True)

    def usb_driver(self):
        """How the remote is connected, and switching it either way (Windows)."""
        from .usb_driver import driver_dialog
        driver_dialog(self)

    def flash_file(self):
        """Write any configuration file, such as a backup, as `concordance -C` would."""
        from .flash_file import flash_file_dialog
        flash_file_dialog(self, user_folder("generated"))

    def configure_sources(self):
        dialog = SourceSettingsDialog(self.source_preferences, self)
        if dialog.exec():
            self.source_preferences = dialog.preferences()
            self.source_preferences.save()
            self.devices_tab.source_preferences = self.source_preferences

    # Saved state
    def _mark_dirty(self):
        self._dirty = True
        self._show_state()

    def _mark_clean(self):
        self._dirty = False
        self._show_state()

    def _show_state(self):
        """The title and the status bar, from the project, its file and whether it is
        saved. Qt shows `[*]` as an asterisk while the window is marked modified."""
        name = Path(self._project_path).name if self._project_path else "Untitled"
        if name == "project.json":
            name = Path(self._project_path).parent.name
        self.setWindowTitle(f"{name}[*] — Afterglow")
        self.setWindowModified(self._dirty)
        self.status.show_project(self.project, self._project_path, self._profile(),
                                 self._dirty)

    def _open_project_folder(self):
        if self._project_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._project_path).parent)))

    def _keep_or_discard_changes(self) -> bool:
        """Before the project is replaced: save, discard, or stay. False means stay."""
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved Changes",
            "This project has unsaved changes. Save them first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            self.save_project()
            return not self._dirty               # a cancelled Save As keeps us here
        return answer == QMessageBox.StandardButton.Discard

    def _retire_flashed_devices(self, device_ids):
        """Make a successful flash's one-time device flags durable in the project."""
        if not retire_new_devices(self.project, device_ids):
            return
        self.devices_tab.refresh()
        if self._project_path:
            self._write_project(self._project_path)
        else:
            # An imported or never-saved project has nowhere safe to write without
            # asking. Keep the change in memory and let the normal close prompt save it.
            self._mark_dirty()

    # The remote
    def _profile(self):
        from .. import remotes
        try:
            return remotes.for_project(self.project)
        except LookupError:
            return None

    def _show_tabs(self):
        """The tabs this project's remote has, as its profile lists them."""
        profile = self._profile()
        offered = profile.tabs if profile else ("devices", "flash")
        for name, tab in (("devices", self.devices_tab), ("activities", self.activities_tab),
                          ("settings", self.settings_tab), ("flash", self.update_tab)):
            self.tabs.setTabVisible(self.tabs.indexOf(tab), name in offered)

    def _reload_tabs(self):
        """Everything shown depends on the project and on its remote; redraw it all."""
        self._show_state()
        self._show_tabs()
        self.devices_tab.refresh()
        self.activities_tab.refresh()
        self.settings_tab.refresh()
        self.update_tab.refresh()

    def _choose_remote(self, title, intro, exclude=None):
        from .default_remote import default_remote_id
        choices = [p for p in remote_profiles() if p.id != exclude]
        if not choices:
            QMessageBox.information(
                self, title, "There is no other remote Afterglow can build for yet.")
            return None
        dialog = ChooseRemoteDialog(choices, title, intro, self,
                                    selected=default_remote_id())
        return dialog.chosen() if dialog.exec() else None

    def change_remote(self, target_id=None):
        """Move the project to another remote: review what changes, save it as new."""
        from .. import migrate, remotes
        source = self._profile()
        if not target_id:
            target_id = self._choose_remote(
                "Change remote",
                "Move this project to another remote. Devices, activities and settings "
                "are checked against what that remote can do; you see every change "
                "before anything is saved, and this project is left as it is.",
                exclude=source.id if source else None)
        if not target_id:
            return
        self.settings_tab.save()
        target = remotes.get(target_id)
        try:
            migrated, report = migrate.migrate(self.project, target)
        except Exception as exc:
            QMessageBox.critical(self, "Change remote", str(exc))
            return
        if not MigrationDialog(source, target, report, self).exec():
            return
        stem = Path(self._project_path).stem if self._project_path else "project"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the moved project",
            str(user_folder("projects") / f"{stem}-{target.id}.json"),
            "JSON Project (*.json);;All (*)")
        if not path:
            return
        migrated.get("settings", {}).pop("out_file", None)   # its build is not this one's
        self.project.clear()
        self.project.update(migrated)
        self._project_path = path
        self._reload_tabs()
        self._write_project(path)
        from .default_remote import offer_after_change
        offer_after_change(self, target)

    def start_with_default_remote(self, remote_id):
        """The startup project is for the remote just chosen, if nothing was done in it."""
        untouched = not self._project_path and not self._dirty and \
            not self.project.get("devices") and not self.project.get("activities")
        profile = self._profile()
        if not remote_id or not untouched or (profile and profile.id == remote_id):
            return
        self.project.clear()
        self.project.update(empty_project(remote_id))
        self._reload_tabs()

    def choose_default_remote(self):
        from .default_remote import choose_default_remote
        self.start_with_default_remote(choose_default_remote(self))

    # Project I/O
    def new_project(self):
        if not self._keep_or_discard_changes():
            return
        project = empty_project()
        # Asked only when there is a choice to make; with one remote, it is that one.
        if len(remote_profiles()) > 1:
            chosen = self._choose_remote(
                "New project", "Which remote is this project for?")
            if not chosen:
                return
            project["settings"]["remote"] = chosen
        self.project.clear()
        self.project.update(project)
        self._project_path = None
        self._dirty = False
        self._reload_tabs()

    def open_project(self):
        from .. import project_bundle
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", str(user_folder("projects")),
            f"Projects (*.json *{project_bundle.SUFFIX});;"
            f"Shareable project (*{project_bundle.SUFFIX});;JSON Project (*.json);;All (*)")
        if not path or not self._keep_or_discard_changes():
            return
        if path.lower().endswith(project_bundle.SUFFIX):
            self.open_bundle(path)
            return
        try:
            self._load_project_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Open Failed", str(e))

    def _load_project_file(self, path):
        """Show the project saved at `path`. Raises if it cannot be read; on failure the
        window is left on an empty project rather than half of a broken one."""
        from .. import project_devices
        data = project_devices.normalise_project(
            drop_retired_fields(json.loads(Path(path).read_text(encoding="utf-8"))))
        try:
            self.project.clear()
            self.project.update(data)
            self._project_path = str(path)
            self._dirty = False
            self._reload_tabs()
        except Exception:
            self.project.clear()
            self.project.update(empty_project())
            self._project_path = None
            self._dirty = False
            self._reload_tabs()
            raise
        _remember_project(self._project_path)

    def reopen_last_project(self) -> bool:
        """Open the project worked on last time. Never raises: a project that was moved,
        deleted or broken is reported in the status bar and an empty one shown."""
        path = str(QSettings("Afterglow", "Afterglow").value(LAST_PROJECT_KEY, "") or "")
        if not path:
            return False
        if not Path(path).is_file():
            _remember_project(None)
            self.status.showMessage(
                f"The last project, {path}, is not there any more.", 15000)
            return False
        try:
            self._load_project_file(path)
        except Exception as exc:                 # noqa: BLE001 - start-up must go on
            from ..applog import LOG
            LOG.warning("could not reopen %s: %s", path, exc, exc_info=True)
            self.status.showMessage(f"Could not reopen {Path(path).name}: {exc}", 15000)
            return False
        self.status.showMessage(f"Reopened {path}", 5000)
        return True

    def show_backups(self):
        """Open the folder of this project's earlier versions, to open one from there."""
        from .. import project_backups
        if not self._project_path:
            QMessageBox.information(
                self, "Earlier versions",
                "Earlier versions are kept each time a project is saved. Save this one "
                "first.")
            return
        folder = project_backups.folder_for(self._project_path)
        if not project_backups.history(self._project_path):
            QMessageBox.information(
                self, "Earlier versions",
                f"No earlier version of this project yet. Each time it is saved, the "
                f"version it replaces is kept in\n{folder}")
            return
        current = self._project_path
        path, _ = QFileDialog.getOpenFileName(
            self, "Open an earlier version", str(folder), "JSON Project (*.json)")
        if not path or not self._keep_or_discard_changes():
            return
        try:
            self._load_project_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Open Failed", str(e))
            return
        # The earlier version is this project's, unsaved: Save puts it back in place of
        # the current one (which is kept as a backup in turn), not into Backups.
        self._project_path = current
        _remember_project(current)
        self._mark_dirty()
        self.status.showMessage(
            f"Opened the version saved in {Path(path).name}. Save to keep it.", 15000)

    def open_bundle(self, path):
        """Unpack a shareable project into a folder of its own and work on it there."""
        from .. import project_bundle
        stem, parent = Path(path).stem, user_folder("projects")
        folder, n = parent / stem, 2
        while folder.exists():                      # never unpack over an earlier copy
            folder, n = parent / f"{stem}-{n}", n + 1
        try:
            data = project_bundle.open_bundle(path, folder)
        except Exception as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            return
        self.project.clear()
        self.project.update(drop_retired_fields(data))
        self._project_path = str(folder / "project.json")
        self._reload_tabs()
        self._write_project(folder / "project.json")
        QMessageBox.information(
            self, "Shareable project",
            f"Opened {Path(path).name}. It is saved as its own project in\n{folder}\n"
            "so the file you were sent is left as it was.")

    def export_bundle(self):
        """One file holding the project and everything it needs to build anywhere."""
        from .. import project_bundle
        self.settings_tab.save()
        stem = Path(self._project_path).stem if self._project_path else "project"
        if stem == "project" and self._project_path:
            stem = Path(self._project_path).parent.name
        suggested = user_folder("projects") / f"{stem}{project_bundle.SUFFIX}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Shareable Project", str(suggested),
            f"Shareable project (*{project_bundle.SUFFIX})")
        if not path:
            return
        if not path.lower().endswith(project_bundle.SUFFIX):
            path += project_bundle.SUFFIX
        base = Path(self._project_path).parent if self._project_path else user_files()
        try:
            notes = project_bundle.export(self.project, path, base_dir=base)
        except Exception as exc:
            QMessageBox.warning(self, "Export Shareable Project", str(exc))
            return
        QMessageBox.information(
            self, "Export Shareable Project",
            f"Saved {Path(path).name}. It holds the project, its pictures and every "
            "protocol its devices use, so it builds on any computer with Afterglow."
            + (f"\n\n{len(notes)} thing(s) were added or left out to make that so." if notes
               else ""))

    def export_ezhex(self):
        """Build the project to a file of the user's choosing, without writing it.

        Flash builds on its own; this is for keeping or sharing the file itself. The
        build is shown on the Flash tab, where its log is."""
        suggested = self.update_tab.out_path()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export .ezhex", str(suggested), "Harmony Config (*.ezhex)")
        if not path:
            return
        if not path.lower().endswith(".ezhex"):
            path += ".ezhex"
        self.tabs.setCurrentWidget(self.update_tab)
        self.update_tab.export_to(Path(path))

    def import_ezhex(self):
        """Import an existing .ezhex: its devices and activities, and on a remote that has
        them its RF blasters (so devices can be routed to a known base station), as an
        editable project. Nothing is left beside the file (importer.import_file)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import .ezhex", str(user_folder("dumps")),
            "Harmony Config (*.ezhex);;All (*)")
        if not path or not self._keep_or_discard_changes():
            return
        try:
            from ..importer import import_file
            imported = import_file(path)
            data = imported.project
            # Rebuild on the imported tree and keep its (possibly exotic) IrProto verbatim;
            # The imported devices and activities are kept; the config is rebuilt from
            # the scaffold rather than from the imported tree, so nothing unmodelled
            # rides along from the remote it came off.
            data["settings"].pop("template", None)
            data["settings"].pop("base_dir", None)
            data["settings"].pop("keep_base_irproto", None)
            self.project.clear()
            self.project.update(data)
            self._project_path = None
            self._dirty = True                   # imported, and not saved anywhere yet
            self._reload_tabs()
            # Everything this config can teach goes into the library: unseen protocols,
            # the devices' command sets, any recorded waveforms. Without it the knowledge
            # stays in one project file, and a config using an unknown protocol cannot be
            # rebuilt.
            learned = ""
            try:
                from ..library import learn, summarise
                learned = "\n\nLearned into the library:\n" + summarise(
                    learn(self.project, path))
                from .. import paths
                self.templates[:] = load_repo_templates(paths.user_library())
            except Exception as exc:                       # never block an import
                learned = f"\n\nCould not update the library: {exc}"
            n_rec = len(rf_receivers(self.project))
            parts = [f"Imported {len(self.project['devices'])} device(s) and "
                     f"{len(self.project['activities'])} activity/ies from {Path(path).name}."]
            # Blasters only mean something on a remote that has them.
            if "rf_blasters" in project_remote(self.project).settings_fields:
                parts.append(
                    f"Found {n_rec} RF blaster base station(s) - each device's 'IR output' "
                    "picker now lists them." if n_rec else
                    "No RF blaster base was configured; all devices emit from the remote's "
                    "front IR.")
            if learned:
                parts.append(learned.strip())
            # what could not be carried over, as the backend said it
            if imported.warnings:
                parts.append("Not carried over:\n" + "\n".join(
                    f"- {note}" for note in imported.warnings))
            QMessageBox.information(self, "Import Complete", "\n\n".join(parts))
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", str(e))

    def save_project(self):
        if self._project_path:
            self._write_project(self._project_path)
        else:
            self.save_project_as()

    def save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", str(user_folder("projects") / "project.json"),
            "JSON Project (*.json);;All (*)")
        if path:
            self._project_path = path
            self._write_project(path)

    def _write_project(self, path):
        from .. import project_backups
        self.settings_tab.save()
        project_backups.back_up(path)        # the version this save replaces
        Path(path).write_text(json.dumps(self.project, indent=2), encoding="utf-8")
        self._mark_clean()
        _remember_project(str(path))
        self.status.showMessage(f"Saved {path}", 5000)

    def _show_log(self):
        """Open the folder that holds the log, for attaching it to a bug report."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        from .. import applog
        log = applog.path()
        if not log.exists():
            QMessageBox.information(self, "Log file",
                                    f"Nothing has been logged yet. It will be at:\n{log}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log.parent)))
        QMessageBox.information(
            self, "Log file", f"The log is {log.name} in the folder that opened:\n{log}"
            "\n\nAttach it when you report a problem.")

    def _about(self):
        # Deliberately no list of supported remotes. It is in the README, and the
        # application answers the question better by reading the model off whatever is
        # plugged in.
        from PyQt6.QtCore import QSize

        box = QMessageBox(self)
        box.setWindowTitle("About")
        box.setIconPixmap(_application_icon().pixmap(QSize(72, 72)))
        from .. import __version__

        box.setText(
            f"<b>Afterglow</b> {__version__}<br><br>"
            "Sets up universal remote controls whose manufacturer's service has shut "
            "down. Builds and projects stay on this computer. Optional online device "
            "sources fetch only catalogue records you choose to search or import."
            "<br><br>"
            "Free software, GPL-3.0-or-later. Some artwork and data files are "
            "Logitech's and are not covered by that licence - see the NOTICE.md in the "
            "icons and scaffolds folders.")
        box.exec()

    def closeEvent(self, event):
        if not self._keep_or_discard_changes():
            event.ignore()
            return
        event.accept()
def _folder_access_check(parent) -> None:
    """Say why nothing can be saved, when Windows Security is the reason.

    Checked on every start, not once: the block comes and goes with a setting outside
    Afterglow, and while it is on, every save fails with a message that names a missing
    file rather than the protection.
    """
    from .. import folder_access
    folder = folder_access.blocked_folder()
    while folder is not None:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Afterglow cannot save its files")
        box.setText(f"Windows is not letting Afterglow save in\n{folder}")
        box.setInformativeText(
            "This is usually Windows Security's ransomware protection (Controlled "
            "folder access), which guards Documents from programs it does not know. "
            "Until Afterglow is allowed, saving a project, a backup or a built "
            "configuration there fails - sometimes as \"File not found\".\n\n"
            "To allow it: Open Windows Security, choose \"Allow an app through "
            "Controlled folder access\", then Add an allowed app and pick "
            f"{Path(sys.executable).name} in\n{Path(sys.executable).parent}\n\n"
            "Or click Allow on the Windows Security notice when it appears. Then press "
            "Try again.")
        open_settings = box.addButton(
            "Open Windows Security", QMessageBox.ButtonRole.ActionRole)
        retry = box.addButton("Try again", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is open_settings:
            QDesktopServices.openUrl(QUrl(folder_access.RANSOMWARE_PROTECTION))
        elif box.clickedButton() is not retry:
            return
        folder = folder_access.blocked_folder()


LAST_PROJECT_KEY = "ui/last_project"


def _remember_project(path) -> None:
    """The project to reopen next time; None forgets it."""
    settings = QSettings("Afterglow", "Afterglow")
    if path:
        settings.setValue(LAST_PROJECT_KEY, str(path))
    else:
        settings.remove(LAST_PROJECT_KEY)


def _driver_reminder(parent) -> None:
    """Say once, where the platform needs it, that a driver must be installed first.

    Only the first time per platform: a warning on every launch is one people learn to
    dismiss without reading, which is worse than not showing it. The Flash tab keeps the
    full explanation for anyone who wants it again.

    Not a blocker - authoring and building need no driver, and someone editing a
    configuration should not be stopped by a dialog about hardware.
    """
    from .. import concord

    # Driven by whether a driver is needed, not by whether the platform is proven.
    # Windows is proven *and* still needs Logitech's driver installed first; gating on
    # the status hid the notice the moment the platform started working.
    if not concord.needs_driver():
        return
    settings = QSettings("Afterglow", "Afterglow")
    if str(settings.value("ui/driver_reminder_shown_for", "")) == sys.platform:
        return

    connection_help(parent)
    settings.setValue("ui/driver_reminder_shown_for", sys.platform)
    settings.sync()


# Logitech's servers are gone; this is the archived installer the README points at.
DRIVER_DOWNLOAD = "https://archive.org/details/logitech-harmony-software-7-8"


def connection_help(parent) -> None:
    """How to get a remote talking to this computer, step by step.

    Shown once at first start where a driver is needed, and from Help at any time. It
    used to say only "install the official drivers, see the README", and that is where
    people stopped: which software, where from now, and what to press once it is in.
    """
    from .. import concord
    steps = []
    if concord.needs_driver():
        steps.append(
            "Install Logitech Harmony Remote Software 7.8. Afterglow only needs its USB "
            "driver - you never have to open it, and it cannot sign in any more.")
    steps += [
        "Plug the remote in and wait until its screen says it is connected over USB.",
        "In Afterglow, open the Flash tab and press Check Connection.",
    ]
    if sys.platform == "win32" and not concord.needs_driver():
        steps.append(
            "The first time, Afterglow offers to turn on direct access. Accept, and "
            "allow the change when Windows asks; Logitech's software is not needed.")
    steps += [
        "Press Read from Remote to save what is on it now. Keep that file: it is how "
        "you get back to where you started.",
    ]
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Connecting a remote")
    box.setText("<ol>" + "".join(f"<li>{step}</li>" for step in steps) + "</ol>")
    download = (box.addButton("Get the driver software", QMessageBox.ButtonRole.ActionRole)
                if concord.needs_driver() else None)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()
    if download is not None and box.clickedButton() is download:
        QDesktopServices.openUrl(QUrl(DRIVER_DOWNLOAD))


def _usb_link_offer(parent, forced: bool = False) -> None:
    """Offer, once, to set up the Linux connection: direct access where our libconcord
    has it, otherwise the network link that comes up by itself.

    The remote waits for a DHCP lease that only arrives if something runs
    `harmony_net.sh` as root, so on Linux flashing simply does not work until someone
    does. That is a bad thing to discover from a failed flash, and a worse thing to
    discover from a *partly* failed one.

    Deliberately not asked when there is nothing to ask: an installed rule or a running
    helper means the link is already handled, and `usb_link.should_ask` is checked before
    the preference so that installing the rule ends the question without the user having
    had to tick anything.

    `forced` is the Settings menu entry, which asks regardless of both - it is the way
    back for anyone who declined, dismissed a password prompt, or ticked the box.

    Never blocks authoring. Declining is a supported answer and is remembered.
    """
    from .. import usb_link

    settings = QSettings("Afterglow", "Afterglow")
    if not forced:
        if not usb_link.should_ask():
            return
        if settings.value(USB_LINK_ASK_KEY, False, type=bool):
            return

    dialog = QDialog(parent)
    dialog.setWindowTitle("Remote connection")
    layout = QVBoxLayout(dialog)
    direct_possible = usb_link.direct_possible()
    if direct_possible and usb_link.direct_state() == usb_link.CURRENT:
        headline = ("Direct access is already on. You can set it up again if the remote "
                    "is not found.")
    elif direct_possible:
        headline = ("Afterglow can talk to the remote over USB itself - direct access. "
                    "It is faster and more reliable than the old network link, which "
                    "needs a DHCP helper running and can be disturbed by the network "
                    "manager. Turning it on asks for your password once.")
    elif usb_link.rule_state() == usb_link.CURRENT:
        headline = ("The network link is already installed. You can reinstall it if "
                    "something is not working.")
    elif usb_link.rule_state() == usb_link.STALE:
        headline = "An older version of the network link is installed and needs replacing."
    else:
        headline = ("A Harmony waits for this computer to give it a network address, "
                    "which needs one privileged helper. Without it, flashing will not "
                    "work.")
    label = QLabel(headline)
    label.setWordWrap(True)
    layout.addWidget(label)

    direct = QRadioButton("Direct access (recommended, asks for your password once)")
    permanent = QRadioButton("The network link, the old way (asks for your password once)")
    session = QRadioButton("The network link for this session only (asks each time)")
    decline = QRadioButton("Neither - Afterglow may not reach the remote")
    choices = ([direct] if direct_possible else []) + [permanent, session, decline]
    choices[0].setChecked(True)
    for button in choices:
        layout.addWidget(button)

    never = QCheckBox("Don't ask again")
    layout.addWidget(never)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.exec()

    # Recorded before acting: someone who ticks the box and then has the password prompt
    # fail has still said they do not want to be asked, and asking again next launch
    # would be overriding them at the worst moment.
    if never.isChecked():
        settings.setValue(USB_LINK_ASK_KEY, True)

    # Remembered whichever way it went, because it changes what a later failure means.
    # Someone who asked for the link and then flashes without it running has hit
    # something that went wrong; someone who declined has not, and telling them the same
    # thing on every button would be nagging about a decision they already made.
    choice = ("direct" if direct.isChecked() else "udev" if permanent.isChecked()
              else "session" if session.isChecked() else "declined")
    settings.setValue(USB_LINK_CHOICE_KEY, choice)
    settings.sync()

    if decline.isChecked():
        return
    ok, message = (usb_link.install_direct() if direct.isChecked()
                   else usb_link.install_rule() if permanent.isChecked()
                   else usb_link.start_helper())
    if not ok:
        # Whatever went wrong - a dismissed password prompt, no agent, a failed install -
        # say so and then stop asking at startup. Repeating an unanswered question every
        # launch is how a dialog becomes something people close without reading, and
        # Settings -> Remote connection is always there for a second attempt.
        settings.setValue(USB_LINK_ASK_KEY, True)
        settings.sync()
        QMessageBox.warning(
            parent, "The connection was not set up",
            f"{message}\n\nAfterglow will not ask again at startup. You can try again "
            f"from Settings \u2192 Remote connection.")
        return
    QMessageBox.information(parent, "Remote connection", message)


# Which drawing to use, by the pixel size actually being drawn. Below 32px these are
# separate files, not scaled copies: a tapered ray ends in a sub-pixel point and
# disappears, and the squiggle's crossings merge into a blob.
ICON_STEPS = ((20, "afterglow-icon-16.svg"),
              (28, "afterglow-icon-24.svg"),
              (40, "afterglow-icon-32.svg"),
              (10 ** 6, "afterglow-icon.svg"))


def _icon_source(pixels: int):
    """The drawing intended for `pixels`, as a path."""
    from .. import paths

    for limit, name in ICON_STEPS:
        if pixels < limit:
            return paths.branding(name)
    return paths.branding(ICON_STEPS[-1][1])


class _MarkIconEngine(QIconEngine):
    """Renders the mark at whatever size is asked for, from the right drawing.

    A `QIcon` full of fixed pixmaps cannot serve a fractionally scaled desktop. At 150%
    the titlebar wants 24 physical pixels for a 16-logical icon, at 125% it wants 20, and
    no fixed set covers every factor - so the compositor upscales the nearest bitmap, and
    that resampling is what puts colour fringes on the edges.

    Rendering from SVG on demand removes the resampling: whatever size is requested is
    drawn at that size. `paint` is the important half, because Qt hands it a painter
    already carrying the device pixel ratio, so a scaled desktop gets a vector-sharp icon
    rather than a stretched bitmap.

    The per-size drawings are kept: the source is chosen by the size being drawn, so 16px
    still gets the drawing made for 16px.
    """

    def __init__(self):
        super().__init__()
        self._cache = {}

    def _renderer(self, pixels: int):
        source = _icon_source(pixels)
        if source not in self._cache:
            renderer = QSvgRenderer(str(source)) if source.is_file() else None
            self._cache[source] = renderer if renderer and renderer.isValid() else None
        return self._cache[source]

    def paint(self, painter, rect, mode, state):
        renderer = self._renderer(min(rect.width(), rect.height()))
        if renderer is not None:
            renderer.render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size, mode, state, scale):
        # `size` is logical; `scale` is the device pixel ratio. Render at the physical
        # size and label the pixmap, so Qt draws it 1:1 instead of stretching it.
        physical = QSize(max(1, int(size.width() * scale)),
                         max(1, int(size.height() * scale)))
        pixmap = QPixmap(physical)
        pixmap.fill(Qt.GlobalColor.transparent)
        renderer = self._renderer(min(physical.width(), physical.height()))
        if renderer is not None:
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
        pixmap.setDevicePixelRatio(scale)
        return pixmap

    def availableSizes(self, mode=None, state=None):
        return [QSize(s, s) for s in (16, 22, 24, 32, 48, 64, 128, 256)]

    def clone(self):
        return _MarkIconEngine()


def _application_icon():
    """The window icon. Vector, so it is sharp at any scale factor."""
    from .. import paths

    missing = [name for _, name in ICON_STEPS if not paths.branding(name).is_file()]
    if missing:
        # An empty icon is not a blank titlebar - the window manager substitutes its own
        # generic application icon, which reads as a rendering fault rather than a
        # missing file.
        print(f"Warning: window icon incomplete, missing {sorted(set(missing))} "
              f"under {paths.branding()}")
    return QIcon(_MarkIconEngine())


def _join_title_bar(window):
    """On macOS, run the title bar straight on into the tabs below it.

    The title bar is made transparent over a window background in the colour Qt paints
    the tabs' row with, and its separator line is dropped, so nothing divides the two.
    Qt has no setting for either, so they are set on the NSWindow directly (the
    separator from macOS 11; older systems keep the line). The colour follows light
    and dark mode.
    """
    if sys.platform != "darwin":
        return
    import ctypes
    import ctypes.util
    try:
        objc = ctypes.CDLL(ctypes.util.find_library("objc"))
    except OSError:
        return
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]

    def send(receiver, selector, *args, restype=ctypes.c_void_p, argtypes=()):
        objc.objc_msgSend.restype = restype
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return objc.objc_msgSend(receiver, objc.sel_registerName(selector), *args)

    nswindow = send(int(window.winId()), b"window")      # winId is the NSView
    if not nswindow:
        return
    send(nswindow, b"setTitlebarAppearsTransparent:", True, argtypes=(ctypes.c_bool,))
    separator = objc.sel_registerName(b"setTitlebarSeparatorStyle:")
    if send(nswindow, b"respondsToSelector:", separator,
            restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)):
        send(nswindow, b"setTitlebarSeparatorStyle:", 1,   # NSTitlebarSeparatorStyleNone
             argtypes=(ctypes.c_long,))

    def paint():
        colour = window.palette().window().color()
        nscolour = send(objc.objc_getClass(b"NSColor"),
                        b"colorWithSRGBRed:green:blue:alpha:",
                        colour.redF(), colour.greenF(), colour.blueF(), 1.0,
                        argtypes=(ctypes.c_double,) * 4)
        send(nswindow, b"setBackgroundColor:", nscolour, argtypes=(ctypes.c_void_p,))

    paint()
    QApplication.styleHints().colorSchemeChanged.connect(lambda _scheme: paint())


def main():
    from .. import applog
    applog.setup()
    from ..certificates import use_system_store
    use_system_store()
    app = QApplication(sys.argv)
    app.setApplicationName("Afterglow")
    app.setOrganizationName("Afterglow")
    from .ui_helpers import keep_wrapped_labels_whole, let_form_fields_grow
    let_form_fields_grow(app)
    keep_wrapped_labels_whole(app)
    # Held for this process's lifetime so the session USB helper can tell when the last
    # window has gone; see `usb_link.hold_instance_lock`.
    from .. import usb_link
    usb_link.hold_instance_lock()
    app.setWindowIcon(_application_icon())

    win = MainWindow()
    win.show()
    _join_title_bar(win)
    _folder_access_check(win)
    _driver_reminder(win)
    _usb_link_offer(win)
    if not win.reopen_last_project():
        from .default_remote import ask_at_first_start
        win.start_with_default_remote(ask_at_first_start(win))
    sys.exit(app.exec())
