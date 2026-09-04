"""Shared fixtures.

Real configurations are never committed (see `configs/README.md`), so every test that
needs one asks for it and **skips** when it is absent. A contributor without a Harmony
still gets a useful run; a maintainer with dumps gets the full one.
"""
import contextlib
import io
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex, ir_protocol  # noqa: E402

# The application ships **no** protocol definitions: every protocol it uses is either
# reconstructed from the IrProto blocks of the configuration being imported, or generated
# from an archive record. That is the product, and
# `test_a_configuration_imports_with_no_protocols_installed` covers it directly.
#
# Most tests still need definitions to have something to build *from* - they are checking
# the compiler, the builder and the round-trip, not protocol discovery. Those live here as
# fixtures rather than as shipped data, so the suite exercises the machinery without the
# application carrying a catalogue it is not supposed to have.
_FIXTURE_PROTOCOLS = ROOT / "tests" / "fixtures" / "protocols"
ir_protocol.LIBRARY = _FIXTURE_PROTOCOLS
# Exported so the tests that build in a subprocess inherit the same choice; without it
# they run against the shipped (empty) library and cannot build anything.
os.environ.setdefault("AFTERGLOW_PROTOCOLS", str(_FIXTURE_PROTOCOLS))

# Every real configuration the maintainer may have, in the order tests prefer them.
# Dumps read off real remotes. Deliberately NOT any config Afterglow produced: a
# build output cannot testify that the tool matches the format, only that it agrees
# with itself - and an old one freezes in whatever was wrong when it was made.
CONFIGS = ["configs/mine/dump.ezhex",
           "configs/donor-1/backup.ezhex",
           "configs/donor-2/backup.ezhex",
           "configs/donor-3/backup.ezhex",
           "configs/donor-4/backup.ezhex"]


def existing_configs():
    return [ROOT / name for name in CONFIGS if (ROOT / name).is_file()]


@pytest.fixture(scope="session")
def configs():
    found = existing_configs()
    if not found:
        pytest.skip("no real configurations available")
    return found


@pytest.fixture(scope="session")
def a_config(configs):
    return configs[0]


@pytest.fixture
def unpacked(tmp_path):
    """unpack(config) -> a directory, quietly."""
    def _unpack(config, name="tree"):
        target = tmp_path / name
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(str(config), str(target))
        return target
    return _unpack


@pytest.fixture
def build(tmp_path):
    """build(project) -> the written .ezhex path, quietly."""
    from afterglow.build_service import ConfigBuildService

    def _build(project, name="out.ezhex"):
        out = tmp_path / name
        project.setdefault("settings", {})
        project["settings"].update(out_file=str(out), remote="harmony-900",
                                   first_name="Test", last_name="User")
        with contextlib.redirect_stdout(io.StringIO()):
            ConfigBuildService(ROOT, lambda _m: None).build(project)
        return out
    return _build


def payload_of(path):
    raw = Path(path).read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    return raw[start:start + size]


def entries_of(path):
    import io as _io
    import zipfile
    return zipfile.ZipFile(_io.BytesIO(payload_of(path)))


@pytest.fixture(scope="session")
def qapp_or_skip():
    """A Qt application, or skip. Widget placement is worth testing; needing a display
    is not a reason to leave it untested."""
    pytest.importorskip("PyQt6.QtWidgets")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def synthetic_device_templates():
    """Private-library-shaped GUI fixtures containing no real household devices."""
    samsung = "e8f716b9ee19"
    rc6 = "6bd42e0eea79"
    nec = "a7b8a0e6c639"

    def captured(model, protocol, commands, **extra):
        rows = []
        raw = {}
        for index, (name, label) in enumerate(commands):
            rows.append([name, label, "", "", None])
            # A structurally valid Samsung native code. The command byte varies only
            # to keep fixture entries distinct; no physical product is represented.
            command = index & 0xFF
            inverse = command ^ 0xFF
            raw[name] = (
                f"0x0000E8030101000000{command:02X}{inverse:02X}"
                f"0101000000{command:02X}{inverse:02X}")
        return {
            "_template_name": model, "mfr": "Test", "model": model,
            "label": model, "type": "Television", "codec": "nec",
            "protocol": protocol, "commands": rows, "raw_codes": raw, **extra,
        }

    media = captured("Captured Controller", rc6, [("Start", "Start")])
    # RC6 has a different native framing from Samsung.
    media["raw_codes"]["Start"] = "0x0000F40100000100FFC1EFBD00"
    receiver = captured(
        "Captured Receiver", samsung,
        [("PowerOn", "On"), ("PowerOff", "Off"), ("InputCable", "Cable")],
        type="Receiver", inputs=[["Cable", "InputCable"]])
    television = captured(
        "Captured Television", samsung,
        [("PowerOn", "On"), ("PowerOff", "Off"), ("VolumeUp", "Volume Up")],
        power_on_cmd="PowerOn", power_off_cmd="PowerOff", power_delay=10500,
        properties={"IsDisplayDevice": "true", "AlwaysOn": "false"})
    generated = {
        "_template_name": "Generated Player", "mfr": "Test",
        "model": "Generated Player", "label": "Generated Player",
        "type": "MediaCenterPC", "codec": "necext", "protocol": nec,
        "necext_addr": ["E5", "87"], "always_on": True,
        "commands": [["Menu", "Menu", "E5", "40", "Menu"]],
    }
    captures = {
        str(index): {"schema": "afterglow-ir-signal/1", "kind": "waveform",
                     "name": f"Capture {index}", "carrier_hz": 38000,
                     "pulses_us": [900 + index, -450, 560, -560]}
        for index in range(11)
    }
    captured_light = {
        "_template_name": "Captured Light", "mfr": "Test",
        "model": "Captured Light", "label": "Captured Light", "type": "Light",
        "codec": "raw", "protocol": None,
        "commands": [[f"Command{index}", f"Command {index}", "", "", None]
                     for index in range(11)],
        "raw_codes": {f"Command{index}": f"0xFFFF{index:02X}00"
                      for index in range(11)},
        "raw_ir": captures,
    }
    from afterglow import device_json

    return [device_json.to_project_device(device) for device in
            (media, receiver, television, generated, captured_light)]
