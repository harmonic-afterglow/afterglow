"""The optional Logitech adapter is pinned, lossless, deduplicated, and explicit."""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote

import pytest

from afterglow import corpus_provider, device_json, ir_protocol, ir_signal, logitech_archive


SONY_PRONTO = (
    "0000 0068 000D 0000 0060 0018 0018 0018 0018 0018 0018 0018 0018 "
    "0018 0018 0018 0030 0018 0018 0018 0030 0018 0018 0018 0018 0018 "
    "0018 0018 0018 0434"
)


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _protocol(name: str, protocol_id: int, *, carrier: int = 40000,
              fields: dict | None = None) -> dict:
    return {
        "name": name,
        "logitechProtocolId": protocol_id,
        "carrierHz": carrier,
        "standardProtocol": None,
        "irp": None,
        "keycodeFields": fields or {},
        "pressMinimumRepeats": None,
        "definition": {"Name": name, "CarrierFrequency": carrier},
    }


def _archive(tmp_path: Path) -> tuple[logitech_archive.Archive, str]:
    sony = _protocol(
        "Sony 12 Bit",
        1,
        fields={
            "Code0": {
                "bits": 12,
                "segment": "0",
                "sequence": "repeat",
                "toggleBit": None,
                "token": 0,
            }
        },
    )
    hid = _protocol("HID 16 Bit", 600, carrier=0)
    protocols = [
        {"carrierHz": 40000, "f": "Sony_12_Bit.json", "id": 1,
         "n": "Sony 12 Bit", "standardProtocol": "Sony12"},
        {"carrierHz": 0, "f": "HID_16_Bit.json", "id": 600,
         "n": "HID 16 Bit", "standardProtocol": None},
    ]
    commands = [
        {
            "name": "NextTrack",
            "protocol": "Sony 12 Bit",
            "keycode": "G:Sony 12 Bit:()(0x8D1)():3",
            "pronto": SONY_PRONTO.replace("0030 0018 0018 0018 0030", "0030 0018 "
                                           "0030 0030 0018"),
        },
        {
            "name": "KeyboardA",
            "protocol": "HID 16 Bit",
            "keycode": "G:HID 16 Bit:()(0x0041)():3",
        },
    ]
    # Use the known archive sample (0x050) for the semantic waveform assertion.
    commands[0]["keycode"] = "G:Sony 12 Bit:()(0x050)():3"
    commands[0]["pronto"] = SONY_PRONTO
    codeset_relative = "codesets/ab/abcdef0123456789.json"
    device_relative = "devices/Sony/CDP222ES.json"
    manifest = {
        "schemaVersion": 1,
        "generated": "2026-08-29",
        "source": "Logitech Harmony",
        "counts": {
            "manufacturers": 1,
            "devices": 1,
            "devicesWithCodes": 1,
            "commands": 2,
            "commandsWithPronto": 1,
            "codesets": 1,
            "protocols": 2,
        },
        "layout": {},
    }
    _write(tmp_path / "manifest.json", manifest)
    _write(tmp_path / "index.json", [{"c": 1, "n": "Sony", "s": "Sony"}])
    _write(tmp_path / "devices/Sony/index.json", [
        {"f": "CDP222ES.json", "id": 744, "m": "CDP222ES"},
    ])
    _write(tmp_path / "protocols/index.json", protocols)
    _write(tmp_path / "protocols/Sony_12_Bit.json", sony)
    _write(tmp_path / "protocols/HID_16_Bit.json", hid)
    _write(tmp_path / codeset_relative, {"commands": commands})
    _write(tmp_path / device_relative, {
        "manufacturer": "Sony",
        "model": "CDP222ES",
        "globalDeviceId": 744,
        "deviceType": 3,
        "codeset": codeset_relative,
    })
    return logitech_archive.Archive(tmp_path), device_relative


def _fixed_waveform_archive(tmp_path: Path) -> Path:
    """One indexed device whose unreviewed protocol is safe as a fixed SsIr signal."""
    archive, device_relative = _archive(tmp_path)
    device = archive.device(device_relative)
    protocol = _protocol("Example 4 Bit", 999)
    _write(tmp_path / "protocols/Example_4_Bit.json", protocol)
    index = json.loads((tmp_path / "protocols/index.json").read_text())
    index.append({"carrierHz": 38000, "f": "Example_4_Bit.json", "id": 999,
                  "n": "Example 4 Bit", "standardProtocol": None})
    _write(tmp_path / "protocols/index.json", index)
    _write(tmp_path / device["codeset"], {"commands": [{
        "name": "PowerToggle",
        "protocol": "Example 4 Bit",
        "keycode": "G:Example 4 Bit:()(0x0)():3",
        "pronto": "0000 006D 0002 0000 0010 0010 0020 0020",
    }]})
    return tmp_path


def _generic_protocol_archive(tmp_path: Path) -> Path:
    """One complete source definition that needs no family-specific adapter."""
    archive, device_relative = _archive(tmp_path)
    device = archive.device(device_relative)
    name = "Example 4 Bit Generic"
    protocol = _protocol(name, 998, carrier=38000, fields={
        "Code0": {
            "bits": 4,
            "segment": "0",
            "sequence": "repeat",
            "toggleBit": None,
            "token": 0,
        },
    })
    protocol["definition"] = {
        "Name": name,
        "CarrierFrequency": 38000,
        "IRSegments": [{
            "Name": name,
            "Header": [
                {"Type": 1, "Value": 900, "MinValue": None, "MaxValue": None},
                {"Type": 0, "Value": 450, "MinValue": None, "MaxValue": None},
            ],
            "Payload": {
                "EncodingType": 0,
                "NumberOfBits": 4,
                "ToggleBit": None,
                "Encodings": [
                    {"BitType": 0, "Atoms": [
                        {"Type": 1, "Value": 100, "MinValue": None, "MaxValue": None},
                        {"Type": 0, "Value": 100, "MinValue": None, "MaxValue": None},
                    ]},
                    {"BitType": 1, "Atoms": [
                        {"Type": 1, "Value": 100, "MinValue": None, "MaxValue": None},
                        {"Type": 0, "Value": 300, "MinValue": None, "MaxValue": None},
                    ]},
                ],
            },
            "Trailer": [
                {"Type": 1, "Value": 100, "MinValue": None, "MaxValue": None},
                {"Type": 0, "Value": 1000, "MinValue": None, "MaxValue": None},
            ],
            "TotalLength": 0,
        }],
        "CodeSegments": [],
        "KeyCode": {
            "Start": None,
            "Repeat": [{"SegmentName": name, "SegmentType": 1}],
            "Finish": None,
        },
        "PressMinimumRepeats": None,
        "HoldDelay": None,
        "HoldMinimumRepeats": None,
        "ControlSection": None,
        "IsFullSequence": None,
        "IsPadded": None,
        "SendingType": 0,
        "Flags": [],
        "Attributes": [],
    }
    _write(tmp_path / "protocols/Example_4_Bit_Generic.json", protocol)
    index = json.loads((tmp_path / "protocols/index.json").read_text())
    index.append({"carrierHz": 38000, "f": "Example_4_Bit_Generic.json", "id": 998,
                  "n": name, "standardProtocol": None})
    _write(tmp_path / "protocols/index.json", index)
    _write(tmp_path / device["codeset"], {"commands": [{
        "name": "PowerToggle",
        "protocol": name,
        "keycode": f"G:{name}:()(0xA)():3",
        "pronto": (
            "0000 006D 0006 0000 0022 0011 0004 000B 0004 0004 "
            "0004 000B 0004 0004 0004 0026"
        ),
    }]})
    return tmp_path


