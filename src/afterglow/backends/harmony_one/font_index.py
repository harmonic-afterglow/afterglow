"""Complete a Harmony One font from the glyphs its own image already contains.

A font indexes the whole repertoire but carries only the glyphs its own labels needed,
which is why a title or menu row cannot always be renamed to what a user wants. The
missing glyphs often exist in the image already, in another font of the same typeface
that happened to need them, and filling a null slot with one of those is the smallest
possible change: no glyph data is written, the record does not move or change size, and
nothing that draws today can be affected, because a label using that code could not have
been drawn before.

Two fonts count as the same typeface only when they declare the same height and every
code they both carry has an identical decoded shape. Where compatible fonts disagree
about a code, that code is left unresolved rather than picked from one of them.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import gspm, relocation, ui_index


def fonts(payload: bytes) -> list[dict]:
    """Return every section-7 font with its declared shape and glyph slots."""
    start, end = gspm.section_ranges(payload)[7]
    count = struct.unpack_from("<H", payload, start)[0]
    if start + 2 + 3 * count > end:
        raise ValueError("section 7 font index exceeds its section")
    out = []
    for attribute in range(count):
        field = start + 2 + 3 * attribute
        offset = int.from_bytes(payload[field:field + 3], "little") - gspm.BASE
        if not 0 <= offset + 3 <= len(payload):
            raise ValueError(f"font {attribute} pointer falls outside the image")
        slots = struct.unpack_from("<H", payload, offset + 1)[0]
        if offset + 3 + 3 * slots > len(payload):
            raise ValueError(f"font {attribute} glyph index is truncated")
        glyphs = {}
        empty = []
        for index in range(slots):
            at = offset + 3 + 3 * index
            pointer = int.from_bytes(payload[at:at + 3], "little")
            if not pointer:
                empty.append(index + 1)
                continue
            shape = ui_index._glyph_shape(payload, pointer - gspm.BASE)
            glyphs[index + 1] = {"field": at, "pointer": pointer, **shape}
        out.append({
            "attribute": attribute, "offset": offset, "field": field,
            "height": payload[offset], "slots": slots,
            "glyphs": glyphs, "empty": empty,
        })
    return out


def same_typeface(one: dict, other: dict) -> bool:
    """Whether two fonts are the same face drawn at the same size."""
    if one["attribute"] == other["attribute"] or one["height"] != other["height"]:
        return False
    shared = set(one["glyphs"]) & set(other["glyphs"])
    return bool(shared) and all(
        one["glyphs"][code]["shape"] == other["glyphs"][code]["shape"]
        for code in shared
    )


def completions(payload: bytes) -> dict[int, dict]:
    """Return, per font, the glyph slots its own typeface could fill and those it cannot."""
    table = fonts(payload)
    out = {}
    for font in table:
        donors = [other for other in table if same_typeface(font, other)]
        fill = {}
        disputed = []
        for code in font["empty"]:
            offered = {
                other["glyphs"][code]["shape"]: other["glyphs"][code]["pointer"]
                for other in donors if code in other["glyphs"]
            }
            if not offered:
                continue
            if len(offered) > 1:
                disputed.append(code)
                continue
            fill[code] = next(iter(offered.values()))
        out[font["attribute"]] = {
            "typeface": [other["attribute"] for other in donors],
            "height": font["height"],
            "drawn": len(font["glyphs"]),
            "fill": fill,
            "disputed": disputed,
            "still_empty": len(font["empty"]) - len(fill),
        }
    return out


def complete(payload: bytes, attributes=None) -> tuple[bytes, dict]:
    """Fill empty glyph slots from the same typeface, in place and same-size.

    A font record keeps its address, height and slot count; only null pointers become
    pointers to glyphs the image already holds. Nothing that draws today can change,
    because a label using one of those codes could not be drawn before.
    """
    available = completions(payload)
    chosen = sorted(available) if attributes is None else sorted(set(attributes))
    unknown = [attribute for attribute in chosen if attribute not in available]
    if unknown:
        raise ValueError(
            "this image declares no font attribute "
            + ", ".join(map(str, unknown)))
    table = {font["attribute"]: font for font in fonts(payload)}
    out = bytearray(payload)
    filled = {}
    for attribute in chosen:
        fill = available[attribute]["fill"]
        if not fill:
            continue
        font = table[attribute]
        for code, pointer in sorted(fill.items()):
            at = font["offset"] + 3 + 3 * (code - 1)
            if int.from_bytes(out[at:at + 3], "little"):
                raise RuntimeError(f"font {attribute} glyph {code} is no longer empty")
            out[at:at + 3] = pointer.to_bytes(3, "little")
        filled[attribute] = sorted(fill)
    checksum_offset = int.from_bytes(payload[4:8], "little") - gspm.BASE - 2
    result = relocation.repair_integrity(bytes(out[:checksum_offset]))
    gspm.validate(result)

    before = fonts(payload)
    after = fonts(result)
    for old, new in zip(before, after):
        kept = {
            code: item["pointer"] for code, item in new["glyphs"].items()
            if code in old["glyphs"]
        }
        if kept != {code: item["pointer"] for code, item in old["glyphs"].items()}:
            raise RuntimeError(f"font {old['attribute']} lost or moved a glyph it had")
        gained = set(new["glyphs"]) - set(old["glyphs"])
        if gained != set(filled.get(old["attribute"], ())):
            raise RuntimeError(
                f"font {old['attribute']} gained {sorted(gained)}, not what was asked")
    return result, {
        "mode": "complete-fonts",
        "fonts": {
            attribute: {
                "added": len(codes),
                "drawn": available[attribute]["drawn"] + len(codes),
                "typeface": available[attribute]["typeface"],
            }
            for attribute, codes in filled.items()
        },
        "added": sum(len(codes) for codes in filled.values()),
        "disputed": {
            attribute: available[attribute]["disputed"]
            for attribute in chosen if available[attribute]["disputed"]
        },
        "changed_ranges": [
            list(item) for item in relocation.changed_ranges(payload, result)
        ],
    }
