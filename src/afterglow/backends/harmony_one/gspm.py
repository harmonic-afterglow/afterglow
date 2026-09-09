"""Structural validation for the Harmony One's indexed configuration image.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct


BASE = 0x040000
MAGIC = b"GSPM"
HEADER_CONSTANT = 0x1600
BUTTON_MAP_OFFSET = 0x63
BUTTON_MAP_MAGIC = b"LWJL7"
SECTION_COUNT = 20
ABSENT_SECTION = 8
CHECKSUM_SEED = (0x21, 0x43)
MAX_SAFE_SIZE = 0x390000


def checksum(data: bytes, end: int) -> tuple[int, int]:
    """Return the firmware's two-lane XOR over complete pairs before ``end``."""
    low, high = CHECKSUM_SEED
    for offset in range(0, end - end % 2, 2):
        low ^= data[offset]
        high ^= data[offset + 1]
    return low, high


def _sections(payload: bytes, checksum_offset: int) -> tuple[int | None, ...]:
    sections = []
    for index in range(SECTION_COUNT):
        absolute = struct.unpack_from("<I", payload, 0x0C + index * 4)[0]
        if not absolute:
            sections.append(None)
            continue
        relative = absolute - BASE
        if not 0 <= relative < checksum_offset:
            raise ValueError(
                f"GSPM section {index} points outside the configuration: {absolute:#08x}")
        sections.append(relative)
    present = [offset for offset in sections if offset is not None]
    if len(present) != len(set(present)):
        raise ValueError("GSPM section pointers are not unique")
    if sections[ABSENT_SECTION] is not None or len(present) != SECTION_COUNT - 1:
        raise ValueError("GSPM master index is not the measured 19-section arch-12 layout")
    return tuple(sections)


def validate(payload: bytes) -> dict:
    """Validate independently measured conditions enforced by the arch-12 format."""
    if not isinstance(payload, bytes):
        raise TypeError("GSPM payload must be bytes")
    if len(payload) < BUTTON_MAP_OFFSET + len(BUTTON_MAP_MAGIC):
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
    if payload[BUTTON_MAP_OFFSET:BUTTON_MAP_OFFSET + 5] != BUTTON_MAP_MAGIC:
        raise ValueError("GSPM arch-12 button-map marker LWJL7 is absent at +0x63")

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
        "validator": "harmony-one/gspm-structural",
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
