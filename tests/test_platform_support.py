"""What the tool claims about the platform it is running on.

Only Linux has ever reached a remote. That is not a libconcord limitation - the remote
enumerates as a USB network adapter and then waits for a DHCP server to lease it
169.254.1.2, which Logitech's Windows driver used to provide. Nothing here and nothing in
Concordance automates that off Linux; Concordance's own helper is bash, dnsmasq, nmcli
and udev.

Most people who run this will be on Windows or macOS, so the tool has to say that plainly
before they write to hardware that cannot be recovered from a vendor. It must not simply
fail with a confusing library error, and it must not imply the path is proven.

The buttons deliberately stay enabled: this states what has been tried, it is not a
capability gate, and someone discovering it works on macOS is a report worth having.
"""
import os
import sys
from pathlib import Path

import pytest

from afterglow import concord

ROOT_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "afterglow"


class _StubSettings:
    """UpdateTab saves the settings tab before building; it needs nothing else here."""

    def save(self):
        pass


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_every_supported_platform_says_something_concrete(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    status, explanation = concord.link_support()
    assert status in ("tested", "untested")
    assert len(explanation) > 40, "an explanation that says nothing is not an explanation"


def test_only_a_platform_someone_has_used_claims_to_be_tested(monkeypatch):
    """The claim this file exists to keep honest.

    Flipping one of these to "tested" requires actually reaching a remote from that
    platform. Linux and Windows qualify; Windows needs Logitech's driver installed. macOS
    remains untried, and no MDLM driver exists for it.
    """
    for platform, expected in (("linux", "tested"), ("win32", "tested"),
                               ("darwin", "untested")):
        monkeypatch.setattr(sys, "platform", platform)
        assert concord.link_support()[0] == expected, platform


def test_an_unknown_platform_is_untested_rather_than_a_crash(monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd14")
    status, explanation = concord.link_support()
    assert status == "untested"
    assert explanation


@pytest.mark.parametrize("platform", ["darwin", "freebsd14"])
def test_an_untested_platform_still_says_authoring_works(monkeypatch, platform):
    """The message must not read as "this tool does not work here". The whole format and
    build layer is portable and covered by CI on all three platforms."""
    monkeypatch.setattr(sys, "platform", platform)
    assert "uthoring" in concord.link_support()[1]


@pytest.mark.parametrize("platform,hint", [("linux", "ldconfig"),
                                           ("darwin", "INSTALL.mac"),
                                           ("win32", "libconcord-6.dll")])
def test_the_missing_library_message_fits_the_platform(monkeypatch, platform, hint):
    """`ldconfig` is not advice on Windows."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(concord, "LIBRARY_NAMES", ("definitely-not-a-real-library",))
    monkeypatch.setattr(concord.ctypes.util, "find_library", lambda _name: None)
    with pytest.raises(concord.NotAvailable) as raised:
        concord._load()
    assert hint in str(raised.value)
    assert "author" in str(raised.value), "must say what still works without it"


def test_the_flash_tab_warns_on_an_untested_platform(qapp_or_skip, monkeypatch):
    """The warning has to reach the screen, not just exist in the module.

    macOS, not Windows: Windows is tested, and the tab is deliberately quiet there. The
    one-time driver dialog covers what a Windows user needs.
    """
    from PyQt6.QtWidgets import QLabel

    from afterglow.gui.tabs import UpdateTab

    monkeypatch.setattr(sys, "platform", "darwin")
    tab = UpdateTab({"settings": {}, "devices": [], "activities": []}, _StubSettings())
    shown = " ".join(w.text() for w in tab.findChildren(QLabel))
    assert "untested on this system" in shown


def test_the_flash_tab_stays_quiet_on_linux(qapp_or_skip, monkeypatch):
    from PyQt6.QtWidgets import QLabel

    from afterglow.gui.tabs import UpdateTab

    monkeypatch.setattr(sys, "platform", "linux")
    tab = UpdateTab({"settings": {}, "devices": [], "activities": []}, _StubSettings())
    shown = " ".join(w.text() for w in tab.findChildren(QLabel))
    assert "untested on this system" not in shown


def test_the_link_helper_is_materialised_where_a_user_can_run_it(tmp_path, monkeypatch):
    """The path named in any message has to be one `sudo` can actually run.

    The shipped copy is under `site-packages` for an install and inside a mode-700
    temporary extraction directory for a frozen build, so it is copied beside the user's
    own files.
    """
    from afterglow import paths

    # The helper is the application's own storage, not one of the user's documents, so
    # it lives under `data_dir`. Cached for the process and resolved by other tests in
    # this file first, so redirect the function rather than the environment it reads.
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    script = paths.usable_helper("harmony_net.sh")
    assert script.is_file(), script
    assert tmp_path in script.parents, "it must live beside the application's own files"
    if os.name == "posix":
        # Windows has no execute bit, and a bash script is not runnable there anyway -
        # the helper is a Linux USB-RNDIS workaround. Asserting the mode everywhere just
        # fails on a platform the file does not apply to.
        assert script.stat().st_mode & 0o111, "the script must be executable"

    # The udev installer reads its rule from beside itself, so the set travels whole.
    beside = {path.name for path in script.parent.iterdir()}
    assert "99-harmony-usbnet.rules" in beside, beside


def test_a_bundled_library_is_found_whatever_the_bundler_named_it(tmp_path, monkeypatch):
    """The bundle is searched by pattern, because the name is not ours to predict.

    `LIBRARY_NAMES` lists what a library is *installed* as; a bundler need not use any of
    them. Given `libconcord.so.6.0.0`, PyInstaller may emit the SONAME `libconcord.so.6`
    or keep the full version. Matching the list exactly yields a bundle that carries the
    library and reports it missing.
    """
    from afterglow import concord

    monkeypatch.setattr(concord.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert concord._bundled_candidates() == [], "nothing to find yet"

    # The exact name the runner produced, which is in no list anywhere.
    versioned = tmp_path / "libconcord.so.6.0.0"
    versioned.write_bytes(b"")
    assert concord._bundled_candidates() == [versioned]

    # And the Windows spelling, which shares no prefix convention with the Unix ones.
    for stale in tmp_path.iterdir():
        stale.unlink()
    dll = tmp_path / "libconcord-6.dll"
    dll.write_bytes(b"")
    assert concord._bundled_candidates() == [dll]


def test_windows_is_tested_and_still_says_the_driver_is_required(monkeypatch):
    """Two questions, both answered, and neither collapses into the other.

    Windows reads and flashes remotes, so the status is `tested` and the Flash tab stays
    quiet. It still needs Logitech's driver installed first, which is a separate fact
    that survives the platform being proven: gating the notice on the status would hide
    it the moment Windows started working.

    No URL here. Every copy is an archive this project cannot vouch for, and a link in
    the code rots without anyone noticing - the README owns it, so there is one place to
    correct.
    """
    from afterglow import concord

    monkeypatch.setattr(concord.sys, "platform", "win32")
    status, explanation = concord.link_support()

    assert status == "tested"
    assert concord.needs_driver(), "a working platform can still need a driver"
    assert "Windows 10 and Windows 11" in explanation
    assert "README" in explanation, "point at the one place the download link lives"
    assert "http" not in explanation, "a URL in the code rots; the README owns it"
    assert "README" in explanation, "point at where the download is documented"
    assert "http://" not in explanation and "https://" not in explanation, (
        "no download link: every copy is a mirror this project cannot vouch for")


def test_the_driver_reminder_shows_once_and_not_where_it_is_pointless(qapp_or_skip,
                                                                     monkeypatch,
                                                                     tmp_path):
    """Once per platform, and never where the link already works.

    A warning shown on every launch is one people learn to dismiss without reading, which
    is worse than not showing it - so the answer is recorded and not asked again. It is
    also not a blocker: authoring and building need no driver, and someone editing a
    configuration should not meet a hardware dialog at all.
    """
    from PyQt6.QtCore import QSettings

    from afterglow import concord
    from afterglow.gui import app as gui_app

    shown = []
    monkeypatch.setattr(gui_app.QMessageBox, "exec", lambda self: shown.append(1))
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(gui_app, "QSettings", lambda *a, **k: settings)

    # Where reaching the remote is already proven, there is nothing to say.
    monkeypatch.setattr(concord.sys, "platform", "linux")
    monkeypatch.setattr(gui_app.sys, "platform", "linux")
    gui_app._driver_reminder(None)
    assert shown == [], "a working platform must not be interrupted"

    # Where it is not, say it - once.
    monkeypatch.setattr(concord.sys, "platform", "win32")
    monkeypatch.setattr(gui_app.sys, "platform", "win32")
    gui_app._driver_reminder(None)
    assert len(shown) == 1
    gui_app._driver_reminder(None)
    assert len(shown) == 1, "the reminder must not return on every launch"


def test_the_driver_reminder_shows_once_with_a_way_to_the_readme(qapp_or_skip,
                                                                monkeypatch, tmp_path):
    """Once per platform, never where the link already works, and it opens the project.

    A warning shown on every launch is one people learn to dismiss without reading, which
    is worse than not showing it - so the answer is recorded and not asked again. It is
    also not a blocker: authoring and building need no driver at all.
    """
    from PyQt6.QtCore import QSettings

    from afterglow import HOMEPAGE, concord
    from afterglow.gui import app as gui_app

    opened, clicked = [], []
    monkeypatch.setattr(gui_app.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString())))
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(gui_app, "QSettings", lambda *a, **k: settings)

    def press(self):
        clicked.append(1)
        # Whatever "Open" is on this box: the reminder must not hardcode a button index.
        for button in self.buttons():
            if button.text().strip("&") == "Open":
                self.setClickedButton = None
                self._chosen = button
        return 0

    monkeypatch.setattr(gui_app.QMessageBox, "exec", press)
    monkeypatch.setattr(gui_app.QMessageBox, "clickedButton",
                        lambda self: getattr(self, "_chosen", None))

    # Where reaching the remote already works, there is nothing to interrupt anyone with.
    monkeypatch.setattr(concord.sys, "platform", "linux")
    monkeypatch.setattr(gui_app.sys, "platform", "linux")
    gui_app._driver_reminder(None)
    assert clicked == [], "a working platform must not be interrupted"

    monkeypatch.setattr(concord.sys, "platform", "win32")
    monkeypatch.setattr(gui_app.sys, "platform", "win32")
    gui_app._driver_reminder(None)
    assert len(clicked) == 1
    assert opened == [HOMEPAGE], "Open must reach the project, not a dead vendor page"

    gui_app._driver_reminder(None)
    assert len(clicked) == 1, "the reminder must not return on every launch"


def test_the_homepage_matches_the_packaging_metadata():
    """One source of truth for the project's own URL.

    The interface sends people here and `pyproject.toml` publishes it; two copies drift,
    and the one that rots is the one nobody looks at.
    """
    import tomllib
    from pathlib import Path

    import afterglow

    root = Path(afterglow.__file__).resolve().parents[2]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert data["project"]["urls"]["Homepage"] == afterglow.HOMEPAGE


def test_a_bundled_library_that_refuses_to_load_says_so(tmp_path, monkeypatch, capsys):
    """"Not available" is two different problems, and the loader knows which.

    A library that was never bundled and one that was bundled and would not load look
    identical from outside. On Windows the DLL was there and failed because `libzip` and
    `libhidapi-0` were not beside it - PyInstaller had warned it could not resolve them,
    and the only later symptom is "libconcord: NOT available", which is expensive to
    trace back.
    """
    from afterglow import concord
    from afterglow.selfcheck import concord_check

    monkeypatch.setattr(concord.sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "libconcord-6.dll").write_bytes(b"not a real library")
    # No system fallback, so the bundled failure is the whole story.
    monkeypatch.setattr(concord, "LIBRARY_NAMES", ("definitely-absent.so",))
    monkeypatch.setattr(concord.ctypes.util, "find_library", lambda _name: None)

    assert concord_check() == 1
    printed = capsys.readouterr().out
    assert "found but did not load" in printed, printed
    assert "libconcord-6.dll" in printed, "name the file that failed"


# the Linux USB link offer
#
# Flashing on Linux does not work until something runs `harmony_net.sh` as root, which is
# a bad thing to learn from a failed flash. Afterglow offers to arrange it at startup;
# these cover the three things that offer must not get wrong - asking when there is
# nothing to ask, starting a second DHCP server, and touching a password.
def test_an_installed_rule_means_there_is_nothing_to_ask(monkeypatch, tmp_path):
    """Content, not existence. A rule from an older release runs the wrong helper, and
    "the file is there" would call that working while the remote never gets a lease."""
    from afterglow import paths, usb_link

    rule = tmp_path / "99-harmony-usbnet.rules"
    helper = tmp_path / "harmony_net.sh"
    monkeypatch.setattr(usb_link, "RULE_PATH", rule)
    monkeypatch.setattr(usb_link, "HELPER_PATH", helper)
    monkeypatch.setattr(usb_link, "link_handled", lambda: False)
    monkeypatch.setattr(usb_link.sys, "platform", "linux")

    assert usb_link.rule_state() == usb_link.ABSENT
    assert usb_link.should_ask() is True

    rule.write_bytes(paths.helper("99-harmony-usbnet.rules").read_bytes())
    helper.write_bytes(b"#!/bin/sh\n# an older release\n")
    assert usb_link.rule_state() == usb_link.STALE, \
        "a rule pointing at a helper we did not ship is not current"
    assert usb_link.should_ask() is True, "a stale install still needs replacing"

    helper.write_bytes(paths.helper("harmony_net.sh").read_bytes())
    assert usb_link.rule_state() == usb_link.CURRENT
    assert usb_link.should_ask() is False, "nothing to offer once it is installed"


def test_a_second_dhcp_server_is_never_started(monkeypatch):
    """Two DHCP servers on one interface fight and the remote loses, so the session
    helper refuses both ways it could become a duplicate: udev already doing it, and a
    copy already running - whoever started that copy."""
    from afterglow import usb_link

    # `elevators`, not `elevator`: naming the wrong one leaves the real lookup
    # running, which finds pkexec on a desktop and nothing on a CI runner.
    monkeypatch.setattr(usb_link, "elevators",
                        lambda: [("pkexec", ["/usr/bin/pkexec"], {})])
    started = []
    monkeypatch.setattr(usb_link.subprocess, "Popen",
                        lambda *a, **k: started.append(a))

    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.CURRENT)
    monkeypatch.setattr(usb_link, "helper_running", lambda: False)
    ok, message = usb_link.start_helper()
    assert ok is False and "already installed" in message
    assert started == []

    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.ABSENT)
    monkeypatch.setattr(usb_link, "helper_running", lambda: True)
    monkeypatch.setattr(usb_link, "host_address_present", lambda: False)
    ok, message = usb_link.start_helper()
    assert ok is False and "already" in message
    assert started == []

    # And an address somebody configured another way counts just as much: matching a
    # process name only ever finds our own script under our own name.
    monkeypatch.setattr(usb_link, "helper_running", lambda: False)
    monkeypatch.setattr(usb_link, "host_address_present", lambda: True)
    ok, message = usb_link.start_helper()
    assert ok is False and "already" in message
    assert started == []

    monkeypatch.setattr(usb_link, "host_address_present", lambda: False)
    ok, _ = usb_link.start_helper()
    assert ok is True and len(started) == 1


def test_privilege_is_asked_for_by_the_desktop_and_never_by_us(monkeypatch):
    """The one rule this module exists to keep: no password ever reaches this process.

    Elevation goes through programs that draw their own dialog - `pkexec` via the polkit
    agent, or `sudo -A` via a system askpass, which sudo runs itself and reads the
    password from. Either way the password travels from a dialog we did not draw to a
    program we are not, and never through Afterglow. A password box of our own would be
    the obvious-looking way to do this and it would be wrong twice over: it would put a
    root password in our address space, and it would teach people to type one into any
    window that asks.

    So when there is nothing that can ask, there is deliberately no fallback: the user is
    handed the command to run themselves, in a terminal they control.
    """
    from afterglow import usb_link

    ran = []
    monkeypatch.setattr(usb_link.subprocess, "run",
                        lambda cmd, **k: ran.append((cmd, k.get("env", {}))) or _Done(0))
    monkeypatch.setattr(usb_link, "elevators",
                        lambda: [("pkexec", ["/usr/bin/pkexec"], {})])
    # This machine may genuinely have a helper running, and the duplicate guard would
    # then answer before the part under test here ever runs.
    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.ABSENT)
    monkeypatch.setattr(usb_link, "helper_running", lambda: False)
    monkeypatch.setattr(usb_link, "host_address_present", lambda: False)
    ok, _ = usb_link.install_rule()
    assert ok is True
    assert ran[0][0][0] == "/usr/bin/pkexec"
    assert ran[0][0][-1].endswith("install_harmony_udev.sh")

    monkeypatch.setattr(usb_link, "elevators", list)
    for action in (usb_link.install_rule, usb_link.start_helper):
        ok, message = action()
        assert ok is False
        assert "sudo " in message, "tell them what to run rather than asking for it"
    assert len(ran) == 1, "nothing is run without something that can authorise it"

    # The module must not grow a password field later, either.
    from pathlib import Path

    source = Path(usb_link.__file__).read_text()
    for forbidden in ("QLineEdit", "getpass", "EchoMode", "stdin=", '"-S"'):
        assert forbidden not in source, f"{forbidden} suggests a password path"


def test_a_missing_polkit_agent_falls_through_but_a_refusal_does_not(monkeypatch):
    """pkexec being installed says nothing about whether anything is listening.

    A bare window manager, a session started from a TTY or a stripped container can all
    have `pkexec` on PATH and no agent behind it, which was the original bad assumption:
    one method, treated as the only one. `sudo -A` with a *system* askpass is the second
    try, and it is safe for the same reason the first is.

    The distinction that matters is between "nobody was asked" and "somebody said no".
    Falling through on the first gets the user a prompt they would otherwise never see;
    falling through on the second would badger someone who just declined.
    """
    from afterglow import usb_link

    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.ABSENT)
    monkeypatch.setattr(usb_link, "helper_running", lambda: False)
    monkeypatch.setattr(usb_link, "host_address_present", lambda: False)
    monkeypatch.setattr(usb_link, "elevators", lambda: [
        ("pkexec", ["/usr/bin/pkexec"], {}),
        ("sudo with ksshaskpass", ["/usr/bin/sudo", "-A", "--"],
         {"SUDO_ASKPASS": "/usr/bin/ksshaskpass"}),
    ])

    tried = []

    def no_agent_then_success(cmd, **kwargs):
        tried.append((cmd, kwargs.get("env") or {}))
        if "pkexec" in cmd[0]:
            return _Done(127, stderr="Error: No authentication agent found.")
        return _Done(0)

    monkeypatch.setattr(usb_link.subprocess, "run", no_agent_then_success)
    ok, message = usb_link.install_rule()
    assert ok is True, message
    assert len(tried) == 2, "it must try the askpass route when nobody could be asked"
    # sudo finds the dialog through the environment; the password goes to sudo, not here.
    assert tried[1][1]["SUDO_ASKPASS"] == "/usr/bin/ksshaskpass"

    # A declined prompt is an answer. Stop.
    tried.clear()
    monkeypatch.setattr(usb_link.subprocess, "run",
                        lambda cmd, **k: tried.append(cmd) or _Done(
                            126, stderr="Request dismissed"))
    ok, message = usb_link.install_rule()
    assert ok is False and "declined" in message
    assert len(tried) == 1, "a refusal must not be re-asked through another mechanism"


def test_the_askpass_helper_is_always_one_the_system_already_had(monkeypatch, tmp_path):
    """Every candidate is a binary somebody else installed. Writing our own would hand
    this process the password and undo the entire point of the chain."""
    from afterglow import usb_link

    monkeypatch.setattr(usb_link.shutil, "which", lambda _name: None)
    monkeypatch.setattr(usb_link, "ASKPASS_PATHS", ())
    assert usb_link.askpass() is None
    assert usb_link.elevators() == [], "no pkexec, no sudo, nothing to offer"

    monkeypatch.setattr(usb_link.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in
                        ("sudo", "ksshaskpass") else None)
    found = usb_link.elevators()
    assert [name for name, _, _ in found] == ["sudo with ksshaskpass"]
    assert found[0][1] == ["/usr/bin/sudo", "-A", "--"]
    assert found[0][2] == {"SUDO_ASKPASS": "/usr/bin/ksshaskpass"}


class _Done:
    """A finished `subprocess.run`, with whatever it said on stderr."""

    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_the_offer_is_skipped_when_it_would_be_pointless(qapp_or_skip, monkeypatch,
                                                         tmp_path):
    """`should_ask` is consulted before the preference, on purpose: installing the rule
    has to end the question by itself, without the user having had to tick a box to stop
    being asked something that no longer applies."""
    from PyQt6.QtCore import QSettings

    from afterglow import usb_link
    from afterglow.gui import app as gui_app

    shown = []
    monkeypatch.setattr(gui_app.QDialog, "exec", lambda self: shown.append(1))
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(gui_app, "QSettings", lambda *a, **k: settings)

    monkeypatch.setattr(usb_link, "link_handled", lambda: False)
    monkeypatch.setattr(usb_link, "should_ask", lambda: False)
    gui_app._usb_link_offer(None)
    assert shown == [], "nothing to offer, so no dialog"

    # And once asked, "don't ask again" is honoured even though the offer still applies.
    monkeypatch.setattr(usb_link, "should_ask", lambda: True)
    settings.setValue(gui_app.USB_LINK_ASK_KEY, True)
    gui_app._usb_link_offer(None)
    assert shown == [], "the preference outranks a standing offer"


def test_the_link_warning_reaches_the_log_and_stops_nobody(qapp_or_skip, monkeypatch):
    """Someone who asked for the link and does not have it gets told, on every button.

    Not just Flash: identify and read need the link too, and "check connection" failing
    is exactly when someone goes looking for a cause. Not a block either - the detection
    is inference from outside the helper, so a false positive must cost a stale log line
    rather than a button that refuses to work.

    And nothing at all for someone who declined. They made a decision; repeating it on
    every press is nagging.
    """
    from afterglow import usb_link

    monkeypatch.setattr(usb_link.sys, "platform", "linux")
    monkeypatch.setattr(usb_link, "helper_running", lambda: False)
    monkeypatch.setattr(usb_link, "host_address_present", lambda: False)
    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.ABSENT)

    assert usb_link.link_warning("declined") is None, "they already said no"
    assert usb_link.link_warning("") is None, "never asked, so nothing to reconcile"
    for choice in ("udev", "session"):
        assert "not running" in usb_link.link_warning(choice)

    # An installed rule starts the helper on plug-in, so the advice is to replug rather
    # than to run something.
    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.CURRENT)
    assert "plug it back in" in usb_link.link_warning("udev")

    # Running is running, whoever started it.
    monkeypatch.setattr(usb_link, "helper_running", lambda: True)
    assert usb_link.link_warning("udev") is None

    # Off Linux there is no such helper and the question is meaningless.
    monkeypatch.setattr(usb_link, "helper_running", lambda: False)
    monkeypatch.setattr(usb_link.sys, "platform", "win32")
    assert usb_link.link_warning("udev") is None


def test_the_offer_uses_a_checkbox_for_the_preference_and_radios_for_the_choice(
        qapp_or_skip, monkeypatch, tmp_path):
    """"Don't ask again" is orthogonal to which option was picked, so it cannot be a
    fourth radio button - that would make declining and remembering the same click."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QCheckBox, QDialog, QRadioButton

    from afterglow import usb_link
    from afterglow.gui import app as gui_app

    monkeypatch.setattr(usb_link, "link_handled", lambda: False)
    monkeypatch.setattr(usb_link, "should_ask", lambda: True)
    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.ABSENT)
    monkeypatch.setattr(usb_link, "start_helper", lambda: (True, "started"))
    monkeypatch.setattr(usb_link, "install_rule", lambda: (True, "installed"))
    monkeypatch.setattr(gui_app.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(gui_app, "QSettings", lambda *a, **k: settings)

    seen = {}
    monkeypatch.setattr(QDialog, "exec", lambda self: seen.setdefault("d", self) and 1)
    gui_app._usb_link_offer(None)
    dialog = seen["d"]

    radios = [w for w in dialog.findChildren(QRadioButton)]
    boxes = [w for w in dialog.findChildren(QCheckBox) if not isinstance(w, QRadioButton)]
    assert len(radios) == 3, "three mutually exclusive answers"
    assert [w.text() for w in boxes] == ["Don't ask again"]
    assert boxes[0].autoExclusive() is False, "it must not join the radio group"
    assert boxes[0].isChecked() is False, "never opted in by default"
    # The choice is recorded so the Flash tab can tell "asked for it and lost it" from
    # "said no thanks".
    assert settings.value(gui_app.USB_LINK_CHOICE_KEY) == "udev"


def test_every_flash_tab_button_goes_past_the_link_check(qapp_or_skip, monkeypatch):
    """The wiring, not the wording.

    `link_warning` being right is worth nothing if nothing calls it, and a unit test of
    the function alone passes in exactly that case. This drives the tab's real button and
    reads its real log, with only the worker and the stored preference replaced - the
    method under test is emphatically not stubbed, which was the first mistake here.
    """
    from afterglow import usb_link
    from afterglow.gui import remote_ops
    from afterglow.gui.tabs import UpdateTab

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(usb_link.sys, "platform", "linux")
    monkeypatch.setattr(usb_link, "helper_running", lambda: False)
    monkeypatch.setattr(usb_link, "host_address_present", lambda: False)
    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.ABSENT)

    class Worker:
        def __init__(self, *a, **k):
            self.log = self.progress = self.done = _Signal()

        def start(self):
            pass

    monkeypatch.setattr(remote_ops, "RemoteWorker", Worker)

    class Settings:
        """Answering as though the user asked for the session helper at startup."""

        def __init__(self, *a, **k):
            pass

        def value(self, _key, default=""):
            return "session"

    # The method imports QSettings when it runs, so patching the source module reaches
    # it - and the user's own settings file is never touched by this test.
    monkeypatch.setattr("PyQt6.QtCore.QSettings", Settings)

    tab = UpdateTab({"settings": {}, "devices": [], "activities": []}, _StubSettings())
    tab.check_connection()
    assert "not running" in tab.log_box.toPlainText(), \
        "Check Connection must go past the link check"

    # And nothing for someone who declined, through the same real code path.
    Settings.value = lambda self, _key, default="": "declined"
    tab.log_box.clear()
    tab._run("identify")
    assert tab.log_box.toPlainText().strip() == "", "a declined answer is not nagged at"


class _Signal:
    def connect(self, _slot):
        pass


def test_a_failed_setup_says_so_and_stops_asking_but_leaves_a_way_back(qapp_or_skip,
                                                                      monkeypatch,
                                                                      tmp_path):
    """A dismissed password prompt is not a reason to ask again every launch.

    Repeating an unanswered question on every start is how a dialog becomes something
    people close without reading. So a failure is reported plainly and then the startup
    offer stops - but it cannot be a one-way door, which is why the Settings entry exists
    and why it asks regardless of both the preference and `should_ask`.
    """
    from PyQt6.QtCore import QSettings

    from afterglow import usb_link
    from afterglow.gui import app as gui_app

    monkeypatch.setattr(usb_link, "link_handled", lambda: False)
    monkeypatch.setattr(usb_link, "should_ask", lambda: True)
    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.ABSENT)
    monkeypatch.setattr(usb_link, "install_rule",
                        lambda: (False, "Permission was declined, so nothing was changed."))
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(gui_app, "QSettings", lambda *a, **k: settings)

    told = []
    monkeypatch.setattr(gui_app.QMessageBox, "warning",
                        staticmethod(lambda _p, _t, text: told.append(text)))
    shown = []
    monkeypatch.setattr(gui_app.QDialog, "exec", lambda self: shown.append(self) or 1)

    gui_app._usb_link_offer(None)
    assert len(told) == 1, "a failure has to be reported, not swallowed"
    assert "declined" in told[0]
    assert "Set up the USB link" in told[0], "say where the second attempt lives"
    assert settings.value(gui_app.USB_LINK_ASK_KEY, False, type=bool) is True

    # Startup now stays quiet...
    gui_app._usb_link_offer(None)
    assert len(shown) == 1, "the startup offer must not return after a failure"

    # ...but the menu entry still opens it.
    gui_app._usb_link_offer(None, forced=True)
    assert len(shown) == 2, "Settings must reach the offer whatever was answered before"


