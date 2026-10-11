"""Load the artwork a generated Harmony One configuration draws.

Every backdrop, button frame, row icon and status icon the remote shows is stored in the
configuration rather than in firmware, so a configuration generated from a project has to
supply them - and because the format is a general drawing VM rather than a fixed set of
pictures, they can be ours. They live as PNG files in the remote's scaffold directory so
that anyone who wants different artwork can open them in an image editor and replace
them, which is the only way an owner can change what their remote looks like.

Two things about the display shape what an asset may be. Pixels are RGB565, so colour is
reduced on the way in and a gradient will band. Transparency is one bit and not a
channel: a run-encoded picture either writes a pixel or leaves whatever was underneath
alone, so a soft edge has to become a hard one. Both are reported rather than done
quietly, because a picture that looked right in the editor and wrong on the remote is
exactly the failure this module exists to prevent.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import json
from pathlib import Path

from ... import imaging
from . import bitmap


MANIFEST = "assets.json"
SCHEMA = "afterglow-scaffold-assets/1"

# Below this an editor's soft edge is taken as "leave the screen alone", at or above it
# as "draw this pixel". The format has no middle, so the choice is made once, here.
ALPHA_THRESHOLD = 128

MODES = {"raw": bitmap.RAW, "runs": bitmap.RUNS, "shorter": None}


def to_rows(image: dict, *, threshold: int = ALPHA_THRESHOLD) -> tuple[list, dict]:
    """Convert a decoded PNG to picture rows, reporting what the display cannot keep."""
    rows, softened, banded = [], 0, 0
    for line in image["rows"]:
        row = []
        for red, green, blue, alpha in line:
            if 0 < alpha < 255:
                softened += 1
            if alpha < threshold:
                row.append(None)
                continue
            shown = bitmap.from_rgb565(bitmap.to_rgb565((red, green, blue)))
            if shown != (red, green, blue):
                banded += 1
            # The reduced colour is kept, not the one the file held, so that reading a
            # picture back out of an image gives the same rows this put in.
            row.append(shown)
        rows.append(row)
    return rows, {"partial_alpha": softened, "colour_reduced": banded}


def to_image(rows: list[list]) -> list[list[tuple[int, int, int, int]]]:
    """Convert picture rows back to RGBA, so an asset can be written out again."""
    return [
        [(0, 0, 0, 0) if pixel is None else (*pixel, 255) for pixel in row]
        for row in rows
    ]


# A text instruction stores a glyph code in one byte below 0x80; a slot holds at most this
# many characters, numbered from 1.
# A slot's codes run from 1; past 0x7F a code takes two bytes (drawing.GlyphCodes).
MAX_CODES = 0x7FFF


def slot_font(role: str, entry: dict, face, characters=None, fallback=None) -> dict:
    """Draw a font slot from ``face`` (faces.py): the characters it is given - printable
    ASCII unless the build says which - numbered from 1, in the slot's colour over its
    shadow (the manifest entry's ``look``). A character the face lacks comes from
    ``fallback`` - the scaffold's default face, under an owner's own font - so a theme's
    font need not have every character the remote draws; one neither has is left out,
    and a label using it is refused by name when it is laid out."""
    from . import faces

    if face is None:
        raise ValueError(
            f"font {role!r}: the scaffold names no typeface to draw it from (the manifest's "
            f"`typeface`, or {faces.TYPEFACE})")
    look = entry["look"]
    height = entry["height"]
    glyphs = {}
    wanted = sorted(set(faces.REPERTOIRE if characters is None else characters) | {" "})
    def source(char):
        if face.glyph(char) is not None:
            return face
        if fallback is not None and fallback.glyph(char) is not None:
            return fallback
        return None
    wanted = [char for char in wanted if source(char) is not None]
    if len(wanted) > MAX_CODES:
        raise ValueError(
            f"font {role!r} would draw {len(wanted)} different characters; a slot holds "
            f"{MAX_CODES}")
    for code, char in enumerate(wanted, start=1):
        made = faces.face_glyph(source(char), char, height, look["colour"], look.get("shadow"))
        rows = [[None if pixel is None else bitmap.from_rgb565(bitmap.to_rgb565(pixel))
                 for pixel in line] for line in made["rows"]]
        glyphs[code] = {"char": char, "width": made["width"], "rows": rows,
                        "body": bitmap.encode_glyph(rows)}
    return {
        "file": None, "height": height, "slots": entry.get("slots"),
        "layout": entry.get("layout"), "glyphs": glyphs,
        "bytes": sum(len(item["body"]) for item in glyphs.values()),
        "partial_alpha": 0, "colour_reduced": 0,
    }


_TYPEFACES: dict = {}


def typeface(directory, small: bool = False):
    """The face a scaffold's text is drawn from, read once: the owner's own TrueType font
    (faces.TYPEFACE) if they put one there, else the scaffold's default face (the
    manifest's ``typeface``), else None. With ``small``, the face for the 11-pixel slots
    where one is given."""
    from .faces import SMALL_TYPEFACE, TYPEFACE

    directory = Path(directory)
    own = directory / (SMALL_TYPEFACE if small else TYPEFACE)
    if small and not own.is_file():
        own = directory / TYPEFACE
    if own.is_file():
        return typeface_file(own)
    return default_typeface(directory, small)


def default_typeface(directory, small: bool = False):
    """The scaffold's own face (the manifest's ``typeface``), whatever an owner adds."""
    default = read_manifest(directory).get("typeface") or {}
    name = default.get("small" if small else "regular") or default.get("regular")
    return typeface_file(Path(directory) / name) if name else None


def typeface_file(path: Path):
    """A TrueType or BDF font file, read once and kept; None when there is none."""
    from ... import bdf
    from ...ttf import TrueType

    if not path.is_file():
        return None
    data = path.read_bytes()
    key = (str(path), len(data), hash(data))
    if key not in _TYPEFACES:
        try:
            bitmap = path.name.endswith((".bdf", ".bdf.gz"))
            _TYPEFACES[key] = bdf.Bitmap.read(path) if bitmap else TrueType(data)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return _TYPEFACES[key]


def load_font(directory, role: str, entry: dict, characters=None) -> dict:
    """Slice one font sheet into glyphs and encode each as the remote stores it, or draw
    the slot from the scaffold's typeface when the manifest gives it a ``look``.

    A sheet is the font's glyphs side by side in code order, so it can be opened and
    redrawn in one piece. The manifest says where each one starts and how wide it is,
    which is what makes a proportional font editable without a font editor: change the
    pixels freely, and change the width here when a letter needs more room.
    """
    if "look" in entry:
        from .faces import SMALL_SLOT
        small = entry["height"] <= SMALL_SLOT
        face = typeface(directory, small=small)
        fallback = default_typeface(directory, small)
        return slot_font(role, entry, face, characters,
                         fallback if fallback is not face else None)
    path = Path(directory) / entry["file"]
    if not path.is_file():
        raise FileNotFoundError(f"font {role!r} names {path}, which does not exist")
    image = imaging.decode(path.read_bytes())
    height = entry.get("height", image["height"])
    if image["height"] < height:
        raise ValueError(
            f"font {role!r} at {path} is {image['height']} pixels tall, "
            f"but declares a height of {height}")
    glyphs, notes = {}, {"partial_alpha": 0, "colour_reduced": 0}
    for item in entry.get("glyphs", ()):
        left, width = item["x"], item["width"]
        if left < 0 or left + width > image["width"]:
            raise ValueError(
                f"font {role!r} glyph {item.get('char') or item['code']} sits at "
                f"{left}..{left + width}, outside a sheet {image['width']} wide")
        cut = {"width": width, "height": height,
               "rows": [row[left:left + width] for row in image["rows"][:height]]}
        rows, report = to_rows(cut)
        for key in notes:
            notes[key] += report[key]
        glyphs[item["code"]] = {
            "char": item.get("char"), "width": width, "rows": rows,
            "body": bitmap.encode_glyph(rows),
        }
    return {
        "file": entry["file"], "height": height, "slots": entry.get("slots"),
        "layout": entry.get("layout"), "glyphs": glyphs,
        "bytes": sum(len(item["body"]) for item in glyphs.values()),
        **notes,
    }


def read_manifest(directory) -> dict:
    """Read a scaffold's asset manifest, or say exactly what is wrong with it."""
    path = Path(directory) / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist, so this scaffold declares no assets")
    try:
        manifest = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if manifest.get("schema") != SCHEMA:
        raise ValueError(
            f"{path} declares schema {manifest.get('schema')!r}, not {SCHEMA!r}")
    pictures = manifest.get("pictures")
    if not isinstance(pictures, dict):
        raise ValueError(f"{path} has no 'pictures' object")
    for role, entry in pictures.items():
        if not isinstance(entry, dict) or "file" not in entry:
            raise ValueError(f"{path}: picture {role!r} names no file")
        mode = entry.get("mode", "shorter")
        if mode not in MODES:
            raise ValueError(
                f"{path}: picture {role!r} asks for mode {mode!r}; "
                f"choose one of {', '.join(sorted(MODES))}")
    return manifest


