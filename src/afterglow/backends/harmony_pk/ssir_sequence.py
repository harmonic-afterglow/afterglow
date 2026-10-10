"""`SsIr.bin` as the Harmony 1100 keeps it: every command a recorded device sequence.

The 1100 plays commands back rather than generating them, so its waveform table is the
whole of its infrared. This reads it into sequences that keep every stored word, carrier
descriptor, repeat point and unexplained byte, so a configuration can be rebuilt from what
was read, and gives each one a portable waveform for everything else to use.

Format reference: docs/harmony_pk/ssir-sequences.md
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

VERSION = 1
SEGMENT_END = (0x0001, 0x0000)
_MARK = 0x8000


@dataclass(frozen=True)
class Variant:
    """One of a sequence's alternatives - a toggle state - as stored."""
    words: tuple[int, ...]
    repeat_at: int | None          # word index the held part restarts from
    tail: bytes = bytes(3)         # three bytes after the repeat point, kept verbatim
    # The held part when it is not in this waveform but shared: Logitech stores an NEC
    # repeat frame once and points every hold of the device at it.
    shared_repeat: tuple[int, ...] | None = None

    def segments(self) -> list[list[int]]:
        """Signed microsecond pulses per segment (+mark, -space), adjacent pulses of
        one kind merged: a gap longer than one word can hold is written as several."""
        out, current = [], []
        words, i = self.words, 0
        while i < len(words):
            if (words[i], words[i + 1] if i + 1 < len(words) else None) == SEGMENT_END:
                out.append(current)
                current, i = [], i + 2
                continue
            word = words[i]
            value = (word & 0x7FFF) * (1 if word & _MARK else -1)
            if current and value and (current[-1] > 0) == (value > 0):
                current[-1] += value
            elif value:
                current.append(value)
            i += 1
        if current:
            out.append(current)
        return out


@dataclass(frozen=True)
class Sequence:
    """One stored sequence: its carrier descriptors and its variants, as stored."""
    carriers: tuple[bytes, ...]    # 7-byte descriptors, verbatim
    variants: tuple[Variant, ...]

    @property
    def carrier_hz(self) -> int:
        period = _u24(self.carriers[0], 1) if self.carriers else 0
        return round(1e9 / period) if period else 0

    def to_native(self) -> dict:
        """The sequence as JSON-safe evidence a build can write back unchanged."""
        return {"carriers": [c.hex() for c in self.carriers],
                "variants": [{"words": struct.pack(f"<{len(v.words)}H", *v.words).hex(),
                              **({"repeat_at": v.repeat_at}
                                 if v.repeat_at is not None else {}),
                              **({"tail": v.tail.hex()} if any(v.tail) else {}),
                              **({"shared_repeat": struct.pack(
                                  f"<{len(v.shared_repeat)}H", *v.shared_repeat).hex()}
                                 if v.shared_repeat is not None else {})}
                             for v in self.variants]}

    @classmethod
    def from_native(cls, native: dict) -> "Sequence":
        variants = []
        for v in native["variants"]:
            raw = bytes.fromhex(v["words"])
            shared = bytes.fromhex(v["shared_repeat"]) if "shared_repeat" in v else None
            variants.append(Variant(struct.unpack(f"<{len(raw) // 2}H", raw),
                                    v.get("repeat_at"),
                                    bytes.fromhex(v.get("tail", "000000")),
                                    struct.unpack(f"<{len(shared) // 2}H", shared)
                                    if shared is not None else None))
        return cls(tuple(bytes.fromhex(c) for c in native["carriers"]), tuple(variants))


def _u24(data: bytes, offset: int) -> int:
    return data[offset] | data[offset + 1] << 8 | data[offset + 2] << 16


