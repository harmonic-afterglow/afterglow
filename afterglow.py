#!/usr/bin/env python3
"""Afterglow - build and flash configurations for a Harmony remote.

    python3 afterglow.py

The package lives in `src/` so that the folder you are looking at is the whole
application: everything it needs is beside this file, and nothing above it matters.

`src` goes on the path *first* on purpose. This file is called `afterglow.py` and the
package is called `afterglow`, so with the script's own directory searched first,
`import afterglow` would find this launcher instead of the package and import the
wrapper a second time under a different name.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    from afterglow.launch import handle_flags  # noqa: E402 - needs `src` on the path first
    status = handle_flags()
    if status is not None:
        raise SystemExit(status)
    from afterglow.gui import main  # noqa: E402
    main()
