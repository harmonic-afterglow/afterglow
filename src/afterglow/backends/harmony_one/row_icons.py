"""Device-row icons, composed at build time from the row frame and a type icon.

A Harmony One draws a device row as two pictures: the row frame, then a 51x48 icon over
its left end. The display has one-bit transparency, so an icon cannot blend into the frame
on the remote; Logitech's icons therefore carried a copy of the frame's patch behind them.
This module does the same at build time: it cuts the patch out of the scaffold's row
frame and blends a type icon onto it, scaled to fit. So the scaffold holds one icon per
device or activity type (images/icons/), any of them can be redrawn at any size, and a
reskinned row frame carries its icons with it.

Pure standard library: pictures are rows of RGBA tuples, as `afterglow.imaging` decodes them.
"""
from __future__ import annotations

from pathlib import Path

ICONS_DIR = "images/icons"
KINDS = ("devices", "activities")
# What a device or activity with no type, or a type the scaffold has no icon for, shows.
FALLBACK = ("activities", "VirtualGeneric")
# The icon fits inside this box, centred on the patch, its proportions kept.
FIT = (47, 40)


def scale(rows: list[list[tuple]], width: int, height: int) -> list[list[tuple]]:
    """``rows`` resampled to ``width`` x ``height`` by averaging the area each new pixel
    covers, weighted by alpha so a transparent pixel lends no colour to its neighbours."""
    source_h, source_w = len(rows), len(rows[0])
    out = []
    for y in range(height):
        top, bottom = y * source_h / height, (y + 1) * source_h / height
        line = []
        for x in range(width):
            left, right = x * source_w / width, (x + 1) * source_w / width
            total = red = green = blue = alpha = 0.0
            for sy in range(int(top), min(source_h, int(-(-bottom // 1)))):
                cover_y = min(bottom, sy + 1) - max(top, sy)
                for sx in range(int(left), min(source_w, int(-(-right // 1)))):
                    cover = cover_y * (min(right, sx + 1) - max(left, sx))
                    r, g, b, a = rows[sy][sx]
                    weight = cover * a
                    red, green, blue = red + r * weight, green + g * weight, blue + b * weight
                    alpha += weight
                    total += cover
            if alpha:
                line.append((round(red / alpha), round(green / alpha), round(blue / alpha),
                             round(alpha / total)))
            else:
                line.append((0, 0, 0, 0))
        out.append(line)
    return out


def fitted(width: int, height: int, box=FIT) -> tuple[int, int]:
    factor = min(box[0] / width, box[1] / height, 1.0)
    return max(1, round(width * factor)), max(1, round(height * factor))


def compose(frame: list[list[tuple]], at: tuple[int, int], size: tuple[int, int],
            icon: list[list[tuple]]) -> list[list[tuple]]:
    """The ``size`` patch of ``frame`` at ``at``, with ``icon`` scaled into it and blended
    over it. Where the frame itself is transparent the patch stays transparent, unless the
    icon covers it."""
    x0, y0 = at
    width, height = size
    patch = [[frame[y0 + y][x0 + x] if y0 + y < len(frame) and x0 + x < len(frame[0])
              else (0, 0, 0, 0) for x in range(width)] for y in range(height)]
    icon = scale(icon, *fitted(len(icon[0]), len(icon)))
    left, top = (width - len(icon[0])) // 2, (height - len(icon)) // 2
    for y, line in enumerate(icon):
        for x, (r, g, b, a) in enumerate(line):
            under = patch[top + y][left + x]
            if not a:
                continue
            if not under[3]:
                patch[top + y][left + x] = (r, g, b, a)
                continue
            share = a / 255
            patch[top + y][left + x] = (
                round(r * share + under[0] * (1 - share)),
                round(g * share + under[1] * (1 - share)),
                round(b * share + under[2] * (1 - share)), 255)
    return patch


def source(directory, kind: str, name: str | None) -> Path | None:
    """The scaffold's icon for a ``kind`` ("devices" or "activities") of type ``name``,
    the fallback when it has none, or None for a scaffold without type icons."""
    folder = Path(directory) / ICONS_DIR
    for path in ([folder / kind / f"{name}.png"] if name else []) + [
            folder / FALLBACK[0] / f"{FALLBACK[1]}.png"]:
        if path.is_file():
            return path
    return None


def role(kind: str, name: str | None, directory) -> str | None:
    """The picture role a composed icon is placed under: one per icon file."""
    path = source(directory, kind, name)
    return None if path is None else f"row-icon/{path.parent.name}/{path.stem}"
