"""What a 5xx build draws that a theme can change: its pictures and its typeface.

The scaffold keeps the pictures as PNG files and names them in its `assets.json`, each
with the box it is drawn in; a theme is a folder of the same files, and a file a theme
leaves out is the scaffold's (scaffolds/harmony-555/THEME.md). A picture can be any PNG:
it is turned grey (transparent counts as white), shrunk to fit its box if it is too big,
dithered to the screen's one bit and centred in the box - so a picture drawn black on
white at its size comes through pixel for pixel - as on the SST-768 and the 688, one
module drawing them all (monochrome.py). The manifest is laid out as the One's: each
picture by role, with its file and its box's size, and the typeface by role.

Format reference: docs/harmony_5xx/ahcm.md, "Pictures"
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import imaging, monochrome

MANIFEST = "assets.json"
SCHEMA = "afterglow-arch9-theme/1"


def picture(data: bytes, width: int, height: int, stored=None) -> list[list[int]]:
    """Any PNG as the remote can show it in a `width` x `height` box (monochrome.py), as
    rows of ink (1) and paper (0), at the top left of a picture of the `stored` size
    (the box's, when not given)."""
    box = monochrome.picture(data, width, height)
    stored_w, stored_h = stored or (width, height)
    rows = [[0] * stored_w for _ in range(stored_h)]
    for y, row in enumerate(box):
        rows[y][:width] = [int(on) for on in row]
    return rows


class Art:
    """A scaffold's pictures and typeface, each the theme's where the theme has it."""

    def __init__(self, scaffold: Path, theme: Path | None = None):
        self.scaffold, self.theme = Path(scaffold), Path(theme) if theme else None
        path = self.scaffold / MANIFEST
        manifest = json.loads(path.read_text("utf-8")) if path.is_file() else {}
        if manifest and manifest.get("schema") != SCHEMA:
            raise ValueError(f"{path} declares {manifest.get('schema')!r}, not {SCHEMA!r}")
        # by file, as the platform's screens name them: {role: {"file", "size", "stored"}}
        self.boxes = {entry["file"]: entry for entry in (manifest.get("pictures") or {}).values()}
        self.face_file = (manifest.get("typeface") or {}).get("regular")

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
            box = {"size": [size["width"], size["height"]]}
        return picture(data, *box["size"], box.get("stored"))

    def face_directory(self) -> Path:
        """The folder whose typeface a build draws: the theme's when it has one of its
        own - a copy of the scaffold's, as the Example's is, is the scaffold's."""
        if self.face_file and self.themed(self.face_file) and \
                self.path(self.face_file).read_bytes() != \
                (self.scaffold / self.face_file).read_bytes():
            return self.theme
        return self.scaffold