def test_macos_needs_the_driver_too_and_says_so(monkeypatch):
    """macOS is untested but not unexplained.

    Logitech's 7.8 release covers macOS as well as Windows, so the driver requirement is
    the same on both. Saying only "untested" would leave a macOS user with nothing to
    try; the honest position is that the driver exists, nobody has confirmed reaching a
    remote with it, and authoring works regardless.
    """
    from afterglow import concord

    monkeypatch.setattr(concord.sys, "platform", "darwin")
    status, explanation = concord.link_support()

    assert status == "untested"
    assert concord.needs_driver(), "the driver is needed whether or not anyone has tried"
    assert "README" in explanation
    assert "uthoring" in explanation, "must not read as 'this tool does not work here'"


def test_the_window_icon_uses_the_drawing_made_for_each_size(qapp_or_skip):
    """Small sizes must be their own drawings, not the large one scaled.

    `QIcon.addFile(path, size)` does not achieve this for SVG sources: Qt renders one file
    and scales it everywhere, so every entry came out as the full-detail mark and the
    16px titlebar icon was an unreadable smudge. The sizes have to be rasterised
    individually and added as pixmaps.

    Compares the icon's 16px entry against the large drawing scaled to 16. They must
    differ, which they only do if the per-size file was used.
    """
    from PyQt6.QtCore import QSize, Qt
    from PyQt6.QtGui import QPainter, QPixmap
    from PyQt6.QtSvg import QSvgRenderer

    from afterglow import paths
    from afterglow.gui.app import _application_icon

    icon = _application_icon()
    assert {(s.width(), s.height()) for s in icon.availableSizes()} >= {
        (16, 16), (22, 22), (24, 24), (32, 32)}, "each small size needs its own entry"

    scaled = QPixmap(QSize(16, 16))
    scaled.fill(Qt.GlobalColor.transparent)
    painter = QPainter(scaled)
    QSvgRenderer(str(paths.branding("afterglow-icon.svg"))).render(painter)
    painter.end()

    assert icon.pixmap(QSize(16, 16)).toImage() != scaled.toImage(), \
        "the 16px icon is the full-detail mark scaled down"


