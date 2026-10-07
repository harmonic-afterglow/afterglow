#!/usr/bin/env python3
"""The remote's own event channel, over the USB network link.

The Harmony runs a Flash interface that drives everything by sending XML to a socket on
itself. Those sockets are **not** loopback-only - they answer over the USB network link
too, which means the host can send exactly what the remote's own interface sends.

    169.254.1.2:1100    HAO event channel - RF, activities, device tests
    169.254.1.2:1600    system settings
    169.254.1.2:3074    LTCP command service (this is what libconcord uses)
    169.254.1.2:80      HTTP: the configuration and the /system/* endpoints

Confirmed on hardware: all four accept connections from the host once
`linux/harmony_net.sh` has given the remote its DHCP lease.

## What this is for

Sending the remote what its own interface would send, and reading its answers. The
messages themselves belong to the firmware family that understands them: RF blaster
pairing for the Harmony 900 family is `backends/harmony_pk/rf_pairing.py`, reached
through the project's backend.
"""
from __future__ import annotations

import re
import socket
import sys
import time

REMOTE_IP = "169.254.1.2"        # what linux/harmony_net.sh leases the remote
HAO_PORT = 1100                  # the Flash interface's HAOSocketSender
SETTINGS_PORT = 1600             # its DSSocketSender
PORTS = {
    HAO_PORT: "HAO event channel",
    SETTINGS_PORT: "system settings channel",
    3074: "LTCP command service (libconcord uses this)",
    80: "HTTP - configuration and /system/* endpoints",
}

def _link_advice() -> str:
    """What to tell someone whose remote stopped answering over the network.

    The shared advice comes first. Naming the helper script would only be correct on
    Linux for a link that was never brought up; when the connection drops part-way
    through an operation it points away from the actual fix.
    """
    from . import concord

    return concord.NOT_CONNECTED_ADVICE + linux_link_note()


def linux_link_note() -> str:
    """The USB link, mentioned only where it exists. Empty everywhere else.

    Separate from `_link_advice` because the post-flash case needs this half without the
    other: there the remote is deliberately rebooting, so "it has not finished connecting
    yet" is the wrong description, while "the network link has to come back up" is still
    true and still Linux-only.

    It no longer prints a command. Afterglow sets the link up itself, and telling somebody
    to run a script we already ran is how a solved problem keeps looking unsolved - the
    only honest pointer now is to the place that can retry it.
    """
    if not sys.platform.startswith("linux"):
        return ""
    return ("\n\nOn Linux the USB network link also has to come back up before the "
            "remote can be reached over the network. If it does not, use "
            "Settings \u2192 Remote connection.")


class NotReachable(RuntimeError):
    """The remote's event channel did not answer."""


def probe(host: str = REMOTE_IP, timeout: float = 1.0) -> dict:
    """`{port: reachable}` for the remote's services."""
    out = {}
    for port in PORTS:
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            out[port] = True
        except OSError:
            out[port] = False
        finally:
            sock.close()
    return out


def event_name(event: str) -> str:
    match = re.search(r"<Name>([^<]+)</Name>", event)
    return match.group(1) if match else "?"


class Channel:
    """The XML event channel. Messages are null-terminated in both directions."""

    def __init__(self, host: str = REMOTE_IP, port: int = HAO_PORT,
                 timeout: float = 2.0):
        self.sock = socket.socket()
        self.sock.settimeout(timeout)
        try:
            self.sock.connect((host, port))
        except OSError as exc:
            raise NotReachable(
                f"{host}:{port} did not answer ({exc}).\n\n{_link_advice()}") from exc
        self.buffer = b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def send(self, message: str) -> None:
        self.sock.sendall(message.encode() + b"\0")

    def events(self, seconds: float):
        """Yield events for a while; the remote pushes them as they happen."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.sock.settimeout(max(0.2, deadline - time.time()))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            self.buffer += chunk
            while b"\0" in self.buffer:
                raw, self.buffer = self.buffer.split(b"\0", 1)
                if raw.strip():
                    yield raw.decode("utf-8", "replace")

    def close(self):
        self.sock.close()
