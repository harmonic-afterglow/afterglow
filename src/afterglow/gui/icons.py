"""Icons for device and activity types.

The pictures come from the remote's own firmware, extracted into `icons/` by
`tools/export_icons.py`. They are what a Harmony owner recognises, because they
are literally what the remote draws. That makes them the project's remote's: a Harmony One
or 800 draws its own set, so a profile names where that remote's pictures are
(`RemoteProfile.type_icons`) and everything that shows a device or an activity passes the
project's remote. Without one - and for button glyphs, which only `icons/` has - it is the
Harmony 900's and 1100's set.

There is deliberately **no substitute set**. Drawn stand-ins were tried and removed: an
abstract box-with-dots is not more useful than an honest blank, and it made the interface
look finished while showing something that was not the user's device. If a type has no
picture, it has no icon.

Replacing the artwork is a drop-in: a file per type, named after the type
(`devices/Television.png`, `activities/VirtualDvd.png`, `buttons/myTV.png`). Nothing here
knows or cares where the images came from.
"""
from pathlib import Path

from ..qt.QtCore import QSize, Qt
from ..qt.QtGui import QIcon, QPixmap

from .. import paths

ARTWORK = paths.icons()
FOLDERS = ("devices", "activities", "buttons")

EXTRACT_HINT = ("Extract them from a firmware image:\n"
                "    python3 tools/export_icons.py path/to/61.hfw")

_paths: dict[tuple[str, str], Path | None] = {}
_pixmaps: dict[tuple[str, int], QPixmap] = {}


def artwork_for(type_name: str, remote=None) -> Path | None:
    """The image for a type, or None if there is none: from `remote`'s own set when a
    profile is given - its stand-in where that remote draws one for a type it has no
    picture of - else from `icons/`."""
    folder, fallback = remote.type_icons if remote is not None else (ARTWORK, None)
    key = (str(folder), type_name)
    if key not in _paths:
        candidates = []
        if type_name:
            candidates += [folder / kind / f"{type_name}.png" for kind in FOLDERS[:2]]
            candidates.append(ARTWORK / "buttons" / f"{type_name}.png")
        if fallback:
            candidates.append(folder / f"{fallback}.png")
        _paths[key] = next((path for path in candidates if path.is_file()), None)
    return _paths[key]


def have_artwork() -> bool:
    return ARTWORK.is_dir() and any((ARTWORK / folder).is_dir() for folder in FOLDERS)


def missing(type_names, remote=None) -> list[str]:
    """Types with no picture - so the interface can say what it cannot show."""
    return [name for name in type_names if artwork_for(name, remote) is None]


def pixmap(type_name: str, size: int = 24, remote=None) -> QPixmap:
    """A type's icon, or a null pixmap. Never a stand-in of our own - only the one
    `remote` itself draws."""
    source = artwork_for(type_name, remote)
    if source is None:
        return QPixmap()
    key = (str(source), size)
    if key not in _pixmaps:
        _pixmaps[key] = QPixmap(str(source)).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    return _pixmaps[key]


def icon(type_name: str, size: int = 24, remote=None) -> QIcon:
    source = pixmap(type_name, size, remote)
    return QIcon() if source.isNull() else QIcon(source)


def populate(combo, type_names, size: int = 20, labels=None, remote=None):
    """Fill a combo with each type: readable label shown, identifier carried as data."""
    combo.setIconSize(QSize(size, size))
    labels = labels or {}
    for name in type_names:
        combo.addItem(icon(name, size, remote), labels.get(name, name), name)
