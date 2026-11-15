#!/usr/bin/env python3
"""Draw every page of an arch-14 configuration - a Harmony 650's or 700's - into one PNG.

    python3 tools/arch14_render.py --remote harmony-700 config.EZHex out.png

A page is drawn as the remote would draw it, from the configuration's own pictures and
glyphs: calls and jumps followed, a switch drawn by its first case, the corner programs
the page queues left out. It is how a generated configuration is looked at before it goes
anywhere near a remote, and how one of Logitech's is compared with it.

Format reference: docs/harmony_650_700/gspm.md
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from afterglow import ezhex, imaging, remotes  # noqa: E402

SCREEN = 128
GAP = 4
COLUMNS = 10


def payload_of(path: Path) -> bytes:
    raw = path.read_bytes()
    if raw[:4] == b"GSPM":
        return raw
    _header, start, size, _checksum = ezhex._split(raw)
    return raw[start:start + size]


def render(backend, payload: bytes, program: int, fonts: list[dict]) -> list[list[tuple]]:
    bitmap, drawing, ui_index = backend["bitmap"], backend["drawing"], backend["ui_index"]
    canvas = [[(0, 0, 0)] * SCREEN for _ in range(SCREEN)]

    def put(rows, x, y):
        for dy, line in enumerate(rows):
            for dx, pixel in enumerate(line):
                if pixel is not None and 0 <= y + dy < SCREEN and 0 <= x + dx < SCREEN:
                    canvas[y + dy][x + dx] = tuple(pixel[:3])

    attribute = [0]

    def run(at, depth=0):
        if depth > 8:
            return
        for item in ui_index.drawing_program(payload, at)["instructions"]:
            kind = item["opcode"]
            if kind in ("call", "jump"):
                run(item["target"], depth + 1)
            elif kind == "switch" and (item["cases"] or item["ranges"]):
                run(item["cases"][0][1] if item["cases"] else item["ranges"][0][2], depth + 1)
            elif kind in ("bitmap", "sized_bitmap"):
                put(bitmap.decode(payload, item["target"])["rows"], item["x"], item["y"])
            elif kind == "rectangle":
                colour = bitmap.from_rgb565(item["color"])
                put([[colour] * item["width"]] * item["height"], item["x"], item["y"])
            elif kind == "attribute":
                attribute[0] = item["value"]
            elif kind in ("text", "inline_text"):
                font = fonts[attribute[0]] if attribute[0] < len(fonts) else None
                x = item["x"]
                for code in drawing.glyph_codes(bytes.fromhex(item["glyphs"])):
                    glyph = font["glyphs"].get(code) if font else None
                    if glyph:
                        shape = bitmap.decode_glyph(payload, glyph["offset"])
                        put(shape["rows"], x, item["y"])
                        x += shape["width"]
    run(program)
    return canvas


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remote", required=True)
    parser.add_argument("config", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    package = "afterglow.backends." + remotes.get(args.remote).backend.replace("-", "_")
    backend = {name: importlib.import_module(f"{package}.{name}")
               for name in ("bitmap", "drawing", "font_index", "ui_index")}
    payload = payload_of(args.config)
    fonts = backend["font_index"].fonts(payload)
    tiles = [render(backend, payload, slot["program_offset"], fonts)
             for screen in backend["ui_index"].screen_slots(payload) for slot in screen["slots"]]
    rows = (len(tiles) + COLUMNS - 1) // COLUMNS
    width, height = COLUMNS * (SCREEN + GAP), rows * (SCREEN + GAP)
    sheet = [[(48, 48, 48, 255)] * width for _ in range(height)]
    for index, tile in enumerate(tiles):
        left, top = (index % COLUMNS) * (SCREEN + GAP), (index // COLUMNS) * (SCREEN + GAP)
        for y, line in enumerate(tile):
            sheet[top + y][left:left + SCREEN] = [(*pixel, 255) for pixel in line]
    args.out.write_bytes(imaging.encode(sheet))
    print(f"drew {len(tiles)} pages into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
