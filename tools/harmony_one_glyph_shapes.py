#!/usr/bin/env python3
"""Record which character each Harmony One glyph shape draws, from real configurations.

A Harmony One draws all its text as glyph codes, and the code a character gets differs
from image to image: four household layouts are established (glyph_codec.py), and others
exist - Kāt's living-room configuration counts 74 and orders them its own way. The shapes
do not differ: Logitech's fonts are the same faces in every image. So a configuration
whose layout is established says which character each of its shapes is, and that reads
the text of any other.

This writes those shapes - fingerprints of each glyph's pixels, not the pixels - with the
character they draw, to the scaffold (platform/glyph-shapes.json), for the importer
(labels.py). Some faces draw two characters alike - a capital I and a small l - so such a
shape is kept with every character it was seen drawing, and the importer tells them apart
by which of them the image already has another code for.

    tools/harmony_one_glyph_shapes.py CONFIG.ezhex [CONFIG.ezhex ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex, paths  # noqa: E402
from afterglow.backends.harmony_one import font_index, glyph_codec  # noqa: E402
from afterglow.backends.harmony_one.labels import SHAPES_FILE  # noqa: E402


def shapes_of(payload: bytes) -> dict[str, set[str]] | None:
    """Each shape in ``payload`` with the characters its established layout gives it;
    None when the layout is not established."""
    report = glyph_codec.inspect(payload)
    if report.get("error"):
        return None
    out = defaultdict(set)
    for font in font_index.fonts(payload):
        for code, glyph in font["glyphs"].items():
            character = report["code_to_character"].get(code)
            if character is None or character == glyph_codec.WIDE_BLANK:
                continue
            # a font that lacks a character draws nothing for it; blank is a space
            if character != " " and glyph["shape"] == blank(glyph["width"], glyph["height"]):
                continue
            out[glyph["shape"]].add(character)
    return out


def blank(width: int, height: int) -> str:
    """The fingerprint of a glyph with no pixels drawn."""
    return hashlib.sha256(bytes([width, height]) + bytes(width * height)).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("configs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path,
                        default=paths.scaffolds("harmony-one") / SHAPES_FILE)
    args = parser.parse_args(argv)
    seen = defaultdict(set)
    used = 0
    for path in args.configs:
        with tempfile.TemporaryDirectory() as work:
            ezhex.unpack(str(path), work)
            payload = (Path(work) / "payload.bin").read_bytes()
        shapes = shapes_of(payload)
        if shapes is None:
            print(f"{path.name}: its glyph layout is not established; skipped")
            continue
        used += 1
        for shape, characters in shapes.items():
            seen[shape] |= characters
    table = {shape: "".join(sorted(chars)) for shape, chars in sorted(seen.items())}
    alike = sum(len(chars) > 1 for chars in seen.values())
    args.out.write_text(json.dumps({
        "schema": "afterglow-harmony-one-glyph-shapes/1",
        "configurations": used,
        "shapes": table,
    }, indent=1, ensure_ascii=False) + "\n", "utf-8")
    print(f"{len(table)} shapes from {used} configurations, {alike} drawing more than one "
          f"character -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
