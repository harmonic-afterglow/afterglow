"""Shared constants: settings keys and library paths.

What a remote can be told - its device and activity types, its keys and the picture of
its keypad - is not here. It belongs to the remote the project is for, so windows ask
`afterglow.vocabulary` with that remote rather than reading a list fixed at import.
"""

from pathlib import Path


from .. import paths                                            # noqa: E402

HERE = Path(__file__).parent

# The startup offer to set up the Linux USB link. Kept here because the window that asks
# and the tab that checks the answer are in different modules, and `app` already imports
# `tabs` - putting the keys in either one would make that import circular.
USB_LINK_ASK_KEY = "ui/usb_link_never_ask"
USB_LINK_CHOICE_KEY = "ui/usb_link_choice"      # "udev", "session" or "declined"
# The offer to put a remote on Windows' own WinUSB driver (`usb_driver`).
USB_DRIVER_ASK_KEY = "ui/usb_driver_never_ask"
def user_files() -> Path:
    """Where the user's own files live - a built .ezhex, a dump, the project file.

    A function, not a constant: as a module-level constant it resolves the user's
    documents folder at import time and creates a directory as a side effect, and fails
    outright where the platform cannot name a home - which a scrubbed subprocess on
    Windows cannot.

    Deliberately not `paths.root()`, which is where the shipped data sits inside the
    package. Saving a user's project there would write their own devices into the
    application.
    """
    return paths.app_dir()
# The shared device library that "Add Device" searches.
REPO_DIR = paths.library("devices")
