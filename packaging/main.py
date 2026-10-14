#!/usr/bin/env python3
"""Entry point for the bundled application.

**Deliberately not named `afterglow.py`.** PyInstaller places the entry script in the
extraction directory and puts that directory on `sys.path`, so a script with the
package's name shadows the package: `import afterglow` finds the launcher, and
`from afterglow import backends` fails with "cannot import name". The repository's
`afterglow.py` warns about exactly this shadowing for the source tree; a frozen build
walks into it from the other direction, and the only fix is a different filename.
"""
import os
import sys


def _usable(stream) -> bool:
    try:
        os.fstat(stream.fileno())
        stream.flush()
    except (AttributeError, OSError, ValueError):
        return False
    return True


def _quiet_missing_console() -> None:
    """A windowed executable has no console, yet its `sys.stdout` can still be a stream
    on a handle that does not exist. Every `print()` then lands in a buffer, and the
    first time the buffer fills, the flush fails with "[Errno 9] Bad file descriptor" -
    in the middle of whatever was printing, such as a build. Output with nowhere to go
    is dropped instead; the log file keeps what matters."""
    for name in ("stdout", "stderr"):
        if not _usable(getattr(sys, name)):
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def main() -> int:
    _quiet_missing_console()
    if "--version" in sys.argv[1:]:
        # Answering this must not need Qt: it is what someone runs to report a bug.
        from afterglow import __version__
        print(__version__)
        return 0
    if "--usb-driver" in sys.argv[1:]:
        # The elevated half of switching the remote's Windows driver: started by the
        # running application through Windows' consent prompt, never by hand.
        from afterglow.windows_driver import main as usb_driver
        return usb_driver()
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
