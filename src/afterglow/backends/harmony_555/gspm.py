"""Structural validation for the Harmony 5xx family's configuration image (architecture 9).

This backend began as a copy of the Harmony 650's, and its modules address the image by
the One's section numbers, as the 650's do. Architecture 9 is the parent of the 650's
`GSPM` format: the same header, section table and checksum, with its own markers -
`AHCM` at the start, `CMAH` at `0x5b`, `MCHA` at the end - and base `0x020000`. The section
table is twenty `{u8 spare; u24 address}` items from `0x0b` (the byte at `0x09` counts
them); the last two are empty, and the eighteen before them are the One's sections 0-7,
9-17 and 19, as on the 650. Unlike the 650's `LWJL`, no key table follows `CMAH`: the keys
are bound in the mode records.

A configuration lives at `0x820000` on the remote, in the five 64 KiB blocks below the log
area at `0x870000`; its own pointers count from `0x020000`
(afterglow-research/harmony-555.md, from Danny Bloemendaal's harmony-explorations, MIT).

Format reference: docs/harmony_5xx/ahcm.md
"""

from __future__ import annotations

import struct


BASE = 0x020000
MAGIC = b"AHCM"
END_MAGIC = b"MCHA"
HEADER_CONSTANT = 0x1400
BUTTON_MAP_OFFSET = 0x5B
# The marker after the section table. On the 650 a key table follows it; here the byte
# after it is zero and the keys live in the mode records.
BUTTON_MAP_MAGIC = b"CMAH"
SECTION_COUNT = 20
TABLE_OFFSET = 0x0B
TABLE_ITEMS = 20
# The One's section number each of the eighteen used items holds, as on the 650.
SLOT_SECTIONS = (0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19)
ABSENT_SECTIONS = (8, 18)
CHECKSUM_SEED = (0x21, 0x43)
# The configuration region runs from the base to the log area, 0x070000 in the image's
# own addresses: five 64 KiB blocks.
MAX_SAFE_SIZE = 0x050000


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
    """Close an AHCM body with the checksum and the end marker ``MCHA``, the header's end
    pointer set to the marker."""
    out = bytearray(body)
    marker = len(out) + 2
    out += b"\x00\x00" + END_MAGIC
    struct.pack_into("<I", out, 4, BASE + marker)
    out[marker - 2:marker] = bytes(checksum(out, marker - 2))
    return bytes(out)


def _item(payload: bytes, index: int) -> int:
    """Section table item ``index``'s address. Its spare byte is checked rather than read
    into the address: a nonzero one would otherwise add 0x1000000 silently."""
    at = TABLE_OFFSET + 4 * index
    if payload[at]:
        raise ValueError(f"AHCM section item {index} has a nonzero spare byte")
    return int.from_bytes(payload[at + 1:at + 4], "little")


def _sections(payload: bytes, checksum_offset: int) -> tuple[int | None, ...]:
    """Section offsets relative to the payload, indexed by the One's section numbers."""
    sections: list[int | None] = [None] * SECTION_COUNT
    for slot, section in enumerate(SLOT_SECTIONS):
        absolute = _item(payload, slot)
        relative = absolute - BASE
        if not absolute or not 0 <= relative < checksum_offset:
            raise ValueError(
                f"AHCM slot {slot} (section {section}) points outside the configuration: "
                f"{absolute:#08x}")
        sections[section] = relative
    for slot in range(len(SLOT_SECTIONS), TABLE_ITEMS):
        if _item(payload, slot):
            raise ValueError(f"AHCM slot {slot} is set where every 5xx leaves it empty")
    present = [offset for offset in sections if offset is not None]
    if len(present) != len(set(present)):
        raise ValueError("AHCM section pointers are not unique")
    return tuple(sections)


def validate(payload: bytes) -> dict:
    """Validate the conditions the architecture-9 format sets, measured on every 5xx
    configuration read so far."""
    if not isinstance(payload, bytes):
        raise TypeError("AHCM payload must be bytes")
    if len(payload) < BUTTON_MAP_OFFSET + len(BUTTON_MAP_MAGIC) + 1:
        raise ValueError("AHCM payload is shorter than its fixed header")
    if len(payload) >= MAX_SAFE_SIZE:
        raise ValueError(
            f"AHCM payload is {len(payload):#x} bytes; the configuration region ends at "
            f"{MAX_SAFE_SIZE:#x}")
    if payload[:4] != MAGIC:
        raise ValueError(f"AHCM magic is {payload[:4]!r}, expected {MAGIC!r}")

    end_vector, constant = struct.unpack_from("<II", payload, 4)
    if constant != HEADER_CONSTANT:
        raise ValueError(
            f"AHCM header word is {constant:#x}, expected {HEADER_CONSTANT:#x} "
            f"({TABLE_ITEMS} section items)")
    marker_offset = end_vector - BASE
    if marker_offset < 2 or marker_offset + 4 != len(payload):
        raise ValueError(
            f"AHCM end vector {end_vector:#08x} does not point at the final MCHA marker")
    if payload[marker_offset:marker_offset + 4] != END_MAGIC:
        raise ValueError("AHCM end vector does not point at MCHA")
    end = BUTTON_MAP_OFFSET + len(BUTTON_MAP_MAGIC)
    if payload[BUTTON_MAP_OFFSET:end] != BUTTON_MAP_MAGIC:
        raise ValueError(
            f"AHCM marker {BUTTON_MAP_MAGIC.decode()} is absent at {BUTTON_MAP_OFFSET:#x}")

    checksum_offset = marker_offset - 2
    actual = checksum(payload, checksum_offset)
    stored = tuple(payload[checksum_offset:marker_offset])
    if actual != stored:
        raise ValueError(
            "AHCM checksum mismatch: "
            f"computed {actual[0]:02x}{actual[1]:02x}, "
            f"stored {stored[0]:02x}{stored[1]:02x}")

    sections = _sections(payload, checksum_offset)
    return {
        "ok": True,
        "validator": "harmony-555/ahcm-structural",
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
