"""Every activity says what to do with every device.

Checked against the donors rather than assumed: all six donor configurations partition
completely - in each of their thirty activities, every device the configuration knows
appears in either <Power><On> or <Power><Off>, never in neither and never in both. The
sums are exact (donor-2: nine devices, and every activity is 4 on + 5 off).

So an activity that leaves a device unlisted is not a lighter-touch activity, it is a
malformed one. That happens when a device is added to a project after it was imported:
the imported activities carry an off-list from the original config, the new device is in
nobody's list, and nothing ever powers it down.

AlwaysOn devices are the one case the donors cannot settle, because none of them has
one. They are excluded from both lists here, on the reading that "always on" means
activities do not power it - if that is ever shown to be wrong, this is the file that
should say so.
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


def donor_files():
    return sorted(glob.glob(str(ROOT / "configs" / "*" / "*.ezhex")))


def partition_of(xml_root):
    """{activity label: (on, off, every device id)} straight out of a config."""
    devices = {d.findtext("Id") for d in xml_root.findall("Device")}
    out = {}
    for activity in xml_root.findall("Activity"):
        out[activity.find("Presentation/Label").text] = (
            {e.text for e in activity.findall("Power/On")},
            {e.text for e in activity.findall("Power/Off")},
            devices)
    return out


@pytest.mark.parametrize("path", donor_files(), ids=lambda p: "/".join(p.split("/")[-2:]))
def test_the_donors_partition_completely(path, unpacked):
    """The evidence the rule rests on. If a donor ever fails this, the rule is wrong
    and the builder should stop enforcing it."""
    root = ET.parse(f"{unpacked(path)}/userconfig/UserConfiguration.xml").getroot()
    for label, (on, off, devices) in partition_of(root).items():
        assert not (on & off), f"{label}: device both switched on and off"
        assert on | off == devices, f"{label}: {devices - on - off} listed nowhere"


@pytest.mark.parametrize("path", donor_files(), ids=lambda p: "/".join(p.split("/")[-2:]))
def test_a_rebuilt_donor_still_partitions_completely(path, unpacked, build):
    """And the round trip has to keep it that way."""
    project = build_project(str(unpacked(path)))
    if not project.get("activities"):
        pytest.skip("no activities to check")
    project.setdefault("assets", [])
    rebuilt = build(project)
    with contextlib.redirect_stdout(io.StringIO()):
        work = tempfile.mkdtemp()
        ezhex.unpack(str(rebuilt), work)
    root = ET.parse(f"{work}/userconfig/UserConfiguration.xml").getroot()
    for label, (on, off, devices) in partition_of(root).items():
        assert on | off == devices, f"{label}: {devices - on - off} listed nowhere"


def test_a_device_added_after_an_import_is_still_powered_down(unpacked, build):
    """The concrete failure. Import a config, add a device the way the interface does,
    and the imported activities must account for it - otherwise the new device is left
    running by every activity that does not use it."""
    donors = donor_files()
    if not donors:
        pytest.skip("no donor configurations available")
    project = build_project(str(unpacked(donors[0])))
    template = dict(project["devices"][0])
    template["id"] = "49999999"
    template["label"] = "Added Later"
    project["devices"].append(template)
    project.setdefault("assets", [])

    with contextlib.redirect_stdout(io.StringIO()):
        work = tempfile.mkdtemp()
        ezhex.unpack(str(build(project)), work)
    root = ET.parse(f"{work}/userconfig/UserConfiguration.xml").getroot()
    for label, (on, off, _devices) in partition_of(root).items():
        assert "49999999" in (on | off), f"{label}: the added device is in neither list"
