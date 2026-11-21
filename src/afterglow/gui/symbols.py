"""The line icons on Afterglow's own buttons and menus: add, the row menu, the arrows.

Buttons said "+ Add Device" and "Add ->", which read as text and look different in every
font. These are Google's Material Symbols (`symbols/`, Apache 2.0, see its NOTICE.md),
drawn in the text colour of the palette they are painted with, so they follow a light or
dark theme and grey out on a disabled button as its label does.
"""
from __future__ import annotations

from functools import lru_cache

from ..qt.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from ..qt.QtGui import QGuiApplication, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from ..qt.QtSvg import QSvgRenderer

from .. import paths


@lru_cache(maxsize=None)
def _source(name: str) -> str:
    path = paths.symbols(f"{name}.svg")
    if not path.is_file():
        raise KeyError(f"no symbol {name!r} in {path.parent}")
    return path.read_text(encoding="utf-8")


def svg(name: str, colour: str) -> bytes:
    """The icon as SVG, filled with ``colour``."""
    return _source(name).replace("<svg ", f'<svg fill="{colour}" ', 1).encode()


class _SymbolEngine(QIconEngine):
    """Draws the icon at whatever size is asked, in the palette's colour for the icon's
    state - sharp on a scaled screen, right in either theme."""

    def __init__(self, name: str, role):
        super().__init__()
        self.name = name
        self.role = role

    def _colour(self, mode) -> str:
        group = (QPalette.ColorGroup.Disabled if mode == QIcon.Mode.Disabled
                 else QPalette.ColorGroup.Active)
        return QGuiApplication.palette().color(group, self.role).name()

    def paint(self, painter: QPainter, rect: QRect, mode, state):
        renderer = QSvgRenderer(QByteArray(svg(self.name, self._colour(mode))))
        side = min(rect.width(), rect.height())
        renderer.render(painter, QRectF(rect.x() + (rect.width() - side) / 2,
                                        rect.y() + (rect.height() - side) / 2, side, side))

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def clone(self):
        return _SymbolEngine(self.name, self.role)


def icon(name: str, role=QPalette.ColorRole.ButtonText) -> QIcon:
    """The named icon (a file in `symbols/`), drawn in ``role``'s colour."""
    _source(name)                         # a missing one is said now, not when drawn
    return QIcon(_SymbolEngine(name, role))
