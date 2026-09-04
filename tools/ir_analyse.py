#!/usr/bin/env python3
"""Compare what a remote actually emitted against what Afterglow predicted.

    python3 tools/ir_analyse.py listen                       # just show frames
    python3 tools/ir_analyse.py expect sony12 --code 0x12345 # gate against a protocol
    python3 tools/ir_analyse.py expect nec1 --address 0x7A --command 0x1A
    python3 tools/ir_analyse.py replay capture.txt expect jvc16 --code 0x1234

## Why this exists

Seven of the twelve shipped protocol families are `vm-validated`: proved only against
Afterglow's port of the remote's own carrier VM. If that port carries a systematic error,
the emitter and the VM agree with each other and are both wrong, and no amount of software
testing notices - the gate is one of the two things being compared. Generic native
emission would build ~772,000 commands on top of that gate.

The way out is to measure the emission with something sharing no code with either side.
`../ir_bench/ir_bench.ino` is that instrument - it lives outside this repository
because it is a generic IR probe with no Afterglow knowledge in it. This is its
host half. It renders the
portable definition independently, aligns it against the captured frame, and reports the
per-pulse error - so a disagreement points at a pulse index, not at a mood.

## What a pass here does and does not mean

It means the remote emitted the mark/space structure the portable definition describes.

It does **not** verify the carrier: a demodulator strips it, so a 40 kHz Sony frame and a
38 kHz NEC frame with equal timings are indistinguishable to this tool. Carrier is
measured separately by `tools/learn_ir.py` through the remote's own learning hardware.
Neither does it prove an appliance responds; that is a further, weaker claim about
emitter strength and angle.

Read the tolerances in `--help` before promoting anything in `mappings.py` from
`vm-validated` to `hardware-anchored` on the strength of a run here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ir_protocol  # noqa: E402

# Modem-control ioctls, for asserting DTR on a native-USB board.
TIOCMGET, TIOCMSET = 0x5415, 0x5418
TIOCM_DTR, TIOCM_RTS = 0x002, 0x004

START_RE = re.compile(r"#FRAME idx=(?P<idx>\d+)")
END_RE = re.compile(
    r"#END pulses=(?P<pulses>\d+) gap_us=(?P<gap>\d+) overflow=(?P<overflow>\d+)")

# A TSOP demodulator stretches marks and shortens the following space by a similar
# amount - typically 50-150 us, and it is a property of the part, not of the emission.
# So absolute timing is judged loosely while *structure* is judged exactly: a wrong bit
# count or a missing frame is a real defect, 80 us on a mark is the sensor.
DEFAULT_ABSOLUTE_US = 200
DEFAULT_RELATIVE = 0.12

# The probe closes a frame after this much idle line and reports that as `gap_us`. It is
# therefore a *threshold*, never a measurement: a real lead-out longer than this is
# indistinguishable from one exactly this long. Parsed from the probe's banner when
# present so the two cannot drift.
DEFAULT_IDLE_GAP_US = 25000
BANNER_GAP_RE = re.compile(r"idle_gap_us=(\d+)")


def parse_stream(lines):
    """Yield ``(info, pulses)`` for each complete frame in an ir_bench stream.

    The probe streams a frame as it measures it and puts the pulse count and terminating
    gap on the closing line, because holding the frame in a second buffer would not fit
    in an AVR's RAM. So a frame is only complete at ``#END``; anything still open when
    the stream ends is a truncated capture and is dropped rather than half-reported.
    """
    info = None
    pulses: list[int] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        start = START_RE.match(line)
        if start:
            info, pulses = start.groupdict(), []
            continue
        end = END_RE.match(line)
        if end:
            if info is not None:
                info.update(end.groupdict())
                declared = int(info["pulses"])
                if declared != len(pulses):
                    # The probe counts what it measured; we count what arrived. A
                    # mismatch means serial loss, which must not be mistaken for the
                    # emitter sending the wrong number of pulses.
                    info["truncated"] = str(declared)
                yield info, pulses
            info, pulses = None, []
            continue
        if line.startswith("#"):
            # Banner and diagnostics are not frames, but silently dropping them makes a
            # dead probe indistinguishable from an idle one on a first run.
            yield {"note": line}, []
            continue
        if info is None:
            continue
        for token in line.split():
            try:
                pulses.append(int(token))
            except ValueError:
                pass


def find_port(explicit: str | None) -> str:
    """Locate the probe, because its device node moves.

    A USB-CDC board re-enumerates on every reset - and reflashing it is a reset - so it
    lands on ttyACM0 one minute and ttyACM1 the next. Hardcoding a path turns a working
    rig into "does not exist", which is not a useful thing to tell someone holding a
    remote control.
    """
    if explicit:
        return explicit
    candidates = sorted(
        [str(path) for path in Path("/dev").glob("ttyACM*")]
        + [str(path) for path in Path("/dev").glob("ttyUSB*")],
        key=lambda name: Path(name).stat().st_mtime if Path(name).exists() else 0)
    if not candidates:
        raise SystemExit(
            "no /dev/ttyACM* or /dev/ttyUSB* found - is the probe plugged in?")
    chosen = candidates[-1]
    if len(candidates) > 1:
        print(f"# several serial devices present {candidates}; using {chosen}. "
              "Pass --port to choose.")
    return chosen


def serial_lines(port: str, baud: int, idle_gap_us: int | None = None):
    """Yield lines from the probe, with or without pyserial.

    pyserial is the portable answer, but it is a dependency this project does not have
    and does not need on Linux: a CDC-ACM device is a character device, so putting the
    line discipline in raw mode with `stty` and reading it as a file works exactly as
    well. Native-USB boards ignore the baud rate anyway - it is negotiated by USB, not by
    the UART - so the setting only matters for a real serial adapter.
    """
    try:
        import serial                                   # pyserial, if present
    except ImportError:
        serial = None

    if serial is not None:
        handle = serial.Serial(port, baud, timeout=1)
        time.sleep(0.2)
        while True:
            raw = handle.readline()
            if raw:
                yield raw.decode("utf-8", "replace")
        return

    if not Path(port).exists():
        raise SystemExit(f"{port} does not exist - is the probe plugged in?")
    if os.name != "posix":
        raise SystemExit(
            f"reading {port} without pyserial only works on POSIX; "
            "pip install pyserial, or capture to a file and use --replay")
    # -echo matters: without it anything the host writes is echoed back and parsed as
    # if the probe had said it. -hupcl keeps the board from resetting on close.
    result = subprocess.run(
        ["stty", "-F", port, "raw", "-echo", "-hupcl", str(baud)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"could not configure {port}: {result.stderr.strip()}")
    # One file descriptor, opened read/write and held for the whole session.
    #
    # This used to open the port for writing, close it, then reopen it for reading. On a
    # native-USB board that is fatal and looks exactly like dead hardware: the 32U4's
    # `Serial` is only true while the host asserts DTR, closing the write handle drops it,
    # and everything the sketch prints after that is discarded. The probe answered `h`
    # with total silence for two sessions before this was found - and a silent probe is
    # indistinguishable from a remote that is not transmitting, which is the one confusion
    # this tool exists to prevent.
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        # Assert DTR/RTS explicitly. `clocal` is set above so the open does not block on
        # carrier, and a board that waits for DTR would otherwise never start talking.
        # POSIX only, and imported here rather than at module scope: this file is also
        # read by tests on Windows, where `fcntl` does not exist and the import alone
        # would fail before any probe was attempted.
        import fcntl

        bits = struct.unpack("I", fcntl.ioctl(fd, TIOCMGET, struct.pack("I", 0)))[0]
        fcntl.ioctl(fd, TIOCMSET,
                    struct.pack("I", bits | TIOCM_DTR | TIOCM_RTS))
        # The board enumerates before the sketch is ready to read commands.
        time.sleep(2.0)
        if idle_gap_us is not None:
            os.write(fd, f"g{int(idle_gap_us)}".encode())
            time.sleep(0.2)
        # 'h' reprints the banner. Without it a silent probe and a dead one look the
        # same, and the first thing anyone needs to know is which they have.
        os.write(fd, b"h")
    except OSError:
        pass

    pending = b""
    try:
        while True:
            try:
                chunk = os.read(fd, 512)
            except BlockingIOError:
                time.sleep(0.02)
                continue
            if not chunk:
                time.sleep(0.02)
                continue
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                yield line.decode("utf-8", "replace")
    finally:
        os.close(fd)


def expected_pulses(protocol_id: str, parameters: dict, phase: str,
                    library=ir_protocol.LIBRARY) -> list[int]:
    """Render the portable definition, independently of any backend."""
    definition = ir_protocol.protocol(protocol_id, library)
    state = ir_protocol.initial_state(definition)
    pulses, _state = ir_protocol.transmission(
        definition, parameters, phase, state=state)
    return list(pulses or [])


def split_trailing_gap(expected: list[int], actual: list[int], gap_us: int):
    """Account for the probe reporting a frame's final space in its header.

    `ir_bench` ends a frame on an idle gap and reports that gap separately, because its
    length depends on when the *next* frame arrives, not on the emission. A rendered
    transmission carries the lead-out as its last pulse. Comparing the two directly
    therefore reports "one pulse short" on every correct capture, which would train
    whoever runs this to ignore the pulse count - the one check that catches a wrong bit
    count. So reconcile it explicitly instead: pair the expected trailing space against
    the measured gap and compare the rest.

    Returns ``(expected_body, trailing_expected_or_None, measured_gap_or_None)``.
    """
    if (len(expected) == len(actual) + 1 and expected and expected[-1] < 0
            and (not actual or actual[-1] > 0)):
        return expected[:-1], expected[-1], gap_us
    return expected, None, None


def align(expected: list[int], actual: list[int], *, absolute_us: int,
          relative: float) -> dict:
    """Compare two pulse trains and describe the first real disagreement."""
    report = {"expected_len": len(expected), "actual_len": len(actual),
              "worst_index": None, "worst_error_us": 0, "worst_pair": None,
              "sign_error": None, "ok": False}
    for index, (want, got) in enumerate(zip(expected, actual)):
        if (want > 0) != (got > 0):
            report["sign_error"] = (index, want, got)
            return report
        error = abs(abs(want) - abs(got))
        if error > report["worst_error_us"]:
            report["worst_error_us"] = error
            report["worst_index"] = index
            report["worst_pair"] = (want, got)
    if len(expected) != len(actual):
        return report
    tolerance_of = lambda want: max(absolute_us, round(abs(want) * relative))  # noqa: E731
    for index, (want, got) in enumerate(zip(expected, actual)):
        if abs(abs(want) - abs(got)) > tolerance_of(want):
            report["worst_index"] = index
            report["worst_pair"] = (want, got)
            report["worst_error_us"] = abs(abs(want) - abs(got))
            return report
    report["ok"] = True
    return report


def describe(report: dict, *, absolute_us: int, relative: float) -> str:
    if report["sign_error"] is not None:
        index, want, got = report["sign_error"]
        return (f"FAIL  pulse {index} changes level: expected "
                f"{'mark' if want > 0 else 'space'}, saw "
                f"{'mark' if got > 0 else 'space'}")
    if report["expected_len"] != report["actual_len"]:
        return (f"FAIL  {report['actual_len']} pulses, expected "
                f"{report['expected_len']}  <- structural, not timing")
    if not report["ok"]:
        index = report["worst_index"]
        want, got = report["worst_pair"]
        allowed = max(absolute_us, round(abs(want) * relative))
        return (f"FAIL  pulse {index}: expected {want} us, measured {got} us "
                f"(off by {report['worst_error_us']} us, allowed {allowed})")
    return (f"PASS  {report['actual_len']} pulses, worst error "
            f"{report['worst_error_us']} us at index {report['worst_index']}")


def summarise(pulses: list[int]) -> str:
    marks = [p for p in pulses if p > 0]
    spaces = [-p for p in pulses if p < 0]
    if not marks:
        return "no marks"
    total = sum(marks) + sum(spaces)
    return (f"{len(pulses)} pulses, {total/1000:.1f} ms, "
            f"mark {min(marks)}-{max(marks)} us, "
            f"space {min(spaces) if spaces else 0}-{max(spaces) if spaces else 0} us")


def subframes(pulses: list[int], idle_gap: int) -> list[list[int]]:
    """Split a rendered transmission the way the probe splits a real one.

    A "press" is often several frames - Sony sends three - separated by gaps that may be
    longer or shorter than the probe's idle threshold. Whether the probe reports one
    capture or three is therefore a property of the *threshold*, not of the emission, and
    comparing a three-frame rendering against a one-frame capture fails for no reason.
    Split the expectation on the same rule the probe uses and the two line up regardless
    of where the threshold sits.
    """
    out, current = [], []
    for pulse in pulses:
        if pulse < 0 and abs(pulse) >= idle_gap:
            if current:
                out.append(current)
            current = []
            continue
        current.append(pulse)
    if current:
        out.append(current)
    return out or [list(pulses)]


def expectation_candidates(path: Path):
    """Candidates from a `<config>.expect.json` written beside a flashed configuration.

    The point of reading a file rather than re-rendering here is independence: those
    waveforms come from the portable definition, while the remote plays a native program
    the compiler produced from it. Comparing the two is the whole test. If this tool
    re-derived the expectation from the same definition at match time it would still be a
    fair check, but keeping the rendering with the config makes it explicit which build is
    being verified.

    The format is one entry per `"<device label> / <command>"`, holding a `protocol` id
    and any of `press`, `hold` and `release` as pulse lists. Whatever builds a bench
    configuration writes it; this tool only reads it.
    """
    data = json.loads(Path(path).read_text())
    out = []
    for label, entry in data.items():
        device, _, command = label.partition(" / ")
        phases = {phase: entry.get(phase) or [] for phase in ir_protocol.PHASES}
        if phases["press"]:
            out.append({"device": device.strip(), "command": command.strip(),
                        "protocol": entry.get("protocol", "?"), "phase": "lifecycle",
                        "pulses": phases["press"], "phases": phases})
    for label, entry in data.items():
        device, _, command = label.partition(" / ")
        # Every phase the portable model has, not just the two a keypress starts with.
        # `release` was omitted here, so a finish sequence - the thing the lifecycle bench
        # exists to measure - could not be matched even when the file described it.
        for phase in ir_protocol.PHASES:
            pulses = entry.get(phase) or []
            if pulses:
                out.append({"device": device.strip(), "command": command.strip(),
                            "protocol": entry.get("protocol", "?"), "phase": phase,
                            "parameters": {}, "pulses": pulses,
                            "why": entry.get("why", "")})
    return out


def run_bulk(args, lines) -> int:
    """Press everything, then identify each frame against the whole bench.

    Ctrl-C is how a run ends - there is no natural end to "press some buttons" - so the
    interrupt is caught here rather than in main(). Letting it propagate discarded the
    summary, which is the only part anyone actually wants.
    """
    candidates = expectation_candidates(args.expect)
    print(f"watching for {len(candidates)} expected emissions "
          f"({len({c['protocol'] for c in candidates})} protocols), "
          f"split at {args.split_at} us")
    print("press every bench button, then stop with Ctrl-C\n")

    seen = {}
    unmatched = []
    frames = 0
    try:
        frames = _bulk_loop(args, lines, candidates, seen, unmatched)
    except KeyboardInterrupt:
        print("\nstopped")
    return report_bulk(candidates, seen, unmatched, frames)


def score_lifecycle(phases: dict, actual: list[int], *, absolute_us: int,
                    relative: float) -> dict | None:
    """Read a whole keypress as `press, hold x N, release` and report N.

    A capture is one keypress, not one phase. Until 2026-09-03 this tool only ever
    compared a capture against a single phase, so the lifecycle measurement it exists to
    make - *how many times did the repeat run, and did the finish play* - had to be done
    by hand outside it, by splitting on frame padding and counting shapes.

    The comparison is on **mark+space pair sums**, not on individual durations. A
    demodulator stretches every mark and shortens the following space by the same amount:
    an expected `484, -512` arrives as `600, -396`, which is 108 us out per pulse and
    exact per pair. Comparing pulses directly reports a 300 us error on a perfect capture.

    Returns None when the capture does not begin with the press, which is how a frame
    belonging to some other remote is rejected.
    """
    def pairs(seq):
        """Mark+space *periods*, which a demodulator preserves.

        Deliberately `|mark| + |space|` and not the signed sum. The signed version also
        cancels the stretch, but it collapses the very thing that tells two protocols
        apart: a 600 us unit gives 0 and -1200, an 800 us unit gives 0 and -1600, so two
        different devices sit 200 us apart and match each other. As periods they are
        1200/2400 against 1600/3200 and cannot be confused.
        """
        return [abs(seq[i]) + abs(seq[i + 1]) for i in range(0, len(seq) - 1, 2)]

    def consume(want, at):
        """Match `want` at offset `at`, returning the next offset or None."""
        if not want:
            return None
        body = want[:-1] if want and want[-1] < 0 else want
        end = at + len(body)
        if end > len(actual):
            return None
        # Polarity must line up, or a shifted alignment could match by arithmetic.
        if any((w > 0) != (g > 0) for w, g in zip(body, actual[at:end])):
            return None
        wp, ap = pairs(body), pairs(actual[at:end])
        if len(wp) != len(ap) or not wp:
            return None
        for a, b in zip(wp, ap):
            if abs(a - b) > max(absolute_us, round(abs(a) * relative)):
                return None
        # Step over the gap that separates this frame from the next, if one was captured.
        return end + 1 if end < len(actual) and actual[end] < 0 else end

    at = consume(phases.get("press"), 0)
    if at is None:
        return None
    holds = 0
    while True:
        nxt = consume(phases.get("hold"), at)
        if nxt is None:
            break
        at, holds = nxt, holds + 1
    release = False
    if phases.get("release"):
        nxt = consume(phases["release"], at)
        if nxt is not None:
            at, release = nxt, True
    return {"holds": holds, "release": release,
            "trailing": max(0, len(actual) - at)}


def find_within(expected, actual, *, absolute_us: int, relative: float):
    """Locate `expected` as a contiguous run inside a longer capture.

    Some protocols cannot be split into frames by gap length at all: B&O 17 Bit Dual has
    34,400 us *inside* a symbol and only 12,302 us between frames, so any threshold that
    keeps one frame whole merges several. DreamMultimedia has 81,400 us inside a frame.
    For those the probe necessarily returns a blob of several frames, and comparing it
    against a single-frame expectation reports a mismatch on a perfectly good emission.

    So look for the expectation *within* the capture rather than requiring the two to be
    the same length. Returns the offset, or None.
    """
    if not expected or len(expected) > len(actual):
        return None
    first = expected[0]
    for start in range(len(actual) - len(expected) + 1):
        got = actual[start]
        if (got > 0) != (first > 0):
            continue
        if abs(abs(got) - abs(first)) > max(absolute_us, abs(first) * relative):
            continue
        if all((w > 0) == (g > 0)
               and abs(abs(w) - abs(g)) <= max(absolute_us, abs(w) * relative)
               for w, g in zip(expected, actual[start:start + len(expected)])):
            return start
    return None


def _bulk_loop(args, lines, candidates, seen, unmatched) -> int:
    frames = 0
    for header, pulses in parse_stream(lines):
        if "note" in header:
            found = BANNER_GAP_RE.search(header["note"])
            if found and int(found.group(1)) != args.split_at:
                args.split_at = int(found.group(1))
                candidates = expectation_candidates(args.expect)
                print(f"# probe reports idle_gap_us={args.split_at}; "
                      f"re-split expectations to match ({len(candidates)} candidates)")
            continue
        if header["overflow"] == "1" or header.get("truncated"):
            print(f"frame {header['idx']}: skipped (capture fault)")
            continue
        frames += 1
        hits = []
        # A whole keypress first: it is the thing a capture actually contains, and it is
        # the only reading that reports a repeat count.
        for candidate in candidates:
            if candidate["phase"] != "lifecycle":
                continue
            score = score_lifecycle(candidate["phases"], pulses,
                                    absolute_us=args.absolute_us,
                                    relative=args.relative)
            if score is not None:
                hits.append((candidate, {"worst_error_us": 0, **score}))
        if hits:
            for candidate, report in hits:
                key = (candidate["device"], candidate["command"], "lifecycle")
                entry = seen.setdefault(key, {"count": 0, "worst": 0})
                entry["count"] += 1
            names = ", ".join(f"{c['device']} / {c['command']}" for c, _r in hits)
            best = hits[0][1]
            tail = f", {best['trailing']} pulse(s) unread" if best["trailing"] else ""
            print(f"frame {header['idx']}: {names}  "
                  f"press + {best['holds']} hold"
                  f"{'' if best['holds'] == 1 else 's'}"
                  f"{' + finish' if best['release'] else ''}{tail}")
            if args.verbose:
                print("   raw: " + " ".join(f"{p:+d}" for p in pulses))
            continue
        for candidate in candidates:
            if candidate["phase"] == "lifecycle":
                continue
            body, _t, _g = split_trailing_gap(
                candidate["pulses"], pulses, int(header["gap"]))
            report = align(body, pulses, absolute_us=args.absolute_us,
                           relative=args.relative)
            if report["ok"]:
                hits.append((candidate, report))
        if not hits:
            # A capture that *begins* with a candidate and runs on is the ordinary shape
            # of a held key: press, then repeats, with nothing between them long enough
            # to end the frame. It is not a merged capture needing `--within` - the
            # command is right there at the start.
            #
            # This matters whenever the idle threshold has to be raised above a protocol's
            # own inter-frame gap. `Zenith 11 Bit Quad` puts 120,900 us between the parts
            # of a single press, so the threshold must exceed that, and then every *other*
            # protocol's press and repeats arrive as one frame. On the 2026-09-03 hardware
            # run all eight captured frames were reported UNMATCHED for this reason alone,
            # while every one of them was the right command.
            for candidate in candidates:
                if candidate["phase"] == "lifecycle":
                    continue
                body = candidate["pulses"]
                if body and body[-1] < 0:
                    body = body[:-1]
                if len(body) >= len(pulses) or len(body) < 8:
                    continue
                report = align(body, pulses[:len(body)],
                               absolute_us=args.absolute_us, relative=args.relative)
                if report["ok"]:
                    report["trailing"] = len(pulses) - len(body)
                    hits.append((candidate, report))
        if not hits and args.within:
            # Merged capture: the frame is in there, just not alone.
            for candidate in candidates:
                if candidate["phase"] == "lifecycle":
                    continue
                body = candidate["pulses"]
                if body and body[-1] < 0:
                    body = body[:-1]
                at = find_within(body, pulses, absolute_us=args.absolute_us,
                                 relative=args.relative)
                if at is not None:
                    hits.append((candidate, {"worst_error_us": 0, "within": at}))
                    break
        if not hits:
            unmatched.append((header["idx"], pulses))
            print(f"frame {header['idx']}: UNMATCHED  {summarise(pulses)}")
            print("   raw: " + " ".join(f"{p:+d}" for p in pulses))
            continue
        # Ambiguity is information, not a nuisance: two commands that render the same
        # waveform would mean the config cannot distinguish them either.
        for candidate, report in hits:
            key = (candidate["device"], candidate["command"], candidate["phase"])
            entry = seen.setdefault(key, {"count": 0, "worst": 0})
            entry["count"] += 1
            entry["worst"] = max(entry["worst"], report["worst_error_us"])
        names = ", ".join(f"{c['device']} / {c['command']} [{c['phase']}]"
                          for c, _r in hits)
        flag = "  AMBIGUOUS" if len(hits) > 1 else ""
        print(f"frame {header['idx']}: {names}{flag}")
        if args.verbose:
            # A matched frame used to print its name and nothing else, so the measurement
            # was thrown away for every frame the matcher understood. That is the wrong
            # half to discard when the question is *how many times* something repeated:
            # the match identifies the command, and only the pulses say how the lifecycle
            # played out.
            print("   raw: " + " ".join(f"{p:+d}" for p in pulses))
        if args.count and frames >= args.count:
            break
    return frames


def report_bulk(candidates, seen, unmatched, frames) -> int:
    print(f"\n{'=' * 68}\n{frames} frames captured\n")
    by_protocol = {}
    for candidate in candidates:
        key = (candidate["device"], candidate["command"], candidate["phase"])
        by_protocol.setdefault(candidate["protocol"], []).append(
            (key, seen.get(key)))
    print(f"{'protocol':16s} {'device / command [phase]':44s} {'seen':>5s} {'worst':>7s}")
    print("-" * 76)
    missing = 0
    for protocol in sorted(by_protocol):
        for (device, command, phase), hit in by_protocol[protocol]:
            label = f"{device} / {command} [{phase}]"
            if hit:
                print(f"{protocol:16s} {label:44s} {hit['count']:5d} "
                      f"{hit['worst']:6d}u")
            else:
                missing += 1
                print(f"{protocol:16s} {label:44s} {'-':>5s} {'not seen':>7s}")
    if unmatched:
        print(f"\n{len(unmatched)} unmatched frame(s) - these are the interesting ones:")
        for idx, pulses in unmatched[:6]:
            print(f"  frame {idx}: {summarise(pulses)}")
    print("\nA 'not seen' row is not a failure - it only means that button was not "
          "pressed.\nAn UNMATCHED frame is either a different remote in the room or a "
          "real disagreement.")
    return 0


def run_listen(args, lines) -> int:
    seen = 0
    for header, pulses in parse_stream(lines):
        if "note" in header:
            print(header["note"])
            continue
        seen += 1
        flag = ("  OVERFLOW - capture incomplete" if header["overflow"] == "1"
                else f"  TRUNCATED - {header['truncated']} measured, "
                     f"{len(pulses)} arrived" if header.get("truncated") else "")
        print(f"frame {header['idx']}: {summarise(pulses)}, "
              f"gap {int(header['gap'])/1000:.1f} ms{flag}")
        if args.verbose:
            print("   " + " ".join(f"{p:+d}" for p in pulses))
        if args.count and seen >= args.count:
            break
    return 0


def run_expect(args, lines) -> int:
    parameters = dict(args.parameters)
    library = ir_protocol.LIBRARY
    if args.definition:
        spec = json.loads(Path(args.definition).read_text())
        ir_protocol.validate(spec)
        library = {spec["id"]: spec}
    expected = expected_pulses(args.protocol, parameters, args.phase, library)
    # A held key emits repeat frames that are not the press frame. Gating every frame
    # against `press` reports those as structural failures, which is how a correct
    # capture gets read as a broken emitter.
    try:
        alternate = expected_pulses(args.protocol, parameters, "hold", library)
    except (KeyError, LookupError, ValueError):
        alternate = []
    if args.phase != "press" or alternate == expected:
        alternate = []
    print(f"protocol {args.protocol} phase={args.phase} parameters={parameters}")
    print(f"expected: {summarise(expected)}")
    if alternate:
        print(f"hold frames: {summarise(alternate)} (recognised, not counted as failures)")
    print(f"tolerance: max({args.absolute_us} us, {args.relative*100:.0f}%) per pulse "
          "- loose on purpose; the demodulator, not the remote, is the error source")
    print("waiting for frames (Ctrl-C to stop)\n")

    passes = failures = holds = 0
    idle_gap = DEFAULT_IDLE_GAP_US
    for header, pulses in parse_stream(lines):
        if "note" in header:
            found = BANNER_GAP_RE.search(header["note"])
            if found:
                idle_gap = int(found.group(1))
            continue
        if header["overflow"] == "1":
            print(f"frame {header['idx']}: SKIP - probe reported a capture overflow")
            continue
        if header.get("truncated"):
            print(f"frame {header['idx']}: SKIP - probe measured "
                  f"{header['truncated']} pulses but only {len(pulses)} arrived "
                  "(serial loss, not an emitter fault)")
            continue
        body, trailing, measured_gap = split_trailing_gap(
            expected, pulses, int(header["gap"]))
        report = align(body, pulses, absolute_us=args.absolute_us,
                       relative=args.relative)
        if not report["ok"] and alternate:
            hold_body, _t, _g = split_trailing_gap(
                alternate, pulses, int(header["gap"]))
            hold_report = align(hold_body, pulses, absolute_us=args.absolute_us,
                                relative=args.relative)
            if hold_report["ok"]:
                print(f"frame {header['idx']}: HOLD  {len(pulses)} pulses, matches the "
                      "hold frame")
                holds += 1
                continue
        line = describe(report, absolute_us=args.absolute_us, relative=args.relative)
        print(f"frame {header['idx']}: {line}")
        if trailing is not None:
            # `gap_us` is the probe's idle threshold, not a duration it measured, so it
            # can only ever confirm "at least that long". Treating it as a measurement
            # reported every correct NEC frame's 40 ms lead-out as SHORT.
            wanted = abs(trailing)
            if wanted > idle_gap + args.absolute_us:
                print(f"   lead-out: expected {wanted} us; NOT VERIFIABLE - this probe "
                      f"closes frames at {idle_gap} us. Raise its idle threshold to "
                      "measure a longer gap.")
            elif measured_gap + args.absolute_us >= wanted:
                print(f"   lead-out: expected {wanted} us, at least {measured_gap} us "
                      "seen -> consistent")
            else:
                print(f"   lead-out: expected {wanted} us but only {measured_gap} us "
                      "seen -> SHORT")
                report["ok"] = False
        if args.verbose and not report["ok"]:
            print("   expected: " + " ".join(f"{p:+d}" for p in body[:20]))
            print("   measured: " + " ".join(f"{p:+d}" for p in pulses[:20]))
        passes += report["ok"]
        failures += not report["ok"]
        if args.count and passes + failures >= args.count:
            break
    print(f"\n{passes} matched, {failures} did not"
          + (f", {holds} were hold/repeat frames" if holds else ""))
    if passes and not failures:
        print("A pass here means the mark/space structure matched. It does NOT verify\n"
              "the carrier (a demodulator strips it) and does NOT prove an appliance\n"
              "responds. Both are separate claims - see this module's docstring before\n"
              "promoting anything to hardware-anchored.")
    return 0 if passes and not failures else 1


class ParameterAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        current = dict(getattr(namespace, self.dest) or {})
        name = option_string.lstrip("-").replace("-", "_")
        try:
            current[name] = int(values, 0)
        except ValueError:
            parser.error(f"{option_string} needs an integer, got {values!r}")
        setattr(namespace, self.dest, current)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n##")[0].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Structure is judged exactly; absolute timing loosely. A wrong pulse\n"
               "count is a real defect. 80 us on a mark is the TSOP part.")
    parser.add_argument("--port", default=None,
                        help="serial device of the probe (default: autodetect, since a "
                             "USB board changes node on every reset)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--replay", type=Path,
                        help="read a saved capture instead of a live probe")
    parser.add_argument("--count", type=int, default=0,
                        help="stop after this many frames (0 = run until Ctrl-C)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    # Repeated on each subcommand so `... listen -v` works as naturally as `... -v listen`;
    # argparse otherwise rejects a global flag placed after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true")
    common.add_argument("--count", type=int, default=0)

    sub.add_parser("listen", parents=[common],
                   help="print every frame the probe sees")

    bulk = sub.add_parser(
        "bulk", parents=[common],
        help="identify every frame against the whole bench config in one pass")
    bulk.add_argument("--absolute-us", type=int, default=DEFAULT_ABSOLUTE_US)
    bulk.add_argument("--relative", type=float, default=DEFAULT_RELATIVE)
    bulk.add_argument("--within", action="store_true",
                      help="also match an expectation found *inside* a longer capture, "
                           "for protocols whose frames cannot be separated by gap length")
    bulk.add_argument("--expect", type=Path, required=True,
                      help="a .expect.json written beside the flashed config; "
                           "verifies that config instead of the built-in bench")
    bulk.add_argument("--set-gap", type=int, default=None,
                      help="set the probe's idle threshold (us) before capturing; must "
                           "exceed the longest gap inside one press")
    bulk.add_argument("--split-at", type=int, default=DEFAULT_IDLE_GAP_US,
                      help="split expectations at this gap; overridden by the probe's "
                           "own banner when it reports one")

    expect = sub.add_parser(
        "expect", parents=[common],
        help="gate frames against a portable protocol definition")
    expect.add_argument("protocol", help="portable protocol id, e.g. sony12, nec1")
    expect.add_argument("--phase", default="press", choices=ir_protocol.PHASES)
    expect.add_argument("--definition", help="a protocol JSON outside the shipped library")
    expect.add_argument("--absolute-us", type=int, default=DEFAULT_ABSOLUTE_US)
    expect.add_argument("--relative", type=float, default=DEFAULT_RELATIVE)
    expect.set_defaults(parameters={})
    for name in ("code", "address", "command", "address-low", "address-high",
                 "device", "function", "toggle"):
        expect.add_argument(f"--{name}", action=ParameterAction, dest="parameters",
                            metavar="N", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.replay:
        lines = args.replay.read_text().splitlines()
    else:
        lines = serial_lines(find_port(args.port), args.baud,
                             getattr(args, "set_gap", None))

    try:
        if args.command == "listen":
            return run_listen(args, lines)
        if args.command == "bulk":
            return run_bulk(args, lines)
        return run_expect(args, lines)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
