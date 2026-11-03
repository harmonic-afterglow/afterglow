#!/usr/bin/env python3
"""Build Galmuri Afterglow: Galmuri with what the remotes need that it lacks.

    python3 tools/galmuri_afterglow.py              build the fonts
    python3 tools/galmuri_afterglow.py --draft-bold  draft bold letters not yet drawn

Galmuri (Lee Minseo, SIL Open Font License 1.1) draws every size the One uses, but its
smallest, Galmuri7 - the One's clock and page counters - has no Cyrillic or Greek, and
Galmuri9 has no bold, where Logitech's own One draws most of its text two pixels wide.
This writes, beside the One's Galmuri:

- `GalmuriAfterglow7.bdf.gz`: Galmuri7 with the Cyrillic and Greek of
  `tools/galmuri/galmuri7-additions.txt`, drawn in its style;
- `GalmuriAfterglow9-Bold.bdf.gz`: the bold letters of `tools/galmuri/galmuri9-bold.txt`,
  each drawn there and checked by eye. `--draft-bold` adds a draft of any letter the file
  lacks - its strokes a pixel wider, never across a gap a pixel wide, so a counter stays
  open - to be looked at and corrected there; a build reads the file and nothing else, so
  what the remote shows is what the file holds.

A modified version of the font, it keeps the OFL and Galmuri's copyright, under a name of
its own.
"""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import bdf  # noqa: E402

ADDITIONS = ROOT / "tools" / "galmuri" / "galmuri7-additions.txt"
BOLD = ROOT / "tools" / "galmuri" / "galmuri9-bold.txt"
KEYPAD = ROOT / "tools" / "galmuri" / "galmuri-keypad.txt"
FOLDER = ROOT / "src" / "afterglow" / "scaffolds" / "harmony-one" / "fonts" / "galmuri"
# Each bold a remote draws: the size, where it lives, the regular face it is drafted from,
# the letters drawn here, and the designer's own bold where Galmuri has one - Galmuri11
# Bold, the 800's, which has no Latin Extended-A, Greek or Cyrillic - whose letters stand
# and to which the drawn ones are added.
BOLDS = {
    9: {"folder": FOLDER, "regular": "Galmuri9.bdf.gz", "drawn": BOLD, "official": None},
    11: {"folder": ROOT / "src" / "afterglow" / "scaffolds" / "harmony-800" / "fonts"
         / "galmuri", "regular": "Galmuri11.bdf.gz",
         "drawn": ROOT / "tools" / "galmuri" / "galmuri11-bold.txt",
         "official": "Galmuri11-Bold.bdf.gz"},
}
# The letters a bold is drawn for: Latin with its accents, Greek and Cyrillic.
BOLD_RANGES = ((0x21, 0x7F), (0xA1, 0x100), (0x100, 0x180), (0x384, 0x3CF),
               (0x400, 0x460), (0x490, 0x492))
# Where a mark comes from: Galmuri7's own accented letter over the letter it accents.
MARKS = {"acute": ("é", "e", "É", "E"), "grave": ("è", "e", "È", "E"),
         "diaeresis": ("ë", "e", "Ë", "E"), "breve": ("ă", "a", "Ă", "A")}
CAP_TOP, X_TOP = 6, 4          # Galmuri7's capital and lowercase tops, rows above the baseline


class Glyph:
    """Pixels as (column, row) - row 0 the baseline, up positive - and an advance."""

    def __init__(self, pixels, advance=None):
        self.pixels = set(pixels)
        width = max((x for x, _ in self.pixels), default=-1) + 1
        self.advance = width + 1 if advance is None else advance

    @classmethod
    def of(cls, font, char):
        found = font.glyph(char)
        if found is None:
            raise KeyError(f"Galmuri has no {char!r}")
        pixels = {(found["x"] + column, found["y"] + found["height"] - 1 - row)
                  for row, line in enumerate(found["rows"])
                  for column, on in enumerate(line) if on}
        return cls(pixels, found["advance"])

    @property
    def width(self):
        return max((x for x, _ in self.pixels), default=-1) + 1

    @property
    def top(self):
        return max((y for _, y in self.pixels), default=0)

    def shifted(self, dx):
        return Glyph({(x + dx, y) for x, y in self.pixels}, self.advance + dx)

    def bold(self):
        return Glyph(self.pixels | {(x + 1, y) for x, y in self.pixels}, self.advance + 1)


def drawn(top: int, lines: list[str]) -> Glyph:
    return Glyph({(column, top - number) for number, line in enumerate(lines)
                  for column, ink in enumerate(line) if ink == "#"})


def shorter(glyph: Glyph) -> Glyph:
    """A capital one row shorter, as Galmuri7 makes room for an accent over one: its
    second row from the top dropped."""
    gone = glyph.top - 1
    return Glyph({(x, y - 1 if y > gone else y) for x, y in glyph.pixels if y != gone},
                 glyph.advance)