def test_the_window_icon_is_rendered_at_fractional_scale_not_stretched(qapp_or_skip):
    """A fractionally scaled desktop asks for sizes no fixed pixmap set contains.

    At 150% a 16-logical titlebar icon is 24 physical pixels, at 125% it is 20. A `QIcon`
    of fixed pixmaps forces the compositor to resample the nearest one, and that
    resampling is what puts colour fringes along the edges. Rendering from SVG at the
    requested size removes it.

    Checks the pixmap is produced at the physical size and labelled with the ratio, so Qt
    draws it 1:1 rather than stretching it.
    """
    from PyQt6.QtCore import QSize

    from afterglow.gui.app import _application_icon

    icon = _application_icon()
    for scale, expected in ((1.0, 16), (1.25, 20), (1.5, 24), (1.75, 28), (2.0, 32)):
        pixmap = icon.pixmap(QSize(16, 16), scale)
        assert pixmap.width() == expected, f"{scale}x should render {expected}px"
        assert pixmap.devicePixelRatio() == scale, "the ratio must be carried"
        assert not pixmap.isNull()


def test_each_icon_size_comes_from_the_drawing_made_for_it(qapp_or_skip):
    """The per-size drawings must survive on-demand rendering.

    Rendering from one SVG at any size would be simpler and would undo the reason the
    small ones exist: a tapered ray ends in a sub-pixel point and disappears.
    """
    from afterglow.gui.app import _icon_source

    assert _icon_source(16).name == "afterglow-icon-16.svg"
    assert _icon_source(24).name == "afterglow-icon-24.svg"
    assert _icon_source(32).name == "afterglow-icon-32.svg"
    assert _icon_source(256).name == "afterglow-icon.svg"
    # 20 and 28 are what 125% and 175% scaling produce; they must not fall back to the
    # full-detail drawing.
    assert _icon_source(20).name == "afterglow-icon-24.svg"
    assert _icon_source(28).name == "afterglow-icon-32.svg"


