"""A device's own page of buttons on the remote's screen.

Logitech's configurations put a chosen few of a device's commands on its page - 131 of
the 144 devices in the donors - in an order of their own (134 of 144 differ from the
command list), under names of their own, with gaps (9) and now and then one command
twice (3). The page used to be rebuilt from the command list, so an imported Harmony 900
came back with every command on it: a reporter's 16 hand-picked Spanish buttons became 44
raw command names in alphabetical order.
"""
from __future__ import annotations

import contextlib
import copy
import io
import xml.etree.ElementTree as ET

import pytest

from afterglow import project_devices

from conftest import entries_of


def _device(rows, **extra):
    return {"commands": [[name, label, "", "", None] for name, label in rows], **extra}


# the page a device has
def test_without_a_page_of_its_own_a_device_shows_its_labelled_commands_in_order():
    device = _device([("PowerOn", "On"), ("Guide", ""), ("Menu", "Menu")],
                     icons={"Menu": "Settings"})
    assert project_devices.screen_buttons(device) == [
        ["PowerOn", "On"], ["Menu", "Menu", "Settings"]]


def test_a_page_of_its_own_is_kept_as_it_is_less_what_the_device_lost():
    device = _device([("PowerOn", "On"), ("Guide", "Guide")], screen_buttons=[
        None, ["Guide", "TV guide"], ["Gone", "Gone"], ["Guide", "Again"], None, None])
    # a gap before the first button is Logitech's; gaps after the last are nothing
    assert project_devices.screen_buttons(device) == [
        None, ["Guide", "TV guide"], ["Guide", "Again"]]


def test_an_empty_page_of_its_own_stays_empty():
    device = _device([("PowerOn", "On")], screen_buttons=[])
    assert project_devices.screen_buttons(device) == []


def test_a_renamed_or_removed_command_is_followed_on_the_page():
    device = _device([("A", "A"), ("B", "B")],
                     screen_buttons=[["A", "Ay"], None, ["B", "Bee"], ["A", "Again"]])
    project_devices.rename_screen_command(device, "A", "Alpha")
    assert device["screen_buttons"] == [["Alpha", "Ay"], None, ["B", "Bee"],
                                        ["Alpha", "Again"]]
    project_devices.rename_screen_command(device, "B", None)
    assert device["screen_buttons"] == [["Alpha", "Ay"], None, ["Alpha", "Again"]]


@pytest.mark.parametrize("page", ["Guide", [["Guide"]], [["Guide", 3]], [[1, "x"]],
                                  [["a", "b", "c", "d"]]])
def test_a_malformed_page_is_refused(page):
    device = {"schema": project_devices.SCHEMA, "commands": [], "signals": {},
              "screen_buttons": page}
    with pytest.raises(ValueError):
        project_devices.validate(device)


# Harmony 900 and 1100
def _pages(path) -> dict:
    zip_file = entries_of(path)
    name = next(n for n in zip_file.namelist() if n.endswith("UserConfiguration.xml"))
    root = ET.fromstring(zip_file.read(name))
    out = {}
    for device in root.findall("Device"):
        misc = [group for group in device.findall("Presentation/ControlGroup")
                if group.get("name") == "Misc"]
        out[device.findtext("Id")] = [
            (button.findtext("Position"), button.findtext("Label") or "",
             button.findtext("ActionId"), button.findtext("Icon"))
            for button in (misc[0].findall("Button") if misc else [])]
    return out


def _imported(config, unpacked):
    from afterglow import importer
    with contextlib.redirect_stdout(io.StringIO()):
        return importer.build_project(str(unpacked(config)))


def test_every_real_device_page_comes_back_as_logitech_laid_it_out(
        configs, unpacked, build):
    for index, config in enumerate(configs):
        project = _imported(config, unpacked)
        project["settings"].pop("remote", None)
        rebuilt = build(project, name=f"page-{index}.ezhex")
        assert _pages(rebuilt) == _pages(config), config.name


def test_every_real_1100_device_page_comes_back_too(configs_1100, unpacked, tmp_path):
    from afterglow.build_service import ConfigBuildService
    for index, config in enumerate(configs_1100):
        project = _imported(config, unpacked)
        out = tmp_path / f"1100-{index}.ezhex"
        project["settings"].update(out_file=str(out), first_name="T", last_name="U")
        with contextlib.redirect_stdout(io.StringIO()):
            ConfigBuildService(tmp_path, lambda _m: None).build(project)
        assert _pages(out) == _pages(config), config.name


def test_a_page_arranged_in_the_project_is_what_the_remote_is_given(
        a_config, unpacked, build):
    project = _imported(a_config, unpacked)
    project["settings"].pop("remote", None)
    device = project["devices"][0]
    first, second = (row[0] for row in device["commands"][:2])
    device["screen_buttons"] = [[second, "Second"], None, [first, "First", "Settings"],
                                [second, "Twice"]]
    page = _pages(build(project))[device["id"]]
    assert page == [
        ("0", "Second", f"{device['id']}_{second}_Hold", None),
        ("2", "First", f"{device['id']}_{first}_Hold", "Settings"),
        ("3", "Twice", f"{device['id']}_{second}_Hold", None)]


