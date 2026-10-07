"""Switching the remote to Windows' WinUSB driver: the parts that are not Windows calls.

The SetupAPI half was proven by hand against a Harmony 900 in a Windows 10 VM - from
Logitech's driver, from no driver, back again, and on a second USB port. What is left to
pin here is the logic around it, which runs anywhere.
"""
import json
import sys

import pytest

from afterglow import windows_driver

ON_LOGITECH = {"id": r"USB\VID_046D&PID_C11F\1", "service": "RemoteControlUSBLAN",
               "started": True}
ON_WINUSB = {"id": r"USB\VID_046D&PID_C11F\2", "service": "WINUSB", "started": True}
ON_NOTHING = {"id": r"USB\VID_046D&PID_C11F\3", "service": "", "started": False}


def test_only_a_remote_not_on_winusb_needs_switching():
    assert not windows_driver.needs_switch([])
    assert not windows_driver.needs_switch([ON_WINUSB])
    assert windows_driver.needs_switch([ON_LOGITECH])
    assert windows_driver.needs_switch([ON_NOTHING])
    # A second port is a second device to Windows: one switched, one not.
    assert windows_driver.needs_switch([ON_WINUSB, ON_LOGITECH])


def test_each_driver_is_named_for_a_person():
    assert "WinUSB" in windows_driver.describe(ON_WINUSB)
    assert "Logitech" in windows_driver.describe(ON_LOGITECH)
    assert windows_driver.describe(ON_NOTHING) == "no driver"
    assert "SomethingElse" in windows_driver.describe(dict(ON_NOTHING, service="SomethingElse"))


def test_nothing_is_looked_for_off_windows(monkeypatch):
    monkeypatch.setattr(windows_driver.sys, "platform", "linux")
    assert not windows_driver.applicable()
    assert windows_driver.remotes() == []
    with pytest.raises(windows_driver.DriverError):
        windows_driver.switch(windows_driver.INSTALL)


def test_a_frozen_build_starts_itself_again(monkeypatch):
    monkeypatch.setattr(windows_driver.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_driver.sys, "executable", r"C:\Apps\afterglow.exe")
    assert windows_driver._relaunch_command() == (r"C:\Apps\afterglow.exe", "")


def test_a_source_run_carries_its_path_on_the_command_line(monkeypatch):
    # An elevated process does not inherit the environment, so PYTHONPATH would be lost.
    monkeypatch.delattr(windows_driver.sys, "frozen", raising=False)
    executable, parameters = windows_driver._relaunch_command()
    assert executable == sys.executable
    assert "windows_driver import main" in parameters
    assert "sys.path.insert" in parameters


def test_the_elevated_half_reports_through_its_result_file(tmp_path, monkeypatch):
    result = tmp_path / "result.json"
    monkeypatch.setattr(windows_driver, "switch", lambda action: f"did {action}")
    assert windows_driver.main(["--usb-driver", "install", "--result", str(result)]) == 0
    assert json.loads(result.read_text()) == {"ok": True, "message": "did install"}

    def refuse(action):
        raise windows_driver.DriverError("no permission")
    monkeypatch.setattr(windows_driver, "switch", refuse)
    assert windows_driver.main(["--usb-driver", "restore", "--result", str(result)]) == 1
    assert json.loads(result.read_text())["message"] == "no permission"

    assert windows_driver.main(["--usb-driver", "format-c", "--result", str(result)]) == 1
    assert "unknown action" in json.loads(result.read_text())["message"]


def test_the_offer_is_made_only_for_a_remote_that_needs_it(monkeypatch, qapp_or_skip):
    from afterglow.gui import usb_driver

    asked = []
    monkeypatch.setattr(usb_driver, "QMessageBox", lambda *a, **k: asked.append(a)
                        or pytest.fail("asked"))
    monkeypatch.setattr(usb_driver, "_relevant", lambda: True)

    monkeypatch.setattr(usb_driver, "_remotes", lambda: [])
    usb_driver.offer_before_operation(None)            # nothing plugged in
    monkeypatch.setattr(usb_driver, "_remotes", lambda: [ON_WINUSB])
    usb_driver.offer_before_operation(None)            # already switched
    monkeypatch.setattr(usb_driver, "_relevant", lambda: False)
    monkeypatch.setattr(usb_driver, "_remotes", lambda: [ON_LOGITECH])
    usb_driver.offer_before_operation(None)            # not Windows, or upstream libconcord
    assert asked == []
