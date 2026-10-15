"""The Harmony 800's configuration image: header, section pointers, checksum and close.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

import struct


BASE = 0x050000                 # /cfg/usercfg's address space
EMBEDDED_BASE = 0x030000        # /fw/embeddedcfg's
MAGIC = b"GSGD"
CLOSE = b"OGSA"
MARKER = b"CHJL"
MARKER_OFFSET = 0x63
HEADER_CONSTANT = 0x1600
SECTION_COUNT = 20
HEADER_SIZE = MARKER_OFFSET + len(MARKER) + 1
CHECKSUM_SEED = (0x21, 0x43)
PARTITION_SIZE = 0x390000       # what /cfg/usercfg may hold, close included


def checksum(data: bytes, end: int) -> tuple[int, int]:
    """The firmware's two-lane XOR over every byte before ``end`` (FUN_0800f144): byte
    pairs, and an odd last byte into the low lane. Concordance and the One's tools skip
    that byte, so images are sealed with an even length (`even`) and every reading
    agrees."""
    pairs = end - end % 2
    low, high = CHECKSUM_SEED
    low, high = low ^ _xor(data[0:pairs:2]), high ^ _xor(data[1:pairs:2])
    if end % 2:
        low ^= data[end - 1]
    return low, high


def _xor(lane: bytes) -> int:
    """Every byte XORed together, as the Harmony One's gspm.py folds them: the lane as one
    integer, each half XORed onto the other until a byte is left - the same sum as a byte
    at a time, which took 45 ms over a megabyte, at C speed."""
    value, width = int.from_bytes(lane, "little"), len(lane)
    while width > 1:
        half = (width + 1) // 2
        value = (value & ((1 << (8 * half)) - 1)) ^ (value >> (8 * half))
        width = half
    return value


def even(body: bytearray) -> bytearray:
    """``body`` padded with a zero to an even length, so the checksum covers whole pairs."""
    if len(body) % 2:
        body += b"\x00"
    return body


def header(sections: list[int], close_offset: int, *, base: int = BASE) -> bytes:
    """The fixed header for section offsets and the close marker's offset."""
    if len(sections) != SECTION_COUNT:
        raise ValueError(f"a GSGD image has {SECTION_COUNT} sections, not {len(sections)}")
    out = bytearray(MAGIC + struct.pack("<II", base + close_offset, HEADER_CONSTANT))
    for offset in sections:
        out += struct.pack("<I", base + offset)
    out += bytes(MARKER_OFFSET - len(out)) + MARKER + b"\x00"
    assert len(out) == HEADER_SIZE
    return bytes(out)


def close(body: bytearray) -> bytes:
    """Seal an image whose header already points at the close: checksum, then `OGSA`.
    The body must be of even length (`even`), as the header's end vector was set for it."""
    if len(body) % 2:
        raise ValueError("a GSGD body is sealed at an even length")
    low, high = checksum(body, len(body))
    return bytes(body) + bytes([low, high]) + CLOSE


def base_of(payload: bytes) -> int:
    """The address space an image was written for, from where its end vector points."""
    end_vector = struct.unpack_from("<I", payload, 4)[0]
    for base in (BASE, EMBEDDED_BASE):
        if 0 <= end_vector - base < len(payload):
            return base
    raise ValueError(f"GSGD end vector {end_vector:#08x} fits neither address space")


def trimmed(payload: bytes) -> bytes:
    """An image without the erased flash after it, as a whole-partition read returns."""
    end = struct.unpack_from("<I", payload, 4)[0] - base_of(payload) + len(CLOSE)
    return payload[:end]


def sections(payload: bytes) -> list[int]:
    """Section offsets relative to the image, validated against its length."""
    base = base_of(payload)
    out = []
    for index in range(SECTION_COUNT):
        absolute = struct.unpack_from("<I", payload, 0x0C + 4 * index)[0]
        offset = absolute - base
        if not HEADER_SIZE <= offset < len(payload):
            raise ValueError(f"GSGD section {index} points outside the image: {absolute:#08x}")
        out.append(offset)
    return out


def validate(payload: bytes) -> dict:
    """Check what the firmware checks, and what makes the rest of the image addressable."""
    if not isinstance(payload, bytes):
        raise TypeError("a GSGD image must be bytes")
    if len(payload) < HEADER_SIZE + 6:
        raise ValueError("GSGD image is shorter than its header")
    if payload[:4] != MAGIC:
        raise ValueError(f"GSGD magic is {payload[:4]!r}, expected {MAGIC!r}")
    payload = trimmed(payload)
    if len(payload) > PARTITION_SIZE:
        raise ValueError(f"GSGD image is {len(payload):#x} bytes; /cfg/usercfg holds "
                         f"{PARTITION_SIZE:#x}")
    constant = struct.unpack_from("<I", payload, 8)[0]
    if constant != HEADER_CONSTANT:
        raise ValueError(f"GSGD header constant is {constant:#x}, expected {HEADER_CONSTANT:#x}")
    if payload[MARKER_OFFSET:MARKER_OFFSET + 4] != MARKER:
        raise ValueError(f"GSGD marker {MARKER.decode()} is absent at {MARKER_OFFSET:#x}")
    if payload[-4:] != CLOSE:
        raise ValueError("GSGD end vector does not point at OGSA")
    stored = tuple(payload[-6:-4])
    actual = checksum(payload, len(payload) - 6)
    if actual != stored:
        raise ValueError(f"GSGD checksum mismatch: computed {actual[0]:02x}{actual[1]:02x}, "
                         f"stored {stored[0]:02x}{stored[1]:02x}")
    sections(payload)
    return {
        "ok": True,
        "validator": "harmony-800/gsgd-structural",
        "size": len(payload),
        "base": base_of(payload),
        "checksum": f"{actual[0]:02x}{actual[1]:02x}",
        "sections": SECTION_COUNT,
    }
