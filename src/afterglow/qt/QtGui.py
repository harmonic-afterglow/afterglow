"""`QtGui` from the chosen binding (see `afterglow.qt`).

Qt 6 moved QAction, QActionGroup and QShortcut here from QtWidgets, and gave input
events `position()` and `globalPosition()` (floating point) in place of `pos()` and
`globalPos()`; under PyQt5 both are provided under their Qt 6 names."""
from . import API

if API == "PyQt5":
    from PyQt5.QtCore import QPointF
    from PyQt5.QtGui import *  # noqa: F401,F403
    from PyQt5.QtGui import QDropEvent, QHelpEvent, QMouseEvent, QWheelEvent
    from PyQt5.QtWidgets import (  # noqa: F401
        QAction, QActionGroup, QFileSystemModel, QShortcut)

    def _position(event):
        local = getattr(event, "localPos", None)
        return QPointF(local()) if local else QPointF(event.posF())

    def _global(event):
        screen = getattr(event, "screenPos", None)
        return QPointF(screen()) if screen else QPointF(event.globalPos())

    for _cls in (QMouseEvent, QWheelEvent):
        if not hasattr(_cls, "position"):
            _cls.position = _position if _cls is QMouseEvent else (
                lambda event: QPointF(event.posF()))
        if not hasattr(_cls, "globalPosition"):
            _cls.globalPosition = _global if _cls is QMouseEvent else (
                lambda event: QPointF(event.globalPosF()))
    if not hasattr(QDropEvent, "position"):
        QDropEvent.position = lambda event: QPointF(event.posF())
    if not hasattr(QHelpEvent, "position"):
        QHelpEvent.position = lambda event: QPointF(event.pos())
else:
    from PyQt6.QtGui import *  # noqa: F401,F403
