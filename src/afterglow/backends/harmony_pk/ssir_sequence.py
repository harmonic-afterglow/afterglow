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
                              **({"tail": v.tail.hex()} if any(v.tail) else {})}
                             for v in self.variants]}

    @classmethod
    def from_native(cls, native: dict) -> "Sequence":
        variants = []
        for v in native["variants"]:
            raw = bytes.fromhex(v["words"])
            variants.append(Variant(struct.unpack(f"<{len(raw) // 2}H", raw),
                                    v.get("repeat_at"),
                                    bytes.fromhex(v.get("tail", "000000"))))
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
