#!/usr/bin/env python3
"""Entry point for the bundled application.

**Deliberately not named `afterglow.py`.** PyInstaller places the entry script in the
extraction directory and puts that directory on `sys.path`, so a script with the
package's name shadows the package: `import afterglow` finds the launcher, and
`from afterglow import backends` fails with "cannot import name". The repository's
`afterglow.py` warns about exactly this shadowing for the source tree; a frozen build
walks into it from the other direction, and the only fix is a different filename.
"""
import sys


def main() -> int:
    if "--version" in sys.argv[1:]:
        # Answering this must not need Qt: it is what someone runs to report a bug.
        from afterglow import __version__
        print(__version__)
        return 0
    if "--self-check" in sys.argv[1:]:
        from afterglow.selfcheck import run
        return run()
    if "--concord-check" in sys.argv[1:]:
        from afterglow.selfcheck import concord_check
        return concord_check()
    if "--import-check" in sys.argv[1:]:
        # Prove the bundle can do the thing it exists for, not merely that its registries
        # resolve: read a real configuration end to end.
        from afterglow.selfcheck import import_check
        return import_check(sys.argv[sys.argv.index("--import-check") + 1])
    from afterglow.gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
