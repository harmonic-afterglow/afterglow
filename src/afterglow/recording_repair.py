"""Recordings an older Afterglow made, made again from the protocols they came from.

A remote that stores no protocol programs hands its commands back as recordings, and a
project imported from it keeps them as recordings - replayed exactly, so a command that
an older release rendered wrongly stays wrong through every later fix. Each backend that
renders this way knows what its earlier releases sent (`repair_recorded_signals`,
optional): given the same device as it is saved elsewhere with its protocols - the
user's library, their other projects - it turns a recording back into its protocol when,
and only when, the recording is exactly what one of those releases rendered from it.

A project records what was repaired and by which version (`repairs`), and every save
records the version that wrote it (`saved_by`), so a fix that changes a rendering again
knows which projects can hold the older one.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__


def sources(library: Path | None = None, projects: Path | None = None) -> list[dict]:
    """The devices saved on this computer that hold protocols: the library's and every
    project's. What cannot be read is skipped - a repair never stops anything opening."""
    from . import device_json, paths
    library = paths.user_library() if library is None else Path(library)
    projects = paths.user_folder("projects") if projects is None else Path(projects)
    found: list[dict] = []
    for path in sorted((library / "devices").glob("*.json")):
        try:
            found.append(device_json.to_project_device(device_json.load(path),
                                                       library=library))
        except Exception:                          # noqa: BLE001 - see above
            continue
    for path in sorted(projects.rglob("*.json")):
        try:
            project = json.loads(path.read_text(encoding="utf-8"))
            devices = project.get("devices") or [] if isinstance(project, dict) else []
        except (OSError, ValueError, AttributeError):
            continue
        found.extend(device for device in devices if isinstance(device, dict)
                     and any(isinstance(signal, dict) and signal.get("kind") == "protocol"
                             for signal in (device.get("signals") or {}).values()))
    return found


def repair(project: dict, saved: list[dict] | None = None) -> int:
    """Turn the project's recordings an older Afterglow rendered back into protocols,
    from `saved` (by default everything on this computer, `sources`) and the project's
    own devices. Records what it did; returns how many."""
    from . import backends
    devices = [device for device in project.get("devices") or []
               if isinstance(device, dict)]
    if not any(isinstance(signal, dict) and signal.get("kind") == "waveform"
               for device in devices for signal in (device.get("signals") or {}).values()):
        return 0
    candidates = devices + list(sources() if saved is None else saved)
    done: dict[str, int] = {}
    for name in backends.installed():
        try:
            hook = getattr(backends.get(name), "repair_recorded_signals", None)
        except (LookupError, TypeError):
            continue
        if hook is None:
            continue
        for device in devices:
            for generation, count in hook(device, candidates).items():
                done[generation] = done.get(generation, 0) + count
    if done:
        project.setdefault("repairs", []).extend(
            {"by": __version__, "rendering": generation, "commands": count}
            for generation, count in sorted(done.items()))
    return sum(done.values())


def stamp(project: dict) -> dict:
    """Mark `project` as written by this version."""
    project["saved_by"] = __version__
    return project
