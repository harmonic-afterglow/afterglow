"""The main window: menu bar, tabs, project load and save."""

import sys
import json
import copy
import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLabel,
    QMainWindow, QMessageBox, QRadioButton, QTabWidget, QVBoxLayout
)
from PyQt6.QtCore import QRectF, QSettings, QSize, Qt, QUrl
from PyQt6.QtGui import (QAction, QDesktopServices, QIcon, QIconEngine,
                         QPainter, QPixmap)
from PyQt6.QtSvg import QSvgRenderer

from .project import DEFAULT_PROJECT

from .constants import USB_LINK_ASK_KEY, USB_LINK_CHOICE_KEY, user_files
from .project import drop_retired_fields, retire_new_devices
from .rf_routing import rf_receivers
from .source_settings import SourcePreferences, SourceSettingsDialog
from .tabs import ActivitiesTab, DevicesTab, SettingsTab, UpdateTab
from .widgets import load_repo_templates


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Afterglow")
        self.resize(900, 600)

        self.project   = copy.deepcopy(DEFAULT_PROJECT)
        from .. import paths
        paths.user_library("devices").mkdir(parents=True, exist_ok=True)
        self.templates = load_repo_templates(paths.user_library())
        self.source_preferences = SourcePreferences.load()
        self._project_path = None

        # Build tabs
        self.tabs = QTabWidget()

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
        self.update_tab.flash_succeeded.connect(self._retire_flashed_devices)

        self.setCentralWidget(self.tabs)
        self._setup_menu()

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

        file_menu.addAction(_act("New Project",       self.new_project))
        file_menu.addAction(_act("Open Project…",     self.open_project))
        file_menu.addAction(_act("Import .ezhex…",    self.import_ezhex))
        file_menu.addAction(_act("Save Project",      self.save_project,    "Ctrl+S"))
        file_menu.addAction(_act("Save Project As…",  self.save_project_as))
        file_menu.addSeparator()
        file_menu.addAction(_act("Exit", self.close))

        settings_menu = mb.addMenu("Settings")
        settings_menu.addAction(_act("Device Sources…", self.configure_sources))
        # Only where there is a link to set up. The startup offer stops asking after a
        # failure or a "don't ask again", and without a way back that would be a
        # one-way door - somebody who dismissed the password prompt once could never
        # reach it again.
        from .. import usb_link
        if usb_link.applicable():
            settings_menu.addAction(_act("Set up the USB link…", self.setup_usb_link))

        help_menu = mb.addMenu("Help")
        help_menu.addAction(_act("About", self._about))

    def setup_usb_link(self):
        """Re-open the startup offer on demand, whatever was answered before."""
        _usb_link_offer(self, forced=True)

    def configure_sources(self):
        dialog = SourceSettingsDialog(self.source_preferences, self)
        if dialog.exec():
            self.source_preferences = dialog.preferences()
            self.source_preferences.save()
            self.devices_tab.source_preferences = self.source_preferences

    # Dirty tracking
    def _mark_dirty(self):
        title = self.windowTitle()
        if not title.endswith(" *"):
            self.setWindowTitle(title + " *")

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

    # Project I/O
    def new_project(self):
        self.project.clear()
        self.project.update(copy.deepcopy(DEFAULT_PROJECT))
        self._project_path = None
        self.setWindowTitle("Afterglow")
        self.devices_tab.refresh()
        self.activities_tab.refresh()
        self.settings_tab.refresh()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", str(user_files()), "JSON Project (*.json);;All (*)")
        if not path:
            return
        try:
            from .. import project_devices
            data = project_devices.normalise_project(
                drop_retired_fields(json.loads(Path(path).read_text())))
            self.project.clear()
            self.project.update(data)
            self._project_path = path
            self.setWindowTitle(f"Afterglow - {Path(path).name}")
            self.devices_tab.refresh()
            self.activities_tab.refresh()
            self.settings_tab.refresh()
        except Exception as e:
            QMessageBox.critical(self, "Open Failed", str(e))

    def import_ezhex(self):
        """Import an existing .ezhex: unpack it, extract its devices/activities AND its RF
        blaster setup (so the base station's MAC is now known and devices can be routed to
        it), and load the result as an editable project that rebuilds on the donor's own tree."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import .ezhex", str(user_files()), "Harmony Config (*.ezhex);;All (*)")
        if not path:
            return
        try:
            from .. import ezhex as harmony_ezhex
            from ..importer import build_project
            stem = Path(path).stem
            extracted = Path(path).resolve().parent / f"{stem}_extracted"
            if extracted.exists():
                shutil.rmtree(extracted)
            harmony_ezhex.unpack(path, str(extracted))
            data = build_project(str(extracted))
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
            self.setWindowTitle(f"Afterglow - {stem} (imported) *")
            self.devices_tab.refresh()
            self.activities_tab.refresh()
            self.settings_tab.refresh()
            # Everything this config can teach goes into the library: unseen protocols,
            # the devices' command sets, any recorded waveforms. Without it the knowledge
            # stays in one project file, and a config using an unknown protocol cannot be
            # rebuilt.
            learned = ""
            try:
                from ..library import learn, summarise
                learned = "\n\nLearned into the library:\n" + summarise(
                    learn(self.project, str(extracted)))
                from .. import paths
                self.templates[:] = load_repo_templates(paths.user_library())
            except Exception as exc:                       # never block an import
                learned = f"\n\nCould not update the library: {exc}"
            n_rec = len(rf_receivers(self.project))
            QMessageBox.information(
                self, "Import Complete",
                f"Imported {len(self.project['devices'])} device(s) and "
                f"{len(self.project['activities'])} activity/ies from {Path(path).name}.\n\n"
                + (f"Found {n_rec} RF blaster base station(s) - each device's 'IR output' "
                   "picker now lists them." if n_rec else
                   "No RF blaster base was configured; all devices emit from the remote's front IR.")
                + learned)
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", str(e))

    def save_project(self):
        if self._project_path:
            self._write_project(self._project_path)
        else:
            self.save_project_as()

    def save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", str(user_files() / "project.json"),
            "JSON Project (*.json);;All (*)")
        if path:
            self._write_project(path)
            self._project_path = path

    def _write_project(self, path):
        self.settings_tab.save()
        Path(path).write_text(json.dumps(self.project, indent=2))
        name = Path(path).name
        self.setWindowTitle(f"Afterglow - {name}")

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
        if self.windowTitle().endswith(" *"):
            r = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Save:
                self.save_project()
            elif r == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        event.accept()
def _driver_reminder(parent) -> None:
    """Say once, where the platform needs it, that a driver must be installed first.

    Only the first time per platform: a warning on every launch is one people learn to
    dismiss without reading, which is worse than not showing it. The Flash tab keeps the
    full explanation for anyone who wants it again.

    Not a blocker - authoring and building need no driver, and someone editing a
    configuration should not be stopped by a dialog about hardware.
    """
    from .. import HOMEPAGE, concord

    # Driven by whether a driver is needed, not by whether the platform is proven.
    # Windows is proven *and* still needs Logitech's driver installed first; gating on
    # the status hid the notice the moment the platform started working.
    if not concord.needs_driver():
        return
    settings = QSettings("Afterglow", "Afterglow")
    if str(settings.value("ui/driver_reminder_shown_for", "")) == sys.platform:
        return

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Before you connect a remote")
    box.setText("To use this software with a remote you need to install the official "
                "Logitech Harmony drivers. Please read the project's README for more "
                "information.")
    open_button = box.addButton("Open", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()
    if box.clickedButton() is open_button:
        QDesktopServices.openUrl(QUrl(HOMEPAGE))

    settings.setValue("ui/driver_reminder_shown_for", sys.platform)
    settings.sync()


def _usb_link_offer(parent, forced: bool = False) -> None:
    """Offer, once, to make the Linux USB link come up by itself.

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
    dialog.setWindowTitle("Connecting to a remote on Linux")
    layout = QVBoxLayout(dialog)
    state = usb_link.rule_state()
    if state == usb_link.CURRENT:
        headline = ("The automatic link is already installed. You can reinstall it if "
                    "something is not working.")
    elif state == usb_link.STALE:
        headline = "An older version of the automatic link is installed and needs replacing."
    else:
        headline = ("A Harmony waits for this computer to give it a network address, "
                    "which needs one privileged helper. Without it, flashing will not "
                    "work.")
    label = QLabel(headline)
    label.setWordWrap(True)
    layout.addWidget(label)

    permanent = QRadioButton("Install the system rule (asks for your password once)")
    permanent.setChecked(True)
    session = QRadioButton("Start the helper for this session (asks each time)")
    decline = QRadioButton("Neither - flashing will not work")
    for button in (permanent, session, decline):
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
    choice = ("udev" if permanent.isChecked()
              else "session" if session.isChecked() else "declined")
    settings.setValue(USB_LINK_CHOICE_KEY, choice)
    settings.sync()

    if decline.isChecked():
        return
    ok, message = (usb_link.install_rule() if permanent.isChecked()
                   else usb_link.start_helper())
    if not ok:
        # Whatever went wrong - a dismissed password prompt, no agent, a failed install -
        # say so and then stop asking at startup. Repeating an unanswered question every
        # launch is how a dialog becomes something people close without reading, and
        # Settings -> Set up the USB link is always there for a second attempt.
        settings.setValue(USB_LINK_ASK_KEY, True)
        settings.sync()
        QMessageBox.warning(
            parent, "The link was not set up",
            f"{message}\n\nAfterglow will not ask again at startup. You can try again "
            f"from Settings \u2192 Set up the USB link.")
        return
    QMessageBox.information(parent, "USB link", message)


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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Afterglow")
    app.setOrganizationName("Afterglow")
    # Held for this process's lifetime so the session USB helper can tell when the last
    # window has gone; see `usb_link.hold_instance_lock`.
    from .. import usb_link
    usb_link.hold_instance_lock()
    app.setWindowIcon(_application_icon())

    win = MainWindow()
    win.show()
    _driver_reminder(win)
    _usb_link_offer(win)
    sys.exit(app.exec())
