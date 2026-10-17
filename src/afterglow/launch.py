"""The command-line flags Afterglow answers instead of opening its window - one copy for
every entry point.

`afterglow.py` (a source checkout) and `packaging/main.py` (the bundled application) both
hand their arguments here first. Each used to keep its own list of flags, and the
checkout's fell behind: `python afterglow.py --version` opened the window instead of
answering. Opening the window stays with them: this module is below the interface and
must not import it.
"""
from __future__ import annotations

import sys


def handle_flags(argv: list[str] | None = None) -> int | None:
    """The exit status of the flag given, or None when there is none to answer and the
    window should open."""
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        # Answering this must not need Qt: it is what someone runs to report a bug.
        from . import __version__
        print(__version__)
        return 0
    if "--usb-driver" in args:
        # The elevated half of switching the remote's Windows driver: started by the
        # running application through Windows' consent prompt, never by hand.
        from .windows_driver import main as usb_driver
        return usb_driver()
    if "--self-check" in args:
        from .selfcheck import run
        return run()
    if "--concord-check" in args:
        from .selfcheck import concord_check
        return concord_check()
    if "--driver-check" in args:
        # Windows only: that direct access can find Windows' generic WinUSB entry.
        from .windows_driver import generic_driver_check
        return generic_driver_check()
    if "--import-check" in args:
        # Prove a build can do the thing it exists for, not merely that its registries
        # resolve: read a real configuration end to end.
        from .selfcheck import import_check
        return import_check(args[args.index("--import-check") + 1])
    return None
