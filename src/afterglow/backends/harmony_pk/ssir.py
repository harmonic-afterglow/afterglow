#!/usr/bin/env python3
"""`SsIr.bin` - raw IR waveforms, for commands no protocol can describe.

Format reference: docs/harmony_pk/ssir.md
"""
from __future__ import annotations

import re
import struct

from ... import ir_signal
from . import BACKEND_NAMES, NAME

PREFIX = bytes.fromhex("010105000001")
ENTRY_BIAS = 5                      # an entry starts at (stored offset + 5)
BACKEND = NAME

RAW_CODE = re.compile(r"^0x[fF]{4}([0-9a-fA-F]{2})", re.ASCII)


def is_raw(code: str) -> bool:
    """Does this command carry a recorded waveform rather than a generated one?"""
    return bool(code and RAW_CODE.match(code.strip()))


def raw_index(code: str) -> int | None:
    """The entry a raw command points at, or None if it is not a raw command."""
    match = RAW_CODE.match((code or "").strip())
    return int(match.group(1), 16) if match else None


def make_code(index: int) -> str:
    """The `<Code>` that selects raw entry `index`."""
    return f"0xFFFF{index:02X}00"


def parse(payload: bytes) -> list[bytes]:
    """The waveform entries, in order. An empty table is normal and means no raw IR."""
    if len(payload) < 8 or payload[:6] != PREFIX:
        raise ValueError(f"not an SsIr payload (prefix {payload[:6].hex()})")
    count, = struct.unpack_from("<H", payload, 6)
    if count == 0:
        return []
    starts = [struct.unpack_from("<H", payload, 8 + 2 * i)[0] + ENTRY_BIAS
              for i in range(count)]
    bounds = starts + [len(payload)]
    return [payload[bounds[i]:bounds[i + 1]] for i in range(count)]


def build(entries: list[bytes]) -> bytes:
    """Entries -> a payload. Order is the index order the codes refer to."""
    count = len(entries)
    out = bytearray(PREFIX + struct.pack("<H", count))
    position = 8 + 2 * count
    offsets = []
    for entry in entries:
        offsets.append(position - ENTRY_BIAS)
        position += len(entry)
    for offset in offsets:
        out += struct.pack("<H", offset)
    for entry in entries:
        out += entry
    return bytes(out)


def read(path: str) -> list[bytes]:
    with open(path, "rb") as handle:
        return parse(handle.read())


def write(path: str, entries: list[bytes]) -> None:
    with open(path, "wb") as handle:
        handle.write(build(entries))


def collect(specs) -> tuple[list[bytes], dict]:
    """Gather the waveforms the given devices use, and renumber their codes.

    Returns `(entries, remap)` where `remap` is `{(device id, command): new code}`. Only
    waveforms actually referenced are carried, and they are renumbered to their position
    in the rebuilt file - the same thing the protocol assembler does for `IrProto.bin`,
    for the same reason: an index is a position, never an identity.
    """
    entries: list[bytes] = []
    remap: dict = {}
    for spec in specs:
        raw_ir = spec.get("raw_ir") or {}
        if not raw_ir:
            continue
        for name, code in (spec.get("raw_codes") or {}).items():
            index = raw_index(code)
            if index is None:
                continue
            waveform = raw_ir.get(str(index))
            if waveform is None:
                continue
            if isinstance(waveform, dict):
                blob = encode_capture(waveform)          # the readable form
            elif isinstance(waveform, str):
                blob = bytes.fromhex(waveform)           # raw hex, still accepted
            else:
                blob = waveform
            if blob in entries:
                new_index = entries.index(blob)
            else:
                new_index = len(entries)
                entries.append(blob)
            remap[(spec["id"], name)] = make_code(new_index)
    return entries, remap


# readable form
# A waveform is a pulse train, so it can be written as one: a list of durations in
# microseconds, positive for a mark (carrier on) and negative for a space. That is the
# convention LIRC and Flipper Zero raw captures use, so a capture is legible and
# comparable against other tools instead of being a wall of hex.
#
# An entry has three parts: a u32 carrier period in nanoseconds, a u16 count of pulse
# *words*, then that many u16 mark/space words.  The count is structural, not a
# pulse.  Treating it as one happened to round-trip imported entries (because it was
# carried through as a negative duration), but made a newly learned entry malformed.
# The four leading bytes are kept verbatim as backend-native Harmony PK evidence; naming
# them after an unproved physical meaning would be a lie in a portable file format.

# Kept as a public alias while callers move from "capture" to the portable signal name.
CAPTURE_SCHEMA = ir_signal.SCHEMA
HEADER_LEN = 4
COUNT_LEN = 2
_MARK = 0x8000
_US = 0x7FFF


def decode_capture(blob: bytes, name: str = "") -> dict:
    """A waveform -> a readable definition."""
    if len(blob) < HEADER_LEN + COUNT_LEN or (len(blob) - HEADER_LEN - COUNT_LEN) % 2:
        raise ValueError(f"not a raw IR entry ({len(blob)} bytes)")
    word_count, = struct.unpack_from("<H", blob, HEADER_LEN)
    actual_count = (len(blob) - HEADER_LEN - COUNT_LEN) // 2
    if word_count != actual_count:
        raise ValueError(
            f"raw IR entry says it has {word_count} pulse words but contains {actual_count}")
    words = [struct.unpack_from("<H", blob, i)[0]
             for i in range(HEADER_LEN + COUNT_LEN, len(blob), 2)]
    pulses = [(w & _US) if (w & _MARK) else -(w & _US) for w in words]
    period_ns, = struct.unpack_from("<I", blob, 0)
    return ir_signal.waveform(
        pulses,
        name=name,
        carrier_hz=round(1_000_000_000 / period_ns) if period_ns else None,
        native={BACKEND: {
            "ssir_carrier_period_ns": period_ns,
            "status": "observed",
        }},
    )


