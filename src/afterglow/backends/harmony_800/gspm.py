"""The Harmony 800's image, under the names the One's code reaches it by.

This backend began as a copy of the Harmony One's, and its modules address the image
through this module as the One's address `GSPM`: its base, its marker, its sections, its
seal. Here those names are the 800's `GSGD` (gsgd.py): base `0x050000`, `CHJL`, `OGSA`, all
twenty sections present.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

import struct

from . import gsgd

BASE = gsgd.BASE
MAGIC = gsgd.MAGIC
HEADER_CONSTANT = gsgd.HEADER_CONSTANT
BUTTON_MAP_OFFSET = gsgd.MARKER_OFFSET
BUTTON_MAP_MAGIC = gsgd.MARKER
SECTION_COUNT = gsgd.SECTION_COUNT
ABSENT_SECTION = None            # the One leaves section 8 out; the 800 has all twenty
CHECKSUM_SEED = gsgd.CHECKSUM_SEED
MAX_SAFE_SIZE = gsgd.PARTITION_SIZE
CLOSE = gsgd.CLOSE

checksum = gsgd.checksum


def seal(body: bytes) -> bytes:
    """Close a body with the checksum and ``OGSA``, the header's end vector set to it. The
    body is padded to an even length first: the firmware's checksum takes an odd last byte
    in and Concordance's leaves it out, and a remote whose checksum disagrees falls back to
    its embedded configuration ("Go to Website to update settings")."""
    out = gsgd.even(bytearray(body))
    marker = len(out) + 2
    out += b"\x00\x00" + CLOSE
    struct.pack_into("<I", out, 4, BASE + marker)
    out[marker - 2:marker] = bytes(checksum(out, marker - 2))
    return bytes(out)


def validate(payload: bytes) -> dict:
    return gsgd.validate(payload)


def section_ranges(payload: bytes) -> dict[int, tuple[int, int]]:
    """Every section's range relative to the payload: from its start to the next one's."""
    validate(payload)
    payload = gsgd.trimmed(payload)
    starts = gsgd.sections(payload)
    boundaries = sorted(set(starts)) + [len(payload) - 6]
    return {index: (start, boundaries[boundaries.index(start) + 1])
            for index, start in enumerate(starts)}
