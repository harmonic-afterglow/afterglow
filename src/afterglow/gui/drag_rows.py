"""Reorder a list or a table by dragging its rows by their grip.

Order is something people see - devices and activities in the remote's lists, startup
steps in the order they run, buttons on a screen - and moving a row three places with
Up and Down buttons was three clicks and a squint; the device and activity lists had no
way at all. Qt's own drag and drop moves items but loses whatever widgets sit in the
rows (a combo box, a key button, a whole card), so this does the dragging itself: it
says which row went where, and the owner reorders its own data and redraws.

Each row shows a grip, `grip_pixmap()`, where dragging starts - in a table's row header,
or on a card. A row can be dragged from anywhere that does not take the mouse itself.
"""
from __future__ import annotations

from typing import Callable

from ..qt.QtCore import QEvent, QObject, QPoint, QRectF, Qt, pyqtSlot
from ..qt.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap
from ..qt.QtWidgets import (QAbstractItemView, QApplication, QFrame, QTableWidget,
                             QTableWidgetItem)

EDGE = 18             # how near the top or bottom a drag scrolls the view


def grip_pixmap(size: int = 16, colour: QColor | None = None) -> QPixmap:
    """Six dots, two across and three down: the mark people know means "drag me"."""
    ratio = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour or QColor(140, 140, 140))
    dot = size / 8
    for column in (size * 0.36, size * 0.64):
        for row in (size * 0.25, size * 0.5, size * 0.75):
            painter.drawEllipse(QRectF(column - dot / 2 - 0.5, row - dot / 2, dot, dot))
    painter.end()
    return pixmap


class RowDragger(QObject):
    """Lets `view`'s rows be dragged into a new order; `moved(from_row, to_row)` is
    called once a row is dropped somewhere else, `to_row` counted after it has left."""

    def __init__(self, view: QAbstractItemView, moved: Callable[[int, int], None],
                 movable: Callable[[int], bool] | None = None):
        super().__init__(view)
        self.view = view
        self.moved = moved
        self.movable = movable or (lambda _row: True)
        self._start = None
        self._row = None
        self._dragging = False
        self._line = QFrame(view.viewport())
        self._line.setFixedHeight(2)
        self._line.setStyleSheet("background: palette(highlight);")
        self._line.hide()
        view.viewport().installEventFilter(self)
        if isinstance(view, QTableWidget):
            header = view.verticalHeader()
            header.viewport().installEventFilter(self)
            header.setCursor(Qt.CursorShape.OpenHandCursor)
            header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
            # After the insert has finished: changing header items while the model is
            # still inserting the row aborts Qt.
            # A method of this object, not a lambda: Qt drops the connection when the
            # view and this go, rather than call into a deleted table later.
            view.model().rowsInserted.connect(self._rows_inserted,
                                              Qt.ConnectionType.QueuedConnection)
            self.refresh_grips()

    @pyqtSlot()
    def _rows_inserted(self):
        self.refresh_grips()

    def refresh_grips(self):
        """A grip in every row header instead of the row's number."""
        icon, none = QIcon(grip_pixmap()), QIcon()
        for row in range(self.view.rowCount()):
            item = self.view.verticalHeaderItem(row)
            if item is None or item.text():
                item = QTableWidgetItem("")
                self.view.setVerticalHeaderItem(row, item)
            item.setIcon(icon if self.movable(row) else none)

    def _rows(self) -> int:
        return self.view.model().rowCount()

    def _row_at(self, y) -> int:
        index = self.view.indexAt(QPoint(4, int(y)))
        return index.row() if index.isValid() else -1

    def _gap(self, y) -> tuple[int, int]:
        """The gap a drop at height `y` lands in, and where to draw it."""
        row = self._row_at(y)
        if row < 0:
            last = self._rows() - 1
            if last < 0:
                return 0, 0
            first = self.view.visualRect(self.view.model().index(0, 0))
            if y < first.top():
                return 0, first.top()
            bottom = self.view.visualRect(self.view.model().index(last, 0)).bottom()
            return self._rows(), bottom
        rect = self.view.visualRect(self.view.model().index(row, 0))
        if y < rect.center().y():
            return row, rect.top()
        return row + 1, rect.bottom()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and \
                event.button() == Qt.MouseButton.LeftButton:
            row = self._row_at(event.position().y())
            if row >= 0 and self.movable(row):
                self._start, self._row = event.position(), row
            return False
        if kind == QEvent.Type.MouseMove and self._row is not None and \
                event.buttons() & Qt.MouseButton.LeftButton:
            y = event.position().y()
            if not self._dragging:
                if (event.position() - self._start).manhattanLength() < \
                        QApplication.startDragDistance():
                    return False
                self._dragging = True
                QApplication.setOverrideCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            self._scroll(y)
            _gap, at = self._gap(y)
            self._line.setGeometry(0, max(0, at - 1), self.view.viewport().width(), 2)
            self._line.show()
            self._line.raise_()
            return True
        if kind == QEvent.Type.MouseButtonRelease and self._row is not None:
            dragged, row = self._dragging, self._row
            self._finish()
            if dragged:
                gap, _at = self._gap(event.position().y())
                target = gap - 1 if gap > row else gap
                if target != row and 0 <= target < self._rows():
                    self.moved(row, target)
                return True
        return False

    def _scroll(self, y):
        bar = self.view.verticalScrollBar()
        if y < EDGE:
            bar.setValue(bar.value() - bar.singleStep())
        elif y > self.view.viewport().height() - EDGE:
            bar.setValue(bar.value() + bar.singleStep())

    def _finish(self):
        if self._dragging:
            QApplication.restoreOverrideCursor()
        self._dragging = False
        self._start = self._row = None
        self._line.hide()


def moved_list(items: list, from_row: int, to_row: int) -> list:
    """`items` with the one at `from_row` moved to `to_row`."""
    items = list(items)
    items.insert(to_row, items.pop(from_row))
    return items


def move_table_row(table: QTableWidget, from_row: int, to_row: int) -> None:
    """Move a table row whose cells are all items - no widgets in it - and select it."""
    items = [table.takeItem(from_row, column) for column in range(table.columnCount())]
    table.removeRow(from_row)
    table.insertRow(to_row)
    for column, item in enumerate(items):
        if item is not None:
            table.setItem(to_row, column, item)
    table.selectRow(to_row)