def test_pronto_sections_retain_intro_repeat_boundaries_without_copying_pulses():
    parsed = logitech_archive.parse_pronto(
        "0000 006D 0001 0001 0010 0020 0030 0040")

    assert parsed["sections"] == {"intro_pulses": 2, "repeat_pulses": 2}
    assert len(parsed["pulses_us"]) == 4
    assert parsed["pulses_us"][0] > 0
    assert parsed["pulses_us"][1] < 0
    signal = ir_signal.waveform(
        parsed["pulses_us"],
        carrier_hz=parsed["carrier_hz"],
        sections=parsed["sections"],
    )
    ir_signal.validate(signal)


def test_pronto_rejects_a_duration_count_that_disagrees_with_its_header():
    with pytest.raises(logitech_archive.ArchiveError, match="declares"):
        logitech_archive.parse_pronto("0000 006D 0002 0000 0010 0020")


def test_archive_waveforms_can_retain_a_space_longer_than_a_pronto_u16_word():
    parsed = logitech_archive.parse_pronto("0000 006D 0001 0000 0010 382BB")
    assert parsed["pulses_us"][-1] < -1_000_000


def test_pronto_pair_padding_does_not_reject_an_odd_length_portable_waveform():
    agreed, reason = logitech_archive._waveforms_agree(
        [[900, -450, 100]],
        {
            "carrier_hz": 38_000,
            "pulses_us": [900, -450, 100, -26],
            "sections": {"intro_pulses": 4, "repeat_pulses": 0},
        },
        38_000,
    )

    assert agreed
    assert "agrees" in reason


def test_pronto_repeat_section_may_omit_its_leading_silent_delay():
    agreed, reason = logitech_archive._waveforms_agree(
        [[900, -450], [-10_000, 100, -300]],
        {
            "carrier_hz": 38_000,
            "pulses_us": [900, -450, 100, -300],
            "sections": {"intro_pulses": 2, "repeat_pulses": 2},
        },
        38_000,
    )

    assert agreed
    assert "agrees" in reason


def test_pronto_carrier_comparison_uses_its_integer_divisor_quantization():
    quantized_450_khz = round(1_000_000 / (9 * 0.241246))
    agreed, _reason = logitech_archive._waveforms_agree(
        [[200, -300]],
        {
            "carrier_hz": quantized_450_khz,
            "pulses_us": [200, -300],
            "sections": {"intro_pulses": 2, "repeat_pulses": 0},
        },
        450_000,
    )
    disagreed, reason = logitech_archive._waveforms_agree(
        [[200, -300]],
        {
            "carrier_hz": round(1_000_000 / (12 * 0.241246)),
            "pulses_us": [200, -300],
            "sections": {"intro_pulses": 2, "repeat_pulses": 0},
        },
        450_000,
    )

    assert agreed
    assert not disagreed
    assert "carrier frequencies differ" in reason


def test_representative_device_keeps_one_shared_codeset_and_content_addressed_protocols(
        tmp_path):
    archive, device_relative = _archive(tmp_path)
    device, codeset, protocols = logitech_archive.transform_device(
        archive, device_relative)

    assert device["codeset"] == "codesets/ab/abcdef0123456789.json"
    assert codeset["id"] == "abcdef0123456789"
    assert len(protocols) == 2
    assert all(path.startswith("protocols/") for path in protocols)
    assert codeset["commands"][0]["classification"] == (
        "semantic-with-pronto-agreement")
    assert codeset["commands"][0]["signal"]["protocol"] == "sony12"
    assert codeset["commands"][1]["classification"] == "non-ir"
    assert "signal" not in codeset["commands"][1]
    assert codeset["source"]["record"]["commands"][0]["pronto"] == SONY_PRONTO


def test_nec_family_archive_values_become_logical_portable_parameters():
    assert logitech_archive._portable_parameters(0x5EA158A7, "nec-wire") == {
        "address": 0x7A, "command": 0x1A}
    assert logitech_archive._portable_parameters(0xE0E0E01F, "samsung-wire") == {
        "address": 0x07, "command": 0x07}
    with pytest.raises(logitech_archive.ArchiveError, match="complement"):
        logitech_archive._portable_parameters(0x5EA158A6, "nec-wire")


def test_an_unmapped_hold_repeat_count_is_refused_rather_than_guessed(tmp_path):
    """`HoldMinimumRepeats` has no established meaning, so conversion must not invent one.

    Every family in the reference archive declares it `null`, so this path has never run
    on real data. Two readings are available and both are wrong:

      multiplied into `hold`   asserts one repeat *cycle* contains N frames
      mapped to `hold_minimum` lowers to native Code byte 4, a floor that applies to a
                               tap as much as to a held key - `ir_emit._verify_generic`
                               rejects it, because a rendered one-frame press no longer
                               matches the four-frame emission

    Byte 4 empirically tracks `PressMinimumRepeats`: `Sony 12 Bit` declares
    `Press=3, Hold=None` and its flashed Codes carry 3.

    So the field is refused with a message naming what to send. A raw database that does
    populate it must surface here on first contact rather than convert into something
    plausible and wrong - which is the whole reason this test exists while nothing in the
    archive can reach it.
    """
    root = _generic_protocol_archive(tmp_path)
    path = root / "protocols/Example_4_Bit_Generic.json"
    source = json.loads(path.read_text())

    # 0 and 1 are one run either way, and must stay convertible.
    for benign in (None, 0, 1):
        source["definition"]["HoldMinimumRepeats"] = benign
        definition = logitech_archive.portable_protocol(source)
        ir_protocol.validate(definition)
        assert len(definition["transmission"]["hold"]) == 1, (
            f"HoldMinimumRepeats={benign} must not multiply the hold sequence")

    source["definition"]["HoldMinimumRepeats"] = 4
    with pytest.raises(logitech_archive.ArchiveError) as raised:
        logitech_archive.portable_protocol(source)
    assert "HoldMinimumRepeats=4" in str(raised.value)
    assert "Issue" in str(raised.value), "a refusal must say what to send"


