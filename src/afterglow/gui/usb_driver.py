"""Offering direct access to the remote on Windows, and Settings > Remote connection."""
from __future__ import annotations

import threading

from PyQt6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox,
                             QProgressDialog, QPushButton, QVBoxLayout)

from .. import concord, windows_driver
from .constants import USB_DRIVER_ASK_KEY

WHY_DIRECT = (
    "With direct access Afterglow talks to the remote over USB itself, using a driver "
    "that comes with Windows. It is faster and more reliable than Logitech's driver, "
    "which is no longer maintained, makes the remote a network adapter, and is refused "
    "by many current PCs.")


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
    dialog.setWindowTitle("Remote connection")
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
        QMessageBox.information(parent, "Remote connection",
                                "Nothing was changed: Windows did not get permission.")
    elif ok:
        QMessageBox.information(parent, "Remote connection", message)
    else:
        QMessageBox.warning(parent, "Remote connection",
                            f"Nothing was changed.\n\n{message}")
    return ok, message


def offer_before_operation(parent) -> None:
    """Offer direct access if a remote is not using it. The operation goes ahead either
    way: Logitech's driver still works where it loads."""
    if not _relevant():
        return
    found = _remotes()
    if not windows_driver.needs_switch(found):
        return
    settings = QSettings("Afterglow", "Afterglow")
    if settings.value(USB_DRIVER_ASK_KEY, False, type=bool):
        return

    now = {windows_driver.describe(remote) for remote in found}
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Turn on direct access?")
    if now == {"Logitech's driver"}:
        box.setText("The remote is connected through Logitech's driver.")
    else:
        box.setText("Windows has no working driver for the remote, so Afterglow cannot "
                    "reach it until direct access is turned on.")
    box.setInformativeText(
        f"{WHY_DIRECT}\n\nTurning it on asks for administrator permission once. "
        "Settings \u2192 Remote connection switches back at any time. If the remote is "
        "later plugged into a different USB port, Windows sees a new device and "
        "Afterglow asks again.")
    switch = box.addButton("Turn on direct access", QMessageBox.ButtonRole.AcceptRole)
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
    """Settings > Remote connection: how the remote is connected, and switching."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Remote connection")
    layout = QVBoxLayout(dialog)
    state = QLabel()
    state.setWordWrap(True)
    layout.addWidget(state)
    explain = QLabel(f"{WHY_DIRECT} Either change asks for administrator permission.")
    explain.setWordWrap(True)
    explain.setStyleSheet("color: gray;")
    layout.addWidget(explain)
    install = QPushButton("Use direct access (recommended)")
    restore = QPushButton("Go back to Logitech's driver")
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
            state.setText("The remote is connected through " + " and ".join(
                sorted({windows_driver.describe(remote) for remote in found})) + ".")
        on_winusb = [r for r in found if r["service"].upper() == windows_driver.WINUSB]
        install.setEnabled(bool(found) and len(on_winusb) < len(found))
        restore.setEnabled(bool(on_winusb))

    install.clicked.connect(lambda: (_switch(dialog, windows_driver.INSTALL), refresh()))
    restore.clicked.connect(lambda: (_switch(dialog, windows_driver.RESTORE), refresh()))
    refresh()
    dialog.exec()
