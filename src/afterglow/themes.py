"""Themes: a remote's look, kept in `Documents/Afterglow/Themes/<remote>/<name>/`.

A theme is a folder laid out like the remote's scaffold - its pictures, fonts and colours
- so making one is copying a folder and changing files. Which remotes take themes is the
remote's profile's to say (`interface.settings` lists "theme"); nothing here names one.

Each such remote's folder is given an `Example`: the shipped scaffold, copied in so there
is something to copy and change. It is a starting point, not a choice: it draws exactly
what the default does, so it is never offered, and it is put back if it goes missing. A
project names its theme by folder name, so a project moved to another computer finds the
theme of that name there.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import paths

EXAMPLE = "Example"
# A folder is a theme when it has the scaffold's asset manifest.
MANIFEST = "assets.json"


def themed_remotes() -> list:
    """Every remote whose profile offers a theme."""
    from . import remotes

    return [profile for profile in remotes.load_all()
            if "theme" in profile.settings_fields]


def folder(remote_id: str) -> Path:
    """Where a remote's themes are kept."""
    return paths.user_folder("themes") / remote_id


def names(remote_id: str) -> list[str]:
    """The themes a project for this remote may choose, by name - not the example."""
    root = folder(remote_id)
    if not root.is_dir():
        return []
    return sorted(item.name for item in root.iterdir()
                  if item.is_dir() and item.name != EXAMPLE and (item / MANIFEST).is_file())


def path(remote_id: str, name: str) -> Path | None:
    """The folder of a theme by name, or None when there is no such theme."""
    if not name or name == EXAMPLE or Path(name).name != name:
        return None
    candidate = folder(remote_id) / name
    return candidate if (candidate / MANIFEST).is_file() else None


def seed_examples() -> list[str]:
    """Copy each themed remote's scaffold in as its `Example`, where it is missing."""
    from .build_service import find_scaffold

    notes = []
    for profile in themed_remotes():
        scaffold = find_scaffold(profile.id)
        target = folder(profile.id) / EXAMPLE
        if scaffold is None or (target / MANIFEST).is_file():
            continue
        try:
            shutil.copytree(scaffold, target, dirs_exist_ok=True)
        except OSError as exc:
            notes.append(f"could not copy the example theme to {target}: {exc}")
            continue
        notes.append(f"copied an example theme to {target}")
    return notes