def test_the_session_helper_stops_only_when_the_last_instance_goes(monkeypatch,
                                                                   tmp_path):
    """The helper has to stop itself; nothing else can stop it.

    It runs as root through pkexec while Afterglow does not, and a non-root process
    cannot signal a root one - terminating it from the application would mean a second
    password prompt at shutdown. So it watches a lock every instance holds, and stops
    when the last one releases it. Watching the pid that started it would cut the link
    out from under a second window when the first closed.

    The udev route gets no such flag: started from the rule there is nothing to outlive.
    """
    from afterglow import paths, usb_link

    if not usb_link.applicable():
        pytest.skip("the session helper is Linux only")

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(usb_link, "_instance_lock", None)
    launched = []
    monkeypatch.setattr(usb_link.subprocess, "Popen",
                        lambda argv, **kwargs: launched.append(argv))
    monkeypatch.setattr(usb_link, "elevators",
                        lambda: [("pkexec", ["/usr/bin/pkexec"], {})])
    monkeypatch.setattr(usb_link, "rule_state", lambda: usb_link.ABSENT)
    monkeypatch.setattr(usb_link, "link_handled", lambda: False)

    ok, message = usb_link.start_helper()
    assert ok, message
    argv = launched[0]
    assert "--exit-when-unused" in argv, "the helper cannot be stopped without this"
    assert argv[argv.index("--exit-when-unused") + 1] == str(tmp_path / "instances.lock")
    assert "close Afterglow" in message, "say what actually stops it"


