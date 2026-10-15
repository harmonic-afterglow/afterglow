"""A page of buttons laid out the way the remote's screen lays them out.

A list says which buttons a device or an activity has and in what order; it does not say
which page a button lands on, or that a gap leaves a hole. This shows one page at a time
in the remote's own grid (`RemoteProfile.screen_grid`), filled row by row, with plain
buttons and arrows to turn the page.
"""
from __future__ import annotations

from ..qt.QtCore import QSize, Qt, pyqtSignal
from ..qt.QtGui import QIcon
from ..qt.QtWidgets import (QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QToolButton, QVBoxLayout)

from .icons import pixmap as glyph_pixmap

ICON = 32


class ScreenPreview(QGroupBox):
    """Shows `buttons` - each `(text, icon name or None)`, or None for a gap - on pages of
    `columns` x `rows`. `picked(index)` says which button was clicked."""

    picked = pyqtSignal(int)

    def __init__(self, columns: int, rows: int, title: str = "", parent=None):
        super().__init__(title, parent)
        self.columns, self.rows = columns, rows
        self.buttons: list = []
        self.page = 0
        self.selected = -1
        self.setToolTip("How the remote lays out this page. Click a button to pick it in "
                        "the list.")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self._cells = []
        for slot in range(columns * rows):
            cell = QPushButton()
            cell.setCheckable(True)
            cell.setFixedSize(QSize(96, 64))
            cell.setIconSize(QSize(ICON, ICON))
            cell.clicked.connect(lambda _checked, slot=slot: self._clicked(slot))
            grid.addWidget(cell, slot // columns, slot % columns)
            self._cells.append(cell)
        layout.addLayout(grid)

        turn = QHBoxLayout()
        self.back = QToolButton()
        self.back.setArrowType(Qt.ArrowType.LeftArrow)
        self.back.clicked.connect(lambda: self._turn(-1))
        self.count = QLabel()
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next = QToolButton()
        self.next.setArrowType(Qt.ArrowType.RightArrow)
        self.next.clicked.connect(lambda: self._turn(1))
        turn.addWidget(self.back)
        turn.addWidget(self.count, 1)
        turn.addWidget(self.next)
        layout.addLayout(turn)
        self._show()

    def let_scale(self):
        """Grow and shrink with whatever holds it, rather than keep a fixed size - for a
        preview drawn inside a picture of the whole screen."""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        for cell in self._cells:
            cell.setMinimumSize(QSize(8, 8))
            cell.setMaximumSize(QSize(16777215, 16777215))
            cell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    @property
    def per_page(self) -> int:
        return self.columns * self.rows

    def pages(self) -> int:
        return max(1, -(-len(self.buttons) // self.per_page))

    def set_buttons(self, buttons: list, title: str | None = None):
        self.buttons = list(buttons)
        if title is not None:
            self.setTitle(title)
        self.page = min(self.page, self.pages() - 1)
        self._show()

    def select(self, index: int):
        """Show the button at `index` picked, turning to its page."""
        self.selected = index
        if 0 <= index < len(self.buttons):
            self.page = index // self.per_page
        self._show()

    def _show(self):
        first = self.page * self.per_page
        for slot, cell in enumerate(self._cells):
            index = first + slot
            button = self.buttons[index] if index < len(self.buttons) else None
            # a gap is a place the remote leaves empty: an empty button that does
            # nothing. Past the last button there is no place at all, only room.
            cell.setFlat(index >= len(self.buttons))
            cell.setEnabled(button is not None)
            cell.setChecked(index == self.selected)
            text, icon = button if button is not None else ("", None)
            glyph = glyph_pixmap(icon, ICON) if icon else None
            cell.setIcon(QIcon(glyph) if glyph is not None and not glyph.isNull()
                         else QIcon())
            cell.setText(text or "")
            cell.setToolTip("An empty place" if button is None else (text or icon or ""))
        self.count.setText(f"{self.page + 1}/{self.pages()}")
        self.back.setEnabled(self.pages() > 1)
        self.next.setEnabled(self.pages() > 1)

    def _turn(self, step: int):
        self.page = (self.page + step) % self.pages()
        self._show()

    def _clicked(self, slot: int):
        index = self.page * self.per_page + slot
        self.select(index)
        self.picked.emit(index)
