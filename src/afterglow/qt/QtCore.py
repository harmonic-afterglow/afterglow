"""`QtCore` from the chosen binding (see `afterglow.qt`)."""
from . import API

if API == "PyQt5":
    from PyQt5.QtCore import *  # noqa: F401,F403
    from PyQt5.QtCore import (  # noqa: F401 - not exported by the star import
        PYQT_VERSION_STR, QT_VERSION_STR, pyqtProperty, pyqtSignal, pyqtSlot)
else:
    from PyQt6.QtCore import *  # noqa: F401,F403
    from PyQt6.QtCore import (  # noqa: F401
        PYQT_VERSION_STR, QT_VERSION_STR, pyqtProperty, pyqtSignal, pyqtSlot)
