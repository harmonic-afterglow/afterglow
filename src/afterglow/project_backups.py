"""Earlier versions of a project, kept on every save.

Most people keep one project and save over it, so a deleted activity or a bad edit
saved once was gone for good. Before a save overwrites the file, the version on disk
is copied to `Documents/Afterglow/Backups/<project>/`, newest last; the last KEEP are
kept. A backup that cannot be made never stops the save it protects.
"""
from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import shutil

from . import paths

KEEP = 20
LOG = logging.getLogger("afterglow")


def name_of(project_path) -> str:
    """A project saved as `<folder>/project.json` (an opened shareable project) is
    named by its folder, as the window title names it."""
    path = Path(project_path)
    return path.parent.name if path.name == "project.json" else path.stem


def folder_for(project_path) -> Path:
    return paths.user_folder("backups") / name_of(project_path)


def history(project_path) -> list[Path]:
    """This project's backups, oldest first."""
    folder = folder_for(project_path)
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def back_up(project_path) -> Path | None:
    """Copy the project file as it is now, before it is overwritten. None when there is
    nothing to keep: no file yet, or the same as the newest backup."""
    source = Path(project_path)
    try:
        if not source.is_file() or not source.stat().st_size:
            return None
        current = source.read_bytes()
        earlier = history(source)
        if earlier and earlier[-1].read_bytes() == current:
            return None
        folder = folder_for(source)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = folder / f"{name_of(source)}-{stamp}.json"
        shutil.copyfile(source, target)
        for old in history(source)[:-KEEP]:
            old.unlink(missing_ok=True)
        return target
    except OSError as exc:
        LOG.warning("could not back up %s before saving: %s", source, exc)
        return None
