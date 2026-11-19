#!/usr/bin/env python3
"""Write the Harmony 5xx's translation template from the words a build draws.

    python3 tools/harmony_5xx_pot.py

Every word a generated 510, 515, 520, 525, 550, 555 or Harmony for Xbox 360 draws is
listed in the harmony_555 backend's catalogue.py, with a note for the translator on where
it is drawn and how much room it has. This writes them to the backend's
locale/<domain>.pot, the template a translator copies to `<language>.po` (Poedit, Weblate
and the rest read it), and brings `en.po` in step: new messages added, gone ones dropped,
English wording already there kept. A test fails when either is out of step with the
catalogue, so run this after changing a word.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def write() -> None:
    from afterglow.backends.harmony_555 import catalogue

    path = catalogue.LOCALE_DIR / f"{catalogue.DOMAIN}.pot"
    path.parent.mkdir(parents=True, exist_ok=True)
    for stale in catalogue.LOCALE_DIR.glob("*.pot"):
        if stale != path:
            stale.unlink()
    path.write_text(catalogue.template(), "utf-8")
    print(f"wrote {len(catalogue.MESSAGES)} messages to {path}")
    # English is a catalogue too: keep its wording, add what is new, drop what is gone.
    english = catalogue.LOCALE_DIR / "en.po"
    existing = english.read_text("utf-8") if english.is_file() else None
    english.write_text(catalogue.english_catalogue(existing), "utf-8")
    print(f"updated {english}")


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    write()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
