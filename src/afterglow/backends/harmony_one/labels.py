"""Reading the text a Harmony One image draws, whatever its glyph codes are.

An image's text is glyph codes, and which character a code stands for is the image's own
business: Logitech's builder numbered each configuration's repertoire its own way (four
layouts are established, glyph_codec.py, and others exist), and this backend numbers
each font slot from 1. What does not change is what a glyph looks like. So a code is
read by its shape: the fingerprint of its pixels against the shapes Logitech's
configurations are known to draw (platform/glyph-shapes.json, written by
tools/harmony_one_glyph_shapes.py) and the shapes this scaffold's own fonts draw.

Logitech's codes are image-wide, one character each, which settles what shape alone does
not: a code read the same in every font that can read it is read so in the rest, and a
shape some face draws for two characters - a capital I and a small l - is the one of them
no other code of the image already stands for. The image's established layout, when it
has one, comes last. A character still unknown is read as U+FFFD and counted, never
guessed.

This backend's own fonts give every character its own code in each slot, so elimination
does not apply to them, and Galmuri draws a capital O and a zero alike. A shape still
drawing two characters is read by its neighbours: a zero among digits, a letter among
letters, a capital starting a word. Those reads are counted too (``inferred``).

A letter with an accent no known configuration draws - Kāt's Finnish ä and ö - is the
image's own unaccented letter with a mark above it: a glyph whose pixels are exactly a
letter the image has read, with ink only above that letter's own, is that letter with the
mark its extra ink makes - two dots, a ring, or a stroke leaning one way or the other.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from . import drawing, font_index, glyph_codec, ui_index

SHAPES_FILE = "platform/glyph-shapes.json"
SHAPES_SCHEMA = "afterglow-harmony-one-glyph-shapes/1"
UNKNOWN = "\N{REPLACEMENT CHARACTER}"
# What this backend's own fonts are asked to draw, to know their shapes: printable ASCII
# and Latin-1's letters, which covers every label the catalogue and an editor produce in
# the languages the One is offered in.
OWN_CHARACTERS = "".join(chr(code) for code in range(0x20, 0x7F)) + "".join(
    chr(code) for code in range(0xC0, 0x100))


def shape(body: bytes) -> str:
    """A glyph's fingerprint, as font_index records it: its pixels, not their colours."""
    return ui_index._glyph_shape(body, 0)["shape"]


@lru_cache(maxsize=4)
def known_shapes(directory: str | None = None) -> dict[str, str]:
    """Every shape whose character is known - the characters, when a face draws more
    than one alike: Logitech's, then this scaffold's fonts'."""
    from ... import paths
    from . import assets

    directory = Path(paths.scaffolds("harmony-one") if directory is None else directory)
    out = {}
    path = directory / SHAPES_FILE
    if path.is_file():
        data = json.loads(path.read_text("utf-8"))
        if data.get("schema") != SHAPES_SCHEMA:
            raise ValueError(f"{path} declares {data.get('schema')!r}, not {SHAPES_SCHEMA!r}")
        out.update(data["shapes"])
    try:
        loaded = assets.load(directory, set(OWN_CHARACTERS))
    except (FileNotFoundError, ValueError):
        return out
    own = defaultdict(set)
    for font in loaded["fonts"].values():
        for item in font["glyphs"].values():
            if item.get("char"):
                own[shape(item["body"])].add(item["char"])
    for fingerprint, characters in own.items():
        out[fingerprint] = "".join(sorted(characters | set(out.get(fingerprint, ""))))
    return out


