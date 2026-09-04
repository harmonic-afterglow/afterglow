"""The PyQt6 authoring GUI.

Split by concern so no one file grows unmanageable again:

    constants.py        device/activity types, hard-key slots, the remote's button grid
    rf_routing.py       per-device IR output (front IR vs an RF blaster base + port)
    widgets.py          small shared widgets and helpers
    device_wizard.py    add/edit a device
    activity_wizard.py  add/edit an activity
    tabs.py             the four main tabs
    app.py              the main window and entry point
"""
from .app import MainWindow, main

__all__ = ["MainWindow", "main"]
