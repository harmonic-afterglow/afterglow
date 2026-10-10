#!/usr/bin/env python3
"""Complete a scaffold font to the whole printable ASCII set.

    python3 tools/harmony_one_font_fill.py src/afterglow/scaffolds/harmony-one --height 14

## Why this exists

A Harmony One font carries only the characters the configuration it came from happened to
draw, because the vendor emitted a subset of their library into each one. Across all four
donors that is 78 of the 95 printable ASCII characters, and no donor has `$%&;<=>@[]^_`
`` ` ``, `{|}~` at any size. A configuration generated from a project has to label a
button with whatever the owner typed, so a font that cannot spell it is not usable.

Most of the gap is filled from the font's own strokes rather than drawn freehand, which is
the only way a new character looks like it belongs: `\\` is `/` mirrored, `=` is the hyphen
twice, `_` is the hyphen at the descender, `;` is the colon's dot over the comma's tail,
`$` is `S` with a bar through it, `[` is a stem with two arms cut from the hyphen. What has
no relative in the font - `&`, `@`, `%`, `~`, the braces - is drawn here, on the same grid
and at the same two-pixel stroke.

Colour is not drawn at all. Every donor font is one colour plus a shadow one pixel down
and to the right, which holds for every glyph in every font measured, so a new glyph is
designed as a shape and the palette is applied afterwards.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from afterglow import imaging  # noqa: E402
from afterglow.backends.harmony_one import assets  # noqa: E402


PRINTABLE = [chr(code) for code in range(0x20, 0x7F)]


def mask_of(rows, palette):
    """The glyph's own stroke, without its shadow."""
    ink = palette[0]
    return [[pixel == ink for pixel in row] for row in rows]


def palette_of(fonts_rows):
    seen = {}
    for rows in fonts_rows:
        for row in rows:
            for pixel in row:
                if pixel is not None:
                    seen[pixel] = seen.get(pixel, 0) + 1
    return sorted(seen, key=lambda colour: (-sum(colour), colour))


