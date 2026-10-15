"""`QtWidgets` from the chosen binding (see `afterglow.qt`).

`QFormLayout.setRowVisible` / `isRowVisible` are Qt 6.4; under PyQt5 a row is hidden by
hiding its label and field, which is what Qt 6 does too."""
from . import API

if API == "PyQt5":
    from PyQt5.QtWidgets import *  # noqa: F401,F403
    from PyQt5.QtWidgets import QFormLayout, QWidget

    def _row(form, row):
        if isinstance(row, int):
            return row
        found, _role = (form.getWidgetPosition(row) if isinstance(row, QWidget)
                        else form.getLayoutPosition(row))
        return found

    def _items(form, row):
        for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole,
                     QFormLayout.ItemRole.SpanningRole):
            item = form.itemAt(row, role)
            if item is not None:
                yield item

    def _set_visible(item, visible):
        if item.widget() is not None:
            item.widget().setVisible(visible)
        elif item.layout() is not None:
            layout = item.layout()
            for index in range(layout.count()):
                _set_visible(layout.itemAt(index), visible)

    def setRowVisible(self, row, visible):
        index = _row(self, row)
        if index is None or index < 0:
            return
        for item in _items(self, index):
            _set_visible(item, visible)

    def isRowVisible(self, row):
        index = _row(self, row)
        if index is None or index < 0:
            return False
        return any(item.widget() is not None and not item.widget().isHidden()
                   for item in _items(self, index))

    if not hasattr(QFormLayout, "setRowVisible"):
        QFormLayout.setRowVisible = setRowVisible
        QFormLayout.isRowVisible = isRowVisible
else:
    from PyQt6.QtWidgets import *  # noqa: F401,F403
