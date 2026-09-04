"""Choosing one of the remote's own button glyphs.

A configuration can put a picture on a button by naming one: `<Icon>myTV</Icon>`. The
names are not free text - they are movie clips in the remote's firmware, so only the ones
it actually contains will draw. There are 87 of them, extracted alongside the device
icons into `icons/buttons/`.

This shows that set and returns the chosen name, which is exactly the string the
configuration stores. A user typing a name into a text box would be guessing at a
vocabulary they cannot see.
"""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QVBoxLayout)

from . import icons


def available() -> list[str]:
    """Every glyph name the remote has, or an empty list if the artwork is missing."""
    folder = icons.ARTWORK / "buttons"
    if not folder.is_dir():
        return []
    return sorted(path.stem for path in folder.glob("*.png"))


class IconPicker(QDialog):
    """Pick a button glyph, or clear the current one."""

    def __init__(self, current: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Button icon")
        self.setModal(True)
        self.chosen = current
        self._cleared = False

        layout = QVBoxLayout(self)
        names = available()
        if not names:
            layout.addWidget(QLabel(
                "No button artwork available.\n\n" + icons.EXTRACT_HINT))
            box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            box.rejected.connect(self.reject)
            layout.addWidget(box)
            return

        self.search = QLineEdit()
        self.search.setPlaceholderText("filter…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(40, 40))
        self.list.setGridSize(QSize(84, 74))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        for name in names:
            item = QListWidgetItem(icons.icon(name, 40), name)
            item.setToolTip(name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.list.addItem(item)
            if name == current:
                self.list.setCurrentItem(item)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        layout.addWidget(self.list)

        clear = QPushButton("No icon")
        clear.clicked.connect(self._clear)
        layout.addWidget(clear)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(520, 460)

    def _filter(self, text):
        text = text.strip().lower()
        for row in range(self.list.count()):
            item = self.list.item(row)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _clear(self):
        self._cleared = True
        self.accept()

    def accept(self):
        if not self._cleared:
            item = self.list.currentItem() if hasattr(self, "list") else None
            self.chosen = item.text() if item else None
        else:
            self.chosen = None
        super().accept()


def choose(current: str | None = None, parent=None) -> tuple[bool, str | None]:
    """(the user confirmed, the chosen name or None)."""
    dialog = IconPicker(current, parent)
    if dialog.exec():
        return True, dialog.chosen
    return False, current
