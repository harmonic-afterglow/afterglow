"""A shell on the remote, over the USB network link.

The Harmony 900 is a small QNX computer, and it runs a telnet server. Everything this
project has worked out by reading bytes back out of configurations, the remote will
simply tell you: it keeps a system log that records what it was asked to do, what it
sent, and what went wrong. When a configuration makes it freeze and reboot, the log is
the difference between reading the failure and inferring it from a byte diff.

    from afterglow import remote_shell
    print(remote_shell.system_log())

The login is the documented default for this model and is not a secret anybody is
keeping - it is the same on every one of these remotes, reachable only over a
point-to-point link you have physically plugged in.

`telnetlib` was removed from the standard library in 3.13, so the protocol is done here.
Only the negotiation matters: the server offers options, and refusing all of them leaves
a plain line-oriented shell, which is all this needs.
"""
from __future__ import annotations

import socket
import time

REMOTE_IP = "169.254.1.2"        # what linux/harmony_net.sh leases the remote
TELNET_PORT = 23

# Where things actually are, mapped over the link rather than guessed - the first guess
# (/fs/etfs/userdata/platformconfig) was wrong, and /fs/etfs/userdata holds only the
# Z-Wave pairing tables.
CONFIG_DIR = "/usr/data"                    # the unpacked config tree; = /fs/etfs/data
PLATFORM_CACHE = "/fs/etfs/platform/cache"  # a second copy of platformconfig + IR data

# The shell is a small QNX one. `ls`, `cat`, `cp`, `mv`, `ls -l` and shell loops work;
# `grep`, `basename` and most of coreutils do not exist. Read a whole file and filter on
# this side rather than reaching for a pipeline that will not be there.
MISSING_TOOLS = ("grep", "basename", "awk", "sed", "find")

# The documented default for this model. The remote's codename is "vodka"; this is not
# a credential anybody chose, and it cannot be changed from the interface.
DEFAULT_USER = "root"
DEFAULT_PASSWORD = "ethanol"

# Telnet negotiation bytes. We answer every offer with a refusal, which is enough to get
# a line-mode shell out of a server that would otherwise wait for an answer.
IAC, DONT, DO, WONT, WILL, SB, SE = (bytes([b]) for b in (255, 254, 253, 252, 251, 250, 240))


class NotReachable(RuntimeError):
    """The remote did not answer. Usually the USB link is not up."""


def _refuse(data: bytes) -> tuple[bytes, bytes]:
    """Strip telnet commands out of `data`, returning (payload, what to send back).

    Every DO becomes WONT and every WILL becomes DONT: we support nothing, which is
    what makes the stream plain text from then on.
    """
    out, reply, i = bytearray(), bytearray(), 0
    while i < len(data):
        byte = data[i:i + 1]
        if byte != IAC:
            out += byte
            i += 1
            continue
        if i + 1 >= len(data):
            break                                   # split mid-command; drop the tail
        verb = data[i + 1:i + 2]
        if verb == IAC:                             # an escaped 0xFF is literal data
            out += IAC
            i += 2
        elif verb in (DO, DONT, WILL, WONT):
            option = data[i + 2:i + 3]
            if verb == DO:
                reply += IAC + WONT + option
            elif verb == WILL:
                reply += IAC + DONT + option
            i += 3
        elif verb == SB:                            # subnegotiation: skip to SE
            end = data.find(IAC + SE, i)
            i = len(data) if end < 0 else end + 2
        else:
            i += 2
    return bytes(out), bytes(reply)


