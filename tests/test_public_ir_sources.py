"""Online public catalogues stay lazy and preserve unsupported protocol boundaries."""
import json

import pytest

from afterglow.flipper import parse_ir_text
from afterglow.public_ir_sources import (
    FLIPPER_RAW_URL,
    FLIPPER_TREE_URL,
    IRDB_INDEX_URL,
    IRDB_RAW_URL,
    FlipperIrdbCatalog,
    IrdbCatalog,
)


FLIPPER_REMOTE = """\
Filetype: IR signals file
Version: 1
#
name: Power
type: parsed
protocol: Samsung32
address: 07 00 00 00
command: 02 00 00 00
#
name: Service
type: raw
frequency: 38000
duty_cycle: 0.330000
data: 9000 4500
 560 560
"""


def test_flipper_parser_retains_parsed_bytes_and_multiline_raw_data():
    parsed, raw = parse_ir_text(FLIPPER_REMOTE)

    assert parsed["command"] == "02"
    assert parsed["command_bytes"] == "02 00 00 00"
    assert raw["data"] == "9000 4500 560 560"


def test_flipper_irdb_indexes_and_materializes_one_remote_without_a_clone():
    tree = {"tree": [{
        "path": "TVs/Samsung/Samsung_Test.ir",
        "type": "blob",
    }]}
    requested = []

    def fetch(url):
        requested.append(url)
        if url == FLIPPER_TREE_URL:
            return json.dumps(tree)
        if url == f"{FLIPPER_RAW_URL}/TVs/Samsung/Samsung_Test.ir":
            return FLIPPER_REMOTE
        raise AssertionError(url)

    catalog = FlipperIrdbCatalog(fetch=fetch)
    assert catalog.manufacturers() == [
        catalog.manufacturer("Samsung")]
    model = catalog.models("Samsung", "Test")[0]
    result = catalog.materialize(model)

    assert model.device_type == "Television"
    assert result["counts"] == {"source": 2, "supported": 2, "excluded": 0}
    assert {command["name"] for command in result["template"]["commands"]} == {
        "Power", "Service"}
    assert requested == [FLIPPER_TREE_URL,
                         f"{FLIPPER_RAW_URL}/TVs/Samsung/Samsung_Test.ir"]


def test_irdb_materializes_mapped_rows_and_reports_unmapped_protocols():
    index = "Samsung/TV/7,7.csv\n"
    codes = """\
functionname,protocol,device,subdevice,function
POWER,NECx2,7,7,2
ODD,Sony20,1,-1,4
"""

    def fetch(url):
        if url == IRDB_INDEX_URL:
            return index
        if url == f"{IRDB_RAW_URL}/Samsung/TV/7%2C7.csv":
            return codes
        raise AssertionError(url)

    catalog = IrdbCatalog(fetch=fetch)
    model = catalog.models("Samsung", "TV")[0]
    result = catalog.materialize(model)

    assert result["counts"] == {"source": 2, "supported": 1, "excluded": 1}
    assert result["template"]["commands"][0]["signal"] == {
        "schema": "afterglow-ir-signal/1",
        "kind": "protocol",
        "protocol": "samsung32",
        "parameters": {"address": 7, "command": 2},
        "provenance": {"kind": "irdb", "protocol": "NECx2"},
    }
    assert "not mapped yet" in result["commands"][1]["reason"]


def test_external_afterglow_database_carries_its_portable_protocol_into_a_build(
        tmp_path, build):
    from afterglow import ir_protocol
    pytest.importorskip("afterglow.qt.QtWidgets")
    from afterglow.gui.widgets import load_repo_templates

    root = tmp_path / "my-dumped-devices"
    definition = json.loads(
        (ir_protocol.LIBRARY / "nec2.json").read_text())
    definition["id"] = "my-nec2"
    protocol_path = root / "protocols" / "my-nec2.json"
    protocol_path.parent.mkdir(parents=True)
    protocol_path.write_text(json.dumps(definition))
    device = {
        "schema": "afterglow-device/2",
        "manufacturer": "My backup",
        "model": "Saved receiver",
        "type": "Receiver",
        "commands": [{
            "name": "PowerToggle",
            "signal": {
                "schema": "afterglow-ir-signal/1",
                "kind": "protocol",
                "protocol": "my-nec2",
                "parameters": {"address": 1, "command": 2},
            },
        }],
    }
    device_path = root / "devices" / "saved-receiver.json"
    device_path.parent.mkdir()
    device_path.write_text(json.dumps(device))

    spec = load_repo_templates(root)[0]
    spec.update(id="40009001", label="Saved receiver")
    output = build({"devices": [spec], "activities": [], "settings": {}})

    assert output.is_file()
    assert spec["portable_protocol_definitions"]["my-nec2"]["id"] == "my-nec2"


