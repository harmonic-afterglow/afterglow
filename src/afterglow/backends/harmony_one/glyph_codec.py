"""Decode Harmony One text with the repertoire declared by its native image.

Harmony One firmware families do not all assign the same character to the same
numeric glyph code. The section-7 repertoire size identifies the four layouts
currently established by independent images; unknown layouts remain undecoded.
Bitmap parsing is still required so a claimed layout cannot silently include a
code for which the image has no drawable glyph.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import gspm, ui_index


_COMMON = {
    0x01: "H", 0x02: "y", 0x03: "S", 0x04: "u", 0x05: "n", 0x06: "M",
    0x07: "o", 0x08: "T", 0x09: "e", 0x0A: "W", 0x0B: "d", 0x0C: "h",
    0x0D: "F", 0x0E: "r", 0x0F: "i", 0x10: "a", 0x11: "t", 0x12: "1",
    0x13: "2", 0x14: ":", 0x15: "3", 0x16: "4", 0x17: "5", 0x18: "6",
    0x19: "7", 0x1A: "8", 0x1B: "9", 0x1C: "0", 0x1D: "/", 0x1E: " ",
    0x1F: "b", 0x20: "l", 0x21: "v", 0x22: "s", 0x23: "w", 0x24: "!",
    0x25: "O", 0x26: "K", 0x27: "U", 0x28: "B", 0x29: "C", 0x2A: "c",
    0x2B: "p", 0x2C: "f", 0x2D: "g", 0x2E: "L", 0x2F: ".", 0x30: "m",
    0x31: "G", 0x32: "I", 0x33: "z", 0x34: "k", 0x35: "R", 0x36: "E",
    0x37: "D", 0x38: "P", 0x39: "A", 0x3A: "q", 0x3B: "\\", 0x3C: "N",
}

WIDE_BLANK = "\N{OPEN BOX}"

# The 71-code layout is RE-Harmony's derivation from a household image. The other three
# were read from independent 72-, 77-, and 79-code donor font sheets and
# cross-checked against their on-screen device labels. Keeping the layouts
# separate is essential: their suffixes are permutations, not extensions.
# The Harmony One factory configuration shipped in firmware 54.2.5 carries its own
# 46-glyph font, and its 56 system messages read back exactly under this table - "Go to
# Website", "FLASH Memory Erase", "Battery Trickle\\Charge" and the rest. It is not an
# extension of the household layouts: after the first two codes it runs in first-use
# order over its own strings. That it also begins H, y is what corroborates the
# household tables, which were derived from entirely different images.
_FACTORY_46 = dict(enumerate(
    "HyGo tWebsiupdangUSBIlzrLckRTmCEDPhFAMfqw\\vNO.", start=1))

REPERTOIRES = {
    46: _FACTORY_46,
    71: _COMMON | dict(zip(
        range(0x3D, 0x48),
        ("x", "?", "Y", "V", WIDE_BLANK, ",", "'", "-", "j", '"', "J"),
        strict=True,
    )),
    72: _COMMON | dict(zip(
        range(0x3D, 0x49),
        ("V", "?", "Y", "-", "j", "x", '"', ",", "+", "'", "Z", "J"),
        strict=True,
    )),
    77: _COMMON | dict(zip(
        range(0x3D, 0x4E),
        ("V", "x", "?", "Y", ",", "'", "-", "j", '"', "(", ")",
         WIDE_BLANK, "J", "+", "Q", "X", "Z"),
        strict=True,
    )),
    79: _COMMON | dict(zip(
        range(0x3D, 0x50),
        ("x", "?", "Y", "X", ",", "V", "-", "(", ")", '"', "+", "j",
         WIDE_BLANK, "J", "Q", "Z", "'", "#", "*"),
        strict=True,
    )),
}

assert all(len(table) == size for size, table in REPERTOIRES.items())
assert all(len(set(table.values())) == size for size, table in REPERTOIRES.items())


def code_shapes(payload: bytes) -> dict[int, set[str]]:
    """Return every decoded bitmap-shape fingerprint grouped by glyph code."""
    start, end = gspm.section_ranges(payload)[7]
    font_count = struct.unpack_from("<H", payload, start)[0]
    if start + 2 + 3 * font_count > end:
        raise ValueError("section 7 font index exceeds its section")
    out: dict[int, set[str]] = {}
    for attribute in range(font_count):
        field = start + 2 + 3 * attribute
        font = int.from_bytes(payload[field:field + 3], "little") - gspm.BASE
        if not 0 <= font + 3 <= len(payload):
            raise ValueError(f"font {attribute} pointer falls outside the image")
        count = struct.unpack_from("<H", payload, font + 1)[0]
        if font + 3 + 3 * count > len(payload):
            raise ValueError(f"font {attribute} glyph index is truncated")
        for index in range(count):
            out.setdefault(index + 1, set())
            absolute = int.from_bytes(
                payload[font + 3 + 3 * index:font + 6 + 3 * index], "little")
            if not absolute:
                continue
            info = ui_index._glyph_shape(payload, absolute - gspm.BASE)
            out[index + 1].add(info["shape"])
    return out


def declared_repertoire(payload: bytes) -> int:
    """Return the largest glyph-slot count declared by any section-7 font."""
    start, end = gspm.section_ranges(payload)[7]
    font_count = struct.unpack_from("<H", payload, start)[0]
    if start + 2 + 3 * font_count > end:
        raise ValueError("section 7 font index exceeds its section")
    repertoire = 0
    for attribute in range(font_count):
        field = start + 2 + 3 * attribute
        font = int.from_bytes(payload[field:field + 3], "little") - gspm.BASE
        if not 0 <= font + 3 <= len(payload):
            raise ValueError(f"font {attribute} pointer falls outside the image")
        repertoire = max(repertoire, struct.unpack_from("<H", payload, font + 1)[0])
    return repertoire


def resolve_mapping(shapes: dict[int, set[str]], repertoire: int | None = None) -> dict:
    """Select a proved repertoire and expose unsupported layouts explicitly."""
    repertoire = max(shapes, default=0) if repertoire is None else repertoire
    table = REPERTOIRES.get(repertoire)
    if table is None:
        return {
            "repertoire": repertoire,
            "code_to_character": {},
            "character_to_code": {},
            "missing_codes": [],
            "unresolved_codes": sorted(shapes),
            "error": f"unsupported Harmony One glyph repertoire: {repertoire}",
        }
    present = {code for code, fingerprints in shapes.items() if fingerprints}
    code_to_character = {
        code: character for code, character in table.items() if code in present
    }
    return {
        "repertoire": repertoire,
        "code_to_character": code_to_character,
        "character_to_code": {
            character: code for code, character in code_to_character.items()
        },
        "missing_codes": sorted(set(table) - present),
        "unresolved_codes": sorted(present - set(table)),
    }


def inspect(payload: bytes) -> dict:
    """Derive this image's mapping and expose explicit unresolved evidence."""
    report = resolve_mapping(code_shapes(payload), declared_repertoire(payload))
    report["counts"] = {
        "repertoire": report["repertoire"],
        "resolved_codes": len(report["code_to_character"]),
        "resolved_characters": len(report["character_to_code"]),
        "missing_codes": len(report["missing_codes"]),
        "unresolved_codes": len(report["unresolved_codes"]),
    }
    return report


def decode(glyphs: bytes, report: dict) -> str:
    """Decode only when every byte belongs to the established repertoire."""
    missing = sorted(set(glyphs) - set(report["code_to_character"]))
    if missing:
        raise ValueError(
            "glyph string contains unresolved codes: "
            + ", ".join(f"{code:#04x}" for code in missing))
    return "".join(report["code_to_character"][code] for code in glyphs)


def encode(text: str, report: dict) -> bytes:
    """Encode only characters established for this native image's repertoire."""
    if not isinstance(text, str) or not text:
        raise ValueError("Harmony One labels must be non-empty strings")
    missing = sorted(set(text) - set(report["character_to_code"]))
    if missing:
        raise ValueError(
            "label contains characters not established for this image: "
            + ", ".join(repr(character) for character in missing))
    return bytes(report["character_to_code"][character] for character in text)
