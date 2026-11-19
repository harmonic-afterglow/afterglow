#!/usr/bin/env python3
"""Derive a Harmony 5xx model's platform from another model's, by measuring its households.

    python3 tools/arch9_derive_platform.py --remote harmony-525 HOUSEHOLD.EZHex [...]

## Why this exists

A model's platform is read from an empty configuration of its own
(tools/arch9_extract_platform.py), and Logitech's software, which wrote those, is gone. Only
the 555's survives. Walked side by side from the platform's roots, the households of the 525,
520, 550 and Harmony for Xbox 360 hold the 555's empty platform in the same shape - the same
firmware screens, the same wiring, the same constant sections - and differ in three things:
the skin, the keys their key lists name, and a word or two (afterglow-research/harmony-555.md,
"The other models' platforms"). So such a model's scaffold is a short file naming the
platform it is derived from and those three differences, measured here from its households:

- the skin each household states, which must agree;
- the key codes the idle key set lists, against the source platform's: the ones it lacks
  and the ones it has besides, which every household must agree on;
- the Activities menu's title, as the households' own words have it;
- for a model whose firmware build reaches the firmware otherwise - the 515 and 510 - the
  parts of the platform its households hold otherwise, grafted in (graft.py): every
  household must give the same graft, and what a household changes is never taken
  (`platform/household.json` of the source).

Nothing that identifies a household is written: the derived file names its evidence by
hash.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex, paths, remotes  # noqa: E402
from afterglow.backends.harmony_555 import generate, graft, gspm, importing  # noqa: E402

IDLE_KEYS = 2          # context 2 lists every key the remote has


def payload_of(path: Path) -> bytes:
    raw = path.read_bytes()
    return raw if raw[:4] == b"AHCM" else ezhex.read(raw).payload


def presses(context: dict) -> set[int]:
    return {row["key_code"] & 0x7F for row in context["rows"] if row["key_code"] & 0x80}


def menu_title(image) -> str | None:
    for screen in image.screens:
        for slot in screen["slots"][:1]:
            lines = image.page_text(slot["program_offset"])
            if lines and lines[0]["y"] == 0 and lines[0]["text"].lower().startswith(
                    "choose an"):
                return lines[0]["text"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--remote", required=True)
    parser.add_argument("--source", default="harmony-555",
                        help="the model whose platform this one's is derived from")
    parser.add_argument("households", nargs="+", type=Path)
    args = parser.parse_args()
    profile = remotes.get(args.remote)
    source = Path(paths.scaffolds(args.source))
    base = generate.load_json(source, generate.WIRING_FILE, generate.WIRING_SCHEMA)
    base_keys = {row[1] & 0x7F for row in base["contexts"][IDLE_KEYS]["rows"]
                 if row[1] & 0x80}
    base_title = next(line["text"] for screen in generate.load_json(
        source, generate.SCREENS_FILE, generate.SCREENS_SCHEMA)["screens"]
        for page in screen["pages"][:1] for line in page["lines"]
        if line["y"] == 0 and line["text"].lower().startswith("choose an"))

    places_file = source / graft.HOUSEHOLD_FILE
    places = ({tuple(place) for place in json.loads(places_file.read_text("utf-8"))["places"]}
              if places_file.is_file() else None)
    platform = graft.model_view(base, generate.load_json(
        source, generate.SCREENS_FILE, generate.SCREENS_SCHEMA))
    grafts, backlights = set(), []
    skins, keysets, titles, evidence = set(), set(), set(), []
    for path in args.households:
        payload = payload_of(path)
        gspm.validate(payload)
        skin = payload[gspm.section_ranges(payload)[1][0] + generate.SKIN_AT]
        if skin not in profile.skins:
            raise SystemExit(f"{path.name} is skin {skin}, not a {profile.model}")
        image = importing.Image(payload)
        skins.add(skin)
        keysets.add(frozenset(presses(image.contexts[IDLE_KEYS])))
        title = menu_title(image)
        if title:
            titles.add(title)
        evidence.append(hashlib.sha256(payload).hexdigest()[:16])
        if places is not None:
            measured = graft.graft(platform, graft.image_view(payload), places)
            # the backlight's time is the owner's setting: its most common value is kept
            for index, timer in list(measured["timers"].items()):
                if graft.timer_role(platform, platform.timers[index]) == "backlight":
                    backlights.append(timer[1])
                    timer[1] = None
            grafts.add(json.dumps(measured, sort_keys=True))
    # a remote sold under several skins (the 515 and 510) is one platform: its own skin is
    # written by the build (settings.skin)
    if len(keysets) != 1:
        raise SystemExit(f"the households disagree: skins {skins}, "
                         f"{len(keysets)} different key sets")
    if len(grafts) > 1:
        raise SystemExit(f"the households disagree on the platform: {len(grafts)} grafts")
    grafted = json.loads(grafts.pop()) if grafts else None
    # a model whose objects are the platform's differs in its keys alone, which the key
    # lists say; only one that wires otherwise is grafted
    if grafted is not None and not grafted["objects"] and not grafted["new"]:
        grafted = None
    if grafted is not None:
        seconds = max(set(backlights), key=backlights.count) if backlights else None
        for timer in grafted["timers"].values():
            if timer[1] is None:
                timer[1] = seconds
    measured = next(iter(keysets))
    words = {}
    for title in titles:
        cut = title.removesuffix("..")
        if (cut.lower() == base_title.lower()[:len(cut)] and cut != base_title[:len(cut)]):
            words[base_title] = cut + base_title[len(cut):]
    derived = {
        "schema": generate.DERIVED_SCHEMA,
        "from": args.source,
        "skin": profile.skin if len(skins) > 1 else skins.pop(),
        "absent_scans": sorted(base_keys - measured),
        "added_scans": sorted(measured - base_keys),
        "words": words,
        **({"graft": grafted} if grafted else {}),
        "evidence": {"households": sorted(evidence),
                     "tool": "tools/arch9_derive_platform.py"},
    }
    target = Path(paths.scaffolds()) / args.remote / "platform"
    target.mkdir(parents=True, exist_ok=True)
    (target / Path(generate.DERIVED_FILE).name).write_text(
        json.dumps(derived, indent=1) + "\n", "utf-8")
    print(f"{args.remote}: skin {derived['skin']}, lacks {derived['absent_scans']}, adds "
          f"{derived['added_scans']}, words {words}, from {len(evidence)} households"
          + (f"; grafted {len(grafted['objects'])} objects, {len(grafted['contexts'])} key "
             f"sets, {len(grafted['timers'])} timers, {len(grafted['new'])} new objects"
             if grafted else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
