#!/usr/bin/env python3
"""Read the remote's own log, over the USB network link.

    sudo linux/harmony_net.sh              # the remote needs its DHCP lease first
    python3 tools/remote_log.py            # print the log
    python3 tools/remote_log.py -o crash.log
    python3 tools/remote_log.py --run "ls /fs/etfs/device/ecnet/receiver"

The Harmony 900 is a small QNX computer with a telnet server, and it keeps a system log
of what it was asked to do. After a configuration makes it misbehave, that log says what
happened - which device, which code, which event - instead of leaving you to infer it.

A freeze-and-reboot caused by a malformed protocol block was diagnosed by comparing
bytes; the log would have said so directly. Read it before guessing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from afterglow import remote_shell                                   # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=remote_shell.REMOTE_IP,
                        help=f"default {remote_shell.REMOTE_IP}")
    parser.add_argument("-o", "--out", type=Path,
                        help="write to a file as well as printing")
    parser.add_argument("--run", metavar="COMMAND",
                        help="run something else instead of reading the log")
    parser.add_argument("--probe", action="store_true",
                        help="just say whether the remote is reachable")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    if args.probe:
        up = remote_shell.reachable(args.host)
        print(f"  {args.host}:{remote_shell.TELNET_PORT}  "
              f"{'open' if up else 'closed'}   the remote's shell")
        if not up:
            print("\nNothing is listening. Bring the USB link up first:")
            print("  sudo linux/harmony_net.sh")
        return 0 if up else 1

    try:
        if args.run:
            text = remote_shell.run(args.run, args.host, args.timeout)
        else:
            text = remote_shell.system_log(args.host, args.timeout)
    except remote_shell.NotReachable as exc:
        print(exc, file=sys.stderr)
        return 1

    print(text)
    if args.out:
        args.out.write_text(text + "\n")
        print(f"\n[{len(text.splitlines())} lines written to {args.out}]",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