def test_complete_source_definition_becomes_a_generic_portable_protocol(tmp_path):
    root = _generic_protocol_archive(tmp_path)
    archive = logitech_archive.Archive(root)
    source = archive.protocol("Example 4 Bit Generic")[1]

    definition = logitech_archive.portable_protocol(source)
    ir_protocol.validate(definition)
    assert definition["id"].startswith("logitech-998-")
    assert definition["parameters"] == {"Code0": {"bits": 4}}
    assert definition["transmission"] == {
        "press": [{"frame": "segment-0", "bind": {"payload": "Code0"}}],
        "hold": [{"frame": "segment-0", "bind": {"payload": "Code0"}}],
        "release": [],
    }


def test_generic_command_is_promoted_only_after_pronto_agreement(tmp_path):
    root = _generic_protocol_archive(tmp_path)
    archive = logitech_archive.Archive(root)
    _device, codeset, protocols = logitech_archive.transform_device(
        archive, "devices/Sony/CDP222ES.json")

    command = codeset["commands"][0]
    assert command["classification"] == "portable-with-pronto-agreement"
    assert command["signal"]["parameters"] == {"Code0": "0xA"}
    wrapper = protocols[command["protocol"]]
    assert wrapper["portable"]["id"] == command["signal"]["protocol"]


def test_exceptional_keycode_recipe_is_preserved_as_a_signal_override(tmp_path):
    root = _generic_protocol_archive(tmp_path)
    codeset_path = root / "codesets/ab/abcdef0123456789.json"
    codeset = json.loads(codeset_path.read_text())
    codeset["commands"][0].update({
        "keycode": "G:Example 4 Bit Generic:(0xA_0x5)()():3",
        "pronto": (
            "0000 006D 000C 0000 "
            "0022 0011 0004 000B 0004 0004 0004 000B 0004 0004 0004 0026 "
            "0022 0011 0004 0004 0004 000B 0004 0004 0004 000B 0004 0026"
        ),
    })
    _write(codeset_path, codeset)
    archive = logitech_archive.Archive(root)

    _device, converted, protocols = logitech_archive.transform_device(
        archive, "devices/Sony/CDP222ES.json")
    command = converted["commands"][0]
    definition = protocols[command["protocol"]]["portable"]
    signal = command["signal"]

    assert command["classification"] == "portable-with-pronto-agreement"
    assert signal["parameters"] == {}
    assert signal["transmission"] == {
        "press": [
            {"frame": "segment-0", "arguments": {"payload": "0xA"}},
            {"frame": "segment-0", "arguments": {"payload": "0x5"}},
        ],
        "hold": [],
        "release": [],
    }
    waveform, _state = ir_protocol.render_transmission(
        signal, library={definition["id"]: definition})
    assert len(waveform["pulses_us"]) == 24


def test_catalogue_device_carries_its_generic_protocol_after_source_disconnects(tmp_path):
    root = _generic_protocol_archive(tmp_path / "source")
    catalog = corpus_provider.LogitechCatalog(root)
    model = catalog.models("Sony", "CDP")[0]
    result = catalog.materialize(model)
    template = result["template"]

    assert result["counts"] == {"source": 1, "supported": 1, "excluded": 0}
    assert len(template["portable_protocol_definitions"]) == 1
    project_device = device_json.to_project_device(template, "40009001")
    protocol_id = project_device["signals"]["PowerToggle"]["protocol"]
    assert project_device["portable_protocol_definitions"][protocol_id]["id"] == protocol_id
    assert project_device["commands"][0][2:4] == ["", "0A"]


def test_optional_real_archive_has_no_well_formed_ir_shape_outside_the_grammar():
    selected = os.environ.get("AFTERGLOW_LOGITECH_ARCHIVE")
    root = (Path(selected).expanduser() if selected else
            Path(__file__).resolve().parents[2] / "logitech-harmony-ir-archive")
    if not (root / "manifest.json").is_file():
        pytest.skip("optional Logitech Harmony IR archive is not present")

    failures = {}
    for path in (root / "protocols").glob("*.json"):
        if path.name == "index.json":
            continue
        source = json.loads(path.read_text(encoding="utf-8"))
        try:
            logitech_archive.portable_protocol(source)
        except logitech_archive.ArchiveError as exc:
            failures[source["name"]] = str(exc)

    assert set(failures) == {
        "HID 16 Bit", "Roku IP", "Sonos IP", "iMonFixed2", "Ferguson 9 Bit Toggle"}


def test_external_catalog_searches_indexes_and_materializes_only_faithful_commands(
        tmp_path):
    root = _fixed_waveform_archive(tmp_path)
    catalog = corpus_provider.LogitechCatalog(root)

    assert [entry.name for entry in catalog.manufacturers("son")] == ["Sony"]
    model = catalog.models("Sony", "CDP")[0]
    result = catalog.materialize(model)

    assert model.relative_path == "devices/Sony/CDP222ES.json"
    assert result["counts"] == {"source": 1, "supported": 1, "excluded": 0}
    assert result["commands"][0]["reason"] == "recorded waveform"
    assert result["template"]["schema"] == "afterglow-device/2"
    assert result["template"]["power"] == {"toggle": "PowerToggle"}
    assert result["template"]["commands"][0]["signal"]["kind"] == "waveform"


def test_external_catalog_is_a_visible_lazy_search_mode(tmp_path, qapp_or_skip):
    root = _fixed_waveform_archive(tmp_path)
    from afterglow.gui.device_wizard import SearchPage

    page = SearchPage([], {}, archive_path=root)
    archive_index = [page.search_type.itemData(index)
                     for index in range(page.search_type.count())].index("archive")
    page.search_type.setCurrentIndex(archive_index)
    page._mfr_box.setText("Sony")
    page._model_box.setText("CDP")
    chosen = next(iter(page._archive_models))
    emitted = []
    page.template_selected.connect(emitted.append)
    page._on_model_chosen(chosen)

    assert page._archive is not None
    assert page._capabilities.rowCount() == 1
    assert "1 of 1 commands" in page._status_lbl.text()
    assert emitted[0]["model"] == "CDP222ES"
    assert emitted[0]["signals"]["PowerToggle"]["kind"] == "waveform"


def test_device_sources_are_independently_enabled_and_persist_outside_projects(
        tmp_path, qapp_or_skip):
    from PyQt6.QtCore import QSettings
    from afterglow.afterglow_sources import ExternalRepository
    from afterglow.gui.source_settings import SourcePreferences

    store = QSettings(str(tmp_path / "afterglow.ini"), QSettings.Format.IniFormat)
    selected = SourcePreferences(
        local_devices=False,
        logitech_online=True,
        flipper_irdb_online=True,
        irdb_online=True,
        external_repositories=(
            ExternalRepository("https://example.test/afterglow-devices.git", False),),
    )
    selected.save(store)

    assert SourcePreferences.load(store) == selected


