"""Afterglow's archive of Logitech's device database, read a device at a time.

The archive serves the raw capture as a static API (harmonic-afterglow/harmony-ir-archive,
`build_api.py`); `harmony_archive.ApiArchive` reads it under the paths the catalogue
reads. These build a small archive the way `build_api.py` lays one out - one smart TV
whose Netflix is an online input, and Logitech's own Toshiba 32 Bit protocol
(`fixtures/archive-protocol-toshiba-32-bit.json`, from the capture) - and check what a
catalogue device comes out with, and that looking one up fetches only its own files.

The projection itself was checked against pickysysadmin's curated tree of the same
capture, field by field: every device field of 20,000 devices agrees, and their command
sets but for commands with no key code, which the curated tree leaves out.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from afterglow import corpus_provider, device_json, harmony_archive, logitech_archive

HERE = Path(__file__).resolve().parent
TV_ID = 272385
CODESET = "0123456789abcdef"


def _press(name, order):
    return {"__type": "IRPressAction:#Logitech", "IRCommandName": name, "Order": order}


def _command(name, code):
    """A Toshiba 32 Bit command as the archive serves one: its key code, and the Pronto
    `build_api.py` adds - the code's bits high first, after the leader, then the repeat
    frames, as every Toshiba 32 Bit command in the capture has them."""
    bits = " ".join("0016 003F" if code >> (31 - n) & 1 else "0016 0015" for n in range(32))
    return {"Name": name, "ProtocolId": 2, "TransportType": 1,
            "KeyCode": f"G:Toshiba 32 Bit:(0x{code:08X})(Repeat)():3",
            "pronto": f"0000 006D 0024 0002 0156 00AB {bits} 0016 05FA "
                      "0156 0055 0016 0E46 0156 0055 0016 0E46",
            "prontoRepeat": "0000 006D 0000 0002 0156 0055 0016 0E46"}


TV = {
    "device": {"Manufacturer": "Panasonic", "Model": "TH-50CS610A", "DeviceType": "Television",
               "InterKeyDelay": 100, "InterDeviceDelay": 500},
    "features": {
        "PowerFeature": [{"PowerTypeId": 1, "PowerOnDelay": 8000,
                          "ConnectedAppPowerOnDelay": 10000,
                          "PowerOnActions": [_press("PowerOn", 0)],
                          "PowerOffActions": [_press("PowerOff", 0)]}],
        "InputFeature": [{"InputType": 1, "InputDelay": 1000, "Inputs": [
            {"InputName": "HDMI 1", "Actions": [_press("InputHdmi1", 0)],
             "PortTypes": [{"Name": "HDMI"}]},
            {"InputName": "Netflix", "IsOnline": True, "Actions": [_press("Netflix", 0)]},
            {"InputName": None, "Actions": [_press("InputHdmi1", 0)]}]}],
    },
    "codeset": CODESET,
    "catalog": {"DeviceType": "Television", "MinRepeats": 2},
}
# Learned in Logitech's software: no key code, no protocol, only the timings captured -
# a 40 kHz carrier, a 2.4 ms mark, then 0.6/1.2 ms marks, and a long gap written in eight
# digits.
LEARNED = ("F9C40P0960S0258P04B0S0258P0258S0258P04B0S000186A0")
COMMANDS = [_command("PowerOn", 0x807F02FD), _command("PowerOff", 0x807F00FF),
            _command("InputHdmi1", 0x807F807F), _command("Netflix", 0x807FB04F),
            {"Name": "Guide", "TransportType": 1, "Raw": LEARNED}]


def _api(root: Path) -> Path:
    """A one-device archive, laid out as `build_api.py` writes `docs/api/v1`."""
    api = root / harmony_archive.API

    def write(relative, value, packed=False):
        path = api / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value).encode()
        path.write_bytes(gzip.compress(payload) if packed else payload)
    write("manifest.json", {
        "api": 1, "build": "b1", "capture_sha256": "c" * 64, "device_buckets": 1024, "codeset_prefix": 3,
        "counts": {"devices": 1, "manufacturers": 1, "codesets": 1,
                   "commands_in_codesets": len(COMMANDS), "protocols": 1}})
    write("manufacturers.json", [{"name": "Panasonic", "slug": "panasonic", "devices": 1}])
    write("manufacturers/panasonic.json", [{"id": TV_ID, "model": "TH-50CS610A",
                                            "type": "Television", "name": None}])
    write(f"devices/{TV_ID % 1024:03x}.json.gz", {str(TV_ID): TV}, packed=True)
    write(f"codesets/{CODESET[:3]}.json.gz", {CODESET: COMMANDS}, packed=True)
    protocol = json.loads((HERE / "fixtures" / "archive-protocol-toshiba-32-bit.json")
                          .read_text())
    write("protocols.json", {"2": protocol})
    return root


def test_a_device_carries_its_timing_and_which_inputs_are_online():
    device = harmony_archive.project_device(TV_ID, TV, f"codesets/{CODESET}.json")

    assert device["timing"]["connectedAppPowerOnDelay"] == 10000
    assert device["timing"]["inputDelay"] == 1000
    assert device["timing"]["powerOnDelay"] == 8000
    assert device["timing"]["minRepeats"] == 2              # the catalogue row's
    assert device["power"] == {"type": "discrete", "on": ["PowerOn"], "off": ["PowerOff"]}
    # a nameless input selects nothing anyone can name, and is left out
    assert device["inputs"]["list"] == [
        {"name": "HDMI 1", "commands": ["InputHdmi1"], "ports": ["HDMI"]},
        {"name": "Netflix", "commands": ["Netflix"], "online": True}]


def test_a_catalogue_device_gets_its_input_delay_and_the_wait_for_its_apps(tmp_path):
    archive = harmony_archive.ApiArchive(_api(tmp_path / "archive"), tmp_path / "cache")
    catalog = corpus_provider.LogitechCatalog(archive)
    [model] = catalog.models("Panasonic", "TH-50CS610A")
    template = catalog.materialize(model)["template"]

    assert template["online_inputs"] == ["Netflix"]
    assert template["timing"]["input_delay"] == 1000
    assert template["timing"]["app_power_delay"] == 10000
    device = device_json.to_project_device(template, "1")
    assert (device["input_delay"], device["app_power_delay"], device["power_delay"]) == (
        1000, 10000, 8000)
    assert device["online_inputs"] == ["Netflix"]


def test_a_learned_command_is_its_captured_timings():
    parsed = logitech_archive.parse_logitech_raw(LEARNED)
    assert parsed["carrier_hz"] == 40000
    assert parsed["pulses_us"] == [2400, -600, 1200, -600, 600, -600, 1200, -100000]
    # one frame, sent again while the key is held
    assert parsed["sections"] == {"intro_pulses": 0, "repeat_pulses": 8}
    with pytest.raises(logitech_archive.ArchiveError):
        logitech_archive.parse_logitech_raw("P0960S0258")       # no carrier


def test_a_device_with_a_learned_command_has_it_beside_the_others(tmp_path):
    """A command with no protocol used to stop the whole device: the catalogue looked
    up every command's protocol."""
    archive = harmony_archive.ApiArchive(_api(tmp_path / "archive"), tmp_path / "cache")
    catalog = corpus_provider.LogitechCatalog(archive)
    result = catalog.materialize(catalog.models("Panasonic", "TH")[0])
    assert result["counts"] == {"source": 5, "supported": 5, "excluded": 0}
    [guide] = [c for c in result["template"]["commands"] if c["name"] == "Guide"]
    assert guide["signal"]["pulses_us"][:2] == [2400, -600]


