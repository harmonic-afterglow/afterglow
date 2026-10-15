"""Switching the remote to Windows' WinUSB driver: the parts that are not Windows calls.

The SetupAPI half was proven by hand against a Harmony 900 in a Windows 10 VM - from
Logitech's driver, from no driver, back again, and on a second USB port. What is left to
pin here is the logic around it, which runs anywhere.
"""
import json
import sys
from pathlib import Path

import pytest

from afterglow import windows_driver

ROOT = Path(__file__).resolve().parent.parent

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


def test_the_connection_is_named_in_plain_words():
    assert windows_driver.describe(ON_WINUSB) == "direct access"
    assert windows_driver.describe(ON_LOGITECH) == "Logitech's driver"
    assert windows_driver.describe(ON_NOTHING) == "no driver"
    other = windows_driver.describe(dict(ON_NOTHING, service="SomethingElse"))
    assert other == "another driver", "no service names in front of the user"


def test_nothing_is_looked_for_off_windows(monkeypatch):
    monkeypatch.setattr(windows_driver.sys, "platform", "linux")
    assert not windows_driver.applicable()
    assert windows_driver.remotes() == []
    with pytest.raises(windows_driver.DriverError):
        windows_driver.switch(windows_driver.INSTALL)


def _windows(monkeypatch, version):
    monkeypatch.setattr(windows_driver.sys, "platform", "win32")
    monkeypatch.setattr(windows_driver.sys, "getwindowsversion", lambda: version,
                        raising=False)


def test_windows_7_brings_its_own_inf_and_later_windows_do_not(monkeypatch):
    """Windows 7's winusb.inf has no generic entry to select, so it gets Afterglow's."""
    _windows(monkeypatch, (6, 1, 7601))
    assert windows_driver.applicable() and windows_driver.needs_own_inf()
    for later in ((6, 2, 9200), (6, 3, 9600), (10, 0, 19045), (10, 0, 26100)):
        _windows(monkeypatch, later)
        assert windows_driver.applicable() and not windows_driver.needs_own_inf()
    _windows(monkeypatch, (6, 0, 6002))
    assert not windows_driver.applicable(), "no Afterglow runs on Vista"


def test_the_own_inf_binds_every_remote_to_windows_winusb():
    text = windows_driver.own_inf_text()
    for ident in windows_driver.REMOTE_IDS:
        assert text.count(f"USB\\{ident}") == 2, "one model line per architecture"
    assert "Include = winusb.inf" in text and "Needs = WINUSB.NT" in text
    assert "ServiceBinary = %12%\\WinUSB.sys" in text
    assert "[ClassInstall32]" in text, "Windows 7 has no USB devices class"
    assert text.isascii()


def test_the_helper_only_deletes_infs_with_the_marker_afterglow_writes():
    """The marker is how the helper tells our INF from everyone else's. It has to be the
    same string in both places, or "go back" would leave ours installed."""
    source = (ROOT / "packaging" / "windows" / "afterglow-winusb.c").read_text()
    assert f'#define MARKER L"{windows_driver.OWN_INF_MARKER}"' in source
    assert windows_driver.own_inf_text().startswith(windows_driver.OWN_INF_MARKER)


def test_the_helper_matches_the_system_not_the_process(monkeypatch, tmp_path):
    """A 32-bit Afterglow on 64-bit Windows 7 must run the 64-bit helper: Windows
    refuses device installation from a 32-bit process there."""
    for name in ("afterglow-winusb-x86.exe", "afterglow-winusb-x64.exe"):
        (tmp_path / name).write_bytes(b"MZ")
    monkeypatch.setattr(windows_driver.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "x86")
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "AMD64")
    assert windows_driver.helper_path().endswith("afterglow-winusb-x64.exe")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432")
    assert windows_driver.helper_path().endswith("afterglow-winusb-x86.exe")


def test_windows_7_switches_through_the_helper(monkeypatch):
    _windows(monkeypatch, (6, 1, 7601))
    state = {"service": "USBLAN"}
    calls = []
    monkeypatch.setattr(windows_driver, "remotes", lambda: [
        {"id": "USB\\VID_046D&PID_C11F\\1", "service": state["service"], "started": True}])
    monkeypatch.setattr(windows_driver, "_settle", lambda want_winusb: windows_driver.remotes())

    def helper(*arguments):
        calls.append(arguments)
        state["service"] = "WinUSB" if arguments[0] == "install" else "USBLAN"
        return ""
    monkeypatch.setattr(windows_driver, "_run_helper", helper)

    assert windows_driver.switch(windows_driver.INSTALL) == \
        "The remote now uses direct access."
    verb, inf, ident = calls[0]
    assert verb == "install" and ident == "USB\\VID_046D&PID_C11F"
    assert windows_driver.own_inf_text().replace("\n", "\r\n") == \
        open(inf, newline="").read()
    assert windows_driver.switch(windows_driver.INSTALL) == "Nothing needed changing."
    assert windows_driver.switch(windows_driver.RESTORE) == \
        "The remote now uses Logitech's driver."
    assert calls[-1] == ("remove", "USB\\VID_046D&PID_C11F")


def test_a_refused_publisher_prompt_says_how_to_accept_it(monkeypatch, tmp_path):
    helper = tmp_path / "afterglow-winusb-x64.exe"
    helper.write_bytes(b"")
    monkeypatch.setattr(windows_driver, "helper_path", lambda: str(helper))

    class Done:
        returncode, stdout, stderr = 2, "Windows was told not to install the driver.", ""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: Done())
    with pytest.raises(windows_driver.DriverError, match="Install this driver software"):
        windows_driver._run_helper("install", "x.inf", "USB\\VID_046D&PID_C11F")


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
