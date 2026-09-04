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
    pytest.importorskip("PyQt6.QtWidgets")
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
    pytest.importorskip("PyQt6.QtWidgets")
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
    signal = spec["signals"]["PowerToggle"]
    assert signal["kind"] == "backend-opaque"
    assert signal["native"]["harmony-pk"]["protocol_definition"]["id"] == \
        "123456789abc"
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
    pytest.importorskip("PyQt6.QtWidgets")
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
