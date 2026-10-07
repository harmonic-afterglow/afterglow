"""When to offer Windows' WinUSB driver for the remote, and the Settings dialog."""
from __future__ import annotations

import threading

from PyQt6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox,
                             QProgressDialog, QPushButton, QVBoxLayout)

from .. import concord, windows_driver
from .constants import USB_DRIVER_ASK_KEY


def _relevant() -> bool:
    return windows_driver.applicable() and concord.has_usb_link()


def _remotes() -> list[dict]:
    try:
        return windows_driver.remotes()
    except Exception:                                              # noqa: BLE001
        return []


def _switch(parent, action: str) -> tuple[bool, str]:
    """Run the elevated switch off the interface thread and report the result."""
    dialog = QProgressDialog("Waiting for Windows to allow the change...", None, 0, 0, parent)
    dialog.setWindowTitle("USB driver")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setCancelButton(None)
    outcome = {}
    loop = QEventLoop()

    def work():
        try:
            outcome["result"] = windows_driver.run_elevated(action)
        except Exception as exc:                                   # noqa: BLE001
            outcome["result"] = (False, f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if not thread.is_alive() else None)
    timer.start(100)
    dialog.show()
    loop.exec()
    timer.stop()
    dialog.close()
    ok, message = outcome["result"]
    if message == windows_driver.CANCELLED:
        QMessageBox.information(parent, "USB driver",
                                "Nothing was changed: Windows did not get permission.")
    elif ok:
        QMessageBox.information(parent, "USB driver", message)
    else:
        QMessageBox.warning(parent, "USB driver", f"The driver was not changed.\n\n{message}")
    return ok, message


def offer_before_operation(parent) -> None:
    """Offer the switch if a remote is not on WinUSB. The operation goes ahead either
    way: Logitech's driver still works through the network path."""
    if not _relevant():
        return
    found = _remotes()
    if not windows_driver.needs_switch(found):
        return
    settings = QSettings("Afterglow", "Afterglow")
    if settings.value(USB_DRIVER_ASK_KEY, False, type=bool):
        return

    on = "; ".join(sorted({windows_driver.describe(remote) for remote in found}))
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Use Windows' USB driver for the remote?")
    box.setText(f"The remote is using {on}.")
    box.setInformativeText(
        "Afterglow talks to the remote over USB through Windows' own WinUSB driver, "
        "which comes with Windows. Switching asks for administrator permission once; "
        "Settings → USB driver switches back at any time.\n\n"
        "If the remote is later plugged into a different USB port, Windows treats it as "
        "a new device and Afterglow asks again.")
    switch = box.addButton("Switch to WinUSB", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
    never = QCheckBox("Don't ask again")
    box.setCheckBox(never)
    box.exec()
    if never.isChecked():
        settings.setValue(USB_DRIVER_ASK_KEY, True)
        settings.sync()
    if box.clickedButton() is switch:
        _switch(parent, windows_driver.INSTALL)


def driver_dialog(parent) -> None:
    """Settings -> USB driver: what the remote is on, and both ways to change it."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("USB driver for the remote")
    layout = QVBoxLayout(dialog)
    state = QLabel()
    state.setWordWrap(True)
    layout.addWidget(state)
    explain = QLabel(
        "Afterglow reaches a Harmony 900, 1000 or 1100 through Windows' own WinUSB "
        "driver. Logitech's driver also works where it loads, more slowly and through a "
        "network adapter. Either change asks for administrator permission.")
    explain.setWordWrap(True)
    explain.setStyleSheet("color: gray;")
    layout.addWidget(explain)
    install = QPushButton("Use Windows' USB driver (WinUSB)")
    restore = QPushButton("Go back to the previous driver")
    layout.addWidget(install)
    layout.addWidget(restore)
    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.rejected.connect(dialog.reject)
    layout.addWidget(close)

    def refresh():
        found = _remotes()
        if not found:
            state.setText("No Harmony 900, 1000 or 1100 is plugged in. Plug the remote in "
                          "and wait for its screen to say it is connected.")
        else:
            state.setText("The remote is using " + "; ".join(
                sorted({windows_driver.describe(remote) for remote in found})) + ".")
        on_winusb = [r for r in found if r["service"].upper() == windows_driver.WINUSB]
        install.setEnabled(bool(found) and len(on_winusb) < len(found))
        restore.setEnabled(bool(on_winusb))

    install.clicked.connect(lambda: (_switch(dialog, windows_driver.INSTALL), refresh()))
    restore.clicked.connect(lambda: (_switch(dialog, windows_driver.RESTORE), refresh()))
    refresh()
    dialog.exec()
