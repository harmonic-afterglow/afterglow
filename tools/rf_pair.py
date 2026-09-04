#!/usr/bin/env python3
"""Pair an RF blaster by driving the remote's own pairing service from the host.

    sudo linux/harmony_net.sh          # the remote needs its DHCP lease first
    python3 tools/rf_pair.py --probe   # what is reachable?
    python3 tools/rf_pair.py --pair    # trigger pairing, then follow the prompts

## What this is

The Harmony 900's RF extender link is **Z-Wave** (`rfgen-zw`, `ZWAVE_NETWORKSETUP_*`,
node table at `/fs/etfs/userdata/zwavenode.inf`). Pairing is a Z-Wave inclusion, run by
the remote's own radio through `ecnet_mgr` - the host has no radio and cannot scan.

But the *trigger* is just a message. The remote's Flash interface drives pairing by
sending one line of XML to a socket:

    HAOSocketSender   127.0.0.1:1100    <- the HAO (Lua) event channel
    DSSocketSender    127.0.0.1:1600    <- system settings

    <Event><Payload><Name>RF:AddReceiver</Name><Params></Params></Payload></Event>

(from `app-main.swf`, `AddReceiver.as` line 207, decompiled from firmware 61.7.5).

The HAO passes that to the network manager as `netmgr_add_receiver`, inclusion runs,
and `rfsHandlePairMessage` writes the result - MAC, assigned label 1-5, firmware
version - into `platformconfig/XmlUserRfSetting.xml`.

Port 1100 is reachable from the host - confirmed on hardware. The Flash app names
`127.0.0.1` only because it runs on the remote; the listener binds beyond loopback.

## What the host gets back

Not the MAC. The events the remote emits to its own interface carry only the receiver
*label* and a firmware-update flag - `rfsHandlePairMessage` sends `NewReceiversFound`
with `<ReceiverLabel>`, and `RF:AvailableReceiversQuery` returns labels alone. The MAC
is written to the configuration.

So the complete operation is: trigger pairing here, press the button on the blaster,
then **re-read the remote** and import. That last step is what populates the list.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from afterglow.hao import (ADD_RECEIVER, DESTRUCTIVE, IDENTIFY_RECEIVER,  # noqa: F401
                           LIST_RECEIVERS, PORTS, READY, REMOTE_IP, Channel,
                           NotReachable, event_name, identify_receiver, pair_receiver,
                           probe as _probe)


def probe(host: str = REMOTE_IP, timeout: float = 1.0) -> dict:
    """Report which of the remote's services answer, and say what each is."""
    reachable = _probe(host, timeout)
    for port, what in PORTS.items():
        print(f"  {host}:{port:<5} {'open  ' if reachable[port] else 'closed'}  {what}")
    return reachable


def show(config: Path) -> int:
    """The receivers a configuration already knows, straight out of its RF settings."""
    import contextlib
    import io
    import tempfile

    from afterglow import ezhex
    from afterglow.rf import extract_rf

    work = tempfile.mkdtemp()
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(config), work)
    rf = extract_rf(work)
    receivers = (rf or {}).get("receivers") or []
    if not receivers:
        print(f"{config.name}: no RF receivers - everything is on the front emitter.")
        return 1
    print(f"{config.name}: {len(receivers)} receiver(s)\n")
    for receiver in receivers:
        print(f"  Base {receiver.get('label')}   MAC {receiver.get('mac')}   "
              f"firmware {receiver.get('firmware', '?')}")
    assign = (rf or {}).get("assign") or {}
    if assign:
        print("\n  device -> output")
        for device_id, token in sorted(assign.items()):
            print(f"    {device_id} -> {token}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=REMOTE_IP)
    parser.add_argument("--probe", action="store_true",
                        help="just report which services are reachable")
    parser.add_argument("--pair", action="store_true",
                        help="trigger pairing (you must press the blaster's button)")
    parser.add_argument("--identify", type=int, metavar="LABEL",
                        help="make receiver 1-5 announce itself, to tell bases apart")
    parser.add_argument("--wait", type=int, default=45,
                        help="seconds to listen for the pairing to complete")
    parser.add_argument("--show", metavar="EZHEX", type=Path,
                        help="list the receivers a saved configuration knows about")
    args = parser.parse_args(argv)

    if args.show:
        return show(args.show)

    if not (args.probe or args.pair or args.identify):
        parser.print_help()
        return 0

    print(f"Remote at {args.host} (from linux/harmony_net.sh)\n")
    if args.probe or not (args.pair or args.identify):
        reachable = probe(args.host)
        if args.probe:
            print()
            if reachable.get(1100):
                print("Port 1100 is open: pairing can be driven from here (--pair).")
            else:
                print("Port 1100 is closed to the host. Pair on the remote itself:")
                print("  Options -> RF Receiver Settings -> Advanced -> Add")
                print("then re-read the remote and import.")
            return 0

    # Both branches below call afterglow.hao rather than re-implementing its message
    # exchange. They used to open-code it against an older API (`HaoChannel`, `MESSAGES`,
    # `name_of`, `pair`) that no longer exists, so every use of --identify, and the
    # default pairing path, raised NameError before reaching the remote.
    if args.identify:
        try:
            identify_receiver(args.identify, args.host)
        except (OSError, NotReachable) as exc:
            print(f"Could not reach {args.host} - {exc}")
            return 1
        print(f"Asked receiver {args.identify} to announce itself.")
        return 0

    try:
        found = pair_receiver(args.host, args.wait,
                              on_event=lambda name: print(f"  <- {name}"))
    except (OSError, NotReachable) as exc:
        print(f"Could not reach {args.host} - {exc}")
        return 1
    if not found:
        print("\nNo receiver joined. Put the blaster into pairing mode (its button) "
              "while this runs, then try again.")
        return 1
    print("\nA receiver joined. Its MAC is only in the remote's own configuration, so "
          "re-read the remote to pick it up:")
    print("  the Flash tab's Read, then tools/rf_pair.py --show <file>.ezhex")
    return 0


if __name__ == "__main__":
    sys.exit(main())