def marked(font, base: Glyph, mark: str) -> Glyph:
    if mark == "tonos":
        # Greek's capital accent stands at its left: the capital moved over to make room
        moved = base.shifted(2)
        return Glyph(moved.pixels | {(0, CAP_TOP - 1), (1, CAP_TOP)}, moved.advance)
    accented, plain, capital_accented, capital = MARKS[mark]
    is_capital = base.top >= CAP_TOP
    if is_capital:
        source, under = Glyph.of(font, capital_accented), Glyph.of(font, capital)
        body = shorter(base)
        mark_pixels = {(x, y) for x, y in source.pixels if y > shorter(under).top}
    else:
        source, under = Glyph.of(font, accented), Glyph.of(font, plain)
        body = base
        mark_pixels = source.pixels - under.pixels
        mark_pixels = {(x, y) for x, y in mark_pixels if y > X_TOP}
        lift = body.top - X_TOP if body.top > X_TOP else 0
        mark_pixels = {(x, y + lift) for x, y in mark_pixels}
    # centred over the letter, as over the one it came from
    dx = (body.width - under.width) // 2
    pixels = body.pixels | {(x + dx, y) for x, y in mark_pixels}
    low = min(x for x, _ in pixels)
    glyph = Glyph(pixels, body.advance)
    return glyph.shifted(-low) if low < 0 else glyph


def additions(font, path=ADDITIONS) -> dict[str, Glyph]:
    out: dict[str, Glyph] = {}

    def resolve(name):
        return out[name] if name in out else Glyph.of(font, name)

    lines = path.read_text("utf-8").splitlines() if path.is_file() else []
    copies: list[tuple[str, str]] = []
    at = 0
    while at < len(lines):
        line = lines[at]
        at += 1
        # a glyph is one character then its top row, or `= ...`; so `# 8` draws `#`, and
        # any other line opening with `#` is a comment
        char, _, rest = line.partition(" ")
        header = len(char) == 1 and (rest.startswith("= ") or rest.lstrip("-").isdigit())
        if not line.strip() or not header:
            continue
        if rest.startswith("= "):
            copies.append((char, rest[2:]))
            continue
        top, body = int(rest), []
        while at < len(lines) and lines[at].strip():
            body.append(lines[at])
            at += 1
        out[char] = drawn(top, body)
    # a copy after every drawn letter, wherever it stands, so it finds the one drawn here
    for char, rest in copies:
        base, _, mark = rest.partition(" + ")
        glyph = resolve(base.strip())
        out[char] = marked(font, glyph, mark.strip()) if mark else glyph
    return out


def record(char: str, glyph: Glyph) -> str:
    code = ord(char)
    if not glyph.pixels:
        box, rows = (0, 0, 0, 0), []
    else:
        xs = [x for x, _ in glyph.pixels]
        ys = [y for _, y in glyph.pixels]
        left, bottom = min(xs), min(ys)
        width, height = max(xs) - left + 1, max(ys) - bottom + 1
        box = (width, height, left, bottom)
        span = (width + 7) // 8
        rows = []
        for y in range(bottom + height - 1, bottom - 1, -1):
            bits = 0
            for x in range(width):
                if (left + x, y) in glyph.pixels:
                    bits |= 1 << (span * 8 - 1 - x)
            rows.append(f"{bits:0{span * 2}X}")
    return "\n".join([f"STARTCHAR U+{code:04X}", f"ENCODING {code}",
                      f"SWIDTH {round(glyph.advance * 1000 / 15)} 0",
                      f"DWIDTH {glyph.advance} 0", "BBX {} {} {} {}".format(*box),
                      "BITMAP", *rows, "ENDCHAR"])


def write(source: Path, out: Path, glyphs: dict[str, Glyph], family: str, weight: str,
          properties: dict | None = None):
    """``source``'s header, renamed, over ``glyphs``; ``properties`` replaces the header's
    own where a font is drawn at another size than its source."""
    text = gzip.decompress(source.read_bytes()).decode("utf-8")
    header = text[:text.index("STARTCHAR")]
    kept = []
    for line in header.splitlines():
        if line.startswith("FONT "):
            line = f"FONT -Afterglow-{family}-{weight}-R-Normal--10-10-75-75-P-80-ISO10646-1"
        elif line.startswith("FAMILY_NAME"):
            line = f'FAMILY_NAME "{family}"'
        elif line.startswith("WEIGHT_NAME"):
            line = f'WEIGHT_NAME "{weight}"'
        elif line.startswith("CHARS "):
            line = f"CHARS {len(glyphs)}"
        elif line.split(" ")[0] in (properties or {}):
            line = f"{line.split(' ')[0]} {properties[line.split(' ')[0]]}"
        elif line.startswith("STARTPROPERTIES"):
            kept.append("COMMENT Galmuri by Lee Minseo, modified for Afterglow "
                        "(tools/galmuri_afterglow.py); SIL Open Font License 1.1")
        kept.append(line)
    body = "\n".join(record(char, glyph) for char, glyph in
                     sorted(glyphs.items(), key=lambda item: ord(item[0])))
    out.write_bytes(gzip.compress(("\n".join(kept) + "\n" + body + "\nENDFONT\n")
                                  .encode("utf-8"), mtime=0))
    print(f"wrote {out.relative_to(ROOT)}: {len(glyphs)} glyphs")


