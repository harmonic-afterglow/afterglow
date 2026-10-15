"""`QtSvg` from the chosen binding (see `afterglow.qt`)."""
from . import API

if API == "PyQt5":
    from PyQt5.QtSvg import *  # noqa: F401,F403
else:
    from PyQt6.QtSvg import *  # noqa: F401,F403