def test_add_device_lists_only_enabled_catalogues(tmp_path, qapp_or_skip, monkeypatch):
    root = tmp_path / "my-devices"
    _write(root / "devices" / "my-tv.json", {
        "schema": "afterglow-device/2",
        "manufacturer": "My backup",
        "model": "Living room TV",
        "type": "Television",
        "commands": [{
            "name": "PowerToggle",
            "signal": {
                "schema": "afterglow-ir-signal/1",
                "kind": "waveform",
                "name": "power",
                "carrier_hz": 38000,
                "pulses_us": [900, -450, 560, -560],
            },
        }],
    })
    from afterglow import afterglow_sources
    from afterglow.afterglow_sources import ExternalRepository
    from afterglow.gui.device_wizard import SearchPage
    from afterglow.gui.source_settings import SourcePreferences

    monkeypatch.setattr(afterglow_sources, "sync_repository", lambda _repository: root)

    # Every source is named, none left to a default. This test is about what the list
    # shows for a given set of preferences; leaving one implicit made it fail the moment
    # `logitech_online` became true by default, which is a change in configuration and
    # not in the behaviour being tested.
    sources = SourcePreferences(
        local_devices=False,
        logitech_online=False,
        flipper_irdb_online=False,
        irdb_online=False,
        external_repositories=(
            ExternalRepository("https://example.test/my-devices.git"),),
    )
    page = SearchPage([], {}, source_preferences=sources)
    modes = [page.search_type.itemData(index)
             for index in range(page.search_type.count())]

    # "All sources" is always offered and always first: someone adding a device knows the
    # make and model, not which catalogue holds it.
    assert modes == ["all", "afterglow_external:0", "learn"]

    # "all" is the default, so choose the external catalogue to see what it indexed.
    page.search_type.setCurrentIndex(modes.index("afterglow_external:0"))
    assert list(page._repo_index) == ["My backup"]


def test_source_setup_keeps_online_descriptions_compact(qapp_or_skip):
    from PyQt6.QtWidgets import QLabel
    from afterglow.gui.device_wizard import SearchPage
    from afterglow.gui.source_settings import SourcePreferences, SourceSettingsDialog

    sources = SourcePreferences(
        logitech_online=True,
        flipper_irdb_online=True,
        irdb_online=True,
    )
    page = SearchPage([], {}, source_preferences=sources)
    modes = [page.search_type.itemData(index)
             for index in range(page.search_type.count())]
    dialog = SourceSettingsDialog(sources)
    descriptions = "\n".join(label.text() for label in dialog.findChildren(QLabel))

    assert "logitech_online" in modes
    assert "flipper_irdb_online" in modes
    assert "irdb_online" in modes
    assert "Dumped from Logitech" not in descriptions  # grammar stays user-facing
    assert "dumped from Logitech's former Harmony servers" in descriptions
    assert "raw.githubusercontent.com" not in descriptions
    assert "Last-read records" not in descriptions
    assert "Devices dumped, learned, or saved by you." in descriptions
    assert "small reviewed device library" not in descriptions


def test_external_afterglow_sources_are_https_git_repositories_not_folders(tmp_path):
    import pytest
    from afterglow.afterglow_sources import ExternalRepository, cache_path

    repository = ExternalRepository("https://example.test/group/devices.git/")
    repository.validate()

    assert repository.name == "devices"
    assert repository.normalized_url == "https://example.test/group/devices.git"
    assert cache_path(repository, tmp_path).parent == tmp_path
    with pytest.raises(ValueError, match="HTTPS Git"):
        ExternalRepository(str(tmp_path / "devices")).validate()


def test_external_afterglow_repository_clone_is_shallow_and_unpinned(tmp_path, monkeypatch):
    from afterglow import afterglow_sources
    from afterglow.afterglow_sources import ExternalRepository, sync_repository

    calls = []

    def fake_git(*args, cwd=None):
        calls.append((args, cwd))
        target = afterglow_sources.cache_path(repository, tmp_path)
        target.mkdir(parents=True, exist_ok=True)
        (target / ".git").mkdir(exist_ok=True)
        (target / "devices").mkdir(exist_ok=True)
        return ""

    repository = ExternalRepository("https://example.test/afterglow/community.git")
    monkeypatch.setattr(afterglow_sources, "_git", fake_git)

    assert sync_repository(repository, tmp_path).is_dir()
    clone = calls[0][0]
    assert clone[:4] == ("clone", "--depth", "1", "--single-branch")
    assert not any("commit" in argument for argument in clone)


def test_online_catalog_fetches_selected_records_without_a_clone(tmp_path, monkeypatch):
    source = _fixed_waveform_archive(tmp_path / "source")
    prefix = corpus_provider.LOGITECH_ARCHIVE_URL + "/"
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

    def open_record(request, timeout):
        assert timeout == 60
        assert request.full_url.startswith(prefix)
        relative = unquote(request.full_url.removeprefix(prefix))
        fetched.append(relative)
        return Response((source / relative).read_bytes())

    monkeypatch.setattr(logitech_archive, "urlopen", open_record)
    catalog = corpus_provider.online_logitech_catalog(cache=tmp_path / "cache")
    model = catalog.models("Sony", "CDP")[0]
    result = catalog.materialize(model)

    assert result["counts"] == {"source": 1, "supported": 1, "excluded": 0}
    assert set(fetched) == {
        "manifest.json",
        "index.json",
        "devices/Sony/index.json",
        "devices/Sony/CDP222ES.json",
        "codesets/ab/abcdef0123456789.json",
        "protocols/index.json",
        "protocols/Example_4_Bit.json",
    }


def test_audit_resumes_by_codeset_and_finishes_every_command_in_an_explicit_class(
        tmp_path):
    archive, _device_relative = _archive(tmp_path)
    partial = logitech_archive.audit(archive, limit=0)
    assert partial["processed"] == {"codesets": 0, "unique_commands": 0}
    assert not partial["complete"]

    complete = logitech_archive.audit(archive, previous=partial)
    assert complete["complete"]
    assert complete["count_agreement"] == {
        "codesets": True,
        "unique_commands_classified": True,
    }
    assert complete["classifications"] == {
        "non-ir": 1,
        "semantic-with-pronto-agreement": 1,
    }
    assert complete["waveform_fallbacks"] == {"reasons": {}, "protocols": {}}
    # Representation only. Asking what a remote can send is a separate request.
    assert "reproduction" not in complete