def every_glyph(font) -> dict[str, Glyph]:
    return {chr(code): Glyph.of(font, chr(code)) for code in sorted(font.index)}


def draft_bold(glyph: Glyph) -> Glyph:
    """A bold draft of ``glyph``: each pixel also drawn to its right, so a stroke is two
    pixels - except where that would close a gap a pixel wide, which stays open and the
    stroke thin there, for the hand to widen the letter instead."""
    ink = glyph.pixels
    out = set(ink) | {(x + 1, y) for x, y in ink
                      if (x + 1, y) not in ink and (x + 2, y) not in ink}
    return Glyph(out, glyph.advance + 1)


def art(char: str, glyph: Glyph) -> str:
    """``glyph`` as the bold file holds it: its char, its top row, its rows."""
    if not glyph.pixels:
        return ""
    top, bottom = glyph.top, min(y for _, y in glyph.pixels)
    rows = []
    for y in range(top, bottom - 1, -1):
        row = "".join("#" if (x, y) in glyph.pixels else " " for x in range(glyph.width))
        rows.append(row.rstrip() or ".")
    return f"{char} {top}\n" + "\n".join(rows) + "\n"


def draft(size: int) -> None:
    """Add a draft of every bold letter the size lacks - not drawn in its file, nor in
    the designer's bold - to its file, to be looked at and corrected there."""
    bold = BOLDS[size]
    regular = bdf.Bitmap.read(bold["folder"] / bold["regular"])
    official = (bdf.Bitmap.read(bold["folder"] / bold["official"]) if bold["official"]
                else None)
    drawn_already = additions(official or regular, bold["drawn"])
    drafts = [art(chr(code), draft_bold(Glyph.of(regular, chr(code))))
              for start, end in BOLD_RANGES for code in range(start, end)
              if chr(code) not in drawn_already and regular.glyph(chr(code)) is not None
              and Glyph.of(regular, chr(code)).pixels
              and (official is None or official.glyph(chr(code)) is None)]
    path = bold["drawn"]
    heading = "" if path.is_file() else (
        f"# Galmuri{size} Bold, letter by letter: each drafted by tools/galmuri_afterglow.py\n"
        "# --draft-bold and then looked at, and corrected where a stroke merged or a letter\n"
        "# lost its shape. The build reads only this file"
        + (f" and {bold['official']}, the designer's own\n# bold, for what it draws" if
           bold["official"] else "") + ". The format is galmuri7-additions.txt's; a row's\n"
        "# numbers count from the baseline, 0.\n")
    with path.open("a", encoding="utf-8") as out:
        out.write(heading + "\n" + "\n".join(drafts))
    print(f"drafted {len(drafts)} bold letters into {path.relative_to(ROOT)}")


def build_bold(size: int) -> None:
    bold = BOLDS[size]
    regular = bdf.Bitmap.read(bold["folder"] / bold["regular"])
    source = bold["folder"] / (bold["official"] or bold["regular"])
    official = bdf.Bitmap.read(source) if bold["official"] else None
    glyphs = every_glyph(official) if official else {}
    # a copy (`Α = A`) is of the designer's letter where there is one
    glyphs.update(additions(official or regular, bold["drawn"]))
    glyphs.setdefault(" ", Glyph(set(), Glyph.of(regular, " ").advance + 1))
    write(source, bold["folder"] / f"GalmuriAfterglow{size}-Bold.bdf.gz", glyphs,
          f"Galmuri Afterglow{size}", "Bold")


def main() -> int:
    if "--draft-bold" in sys.argv:
        for size in BOLDS:
            draft(size)
        return 0

    small = FOLDER / "Galmuri7.bdf.gz"
    font = bdf.Bitmap.read(small)
    glyphs = every_glyph(font)
    glyphs.update({char: glyph for char, glyph in additions(font).items()
                   if font.glyph(char) is None})
    write(small, FOLDER / "GalmuriAfterglow7.bdf.gz", glyphs, "Galmuri Afterglow7",
          "Regular")
    for size in BOLDS:
        build_bold(size)
    # the 800's number pad, at its slot's own size
    folder = BOLDS[11]["folder"]
    official = bdf.Bitmap.read(folder / BOLDS[11]["official"])
    write(folder / BOLDS[11]["official"], folder / "GalmuriAfterglowKeypad.bdf.gz",
          additions(official, KEYPAD), "Galmuri Afterglow Keypad", "Bold",
          {"CAP_HEIGHT": 22, "FONT_ASCENT": 24, "FONT_DESCENT": 2, "PIXEL_SIZE": 30})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
