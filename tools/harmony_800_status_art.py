#!/usr/bin/env python3
"""Take the Harmony 800's own status pictures out of its factory configuration.

    python3 tools/harmony_800_status_art.py usercfg.bin

The firmware's notices on the 800 are the One's drawing programs (platform/), drawn with
the One's pictures centred on the larger display. The 800's factory configuration - the
one a remote carries before it is set up, read from `/cfg/usercfg` - has its own: the
battery warning, USB connected and the charging battery, each a whole 240 x 320 screen,
and the red cross of a charging problem. This reads those pictures (artwork only) and
writes them into the scaffold: the warning's and USB's icons cut out of their screens, to
sit above the notices' words as the One lays a notice out, the charging screen whole, and
the cross as it is.

The factory configuration is not part of this repository; only these pictures are kept.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import imaging  # noqa: E402
from afterglow.backends.harmony_800 import bitmap  # noqa: E402

SCAFFOLD = ROOT / "src/afterglow/scaffolds/harmony-800"
BASE = 0x050000                 # where the 800 keeps `/cfg/usercfg` in its flash
# Each picture taken: its address in the factory configuration, and the part of it kept
# (x, y, width, height), or the whole of it.
PICTURES = {
    "platform/battery-low": (0x140207, (80, 150, 84, 96)),
    "platform/usb-connected": (0x0CF1C2, (76, 129, 94, 126)),
    "charging/battery": (0x0A9821, None),
    "platform/screen-09-0": (0x0832FF, None),
}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    raw = Path(argv[0]).read_bytes()
    if raw[:4] != b"GSGD":
        print("not an 800 configuration (no GSGD header)", file=sys.stderr)
        return 1
    manifest_path = SCAFFOLD / "assets.json"
    manifest = json.loads(manifest_path.read_text())
    for role, (address, box) in PICTURES.items():
        picture = bitmap.decode(raw, address - BASE)
        rows = picture["rows"]
        if box is not None:
            x, y, width, height = box
            rows = [row[x:x + width] for row in rows[y:y + height]]
        rgba = [[(0, 0, 0, 255) if pixel is None else (*pixel, 255) for pixel in row]
                for row in rows]
        file = f"images/{role}.png"
        (SCAFFOLD / file).write_bytes(imaging.encode(rgba))
        manifest["pictures"][role] = {"file": file, "mode": "raw",
                                      "size": [len(rgba[0]), len(rgba)]}
        print(f"{file}: {len(rgba[0])}x{len(rgba)} from {address:#x}")
    manifest["pictures"] = dict(sorted(manifest["pictures"].items()))
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
