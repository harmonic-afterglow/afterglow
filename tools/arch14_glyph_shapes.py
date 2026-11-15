#!/usr/bin/env python3
"""Record which character each arch-14 glyph shape draws, from real configurations.

A Harmony 650 or 700 draws its text as glyph codes, and which character a code stands for differs from
image to image past the first fifty or so - each household's own characters are numbered
as they are first used. The shapes do not differ: Logitech's fonts are the same faces in
every arch-14 image. So this learns shapes from what a configuration is known to say and
writes them - fingerprints of each glyph's pixels, not the pixels - to the scaffold
(platform/glyph-shapes.json), for the importer (labels.py).

What a configuration is known to say is its firmware screens: their words are its own
remote's catalogue's (catalogue.NOTICES in that remote's backend). A household character those screens never draw is named by hand, by the
code it has in one configuration (``--read 700-backup.ezhex:61=V``); the tool lists every
code it still cannot read, with the words around it, so they can be. The table only grows:
what an earlier run learned is kept. A configuration whose firmware screens are in another
language than the catalogue's teaches nothing from them, only what ``--read`` names.

    tools/arch14_glyph_shapes.py --remote harmony-700 CONFIG.ezhex [...] \
        [--read NAME:CODE=CHAR ...]

Configurations of either remote may be given; the table is written to ``--remote``'s
scaffold.

Format reference: docs/harmony_650_700/gspm.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex, paths, remotes  # noqa: E402

SOFTKEY_TOP = 108


def backend_of(profile):
    """A remote's backend modules, by name."""
    import importlib

    package = "afterglow.backends." + profile.backend.replace("-", "_")
    return {name: importlib.import_module(f"{package}.{name}")
            for name in ("catalogue", "drawing", "font_index", "labels", "ui_index")}


def payload_of(path: Path) -> tuple[bytes, bytes]:
    raw = path.read_bytes()
    header, start, size, _checksum = ezhex._split(raw)
    return header, raw[start:start + size]


def lines_of(payload: bytes, screens: list, mode: int, ui_index, drawing) -> list[list[int]]:
    """The glyph codes of each line a screen draws above its softkey, in drawing order."""
    out = []

    def walk(at, depth=0):
        if depth > 6:
            return
        for item in ui_index.drawing_program(payload, at)["instructions"]:
            if item["opcode"] in ("text", "inline_text") and item["y"] < SOFTKEY_TOP:
                out.append(drawing.glyph_codes(bytes.fromhex(item["glyphs"])))
            elif item["opcode"] in ("call", "jump"):
                walk(item["target"], depth + 1)

    for slot in screens[mode]["slots"]:
        walk(slot["program_offset"])
    return out


def read_notices(payload: bytes, screens: list, modules: dict
                 ) -> tuple[dict[int, set[str]], list[str]]:
    """Each code's characters, from the firmware screens whose words are known."""
    codes, refused = defaultdict(set), []
    for number, words in sorted(modules["catalogue"].NOTICES.items()):
        drawn = lines_of(payload, screens, number, modules["ui_index"],
                         modules["drawing"])
        expected = words.split("\n")
        if len(drawn) != len(expected):
            refused.append(f"screen {number} draws {len(drawn)} lines, "
                           f"not {len(expected)}")
            continue
        for line, text in zip(drawn, expected):
            if len(line) != len(text):
                refused.append(f"screen {number}: {text!r} is {len(line)} glyphs")
                continue
            for code, character in zip(line, text):
                codes[code].add(character)
    return codes, refused


def context(payload: bytes, screens: list, code: int, modules: dict) -> str:
    """A line the image draws with ``code`` in it, with its codes."""
    for screen in screens:
        for line in lines_of(payload, screens, screen["ordinal"], modules["ui_index"],
                             modules["drawing"]):
            if code in line:
                return f"screen {screen['ordinal']}: {line}"
    return "not drawn"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--remote", required=True,
                        help="the profile whose scaffold the table is written to")
    parser.add_argument("configs", nargs="+", type=Path)
    parser.add_argument("--read", action="append", default=[], metavar="NAME:CODE=CHAR",
                        help="the character a code stands for in the configuration so named")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    own = backend_of(remotes.get(args.remote))
    SHAPES_FILE, SHAPES_SCHEMA = own["labels"].SHAPES_FILE, own["labels"].SHAPES_SCHEMA
    args.out = args.out or paths.scaffolds(args.remote) / SHAPES_FILE

    seen: dict[str, set[str]] = defaultdict(set)
    used = earlier = 0
    if args.out.is_file():
        previous = json.loads(args.out.read_text("utf-8"))
        if previous.get("schema") == SHAPES_SCHEMA:
            for shape, characters in previous["shapes"].items():
                seen[shape] |= set(characters)
            earlier = previous.get("configurations", 0)
    told = defaultdict(dict)
    for item in args.read:
        name, _, rest = item.partition(":")
        code, _, character = rest.partition("=")
        if not name or not code.isdigit() or len(character) != 1:
            parser.error(f"--read {item!r} is not NAME:CODE=CHAR")
        told[name][int(code)] = character

    images = []
    for path in args.configs:
        header, payload = payload_of(path)
        modules = backend_of(remotes.identify(header))
        screens = modules["ui_index"].screen_slots(payload)
        codes, refused = read_notices(payload, screens, modules)
        for note in refused:
            print(f"{path.name}: {note}; not used")
        fonts = modules["font_index"].fonts(payload)
        # A configuration whose firmware screens say other words than the catalogue's -
        # Logitech compiled them in the household's language, Dutch on a Dutch 650 - would
        # teach every shape the wrong character. One shape the table already reads being
        # given another is the sign: then none of its screens are used, and only what
        # --read names is learned from it.
        clashes = {glyph["shape"] for font in fonts for code, glyph in font["glyphs"].items()
                   if code in codes and seen.get(glyph["shape"])
                   and not codes[code] <= seen[glyph["shape"]]}
        if clashes:
            print(f"{path.name}: its firmware screens disagree with the catalogue on "
                  f"{len(clashes)} shapes the table reads (another language?); not used")
            codes = defaultdict(set)
        for code, character in told.get(path.name, {}).items():
            codes[code].add(character)
        for font in fonts:
            for code, glyph in font["glyphs"].items():
                if code in codes:
                    seen[glyph["shape"]] |= codes[code]
        images.append((path, payload, screens, fonts, modules))
        used += 1

    for path, payload, screens, fonts, modules in images:
        known = {code for font in fonts for code, glyph in font["glyphs"].items()
                 if glyph["shape"] in seen}
        unread = sorted({code for font in fonts for code in font["glyphs"]} - known)
        for code in unread:
            print(f"{path.name}: code {code} is not read - {context(payload, screens, code, modules)}")

    table = {shape: "".join(sorted(chars)) for shape, chars in sorted(seen.items())}
    args.out.write_text(json.dumps({
        "schema": SHAPES_SCHEMA,
        "configurations": max(used, earlier),
        "shapes": table,
    }, indent=1, ensure_ascii=False) + "\n", "utf-8")
    alike = sum(len(chars) > 1 for chars in table.values())
    print(f"{len(table)} shapes, {alike} drawing more than one character -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