def test_audit_measures_remote_reproduction_separately_from_representation(tmp_path):
    """A portable classification is not a claim that any remote can transmit it.

    Quoting corpus coverage alone once put "99.99% portable" in the roadmap for a corpus
    the only writable remote refuses about half of. The two measurements now come out of
    one pass so they cannot drift apart in prose again.
    """
    from afterglow import remotes

    archive, _device_relative = _archive(tmp_path)
    profile = remotes.get("harmony-900")
    state = logitech_archive.audit(archive, reproduce=profile)

    assert state["complete"]
    reproduction = state["reproduction"]
    assert reproduction["remote"] == profile.model
    assert reproduction["backend"] == (profile.infrared or {}).get("backend")

    # Every classified command is answered for, so the two totals stay comparable.
    assert (sum(reproduction["strategies"].values())
            == sum(state["classifications"].values())
            == state["processed"]["unique_commands"])

    # The fixture's Sony 12 Bit command is a shipped semantic protocol the backend
    # emits natively; its HID entry is not infrared at all and has no signal to lower.
    assert reproduction["strategies"] == {"native-protocol": 1, "not-portable": 1}
    assert reproduction["protocols"]["Sony 12 Bit"] == {"native-protocol": 1}


def test_reproduction_survives_a_resumed_audit(tmp_path):
    """Counts carry across a checkpoint; a resumed run must not restart them at zero."""
    from afterglow import remotes

    archive, _device_relative = _archive(tmp_path)
    profile = remotes.get("harmony-900")
    partial = logitech_archive.audit(archive, limit=1, reproduce=profile)
    resumed = logitech_archive.audit(archive, previous=partial, reproduce=profile)
    assert resumed["complete"]
    assert (sum(resumed["reproduction"]["strategies"].values())
            == resumed["processed"]["unique_commands"])


def test_reproduction_caches_parameters_but_not_command_lifecycle(monkeypatch):
    """An exceptional keycode must not inherit its protocol's default verdict."""
    from afterglow import backends

    class Profile:
        model = "test remote"
        infrared = {"backend": "test"}

    class Backend:
        calls = []

        @classmethod
        def capability(cls, signal, _profile, *, library):
            cls.calls.append((signal, library))
            return {"strategy": "native-protocol", "reason": "protocol command"}

    monkeypatch.setattr(backends, "for_profile", lambda _profile: Backend)
    reproduction = logitech_archive._Reproduction(Profile())
    base = {"protocol": "example", "parameters": {"Code0": "0x01"}}
    changed_value = {"protocol": "example", "parameters": {"Code0": "0x02"}}
    override = {
        "protocol": "example",
        "parameters": {},
        "transmission": {"press": [{"frame": "alternate"}], "hold": [], "release": []},
    }

    reproduction._verdict(base, None)
    reproduction._verdict(changed_value, None)
    reproduction._verdict(override, None)

    assert len(Backend.calls) == 2


def _control_archive(tmp_path: Path) -> Path:
    """A device published with schema-2 control data, shaped like the archive's own
    worked example (`Magnavox RJ5540`): a stepped input that needs two presses and a
    wait, alongside one directly selectable input."""
    root = _generic_protocol_archive(tmp_path)
    device_relative = "devices/Sony/CDP222ES.json"
    device = json.loads((root / device_relative).read_text())
    _write(root / device["codeset"], {"commands": [
        {"name": name, "protocol": "Example 4 Bit Generic",
         "keycode": "G:Example 4 Bit Generic:()(0xA)():3",
         "pronto": ("0000 006D 0006 0000 0022 0011 0004 000B 0004 0004 "
                    "0004 000B 0004 0004 0004 0026")}
        for name in ("PowerToggle", "InputNext", "InputAux", "InputTuner")]})
    device.update({
        "timing": {"interKeyDelay": 100, "interDeviceDelay": 500,
                   "powerOnDelay": 4000, "pressMinRepeats": 3},
        "power": {"toggle": ["PowerToggle"], "type": "toggle"},
        "inputs": {"type": 1, "list": [
            {"name": "TV", "commands": ["InputNext", {"delayMs": 500}, "InputTuner"]},
            {"name": "Aux In", "commands": ["InputAux"]},
        ]},
    })
    _write(root / device_relative, device)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["schemaVersion"] = 2
    _write(root / "manifest.json", manifest)
    return root


def test_published_device_control_replaces_the_command_name_heuristic(tmp_path):
    """Logitech's own power and input data is used in place of guessing from names.

    The heuristic reads every command beginning "Input" as a directly selectable input,
    which is wrong in both directions. The archive's worked example is `Magnavox RJ5540`:
    it publishes two inputs, each reached by `InputNext`, a 500 ms wait, then a second
    press. The heuristic invents an input called "Next" out of the stepping command and
    claims each is directly selectable.

    A multi-step entry is skipped rather than flattened to its first command, because
    sending only `InputNext` selects whatever happens to be adjacent.
    """
    catalog = corpus_provider.LogitechCatalog(_control_archive(tmp_path))
    model = next(m for m in catalog.models("Sony", "CDP222ES") if m.name == "CDP222ES")
    template = catalog.materialize(model)["template"]

    assert template["power"] == {
        "mode": "toggle", "toggle": "PowerToggle", "delay_ms": 4000}
    assert template["inputs"] == [
        ["TV", ["InputNext", {"delay_ms": 500}, "InputTuner"]],
        ["Aux In", "InputAux"],
    ], ("a stepped input keeps its whole sequence and must not be flattened to its first "
        "command; a directly selectable one stays a bare name; and InputNext must not "
        "become an input of its own")
    assert template["timing"] == {"press_interkey": 100}

    device = device_json.to_project_device(template, "40000001")
    assert device["power_cmd"] == "PowerToggle"
    assert device["power_delay"] == 4000
    assert device["press_interkey"] == 100