def parse(payload: bytes) -> list[list[Sequence]]:
    """Every device's sequences, by DeviceIndex then SequenceIndex.

    Raises ValueError on a file without this layout - the 900's `SsIr.bin` shares the
    name - rather than following pointers through somebody else's bytes.
    """
    if len(payload) < 5 or struct.unpack_from("<H", payload)[0] != VERSION:
        raise ValueError("not a device-sequence SsIr.bin")
    root = _u24(payload, 2)
    if root >= len(payload):
        raise ValueError("SsIr.bin root directory points outside the file")

    # Where every structure starts. A waveform has no length of its own: it runs to
    # whatever the pool holds next.
    records, starts = [], {root, len(payload)}
    for d in range(payload[root]):
        table = _u24(payload, root + 1 + 3 * d)
        starts.add(table)
        count = struct.unpack_from("<H", payload, table + 1)[0]
        row = []
        for s in range(count):
            record = _u24(payload, table + 3 + 3 * s)
            starts.add(record)
            n = payload[record]
            carriers = [_u24(payload, record + 1 + 3 * k) for k in range(n)]
            at = record + 1 + 3 * n
            m = payload[at]
            variants = []
            for k in range(m):
                base = at + 1 + 9 * k
                variants.append((_u24(payload, base), _u24(payload, base + 3),
                                 payload[base + 6:base + 9]))
            starts.update(carriers)
            starts.update(wave for wave, _r, _t in variants)
            row.append((carriers, variants))
        records.append(row)
    ordered = sorted(starts)

    def end_of(start):
        for position in ordered:
            if position > start:
                return position
        return len(payload)

    devices = []
    for row in records:
        sequences = []
        for carriers, variants in row:
            out = []
            for wave, repeat, tail in variants:
                end = end_of(wave)
                words = struct.unpack_from(f"<{(end - wave) // 2}H", payload, wave)
                if repeat and not wave <= repeat < end:
                    # Held part shared with another waveform: keep the words it plays.
                    shared = struct.unpack_from(f"<{(end_of(repeat) - repeat) // 2}H",
                                                payload, repeat)
                    out.append(Variant(tuple(words), None, bytes(tail), tuple(shared)))
                    continue
                out.append(Variant(tuple(words), (repeat - wave) // 2 if repeat else None,
                                   bytes(tail)))
            sequences.append(Sequence(tuple(payload[c:c + 7] for c in carriers),
                                      tuple(out)))
        devices.append(sequences)
    return devices


def first_frame(sequence: Sequence) -> list[int]:
    """The first variant's first segment without its lead-in silence: what a receiver
    sees for one press, as a portable waveform's pulses."""
    segments = sequence.variants[0].segments() if sequence.variants else []
    pulses = list(segments[0]) if segments else []
    while pulses and pulses[0] < 0:
        pulses.pop(0)
    return pulses


def _p24(value: int) -> bytes:
    if not 0 <= value < 1 << 24:
        raise ValueError(f"SsIr.bin offset {value:#x} does not fit in three bytes")
    return bytes((value & 0xFF, value >> 8 & 0xFF, value >> 16))


def _shared_at(repeats: dict[tuple[int, ...], int], stored: dict[tuple[int, ...], int],
               words: tuple[int, ...]) -> int | None:
    """Where `words` already are: a repeat point this device wrote before with exactly
    that held part, else the first stored waveform that ends with them."""
    if words in repeats:
        return repeats[words]
    for waveform, start in stored.items():
        if len(waveform) >= len(words) and waveform[len(waveform) - len(words):] == words:
            return start + 2 * (len(waveform) - len(words))
    return None


def build(devices: list[list[Sequence]]) -> bytes:
    """Sequences by DeviceIndex then SequenceIndex -> an `SsIr.bin`.

    Laid out as Logitech's are: each sequence's waveforms, then its carrier descriptors,
    then its record; after every device's pool, the device tables; the root last. A
    waveform identical to one already stored is pointed at rather than stored again, and
    a shared repeat points where the device first wrote that held part.
    """
    out = bytearray(b"\x00" * 5)
    tables = []
    stored: dict[tuple[int, ...], int] = {}      # an identical waveform is stored once
    for sequences in devices:
        repeats: dict[tuple[int, ...], int] = {}  # held part -> the device's first repeat
        records = []
        for sequence in sequences:
            waves = []
            for variant in sequence.variants:
                if variant.shared_repeat is not None and \
                        _shared_at(repeats, stored, variant.shared_repeat) is None:
                    stored[variant.shared_repeat] = repeats[variant.shared_repeat] = len(out)
                    out += struct.pack(f"<{len(variant.shared_repeat)}H",
                                       *variant.shared_repeat)
                if variant.words in stored:
                    waves.append(stored[variant.words])
                    continue
                stored[variant.words] = len(out)
                waves.append(len(out))
                out += struct.pack(f"<{len(variant.words)}H", *variant.words)
            carriers = []
            for descriptor in sequence.carriers:
                carriers.append(len(out))
                out += descriptor
            records.append(len(out))
            out.append(len(carriers))
            for position in carriers:
                out += _p24(position)
            out.append(len(sequence.variants))
            for start, variant in zip(waves, sequence.variants):
                if variant.shared_repeat is not None:
                    repeat = _shared_at(repeats, stored, variant.shared_repeat)
                elif variant.repeat_at is not None:
                    repeat = start + 2 * variant.repeat_at
                    repeats.setdefault(variant.words[variant.repeat_at:], repeat)
                else:
                    repeat = 0
                out += _p24(start) + _p24(repeat) + variant.tail
        tables.append(records)
    positions = []
    for records in tables:
        positions.append(len(out))
        out += b"\x00" + struct.pack("<H", len(records))
        for record in records:
            out += _p24(record)
    root = len(out)
    out.append(len(positions))
    for position in positions:
        out += _p24(position)
    struct.pack_into("<H", out, 0, VERSION)
    out[2:5] = _p24(root)
    return bytes(out)


