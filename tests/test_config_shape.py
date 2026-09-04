"""The shape of a configuration, as distinct from its contents.

Faults here do not show up when reading a config back: devices, activities, codes and
protocol blocks can all be correct while the document around them is wrong, and the
remote's own interface is what notices. Two invariants, held by all six donor configs:

* `NewDeviceFound` agrees with the devices carrying `IsNewDevice`. The flag runs the
  remote's new-device walkthrough, and claiming a new device while flagging none leaves
  it walking an empty list.
* `<Protocols>` comes last.
"""
import glob
import xml.etree.ElementTree as ET

import pytest

from conftest import ROOT

REAL_ORDER = ["Properties", "User", "Controller", "Device", "Activity", "Protocols"]


def order_of(root):
    seen, out = set(), []
    for child in root:
        if child.tag not in seen:
            seen.add(child.tag)
            out.append(child.tag)
    return out


def flagged_new(root):
    return [d.findtext("Presentation/Label") for d in root.findall("Device")
            if d.find('Properties/Property[@name="IsNewDevice"]') is not None]


def says_new_device_found(root):
    found = root.find('User/Properties/Property[@name="NewDeviceFound"]')
    return found is not None and (found.text or "").lower() == "true"


def one_device():
    from afterglow import ir_signal, project_devices

    return {"schema": project_devices.SCHEMA,
            "id": "40009001", "label": "TV", "type": "Television",
            "commands": [["PowerOn", "On", "07", "01", None],
                         ["PowerOff", "Off", "07", "02", None]],
            "signals": {
                "PowerOn": ir_signal.protocol_signal(
                    "nec1", {"address": "07", "command": "01"}),
                "PowerOff": ir_signal.protocol_signal(
                    "nec1", {"address": "07", "command": "02"}),
            },
            "power_on_cmd": "PowerOn", "power_off_cmd": "PowerOff"}


# what real configurations do
@pytest.mark.parametrize("path", sorted(glob.glob(str(ROOT / "configs" / "*" / "*.ezhex"))),
                         ids=lambda p: "/".join(p.split("/")[-2:]))
def test_a_real_config_never_claims_a_new_device_without_flagging_one(path, unpacked):
    root = ET.parse(f'{unpacked(path)}/userconfig/UserConfiguration.xml').getroot()
    if says_new_device_found(root):
        assert flagged_new(root), "claims a new device but flags none"


@pytest.mark.parametrize("path", sorted(glob.glob(str(ROOT / "configs" / "*" / "*.ezhex"))),
                         ids=lambda p: "/".join(p.split("/")[-2:]))
def test_a_real_config_ends_with_protocols(path, unpacked):
    root = ET.parse(f'{unpacked(path)}/userconfig/UserConfiguration.xml').getroot()
    assert order_of(root) == REAL_ORDER


# what we build
def test_a_build_with_no_new_devices_does_not_claim_one(build, unpacked):
    """The scaffold carries the flag because the dump behind it genuinely had a new
    device. It has to come off unless this configuration also has one."""
    tree = unpacked(build({"devices": [one_device()], "activities": [], "assets": []}),
                    "no-new")
    root = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
    assert not says_new_device_found(root)
    assert not flagged_new(root)


def test_a_build_with_a_new_device_says_so(build, unpacked):
    """And the other direction, so the fix is not simply "always remove it"."""
    device = one_device() | {"properties": {"IsNewDevice": "true"}}
    tree = unpacked(build({"devices": [device], "activities": [], "assets": []}), "new")
    root = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
    assert flagged_new(root) == ["TV"]
    assert says_new_device_found(root), (
        "a device is flagged new but the remote is not told to walk it")


def test_a_built_config_has_the_same_element_order_as_a_real_one(build, unpacked):
    tree = unpacked(build({"devices": [one_device()], "activities": [], "assets": []}),
                    "order")
    root = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
    assert order_of(root) == REAL_ORDER


