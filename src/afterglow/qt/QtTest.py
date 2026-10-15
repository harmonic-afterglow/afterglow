"""`QtTest` from the chosen binding (see `afterglow.qt`)."""
from . import API

if API == "PyQt5":
    from PyQt5.QtTest import *  # noqa: F401,F403
else:
    from PyQt6.QtTest import *  # noqa: F401,F403
