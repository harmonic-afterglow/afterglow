#!/usr/bin/env python3
"""Record which device or activity type each Harmony One row icon stands for.

A Harmony One draws a device's or an activity's menu row with its type's icon, and
Logitech's icons are the same pixels in every configuration. So a configuration whose
rows are known says which type each icon is, and an import (importing.py) reads the type
of any other configuration's rows from it. Only fingerprints of the icons are written,
to the scaffold (platform/type-icons.json), not the icons.

Each icon is given the type whose scaffold icon, drawn on the same row frame, looks most
like it; ``--type LABEL=TYPE`` names it outright where that is wrong, by the row's label.

    tools/harmony_one_type_icons.py CONFIG.ezhex [...] [--type "AV Receiver=Receiver"]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex, imaging, paths  # noqa: E402
from afterglow.backends.harmony_one import importing, row_icons  # noqa: E402
from afterglow.backends.harmony_one.importing import TYPE_ICONS_FILE  # noqa: E402

KINDS = {"device": "devices", "activity": "activities"}


def nearest(kind: str, frame, at, icon) -> str:
    """The scaffold type whose icon, drawn on ``frame`` at ``at``, is nearest ``icon``."""
    folder = paths.scaffolds("harmony-one") / row_icons.ICONS_DIR / KINDS[kind]
    size = (len(icon[0]), len(icon))
    best = None
    for path in sorted(folder.glob("*.png")):
        drawn = row_icons.compose(frame, at, size, imaging.decode(path.read_bytes())["rows"])
        distance = sum(abs(a - b) for one, two in zip(drawn, icon) for p, q in zip(one, two)
                       for a, b in zip(p[:3], q[:3]))
        if best is None or distance < best[0]:
            best = (distance, path.stem)
    return best[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("configs", nargs="+", type=Path)
    parser.add_argument("--type", action="append", default=[], metavar="LABEL=TYPE")
    parser.add_argument("--out", type=Path,
                        default=paths.scaffolds("harmony-one") / TYPE_ICONS_FILE)
    args = parser.parse_args(argv)
    named = dict(item.split("=", 1) for item in args.type)
    table = {"devices": {}, "activities": {}}
    for path in args.configs:
        with tempfile.TemporaryDirectory() as work:
            ezhex.unpack(str(path), work)
            image = importing.Image((Path(work) / "payload.bin").read_bytes())
        for row in importing.menu_icons(image):
            kind = row["kind"]
            chosen = named.get(row["label"]) or nearest(kind, row["frame"], row["at"],
                                                        row["icon"])
            known = table[KINDS[kind]].setdefault(row["fingerprint"], chosen)
            print(f"{path.name}: {kind} {row['label']!r} -> {known}")
    args.out.write_text(json.dumps({"schema": "afterglow-harmony-one-type-icons/1",
                                    **table}, indent=1, sort_keys=True) + "\n", "utf-8")
    print(f"{sum(map(len, table.values()))} icons -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