class Text:
    """The text of one image, read font by font. ``decode(glyphs, attribute)`` reads a
    stored glyph string drawn in the font of that attribute."""

    def __init__(self, payload: bytes, shapes: dict[str, str] | None = None):
        shapes = known_shapes() if shapes is None else shapes
        fonts = font_index.fonts(payload)
        self.candidates = [{code: shapes[glyph["shape"]] for code, glyph in font["glyphs"].items()
                            if glyph["shape"] in shapes} for font in fonts]
        self.fonts, self.shared = read_fonts(self.candidates)
        for font, read in zip(fonts, self.fonts):
            _read_accents(payload, font, read)
        layout = glyph_codec.inspect(payload)
        self.layout = {} if layout.get("error") else dict(layout["code_to_character"])
        self.unknown = 0
        self.inferred = 0

    def _read(self, code: int, attribute: int | None) -> str:
        """A character, or the characters it may be, or "" when nothing reads it."""
        if attribute is not None and 0 <= attribute < len(self.fonts):
            found = self.fonts[attribute].get(code)
            if found is not None:
                return found
        found = self.shared.get(code) or self.layout.get(code)
        if found is not None and found != glyph_codec.WIDE_BLANK:
            return found
        if attribute is not None and 0 <= attribute < len(self.candidates):
            return self.candidates[attribute].get(code, "")
        return ""

    def decode(self, glyphs: bytes, attribute: int | None) -> str:
        read = [self._read(code, attribute) for code in drawing.glyph_codes(bytes(glyphs))]
        out = []
        for index, characters in enumerate(read):
            if len(characters) == 1:
                out.append(characters)
            elif not characters:
                self.unknown += 1
                out.append(UNKNOWN)
            else:
                self.inferred += 1
                out.append(_by_neighbours(characters, out[-1] if out else "",
                                          read[index + 1] if index + 1 < len(read) else ""))
        return "".join(out)


def _by_neighbours(characters: str, before: str, following: str) -> str:
    """Which of look-alike ``characters`` a glyph is, from the character read before it
    and what the next glyph may be."""
    after = following if len(following) == 1 else ""
    digits = [character for character in characters if character.isdigit()]
    if digits and not before.isalpha() and not after.isalpha():
        return digits[0]
    letters = [character for character in characters if character.isalpha()] or list(characters)
    if before.isalpha() or after.isalpha():
        upper = [character for character in letters if character.isupper()]
        lower = [character for character in letters if character.islower()]
        starts = not before.isalpha()
        if starts and upper and (not after or after.islower() or after.isupper()):
            return upper[0]
        if lower and not starts:
            return lower[0]
    return letters[0]


def read_fonts(candidates: list[dict[int, str]]) -> tuple[list[dict[int, str]], dict[int, str]]:
    """Each font's codes as characters, from the characters each code's shape may be.
    The second result is what a code is in every font that can read it alone."""
    votes: dict[int, Counter] = defaultdict(Counter)
    for table in candidates:
        for code, characters in table.items():
            if len(characters) == 1:
                votes[code][characters] += 1
    shared = {code: next(iter(counter)) for code, counter in votes.items()
              if len(counter) == 1}
    claimed = set(shared.values())
    fonts = []
    for table in candidates:
        read = {}
        for code, characters in table.items():
            if len(characters) == 1:
                read[code] = characters
            elif code in shared and shared[code] in characters:
                read[code] = shared[code]
            else:
                left = [character for character in characters if character not in claimed]
                if len(left) == 1:
                    read[code] = left[0]
        fonts.append(read)
    return fonts, shared


# The combining marks a letter's extra ink is read as.
DIAERESIS, RING, ACUTE, GRAVE, CIRCUMFLEX = "\u0308", "\u030a", "\u0301", "\u0300", "\u0302"


def _read_accents(payload: bytes, font: dict, read: dict[int, str]):
    """Add to ``read`` each glyph of ``font`` that is a letter it has read with a mark
    above: the same pixels from the letter's own top row down, and ink above it only."""
    masks = {}

    def mask(code):
        if code not in masks:
            masks[code] = ui_index.glyph_mask(payload, font["glyphs"][code]["offset"])[0]
        return masks[code]
    bases = [(code, character) for code, character in read.items()
             if character.isalpha() and len(character) == 1]
    for code in font["glyphs"]:
        if code in read:
            continue
        found = set()
        for base_code, character in bases:
            accented = _accented(mask(code), mask(base_code), character)
            if accented:
                found.add(accented)
        if len(found) == 1:
            read[code] = found.pop()


