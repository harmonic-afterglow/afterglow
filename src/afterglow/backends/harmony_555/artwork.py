"""What a 5xx build draws that a theme can change: its pictures and its typeface.

The scaffold keeps the pictures as PNG files and names them in its `assets.json`, each
with the box it is drawn in; a theme is a folder of the same files, and a file a theme
leaves out is the scaffold's (scaffolds/harmony-555/THEME.md). A picture can be any PNG:
it is turned grey (transparent counts as white), shrunk to fit its box if it is too big,
dithered to the screen's one bit and centred in the box - so a picture drawn black on
white at its size comes through pixel for pixel. The SST-768's scaffold takes its
pictures the same way (backends/harmony_768/drawing.py).

Format reference: docs/harmony_5xx/ahcm.md, "Pictures"
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import imaging

MANIFEST = "assets.json"
SCHEMA = "afterglow-arch9-theme/1"


def shades(data: bytes) -> list[list[float]]:
    """A PNG's rows as grey levels, 0 black to 255 white, laid over white where it is
    transparent; colour weighed as the eye weighs it."""
    image = imaging.decode(data)
    return [[255 - alpha / 255 * (255 - (0.299 * red + 0.587 * green + 0.114 * blue))
             for red, green, blue, alpha in row] for row in image["rows"]]


def fitted(rows: list[list[float]], width: int, height: int) -> list[list[float]]:
    """`rows` shrunk to fit `width` x `height`, its proportions kept, each new pixel the
    average of the area it covers; a picture that fits already is left as it is."""
    source_h, source_w = len(rows), len(rows[0])
    factor = min(width / source_w, height / source_h, 1.0)
    if factor == 1.0:
        return rows
    new_w, new_h = max(1, round(source_w * factor)), max(1, round(source_h * factor))
    out = []
    for y in range(new_h):
        top, bottom = y * source_h / new_h, (y + 1) * source_h / new_h
        line = []
        for x in range(new_w):
            left, right = x * source_w / new_w, (x + 1) * source_w / new_w
            total = weight = 0.0
            for sy in range(int(top), min(source_h, -int(-bottom // 1))):
                cover_y = min(bottom, sy + 1) - max(top, sy)
                for sx in range(int(left), min(source_w, -int(-right // 1))):
                    cover = cover_y * (min(right, sx + 1) - max(left, sx))
                    total += rows[sy][sx] * cover
                    weight += cover
            line.append(total / weight)
        out.append(line)
    return out


def dithered(rows: list[list[float]]) -> list[list[int]]:
    """Grey levels as ink (1) and paper (0), Floyd-Steinberg: each pixel's error carried
    to the ones not yet decided. Black and white come through as they are."""
    rows = [list(row) for row in rows]
    out = []
    for y, row in enumerate(rows):
        line = []
        for x, level in enumerate(row):
            ink = level < 128
            line.append(1 if ink else 0)
            error = level - (0 if ink else 255)
            for dx, dy, share in ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)):
                if 0 <= x + dx < len(row) and y + dy < len(rows):
                    rows[y + dy][x + dx] += error * share / 16
        out.append(line)
    return out


def picture(data: bytes, width: int, height: int, stored=None) -> list[list[int]]:
    """Any PNG as the remote can show it in a `width` x `height` box, centred, at the top
    left of a picture of the `stored` size (the box's, when not given)."""
    drawn = dithered(fitted(shades(data), width, height))
    stored_w, stored_h = stored or (width, height)
    left, top = (width - len(drawn[0])) // 2, (height - len(drawn)) // 2
    rows = [[0] * stored_w for _ in range(stored_h)]
    for y, row in enumerate(drawn):
        rows[top + y][left:left + len(row)] = row
    return rows


class Art:
    """A scaffold's pictures and typeface, each the theme's where the theme has it."""

    def __init__(self, scaffold: Path, theme: Path | None = None):
        self.scaffold, self.theme = Path(scaffold), Path(theme) if theme else None
        path = self.scaffold / MANIFEST
        manifest = json.loads(path.read_text("utf-8")) if path.is_file() else {}
        if manifest and manifest.get("schema") != SCHEMA:
            raise ValueError(f"{path} declares {manifest.get('schema')!r}, not {SCHEMA!r}")
        self.boxes = manifest.get("pictures") or {}
        self.face_file = manifest.get("face")

    def path(self, name: str) -> Path:
        """A file of the theme's, else the scaffold's."""
        if self.theme is not None and (self.theme / name).is_file():
            return self.theme / name
        return self.scaffold / name

    def themed(self, name: str) -> bool:
        return self.path(name) != self.scaffold / name

    def picture(self, name: str) -> list[list[int]]:
        """The picture `name` (a path in the scaffold) as rows of ink and paper."""
        data = self.path(name).read_bytes()
        box = self.boxes.get(name)
        if box is None:                     # a picture the manifest does not name
            size = imaging.decode(data)
            box = {"width": size["width"], "height": size["height"]}
        return picture(data, box["width"], box["height"], box.get("stored"))

    def face_directory(self) -> Path:
        """The folder whose typeface a build draws: the theme's when it has one of its
        own - a copy of the scaffold's, as the Example's is, is the scaffold's."""
        if self.face_file and self.themed(self.face_file) and \
                self.path(self.face_file).read_bytes() != \
                (self.scaffold / self.face_file).read_bytes():
            return self.theme
        return self.scaffold