def test_the_instance_lock_is_taken_shared_not_exclusive(tmp_path, monkeypatch):
    """The one decision here that is ours: `LOCK_SH`, not `LOCK_EX`.

    An exclusive lock would mean the second Afterglow window could not take it, so it
    would either fail to start or silently not count as an instance - and the helper
    would stop while that window was still using it.

    Deliberately does not assert that a shared lock excludes an exclusive one, or that
    the kernel releases locks on exit. Those are POSIX guarantees; this project does not
    implement them and a test of them would only ever report on the host.
    """
    from afterglow import paths, usb_link

    if not usb_link.applicable():
        pytest.skip("the USB link, and fcntl, are Linux only")

    import fcntl
    import os

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(usb_link, "_instance_lock", None)

    path = usb_link.hold_instance_lock()
    assert path == tmp_path / "instances.lock"

    # A second instance takes the same lock. This only succeeds if the first was shared.
    second = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(second, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:                       # noqa: PERF203
        raise AssertionError("held exclusively; a second window could not start") from None
    finally:
        os.close(second)
        held, usb_link._instance_lock = usb_link._instance_lock, None
        if held is not None:
            os.close(held)


def test_the_helper_script_understands_the_flag_python_passes():
    """A contract between two files in different languages, which nothing else checks.

    `usb_link` passes `--exit-when-unused`; the shell script has to parse that exact
    spelling and act on it in both of its waiting loops. If they drift the helper simply
    never stops, with nothing failing anywhere.
    """
    from afterglow import paths

    script = paths.helper("harmony_net.sh").read_text()
    assert "--exit-when-unused" in script, "the script does not parse the flag passed"
    # Both loops: one waits for the remote to appear, one runs while dnsmasq does.
    assert script.count("nobody_left") >= 3
    # Uncertainty must keep the link up, never end it.
    assert 'command -v flock >/dev/null 2>&1 || return 1' in script


def test_the_version_prefers_the_build_stamp_then_falls_back(monkeypatch, tmp_path):
    """A downloaded executable has to be able to name itself.

    A frozen build carries no `dist-info`, so package metadata cannot answer this, and a
    tag build and a branch build of the same commit have to be distinguishable. The
    bundle workflow writes `_build.py`; everything else falls back to what
    `pyproject.toml` declares.
    """
    import importlib
    import sys as _sys

    import afterglow

    assert afterglow.__version__, "a build must always be able to name itself"

    stamp = ROOT_PACKAGE / "_build.py"
    assert not stamp.exists(), "the stamp is generated; it must not be committed"

    # Without a stamp it reports what pyproject declares.
    import tomllib
    declared = tomllib.loads((ROOT_PACKAGE.parent.parent / "pyproject.toml")
                             .read_text())["project"]["version"]
    assert afterglow._resolve_version() in (declared, afterglow.__version__)

    # With one, the stamp wins.
    stamp.write_text('VERSION = "v9.9.9-test"\n')
    try:
        _sys.modules.pop("afterglow._build", None)
        assert afterglow._resolve_version() == "v9.9.9-test"
    finally:
        stamp.unlink()
        _sys.modules.pop("afterglow._build", None)
    importlib.invalidate_caches()


def test_the_generated_stamp_is_ignored_by_git():
    """A committed stamp would make every later build claim the wrong version."""
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "src/afterglow/_build.py"],
        cwd=ROOT_PACKAGE.parent.parent, capture_output=True)
    assert result.returncode == 0, "src/afterglow/_build.py must be gitignored"
