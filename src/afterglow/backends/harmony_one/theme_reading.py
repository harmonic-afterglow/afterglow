"""A configuration's own look read back as a theme: the pictures it draws for the roles a
scaffold names.

A theme only changes pictures: the same project in another theme draws the same pictures
in the same places, each one the theme's for its role. So the project an import reads is
built again in the default look and the two images' drawings laid side by side - screen
by screen, slot by slot, call by call - and wherever the default draws a scaffold role's
picture, the configuration draws its theme's. A role the configuration never draws (a
button frame for a position no page uses) keeps the default's.

Format reference: docs/harmony_one/reading.md, "A theme is read by the default it replaces"
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import bitmap, ui_index

DEPTH = 6


def _draws(payload: bytes) -> list[tuple[tuple, int]]:
    """Every picture the image's screens draw: ``(where, picture)``, where being the
    screen, slot and the path of calls to the instruction and its place."""
    out = []

    def walk(offset, path, depth):
        if depth > DEPTH:
            return
        try:
            program = ui_index.drawing_program(payload, offset)["instructions"]
        except ValueError:
            return
        for index, item in enumerate(program):
            if item["opcode"] == "bitmap":
                out.append((path + (index, item["x"], item["y"]), item["target"]))
            elif item["opcode"] in ("call", "jump"):
                walk(item["target"], path + (index,), depth + 1)
    for number, screen in enumerate(ui_index.screen_slots(payload)):
        for place, slot in enumerate(screen["slots"]):
            walk(slot["program_offset"], (number, place), 0)
    return out


def _rows(payload: bytes, target: int):
    from .importing import _rgba
    return _rgba(bitmap.decode(payload, target))


def _key(rows) -> str:
    return json.dumps([[list(pixel) for pixel in row] for row in rows])


def theme_pictures(payload: bytes, project: dict, directory: Path | None = None) -> dict:
    """``{role: rows}`` of each scaffold role the image draws in a look of its own; empty
    when its layout is not the default build's of ``project``."""
    from ... import imaging, paths
    from . import assets, generate

    directory = Path(paths.scaffolds("harmony-one") if directory is None else directory)
    manifest = assets.read_manifest(directory)
    roles: dict[str, list[str]] = {}
    for role, item in manifest["pictures"].items():
        rows = imaging.decode((directory / item["file"]).read_bytes())["rows"]
        roles.setdefault(_key(rows), []).append(role)
    plain = {**project, "settings": {key: value for key, value in
                                     (project.get("settings") or {}).items() if key != "theme"}}
    try:
        default = bytes(generate.build(plain, directory=directory)["image"])
    except (KeyError, LookupError, ValueError):
        return {}
    ours, theirs = _draws(default), _draws(payload)
    if [where for where, _target in ours] != [where for where, _target in theirs]:
        return {}
    out: dict[str, list] = {}
    for (_where, mine), (_same, drawn) in zip(ours, theirs):
        named = roles.get(_key(_rows(default, mine)))
        if not named:
            continue
        rows = _rows(payload, drawn)
        if _key(rows) == _key(_rows(default, mine)):
            continue
        for role in named:
            out.setdefault(role, rows)
    return out


def write_theme(name: str, pictures: dict, directory: Path | None = None) -> str:
    """A theme folder for the One - the scaffold, with ``pictures`` put in for their roles
    - under the name, or the name and a number when one is taken. Its name."""
    from ... import imaging, paths, themes
    from . import assets

    source = Path(paths.scaffolds("harmony-one") if directory is None else directory)
    root = themes.folder("harmony-one")
    chosen, number = name, 2
    while (root / chosen).exists():
        chosen, number = f"{name} {number}", number + 1
    target = root / chosen
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(themes.STAMP))
    files = assets.read_manifest(target)["pictures"]
    for role, rows in pictures.items():
        (target / files[role]["file"]).write_bytes(imaging.encode(rows))
    return chosen