def load(directory, characters=None) -> dict:
    """Load every picture and font a scaffold declares, encoded as the remote stores them.

    ``characters`` is what the fonts drawn from a typeface carry:
    printable ASCII when not given, one set for every slot, or ``{role: set}``."""
    directory = Path(directory)
    manifest = read_manifest(directory)
    pictures, notes = {}, {}
    for role, entry in sorted(manifest["pictures"].items()):
        path = directory / entry["file"]
        if not path.is_file():
            raise FileNotFoundError(f"picture {role!r} names {path}, which does not exist")
        try:
            image = imaging.decode(path.read_bytes())
        except ValueError as exc:
            raise ValueError(f"picture {role!r} at {path} cannot be read: {exc}") from exc
        declared = entry.get("size")
        if declared is not None:
            width, height = declared
            if (image["width"], image["height"]) != (width, height):
                raise ValueError(
                    f"picture {role!r} at {path} is "
                    f"{image['width']}x{image['height']}, but the manifest says "
                    f"{width}x{height}")
        rows, report = to_rows(image)
        try:
            body = bitmap.encode(rows, mode=MODES[entry.get("mode", "shorter")])
        except ValueError as exc:
            raise ValueError(f"picture {role!r} at {path} cannot be stored: {exc}") from exc
        pictures[role] = {
            "file": entry["file"], "width": image["width"], "height": image["height"],
            "rows": rows, "body": body,
            "mode": body[0], "bytes": len(body), **report,
        }
        if report["partial_alpha"] or report["colour_reduced"]:
            notes[role] = report
    fonts = {}
    for role, entry in sorted(manifest.get("fonts", {}).items()):
        wanted = characters.get(role) if isinstance(characters, dict) else characters
        font = load_font(directory, role, entry, wanted)
        fonts[role] = font
        if font["partial_alpha"] or font["colour_reduced"]:
            notes[role] = {"partial_alpha": font["partial_alpha"],
                           "colour_reduced": font["colour_reduced"]}
    return {
        "directory": str(directory),
        "remote": manifest.get("remote"),
        "pictures": pictures,
        "fonts": fonts,
        # What the display could not keep, per picture. Not an error: a photograph will
        # band and a soft-edged icon will harden, and the owner may well want it anyway.
        "notes": notes,
        "bytes": (sum(item["bytes"] for item in pictures.values())
                  + sum(item["bytes"] for item in fonts.values())),
    }


