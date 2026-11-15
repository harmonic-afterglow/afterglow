#!/usr/bin/env python3
"""Write the Harmony 650's and 700's translation templates from the words a build draws.

    python3 tools/arch14_pot.py [--remote harmony-650|harmony-700]

Every word a generated 650 or 700 shows is listed in its backend's catalogue.py, with a
note for the translator on where it is drawn and how much room it has. This writes them
to the backend's locale/<domain>.pot, the template a translator copies to `<language>.po`
(Poedit, Weblate and the rest read it), and brings `en.po` in step: new messages added,
gone ones dropped, English wording already there kept. A test fails when either is out of
step with the catalogue, so run this after changing a word. Without --remote, both.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

REMOTES = ("harmony-650", "harmony-700")


def write(remote: str) -> None:
    catalogue = importlib.import_module(
        f"afterglow.backends.{remote.replace('-', '_')}.catalogue")
    path = catalogue.LOCALE_DIR / f"{catalogue.DOMAIN}.pot"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(catalogue.template(), "utf-8")
    print(f"wrote {len(catalogue.MESSAGES)} messages to {path}")
    # English is a catalogue too: keep its wording, add what is new, drop what is gone.
    english = catalogue.LOCALE_DIR / "en.po"
    existing = english.read_text("utf-8") if english.is_file() else None
    english.write_text(catalogue.english_catalogue(existing), "utf-8")
    print(f"updated {english}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remote", choices=REMOTES, action="append")
    for remote in parser.parse_args(argv).remote or REMOTES:
        write(remote)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
