"""Read the owned section-0 named-record chain in Harmony One images.

Restricting the grammar to section 0 and requiring a contiguous chain closed by `BEEF`
prevents ordinary bitmap or program bytes from becoming names merely because they resemble
an A7 record.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from collections import Counter
import struct

from . import gspm


def inspect(payload: bytes) -> dict:
    """Parse every section-0 record or reject the chain as a whole."""
    start, end = gspm.section_ranges(payload)[0]
    if end - start < 7 or payload[start:start + 2] != b"\xed\xfe":
        raise ValueError("section 0 has no FEED named-record header")
    declared = int.from_bytes(payload[start + 2:start + 5], "little")
    if declared != end - start - 2:
        raise ValueError(
            f"section 0 declares {declared} bytes, expected {end - start - 2}")
    cursor = start + 5
    records = []
    rejected = Counter()
    while cursor < end:
        if payload[cursor:cursor + 2] == b"\xef\xbe":
            cursor += 2
            break
        if cursor + 7 > end or payload[cursor] != 0xA7:
            raise ValueError(f"section 0 record chain breaks at {cursor:#x}")
        length, record_type, identifier = struct.unpack_from("<HHH", payload, cursor + 1)
        name_length = length - 4
        record_end = cursor + 3 + length
        if name_length < 1 or record_end > end:
            raise ValueError(f"section 0 record at {cursor:#x} has invalid length {length}")
        raw = payload[cursor + 7:record_end]
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError:
            name = None
            rejected["non_utf8_name"] += 1
        records.append({
            "offset": cursor, "length": length, "type": record_type,
            "id": identifier, "name": name, "raw_name": raw.hex(),
        })
        cursor = record_end
    if cursor != end:
        raise ValueError("section 0 record terminator is not at the section boundary")
    duplicate_ids = Counter(
        record["id"] for record in records if record["type"] == 1
    )
    rejected["duplicate_leaf_id"] += sum(count - 1 for count in duplicate_ids.values())
    return {
        "counts": {
            "records": len(records),
            "containers": sum(record["type"] == 0 for record in records),
            "leaves": sum(record["type"] == 1 for record in records),
            "other_types": sum(record["type"] not in (0, 1) for record in records),
        },
        "rejected": {key: value for key, value in rejected.items() if value},
        "records": records,
    }


def leaf_names(report: dict) -> dict[int, str]:
    """Return only uniquely owned, decodable leaf names by native identifier."""
    grouped: dict[int, list[str]] = {}
    for record in report["records"]:
        if record["type"] == 1 and record["name"] is not None:
            grouped.setdefault(record["id"], []).append(record["name"])
    return {
        identifier: names[0]
        for identifier, names in grouped.items() if len(names) == 1
    }
