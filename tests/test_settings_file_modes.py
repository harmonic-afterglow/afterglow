"""The file mode given to the remote's settings files, which is load-bearing.

`data_srv` holds every setting and runs as `nobody`; the update manager extracts a
flashed config as `root`. At 0600 root:root the service can neither read nor write
`platformconfig/system_*.dat`, and the failure is silent: every save fails with EACCES
and the remote falls back to compiled-in defaults at boot.

A dump shows 0600 because there `data_srv` created the files and owns them. Copying a
mode read from a dump is the mistake this guards against. See docs/harmony_pk/configuration.md.
"""
import io
import zipfile

import pytest

from afterglow.payloads.pk import mode_for


def modes_in(path):
    data = open(path, "rb").read()
    start = data.find(b"PK\x03\x04")
    zf = zipfile.ZipFile(io.BytesIO(data[start:]))
    return {i.filename: (i.external_attr >> 16) & 0o7777 for i in zf.infolist()}


def test_a_settings_file_we_ship_is_writable_by_a_process_that_is_not_root():
    """The invariant, stated at the source. `nobody` must retain read and write."""
    mode = mode_for("platformconfig/system_theme.dat") & 0o777
    assert mode & 0o006 == 0o006, (
        f"system_*.dat ships as {oct(mode)}; the remote installs it root-owned, so "
        "data_srv (running as nobody) can neither read nor write it and every setting "
        "silently reverts to a default on the next boot")


@pytest.mark.parametrize("name", ["system_theme.dat", "system_timeformat.dat",
                                  "system_uselargefont.dat", "system_sound.dat",
                                  "system_backlightlevel.dat", "system_childlock.dat"])
def test_every_settings_file_gets_the_same_treatment(name):
    assert mode_for(f"platformconfig/{name}") == 0o100666


def test_non_settings_files_are_not_made_world_writable():
    """The fix is targeted. Nothing else needs loosening, and quietly widening the rest
    would be a change we have no accepted sample of."""
    for path in ("platformconfig/tiltcfg.dat", "platformconfig/batt_lvls.dat",
                 "userconfig/UserConfiguration.xml", "platformconfig/help.db"):
        assert mode_for(path) & 0o002 == 0, f"{path} should not be world-writable"


def test_a_built_config_carries_the_mode_all_the_way_into_the_package(build):
    """mode_for() is only the policy; what matters is the mode recorded in the .ezhex,
    because that is what the remote's extractor applies."""
    device = {"id": "40009001", "label": "TV", "type": "Television",
              "commands": [["PowerOn", "On", "07", "01", None]],
              "power_on_cmd": "PowerOn"}
    out = build({"devices": [device], "activities": [], "assets": []})
    modes = modes_in(out)
    settings = {n: m for n, m in modes.items()
                if n.startswith("platformconfig/system_") and n.endswith(".dat")}
    assert settings, "the build shipped no settings files at all - has the scaffold moved?"
    bad = {n: oct(m) for n, m in settings.items() if m & 0o006 != 0o006}
    assert not bad, f"shipped unreadable/unwritable by nobody: {bad}"