def test_the_two_new_device_signals_can_never_disagree(build, unpacked):
    """The invariant itself, whichever way round. A remote told to walk devices it
    cannot enumerate shows an empty power-on test and then offers to turn off
    "undefined"."""
    for properties in ({}, {"IsNewDevice": "true"}, {"IsNewDevice": "false"}):
        device = one_device() | ({"properties": properties} if properties else {})
        tree = unpacked(build({"devices": [device], "activities": [], "assets": []}),
                        f"agree-{len(properties)}-{properties.get('IsNewDevice')}")
        root = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
        assert says_new_device_found(root) == bool(flagged_new(root)), properties


def test_the_scaffold_keeps_the_line_endings_the_remote_expects():
    """The remote executes some of these files, and rejects the configuration if it cannot.

    `.preinstall` and `.postinstall` are shell scripts the remote *runs* during install.
    With CRLF the shebang reads `#!/bin/sh\r`, an interpreter that does not exist, so the
    script fails and the whole configuration is refused. The `platformconfig` files are
    parsed line by line, where a trailing `\r` corrupts every value.

    The remote's own configuration mixes endings deliberately - those files are LF while
    `.version` and `META-INF/MANIFEST.MF` are CRLF - so the rule is not "use LF", it is
    "preserve exactly what is there". `.gitattributes` marks the scaffold `-text` for that
    reason.

    A checkout with `core.autocrlf` converts them and the builder, which copies bytes,
    passes the damage through without noticing. See docs/harmony_pk/configuration.md.
    """
    from pathlib import Path

    from afterglow import paths

    scaffold = Path(paths.scaffolds("harmony-900"))
    assert scaffold.is_dir(), scaffold

    # Everything the remote reads as text, except the two that are CRLF on the device.
    crlf_is_correct = {".version", "MANIFEST.MF"}
    offenders = []
    for path in sorted(scaffold.rglob("*")):
        if not path.is_file() or path.name in crlf_is_correct:
            continue
        data = path.read_bytes()
        if b"\x00" in data:            # genuinely binary, not line-oriented
            continue
        if b"\r\n" in data:
            offenders.append(str(path.relative_to(scaffold)))
    assert not offenders, (
        f"CRLF in scaffold files the remote needs as LF: {offenders}. A configuration "
        f"built from this checkout will be rejected by the remote.")

    shebang = (scaffold / ".preinstall").read_bytes()[:20]
    assert shebang.startswith(b"#!/bin/sh\n"), (
        f"the install script's shebang is not usable on the remote: {shebang!r}")


def test_a_build_repairs_a_mangled_scaffold_and_says_so(tmp_path, capsys):
    """Fix it and report it, rather than stopping the user or shipping it broken.

    A configuration built from a CRLF-converted scaffold is well formed in every way this
    project can check - the copy is faithful, the container round-trips byte-identically -
    and the remote still rejects it, after reporting the transfer as successful. The
    working copy is disposable, so repairing it costs nothing and the user gets a
    configuration that flashes.

    Reported, not silent: the real fault is whatever converted the files, and that wants
    fixing at the source rather than being papered over on every build.
    """
    from afterglow.backends.harmony_pk.builder import assemble

    work = tmp_path / "work"
    (work / "platformconfig").mkdir(parents=True)
    (work / ".preinstall").write_bytes(b"#!/bin/sh\r\n\r\necho hello\r\n")
    (work / "platformconfig" / "sleepcfg.dat").write_bytes(b"4\r\n2000\r\n")
    # CRLF is what the remote itself has here, so it must survive untouched.
    (work / ".version").write_bytes(b"0x04 0x00 0x00 0x00\r\n")

    assemble._repair_scaffold_line_endings(str(work))

    assert (work / ".preinstall").read_bytes() == b"#!/bin/sh\n\necho hello\n"
    assert (work / "platformconfig" / "sleepcfg.dat").read_bytes() == b"4\n2000\n"
    assert (work / ".version").read_bytes() == b"0x04 0x00 0x00 0x00\r\n", (
        "files the remote keeps as CRLF must not be 'repaired' into corruption")

    printed = capsys.readouterr().out
    assert "Windows line endings" in printed
    assert ".preinstall" in printed and "sleepcfg.dat" in printed

    # A clean scaffold is left alone and says nothing.
    assemble._repair_scaffold_line_endings(str(work))
    assert capsys.readouterr().out == ""
