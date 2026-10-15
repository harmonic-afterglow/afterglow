#!/usr/bin/env python3
"""Fit the Harmony One's frames and fonts to the Harmony 800's screens (scaffolds/harmony-800).

    python3 tools/harmony_800_fit_artwork.py

The 800's scaffold began as a copy of the One's. The screens this backend builds for the
800 are 240 pixels wide (backends/harmony_800/pages.py): two columns of 114-pixel buttons
and four rows of them, and rows 228 pixels wide. A frame is plain across its middle, so it
is widened by repeating its middle column, which keeps its ends and its gradient exactly.
The fourth row of buttons draws the frames of the third. The backdrop - what clears the
display before a screen draws - is made the display's size, the charging screens are made
to fill the display, and the fonts set to Galmuri 11 and Galmuri 9, drawn at their own sizes.

Run it once on a fresh copy of the One's scaffold; it is not meant to be run twice.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import imaging  # noqa: E402

SCAFFOLD = ROOT / "src/afterglow/scaffolds/harmony-800"
BUTTON_WIDTH, ROW_WIDTH = 114, 228
BUTTONS = ("button-frame", "activity/button-frame", "options/button-frame")
ROWS = ("row-frame", "row-frame/1", "row-frame/2", "activity/row-frame",
        "options/row-frame/0", "options/row-frame/1", "options/row-frame/2")


def widen(path: Path, width: int) -> list[int]:
    image = imaging.decode(path.read_bytes())
    rows = image["rows"]
    middle = len(rows[0]) // 2
    extra = width - len(rows[0])
    if extra < 0:
        raise ValueError(f"{path} is already wider than {width}")
    rows = [row[:middle] + [row[middle]] * extra + row[middle:] for row in rows]
    path.write_bytes(imaging.encode(rows))
    return [width, len(rows)]


def fill(path: Path, width: int, height: int, *, cover: bool) -> list[int]:
    """A whole-screen picture made to fill the 800's: ``cover`` scales it up until it
    covers the screen and cuts the overflow (the charging photographs); otherwise it is
    centred on black (the charging battery, which is black around its icon)."""
    image = imaging.decode(path.read_bytes())
    rows, w, h = image["rows"], image["width"], image["height"]
    if cover:
        scale = max(width / w, height / h)
        sw, sh = round(w * scale), round(h * scale)
        left, top = (sw - width) // 2, (sh - height) // 2
        out = [[rows[min(h - 1, int((y + top) / scale))][min(w - 1, int((x + left) / scale))]
                for x in range(width)] for y in range(height)]
    else:
        black = (0, 0, 0, 255)
        left, top = (width - w) // 2, (height - h) // 2
        out = [[black] * width for _ in range(height)]
        for y in range(h):
            out[top + y][left:left + w] = rows[y]
    path.write_bytes(imaging.encode(out))
    return [width, height]


def main() -> int:
    manifest_path = SCAFFOLD / "assets.json"
    manifest = json.loads(manifest_path.read_text())
    pictures = manifest["pictures"]
    for group in BUTTONS:
        for index in range(6):
            role = f"{group}/{index}"
            pictures[role]["size"] = widen(SCAFFOLD / pictures[role]["file"], BUTTON_WIDTH)
        for index, source in ((6, 4), (7, 5)):
            role, file = f"{group}/{index}", f"images/{group}/{index}.png"
            shutil.copyfile(SCAFFOLD / pictures[f"{group}/{source}"]["file"], SCAFFOLD / file)
            pictures[role] = dict(pictures[f"{group}/{source}"], file=file)
    for role in ROWS:
        pictures[role]["size"] = widen(SCAFFOLD / pictures[role]["file"], ROW_WIDTH)
    # The backdrop, black, covers the whole display: the 800 clears its screen with it.
    backdrop = pictures["backdrop"]
    (SCAFFOLD / backdrop["file"]).write_bytes(
        imaging.encode([[(0, 0, 0, 255)] * 240 for _ in range(320)]))
    backdrop["size"] = [240, 320]
    # The charging screens fill the display: the battery centred, the photographs covering it.
    for role, entry in pictures.items():
        if role.startswith("charging/"):
            entry["size"] = fill(SCAFFOLD / entry["file"], 240, 320,
                                 cover=role != "charging/battery")
    # Text from Galmuri 11 and Galmuri 9 at their own sizes, in slots tall enough for them
    # (backends/harmony_800/faces.py): 18 pixels, and 13 for the One's 11-pixel slots.
    manifest["typeface"] = {"regular": "fonts/galmuri/Galmuri11.bdf.gz",
                            "small": "fonts/galmuri/Galmuri9.bdf.gz"}
    for font in manifest["fonts"].values():
        font["height"] = 13 if font["height"] <= 11 else 18
    manifest["remote"] = "harmony-800"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"fitted {len(BUTTONS) * 8 + len(ROWS)} frames in {SCAFFOLD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