def _accented(glyph: list[bytes], base: list[bytes], character: str) -> str | None:
    if len(glyph) != len(base) or len(glyph[0]) != len(base[0]):
        return None
    inked = [row for row, line in enumerate(base) if any(line)]
    if not inked or glyph[inked[0]:] != base[inked[0]:]:
        return None
    mark = [line for line in glyph[:inked[0]] if any(line)]
    kind = _mark(mark)
    if kind is None:
        return None
    composed = unicodedata.normalize("NFC", character + kind)
    return composed if len(composed) == 1 else None


def _mark(rows: list[bytes]) -> str | None:
    """Which accent a patch of ink above a letter is."""
    if not rows:
        return None
    # two dots: two separate runs of ink along the top, however their shadows touch
    top_runs = sum(1 for x, value in enumerate(rows[0]) if value and (x == 0 or not rows[0][x - 1]))
    if top_runs == 2:
        return DIAERESIS
    ink = {(x, y) for y, line in enumerate(rows) for x, value in enumerate(line) if value}
    components = []
    while ink:
        stack, part = [ink.pop()], set()
        while stack:
            x, y = stack.pop()
            part.add((x, y))
            # pixels touching at a corner are one mark: Logitech draws a dot with its
            # shadow, diagonally
            for neighbour in ((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                if neighbour in ink:
                    ink.remove(neighbour)
                    stack.append(neighbour)
        components.append(part)
    if len(components) == 2:
        left, right = sorted(components, key=lambda part: min(x for x, _y in part))
        if max(x for x, _y in left) < min(x for x, _y in right):
            return DIAERESIS
        return None
    if len(components) != 1:
        return None
    [part] = components
    xs = [x for x, _y in part]
    ys = [y for _x, y in part]
    width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    # a ring encloses a gap no ink reaches from outside it
    inside = {(x, y) for x in range(min(xs), max(xs) + 1) for y in range(min(ys), max(ys) + 1)}
    outside = {cell for cell in inside - part
               if cell[0] in (min(xs), max(xs)) or cell[1] in (min(ys), max(ys))}
    stack = list(outside)
    while stack:
        x, y = stack.pop()
        for neighbour in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if neighbour in inside and neighbour not in part and neighbour not in outside:
                outside.add(neighbour)
                stack.append(neighbour)
    if inside - part - outside:
        return RING
    if height < 2:
        return None
    top = sum(x for x, y in part if y == min(ys)) / sum(1 for _x, y in part if y == min(ys))
    bottom = sum(x for x, y in part if y == max(ys)) / sum(1 for _x, y in part if y == max(ys))
    if width >= 3 and abs(top - (min(xs) + max(xs)) / 2) < 1 and bottom != top:
        return CIRCUMFLEX
    if top > bottom:
        return ACUTE
    if top < bottom:
        return GRAVE
    return None


def screen_text(payload: bytes, program: int, text: Text, *, depth: int = 6) -> list[dict]:
    """What a page program draws as text, in drawing order: ``{x, y, attribute, text}``.

    Calls are followed, as the remote runs them - a page's title is drawn by the
    prologue it calls - and the font attribute carries across them as the drawing VM's
    does. A switch is not followed: what it draws depends on state, such as the
    "Current Activity" softkey."""
    out: list[dict] = []
    state = {"attribute": None}

    def walk(offset, level):
        if level > depth:
            return
        for item in ui_index.drawing_program(payload, offset)["instructions"]:
            opcode = item["opcode"]
            if opcode == "attribute":
                state["attribute"] = item["value"]
            elif opcode in ("text", "inline_text"):
                out.append({"x": item["x"], "y": item["y"], "attribute": state["attribute"],
                            "text": text.decode(bytes.fromhex(item["glyphs"]),
                                                state["attribute"])})
            elif opcode == "call":
                walk(item["target"], level + 1)
            elif opcode == "jump":
                walk(item["target"], level + 1)
                return
    walk(program, 0)
    return out
