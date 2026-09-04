"""Shared constants: settings keys, library paths and the remote key grid."""

from pathlib import Path


from .. import paths                                            # noqa: E402

HERE = Path(__file__).parent

# The startup offer to set up the Linux USB link. Kept here because the window that asks
# and the tab that checks the answer are in different modules, and `app` already imports
# `tabs` - putting the keys in either one would make that import circular.
USB_LINK_ASK_KEY = "ui/usb_link_never_ask"
USB_LINK_CHOICE_KEY = "ui/usb_link_choice"      # "udev", "session" or "declined"
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
# The vocabulary the firmware ships, kept out of the interface so the build layer can
# check against it without PyQt. Re-exported here because that is where the windows
# have always looked for it.
from .. import vocabulary                                        # noqa: E402
from ..vocabulary import (ACTIVITY_TYPES, DEVICE_TYPE_LABELS,   # noqa: E402,F401
                          DEVICE_TYPES)

# The physical keys this remote's case has, from its profile rather than from a list
# kept here - another model has a different set.
HARD_SLOTS = vocabulary.HARD_KEYS
_REMOTE_GRID = [
    # - Top Zone --------------------------------------------------------
    (0, 0, 1, 2, "Menu", "Menu"),
    (0, 2, 1, 1, None, "Pg Up"),
    (0, 3, 1, 2, "Info", "Info"),

    (1, 0, 1, 2, "Exit", "Exit"),
    (1, 2, 1, 1, None, "Pg Dn"),
    (1, 3, 1, 2, "Guide", "Guide"),

    # - Color Buttons ---------------------------------------------------
    (2, 0, 1, 1, "Red", "Red"),
    (2, 1, 1, 1, "Green", "Green"),
    (2, 3, 1, 1, "Yellow", "Yellow"),
    (2, 4, 1, 1, "Blue", "Blue"),

    # - D-Pad & Volume/Channel ------------------------------------------
    (3, 0, 1, 1, "VolumeUp", "Vol +"),
    (3, 2, 1, 1, "DirectionUp", "Up"),
    (3, 4, 1, 1, "ChannelUp", "Ch +"),

    (4, 1, 1, 1, "DirectionLeft", "Left"),
    (4, 2, 1, 1, "Select", "OK"),
    (4, 3, 1, 1, "DirectionRight", "Right"),

    (5, 0, 1, 1, "VolumeDown", "Vol -"),
    (5, 2, 1, 1, "DirectionDown", "Down"),
    (5, 4, 1, 1, "ChannelDown", "Ch -"),

    # - Middle Function Buttons -----------------------------------------
    (6, 1, 1, 1, "VolumeMute", "*"),           # Often used as mute/aspect
    (6, 3, 1, 1, "PrevChannel", "Return"),     # Curved arrow

    # - Media Transport -------------------------------------------------
    (7, 0, 1, 1, "Rewind", "Rew"),
    (7, 2, 1, 1, "Play", "Play"),
    (7, 4, 1, 1, "FastForward", "FF"),

    (8, 0, 1, 1, "Replay", "Replay"),
    (8, 2, 1, 1, "Pause", "Pause"),
    (8, 4, 1, 1, "Skip", "Skip"),

    (9, 0, 1, 1, "Record", "Record"),
    (9, 4, 1, 1, "Stop", "Stop"),

    # - Numpad ----------------------------------------------------------
    (10, 1, 1, 1, "Number1", "1"),
    (10, 2, 1, 1, "Number2", "2"),
    (10, 3, 1, 1, "Number3", "3"),

    (11, 1, 1, 1, "Number4", "4"),
    (11, 2, 1, 1, "Number5", "5"),
    (11, 3, 1, 1, "Number6", "6"),

    (12, 1, 1, 1, "Number7", "7"),
    (12, 2, 1, 1, "Number8", "8"),
    (12, 3, 1, 1, "Number9", "9"),

    (13, 1, 1, 1, "Back", "Clear"),            # Lower left
    (13, 2, 1, 1, "Number0", "0"),
    (13, 3, 1, 1, "InputAV", "Enter"),         # Lower right 'E'
]
