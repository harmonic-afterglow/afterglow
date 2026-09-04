#!/usr/bin/env python3
"""Learn an IR code from another remote, through the Harmony's own IR receiver.

    sudo linux/harmony_net.sh                       # bring the USB link up first
    python3 tools/learn_ir.py --against yamaha-rx-v3067 --name PowerOn

This drives Concordance's `learn_from_remote()`, which arrived in its most recent
commit (`6ec3fae "Add H900 learning"`). Learning runs over the **USB network link** on
this remote - `CRemoteZ_USBNET::LearnIR` - so `harmony_net.sh` must have run, exactly
as for reading or writing a configuration.

Nothing here writes to the remote. Learning puts it in a listening mode and reads back
what its IR receiver hears; the configuration on the remote is not touched.

## What comes back

`carrier_clock` in hertz, and alternating mark/space durations in microseconds starting
with a mark. The remote derives the carrier from the first burst: the second word it
reports is that burst's carrier *cycle count*, and `frequency = cycles * 1e6 / on_time`
(`remote.cpp _handle_ir_response`).

## How the learned carrier becomes SsIr

Every entry in `SsIr.bin` - the remote's table of recorded waveforms - starts with four
bytes containing a little-endian u32 carrier period in nanoseconds. This is established
by the remote's unstripped `irgen`: the raw `ProcessIrCmd` branch parses the value,
`StartIrfire` passes it to `IrgenInitPwm`, and that function computes
`1,000,000,000 / period` before programming PWM.

Afterglow therefore converts libconcord's measured carrier to the nearest integer period.
An imported entry retains its exact observed period. `--against <library device>` remains
useful for checking that the learned waveform and identified protocol agree.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
LIBRARY = ROOT / "src" / "afterglow" / "library"

from afterglow.concord import (LEARN_SINGLE as LC_LEARN_SINGLE,  # noqa: F401
                               LEARN_STREAM as LC_LEARN_STREAM,
                               NotAvailable, Remote, RemoteError, learned_capture)


class Concord:
    """Thin adapter so this tool reads the same as before `afterglow.concord` existed."""

    def __init__(self, library=None):
        self.remote = Remote()

    def __enter__(self):
        self.remote.__enter__()
        return self

    def __exit__(self, *exc):
        self.remote.__exit__(*exc)

    def identify(self):
        return self.remote.identity()

    def set_mode(self, mode, timeout_ms):
        return self.remote.set_learning_mode(mode, timeout_ms)

    def learn(self):
        return self.remote.learn()


# --- presenting what came back ----------------------------------------------------
def graph(durations: list[int], width_us: int = 400) -> str:
    """A rough ASCII picture, in the spirit of concordance's own output."""
    out = []
    for index, duration in enumerate(durations):
        blocks = max(1, round(duration / width_us))
        out.append(("#" if index % 2 == 0 else ".") * min(blocks, 60))
    return "".join(out)


def to_capture(carrier_hz: int, durations: list[int], name: str) -> dict:
    """The learned signal in Afterglow's capture form."""
    return learned_capture(carrier_hz, durations, name)


def decode_nec(durations: list[int]) -> dict | None:
    """Decode a learned NEC frame into its address and command bytes.

    NEC is a 9000/4500 leader then 32 bits, each a 562 us mark and either a 562 us
    space (0) or a 1687 us space (1), sent least-significant bit first as
    address, ~address, command, ~command. The complements are a built-in check: if
    they hold, the frame was read correctly, which makes this a far stronger test of
    the whole path than the carrier alone.
    """
    if len(durations) < 67:
        return None
    lead_mark, lead_space = durations[0], durations[1]
    if not (7500 < lead_mark < 10500 and 3500 < lead_space < 5500):
        return None
    bits = []
    for index in range(2, 2 + 64, 2):
        space = durations[index + 1]
        if space > 1100:
            bits.append(1)
        elif space > 200:
            bits.append(0)
        else:
            return None
    low, high, command, command_inv = [
        sum(bit << i for i, bit in enumerate(bits[n:n + 8])) for n in range(0, 32, 8)]
    # Two flavours share the same frame. Classic NEC sends an 8-bit address followed by
    # its complement; NEC *extended* uses both bytes as a 16-bit address and does not
    # complement it. Yamaha is extended (address FE 80), so requiring the complement
    # would have rejected a perfectly good frame.
    extended = low ^ high != 0xFF
    return {
        "address": (high << 8) | low if extended else low,
        "address_bytes": (low, high),
        "extended": extended,
        "command": command,
        "command_ok": command ^ command_inv == 0xFF,
        "hex": f"{command:02X}",
    }


