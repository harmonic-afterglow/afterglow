"""The log file: what the remote operations did, and anything that went wrong.

A tester whose remote answered "unknown error" had nothing to send: the interface showed
the one line, nothing reached the console, and there was no file. Now every remote
operation's steps and outcome, and any error the interface did not expect, go to
`Documents/Afterglow/afterglow.log` (and the console), which Help > Show log file opens.
"""
from __future__ import annotations

import contextlib
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

from . import paths

LOG = logging.getLogger("afterglow")
NAME = "afterglow.log"


def path() -> Path:
    return paths.app_dir() / NAME


def setup() -> Path | None:
    """Start logging to the file and the console; None when the file cannot be
    written, and the console alone is used."""
    if LOG.handlers:
        return path()
    LOG.setLevel(logging.INFO)
    form = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(form)
    LOG.addHandler(console)
    written = None
    with contextlib.suppress(OSError):
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        # Two files of a megabyte: enough for a session's worth of writes, small enough
        # to attach to a bug report.
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
        handler.setFormatter(form)
        LOG.addHandler(handler)
        written = target
    from . import __version__
    LOG.info("Afterglow %s on %s, Python %s", __version__, sys.platform,
             sys.version.split()[0])
    _catch_uncaught()
    return written


def _catch_uncaught():
    previous, previous_thread = sys.excepthook, threading.excepthook

    def hook(kind, value, trace):
        LOG.error("Unexpected error", exc_info=(kind, value, trace))
        previous(kind, value, trace)

    def thread_hook(args):
        LOG.error("Unexpected error in %s", getattr(args.thread, "name", "a thread"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        previous_thread(args)

    sys.excepthook = hook
    threading.excepthook = thread_hook
