"""Icons for device and activity types.

The pictures come from the remote's own firmware, extracted into `icons/` by
`tools/export_icons.py`. They are what a Harmony owner recognises, because they
are literally what the remote draws.

There is deliberately **no substitute set**. Drawn stand-ins were tried and removed: an
abstract box-with-dots is not more useful than an honest blank, and it made the interface
look finished while showing something that was not the user's device. If a type has no
picture, it has no icon.

Replacing the artwork is a drop-in: a file per type, named after the type
(`devices/Television.png`, `activities/VirtualDvd.png`, `buttons/myTV.png`). Nothing here
knows or cares where the images came from.
"""
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap

from .. import paths

ARTWORK = paths.icons()
FOLDERS = ("devices", "activities", "buttons")

EXTRACT_HINT = ("Extract them from a firmware image:\n"
                "    python3 tools/export_icons.py path/to/61.hfw")

_paths: dict[str, Path | None] = {}
_pixmaps: dict[tuple[str, int], QPixmap] = {}


def artwork_for(type_name: str) -> Path | None:
    """The image for a type, or None if there is none."""
    if type_name not in _paths:
        found = None
        for folder in FOLDERS:
            candidate = ARTWORK / folder / f"{type_name}.png"
            if candidate.is_file():
                found = candidate
                break
        _paths[type_name] = found
    return _paths[type_name]


def have_artwork() -> bool:
    return ARTWORK.is_dir() and any((ARTWORK / folder).is_dir() for folder in FOLDERS)


def missing(type_names) -> list[str]:
    """Types with no picture - so the interface can say what it cannot show."""
    return [name for name in type_names if artwork_for(name) is None]


def pixmap(type_name: str, size: int = 24) -> QPixmap:
    """A type's icon, or a null pixmap. Never a stand-in."""
    source = artwork_for(type_name)
    if source is None:
        return QPixmap()
    key = (str(source), size)
    if key not in _pixmaps:
        _pixmaps[key] = QPixmap(str(source)).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    return _pixmaps[key]


def icon(type_name: str, size: int = 24) -> QIcon:
    source = pixmap(type_name, size)
    return QIcon() if source.isNull() else QIcon(source)


def populate(combo, type_names, size: int = 20, labels=None):
    """Fill a combo with each type: readable label shown, identifier carried as data."""
    combo.setIconSize(QSize(size, size))
    labels = labels or {}
    for name in type_names:
        combo.addItem(icon(name, size), labels.get(name, name), name)