def mapping(font: dict) -> dict:
    """The character-to-code table a scaffold font declares, shaped like a donor's.

    `glyph_codec` derives its repertoires from donor images, so it knows nothing about the
    characters added here - a font completed to printable ASCII indexes past the largest
    repertoire any donor uses. A generated configuration is not reading somebody's image
    though: it is writing its own, and the manifest is the authority on what each code
    means. This returns that authority in the shape the encoder already consumes, so a
    label goes through the same refusal path when a font genuinely cannot draw it.
    """
    code_to_character = {
        code: item["char"] for code, item in font["glyphs"].items() if item["char"]
    }
    return {
        "repertoire": max(font["glyphs"], default=0),
        "code_to_character": code_to_character,
        "character_to_code": {
            character: code for code, character in code_to_character.items()
        },
        "missing_codes": [],
        "unresolved_codes": sorted(
            code for code, item in font["glyphs"].items() if not item["char"]),
    }


def widths(font: dict) -> dict[int, int]:
    """Each code's advance width, which is what a label's layout is measured in."""
    return {code: item["width"] for code, item in font["glyphs"].items()}


def audit(directory, required=()) -> dict:
    """Report what a scaffold supplies and what a build would still be missing."""
    try:
        loaded = load(directory)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "problem": str(exc), "pictures": {}, "fonts": {},
                "missing": list(required)}
    missing = [role for role in required if role not in loaded["pictures"]]
    return {
        "ok": not missing,
        "problem": None,
        "pictures": {
            role: f"{item['width']}x{item['height']} "
                  f"{'run-encoded' if item['mode'] == bitmap.RUNS else 'stored whole'}, "
                  f"{item['bytes']} bytes"
            for role, item in sorted(loaded["pictures"].items())
        },
        "fonts": {
            role: f"height {item['height']}, {len(item['glyphs'])} glyphs, "
                  f"{item['bytes']} bytes"
            for role, item in sorted(loaded["fonts"].items())
        },
        "missing": missing,
        "notes": loaded["notes"],
        "bytes": loaded["bytes"],
    }