def test_external_afterglow_database_carries_a_dumped_native_protocol_into_a_build(
        tmp_path, build):
    from afterglow.backends.harmony_pk import ir_emit, mappings
    pytest.importorskip("afterglow.qt.QtWidgets")
    from afterglow.gui.widgets import load_repo_templates

    root = tmp_path / "remote-backups"
    definition = ir_emit.emit("samsung32", mappings.protocol("samsung32"))
    definition["id"] = "123456789abc"
    protocol_path = root / "protocols" / "my-dumped-protocol.json"
    protocol_path.parent.mkdir(parents=True)
    protocol_path.write_text(json.dumps(definition))
    source_command = {
        "name": "PowerToggle", "label": "Power",
        "raw": "0x0000E803010100E0E067980101E0E06798",
    }
    device = {
        "schema": "harmony-ir-device/1",
        "fingerprint": "my-backup",
        "manufacturer": "My backup",
        "model": "Dumped TV",
        "names": ["Dumped TV"],
        "type": "Television",
        "protocol": protocol_path.name,
        "encoding": {"codec": "nec"},
        "commands": [source_command],
    }
    device_path = root / "devices" / "dumped-tv.json"
    device_path.parent.mkdir()
    device_path.write_text(json.dumps(device))

    spec = load_repo_templates(root)[0]
    spec.update(id="40009001", label="Dumped TV")
    output = build({"devices": [spec], "activities": [], "settings": {}})

    assert output.is_file()
    # The dumped program travels with the command and is converted on reading, as every
    # native Code with its program is: the device is portable, so other remotes play it.
    signal = spec["signals"]["PowerToggle"]
    assert signal["kind"] == "protocol"
    assert signal["protocol"] in spec["portable_protocol_definitions"]
    assert "protocol_definitions" not in spec


def test_a_record_naming_a_removed_catalogue_file_is_refused_with_guidance(tmp_path):
    """The legacy filename alias table is gone; the refusal must be actionable.

    It only ever covered 4 of the 21 filenames the removed native catalogue used, so it
    rescued a quarter of such records and failed the rest - a partial rescue that looks
    like success. With the generic compiler reproducing 99.96% of the archive there is
    nothing left for it to save.

    What matters is that the failure names the file and asks for it, rather than letting
    every command decay to opaque evidence that builds and then refuses much later with a
    block id nobody recognises.
    """
    import json
    pytest.importorskip("afterglow.qt.QtWidgets")
    from afterglow.gui.widgets import load_repo_templates

    root = tmp_path / "private-library"
    device_path = root / "devices" / "saved-tv.json"
    device_path.parent.mkdir(parents=True)
    device_path.write_text(json.dumps({
        "schema": "harmony-ir-device/1",
        "manufacturer": "Test", "model": "Saved TV", "type": "Television",
        "protocol": "samsung32-38-0-khz.json", "encoding": {"codec": "nec"},
        "commands": [{
            "name": "PowerToggle", "label": "Power",
            "raw": "0x0000E8030101000000679801010000006798",
        }],
    }))

    # `load_repo_templates` reports and skips a device it cannot read, so the library
    # opens rather than dying on one bad record.
    assert load_repo_templates(root) == []

    from afterglow import device_json
    spec = json.loads(device_path.read_text())
    with pytest.raises(ValueError, match="open an issue"):
        device_json.to_project_device(spec, "40009001", library=root)