def test_declared_device_states_rebuild_the_shape_logitech_flashes(tmp_path):
    """Archive `states` become the `<State>` blocks a real configuration carries.

    Validated against a pair Logitech itself produced rather than invented here:
    `Panasonic TX-P42VT20E` publishes `AV2Input`, `InputType` and `TVInput` in the
    archive and also appears in a donor configuration, and rebuilding the archive side
    reproduces the flashed side exactly - values, containers and action bodies.

    The fixture mirrors that shape. `setType` is the interesting part: the archive
    documents it as an undecoded enum, and across all eleven routed values of that
    device's `InputType` it decodes without exception - **1 is a plain set, 2 is a
    change** - which the firmware keeps in different action kinds.
    """
    from afterglow.backends.harmony_pk import states as states_mod

    root = _control_archive(tmp_path)
    device_relative = "devices/Sony/CDP222ES.json"
    device = json.loads((root / device_relative).read_text())
    device["states"] = {
        "InputType": {"values": [
            {"name": "AV1", "select": [{"commands": ["InputAux"], "setType": 1}]},
            {"name": "AV2", "select": [{"commands": ["InputTuner"], "setType": 2}]},
            {"name": "Unreachable"},
        ]},
        "Stepper": {"values": [{"name": "A"}, {"name": "B"}],
                    "start": ["PowerToggle"], "next": ["InputNext"]},
    }
    _write(root / device_relative, device)

    catalog = corpus_provider.LogitechCatalog(root)
    model = next(m for m in catalog.models("Sony", "CDP222ES") if m.name == "CDP222ES")
    template = catalog.materialize(model)["template"]

    declared = {s["id"]: s for s in template["control_states"]}
    assert declared["InputType"]["values"] == ["AV1", "AV2", "Unreachable"], (
        "a value with no route is still declared - a {'to': ...} step may name it")
    assert declared["InputType"]["select"]["AV1"]["set_type"] == 1
    assert declared["InputType"]["select"]["AV2"]["set_type"] == 2
    assert "Unreachable" not in declared["InputType"]["select"]

    built = {s["id"]: s for s in
             states_mod.build_control_states(template["control_states"], "7")}
    kinds = {a["name"]: a["kind"] for a in built["InputType"]["actions"]}
    assert kinds == {"AV1": "SetAction", "AV2": "ChangeAction"}, (
        f"setType must select the action kind: {kinds}")

    stepper = built["Stepper"]["actions"]
    assert [(a["group"], a["kind"]) for a in stepper] == [
        (None, "StartAction"), ("RelativeActions", "NextAction")]

    # Mutually exclusive: `State.lua` reads RelativeActions and only falls to
    # DiscreteActions in an elseif, so a state with routes must not also emit stepping.
    assert all(a["group"] != "RelativeActions"
               for a in built["InputType"]["actions"])


def test_a_press_and_hold_keeps_its_length(tmp_path):
    """`durationMs` survives as a real `Duration` parameter, not a bare Hold modifier.

    Real configurations write `Modifier=Press` alongside `Duration=2000` - the Panasonic
    TX-P42VT20E in the donor set powers off that way, and a set that needs a long press
    does nothing at all if sent a tap. SendCommand carries a duration; dropping the
    length loses the press.

    The device `<States>` path already carried it, because that block round-trips
    verbatim. This covers the two places that build actions from parts instead.
    """
    from afterglow.backends.harmony_pk.builder import actions, devices as device_builder

    assert 'name="Duration">2000<' in actions._action(
        ["command", "7", "PowerOff", "Press", 2000])
    assert "Duration" not in actions._action(["command", "7", "PowerOff"])

    root = _control_archive(tmp_path)
    device_relative = "devices/Sony/CDP222ES.json"
    device = json.loads((root / device_relative).read_text())
    device["inputs"] = {"type": 1, "list": [
        {"name": "TV", "commands": [{"command": "InputTuner", "durationMs": 1500}]}]}
    _write(root / device_relative, device)

    catalog = corpus_provider.LogitechCatalog(root)
    model = next(m for m in catalog.models("Sony", "CDP222ES") if m.name == "CDP222ES")
    template = catalog.materialize(model)["template"]
    assert template["inputs"] == [["TV", [{"command": "InputTuner", "hold_ms": 1500}]]]

    project = device_json.to_project_device(template, "7")
    project["_proto_idx"] = 0
    project["raw_codes"] = {name: "000000000100"
                            for name, *_rest in project["commands"]}
    xml, _actions = device_builder._gen_device(project)
    assert 'name="Duration">1500<' in xml, "the hold length must reach the remote"


def test_channel_tuning_and_input_cycling_reach_the_built_configuration(tmp_path):
    """Two more control blocks the archive publishes and the remote can express.

    `fixedDigits` is on 57,940 devices: there, channel 7 must be dialled `07` or the tuner
    waits for a digit that never arrives. And 209,010 devices name their inputs while only
    some name a command that selects one - the rest can only step, so `next`/`previous`
    are the whole of their input control and a list of unreachable names is not useful.
    """
    from afterglow.backends.harmony_pk.builder import devices as device_builder

    root = _control_archive(tmp_path)
    device_relative = "devices/Sony/CDP222ES.json"
    device = json.loads((root / device_relative).read_text())
    _write(root / device["codeset"], {"commands": [
        {"name": name, "protocol": "Example 4 Bit Generic",
         "keycode": "G:Example 4 Bit Generic:()(0xA)():3",
         "pronto": ("0000 006D 0006 0000 0022 0011 0004 000B 0004 0004 "
                    "0004 000B 0004 0004 0004 0026")}
        for name in ["PowerToggle", "InputNext", "InputPrev", "Enter"]
        + [str(digit) for digit in range(10)]]})
    device["channelTuning"] = {"fixedDigits": 2, "finish": ["Enter"]}
    device["inputs"] = {"type": 1, "list": [], "next": ["InputNext"],
                        "previous": ["InputPrev"]}
    _write(root / device_relative, device)

    catalog = corpus_provider.LogitechCatalog(root)
    model = next(m for m in catalog.models("Sony", "CDP222ES") if m.name == "CDP222ES")
    template = catalog.materialize(model)["template"]

    assert template["numeric"] == {"fixed": 2, "finish": "Enter"}

    # The `-/--` prefix, settled from `Numeric.lua` in the firmware image rather than
    # guessed: `<GreaterTen>` and `<GreaterHundred>` are elements of `<Numeric>` holding
    # action lists, emitted before the digits - GreaterTen for a two-digit number,
    # GreaterHundred for three to six.
    device["channelTuning"] = {"fixedDigits": 2, "finish": ["Enter"],
                               "greaterTen": ["InputNext"],
                               "greaterHundred": ["InputPrev", {"delayMs": 200}]}
    _write(root / device_relative, device)
    catalog = corpus_provider.LogitechCatalog(root)
    model = next(m for m in catalog.models("Sony", "CDP222ES") if m.name == "CDP222ES")
    template = catalog.materialize(model)["template"]
    assert template["numeric"] == {
        "fixed": 2, "finish": "Enter", "greater_ten": ["InputNext"],
        "greater_hundred": ["InputPrev", {"delay_ms": 200}]}

    project = device_json.to_project_device(template, "7")
    project["_proto_idx"] = 0
    project["raw_codes"] = {name: "000000000100"
                            for name, *_rest in project["commands"]}
    prefixed, _actions = device_builder._gen_device(project)
    assert "<GreaterTen>" in prefixed and "<GreaterHundred>" in prefixed
    assert prefixed.index("<GreaterTen>") < prefixed.index("<FirstDigit>"), (
        "a prefix is pressed before the digits")
    assert 'name="Delay">200<' in prefixed
    assert template["input_cycle"] == {"next": ["InputNext"],
                                       "previous": ["InputPrev"]}

    project = device_json.to_project_device(template, "7")
    project["_proto_idx"] = 0
    project["raw_codes"] = {name: "000000000100"
                            for name, *_rest in project["commands"]}
    xml, _actions = device_builder._gen_device(project)

    assert "<FixedDigits>2</FixedDigits>" in xml, "channel 7 must be dialled as 07"
    assert "<NextAction>" in xml and "InputNext" in xml
    assert "<PrevAction>" in xml and "InputPrev" in xml


