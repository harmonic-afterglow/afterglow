"""Project persistence and protocol-catalog concerns, independent of Qt widgets."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_PROJECT: dict[str, Any] = {
    "devices": [],
    "activities": [],
    # A new project deliberately carries no output name and no user name: those are
    # answers only the user has, and a plausible-looking default is worse than an empty
    # box (it gets shipped unnoticed). rf="front" means every device emits from the
    # remote's own front IR LED; importing a config picks up any RF blaster base.
    "settings": {"rf": "front", "remote": "harmony-900"},
}

NEW_DEVICE_PROPERTY = "IsNewDevice"


def mark_device_new(device: dict) -> None:
    """Flag a device added in Afterglow for the remote's one-time walkthrough."""
    properties = dict(device.get("properties") or {})
    properties[NEW_DEVICE_PROPERTY] = "true"
    device["properties"] = properties


def new_device_ids(project: dict) -> tuple[str, ...]:
    """The devices the next built configuration will present as newly added."""
    return tuple(
        str(device.get("id"))
        for device in project.get("devices") or []
        if device.get("id") is not None
        and str((device.get("properties") or {}).get(NEW_DEVICE_PROPERTY, "")).lower()
        == "true"
    )


def retire_new_devices(project: dict, device_ids=None) -> int:
    """Remove the one-time flag after those devices were successfully flashed.

    Real configurations represent an old device by omitting ``IsNewDevice``. Writing
    ``false`` would invent a third state that none of the available configurations use.
    ``device_ids`` is the snapshot included in the flashed build, so a device added
    while an older build awaits flashing cannot be retired accidentally.
    """
    wanted = None if device_ids is None else {str(device_id) for device_id in device_ids}
    retired = 0
    for device in project.get("devices") or []:
        if wanted is not None and str(device.get("id")) not in wanted:
            continue
        properties = device.get("properties") or {}
        if str(properties.get(NEW_DEVICE_PROPERTY, "")).lower() != "true":
            continue
        properties = dict(properties)
        properties.pop(NEW_DEVICE_PROPERTY, None)
        if properties:
            device["properties"] = properties
        else:
            device.pop("properties", None)
        retired += 1
    return retired


# Fields Afterglow used to write into a project and no longer honours. They are dropped
# on load rather than ignored in place, so a project saved by this version does not keep
# carrying a setting nothing reads - a reader would reasonably assume it still did
# something.
#
# `manual_startup` was this project's, not Logitech's: no donor activity has any property like it,
# the builder only ever used it to suppress output, and the importer never read it back.
# So it never survived a flash-and-reread, while the config it produced - an activity
# with no input switch and no power list - was permanent. Nothing in the format is lost
# by removing it: an activity that should not switch inputs simply has no input step.
RETIRED_ACTIVITY_FIELDS = ("manual_startup",)


def drop_retired_fields(project: dict) -> dict:
    """Quietly clean a project written by an older version."""
    for activity in project.get("activities") or []:
        for field in RETIRED_ACTIVITY_FIELDS:
            activity.pop(field, None)
    return project


class TemplateRepository:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(exist_ok=True)

    def load(self) -> list[dict[str, Any]]:
        templates = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                data["_source_file"] = str(path)
                templates.append(data)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[warn] could not load {path.name}: {exc}")
        return templates

    @staticmethod
    def by_manufacturer(templates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for template in templates:
            result.setdefault(template.get("mfr", "Unknown").strip(), []).append(template)
        return result


def new_project() -> dict[str, Any]:
    return deepcopy(DEFAULT_PROJECT)
