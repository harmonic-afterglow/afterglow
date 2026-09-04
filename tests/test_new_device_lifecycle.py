"""A newly added device should be tested once, not after every future flash.

The remote uses two coupled markers: ``IsNewDevice=true`` on each device and
``NewDeviceFound=true`` on the user. The builder already derives the latter from the
former. This file guards the project lifecycle around that format: Add Device creates
the per-device marker, and only a successful write retires the exact devices included
in that build.
"""
from types import SimpleNamespace

import pytest

# `gui.project` needs no Qt of its own, but importing any `afterglow.gui` submodule runs
# the package `__init__`, which imports `app` and therefore PyQt6. This import happens at
# collection, so a fixture cannot skip in time and the module errors instead.
pytest.importorskip("PyQt6.QtWidgets")

from afterglow.gui.project import (mark_device_new, new_device_ids,  # noqa: E402
                                   retire_new_devices)


def device(device_id, *, new=False):
    result = {"id": device_id, "label": device_id, "commands": []}
    if new:
        result["properties"] = {"IsNewDevice": "true", "Keep": "value"}
    return result


def test_new_and_old_are_true_and_absent_not_true_and_false():
    added = device("40009001")
    mark_device_new(added)
    assert added["properties"]["IsNewDevice"] == "true"

    project = {"devices": [added]}
    assert retire_new_devices(project) == 1
    assert "IsNewDevice" not in added.get("properties", {})


def test_retiring_a_build_does_not_retire_a_device_added_after_it():
    included = device("40009001", new=True)
    added_later = device("40009002", new=True)
    project = {"devices": [included, added_later]}

    assert retire_new_devices(project, (included["id"],)) == 1
    assert new_device_ids(project) == (added_later["id"],)


def test_add_device_marks_the_wizard_result_new(qapp_or_skip, monkeypatch):
    from afterglow.gui import tabs

    result = device("40009001")

    class Wizard:
        def __init__(self, *_args, **_kwargs):
            self.result_spec = result

        def exec(self):
            return True

        def rf_token(self):
            return "front"

    monkeypatch.setattr(tabs, "DeviceWizard", Wizard)
    project = {"devices": [], "activities": [], "settings": {}}
    tab = tabs.DevicesTab(project, [])
    tab.add_device()

    assert project["devices"][0]["properties"]["IsNewDevice"] == "true"


def test_only_a_successful_write_emits_the_built_new_device_snapshot(qapp_or_skip):
    from afterglow.gui.tabs import UpdateTab

    class Settings:
        def save(self):
            pass

    tab = UpdateTab({"devices": [], "settings": {}}, Settings())
    tab._built_new_device_ids = ("40009001",)
    tab._worker = SimpleNamespace(operation="write")
    emitted = []
    tab.flash_succeeded.connect(emitted.append)

    tab._on_remote_done(False, "failed")
    assert emitted == []
    tab._on_remote_done(True, "written")
    assert emitted == [("40009001",)]
    assert not tab.flash_btn.isEnabled(), "the still-flagged artifact can be reflashed"


def test_flash_retirement_is_saved_when_the_project_has_a_path():
    from afterglow.gui.app import MainWindow

    project = {"devices": [device("40009001", new=True),
                            device("40009002", new=True)]}
    saved = []
    refreshed = []
    window = SimpleNamespace(
        project=project,
        _project_path="project.json",
        devices_tab=SimpleNamespace(refresh=lambda: refreshed.append(True)),
        _write_project=lambda path: saved.append(path),
        _mark_dirty=lambda: None,
    )

    MainWindow._retire_flashed_devices(window, ("40009001",))

    assert new_device_ids(project) == ("40009002",)
    assert refreshed == [True]
    assert saved == ["project.json"]
