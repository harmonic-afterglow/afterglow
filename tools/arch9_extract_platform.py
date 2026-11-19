#!/usr/bin/env python3
"""Extract a Harmony 5xx's platform layer from an empty configuration into its scaffold.

    python3 tools/arch9_extract_platform.py --remote harmony-555 EMPTY.EZHex \
        src/afterglow/scaffolds/harmony-555

## Why this exists

A 5xx keeps nothing of its screens in firmware: the firmware's own notices (screens 0 to
40), the frame every household is built in - the Devices and Activities screens, "Stopping
Activity", the battery warnings, the Remote Assistant - and the wiring that connects the
firmware's events to them all live in the configuration. A generated configuration has to
supply all of it, so this reads Logitech's empty configuration (one with no device and no
activity, as Logitech's software writes for a new remote) into a model the builder links:

- `platform/wiring.json`: the state variables, contexts, objects, timers, switch tables,
  the start-up list and the small constant tables, as numbers. Nothing in them identifies
  a remote or its owner: an empty configuration has no device, activity or name of its own.
- `platform/screens.json`: every screen as its key lists and, per page, a backdrop, the
  pictures drawn over it and its lines of text with their place and font. The words are
  stored as English and drawn by the builder in its own typeface.
- `images/*.png`: the pictures, one bit a pixel.

The fonts are not taken: a build draws text from Galmuri Afterglow, the typeface the other
remotes' scaffolds ship.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex, imaging, remotes  # noqa: E402
from afterglow.backends.harmony_555 import (  # noqa: E402
    activity_index, command_index, gspm, importing, pixels, render, ui_index)

# Words Logitech cut to fit its own font, kept whole: a build draws them in its own
# typeface and cuts them only if that needs it (generate.py, `fit`).
UNCUT = {"Choose an activi..": "Choose an activity"}
SCHEMA_WIRING = "afterglow-arch9-wiring/1"
SCHEMA_SCREENS = "afterglow-arch9-screens/1"
BANDS = 8
WIDTH = 96


def payload_of(path: Path) -> bytes:
    raw = path.read_bytes()
    return raw if raw[:4] == b"AHCM" else ezhex.read(raw).payload


def _u24(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset:offset + 3], "little")


def _target(payload: bytes, field: int) -> int:
    return _u24(payload, field) - gspm.BASE


class Extract:
    def __init__(self, payload: bytes):
        gspm.validate(payload)
        self.p = payload
        self.ranges = gspm.section_ranges(payload)
        self.image = importing.Image(payload)
        if self.image.unreadable:
            raise SystemExit(f"the donor reads with errors: {self.image.unreadable}")
        if any(name for name in self.image.names.values()
               if not name.startswith(("CurrentLocation", "CurrentActivityState"))):
            raise SystemExit("the donor names devices of its own: use an empty configuration")
        self.fonts = render.Fonts(payload)
        self.pictures: dict[int, str] = {}           # picture offset -> role

    # -- the wiring

    def section12(self) -> list[int]:
        start = self.ranges[12][0]
        count = struct.unpack_from("<H", self.p, start)[0]
        return [_target(self.p, start + 2 + 3 * index) for index in range(count)]

    def atoms_of_program(self, offset: int) -> list[list[int]]:
        """A switch case or section-12 program: atoms, then the end."""
        listing = ui_index.drawing_program(self.p, offset)
        if listing["stopped"] != "end":
            raise SystemExit(f"program {offset:#x} is not a list of atoms")
        atoms = []
        for item in listing["instructions"]:
            if item["opcode"] == "atom":
                atoms.append([item["operand"], item["category"]])
            elif item["opcode"] != "end":
                raise SystemExit(f"program {offset:#x} draws ({item['opcode']})")
        return atoms

    def wiring(self) -> dict:
        p, ranges = self.p, self.ranges
        programs = self.section12()
        at_program = {offset: index for index, offset in enumerate(programs)}
        tables = []
        for group in importing.switch_tables(p):
            cases = []
            for value, block in group["cases"]:
                if block not in at_program:
                    raise SystemExit(f"a switch case at {block:#x} is not a section-12 program")
                cases.append([value, at_program[block]])
            if group["ranges"]:
                raise SystemExit("the donor's switch tables have ranges; not modelled")
            tables.append({"cases": cases})
        start = ranges[15][0]
        count = p[start]
        tail_start = start + 1 + 3 * count
        tail_end = ranges[15][1]
        s16 = ranges[16][0]
        tail_offsets = [_target(p, s16 + 1 + 3 * index) - tail_start
                        for index in range(p[s16])]
        if any(not 0 <= offset < tail_end - tail_start for offset in tail_offsets):
            raise SystemExit("section 16 points outside section 15's tail")
        timers = []
        s13 = ranges[13][0]
        for index in range(p[s13]):
            at = _target(p, s13 + 1 + 3 * index)
            flags, duration = p[at], _u24(p, at + 1)
            operand, opcode = struct.unpack_from("<HB", p, at + 4)
            timers.append([flags, duration, operand, opcode])
        lead_at = ranges[9][0]
        lead = [list(struct.unpack_from("<HB", p, lead_at + 1 + 3 * index))
                for index in range(p[lead_at])]
        variables = [{"initial": record["initial"], "limit": record["limit"],
                      "transitions": [[t["flags"], t["from"], t["to"], t["operand"],
                                       t["category"]] for t in record["transitions"]]}
                     for record in activity_index.engine_records(p)]
        contexts = [{"form": context["form"],
                     "rows": [[row["flags"], row["key_code"], row["operand"], row["category"]]
                              for row in context["rows"]]}
                    for context in activity_index.contexts(p)]
        objects = [[list(atom) for atom in item["atoms"]] for item in command_index.objects(p)]
        section4 = p[ranges[4][0]:ranges[5][0]]
        return {
            "schema": SCHEMA_WIRING,
            "section1": p[ranges[1][0]:ranges[1][1]].hex(),
            "section2": p[ranges[2][0]:ranges[2][1]].hex(),
            "section4": section4.hex(),
            "section17": p[ranges[17][0]:ranges[17][1]].hex(),
            "names": self.names(),
            "lead": lead,
            "variables": variables,
            "contexts": contexts,
            "objects": objects,
            "timers": timers,
            "programs": [self.atoms_of_program(offset) for offset in programs],
            "tables": tables,
            "section15_tail": p[tail_start:tail_end].hex(),
            "section16": tail_offsets,
        }

    def names(self) -> list[list]:
        """Section 0's records as `[level, id, name]`, the levels as the tree nests them."""
        start, end = self.ranges[0]
        p = self.p
        if p[start:start + 2] != b"\xed\xfe" or p[end - 2:end] != b"\xef\xbe":
            raise SystemExit("section 0 is not a name chain")
        out, at = [], start + 5
        while at < end - 2:
            if p[at] != 0xA7:
                raise SystemExit(f"section 0 has no record at {at:#x}")
            length, level, identifier = struct.unpack_from("<HHH", p, at + 1)
            out.append([level, identifier, p[at + 7:at + 3 + length].decode("utf-8")])
            at += 3 + length
        return out

    # -- the screens

    def role(self, offset: int) -> str:
        if offset not in self.pictures:
            self.pictures[offset] = f"picture-{len(self.pictures)}"
        return self.pictures[offset]

    def page(self, program: int) -> dict:
        """A page program in Logitech's shape: eight bands, each the backdrop's band, then
        any picture drawn over it and the text, then the transfer."""
        listing = ui_index.drawing_program(self.p, program, limit=4000)
        if listing["stopped"] != "end":
            raise SystemExit(f"page program {program:#x} stops at {listing['stopped']}")
        backdrop, overlays, lines = None, [], []
        band, attribute = None, None
        seen = set()
        for item in listing["instructions"]:
            kind = item["opcode"]
            if kind == "row":
                band = item["value"]
                first = True
            elif kind == "sized_bitmap":
                sx, sy = bytes.fromhex(item["reserved"])
                whole = (item["x"], item["y"], sx, sy, item["width"], item["height"]) == (
                    0, 8 * band, 0, 8 * band, WIDTH, 8)
                if whole and first:
                    role = self.role(item["target"])
                    if backdrop not in (None, role):
                        raise SystemExit(f"page {program:#x} changes backdrop between bands")
                    backdrop = role
                else:
                    overlay = {"picture": self.role(item["target"]), "x": item["x"],
                               "y": item["y"], "sx": sx, "sy": sy,
                               "width": item["width"], "height": item["height"]}
                    if overlay not in overlays:
                        overlays.append(overlay)
                first = False
            elif kind == "attribute":
                attribute = item["value"]
            elif kind in ("text", "inline_text"):
                codes = bytes.fromhex(item["glyphs"])
                key = (attribute, item["x"], item["y"], codes)
                if key not in seen:
                    seen.add(key)
                    lines.append(self.line(attribute, item["x"], item["y"], codes))
            elif kind in ("transfer", "end"):
                continue
            else:
                raise SystemExit(f"page {program:#x} uses {kind}; not modelled")
        lines.sort(key=lambda line: (line["y"], line["x"]))
        return {"backdrop": backdrop, "overlays": overlays, "lines": lines}

    def line(self, attribute: int, x: int, y: int, codes: bytes) -> dict:
        before = self.image.text.unknown
        text = self.image.text.decode(codes, attribute)
        if self.image.text.unknown != before:
            raise SystemExit(f"a line at ({x}, {y}) reads as {text!r}: name its glyphs first")
        width = sum(len((self.fonts.glyph(attribute, code) or [[0]])[0]) for code in codes)
        centred = abs(x - (WIDTH - width) // 2) <= 1
        return {"attribute": attribute, "x": x, "y": y, "align": "centre" if centred else "left",
                "text": UNCUT.get(text, text)}

    def screens(self) -> list[dict]:
        out = []
        p = self.p
        for screen in self.image.screens:
            trailer = screen["trailer_offset"]
            pages = []
            for slot in screen["slots"]:
                pages.append({
                    "keys": [[entry["key_code"], entry["operand"], entry["category"]]
                             for entry in slot.get("entries", [])],
                    **self.page(slot["program_offset"]),
                })
            out.append({
                "flag": p[trailer],
                "keys": [[entry["key_code"], entry["operand"], entry["category"]]
                         for entry in screen["header_entries"]],
                "pages": pages,
            })
        return out

    def write_pictures(self, directory: Path) -> dict:
        manifest = {}
        for offset, role in sorted(self.pictures.items(), key=lambda item: item[1]):
            picture = pixels.decode_picture(self.p, offset)
            rows = [[(0, 0, 0, 255) if pixel else (255, 255, 255, 255) for pixel in row]
                    for row in picture["rows"]]
            name = f"images/{role}.png"
            (directory / name).parent.mkdir(parents=True, exist_ok=True)
            (directory / name).write_bytes(imaging.encode(rows))
            manifest[role] = {"file": name, "width": picture["width"],
                              "height": picture["height"]}
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--remote", default="harmony-555")
    parser.add_argument("donor", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    profile = remotes.get(args.remote)
    payload = payload_of(args.donor)
    skin = payload[gspm.section_ranges(payload)[1][0] + 2]
    if skin not in profile.skins:
        raise SystemExit(f"the donor is skin {skin}, not a {profile.model}")
    extract = Extract(payload)
    wiring = extract.wiring()
    screens = extract.screens()
    platform = args.directory / "platform"
    platform.mkdir(parents=True, exist_ok=True)
    pictures = extract.write_pictures(args.directory)
    (platform / "wiring.json").write_text(json.dumps(wiring) + "\n", "utf-8")
    (platform / "screens.json").write_text(json.dumps(
        {"schema": SCHEMA_SCREENS, "pictures": pictures, "screens": screens},
        ensure_ascii=False) + "\n", "utf-8")
    print(f"wrote {len(screens)} screens, {len(pictures)} pictures, "
          f"{len(wiring['objects'])} objects, {len(wiring['contexts'])} contexts, "
          f"{len(wiring['variables'])} variables, {len(wiring['tables'])} switch tables "
          f"into {args.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
