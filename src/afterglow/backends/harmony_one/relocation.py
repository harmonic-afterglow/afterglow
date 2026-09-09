"""Fail-closed relocation primitives for Harmony One GSPM sections.

Only pointer fields reached through an independently parsed native structure are
eligible for repair.  This deliberately does not scan arbitrary aligned values and
call them pointers: coincidence is common in bitmap and waveform data.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import gspm


MOVED_SECTIONS = (9, 10, 11)


def append_map(old: bytes, new: bytes) -> tuple[tuple[int, int, int], ...] | None:
    """Return the identity map when ``new`` preserves ``old`` as its prefix."""
    if len(new) < len(old) or new[:len(old)] != old:
        return None
    return ((0, len(old), 0),)


def insertion_map(old_size: int, offset: int, size: int) -> tuple[tuple[int, int, int], ...]:
    """Describe where old bytes land after one insertion into a section body."""
    if isinstance(old_size, bool) or not isinstance(old_size, int) or old_size < 0:
        raise ValueError("old section size must be a non-negative integer")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= old_size:
        raise ValueError("insertion offset must fall inside the old section")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("insertion size must be a non-negative integer")
    if not size or offset == old_size:
        return ((0, old_size, 0),)
    if not offset:
        return ((0, old_size, size),)
    return ((0, offset, 0), (offset, old_size, size))


def validate_map(
        old: bytes, new: bytes, mapping: tuple[tuple[int, int, int], ...], *,
        edited: tuple[tuple[int, int], ...] = (), check_content: bool = True,
) -> None:
    """Require contiguous coverage and unchanged non-edited bytes in every run."""
    cursor = 0
    for start, end, delta in mapping:
        if start != cursor or end < start:
            raise ValueError(f"relocation map has a gap or overlap at {cursor:#x}")
        if start + delta < 0 or end + delta > len(new):
            raise ValueError("relocation map lands outside the new section body")
        if check_content:
            for old_offset in range(start, end):
                if any(a <= old_offset < z for a, z in edited):
                    continue
                if old[old_offset] != new[old_offset + delta]:
                    raise ValueError(
                        "relocation map does not reproduce the old section at "
                        f"{old_offset:#x}")
        cursor = end
    if cursor != len(old):
        raise ValueError(
            f"relocation map covers {cursor} of {len(old)} old section bytes")


def map_offset(mapping: tuple[tuple[int, int, int], ...], offset: int) -> int | None:
    """Translate one old section-local offset, or return ``None`` if deleted."""
    for start, end, delta in mapping:
        if start <= offset < end:
            return offset + delta
    return None


def _pointer(payload: bytes, field: int, width: int, label: str) -> dict:
    if field < 0 or field + width > len(payload):
        raise ValueError(f"{label} pointer field falls outside the GSPM image")
    absolute = int.from_bytes(payload[field:field + width], "little")
    target = absolute - gspm.BASE
    if not 0 <= target < len(payload):
        raise ValueError(f"{label} points outside the GSPM image: {absolute:#08x}")
    return {"field": field, "target": target, "width": width, "label": label}


def pointer_census(payload: bytes) -> list[dict]:
    """Enumerate pointer fields that own the relocation of sections 9, 10 and 11.

    The census covers the master index, section 11's object table, and the full
    section-6 screen/trailer/slot chain.  These are the parsed structures with
    references into the three sections moved by the native authoring strategy.
    """
    ranges = gspm.section_ranges(payload)
    found: dict[int, dict] = {}

    def add(field: int, width: int, label: str) -> int:
        item = _pointer(payload, field, width, label)
        previous = found.setdefault(field, item)
        if previous != item:
            raise ValueError(f"pointer field {field:#x} has conflicting ownership")
        return item["target"]

    for section in range(gspm.SECTION_COUNT):
        field = 0x0C + 4 * section
        if struct.unpack_from("<I", payload, field)[0]:
            add(field, 4, f"master section {section}")

    object_start, object_end = ranges[11]
    object_count = struct.unpack_from("<H", payload, object_start)[0]
    if not object_count or object_start + 2 + 3 * object_count > object_end:
        raise ValueError("GSPM object table exceeds section 11")
    for index in range(object_count):
        add(object_start + 2 + 3 * index, 3, f"section 11 object {index}")

    screen_start, screen_end = ranges[6]
    screen_count = struct.unpack_from("<H", payload, screen_start)[0]
    if (screen_start + 3 > screen_end or payload[screen_start + 2] != 0
            or not screen_count or screen_start + 3 + 3 * screen_count > screen_end):
        raise ValueError("GSPM section 6 has an invalid screen index")
    for screen in range(screen_count):
        trailer = add(
            screen_start + 3 + 3 * screen, 3, f"section 6 screen {screen} trailer")
        if trailer + 6 > len(payload):
            raise ValueError(f"screen {screen} trailer is truncated")
        add(trailer + 1, 3, f"section 6 screen {screen} header")
        slot_count = struct.unpack_from("<H", payload, trailer + 4)[0]
        if not slot_count or trailer + 6 + 3 * slot_count > len(payload):
            raise ValueError(f"screen {screen} has an invalid slot table")
        for slot in range(slot_count):
            slot_offset = add(
                trailer + 6 + 3 * slot, 3,
                f"section 6 screen {screen} slot {slot}")
            if slot_offset + 7 > len(payload):
                raise ValueError(f"screen {screen} slot {slot} is truncated")
            add(slot_offset + 1, 3, f"section 6 screen {screen} slot {slot} key register")
            add(slot_offset + 4, 3, f"section 6 screen {screen} slot {slot} program")

    return [found[field] for field in sorted(found)]


def references_into(payload: bytes, ranges: dict[int, tuple[int, int]]) -> list[dict]:
    """Return census entries whose targets fall in one of ``ranges``."""
    out = []
    for item in pointer_census(payload):
        section = next(
            (index for index, (start, end) in ranges.items()
             if start <= item["target"] < end), None)
        if section is not None:
            out.append({**item, "section": section})
    return out


def repair_integrity(body: bytes) -> bytes:
    """Close a marker-less GSPM body with padding, checksum, and ``PTYY``."""
    out = bytearray(body)
    if len(out) % 2:
        out.append(0)
    marker = len(out) + 2
    out += b"\x00\x00PTYY"
    struct.pack_into("<I", out, 4, gspm.BASE + marker)
    out[marker - 2:marker] = bytes(gspm.checksum(out, marker - 2))
    return bytes(out)


def changed_ranges(before: bytes, after: bytes) -> list[tuple[int, int]]:
    """Return compact half-open ranges containing every changed byte."""
    limit = max(len(before), len(after))
    changed = [
        index for index in range(limit)
        if (before[index] if index < len(before) else None)
        != (after[index] if index < len(after) else None)
    ]
    if not changed:
        return []
    ranges = []
    start = previous = changed[0]
    for index in changed[1:]:
        if index != previous + 1:
            ranges.append((start, previous + 1))
            start = index
        previous = index
    ranges.append((start, previous + 1))
    return ranges


def _section_for(offset: int, ranges: dict[int, tuple[int, int]]) -> int | None:
    return next(
        (index for index, (start, end) in ranges.items() if start <= offset < end),
        None,
    )


def _write_pointer(out: bytearray, field: int, width: int, target: int) -> None:
    absolute = gspm.BASE + target
    if absolute >= 1 << (8 * width):
        raise ValueError(f"relocated pointer {absolute:#x} does not fit in {width} bytes")
    out[field:field + width] = absolute.to_bytes(width, "little")


def relocate(
        payload: bytes, replacements: dict[int, bytes] | None = None, *,
        maps: dict[int, tuple[tuple[int, int, int], ...]] | None = None,
        edited: dict[int, tuple[tuple[int, int], ...]] | None = None,
        extra_object_offsets: tuple[int, ...] = (),
        object_repoints: dict[int, int] | None = None,
) -> tuple[bytes, dict]:
    """Move sections 9, 10 and 11 to the tail and repair every owned reference.

    Old section bytes remain in place as unreachable preservation data. Replacements
    that do more than append require an explicit piecewise map; changed in-place bytes
    must also be declared through ``edited``. The returned report accounts for every
    affected pointer and changed byte range.
    """
    gspm.validate(payload)
    replacements = dict(replacements or {})
    maps = dict(maps or {})
    edited = dict(edited or {})
    object_repoints = dict(object_repoints or {})
    unexpected = set(replacements) - set(MOVED_SECTIONS)
    if unexpected:
        raise ValueError(
            "relocation can replace only sections 9, 10 and 11; got "
            + ", ".join(map(str, sorted(unexpected))))

    old_ranges = gspm.section_ranges(payload)
    moved_ranges = {index: old_ranges[index] for index in MOVED_SECTIONS}
    references = references_into(payload, moved_ranges)
    bodies = {
        index: bytes(replacements.get(index, payload[start:end]))
        for index, (start, end) in moved_ranges.items()
    }
    section_maps = {}
    for index in (9, 10):
        start, end = old_ranges[index]
        old = payload[start:end]
        mapping = maps.get(index) or append_map(old, bodies[index])
        if mapping is None:
            raise ValueError(
                f"section {index} changed other than by tail append without a map")
        validate_map(old, bodies[index], mapping, edited=edited.get(index, ()))
        section_maps[index] = mapping

    checksum_offset = struct.unpack_from("<I", payload, 4)[0] - gspm.BASE - 2
    out = bytearray(payload[:checksum_offset])
    new_starts = {}
    for index in (9, 10):
        new_starts[index] = len(out)
        out += bodies[index]

    # Section 11 is rebuilt at the same stride because all of its entries are
    # absolute pointers. Its own old bytes retain identity local positions.
    object_start, object_end = old_ranges[11]
    object_count = struct.unpack_from("<H", payload, object_start)[0]
    object_targets = [
        int.from_bytes(
            payload[object_start + 2 + 3 * index:object_start + 5 + 3 * index],
            "little",
        ) - gspm.BASE
        for index in range(object_count)
    ]
    translated_objects = []
    old10_start, old10_end = old_ranges[10]
    repointed_fields = {}
    for object_id, target in enumerate(object_targets):
        if object_id in object_repoints:
            local = object_repoints[object_id]
            if not 0 <= local < len(bodies[10]):
                raise ValueError(
                    f"object {object_id} repoint falls outside new section 10")
            target = new_starts[10] + local
            repointed_fields[object_start + 2 + 3 * object_id] = target
            translated_objects.append(target)
            continue
        if old10_start <= target < old10_end:
            local = map_offset(section_maps[10], target - old10_start)
            if local is None:
                raise ValueError("a section 11 object target was deleted by relocation")
            target = new_starts[10] + local
        translated_objects.append(target)
    for local in extra_object_offsets:
        if isinstance(local, bool) or not isinstance(local, int) or not 0 <= local < len(bodies[10]):
            raise ValueError("extra object offsets must fall inside new section 10")
        translated_objects.append(new_starts[10] + local)

    old_table_size = 2 + 3 * object_count
    section11 = bytearray(len(translated_objects).to_bytes(2, "little"))
    for target in translated_objects:
        absolute = gspm.BASE + target
        if absolute >= 1 << 24:
            raise ValueError("section 11 object pointer does not fit in 24 bits")
        section11 += absolute.to_bytes(3, "little")
    section11 += payload[object_start + old_table_size:object_end]
    if 11 in replacements and bytes(section11) != bodies[11]:
        raise ValueError("section 11 is derived from the object table and cannot be replaced")
    inserted = 3 * len(extra_object_offsets)
    section_maps[11] = insertion_map(
        object_end - object_start, old_table_size, inserted)
    validate_map(
        payload[object_start:object_end], bytes(section11), section_maps[11],
        check_content=False,
    )
    new_starts[11] = len(out)
    out += section11

    for index, start in new_starts.items():
        _write_pointer(out, 0x0C + 4 * index, 4, start)

    rebuilt_table_fields = {
        object_start + 2 + 3 * index for index in range(object_count)
    }
    master_fields = {0x0C + 4 * index for index in MOVED_SECTIONS}
    for item in references:
        if item["field"] in master_fields or item["field"] in rebuilt_table_fields:
            continue
        target_start = old_ranges[item["section"]][0]
        local = map_offset(section_maps[item["section"]], item["target"] - target_start)
        if local is None:
            raise ValueError(f"{item['label']} points at bytes deleted by relocation")
        field = item["field"]
        owner = _section_for(field, moved_ranges)
        if owner is not None:
            field_local = map_offset(section_maps[owner], field - old_ranges[owner][0])
            if field_local is None:
                raise ValueError(f"the {item['label']} field was deleted by relocation")
            field = new_starts[owner] + field_local
        _write_pointer(out, field, item["width"], new_starts[item["section"]] + local)

    result = repair_integrity(bytes(out))
    if len(result) >= gspm.MAX_SAFE_SIZE:
        raise ValueError("relocated GSPM image reaches the protected backup region")
    new_ranges = gspm.section_ranges(result)

    failures = []
    for item in references:
        target_start = old_ranges[item["section"]][0]
        local = map_offset(section_maps[item["section"]], item["target"] - target_start)
        if local is None:
            failures.append(f"{item['label']}: target was deleted")
            continue
        expected = repointed_fields.get(
            item["field"], new_starts[item["section"]] + local)
        field = item["field"]
        owner = _section_for(field, moved_ranges)
        if owner is not None:
            field_local = map_offset(section_maps[owner], field - old_ranges[owner][0])
            field = None if field_local is None else new_starts[owner] + field_local
        if field is None:
            failures.append(f"{item['label']}: pointer field was deleted")
            continue
        actual = int.from_bytes(result[field:field + item["width"]], "little") - gspm.BASE
        if actual != expected:
            failures.append(
                f"{item['label']}: points at {actual:#x}, expected {expected:#x}")
            continue
        if item["section"] == 11 or item["field"] in repointed_fields:
            continue
        old_available = old_ranges[item["section"]][1] - item["target"]
        sample = min(24, old_available)
        for index in range(sample):
            old_local = item["target"] - target_start + index
            if any(a <= old_local < z for a, z in edited.get(item["section"], ())):
                continue
            if payload[item["target"] + index] != result[expected + index]:
                failures.append(f"{item['label']}: pointed content changed at +{index:#x}")
                break
    if failures:
        raise RuntimeError(
            f"{len(failures)} relocated pointers failed verification: "
            + "; ".join(failures[:8]))

    stale = [
        item for item in references_into(result, moved_ranges)
        if _section_for(item["field"], moved_ranges) is None
    ]
    if stale:
        raise RuntimeError(
            f"{len(stale)} live pointer fields still target vacated section bytes")

    return result, {
        "mode": "append-only-section-relocation",
        "sections": {
            index: {
                "old": list(old_ranges[index]), "new": list(new_ranges[index]),
                "old_size": old_ranges[index][1] - old_ranges[index][0],
                "new_size": new_ranges[index][1] - new_ranges[index][0],
            }
            for index in MOVED_SECTIONS
        },
        "repaired_pointers": len(references),
        "changed_ranges": [list(item) for item in changed_ranges(payload, result)],
        "old_size": len(payload),
        "new_size": len(result),
        "repointed_objects": len(object_repoints),
    }