# Harmony One
@pytest.fixture(scope="module")
def one_project():
    from test_harmony_one_activities import PROJECT
    project = copy.deepcopy(PROJECT)
    project["devices"][0]["screen_buttons"] = [
        ["Menu", "Menu"], None, ["PowerOn", "PowerOn"], ["Guide", "Guide"]]
    return project


def test_the_one_draws_a_device_s_page_in_its_order_under_its_labels(one_project):
    from afterglow.backends.harmony_one import devices, hub
    project = copy.deepcopy(one_project)
    project["devices"][0]["screen_buttons"] = [
        ["Menu", "Set up"], None, ["PowerOn", "On"], ["Menu", "Again"]]
    lowered = devices.lowered_devices(project)
    frames = type("Frames", (), {"buttons": ["button"]})()
    pages = hub.device_pages(lowered, frames, {"button"}, font={})
    [page] = pages[0]
    # a gap is a place left empty, as on the 900 and 1100
    assert [button and (button["name"], button["label"]) for button in page] == [
        ("Menu", "Set up"), None, ("PowerOn", "On"), ("Menu", "Again")]
    # a device with no page of its own is drawn as before
    assert [button["name"] for page in pages[1] for button in page if button] == [
        command["name"] for command in lowered[1]["commands"] if not command.get("hidden")]


def test_a_one_device_s_page_reads_back_in_its_order(one_project, tmp_path):
    from afterglow.backends.harmony_one import generate
    from test_harmony_one_import import _imported as imported
    project = imported(generate.build(one_project)["image"], tmp_path)
    # the gap included: nothing is drawn or bound there, and so nothing reads back
    assert project["devices"][0]["screen_buttons"] == [
        ["Menu", "Menu"], None, ["PowerOn", "PowerOn"], ["Guide", "Guide"]]


# the editor
def test_the_screen_page_arranges_a_device_s_buttons(qapp_or_skip):
    from afterglow.gui.device_screen import DeviceScreenPage
    rows = [["PowerOn", "On", "", "", None], ["Guide", "", "", "", None],
            ["Menu", "Menu", "", "", None]]
    page = DeviceScreenPage({}, lambda: rows)
    # nothing arranged yet: the page the labels make, and nothing written for it
    assert page.entries() == [["PowerOn", "On"], ["Menu", "Menu"]]
    spec = {"screen_buttons": "stale"}
    page.apply(spec)
    assert "screen_buttons" not in spec

    page.table.selectRow(0)
    page.commands.setCurrentRow(1)          # Guide, which has no label of its own
    page._add()
    page._add_gap()
    page._moved(3, 0)                       # Menu to the front
    page.table.item(1, 0).setText("Power")
    page.apply(spec)
    assert spec["screen_buttons"] == [["Menu", "Menu"], ["PowerOn", "Power"],
                                      ["Guide", "Guide"], None]

    # a command the Commands page no longer has leaves the page when it is next shown
    rows.pop(1)
    page.refresh()
    assert page.entries() == [["Menu", "Menu"], ["PowerOn", "Power"]]
    page._clear()
    page.apply(spec)
    assert spec["screen_buttons"] == []


def test_the_screen_page_keeps_an_imported_page_and_its_icons(qapp_or_skip):
    from afterglow.gui.device_screen import DeviceScreenPage
    rows = [["PowerOn", "PowerOn", "", "", None], ["Menu", "Menu", "", "", None]]
    existing = {"screen_buttons": [None, ["Menu", "Setup", "Settings"]]}
    page = DeviceScreenPage(existing, lambda: rows)
    spec = {}
    page.apply(spec)
    assert spec["screen_buttons"] == [None, ["Menu", "Setup", "Settings"]]


# an activity's page
def _activity_pages(path) -> dict:
    zip_file = entries_of(path)
    name = next(n for n in zip_file.namelist() if n.endswith("UserConfiguration.xml"))
    root = ET.fromstring(zip_file.read(name))
    out = {}
    for activity in root.findall("Activity"):
        misc = [group for group in activity.findall("Presentation/ControlGroup")
                if group.get("name") == "Misc"]
        # a macro button's ActionList is named afresh by a build; what it runs is not
        out[activity.findtext("Id")] = sorted(
            (int(button.findtext("Position") or -1), button.findtext("Label") or "",
             button.findtext("Icon"),
             button.findtext("ActionId") if button.findtext("ActionId", "").endswith("_Hold")
             else "macro")
            for button in (misc[0].findall("Button") if misc else []))
    return out