# from portable signals
_MAX_VARIANTS = 4                  # toggle states a protocol may cycle through


def _words(pulses) -> list[int]:
    """Signed microseconds -> stored words; a duration over 32767 us is split."""
    out = []
    for pulse in pulses:
        mark, length = pulse > 0, abs(int(pulse))
        while length > 0:
            part = min(length, 0x7FFF)
            out.append((_MARK | part) if mark else part)
            length -= part
    return out


def carrier_descriptor(carrier_hz: int) -> bytes:
    """A carrier as the 1100 stores it: the period and half of it as on-time, in ns."""
    period = round(1e9 / carrier_hz)
    return b"\x00" + _p24(period) + _p24(period // 2)


def _segment(pulses, silence_ms: int = 0) -> list[int]:
    return _words(([-int(silence_ms) * 1000] if silence_ms else []) + list(pulses)) \
        + list(SEGMENT_END)


def _renders(signal: dict, library) -> tuple[int, list[tuple[list[int], list[int]]]]:
    """(carrier Hz, [(press pulses, hold pulses) per toggle state])."""
    from ... import ir_protocol
    if signal["kind"] == "waveform":
        pulses = list(signal["pulses_us"])
        return int(signal.get("carrier_hz") or 38000), [(pulses, pulses)]
    if signal["kind"] != "protocol":
        raise ValueError(f"a {signal['kind']} signal has nothing to play back")
    variants, state, carrier = [], None, 38000
    for _ in range(_MAX_VARIANTS):
        press, after = ir_protocol.render_transmission(signal, phase="press", state=state,
                                                       library=library)
        hold, _ignored = ir_protocol.render_transmission(signal, phase="hold",
                                                         state=after, library=library)
        carrier = press["carrier_hz"] if press else carrier
        pair = (press["pulses_us"] if press else [],
                hold["pulses_us"] if hold else [])
        if variants and pair == variants[0]:
            break                                   # the toggle state has cycled back
        variants.append(pair)
        state = after
    return carrier, variants


def for_signal(signal: dict, *, press_presilence: int, hold_presilence: int,
               library=None) -> tuple[Sequence, Sequence]:
    """(press, hold) sequences that play `signal` on a Harmony 1100.

    A signal read from an 1100 carries Logitech's own sequences and gets them back
    unchanged. Anything else is rendered: one variant per toggle state; a press is the
    device's press presilence and one frame; a hold is its hold presilence and one
    frame, then the frame the protocol repeats while held, where it restarts.
    """
    from . import NAME
    evidence = ((signal.get("native") or {}).get(NAME) or {})
    if evidence.get("format") == "device-sequence" and "press" in evidence:
        press = Sequence.from_native(evidence["press"])
        hold = Sequence.from_native(evidence["hold"]) if "hold" in evidence else press
        return press, hold
    carrier, renders = _renders(signal, library)
    descriptor = (carrier_descriptor(carrier),)
    press_variants, hold_variants = [], []
    for press, hold in renders:
        if not press:
            raise ValueError(f"{signal.get('name') or 'a command'} renders to nothing")
        press_variants.append(Variant(tuple(_segment(press, press_presilence)), None))
        start = _segment(press, hold_presilence)
        hold_variants.append(Variant(tuple(start + _segment(hold or press)), len(start)))
    return (Sequence(descriptor, tuple(press_variants)),
            Sequence(descriptor, tuple(hold_variants)))
