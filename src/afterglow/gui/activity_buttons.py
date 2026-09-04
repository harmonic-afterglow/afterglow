"""The two kinds of button an activity puts on the touchscreen.

They are different things on the remote and were being edited as one, which is why an
"image button" dialog also asked for an icon:

**Favourites** are a grid of channel logos. Each carries an `<Image>` - a picture file
copied into the configuration - and dials a channel, sends a command, or runs a macro.
Their `<Number>` is followed by a confirm key on many receivers.

**Screen buttons** are labelled keys. Each may carry an `<Icon>`: the *name* of one of
the 87 glyphs already in the remote's firmware, not a file. There is nothing to import
and nothing to scale.

So: favourites take an image and no icon, screen buttons take an icon and no image, and
both show what was picked instead of a filename.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                             QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QMessageBox, QPushButton,
                             QStackedWidget, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget, QWizardPage)

from .icon_picker import choose as choose_icon
from .icons import pixmap as glyph_pixmap
from .macro import MacroEditorWidget
from .ui_helpers import FilterCombo, order_by_participation

PREVIEW = 48          # the remote draws these small; showing them huge flatters them


class _Preview(QLabel):
    """A fixed square that shows the chosen picture, or says nothing is chosen."""

    def __init__(self, side: int = PREVIEW):
        super().__init__()
        self._side = side
        self.setFixedSize(side, side)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("border: 1px solid palette(mid); color: gray;")
        self.clear_preview()

    def clear_preview(self):
        self.setPixmap(QPixmap())
        self.setText("none")

    def show_file(self, path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.clear_preview()
            return False
        self.setPixmap(pixmap.scaled(self._side, self._side,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        self.setText("")
        return True

    def show_glyph(self, name):
        if not name:
            self.clear_preview()
            return
        pixmap = glyph_pixmap(name, self._side)
        if pixmap.isNull():
            self.setText(name)
            return
        self.setPixmap(pixmap)
        self.setText("")


class _ActionEditor(QWidget):
    """Pick what a button does: a command, or a macro. Shared by both dialogs."""

    def __init__(self, devices, with_channel: bool, parent=None, participating=None,
                 existing=None):
        super().__init__(parent)
        self.devices = devices
        self._existing = existing or {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.kind = FilterCombo()
        kinds = [("Send a command", "command"), ("Run a macro", "macro")]
        if with_channel:
            kinds.insert(0, ("Tune to a channel", "channel"))
        self.kind.set_items(kinds)
        self.kind.setEditable(False)
        layout.addWidget(self.kind)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.channel = QLineEdit()
        self.channel.setPlaceholderText("channel number, e.g. 101")
        if with_channel:
            self.stack.addWidget(self.channel)

        command = QWidget()
        form = QFormLayout(command)
        form.setContentsMargins(0, 0, 0, 0)
        self.device = FilterCombo()
        self.device.setEditable(False)
        ordered, split = order_by_participation(devices, participating)
        self.device.set_items([(d.get("label", "?"), d["id"]) for d in ordered])
        if split:
            self.device.insertSeparator(split)
        self.command = FilterCombo()
        form.addRow("Device:", self.device)
        form.addRow("Command:", self.command)
        self.stack.addWidget(command)

        self.macro = MacroEditorWidget(devices, participating=participating)
        self.stack.addWidget(self.macro)

        self.kind.currentIndexChanged.connect(
            lambda: self.stack.setCurrentIndex(self.kind.currentIndex()))
        self.device.currentIndexChanged.connect(self._device_changed)
        self._device_changed()
        self._load(self._existing)

    def _load(self, existing):
        """Fill in an action that already exists, so it can be edited rather than
        deleted and typed again."""
        kind = existing.get("kind")
        if not kind:
            return
        self.kind.select_data(kind)
        self.stack.setCurrentIndex(self.kind.currentIndex())
        payload = existing.get("payload")
        if kind == "channel":
            self.channel.setText(str(payload or ""))
        elif kind == "command" and isinstance(payload, (list, tuple)):
            self.device.select_data(payload[0])
            self._device_changed()
            self.command.select_data(payload[1])
        elif kind == "macro":
            self.macro.load(payload or [])

    def _device_changed(self):
        device = next((d for d in self.devices
                       if d["id"] == self.device.currentData()), None)
        self.command.set_items([(c[0], c[0]) for c in (device or {}).get("commands", [])])

    def value(self):
        kind = self.kind.currentData()
        if kind == "channel":
            return kind, self.channel.text().strip()
        if kind == "command":
            return kind, (self.device.currentData(), self.command.currentData())
        return kind, self.macro.get_macro()


class FavouriteDialog(QDialog):
    """A favourite: a logo, a label, and what it tunes to."""

    def __init__(self, devices, parent=None, existing=None, participating=None):
        super().__init__(parent)
        self.setWindowTitle("Favourite")
        self.resize(520, 460)
        self.result_data = None
        self.image_path = None

        layout = QFormLayout(self)
        self.label_edit = QLineEdit((existing or {}).get("label", ""))
        self.label_edit.setPlaceholderText("e.g. BBC One")
        layout.addRow("Label:", self.label_edit)

        self.action = _ActionEditor(devices, with_channel=True,
                                    participating=participating,
                                    existing=existing)
        layout.addRow("Does:", self.action)

        row = QHBoxLayout()
        self.preview = _Preview()
        browse = QPushButton("Choose image…")
        browse.clicked.connect(self._browse)
        self.image_name = QLabel("none")
        self.image_name.setStyleSheet("color: gray;")
        row.addWidget(self.preview)
        row.addWidget(browse)
        row.addWidget(self.image_name, 1)
        layout.addRow("Logo:", row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        keep = (existing or {}).get("image")
        if keep:
            self.image_name.setText(str(keep))
            found = _find_image(keep)
            if found:
                self.preview.show_file(found)
            self._kept_image = keep

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a logo", "", "Images (*.png *.jpg *.jpeg *.gif)")
        if not path:
            return
        # Fit it to the touchscreen's cell first: what goes in the configuration is the
        # normalised copy, not the original, and the preview shows what the remote will.
        try:
            prepared = prepare_logo(path)
        except Exception as exc:
            QMessageBox.warning(self, "Not an image",
                                f"{Path(path).name} could not be read as a picture.\n\n{exc}")
            return
        if self.preview.show_file(prepared):
            self.image_path = str(prepared)
            self.image_name.setText(prepared.name)
        else:
            QMessageBox.warning(self, "Not an image",
                                f"{Path(path).name} could not be read as a picture.")

    def accept(self):
        label = self.label_edit.text().strip()
        if not label:
            QMessageBox.warning(self, "A label is needed",
                                "Give the favourite a name to show under its logo.")
            return
        kind, payload = self.action.value()
        image = (Path(self.image_path).name if self.image_path
                 else getattr(self, "_kept_image", ""))
        self.result_data = (label, kind, payload, image)
        super().accept()


class ScreenButtonDialog(QDialog):
    """A touchscreen button: a label, a glyph from the remote, and what it does."""

    def __init__(self, devices, parent=None, participating=None, existing=None):
        super().__init__(parent)
        self.setWindowTitle("Command")
        self.resize(520, 460)
        self.result_data = None
        existing = existing or {}
        self.icon_name = existing.get("icon")

        layout = QFormLayout(self)
        self.label_edit = QLineEdit(existing.get("label", ""))
        self.label_edit.setPlaceholderText("e.g. Guide")
        layout.addRow("Label:", self.label_edit)

        action_state = {}
        if existing.get("macro"):
            action_state = {"kind": "macro", "payload": existing["macro"]}
        elif existing.get("command"):
            action_state = {"kind": "command",
                            "payload": (existing.get("device"), existing["command"])}
        self.action = _ActionEditor(devices, with_channel=False,
                                    participating=participating,
                                    existing=action_state)
        layout.addRow("Does:", self.action)

        row = QHBoxLayout()
        self.preview = _Preview()
        choose = QPushButton("Choose icon…")
        choose.clicked.connect(self._choose_icon)
        self.icon_label = QLabel("none")
        self.icon_label.setStyleSheet("color: gray;")
        row.addWidget(self.preview)
        row.addWidget(choose)
        row.addWidget(self.icon_label, 1)
        layout.addRow("Icon:", row)
        if self.icon_name:
            self.icon_label.setText(self.icon_name)
            self.preview.show_glyph(self.icon_name)
        note = QLabel("Icons come from the remote's own set.")
        note.setStyleSheet("color: gray;")
        layout.addRow("", note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _choose_icon(self):
        ok, name = choose_icon(self.icon_name, self)
        if not ok:
            return
        self.icon_name = name or None
        self.icon_label.setText(self.icon_name or "none")
        self.preview.show_glyph(self.icon_name)

    def accept(self):
        label = self.label_edit.text().strip()
        if not label:
            QMessageBox.warning(self, "A label is needed",
                                "Give the button a name to show on screen.")
            return
        kind, payload = self.action.value()
        entry = {"label": label}
        if self.icon_name:
            entry["icon"] = self.icon_name
        if kind == "macro":
            entry["macro"] = payload
        else:
            entry["device"], entry["command"] = payload
        self.result_data = entry
        super().accept()


class _ButtonTable(QTableWidget):
    """Shared table plumbing: a preview column and one row per button."""

    def __init__(self, headers):
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setDefaultSectionSize(PREVIEW + 8)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)


class FavouritesPage(QWizardPage):
    """Favourites: logos that tune to something."""

    def __init__(self, devices, existing, parent=None):
        super().__init__(parent)
        self.devices = devices
        self.setTitle("Favourites")
        self.setSubTitle(
            "Channel logos for the touchscreen. Each one tunes to a channel, sends a "
            "command, or runs a macro.")
        layout = QVBoxLayout(self)

        self.table = _ButtonTable(["Logo", "Label", "Does"])
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        add = QPushButton("Add favourite…")
        add.clicked.connect(self._add)
        edit = QPushButton("Edit…")
        edit.clicked.connect(self._edit)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        for button in (add, edit, remove):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.table.itemDoubleClicked.connect(lambda *_: self._edit())

        # Many receivers need the channel number confirmed with OK. Without this the
        # favourite types the digits and sits there.
        confirm_row = QHBoxLayout()
        confirm_row.addWidget(QLabel("Press after the digits:"))
        self.confirm = FilterCombo()
        self.confirm.setToolTip(
            "The key that confirms a channel number on the control device - often "
            "Select or OK. Leave blank if it tunes as soon as the digits are entered.")
        confirm_row.addWidget(self.confirm, 1)
        layout.addLayout(confirm_row)
        self._load_confirm_choices(existing.get("channel_confirm"))

        for entry in existing.get("image_buttons", []):
            self._add_row(*entry)
        for station, number, image in existing.get("channels", []):
            self._add_row(station, "channel", number, image)

    def _load_confirm_choices(self, current):
        names = {c[0] for d in self.devices for c in d.get("commands", [])}
        likely = [n for n in ("Select", "OK", "Enter", "NumberEnter") if n in names]
        rest = sorted(names - set(likely))
        self.confirm.set_items([("(none)", None)]
                               + [(n, n) for n in likely + rest])
        if current:
            self.confirm.select_data(current)

    def _add_row(self, label, kind, payload, image):
        row = self.table.rowCount()
        self.table.insertRow(row)
        preview = _Preview(PREVIEW - 8)
        if image:
            found = _find_image(image)
            if found:
                preview.show_file(found)
            else:
                preview.setText(Path(str(image)).stem[:6])
        self.table.setCellWidget(row, 0, preview)
        self.table.setItem(row, 1, QTableWidgetItem(str(label)))
        self.table.setItem(row, 2, QTableWidgetItem(_describe(kind, payload)))
        self.table.item(row, 1).setData(Qt.ItemDataRole.UserRole,
                                        (label, kind, payload, image))

    def set_participating(self, ids):
        self._participating = list(ids or [])

    def _add(self):
        dialog = FavouriteDialog(self.devices, self,
                                 participating=getattr(self, "_participating", None))
        if dialog.exec() and dialog.result_data:
            self._add_row(*dialog.result_data)
            if dialog.image_path:
                self._remember_asset(dialog.image_path)

    def _remember_asset(self, path):
        self.setProperty("assets", (self.property("assets") or []) + [path])

    def _edit(self):
        """Change a favourite that is already in the list.

        Without this the only way to correct a typo or swap a logo was to delete the
        row and build it again from nothing.
        """
        row = self.table.currentRow()
        if row < 0:
            return
        label, kind, payload, image = self.table.item(row, 1).data(
            Qt.ItemDataRole.UserRole)
        dialog = FavouriteDialog(
            self.devices, self,
            existing={"label": label, "kind": kind, "payload": payload, "image": image},
            participating=getattr(self, "_participating", None))
        if dialog.exec() and dialog.result_data:
            self.table.removeRow(row)
            self._add_row(*dialog.result_data)
            if dialog.image_path:
                self._remember_asset(dialog.image_path)

    def _remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def get_buttons(self):
        return [self.table.item(r, 1).data(Qt.ItemDataRole.UserRole)
                for r in range(self.table.rowCount())]

    def get_confirm(self):
        return self.confirm.currentData()

    def get_assets(self):
        return list(self.property("assets") or [])


class ScreenButtonsPage(QWizardPage):
    """The labelled buttons the activity puts on the touchscreen."""

    def __init__(self, devices, existing, parent=None):
        super().__init__(parent)
        self.devices = devices
        self.setTitle("Commands")
        self.setSubTitle(
            "The buttons on this activity's touchscreen page - what the remote "
            "itself calls Commands. Each sends one command or runs a macro, and can "
            "carry one of the remote's own icons.")
        layout = QVBoxLayout(self)

        self.table = _ButtonTable(["Icon", "Label", "Does"])
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        add = QPushButton("Add command…")
        add.clicked.connect(self._add)
        edit = QPushButton("Edit…")
        edit.clicked.connect(self._edit)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        for button in (add, edit, remove):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.table.itemDoubleClicked.connect(lambda *_: self._edit())

        for entry in existing.get("soft_buttons", []):
            self._add_row(entry)

    def _add_row(self, entry):
        if isinstance(entry, (list, tuple)):        # (label, device, command[, icon])
            entry = {"label": entry[0], "device": entry[1], "command": entry[2],
                     **({"icon": entry[3]} if len(entry) > 3 else {})}
        row = self.table.rowCount()
        self.table.insertRow(row)
        preview = _Preview(PREVIEW - 8)
        preview.show_glyph(entry.get("icon"))
        self.table.setCellWidget(row, 0, preview)
        self.table.setItem(row, 1, QTableWidgetItem(entry.get("label", "?")))
        does = ("macro, %d step(s)" % len(entry["macro"]) if entry.get("macro")
                else f"{self._device_name(entry.get('device'))} · {entry.get('command')}")
        self.table.setItem(row, 2, QTableWidgetItem(does))
        self.table.item(row, 1).setData(Qt.ItemDataRole.UserRole, entry)

    def _device_name(self, device_id):
        return next((d.get("label", "?") for d in self.devices
                     if d["id"] == device_id), device_id or "?")

    def set_participating(self, ids):
        self._participating = list(ids or [])

    def _add(self):
        dialog = ScreenButtonDialog(
            self.devices, self, participating=getattr(self, "_participating", None))
        if dialog.exec() and dialog.result_data:
            self._add_row(dialog.result_data)

    def _edit(self):
        """Change a command that is already in the list."""
        row = self.table.currentRow()
        if row < 0:
            return
        entry = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        dialog = ScreenButtonDialog(
            self.devices, self, participating=getattr(self, "_participating", None),
            existing=entry)
        if dialog.exec() and dialog.result_data:
            self.table.removeRow(row)
            self._add_row(dialog.result_data)

    def _remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def get_buttons(self):
        return [self.table.item(r, 1).data(Qt.ItemDataRole.UserRole)
                for r in range(self.table.rowCount())]


def _describe(kind, payload):
    if kind == "channel":
        return f"tunes to {payload}"
    if kind == "command":
        return f"sends {payload[1]}" if isinstance(payload, (list, tuple)) else "sends"
    return f"macro, {len(payload)} step(s)"


def _find_image(name):
    """Where a logo might live, so the table can show it rather than its filename."""
    from .. import paths
    from .constants import HERE
    # The application's own folder, not the package's: the two below it were left over
    # from when this code lived at the top level, and never held any logos.
    for folder in (prepared_dir(), paths.root() / "channel_logos", HERE):
        candidate = Path(folder) / str(name)
        if candidate.is_file():
            return candidate
    return None


# The touchscreen draws a favourite's logo into a cell this big. Every logo in every
# real configuration is exactly this, and nothing scales them on the remote.
LOGO_W, LOGO_H = 90, 54
# How much of the cell the artwork should cover, by ink rather than by bounding box, so
# a wide wordmark and a square badge come out looking the same weight beside each other.
_TARGET_FILL = 0.30
_MIN_PADDING = 8


def prepared_dir() -> Path:
    """Where normalised logos are kept, outside the project so it stays portable."""
    from PyQt6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation)
    folder = Path(base or Path.home() / ".afterglow") / "logos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def prepare_logo(src_path) -> Path:
    """Fit a picture to the favourites grid and return the file to put in the config.

    The picture a user picks is whatever they had - a screenshot, a photo, a 2000-pixel
    wordmark off a website. The remote does not resize anything: it draws the file as it
    is, so an oversized one is simply wrong on screen and wastes the config's space.

    This is done when the image is chosen rather than at build time because the build
    layer is deliberately pure standard library, and fitting the artwork needs Pillow.
    """
    import math

    from PIL import Image, ImageStat

    image = Image.open(src_path).convert("RGBA")
    bbox = image.split()[3].getbbox()          # trim transparent margin before fitting
    if bbox:
        image = image.crop(bbox)

    ink = ImageStat.Stat(image.split()[3]).sum[0] / 255.0
    if ink > 0:
        scale = min(math.sqrt(_TARGET_FILL * LOGO_W * LOGO_H / ink),
                    (LOGO_W - 2 * _MIN_PADDING) / image.width,
                    (LOGO_H - 2 * _MIN_PADDING) / image.height)
        image = image.resize((max(1, int(image.width * scale)),
                              max(1, int(image.height * scale))), Image.LANCZOS)

    canvas = Image.new("RGBA", (LOGO_W, LOGO_H), (0, 0, 0, 0))
    canvas.paste(image, ((LOGO_W - image.width) // 2, (LOGO_H - image.height) // 2),
                 image)

    # Always PNG, whatever came in: every logo in every real configuration is one, and
    # the name has to be settled here so the <Image> reference and the file agree.
    out = prepared_dir() / (Path(src_path).stem.replace(" ", "").lower() + ".png")
    canvas.save(out, "PNG")
    return out
