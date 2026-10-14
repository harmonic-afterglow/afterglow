"""Whether Afterglow may save in its own folder.

Windows Security's ransomware protection (Controlled folder access) guards Documents
against programs it does not know, and an unsigned Afterglow is one. It blocks quietly:
a tester's save dialog said "File not found. Check the file name and try again" for
every project, and nothing pointed at Windows Security. A program cannot put itself on
that list - ransomware could too - so the most Afterglow can do is notice and say how.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

# The Windows Security page with "Allow an app through Controlled folder access".
RANSOMWARE_PROTECTION = "windowsdefender://ransomwareprotection"


def can_save_in(folder: Path) -> bool:
    """Create and remove a file in `folder` - what any save there will need."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".afterglow-check-", dir=folder)
        os.close(handle)
        os.remove(name)
    except OSError:
        return False
    return True


def blocked_folder() -> Path | None:
    """Afterglow's own folder when Windows will not let it save there, else None.

    Windows only: elsewhere an unwritable folder has no hidden cause worth naming, and
    the failed save already says what went wrong.
    """
    if sys.platform != "win32" or os.environ.get("AFTERGLOW_HOME"):
        return None
    from . import paths
    folder = paths.app_dir()
    return None if can_save_in(folder) else folder