def test_every_real_activity_page_keeps_its_places_and_gaps(configs, unpacked, build):
    """48 of the 104 pages in the 900 donors leave places empty, and 60 list their
    buttons out of position order; the remote lays a page out by position."""
    for index, config in enumerate(configs):
        project = _imported(config, unpacked)
        project["settings"].pop("remote", None)
        rebuilt = build(project, name=f"activity-{index}.ezhex")
        assert _activity_pages(rebuilt) == _activity_pages(config), config.name


def test_an_imported_activity_page_reads_in_position_order_with_its_gaps(
        configs, unpacked):
    gaps = 0
    for config in configs:
        for activity in _imported(config, unpacked)["activities"]:
            buttons = activity.get("soft_buttons") or []
            gaps += buttons.count(None)
            assert not buttons or buttons[-1] is not None
    assert gaps, "the donors leave places empty on some activity pages"


def test_an_activity_page_arranged_with_a_gap_is_built_with_it(configs, unpacked, build):
    project = next(project for project in (_imported(config, unpacked) for config in configs)
                   if project["activities"])
    project["settings"].pop("remote", None)
    device = project["devices"][0]
    command = device["commands"][0][0]
    activity = project["activities"][0]
    activity.pop("screen_groups", None)
    activity["soft_buttons"] = [None, ["Go", device["id"], command], None, None]
    page = _activity_pages(build(project))[activity["id"]]
    assert page == [(1, "Go", None, f"{device['id']}_{command}_Hold")]


def test_the_one_keeps_an_activity_s_gaps():
    from afterglow.backends.harmony_one import activities
    activity = {"soft_buttons": [None, ["A", "tv", "Menu"], None, ["B", "tv", "Guide"],
                                 None]}
    # a place left empty stays empty; there is nothing after the last button
    assert [button and button[0] for button in activities._buttons(activity)] == [
        None, "A", None, "B"]


# not digits: a button that dials a number reads back as a favourite
FILLERS = ("ChannelUp", "Select", "InputHdmi1", "PowerOn")


def test_a_one_activity_s_gaps_read_back(tmp_path):
    from afterglow.backends.harmony_one import generate
    from test_harmony_one_activities import PROJECT
    from test_harmony_one_import import _imported as imported
    project = copy.deepcopy(PROJECT)
    project["activities"][0]["soft_buttons"] = [
        ["Guide", "tv", "Guide"], None, ["Menu", "tv", "Menu"]] + [
        [name, "tv", name] for name in FILLERS] + [None, ["Last", "tv", "InputHdmi2"]]
    back = imported(generate.build(project)["image"], tmp_path)["activities"][0]
    tv = back["soft_buttons"][0][1]
    # a gap on the first page, and one on the second
    assert back["soft_buttons"] == [["Guide", tv, "Guide"], None, ["Menu", tv, "Menu"]] + [
        [name, tv, name] for name in FILLERS] + [None, ["Last", tv, "InputHdmi2"]]


# the remote's grid
@pytest.mark.parametrize("remote, device, activity, gaps", [
    ("harmony-900", (2, 3), (2, 3), True),       # ButtonImporter.as, LayoutManager.as
    ("harmony-1100", (3, 3), (3, 2), True),      # devices-group / pushlist-group swf
    ("harmony-one", (2, 3), (2, 3), True),       # pages.BUTTON_POSITIONS
])
def test_each_remote_says_how_its_pages_are_laid_out(remote, device, activity, gaps):
    from afterglow import backends, remotes
    profile = remotes.get(remote)
    assert profile.screen_grid("device") == device
    assert profile.screen_grid("activity") == activity
    assert backends.screen_gaps(profile) is gaps


def test_the_preview_turns_to_a_picked_button_s_page(qapp_or_skip):
    from afterglow.gui.screen_preview import ScreenPreview
    preview = ScreenPreview(2, 3, "TV")
    preview.set_buttons([("A", None), None] + [(str(n), None) for n in range(9)])
    assert preview.pages() == 2
    preview.select(7)
    assert preview.page == 1
    preview.set_buttons([("A", None)])
    assert (preview.pages(), preview.page) == (1, 0)


def test_the_activity_screen_buttons_page_keeps_gaps(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.activity_buttons import ScreenButtonsPage
    devices = [{"id": "tv", "label": "TV"}]
    existing = {"soft_buttons": [None, ["Menu", "tv", "Menu"]]}
    page = ScreenButtonsPage(devices, existing, remote=remotes.get("harmony-900"))
    assert page.get_buttons() == [None, {"label": "Menu", "device": "tv",
                                         "command": "Menu"}]
    page.table.selectRow(1)
    page._add_gap()
    page._add_gap()
    assert page.get_buttons()[:2] == [None, {"label": "Menu", "device": "tv",
                                             "command": "Menu"}]
    assert len(page._entries()) == 4 and page.preview.buttons[2:] == [None, None]
