"""Complete a Harmony 800 font from the glyphs its own image already contains.

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

from . import gspm, ui_index


# Two font-record headers are established, both three bytes after the height. Every
# household image counts its glyphs in a little-endian u16; the factory configuration in
# Harmony One firmware 54.2.5 counts in the third byte instead, and reading it that way
# is what makes its 46 glyph pointers land exactly on the start of section 7. Neither
# reading can be applied blind, so the count is the one whose index resolves.
WIDE_COUNT = "u16-count"
BYTE_COUNT = "u8-count"


def _glyph_count(payload: bytes, offset: int, attribute: int) -> tuple[int, str]:
    """Return a font's glyph count and which of the two headers it uses."""
    candidates = (
        (struct.unpack_from("<H", payload, offset + 1)[0], WIDE_COUNT),
        (payload[offset + 2], BYTE_COUNT),
    )
    for slots, layout in candidates:
        if not slots or offset + 3 + 3 * slots > len(payload):
            continue
        if all(
            _resolves(payload, offset + 3 + 3 * index) for index in range(slots)
        ):
            return slots, layout
    raise ValueError(
        f"font {attribute} declares no glyph count that resolves; tried "
        + ", ".join(f"{layout} = {slots}" for slots, layout in candidates))


def _resolves(payload: bytes, at: int) -> bool:
    pointer = int.from_bytes(payload[at:at + 3], "little")
    if not pointer:
        return True
    target = pointer - gspm.BASE
    return 0 <= target < len(payload)


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
        slots, layout = _glyph_count(payload, offset, attribute)
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
            "height": payload[offset], "slots": slots, "layout": layout,
            "glyphs": glyphs, "empty": empty,
        })
    return out