def normalise_signal(spec: dict) -> dict:
    """Migrate old Afterglow SsIr capture JSON with its exact native period."""
    signal = ir_signal.normalise(spec)
    prefix = spec.get("header_hex") if isinstance(spec, dict) else None
    if not prefix:
        return signal
    try:
        raw_prefix = bytes.fromhex(prefix)
    except ValueError as exc:
        raise ValueError(f"invalid legacy SsIr header {prefix!r}") from exc
    if len(raw_prefix) != 4:
        raise ValueError(f"legacy SsIr header must be 4 bytes, got {len(raw_prefix)}")
    signal = dict(signal)
    native = dict(signal.get("native") or {})
    native[BACKEND] = {
        "ssir_carrier_period_ns": int.from_bytes(raw_prefix, "little"),
        "status": "observed",
    }
    signal["native"] = native
    return signal


def _observed_period_ns(spec: dict) -> int | None:
    """Read exact native evidence without making the portable layer interpret it."""
    signal = normalise_signal(spec)
    evidence = signal.get("native") or {}
    native = next((evidence[name] for name in BACKEND_NAMES if evidence.get(name)), {})
    period = native.get("ssir_carrier_period_ns")
    if period is not None:
        if not isinstance(period, int) or not 0 < period <= 0xFFFFFFFF:
            raise ValueError("Harmony PK SsIr carrier period must fit a non-zero u32")
        return period
    text = native.get("ssir_prefix_hex")
    if not text:
        return None
    try:
        prefix = bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(f"invalid Harmony PK SsIr prefix {text!r}") from exc
    if len(prefix) != 4:
        raise ValueError(f"Harmony PK SsIr prefix must be 4 bytes, got {len(prefix)}")
    return int.from_bytes(prefix, "little")


def capture_header(spec: dict) -> bytes:
    """The four-byte carrier period an SsIr entry begins with.

    A capture read from a real configuration carries its own backend-native prefix and
    that is written back untouched. Otherwise libconcord's measured carrier is converted
    to the nearest integer period in nanoseconds.

    This is established statically in the remote's unstripped `irgen`: ProcessIrCmd's raw
    branch parses these bytes as a little-endian u32, StartIrfire passes that value to
    IrgenInitPwm, and IrgenInitPwm computes 1,000,000,000 / value before programming PWM.
    It is the same representation as IrProto's carrier_period_ns field.
    """
    observed_period = _observed_period_ns(spec)
    if observed_period is not None:
        return struct.pack("<I", observed_period)
    signal = normalise_signal(spec)
    carrier_hz = signal.get("carrier_hz")
    if carrier_hz:
        period_ns = round(1_000_000_000 / carrier_hz)
        if not 0 < period_ns <= 0xFFFFFFFF:
            raise ValueError(
                f"capture {spec.get('name', '?')!r} carrier period is out of u32 range")
        return struct.pack("<I", period_ns)
    raise ValueError(
        f"capture {spec.get('name', '?')!r} has neither an observed Harmony PK carrier "
        "period nor a measured carrier_hz")


def _words_for(pulse: int) -> list[int]:
    """One signed microsecond duration -> the SsIr words that reproduce it.

    A word carries a 15-bit duration, so 32767 us is the longest single one. A space
    longer than that is written as **consecutive off words**, which is this format's own
    idiom rather than an invention: a real Logitech `SsIr.bin` entry in the private donor
    corpus contains runs of 10 and 2 adjacent off words, and `ir_emit._split_space` uses
    the same construction for the native protocol path.

    The alternative - dropping the overlong trailing space - makes a rendered RC6
    waveform fail against a real MCE receiver while every software check passes. The
    lead-out separates one frame from the next; without it a held key runs frames
    together. Do not "simplify" this back.

    Marks are not chunked. A carrier burst longer than 32.767 ms is not a real infrared
    signal, so an oversized mark stays an error rather than becoming a plausible one.
    """
    duration = abs(pulse)
    if pulse > 0:
        if duration > _US:
            raise ValueError(
                f"SsIr mark durations must fit 15 bits ({_US} us maximum); got {pulse} us")
        return [duration | _MARK]
    words = []
    while duration > 0:
        chunk = min(duration, _US)
        words.append(chunk)
        duration -= chunk
    return words or [0]


def encode_capture(spec: dict) -> bytes:
    """A readable definition -> the waveform bytes."""
    signal = normalise_signal(spec)
    if signal.get("kind") != "waveform":
        raise ValueError(f"SsIr needs a waveform signal, got {signal.get('kind')!r}")
    pulses = signal["pulses_us"]
    words = [word for pulse in pulses for word in _words_for(pulse)]
    if len(words) > _US:
        raise ValueError(
            f"raw IR capture needs {len(words)} pulse words; maximum is {_US}")
    out = bytearray(capture_header(signal))
    out += struct.pack("<H", len(words))
    for word in words:
        out += struct.pack("<H", word)
    return bytes(out)
