"""Where an image is read against when no remote is named: the scaffold of the first
remote this backend serves, whose platform holds the fonts and glyph shapes the reader
compares a configuration's own against.
"""

from __future__ import annotations

import json
from pathlib import Path

BACKEND = "harmony-555"


def default_directory() -> Path:
    """The scaffold an image is read against when no remote is named: the first remote
    this backend serves that has one, or the one a model's derived platform names
    (generate.DERIVED_FILE), which holds the fonts and glyph shapes; a build always names
    its remote's own (backend.build_project)."""
    from ... import paths, remotes

    for profile in remotes.load_all():
        directory = Path(paths.scaffolds(profile.id))
        if profile.backend != BACKEND or not directory.is_dir():
            continue
        derived = directory / "platform" / "derived.json"
        if derived.is_file():
            directory = directory.parent / json.loads(derived.read_text("utf-8"))["from"]
        return directory
    raise FileNotFoundError("no remote this backend serves has a scaffold")
