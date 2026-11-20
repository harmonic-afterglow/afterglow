"""Themes: a remote's look, kept in `Documents/Afterglow/Themes/<remote>/<name>/`.

A theme is a folder laid out like the remote's scaffold - its pictures, fonts and colours
- so making one is copying a folder and changing files. Which remotes take themes is the
remote's profile's to say (`interface.settings` lists "theme"); nothing here names one.

Each such remote's folder is given an `Example`: the shipped scaffold, copied in so there
is something to copy and change. It is a starting point, not a choice: it draws exactly
what the default does, so it is never offered, and it is put back if it goes missing - or
replaced when the scaffold has changed since, so a copy made from it has every picture the
default draws. Changes made to `Example` itself are therefore not kept. A
project names its theme by folder name, so a project moved to another computer finds the
theme of that name there.

A scaffold's manifest may narrow the example to the files a theme can change
(`theme_files`, paths in the scaffold), where the rest of the scaffold is the platform a
build takes from the scaffold whatever the theme; and a scaffold derived from another
names the one its example comes from (`theme_from`, a scaffold beside it).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import paths

EXAMPLE = "Example"
# A folder is a theme when it has the scaffold's asset manifest.
MANIFEST = "assets.json"
# In an example: which scaffold it was copied from, as its fingerprint.
STAMP = ".afterglow-example"


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


def fingerprint(scaffold: Path, files=None) -> str:
    """Every file of a scaffold - or those of `files` it has - by path and contents."""
    digest = hashlib.sha256()
    items = (sorted(scaffold.rglob("*")) if files is None
             else [scaffold / name for name in sorted(files)])
    for item in items:
        if item.is_file() and "__pycache__" not in item.parts and item.name != STAMP:
            digest.update(item.relative_to(scaffold).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def example_source(scaffold: Path) -> tuple[Path, list | None]:
    """The folder a remote's example is copied from and the files copied (None: all of
    it), as the scaffold's manifest says (`theme_from`, `theme_files`)."""
    for _ in range(4):                       # a chain of derivations, never a loop
        try:
            manifest = json.loads((scaffold / MANIFEST).read_text("utf-8"))
        except (OSError, ValueError):
            return scaffold, None
        source = manifest.get("theme_from")
        if not source:
            files = manifest.get("theme_files")
            return scaffold, (None if files is None else sorted({MANIFEST, *files}))
        scaffold = scaffold.parent / Path(source).name
    return scaffold, None


def seed_examples() -> list[str]:
    """Copy each themed remote's scaffold in as its `Example` where it is missing, and
    again where the scaffold has changed since it was copied. An Example its owner has
    edited is kept, renamed `Example (yours, <date>)`, never deleted: people start from
    it, and editing it in place used to lose the work at the next update."""
    import datetime
    from .build_service import find_scaffold

    notes = []
    for profile in themed_remotes():
        scaffold = find_scaffold(profile.id)
        if scaffold is None:
            continue
        target = folder(profile.id) / EXAMPLE
        source, files = example_source(Path(scaffold))
        wanted = fingerprint(source, files)
        stamp = target / STAMP
        present = (target / MANIFEST).is_file()
        try:
            if present and stamp.is_file() and stamp.read_text("utf-8").strip() == wanted:
                continue
            kept = None
            if target.exists():
                edited = not stamp.is_file() or \
                    fingerprint(target, files) != stamp.read_text("utf-8").strip()
                if edited:
                    day = datetime.date.today().isoformat()
                    kept = target.with_name(f"{EXAMPLE} (yours, {day})")
                    n = 2
                    while kept.exists():
                        kept, n = target.with_name(f"{EXAMPLE} (yours, {day}) {n}"), n + 1
                    target.rename(kept)
                else:
                    shutil.rmtree(target)
            if files is None:
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                for name in files:
                    (target / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / name, target / name)
            stamp.write_text(wanted + "\n", "utf-8")
        except OSError as exc:
            notes.append(f"could not copy the example theme to {target}: {exc}")
            continue
        notes.append(f"{'updated' if present else 'copied'} the example theme in {target}"
                     + (f"; your changes to it are kept in {kept}" if kept else ""))
    return notes


def build_folder(settings: dict, remote_id: str, context) -> Path | None:
    """The theme a project's settings name (`theme_folder`) for a build: a theme's name in
    the owner's Themes folder, or a folder of its own, taken from the project's folder
    when relative; None when the project names none, and the build draws the scaffold.
    Not `theme`, which the Harmony 900 already uses for a preference of its own."""
    theme = settings.get("theme_folder")
    if not theme:
        return None
    directory = context.find_theme(remote_id, theme) or Path(theme)
    if not directory.is_absolute():
        directory = Path(context.root) / directory
    if not (directory / MANIFEST).is_file():
        raise ValueError(f"there is no theme {theme!r}: no such theme in the Themes "
                         "folder, and no scaffold folder of that name")
    return directory