def test_a_sequenced_input_reaches_the_built_configuration_with_its_wait(tmp_path):
    """The whole sequence has to survive to the remote, not just to the device model.

    An input reached by `InputNext`, a settling wait, then `InputTuner` is one of about a
    fifth of the archive's published inputs. Sending only the first step selects whatever
    input happens to be adjacent, so a builder that renders one press per input is not a
    less precise version of this - it is wrong.
    """
    from afterglow.backends.harmony_pk.builder import devices as device_builder

    catalog = corpus_provider.LogitechCatalog(_control_archive(tmp_path))
    model = next(m for m in catalog.models("Sony", "CDP222ES") if m.name == "CDP222ES")
    device = device_json.to_project_device(catalog.materialize(model)["template"], "7")
    # Codes supplied directly: this is about how a *selection sequence* is rendered, not
    # about protocol lowering, and `_gen_device` would otherwise need a native mapping.
    device["_proto_idx"] = 0
    device["raw_codes"] = {name: "000000000100"
                           for name, *_rest in device["commands"]}

    xml, _actions = device_builder._gen_device(device)

    assert "<Name>SendDelay</Name>" in xml and "<Parameter name=\"Delay\">500<" in xml, (
        "the settling wait must reach the configuration")
    tv = xml.split("<Name>TV</Name>")[0]
    assert tv.count("<Name>SendCommand</Name>") >= 2, (
        f"the TV input must send both presses, not just the first: {tv[-400:]}")
    assert "InputNext" in tv and "InputTuner" in tv


def test_a_published_toggle_device_never_gains_guessed_discrete_power(tmp_path):
    """`power.type` is authoritative even when its actions are not expressible here.

    The archive calls `type` its most important field after the codes: a device can carry
    a command named `PowerOn` and still be toggle-behaviour, and sending that to turn a
    set on turns it off half the time. About one published power block in sixty is a
    multi-step sequence this model cannot hold, and falling back to the command-name
    heuristic for those would read `PowerOn`/`PowerOff` out of the code set and declare
    discrete power on a device that only toggles.
    """
    root = _control_archive(tmp_path)
    device_relative = "devices/Sony/CDP222ES.json"
    device = json.loads((root / device_relative).read_text())
    # A code set that names discrete power, and a device Logitech says only toggles - by
    # a route too long to express.
    _write(root / device["codeset"], {"commands": [
        {"name": name, "protocol": "Example 4 Bit Generic",
         "keycode": "G:Example 4 Bit Generic:()(0xA)():3",
         "pronto": ("0000 006D 0006 0000 0022 0011 0004 000B 0004 0004 "
                    "0004 000B 0004 0004 0004 0026")}
        for name in ("PowerOn", "PowerOff", "PowerToggle", "Menu")]})
    device["power"] = {"type": "toggle",
                       "toggle": ["Menu", {"delayMs": 500}, "PowerToggle"]}
    _write(root / device_relative, device)

    catalog = corpus_provider.LogitechCatalog(root)
    model = next(m for m in catalog.models("Sony", "CDP222ES") if m.name == "CDP222ES")
    power = catalog.materialize(model)["template"]["power"]

    assert power["mode"] == "toggle"
    assert "on" not in power and "off" not in power, (
        f"a toggle device must not gain discrete power from command names: {power}")


def test_an_unnamed_catalogue_device_does_not_hide_its_manufacturer(tmp_path):
    """Three of the 276,236 devices publish a null model and no codeset.

    They name nothing and carry no commands, so there is nothing to list or send. One
    such entry used to raise for the whole manufacturer, which made all 20,006 Sony
    devices unreachable. Skip the entry, keep the rest, and still refuse an entry that is
    malformed in any other way.
    """
    root = _control_archive(tmp_path)
    index = json.loads((root / "devices/Sony/index.json").read_text())
    _write(root / "devices/Sony/index.json",
           [{"f": "device-234951.json", "id": 234951, "m": None}] + index)
    catalog = corpus_provider.LogitechCatalog(root)
    assert [m.name for m in catalog.models("Sony", "CDP222ES")] == ["CDP222ES"]

    _write(root / "devices/Sony/index.json",
           [{"f": "broken.json", "id": "not-an-id", "m": "Broken"}] + index)
    catalog = corpus_provider.LogitechCatalog(root)
    with pytest.raises(logitech_archive.ArchiveError, match="incomplete device"):
        catalog.models("Sony", "CDP222ES")


def test_archive_adapter_refuses_an_unpinned_schema(tmp_path):
    """Known schemas are read; an unknown one is refused rather than assumed additive.

    Schema 2 is accepted because upstream states, and the tree confirms, that it only
    adds per-device blocks and leaves `codesets/` and `protocols/` byte-identical. That
    reasoning does not transfer to a version nobody has looked at.
    """
    for known in (1, 2):
        _write(tmp_path / "manifest.json", {"schemaVersion": known})
        logitech_archive.Archive(tmp_path)
    _write(tmp_path / "manifest.json", {"schemaVersion": 3})
    with pytest.raises(logitech_archive.ArchiveError, match="schema"):
        logitech_archive.Archive(tmp_path)


def test_managed_http_source_refuses_a_moving_or_unencrypted_url(tmp_path):
    revision = "a" * 40
    with pytest.raises(logitech_archive.ArchiveError, match="contain its pinned"):
        logitech_archive.CachedHttpArchive(
            "https://example.invalid/archive/main", tmp_path, revision)
    with pytest.raises(logitech_archive.ArchiveError, match="HTTPS"):
        logitech_archive.CachedHttpArchive(
            "http://example.invalid/archive/{revision}", tmp_path, revision)


def test_optional_real_archive_converts_the_documented_sony_representative():
    selected = os.environ.get("AFTERGLOW_LOGITECH_ARCHIVE")
    root = (Path(selected).expanduser() if selected else
            Path(__file__).resolve().parents[2] / "logitech-harmony-ir-archive")
    if not (root / "manifest.json").is_file():
        pytest.skip("optional Logitech Harmony IR archive is not present")

    archive = logitech_archive.Archive(root)
    device, codeset, protocols = logitech_archive.transform_device(
        archive, "devices/Sony/CDP222ES.json")

    assert device["id"] == "logitech:744"
    assert codeset is not None
    assert len(codeset["commands"]) == 7
    assert {command["classification"] for command in codeset["commands"]} == {
        "semantic-with-pronto-agreement"}
    assert len(protocols) == 2


