"""One command may sit on more than one physical key.

A set-top box that puts Menu on both the Menu and Exit keys, or Play/Pause on both
Play and Pause, is ordinary - donor-1 and donor-4 each carry three such commands, and
the format has always allowed it (`_slot_map` in builder/activities.py walks a list of
slots).

The importer assigned rather than collected, so whichever button came last in the file
won and the other key was left dead on the device page. Found on real hardware: after a
read-modify-write cycle the set-top box's Menu and Play keys stopped working, while Exit
and Pause - the very same two commands - still did.
"""
import contextlib
import glob
import io
import tempfile
import xml.etree.ElementTree as ET

import pytest

from afterglow import ezhex
from afterglow.importer import build_project
from conftest import ROOT


def projects():
    """Every donor configuration available, imported."""
    found = {}
    for path in sorted(glob.glob(str(ROOT / "configs" / "*" / "*.ezhex"))):
        work = tempfile.mkdtemp()
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(path, work)
            found[path] = (build_project(work), work)
    return found


@pytest.fixture(scope="module")
def donors():
    found = projects()
    if not found:
        pytest.skip("no donor configurations available")
    return found


def slots_of(command):
    """The hard keys a command sits on, however the field is spelled."""
    hard = command[4]
    if hard is None:
        return []
    return list(hard) if isinstance(hard, (list, tuple)) else [hard]


def test_a_command_on_two_keys_keeps_both(donors):
    multi = [(path, device["label"], command[0], slots_of(command))
             for path, (project, _work) in donors.items()
             for device in project["devices"]
             for command in device["commands"]
             if len(slots_of(command)) > 1]
    assert multi, "no donor has a command on two keys - this test is not testing anything"
    for _path, _label, _name, slots in multi:
        assert len(slots) == len(set(slots)), "a key was recorded twice"


def test_no_hard_key_is_lost_on_import(donors):
    """Counted against the file itself: every <Button> under a device's HardButtons has
    to survive into the project, or a key that worked before an import stops working
    after it."""
    for path, (project, work) in donors.items():
        root = ET.parse(f"{work}/userconfig/UserConfiguration.xml").getroot()
        in_file = sum(len(group.findall("Button"))
                      for device in root.findall("Device")
                      for group in device.findall('Presentation/ControlGroup')
                      if group.attrib.get("name") == "HardButtons")
        carried = sum(len(slots_of(command))
                      for device in project["devices"]
                      for command in device["commands"])
        assert carried == in_file, (
            f"{path}: {in_file} hard keys in the file, {carried} survived import")


def test_the_ordinary_single_key_command_stays_a_plain_string(donors):
    """The common case must not change shape: everything that reads a device spec
    expects a bare slot name, and turning every one into a list would ripple."""
    singles = [command[4]
               for _path, (project, _work) in donors.items()
               for device in project["devices"]
               for command in device["commands"]
               if command[4] is not None and not isinstance(command[4], list)]
    assert singles, "no single-key commands found at all - something is wrong"
    assert all(isinstance(slot, str) for slot in singles)


# and editing must not undo the import
def test_editing_a_device_keeps_every_key_a_command_sits_on(qapp_or_skip):
    """The importer was fixed to keep both keys; the editor then threw the second away
    on the way back out. The hard-key button can only show one, so it shows the first
    and carries the rest - `slot[0]` discarded them."""
    from afterglow.gui.device_wizard import DeviceEditor
    from afterglow.gui.widgets import load_repo_templates

    device = {"id": "40009001", "label": "Set-top Box", "type": "SetTopBox",
              "commands": [["Menu", "Menu", "00", "00", ["Menu", "Exit"]],
                           ["PlayPause", "Play/Pause", "00", "00", ["Play", "Pause"]],
                           ["Guide", "Guide", "00", "00", "Guide"],
                           ["Blue", "Blue", "00", "00", None]]}
    collected = DeviceEditor(load_repo_templates(), existing=device,
                             project={"devices": [device], "settings": {}})._collect()
    assert [c[4] for c in collected["commands"]] == [c[4] for c in device["commands"]]


def test_a_single_key_does_not_become_a_list(qapp_or_skip):
    """The shape has to stay what every other reader expects."""
    from afterglow.gui.device_wizard import DeviceEditor
    from afterglow.gui.widgets import load_repo_templates
    device = {"id": "40009001", "label": "TV", "type": "Television",
              "commands": [["Guide", "Guide", "00", "00", "Guide"]]}
    out = DeviceEditor(load_repo_templates(), existing=device,
                       project={"devices": [device], "settings": {}})._collect()
    assert out["commands"][0][4] == "Guide"


def test_a_donor_survives_being_opened_and_saved(qapp_or_skip, donors):
    """End to end: import a real configuration, open every device, change nothing, and
    no key may come out bound differently."""
    from afterglow.gui.device_wizard import DeviceEditor
    from afterglow.gui.widgets import load_repo_templates
    templates = load_repo_templates()
    for path, (project, _work) in donors.items():
        for device in project["devices"]:
            out = DeviceEditor(templates, existing=device,
                               project=project)._collect()
            assert [slots_of(c) for c in out["commands"]] == \
                   [slots_of(c) for c in device["commands"]], f"{path}: {device['label']}"
