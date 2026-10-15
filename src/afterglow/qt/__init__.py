"""The Qt binding Afterglow runs on: PyQt6, or PyQt5 for older systems.

Qt 6 needs Windows 10 and macOS 11; Qt 5.15 runs on Windows 7 and macOS 10.13, which
many Harmony owners' computers still are. The interface is written against PyQt6, and
imports Qt only from here - `from afterglow.qt.QtWidgets import QDialog` - so the same
code runs on either. Under PyQt5 the submodules fill in the few Qt 6 names and calls it
uses (QAction in QtGui, QFormLayout.setRowVisible, mouse-event position()).

PyQt6 is used when it is installed; `AFTERGLOW_QT=pyqt5` chooses PyQt5 regardless.
"""
from __future__ import annotations

import importlib
import os


def _choose() -> str:
    wanted = os.environ.get("AFTERGLOW_QT", "").strip().lower()
    order = ["PyQt5", "PyQt6"] if wanted == "pyqt5" else ["PyQt6", "PyQt5"]
    for name in order:
        try:
            importlib.import_module(f"{name}.QtCore")
        except ImportError:
            continue
        return name
    raise ImportError("Afterglow's interface needs PyQt6 (or PyQt5 on older systems)")


API = _choose()
QT5 = API == "PyQt5"


def prepare_application() -> None:
    """What Qt needs before the QApplication exists. Qt 6 scales for high-resolution
    screens by itself; Qt 5 only when asked, and drew everything at half size on a
    Retina display or a Windows screen at 150%."""
    if not QT5:
        return
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QGuiApplication
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    # Qt 5.14+: scale by 1.5 at 150% rather than rounding to 2, as Qt 6 does.
    policy = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
    if policy is not None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy.PassThrough)
