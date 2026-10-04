"""A project as one file that builds on anybody's machine.

A saved project is a JSON file that leans on its owner's computer: its pictures are
paths into the owner's files (into a folder an import unpacked, for an imported
configuration), and a device that does not carry its own protocol definition relies on
whatever protocols that machine has installed. Sent to someone else it opens, and then
cannot build.

A bundle is a ZIP holding the project, every picture it uses, and a manifest. Exporting
embeds each protocol a device uses into that device, so building needs nobody's library,
and drops the paths that only meant something on the machine it came from. Opening one
unpacks it into a folder of its own and points the project at the copies there.

Only `manifest.json`, `project.json` and `assets/<name>` are ever read out of a bundle:
it is a file people send each other, and nothing in it may write anywhere else.
"""
from __future__ import annotations

import json
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import ir_protocol, project_devices

SUFFIX = ".afterglow"
SCHEMA = "afterglow-project-bundle/1"
# Settings that name a place on the machine a project was saved on.
MACHINE_SETTINGS = ("template", "base_dir", "work_dir")


class BundleError(ValueError):
    """A bundle that cannot be opened, or a project that cannot be bundled."""


def _protocols_used(device: dict) -> set[str]:
    return {signal["protocol"] for signal in (device.get("signals") or {}).values()
            if isinstance(signal, dict) and signal.get("kind") == "protocol"
            and signal.get("protocol")}


def export(project: dict, target, *, base_dir=None) -> list[str]:
    """Write `project` as a bundle to `target`. Returns what was done to make it whole.

    `base_dir` is where relative picture paths are resolved from - the folder the
    project was saved in.
    """
    target = Path(target)
    base = Path(base_dir) if base_dir else Path.cwd()
    out = deepcopy(project)
    notes: list[str] = []
    settings = out.setdefault("settings", {})
    for key in MACHINE_SETTINGS:
        if settings.pop(key, None) is not None:
            notes.append(f"left out the {key} path, which only exists on this computer")
    if settings.get("out_file"):
        settings["out_file"] = PurePosixPath(Path(settings["out_file"]).name).as_posix()

    installed = ir_protocol.catalog()
    missing = []
    for device in out.get("devices") or []:
        carried = device.setdefault("portable_protocol_definitions", {})
        for protocol_id in sorted(_protocols_used(device) - set(carried)):
            if protocol_id in installed:
                carried[protocol_id] = installed[protocol_id]
                notes.append(f"included protocol {protocol_id} for {device.get('label')}")
            else:
                missing.append(f"{device.get('label')}: {protocol_id}")
        if not carried:
            device.pop("portable_protocol_definitions")
    if missing:
        raise BundleError("these devices use protocols this computer does not have, so "
                          "the project could not be built anywhere else: "
                          + "; ".join(missing))

    pictures = {}
    for asset in out.get("assets") or []:
        name = PurePosixPath(asset.get("name") or "").name
        source = Path(asset.get("source") or "")
        source = source if source.is_absolute() else base / source
        if not name or not source.is_file():
            raise BundleError(f"the picture {asset.get('name')!r} is missing: {source}")
        pictures[name] = source.read_bytes()
        asset["name"], asset["source"] = name, f"assets/{name}"

    manifest = {"schema": SCHEMA, "remote": settings.get("remote"),
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("project.json", json.dumps(out, indent=2, ensure_ascii=False))
        for name, data in sorted(pictures.items()):
            archive.writestr(f"assets/{name}", data)
    return notes


def open_bundle(source, folder) -> dict:
    """Unpack a bundle into `folder` and return its project, ready to edit and build."""
    folder = Path(folder)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BundleError(f"{Path(source).name} is not a shareable project: {exc}") from exc
    with archive:
        names = set(archive.namelist())
        if "manifest.json" not in names or "project.json" not in names:
            raise BundleError(f"{Path(source).name} is not a shareable project")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") != SCHEMA:
            raise BundleError(
                f"{Path(source).name} is a {manifest.get('schema')!r} bundle; this version "
                f"of Afterglow reads {SCHEMA!r}")
        project = json.loads(archive.read("project.json"))
        folder.mkdir(parents=True, exist_ok=True)
        for asset in project.get("assets") or []:
            name = PurePosixPath(asset.get("name") or "").name
            entry = f"assets/{name}"
            if not name or entry not in names:
                raise BundleError(f"the bundle lacks the picture {asset.get('name')!r}")
            (folder / "assets").mkdir(exist_ok=True)
            (folder / "assets" / name).write_bytes(archive.read(entry))
            asset["name"], asset["source"] = name, str(folder / "assets" / name)
    return project_devices.normalise_project(project)
