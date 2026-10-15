#!/usr/bin/env python3
"""Extract the Harmony 800's platform state into scaffolds/harmony-800/platform/platform.json.

    python3 tools/harmony_800_extract_platform.py EMBEDDEDCFG.bin USERCFG.bin

``EMBEDDEDCFG.bin`` is a factory remote's `/fw/embeddedcfg` and ``USERCFG.bin`` its
`/cfg/usercfg` (read over MH, e.g. with tools/harmony_probe). Only platform state is taken -
the constant sections, the engine records and the property tables - never a device, a
screen's words or anything that identifies a remote. Neither image is written into the tree.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow.backends.harmony_800 import gsgd  # noqa: E402


def _bounds(payload: bytes) -> dict[int, tuple[int, int]]:
    starts = gsgd.sections(payload)
    ends = sorted(set(starts)) + [len(payload) - 6]
    return {n: (start, ends[ends.index(start) + 1]) for n, start in enumerate(starts)}


def _u24(payload: bytes, offset: int, base: int) -> int:
    return int.from_bytes(payload[offset:offset + 3], "little") - base


def engine(payload: bytes) -> dict:
    """Section 14: its eight-byte head, then the records its pointers name, in order."""
    base = gsgd.base_of(payload)
    start, _end = _bounds(payload)[14]
    count = struct.unpack_from("<H", payload, start)[0]
    pointers = [_u24(payload, start + 8 + 3 * i, base) for i in range(count)]
    ends = sorted(set(pointers))
    records = []
    for pointer in pointers:
        later = [p for p in ends if p > pointer]
        records.append(payload[pointer:later[0] if later else pointer + 7])
    # A record's own length: three u16 fields, a byte, eight bytes per transition.
    sized = []
    for record in records:
        transitions = struct.unpack_from("<H", record, 4)[0]
        size = 7 + 8 * transitions
        if size > len(record):
            raise ValueError(f"an engine record runs into the next: {record.hex()}")
        sized.append(record[:size].hex())
    return {"head": payload[start:start + 8].hex(), "records": sized}


def properties(payload: bytes) -> dict:
    """Section 15's property tables - after its switch-table count and pointers - and
    section 16's pointers into them, as offsets into the tables."""
    base = gsgd.base_of(payload)
    bounds = _bounds(payload)
    start15, end15 = bounds[15]
    start16, _ = bounds[16]
    count = payload[start16]
    pointers = [_u24(payload, start16 + 1 + 3 * i, base) for i in range(count)]
    tail = min(pointers)
    if not start15 <= tail < end15:
        raise ValueError("section 16 does not point into section 15")
    return {"tail": payload[tail:end15].hex(), "tables": [p - tail for p in pointers]}


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    embedded = gsgd.trimmed(Path(sys.argv[1]).read_bytes())
    user = gsgd.trimmed(Path(sys.argv[2]).read_bytes())
    gsgd.validate(embedded)
    gsgd.validate(user)
    if gsgd.base_of(embedded) != gsgd.EMBEDDED_BASE or gsgd.base_of(user) != gsgd.BASE:
        raise SystemExit("give the embedded configuration first, then the user configuration")
    bounds = _bounds(embedded)
    platform = {
        "_comment": "Logitech's Harmony 800 platform state, from a factory remote's "
                    "/fw/embeddedcfg (sections 0-3, 17, 18, the engine records) and "
                    "/cfg/usercfg (the property tables). See NOTICE.md.",
        "sections": {str(n): embedded[slice(*bounds[n])].hex() for n in (0, 1, 2, 3, 17, 18)},
        "engine": engine(embedded),
        "properties": properties(user),
    }
    out = ROOT / "src/afterglow/scaffolds/harmony-800/platform/platform.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(platform, indent=1) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