def check_against_commands(decoded: dict, device_file: str) -> None:
    """Does the decoded byte match a command this device is supposed to have?"""
    path = LIBRARY / "devices" / f"{device_file.removesuffix('.json')}.json"
    if not path.is_file():
        return
    spec = json.loads(path.read_text())
    wanted = (decoded["address"], decoded["command"])
    hits = [command["name"] for command in spec.get("commands", [])
            if nec_bytes_in(command) == wanted]
    width = 4 if decoded.get("extended") else 2
    print(f"    address 0x{decoded['address']:0{width}X} command "
          f"0x{decoded['hex']} -> ", end="")
    if hits:
        print(f"{', '.join(hits)} - the library has this exact code")
        return
    # The scan can land on a coincidental complement pair in an unrelated code, so
    # judge by the address the device's codes actually agree on, not by every hit.
    import collections
    counts = collections.Counter(pair[0] for pair in
                                 (nec_bytes_in(c) for c in spec.get("commands", []))
                                 if pair)
    common = max(counts.values()) if counts else 0
    addresses = {a for a, n in counts.items() if n > 1 or n == common}
    print("not in this device's codes")
    if addresses and decoded["address"] not in addresses:
        print(f"      Its codes use address(es) "
              f"{', '.join(f'0x{a:04X}' for a in sorted(addresses))} - so this is a "
              "different device, not a missing button.")
    else:
        print("      Same address, unknown command: a button the library entry lacks. "
              "Worth adding.")


def nec_bytes_in(command: dict) -> tuple[int, int] | None:
    """(address, command) out of a stored code, or None if it is not NEC-shaped.

    A device learned from a real config stores the whole `<Code>` string rather than a
    decoded value. The NEC quad sits inside it and identifies itself: two pairs of
    bytes that are each other's complement.
    """
    raw = str(command.get("raw") or command.get("value") or "")
    raw = raw.lower().removeprefix("0x")
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return None
    # Parse by position, not by hunting for complemented pairs. Every stored code has
    # the same shape - a 7-byte prefix, the four protocol bytes, then 01 01 00 - and
    # scanning found the wrong quad: classic NEC complements its address too, so the
    # address pair was read as the command pair one position early.
    if len(data) >= 10 and data[-3:] == b"\x01\x01\x00":
        low, high, cmd, _cmd_inv = data[-7:-3]
        # Classic NEC complements the address; extended uses both bytes as one.
        return (low if low ^ high == 0xFF else (high << 8) | low), cmd
    return None


def compare(carrier_hz: int, durations: list[int], device_file: str) -> bool | None:
    """Measured carrier against the protocol Afterglow already has for that device."""
    path = LIBRARY / "devices" / f"{device_file.removesuffix('.json')}.json"
    if not path.is_file():
        print(f"  (no library device {path.name}; skipping the comparison)")
        return None
    spec = json.loads(path.read_text())
    protocol_path = LIBRARY / "protocols" / spec.get("protocol", "")
    if not protocol_path.is_file():
        print(f"  (device references {spec.get('protocol')!r}, which is not present)")
        return None
    protocol = json.loads(protocol_path.read_text())
    period = protocol.get("carrier_period_ns")
    expected = 1e9 / period if period else None

    agreed = None
    print(f"\n  Library says: {path.name} -> {protocol_path.name}")
    if expected:
        drift = (carrier_hz - expected) / expected * 100
        print(f"    protocol carrier : {expected:9.0f} Hz  (carrier_period_ns {period})")
        print(f"    measured carrier : {carrier_hz:9d} Hz  ({drift:+.1f}%)")
        agreed = abs(drift) < 5
        print("    -> " + ("agree - the protocol's carrier derivation is sound"
                            if agreed else
                            "DISAGREE - one of the two is wrong, and that is the finding"))
    return agreed


