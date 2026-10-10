#!/usr/bin/env python3
"""Draw the default Harmony One artwork into a scaffold directory.

    python3 tools/harmony_one_default_assets.py src/afterglow/scaffolds/harmony-one

## Why this exists

A generated Harmony One configuration has to carry every picture the remote draws,
because the remote keeps none of them in firmware. The vendor emitted a subset of their
own asset library into every config; we cannot ship theirs, so we ship ours.

Keeping the default set as a generator rather than as a folder of opaque PNGs means the
artwork is readable, reviewable and reproducible: anyone can see exactly what is in it,
change a colour here, and regenerate. Nothing stops an owner replacing any of the files
with their own - that is the point of the directory - but the shipped default is
something the project can explain.

The palette is deliberately plain and dark: the display is RGB565, so flat fills and
hard edges survive it while gradients band and soft edges harden.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from afterglow import imaging  # noqa: E402


INK = (238, 234, 238, 255)
DIM = (148, 153, 164, 255)
EDGE = (82, 93, 106, 255)
PANEL = (32, 36, 49, 255)
DEEP = (16, 20, 24, 255)
GLOW = (98, 178, 238, 255)
WARN = (238, 153, 65, 255)
NONE = (0, 0, 0, 0)


def blank(width: int, height: int, colour=NONE):
    return [[colour for _ in range(width)] for _ in range(height)]


def rect(rows, x0, y0, x1, y1, colour):
    for y in range(max(0, y0), min(len(rows), y1)):
        for x in range(max(0, x0), min(len(rows[0]), x1)):
            rows[y][x] = colour


def frame(rows, x0, y0, x1, y1, colour, width=1):
    for i in range(width):
        rect(rows, x0 + i, y0 + i, x1 - i, y0 + i + 1, colour)
        rect(rows, x0 + i, y1 - i - 1, x1 - i, y1 - i, colour)
        rect(rows, x0 + i, y0 + i, x0 + i + 1, y1 - i, colour)
        rect(rows, x1 - i - 1, y0 + i, x1 - i, y1 - i, colour)


def panel(width: int, height: int, *, fill=PANEL, edge=EDGE):
    rows = blank(width, height, fill)
    frame(rows, 0, 0, width, height, edge)
    # a one-pixel highlight along the top reads as a raised surface at this size
    rect(rows, 1, 1, width - 1, 2, (57, 64, 74, 255))
    return rows


def backdrop(width=176, height=220):
    rows = blank(width, height, DEEP)
    rect(rows, 0, 0, width, 20, (24, 28, 32, 255))
    rect(rows, 0, 19, width, 20, EDGE)
    rect(rows, 0, height - 24, width, height, (24, 28, 32, 255))
    rect(rows, 0, height - 24, width, height - 23, EDGE)
    return rows


def battery(level: int, *, width=20, height=11):
    """Eight levels, the shape the eight-case status program switches between."""
    rows = blank(width, height)
    frame(rows, 0, 1, width - 2, height - 1, INK)
    rect(rows, width - 2, 4, width, height - 4, INK)
    inner = width - 6
    filled = round(inner * level / 7)
    colour = INK if level > 1 else WARN
    rect(rows, 2, 3, 2 + filled, height - 3, colour)
    return rows


def charging(step: int, *, width=20, height=11):
    rows = battery(min(7, 2 + 2 * step))
    rect(rows, 8, 3, 12, height - 3, GLOW)
    return rows


def transmitting(width=20, height=11):
    """An emitter and three waves leaving it, the nearest brightest."""
    rows = blank(width, height)
    middle = height // 2
    rect(rows, 2, middle - 2, 6, middle + 3, GLOW)
    for index, x in enumerate((8, 12, 16)):
        reach = 2 + index
        colour = GLOW if index < 2 else DIM
        rect(rows, x, middle - reach, x + 2, middle + reach + 1, colour)
    return rows


def indicator(width=22, height=18):
    rows = blank(width, height)
    frame(rows, 1, 1, width - 1, height - 1, DIM)
    rect(rows, 5, 5, width - 5, height - 5, GLOW)
    return rows


def progress(width=88, height=10):
    rows = blank(width, height)
    frame(rows, 0, 0, width, height, EDGE)
    rect(rows, 2, 2, width - 2, height - 2, PANEL)
    rect(rows, 2, 2, width // 3, height - 2, GLOW)
    return rows


def row_icon(width=51, height=48):
    rows = panel(width, height)
    rect(rows, 12, 12, width - 12, height - 12, GLOW)
    return rows


ASSETS = {
    "backdrop": (backdrop(), (176, 220), "raw"),
    "button-frame": (panel(81, 50), (81, 50), "shorter"),
    "row-frame": (panel(164, 50), (164, 50), "shorter"),
    "row-icon": (row_icon(), (51, 48), "shorter"),
    "panel": (panel(62, 42), (62, 42), "shorter"),
    "softkey": (panel(88, 22, fill=(24, 28, 32, 255)), (88, 22), "shorter"),
    "indicator": (indicator(), (22, 18), "runs"),
    "progress": (progress(), (88, 10), "shorter"),
    "status/transmitting": (transmitting(), (20, 11), "runs"),
    **{f"status/battery-{n}": (battery(n), (20, 11), "runs") for n in range(8)},
    **{f"status/charging-{n}": (charging(n), (20, 11), "runs") for n in range(3)},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--force", action="store_true",
                        help="overwrite a manifest that already declares fonts")
    args = parser.parse_args()

    # This draws pictures and no fonts, so running it over an extracted scaffold would
    # leave a manifest whose fonts are gone and whose sheets are orphaned.
    existing = args.directory / "assets.json"
    if existing.is_file() and not args.force:
        current = json.loads(existing.read_text("utf-8"))
        if current.get("fonts"):
            raise SystemExit(
                f"{existing} declares {len(current['fonts'])} fonts, which this would "
                "remove. Write somewhere else, or pass --force.")

    pictures = {}
    for role, (rows, size, mode) in sorted(ASSETS.items()):
        name = f"images/{role}.png"
        path = args.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if (len(rows[0]), len(rows)) != size:
            raise SystemExit(
                f"{role} drew {len(rows[0])}x{len(rows)} but declares {size[0]}x{size[1]}")
        path.write_bytes(imaging.encode(rows))
        pictures[role] = {"file": name, "size": list(size), "mode": mode}

    manifest = {
        "schema": "afterglow-scaffold-assets/1",
        "remote": "harmony-one",
        "generator": "tools/harmony_one_default_assets.py",
        "pictures": pictures,
    }
    (args.directory / "assets.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8")
    print(f"wrote {len(pictures)} pictures and assets.json into {args.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