# Sony SIRC and RC5, from what each protocol puts on the air - not from the definitions,
# so a mistake in either the translation or a definition shows.
def _merged(pulses):
    out = []
    for value in pulses:
        if out and (out[-1] > 0) == (value > 0):
            out[-1] += value
        else:
            out.append(value)
    return out


def _sirc(command, address, width):
    """2.4 ms mark, then the command and the address lowest bit first, each bit a 0.6 ms
    space and a mark of 0.6 ms for 0 or 1.2 ms for 1."""
    bits = [(command >> i) & 1 for i in range(7)] + [(address >> i) & 1 for i in range(width)]
    out = [2400]
    for bit in bits:
        out += [-600, 1200 if bit else 600]
    return out


def _rc5_air(address, command, toggle=0):
    """Manchester at 889 us a half: start 1, field (clear past command 63), toggle, 5
    address bits and 6 command bits highest first; a 1 is low then high."""
    bits = [1, 0 if command >= 64 else 1, toggle] + \
        [(address >> i) & 1 for i in range(4, -1, -1)] + \
        [(command >> i) & 1 for i in range(5, -1, -1)]
    out = []
    for bit in bits:
        out += [-889, 889] if bit else [889, -889]
    return _merged(out)[1:] if out[0] < 0 else _merged(out)   # no leading silence


@pytest.mark.parametrize("protocol, address, command, width", [
    ("SIRC", 1, 0x15, 5), ("SIRC15", 0x97, 0x2A, 8), ("SIRC20", 0x1A3A, 0x33, 13)])
def test_a_flipper_sony_command_sends_what_sirc_does(protocol, address, command, width):
    from afterglow import ir_protocol
    from afterglow.public_ir_sources import _flipper_signal
    record = {"type": "parsed", "protocol": protocol,
              "address": f"{address & 0xFF:02X} {address >> 8:02X} 00 00",
              "command": f"{command:02X} 00 00 00"}
    signal, _why = _flipper_signal(record)
    air = ir_protocol.render(signal, frame_name="data")["pulses_us"]
    expected = _sirc(command, address, width)
    assert air[:len(expected)] == expected


@pytest.mark.parametrize("address, command", [(0, 12), (5, 53), (20, 70)])
def test_an_rc5_command_sends_what_rc5_does(address, command):
    from afterglow import ir_protocol
    from afterglow.public_ir_sources import _flipper_signal, _irdb_signal
    flipper, _why = _flipper_signal({
        "type": "parsed", "protocol": "RC5X" if command >= 64 else "RC5",
        "address": f"{address:02X} 00 00 00", "command": f"{command:02X} 00 00 00"})
    expected = _rc5_air(address, command)
    air = _merged(ir_protocol.render(flipper, frame_name="data")["pulses_us"])
    assert air[:len(expected) - 1] == expected[:-1]
    if command < 64:
        irdb, _why = _irdb_signal({"protocol": "RC5", "device": str(address),
                                   "subdevice": "-1", "function": str(command)})
        assert irdb["parameters"] == flipper["parameters"]


def test_a_flipper_nec_device_resolves_with_what_is_shipped():
    """The OSSC's commands: NEC, which nothing shipped could resolve."""
    from afterglow import ir_protocol
    from afterglow.public_ir_sources import _flipper_signal
    signal, _why = _flipper_signal({"type": "parsed", "protocol": "NEC",
                                    "address": "00 00 00 00", "command": "1C 00 00 00"})
    assert ir_protocol.render(signal, library=ir_protocol.paths.library("protocols"))


def test_a_flipper_capture_without_its_closing_gap_is_given_one():
    from afterglow.public_ir_sources import RAW_GAP_US, _flipper_signal
    signal, _why = _flipper_signal({"type": "raw", "frequency": "38000",
                                    "data": "9000 4500 560 560 560"})
    assert signal["pulses_us"][-1] == -RAW_GAP_US
    whole, _why = _flipper_signal({"type": "raw", "frequency": "38000",
                                   "data": "9000 4500 560 30000"})
    assert whole["pulses_us"][-1] == -30000              # one it has is kept