class Shell:
    """One telnet session. Use it as a context manager."""

    def __init__(self, host: str = REMOTE_IP, timeout: float = 10.0,
                 port: int = TELNET_PORT):
        self.host, self.timeout, self.port = host, timeout, port
        self.sock: socket.socket | None = None

    # connection
    def __enter__(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as exc:
            # Same advice as everywhere else, for the same reason - see `hao._link_advice`.
            from .hao import _link_advice
            raise NotReachable(
                f"no telnet on {self.host}:{self.port} - {exc}."
                f"\n\n{_link_advice()}") from None
        self.sock.settimeout(self.timeout)
        return self

    def __exit__(self, *_exc):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    # the wire
    def _read_until(self, *needles: bytes, deadline: float | None = None) -> bytes:
        """Read until one of `needles` appears, answering negotiation as it arrives."""
        deadline = deadline or (time.monotonic() + self.timeout)
        buffer = bytearray()
        while time.monotonic() < deadline:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            payload, reply = _refuse(chunk)
            if reply:
                self.sock.sendall(reply)
            buffer += payload
            if any(n in buffer for n in needles):
                break
        return bytes(buffer)

    def _send_line(self, text: str) -> None:
        self.sock.sendall(text.encode() + b"\r\n")

    def login(self, user: str = DEFAULT_USER, password: str = DEFAULT_PASSWORD) -> None:
        self._read_until(b"login:", b"ogin:")
        self._send_line(user)
        self._read_until(b"assword:")
        self._send_line(password)
        banner = self._read_until(b"# ", b"$ ")
        if b"incorrect" in banner.lower() or b"ogin:" in banner:
            raise NotReachable(
                f"the remote refused {user!r}. The documented default for this model is "
                f"{DEFAULT_USER}/{DEFAULT_PASSWORD}.")

    def run(self, command: str) -> str:
        """One command, and whatever it printed."""
        # A marker rather than the prompt, because output contains "# " itself and the
        # log certainly does.
        #
        # It is written in two pieces so that the shell joins them but the echoed
        # command line does not contain the joined form. A telnet server echoes what you
        # type, so a marker sent literally appears *before* the output as well as after
        # it, and reading up to the first occurrence returns nothing at all.
        marker = "__afterglow_done__"
        self._send_line(f'{command}; echo "__afterglow""_done__"')
        out = self._read_until(marker.encode()).decode("utf-8", "replace")
        body = out.split(marker)[0]
        # Drop the echoed command line, which the server sends back to us.
        lines = body.splitlines()
        if lines and command[:30] in lines[0]:
            lines = lines[1:]
        return "\n".join(lines).strip("\r\n")


def _with_shell(command: str, host: str = REMOTE_IP, timeout: float = 10.0,
                port: int = TELNET_PORT) -> str:
    with Shell(host, timeout, port) as shell:
        shell.login()
        return shell.run(command)


def system_log(host: str = REMOTE_IP, timeout: float = 20.0,
               port: int = TELNET_PORT) -> str:
    """The remote's own log: key presses, the commands it sent, and any fault.

    This is the thing to read after a configuration makes it misbehave. It records the
    IR it was asked to send, the device and code for each, and the events it exchanged
    with the RF hub.
    """
    return _with_shell("sloginfo", host, timeout, port)


def run(command: str, host: str = REMOTE_IP, timeout: float = 10.0,
        port: int = TELNET_PORT) -> str:
    """Any other command, for looking around."""
    return _with_shell(command, host, timeout, port)


def settings(host: str = REMOTE_IP, timeout: float = 30.0,
             port: int = TELNET_PORT) -> dict:
    """Both copies of every `system_*.dat`, so they can be compared.

    The remote keeps one set under the flashed configuration and another in the platform
    cache. Which of them the interface actually reads is not settled - see the roadmap -
    and this is the thing to look at when a flashed setting does not take effect, or a
    setting changed on the remote goes back after a restart.
    """
    out = {}
    with Shell(host, timeout, port) as shell:
        shell.login()
        for where, folder in (("config", CONFIG_DIR + "/platformconfig"),
                              ("cache", PLATFORM_CACHE)):
            listing = shell.run(f"ls {folder}")
            out[where] = {}
            for name in listing.split():
                if name.startswith("system_") and name.endswith(".dat"):
                    out[where][name] = shell.run(f"cat {folder}/{name}").strip()
    return out


def reachable(host: str = REMOTE_IP, timeout: float = 1.0,
              port: int = TELNET_PORT) -> bool:
    try:
        socket.create_connection((host, port), timeout).close()
        return True
    except OSError:
        return False