def shade(mask, palette, height):
    """Apply the font's colours: the stroke, then its shadow one pixel down and right."""
    width = len(mask[0])
    out = [[None] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if mask[y][x]:
                out[y][x] = palette[0]
            elif (len(palette) > 1 and y and x
                  and mask[y - 1][x - 1]):
                out[y][x] = palette[1]
    return out


def blank(width, height):
    return [[False] * width for _ in range(height)]


def mirrored(mask):
    return [list(reversed(row)) for row in mask]


def shifted(mask, dx, dy, width=None):
    height = len(mask)
    width = width if width is not None else len(mask[0])
    out = blank(width, height)
    for y, row in enumerate(mask):
        for x, on in enumerate(row):
            if on and 0 <= y + dy < height and 0 <= x + dx < width:
                out[y + dy][x + dx] = True
    return out


def over(*masks):
    height = len(masks[0])
    width = max(len(m[0]) for m in masks)
    out = blank(width, height)
    for mask in masks:
        for y, row in enumerate(mask):
            for x, on in enumerate(row):
                if on:
                    out[y][x] = True
    return out


def widened(mask, width):
    return [row + [False] * (width - len(row)) for row in mask]


def rows_of(mask):
    return [y for y, row in enumerate(mask) if any(row)]


def draw(art, height, width):
    """Turn pixel art into a mask, padded to the font's cell."""
    out = blank(width, height)
    for y, line in art.items():
        for x, character in enumerate(line):
            if character == "#" and y < height and x < width:
                out[y][x] = True
    return out


def metrics(masks: dict[str, list]) -> dict:
    """Read the font's own grid off the letters it already has."""
    out = {}
    for name, character, edge in (
            ("cap_top", "H", min), ("baseline", "H", max),
            ("x_top", "x", min), ("descender", "p", max)):
        mask = masks.get(character)
        rows = rows_of(mask) if mask else []
        if rows:
            out[name] = edge(rows)
    out.setdefault("cap_top", 3)
    out.setdefault("baseline", len(next(iter(masks.values()))) - 4)
    out.setdefault("x_top", out["cap_top"] + 2)
    out.setdefault("descender", out["baseline"] + 2)
    return out


# Symbols with no relative among the font's own letters, drawn on the cap grid: eight rows
# from the cap line to the baseline, two pixels of stroke, the same as every capital.
DESIGNS = {
    "<": ["...##", "..##.", ".##..", "##...", "##...", ".##..", "..##.", "...##"],
    ">": ["##...", ".##..", "..##.", "...##", "...##", "..##.", ".##..", "##..."],
    "{": ["..###", ".##..", ".##..", "###..", "###..", ".##..", ".##..", "..###"],
    "}": ["###..", "..##.", "..##.", "..###", "..###", "..##.", "..##.", "###.."],
    "^": ["..##..", ".####.", "##..##", "......", "......", "......", "......", "......"],
    "~": ["......", "......", "......", ".##..#", "##.###", "#...##", "......", "......"],
    # An ampersand whose bowls are the same size reads as an eight. The upper bowl is
    # kept small and the tail left open to the lower right, which is what tells them
    # apart at this size.
    "&": ["..###...", ".##.##..", ".##.##..", "..###...", ".###.##.", "##.###..",
          "##..##..", ".###.##."],
    "@": [".#####..", "##...##.", "##.###.#", "##.##.##", "##.##.##", "##.####.",
          "##......", ".#####.."],
    "%": ["##...##", "##..##.", "....##.", "...##..", "..##...", ".##..##", "##...##",
          "....###"],
}


def derive(character: str, masks: dict, grid: dict, height: int):
    """Build a missing glyph out of the font's own strokes where one can be."""
    cap, base = grid["cap_top"], grid["baseline"]
    x_top, descender = grid["x_top"], grid["descender"]
    stem = [[True, True] for _ in range(base - cap + 1)]

    def at(rows_mask, top, width):
        out = blank(width, height)
        for index, row in enumerate(rows_mask):
            for x, on in enumerate(row):
                if on and top + index < height and x < width:
                    out[top + index][x] = True
        return out

    if character == "\\" and "/" in masks:
        return mirrored(masks["/"])
    if character == "`" and "'" in masks:
        return mirrored(masks["'"])
    if character == '"' and "'" in masks:
        tick = masks["'"]
        width = len(tick[0])
        gap = max(2, width)
        return over(widened(tick, width + gap), shifted(tick, gap, 0, width + gap))
    if character == "|":
        return at(stem + [[True, True]] * (descender - base), cap, 3)
    if character in "=_" and "-" in masks:
        bar = [row for row in masks["-"] if any(row)]
        width = len(masks["-"][0])
        if character == "_":
            return at(bar, min(descender, height - 2), width)
        gap = max(2, (base - x_top) // 2)
        return over(at(bar, x_top + 1, width), at(bar, x_top + 1 + gap, width))
    if character == ";" and ":" in masks and "," in masks:
        colon = masks[":"]
        upper = [row if index < (x_top + base) // 2 else [False] * len(row)
                 for index, row in enumerate(colon)]
        return over(widened(upper, len(masks[","][0])), masks[","])
    if character == "$" and "S" in masks:
        letter = masks["S"]
        width = len(letter[0])
        bar = at([[True, True]] * (base - cap + 3), cap - 1, width)
        centre = (width - 2) // 2
        return over(letter, shifted(bar, centre, 0, width))
    if character in "[]" and "-" in masks:
        arm = [[True] * 4]
        body = over(at(stem, cap, 5), at(arm, cap, 5), at(arm, base, 5))
        return body if character == "[" else mirrored(body)
    art = DESIGNS.get(character)
    if art is None:
        return None
    # A design is written for an eight-row cap; a taller font keeps it on the cap line
    # and leaves the extra row at the bottom, which is a pixel short rather than stretched.
    width = max(len(line) for line in art) + 1
    return at([[c == "#" for c in line] for line in art], cap, width)


def fill_font(directory: Path, role: str, entry: dict, wanted: list[str]) -> dict:
    """Add every wanted character the font lacks, and rewrite its sheet."""
    image = imaging.decode((directory / entry["file"]).read_bytes())
    height = entry["height"]
    have, palette_source = {}, []
    for item in entry["glyphs"]:
        cut = [row[item["x"]:item["x"] + item["width"]] for row in image["rows"][:height]]
        rows = [[None if pixel[3] < 128 else pixel[:3] for pixel in row] for row in cut]
        have[item["code"]] = {"char": item.get("char"), "rows": rows,
                              "width": item["width"]}
        palette_source.append(rows)
    palette = palette_of(palette_source)
    if not palette:
        return {"added": [], "entry": entry}
    by_char = {
        item["char"]: mask_of(item["rows"], palette)
        for item in have.values() if item["char"]
    }
    grid = metrics(by_char)

    next_code = max(have) + 1 if have else 1
    added = []
    for character in wanted:
        if character in by_char:
            continue
        if character == " ":
            continue
        mask = derive(character, by_char, grid, height)
        if mask is None:
            continue
        have[next_code] = {"char": character, "width": len(mask[0]),
                           "rows": shade(mask, palette, height)}
        by_char[character] = mask
        added.append(character)
        next_code += 1

    order = sorted(have)
    width = sum(have[code]["width"] for code in order)
    sheet = [[(0, 0, 0, 0)] * width for _ in range(height)]
    placed, cursor = [], 0
    for code in order:
        item = have[code]
        for y, row in enumerate(item["rows"]):
            for x, pixel in enumerate(row):
                if pixel is not None:
                    sheet[y][cursor + x] = (*pixel, 255)
        placed.append({"code": code, "x": cursor, "width": item["width"],
                       "char": item["char"]})
        cursor += item["width"]
    (directory / entry["file"]).write_bytes(imaging.encode(sheet))
    return {"added": added, "entry": {**entry, "glyphs": placed}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--height", type=int, action="append",
                        help="only complete fonts of this height; repeatable")
    args = parser.parse_args()

    manifest = json.loads((args.directory / assets.MANIFEST).read_text("utf-8"))
    wanted = [c for c in PRINTABLE if c != " "]
    report = {}
    for role, entry in sorted(manifest.get("fonts", {}).items()):
        if args.height and entry["height"] not in args.height:
            continue
        result = fill_font(args.directory, role, entry, wanted)
        manifest["fonts"][role] = result["entry"]
        report[role] = result["added"]
    (args.directory / assets.MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8")
    for role, added in sorted(report.items()):
        print(f"{role}: added {len(added)} -> {''.join(added)!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