def test_looking_a_device_up_fetches_only_its_own_files(tmp_path, monkeypatch):
    source = _api(tmp_path / "source")
    prefix = corpus_provider.logitech_archive_url() + "/"
    fetched = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def open_file(request, timeout):
        assert request.full_url.startswith(prefix)
        relative = unquote(request.full_url.removeprefix(prefix))
        fetched.append(relative.removeprefix(harmony_archive.API + "/"))
        return Response((source / relative).read_bytes())

    monkeypatch.setattr(harmony_archive, "urlopen", open_file)
    catalog = corpus_provider.online_logitech_catalog(cache=tmp_path / "cache")
    [model] = catalog.models("Panasonic", "TH")
    catalog.materialize(model)

    assert sorted(fetched) == sorted([
        "manifest.json", "manufacturers.json", "manufacturers/panasonic.json",
        f"devices/{TV_ID % 1024:03x}.json.gz", f"codesets/{CODESET[:3]}.json.gz",
        "protocols.json"])
    # and a second look is served from the cache, but for the manifest: the build
    # it names is what the cache is kept by
    fetched.clear()
    again = corpus_provider.online_logitech_catalog(cache=tmp_path / "cache")
    again.materialize(again.models("Panasonic", "TH")[0])
    assert fetched == ["manifest.json"]


def test_the_archive_is_read_from_its_pages_or_where_the_override_says(monkeypatch):
    monkeypatch.delenv("AFTERGLOW_ARCHIVE_URL", raising=False)
    assert corpus_provider.logitech_archive_url() == (
        "https://harmonic-afterglow.github.io/harmony-ir-archive")
    monkeypatch.setenv("AFTERGLOW_ARCHIVE_URL", "/somewhere/harmony-ir-archive/docs")
    assert corpus_provider.logitech_archive_url() == "/somewhere/harmony-ir-archive/docs"


def test_a_rebuilt_archive_is_read_at_once_and_an_unreachable_one_from_the_cache(tmp_path):
    root = _api(tmp_path / "archive")
    first = harmony_archive.ApiArchive(root, tmp_path / "cache")
    first.read_json(f"devices/panasonic/{TV_ID}.json")

    # rebuilt: the model has a new name, and the build a new id
    api = root / harmony_archive.API
    (api / "manufacturers/panasonic.json").write_text(json.dumps(
        [{"id": TV_ID, "model": "TH-50CS610B", "type": "Television", "name": None}]))
    manifest = json.loads((api / "manifest.json").read_text())
    (api / "manifest.json").write_text(json.dumps({**manifest, "build": "b2"}))
    rebuilt = harmony_archive.ApiArchive(root, tmp_path / "cache")
    assert rebuilt.read_json("devices/panasonic/index.json")[0]["m"] == "TH-50CS610B"

    # gone: what the cache has of the last build it saw still answers
    import shutil
    shutil.rmtree(root)
    offline = harmony_archive.ApiArchive(root, tmp_path / "cache")
    assert offline.read_json("devices/panasonic/index.json")[0]["m"] == "TH-50CS610B"


def test_an_archive_from_another_api_is_refused(tmp_path):
    root = _api(tmp_path / "archive")
    manifest = root / harmony_archive.API / "manifest.json"
    manifest.write_text(json.dumps({**json.loads(manifest.read_text()), "api": 2}))
    with pytest.raises(harmony_archive.ArchiveError, match="API 1"):
        harmony_archive.ApiArchive(root, tmp_path / "cache")
