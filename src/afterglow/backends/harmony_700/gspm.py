"""Structural validation for the Harmony 700's indexed configuration image.

This backend began as a copy of the Harmony One's, and its modules address the image by
the One's section numbers. The 700 is the same `GSPM` family at architecture 14: base
`0x030000`, header word `0x1400`, `LWJL` at `0x5b`, and eighteen master-index slots with
none left empty. The slots are the One's sections 0-7, 9-17 and 19 in that order; the One's
section 8 and 18 have nothing in the 700, so they read as absent here.

Format reference: docs/harmony_650_700/gspm.md
"""

from __future__ import annotations

import struct


BASE = 0x030000
MAGIC = b"GSPM"
HEADER_CONSTANT = 0x1400
BUTTON_MAP_OFFSET = 0x5B
# `LWJL` is the marker; the byte after it counts mode 0's list (163 entries on a 700).
BUTTON_MAP_MAGIC = b"LWJL"
SECTION_COUNT = 20
# The One's section number each of the 700's eighteen master-index slots holds.
SLOT_SECTIONS = (0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19)
ABSENT_SECTIONS = (8, 18)
CHECKSUM_SEED = (0x21, 0x43)
# The 700's flash map is not measured; the One's limit is kept until it is.
MAX_SAFE_SIZE = 0x390000


def checksum(data: bytes, end: int) -> tuple[int, int]:
    """Return the firmware's two-lane XOR over complete pairs before ``end``."""
    end -= end % 2
    low, high = CHECKSUM_SEED
    return low ^ _xor(data[0:end:2]), high ^ _xor(data[1:end:2])


def _xor(lane: bytes) -> int:
    """Every byte XORed together, folding the lane as one integer - each half XORed onto
    the other until a byte is left - which is the same sum at C speed."""
    value, width = int.from_bytes(lane, "little"), len(lane)
    while width > 1:
        half = (width + 1) // 2
        value = (value & ((1 << (8 * half)) - 1)) ^ (value >> (8 * half))
        width = half
    return value


def seal(body: bytes) -> bytes:
    """Close a GSPM body with the checksum and the end marker ``PTYY``, the header's end
    pointer set to the marker. An odd-sized body needs no padding: the checksum covers
    whole pairs only."""
    out = bytearray(body)
    marker = len(out) + 2
    out += b"\x00\x00PTYY"
    struct.pack_into("<I", out, 4, BASE + marker)
    out[marker - 2:marker] = bytes(checksum(out, marker - 2))
    return bytes(out)


def _sections(payload: bytes, checksum_offset: int) -> tuple[int | None, ...]:
    """Section offsets relative to the payload, indexed by the One's section numbers."""
    sections: list[int | None] = [None] * SECTION_COUNT
    for slot, section in enumerate(SLOT_SECTIONS):
        absolute = struct.unpack_from("<I", payload, 0x0C + slot * 4)[0]
        relative = absolute - BASE
        if not absolute or not 0 <= relative < checksum_offset:
            raise ValueError(
                f"GSPM slot {slot} (section {section}) points outside the configuration: "
                f"{absolute:#08x}")
        sections[section] = relative
    present = [offset for offset in sections if offset is not None]
    if len(present) != len(set(present)):
        raise ValueError("GSPM section pointers are not unique")
    return tuple(sections)


def validate(payload: bytes) -> dict:
    """Validate independently measured conditions enforced by the arch-14 format."""
    if not isinstance(payload, bytes):
        raise TypeError("GSPM payload must be bytes")
    if len(payload) < BUTTON_MAP_OFFSET + len(BUTTON_MAP_MAGIC) + 1:
        raise ValueError("GSPM payload is shorter than its fixed header")
    if len(payload) >= MAX_SAFE_SIZE:
        raise ValueError(
            f"GSPM payload is {len(payload):#x} bytes; safe limit is below {MAX_SAFE_SIZE:#x}")
    if payload[:4] != MAGIC:
        raise ValueError(f"GSPM magic is {payload[:4]!r}, expected {MAGIC!r}")

    end_vector, constant = struct.unpack_from("<II", payload, 4)
    if constant != HEADER_CONSTANT:
        raise ValueError(
            f"GSPM header constant is {constant:#x}, expected {HEADER_CONSTANT:#x}")
    marker_offset = end_vector - BASE
    if marker_offset < 2 or marker_offset + 4 != len(payload):
        raise ValueError(
            f"GSPM end vector {end_vector:#08x} does not point at the final PTYY marker")
    if payload[marker_offset:marker_offset + 4] != b"PTYY":
        raise ValueError("GSPM end vector does not point at PTYY")
    end = BUTTON_MAP_OFFSET + len(BUTTON_MAP_MAGIC)
    if payload[BUTTON_MAP_OFFSET:end] != BUTTON_MAP_MAGIC:
        raise ValueError(
            f"GSPM arch-14 marker {BUTTON_MAP_MAGIC.decode()} is absent at "
            f"{BUTTON_MAP_OFFSET:#x}")

    checksum_offset = marker_offset - 2
    actual = checksum(payload, checksum_offset)
    stored = tuple(payload[checksum_offset:marker_offset])
    if actual != stored:
        raise ValueError(
            "GSPM checksum mismatch: "
            f"computed {actual[0]:02x}{actual[1]:02x}, "
            f"stored {stored[0]:02x}{stored[1]:02x}")

    sections = _sections(payload, checksum_offset)
    return {
        "ok": True,
        "validator": "harmony-700/gspm-structural",
        "size": len(payload),
        "end_vector": end_vector,
        "checksum": f"{actual[0]:02x}{actual[1]:02x}",
        "sections": sum(offset is not None for offset in sections),
        "preserved_bytes": len(payload),
    }


def section_ranges(payload: bytes) -> dict[int, tuple[int, int]]:
    """Return validated section ranges as offsets relative to the payload."""
    validate(payload)
    marker_offset = struct.unpack_from("<I", payload, 4)[0] - BASE
    checksum_offset = marker_offset - 2
    sections = _sections(payload, checksum_offset)
    starts = sorted(offset for offset in sections if offset is not None)
    boundaries = starts + [checksum_offset]
    return {
        index: (start, boundaries[boundaries.index(start) + 1])
        for index, start in enumerate(sections)
        if start is not None
    }