def ssir_encoding(carrier_hz: int, agreed: bool | None) -> None:
    """Show the exact SsIr period generated from this measurement."""
    period_ns = round(1_000_000_000 / carrier_hz)
    actual_hz = 1_000_000_000 // period_ns
    print("\n  Harmony PK SsIr encoding")
    print(f"    measured carrier : {carrier_hz} Hz")
    print(f"    carrier period   : {period_ns} ns ({period_ns.to_bytes(4, 'little').hex()})")
    print(f"    irgen integer Hz : {actual_hz} Hz")
    if agreed is False:
        print("    Warning: this disagrees with the comparison protocol; inspect the capture")
        print("    before treating that protocol identification as correct.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="learned",
                        help="what this code is, e.g. PowerOn")
    parser.add_argument("--against", metavar="DEVICE",
                        help="library device file to compare against, "
                             "e.g. yamaha-rx-v3067")
    parser.add_argument("--mode", choices=("single", "stream"), default="single")
    parser.add_argument("--timeout", type=int, default=5000,
                        help="stream mode: how long to record, in ms")
    parser.add_argument("--repeat", type=int, default=1,
                        help="learn this many times, to see how stable it is")
    parser.add_argument("-o", "--out", type=Path,
                        help="write the captures to this JSON file")
    args = parser.parse_args(argv)

    try:
        concord = Concord()
    except NotAvailable as exc:
        print(exc)
        return 1

    captures = []
    with concord as remote:
        try:
            identity = remote.identify()
            print(f"Remote: {identity['mfg']} {identity['model']} "
                  f"(skin {identity['skin']})")
            if identity["skin"] != 61:
                print("  Note: learning modes are documented as Harmony 900 only.")
        except RemoteError as exc:
            print(f"Could not identify the remote: {exc}")
            print("Has `sudo linux/harmony_net.sh` been run?")
            return 1

        mode = LC_LEARN_STREAM if args.mode == "stream" else LC_LEARN_SINGLE
        if remote.set_mode(mode, args.timeout):
            print(f"Learning mode: {args.mode} ({args.timeout} ms)")
        else:
            print("This libconcord has no set_learning_mode; using its default.")

        for attempt in range(1, args.repeat + 1):
            label = args.name if args.repeat == 1 else f"{args.name}-{attempt}"
            print(f"\n--- {label}: point the other remote at the Harmony's front "
                  f"and press the key (5 s)")
            try:
                carrier, durations = remote.learn()
            except RemoteError as exc:
                print(f"  {exc}")
                continue
            if not durations:
                print("  nothing received")
                continue

            print(f"  carrier          : {carrier} Hz")
            print(f"  mark/space pairs : {len(durations) // 2}")
            print(f"  total            : {sum(durations)} us")
            print(f"  first 12         : {durations[:12]}")
            print(f"  {graph(durations[:40])}")
            captures.append(to_capture(carrier, durations, label))

    if not captures:
        print("\nNothing learned.")
        return 1

    carriers = [c["carrier_hz"] for c in captures]
    if len(carriers) > 1:
        print(f"\nCarrier across {len(carriers)} readings: {carriers}")
        print(f"  spread: {max(carriers) - min(carriers)} Hz - a wide spread means the "
              "remote measures rather than reports it")

    # A learned NEC frame carries its own checksum, so decoding it verifies the whole
    # path - carrier, timings and command byte - not just the carrier.
    first = [abs(p) for p in captures[0]["pulses_us"]]
    decoded = decode_nec(first)
    if decoded:
        kind = "NEC extended" if decoded["extended"] else "NEC"
        width = 4 if decoded["extended"] else 2
        print(f"\n  Decoded as {kind}: address 0x{decoded['address']:0{width}X}, "
              f"command 0x{decoded['hex']}")
        print(f"    command complement: "
              f"{'ok' if decoded['command_ok'] else 'FAILED - misread frame'}")
        if args.against:
            check_against_commands(decoded, args.against)

    agreed = compare(carriers[0], captures[0]["pulses_us"],
                     args.against) if args.against else None
    ssir_encoding(carriers[0], agreed)

    if args.out:
        args.out.write_text(json.dumps(captures, indent=2) + "\n")
        print(f"\nWrote {len(captures)} capture(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