def test_optional_real_archive_builds_the_three_ui_validation_devices(tmp_path):
    selected = os.environ.get("AFTERGLOW_LOGITECH_ARCHIVE")
    root = (Path(selected).expanduser() if selected else
            Path(__file__).resolve().parents[2] / "logitech-harmony-ir-archive")
    if not (root / "manifest.json").is_file():
        pytest.skip("optional Logitech Harmony IR archive is not present")

    from afterglow import device_json
    from afterglow.backends.harmony_pk import irproto, ssir
    from afterglow.build_service import ConfigBuildService
    import zipfile
    import xml.etree.ElementTree as ET

    catalog = corpus_provider.LogitechCatalog(root)
    selected_models = (
        ("Samsung", "QN65S90F", 77),
        ("Yamaha", "HTR-5630RDS", 29),
        # Genuinely mixed-protocol: two long-space mouse commands are safe SsIr
        # entries, and per-command IrProto selection admits all 60 release-framed
        # commands rather than discarding them.
        ("Microsoft", "MCE EU", 126),
    )
    devices = []
    for index, (manufacturer, model_name, expected) in enumerate(selected_models, 1):
        model = catalog.models(manufacturer, model_name)[0]
        result = catalog.materialize(model)
        assert result["counts"]["supported"] == expected
        devices.append(device_json.to_project_device(
            result["template"], f"40009{index:03d}"))

    output = tmp_path / "corpus-ui-validation.ezhex"
    project = {
        "devices": devices,
        "activities": [],
        "assets": [],
        "settings": {
            "remote": "harmony-900",
            "out_file": str(output),
            "first_name": "Corpus",
            "last_name": "Test",
        },
    }
    ConfigBuildService(Path(__file__).resolve().parents[1], lambda _message: None).build(
        project)

    assert output.is_file()
    with zipfile.ZipFile(output) as archive:
        blocks, _starts = irproto.parse_proto(
            archive.read("userconfig/IrProto.bin")[8:])
        captures = ssir.parse(archive.read("userconfig/SsIr.bin"))
        root = ET.fromstring(archive.read("userconfig/UserConfiguration.xml"))
    # Three additional generic blocks carry the MCE command groups that include a
    # release stage. Every command must select the same runtime index in both places.
    assert len(blocks) == 6
    for data in root.findall("Device/Commands/Command/Data"):
        protocol = int(data.findtext("Protocol"))
        code = bytes.fromhex(data.findtext("Code").removeprefix("0x"))
        if protocol < 0:
            assert code.startswith(b"\xff\xff")
        else:
            assert code[0] == protocol
    # There were ten SsIr fallbacks while one block had to win per device. With
    # per-command block selection every one of these 232 commands keeps its VM-gated
    # native lifecycle, so this validation config no longer needs fixed captures.
    assert len(captures) == 0
    assert all(len(capture) >= ssir.HEADER_LEN + ssir.COUNT_LEN for capture in captures)


def test_whole_converter_checkpoints_and_resumes_without_expanding_shared_codesets(
        tmp_path):
    source = tmp_path / "source"
    archive, _device_relative = _archive(source)
    output = tmp_path / "converted"
    tool = Path(__file__).resolve().parents[1] / "tools/logitech_archive.py"
    command = [
        sys.executable,
        str(tool),
        str(archive.root),
        "convert-all",
        str(output),
        "--limit-records",
        "2",
    ]
    for _attempt in range(3):
        subprocess.run(command, check=True, capture_output=True, text=True)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["conversion"]["complete"]
    assert manifest["counts"] == {
        "devices": 1,
        "codesets": 1,
        "protocols": 2,
        "unique_commands": 2,
        "classifications": {
            "non-ir": 1,
            "semantic-with-pronto-agreement": 1,
        },
    }
    assert len(list(output.glob("codesets/*/*.json"))) == 1

    verified = subprocess.run(
        [sys.executable, str(tool), str(archive.root), "verify", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"verified": true' in verified.stdout.lower()


def test_the_archive_revision_is_pinned_and_can_be_overridden(monkeypatch):
    """A third-party repository read at run time must not be a moving target.

    Following `main` means a change upstream alters what a build produces with nothing
    here changing: the same version of Afterglow, the same device, a different answer next
    week, and a bug report nobody can reproduce. Pinning also keeps an upstream mistake
    away from users until the pin is deliberately moved.

    The escape hatch matters as much as the pin - checking whether something is already
    fixed upstream must not need a code edit - so there is an environment variable and a
    setting, and the two caches are kept apart so a record fetched at the tip is never
    served as though it came from the pinned revision.
    """
    from afterglow import corpus_provider

    assert len(corpus_provider.LOGITECH_ARCHIVE_REVISION) == 40, "pin a full commit"
    assert corpus_provider.logitech_archive_url().endswith(
        corpus_provider.LOGITECH_ARCHIVE_REVISION)

    monkeypatch.setenv("AFTERGLOW_LOGITECH_ARCHIVE_REVISION", "main")
    assert corpus_provider.logitech_archive_url().endswith("/main")
    monkeypatch.delenv("AFTERGLOW_LOGITECH_ARCHIVE_REVISION")

    pinned = corpus_provider.online_logitech_catalog()
    latest = corpus_provider.online_logitech_catalog(follow_latest=True)
    assert pinned.archive.cache_root != latest.archive.cache_root, (
        "the pinned and tip caches must not be shared")


def test_all_sources_merges_offline_catalogues_and_prefers_the_local_one(tmp_path,
                                                                        qapp_or_skip,
                                                                        monkeypatch):
    """"All" is the default because a user knows their device, not their catalogues.

    Local entries win a collision: those are the user's own - imported from their
    configuration, learned off their handset - so they carry the commands they actually
    have, where a catalogue entry is a generic record for the model.

    Only in-memory sources are merged. Reaching the network to answer a keystroke would
    make typing a manufacturer's name unpredictably slow, which is why the online
    catalogues keep their own entries in the list.
    """
    from afterglow.gui.device_wizard import SearchPage
    from afterglow.gui.source_settings import SourcePreferences

    local = [{"mfr": "Sony", "model": "KDL-40W2000", "commands": []}]
    page = SearchPage(local, {}, source_preferences=SourcePreferences(
        logitech_online=False, flipper_irdb_online=False, irdb_online=False))
    page._external_repo_indexes["afterglow_external:0"] = {
        "Sony": [{"mfr": "Sony", "model": "KDL-40W2000", "commands": []},
                 {"mfr": "Sony", "model": "STR-DA5400ES", "commands": []}],
        "Yamaha": [{"mfr": "Yamaha", "model": "RX-V3067", "commands": []}],
    }

    merged = page._merged_repo_index()
    assert sorted(merged) == ["Sony", "Yamaha"], "every offline source contributes"
    sony = [entry["model"] for entry in merged["Sony"]]
    assert sony == ["KDL-40W2000", "STR-DA5400ES"], sony
    assert merged["Sony"][0] is local[0], "the local template wins the collision"
