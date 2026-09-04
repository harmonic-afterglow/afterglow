"""Bringing the Linux USB network link up, without ever handling a password.

Windows ships a driver that runs a DHCP server for the remote. Linux does not, so the
remote enumerates as a USB network adapter and then sits there waiting for a lease that
never arrives - see `linux/harmony_net.sh` for what it does about that. Something has to
run that script as root, and this module is about *how it gets asked for*.

## Two ways, and they are not interchangeable

`udev`      Install the rule and the script once. From then on plugging the remote in
            starts a transient systemd unit automatically, with no prompt ever again.
            This is the one worth having, and the only one that survives a reboot.

`session`   Run the script once, now, for as long as Afterglow is open - it is passed
            this process's pid and exits when that goes away. Nothing is written outside
            the running system, and it has to be done again next time.

## Passwords

**This module never sees, asks for, stores or types a password.** Every route works the
same way: a program that is not Afterglow draws the dialog and receives what is typed.

1. `pkexec`, which hands the request to the desktop's own polkit agent.
2. `sudo -A`, where *sudo* runs a system askpass binary and reads the password from its
   stdout. We set `SUDO_ASKPASS` and nothing else; the password never enters this
   process.
3. Neither available: print the command for the user to run in a terminal.

pkexec alone was the first design and it was too strong an assumption. It needs an
*agent* running in the session, and a bare window manager, a session started from a TTY
or a stripped container can all have `pkexec` on `PATH` with nothing listening behind it
- so the chain falls through on "nobody could be asked" while stopping dead on "somebody
said no", which is an answer.

### Why there is no setuid helper, in C or otherwise

The classic answer to this problem is a small setuid-root binary. It is not used here and
should not be added. A setuid program that runs a *shell script* as root is a local
privilege escalation for the whole machine, and the script in question lives under the
user's own data directory, where anything running as that user can rewrite it before the
helper reads it. Hardening that away means pinning the path, dropping the environment,
closing inherited descriptors and auditing every branch of a bash script for root safety
- to save one password prompt that the udev option already removes permanently.

The legitimate C-adjacent version is a polkit action file plus a D-Bus service, which is
more code, still depends on polkit, and buys nothing over option 1 above.

## Duplicates

Two DHCP servers on one interface fight, and the loser is the user's remote. So:

* the rule and the helper are compared against what is installed before either is
  offered, and a matching install means there is nothing to ask about at all;
* the script is not started if the rule is installed, because udev is already doing it;
* the script is not started if it is already running, whoever started it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

# Where `install_harmony_udev.sh` puts things. Duplicated here rather than parsed out of
# the script, because this module has to answer "is it installed?" without running
# anything, and a wrong answer here only ever means one redundant question.
RULE_PATH = Path("/etc/udev/rules.d/99-harmony-usbnet.rules")
HELPER_PATH = Path("/usr/local/bin/harmony_net.sh")

ABSENT, CURRENT, STALE = "absent", "current", "stale"


def applicable() -> bool:
    """Whether any of this means anything on the running platform.

    Only Linux needs it. macOS is unproven either way and Windows has the vendor driver,
    so on both the honest answer is that there is nothing here to offer.
    """
    return sys.platform.startswith("linux")


def _shipped(name: str) -> bytes:
    return paths.helper(name).read_bytes()


def rule_state() -> str:
    """`absent`, `current`, or `stale` - the last meaning an older version is installed.

    Compared by content, not by existence. A rule file left by an earlier release runs
    the wrong script or matches the wrong device, and "the file is there" would report
    that as working while the remote never gets a lease.
    """
    try:
        if RULE_PATH.read_bytes() != _shipped("99-harmony-usbnet.rules"):
            return STALE
        if HELPER_PATH.read_bytes() != _shipped("harmony_net.sh"):
            # The rule is right and points at a helper other than the shipped one.
            return STALE
    except FileNotFoundError:
        return ABSENT
    except OSError:
        # Unreadable is not absent, and offering to reinstall over something that
        # cannot be inspected is worse than staying quiet.
        return CURRENT
    return CURRENT


INSTANCE_LOCK = "instances.lock"
_instance_lock = None


def instance_lock_path():
    return paths.data_dir() / INSTANCE_LOCK


def hold_instance_lock():
    """Mark this process as a running instance, for as long as it lives.

    The session helper runs as root and cannot be signalled by the application, so it
    stops itself when nobody is using it. "Nobody" has to mean *no instance at all* - a
    second window must not lose its link because the first one closed - so every instance
    takes a shared lock on one file and the helper tests for an exclusive one.

    The descriptor is kept in a module global deliberately: closing it would release the
    lock, and letting it be garbage collected would end the link at an arbitrary moment.
    The kernel releases it however the process ends, so a crash needs no cleanup.

    Returns the path, or `None` where this does not apply.
    """
    global _instance_lock
    if not applicable():
        return None
    if _instance_lock is not None:
        return instance_lock_path()
    import fcntl

    path = instance_lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        # Without the lock the helper cannot tell when to stop, so it keeps running -
        # which is the safe direction, and not worth failing a launch over.
        return None
    _instance_lock = handle
    return path


def helper_running() -> bool:
    """Whether a copy of the script is already serving DHCP, whoever started it.

    Covers both routes: a transient `harmony-net-*` unit from the udev rule and a manual
    run, because both show up as the same process. `pgrep` failing for any reason is
    reported as "not running" - the cost of a redundant offer is a prompt the user can
    decline, and the cost of the opposite is two DHCP servers on one interface.
    """
    if not shutil.which("pgrep"):
        return False
    try:
        found = subprocess.run(["pgrep", "-f", "harmony_net.sh"],
                               capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return found.returncode == 0


# Graphical password prompts that ship with desktops, in the order they are tried. Each
# is a *separate program* that draws its own dialog and writes the password to `sudo` on
# its stdout - Afterglow is not in that path and never reads it, which is the whole point.
# Writing our own askpass would put the password back in our address space and is exactly
# what this list exists to avoid.
ASKPASS_COMMANDS = (
    "ksshaskpass",                 # KDE
    "lxqt-openssh-askpass",        # LXQt
    "ssh-askpass",                 # whatever the distribution has aliased
    "x11-ssh-askpass",
    "ssh-askpass-fullscreen",
)
ASKPASS_PATHS = (
    "/usr/lib/ssh/ssh-askpass",
    "/usr/lib/seahorse/ssh-askpass",            # GNOME
    "/usr/libexec/openssh/ssh-askpass",
    "/usr/lib/openssh/gnome-ssh-askpass",
)

# What pkexec says when it cannot find an agent to ask, as opposed to when the user was
# asked and said no. Falling through on the first is right; falling through on the second
# would prompt somebody a second time for something they just declined.
_NO_AGENT = ("no authentication agent", "authentication agent found",
             "cannot open display", "polkit-agent-helper")


def askpass() -> str | None:
    """A password dialog that already exists on this system, or `None`."""
    for name in ASKPASS_COMMANDS:
        found = shutil.which(name)
        if found:
            return found
    for path in ASKPASS_PATHS:
        if Path(path).is_file():
            return path
    return None


def elevators() -> list[tuple[str, list[str], dict]]:
    """Every way this system can raise privileges, best first.

    `(name, argv prefix, extra environment)`.

    pkexec was the only one, and that was too strong an assumption: it needs a polkit
    *agent* running in the session, which plenty of setups do not have - a bare window
    manager, a session started from a TTY, a stripped container. pkexec being installed
    says nothing about whether one is listening.

    `sudo -A` is the fallback, and it is safe for the same reason pkexec is: `sudo` runs
    the askpass program itself and reads the password from *its* stdout. The dialog is a
    system binary, the password goes to sudo, and it never passes through this process.

    Deliberately absent: anything that would have Afterglow collect the password and hand
    it over - a `-S` pipe, a PAM conversation of our own, a text field in our own window.
    A setuid helper is absent for a different reason; see the module docstring.
    """
    found: list[tuple[str, list[str], dict]] = []
    pkexec = shutil.which("pkexec")
    if pkexec:
        found.append(("pkexec", [pkexec], {}))
    sudo, helper = shutil.which("sudo"), askpass()
    if sudo and helper:
        found.append((f"sudo with {Path(helper).name}",
                      [sudo, "-A", "--"], {"SUDO_ASKPASS": helper}))
    return found


HOST_IP = "169.254.1.1"


def host_address_present() -> bool:
    """Whether this machine already holds the address the helper would assign.

    A second signal for "somebody is already doing this", because matching a process
    name only finds *our* script under *our* name. A user with the address configured by
    hand, or through NetworkManager, or by Concordance's own
    `start_concordance_dhcpd.sh`, is equally already served - and starting a second DHCP
    server on that interface would break a setup that was working.

    Reads `/proc/net` via `ip`; absence of `ip` is reported as "not present", which only
    ever means one redundant question.
    """
    if not shutil.which("ip"):
        return False
    try:
        found = subprocess.run(["ip", "-4", "-oneline", "addr"],
                               capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return HOST_IP in (found.stdout or "")


def link_handled() -> bool:
    """Whether anything at all is already bringing the link up."""
    return helper_running() or host_address_present()


def manual_command(action: str) -> str:
    """What to run in a terminal, for when there is no polkit agent to ask."""
    if action == "udev":
        return f"sudo {paths.usable_helper('install_harmony_udev.sh')}"
    return f"sudo {paths.usable_helper('harmony_net.sh')}"


def _no_agent(done) -> bool:
    """Whether an attempt failed for want of somebody to ask, rather than an answer.

    The distinction decides whether trying the next method is helpful or rude. "No agent"
    means nobody was ever asked, so falling through to `sudo -A` gets the user a prompt
    they would otherwise never see. A *declined* prompt is an answer, and re-asking
    through a different mechanism would be badgering someone who just said no.
    """
    text = f"{done.stderr or ''}{done.stdout or ''}".lower()
    return any(marker in text for marker in _NO_AGENT)


def _no_way_to_ask(action: str) -> str:
    return ("Nothing on this system could ask for your password - there is no polkit "
            "agent and no graphical password helper. Run this in a terminal instead, and "
            f"leave it running:\n\n{manual_command(action)}")


def install_rule() -> tuple[bool, str]:
    """Install the udev rule and helper for good. Returns `(ok, what to tell the user)`.

    Tries each available elevator in turn, because "pkexec exists" and "pkexec can ask
    anybody anything" are different facts and only the second one matters.

    The installer is run from the materialised copy rather than from inside the bundle:
    a frozen build's data lives in a directory that is deleted when the process exits, so
    a rule pointing into it would work until the first restart and then silently stop.
    """
    # The installer copies its two siblings out of the directory it is run from, which
    # works because `usable_helper` materialises the whole `linux/` set rather than the
    # one file asked for.
    script = paths.usable_helper("install_harmony_udev.sh")
    attempts = []
    for name, prefix, extra in elevators():
        try:
            done = subprocess.run([*prefix, str(script)], capture_output=True, text=True,
                                  timeout=300, env={**os.environ, **extra})
        except (OSError, subprocess.SubprocessError) as exc:
            attempts.append(f"{name}: {exc}")
            continue
        if done.returncode == 0:
            return True, ("Installed. Unplug the remote and plug it back in - the link "
                          "will come up on its own from now on, with no password.")
        if _no_agent(done):
            attempts.append(f"{name}: nothing available to show a prompt")
            continue
        if done.returncode in (126, 127):
            return False, "Permission was declined, so nothing was changed."
        detail = (done.stderr or done.stdout or "").strip()
        return False, f"The installer failed: {detail or f'exit {done.returncode}'}"
    if attempts:
        return False, _no_way_to_ask("udev") + "\n\nTried: " + "; ".join(attempts)
    return False, _no_way_to_ask("udev")


def start_helper() -> tuple[bool, str]:
    """Run the helper for this session only. Returns `(ok, what to tell the user)`.

    Left running in the background on purpose: the script holds the interface and serves
    DHCP for as long as it lives, so returning from here must not mean killing it. It is
    not waited on and its output is discarded - what matters is visible in `ip addr` and
    in whether the remote answers.
    """
    if rule_state() == CURRENT:
        return False, ("The udev rule is already installed, so the link comes up by "
                       "itself. Starting a second copy would fight the first.")
    if link_handled():
        return False, ("Something is already bringing the link up - either the helper "
                       "or an address configured another way. Starting a second "
                       "DHCP server would break it.")
    available = elevators()
    if not available:
        return False, _no_way_to_ask("session")
    _name, prefix, extra = available[0]
    script = paths.usable_helper("harmony_net.sh")
    lock = hold_instance_lock()
    try:
        # Not waited on, and no failure is visible from here: the process outlives this
        # call by design, and whether it got past the password prompt is only knowable
        # afterwards. That is what the Flash tab's link check is for - it reports the
        # state of the world rather than the exit code of a launcher.
        # See `hold_instance_lock`: the helper stops when the last instance releases
        # this, not when the one that started it exits.
        watch = ["--exit-when-unused", str(lock)] if lock else []
        subprocess.Popen([*prefix, str(script), *watch],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, env={**os.environ, **extra})
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"The helper could not be started: {exc}"
    return True, ("Starting the link. It stops when you close Afterglow, and you will "
                  "be asked again next time unless you install the rule.")


def link_warning(choice: str) -> str | None:
    """What to say before a remote operation, or `None` when there is nothing to say.

    `choice` is what the user answered at startup - `udev`, `session` or `declined`.

    Only for someone who asked for the link and does not have it: they expected this to
    be handled, so its absence is a thing that went wrong and worth a line in the log.
    Somebody who declined made a decision, and repeating it on every button press would
    be nagging them about it.

    A warning and not a refusal. The check is a guess from the outside - a helper started
    some other way, or an interface already configured by hand, both look like "nothing
    running" from here - and being wrong must cost a stale log line rather than a button
    that will not work.
    """
    if not applicable() or choice not in ("udev", "session") or link_handled():
        return None
    if rule_state() == CURRENT:
        # udev starts the helper when the remote appears, so the rule being installed and
        # nothing running usually means the remote is not plugged in at all.
        return ("Warning: the USB link helper is not running. The system rule is "
                "installed, so plugging the remote in should start it - if it is already "
                "plugged in, unplug it and plug it back in.")
    return ("Warning: the USB link helper is not running, so the remote may not get a "
            "network address. Set it up again from Settings \u2192 Set up the USB link.")


def should_ask() -> bool:
    """Whether there is anything worth asking about at all.

    Nothing to offer when the platform does not need it, when the rule is already
    installed and current, or when a helper is already serving. Checked before the
    "don't ask again" preference, so that someone who installs the rule stops being asked
    without having had to opt out of a question that no longer applies.
    """
    return applicable() and rule_state() != CURRENT and not link_handled()
