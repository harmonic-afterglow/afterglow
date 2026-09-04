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

Adding an RF blaster. The MAC of a blaster cannot be *discovered* by the host - there
is no radio in a PC, and the link is Z-Wave, so inclusion is run by the remote's own
radio through `ecnet_mgr`. But the *trigger* is one message, and after inclusion the
remote writes the MAC into `platformconfig/XmlUserRfSetting.xml`.

So adding a blaster is: send `RF:AddReceiver`, have the user press the button on the
blaster, then re-read the configuration. The MAC never travels over this channel - the
events carry only the receiver's label - so the re-read is not optional.

Message names and payloads are taken from the remote's own `app-main.swf`
(`AddReceiver.as`, `BaseRF.as`) in firmware 61.7.5, so they are what the interface
itself sends rather than a guess.
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
    HAO_PORT: "HAO event channel (RF lives here)",
    SETTINGS_PORT: "system settings channel",
    3074: "LTCP command service (libconcord uses this)",
    80: "HTTP - configuration and /system/* endpoints",
}

# Exactly what the remote's own interface sends.
READY = "<Event><Payload><Name>RF:ReadyForRF</Name></Payload></Event>"
ADD_RECEIVER = ("<Event><Payload><Name>RF:AddReceiver</Name><Params></Params>"
                "</Payload></Event>")
LIST_RECEIVERS = ("<Event><Payload><Name>RF:AvailableReceiversQuery</Name><Params>"
                  "</Params></Payload></Event>")
DEVICE_ASSIGNMENTS = ("<Event><Payload><Name>RF:DeviceAssignmentQuery</Name><Params>"
                      "</Params></Payload></Event>")
IDENTIFY_RECEIVER = ("<Event><Payload><Name>RF:IdentifyReceiver</Name><Params>"
                     "<Receiver><ReceiverLabel>{label}</ReceiverLabel></Receiver>"
                     "</Params></Payload></Event>")

# Messages that discard pairing or routing. Not sent by anything here; listed so the
# vocabulary is complete and to make accidental use visible.
DESTRUCTIVE = {
    "RF:ResetNetwork": "forgets every paired receiver",
    "RF:RemoveReceiver": "unpairs one receiver",
    "RF:ResetPortAssignments": "clears which device uses which port",
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
            "Settings \u2192 Set up the USB link.")


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


RF_SETTINGS_URL = "http://{host}/xmluserrfsetting"


def rf_settings(host: str = REMOTE_IP, timeout: float = 4.0) -> str:
    """The remote's RF settings **as they are right now**, over HTTP.

    `data_srv` serves `/usr/data/platformconfig/`, so this is the same
    `XmlUserRfSetting.xml` a configuration dump contains - but live, in under a
    kilobyte, and without reading the whole configuration.

    This is what makes pairing observable. `rfsExportDbAsXML` ends with a
    fire-and-forget `httppost` to this path, and nothing acknowledges that write on
    the event channel, so "a receiver joined" and "the file has been updated" are two
    different moments. Polling here is how the second one is detected instead of
    assumed.
    """
    import urllib.request
    with urllib.request.urlopen(RF_SETTINGS_URL.format(host=host),
                                timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def receivers_now(host: str = REMOTE_IP) -> list[dict]:
    """`[{mac, label, firmware}]` from the live settings, or `[]`.

    Three different situations used to arrive here as one bare `except`, and all three
    were reported as "no receivers": a remote that is not answering, a remote with no
    RF receivers paired, and settings this cannot parse. Only the first two mean an
    empty list. The third is a fault, and saying "no receivers" for it sends someone
    to look at their hardware for a software problem.
    """
    from . import rf
    try:
        settings = rf_settings(host)
    except OSError:
        # Asleep, unplugged, refused, timed out. Ordinary, and the caller's own
        # business - `URLError`, `HTTPError` and `timeout` are all `OSError`.
        return []
    parsed = rf.parse_rf_xml(settings)
    if parsed is None:
        return []                       # documented: no RF receivers are paired
    try:
        return parsed["receivers"]
    except (KeyError, TypeError) as exc:
        print(f"Warning: the remote's RF settings parsed but had no receiver list "
              f"({exc}). Treating it as none paired.")
        return []


def wait_for_new_receiver(before: set, host: str = REMOTE_IP, timeout: float = 20.0,
                          interval: float = 1.0) -> list[dict]:
    """Poll until a receiver appears that was not there before, or time out.

    The pairing event says the radio finished; the settings file is written separately
    and asynchronously. Waiting for the file is what makes the address actually
    readable.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = receivers_now(host)
        fresh = [r for r in current if r.get("mac") not in before]
        if fresh:
            return fresh
        time.sleep(interval)
    return []


RESET_NETWORK = "<Event><Payload><Name>RF:ResetNetwork</Name></Payload></Event>"


def start_pairing(host: str = REMOTE_IP) -> None:
    """Open the inclusion window and return immediately.

    Inclusion runs on the remote for as long as it runs; nothing here has to sit and
    wait for it. The caller watches `receivers_now()` instead, which is what makes a
    countdown and a live list possible.
    """
    with Channel(host) as channel:
        channel.send(READY)                  # -> netmgr_app_ready
        list(channel.events(0.5))
        channel.send(ADD_RECEIVER)           # -> netmgr_add_receiver
        list(channel.events(0.5))


def reset_network(host: str = REMOTE_IP) -> None:
    """Forget every paired blaster. **This is destructive and physical.**

    `rfsResetNetwork` empties `db.Receivers` *and* `db.Map`, and the network manager
    erases the Blackbox pairing table (`devctl erase Blackbox pair table`). So it
    costs, on the remote:

      * every blaster unpaired at the radio - each one has to be paired again by hand;
      * every device-to-base-and-port assignment.

    It is worth doing before a scan when the point is to enumerate what is out there
    from scratch, because a receiver the remote already knows does not announce itself
    as new. It is not something to do casually.
    """
    with Channel(host) as channel:
        channel.send(READY)
        list(channel.events(0.5))
        channel.send(RESET_NETWORK)
        list(channel.events(2.0))


def pair_receiver(host: str = REMOTE_IP, wait: float = 45.0, on_event=None) -> bool:
    """Start inclusion and wait for a receiver to join.

    The user must put the blaster into pairing mode while this runs - Z-Wave inclusion
    needs the device to announce itself, so there is no way to do this from the host
    alone. Returns True if the remote reported a new receiver.

    The caller must then re-read the configuration to learn the MAC.
    """
    with Channel(host) as channel:
        channel.send(READY)                  # -> netmgr_app_ready
        for event in channel.events(1.0):
            if on_event:
                on_event(event_name(event))
        channel.send(ADD_RECEIVER)           # -> netmgr_add_receiver
        found = False
        for event in channel.events(wait):
            name = event_name(event)
            if on_event:
                on_event(name)
            if name == "NewReceiversFound":
                found = True
        return found


def identify_receiver(label: int, host: str = REMOTE_IP) -> None:
    """Make one base announce itself, so bases can be told apart when assigning."""
    with Channel(host) as channel:
        channel.send(READY)
        list(channel.events(0.5))
        channel.send(IDENTIFY_RECEIVER.format(label=int(label)))
        list(channel.events(3.0))
