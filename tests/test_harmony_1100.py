"""A Harmony 1100 configuration is recognised and read without losing a command.

The 1100 plays every command back from a recorded sequence rather than generating it,
so its `SsIr.bin` has a layout of its own and its commands no `<Protocol>`/`<Code>`. These
need a real 1100 configuration (`configs/1100/`) and skip without one.

Format reference: docs/harmony_pk/ssir-sequences.md
"""
from __future__ import annotations

import contextlib
import io
import struct
import zipfile

import pytest

from afterglow import ezhex, project_devices, remotes
from afterglow.backends.harmony_pk import ssir, ssir_sequence


def _payload(path):
    raw = path.read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    return zipfile.ZipFile(io.BytesIO(raw[start:start + size]))


def _import(config, unpacked):
    from afterglow import importer
    with contextlib.redirect_stdout(io.StringIO()):
        return importer.build_project(str(unpacked(config)))


def test_both_skin_numbers_are_the_harmony_1100():
    profile = remotes.get("harmony-1100")
    for skin in (62, 63):
        assert profile.matches({"arch": 11, "skin": skin, "flash": "0x01:0x49",
                                "board": "0.3.0", "software_type": 0})
    assert not remotes.get("harmony-900").matches({"arch": 11, "skin": 62})


def test_it_is_read_only_until_a_build_has_been_flashed_and_booted():
    with pytest.raises(remotes.NotBuildable):
        remotes.get("harmony-1100").require_buildable()


def test_its_interface_has_no_rf_and_its_own_settings():
    profile = remotes.get("harmony-1100")
    assert "rf_blasters" not in profile.settings_fields
    assert list(profile.preferences) == ["time_format", "backlight_level",
                                         "backlight_timeout", "remote_assistant"]
    assert profile.preferences["backlight_level"]["range"] == [0, 255]


def test_the_900s_waveform_table_is_not_read_as_an_1100s():
    with pytest.raises(ValueError):
        ssir_sequence.parse(ssir.build([bytes(8)]))


def test_every_recorded_sequence_is_read_and_kept_exactly(configs_1100):
    for config in configs_1100:
        devices = ssir_sequence.parse(_payload(config).read("userconfig/SsIr.bin"))
        assert devices and all(devices)
        for sequences in devices:
            for sequence in sequences:
                assert sequence.carrier_hz > 0
                assert ssir_sequence.Sequence.from_native(sequence.to_native()) == sequence


def test_a_press_is_one_segment_and_a_hold_two_with_a_repeat_point(configs_1100):
    """Per variant, in every sequence the format document describes."""
    for config in configs_1100:
        for sequences in ssir_sequence.parse(_payload(config).read("userconfig/SsIr.bin")):
            for sequence in sequences:
                shapes = {(len(v.segments()), v.repeat_at is not None)
                          for v in sequence.variants}
                assert shapes in ({(1, False)}, {(2, True)})


def test_the_configuration_identifies_as_an_1100(configs_1100):
    for config in configs_1100:
        header, *_rest = ezhex._split(config.read_bytes())
        assert remotes.identify(header).id == "harmony-1100"


def test_every_command_imports_as_a_waveform_with_its_sequences(configs_1100, unpacked):
    """Nothing dropped: each command in the XML is a portable waveform carrying the
    press and hold sequences it was played from."""
    for config in configs_1100:
        xml = _payload(config).read("userconfig/UserConfiguration.xml").decode()
        project = _import(config, unpacked)
        assert project["settings"]["remote"] == "harmony-1100"
        commands = sum(len(d["commands"]) for d in project["devices"])
        assert commands == xml.count("<Command>")
        for device in project["devices"]:
            project_devices.validate(device)
            for name, signal in device["signals"].items():
                assert signal["kind"] == "waveform", (device["label"], name)
                evidence = signal["native"]["harmony-pk"]
                assert evidence["format"] == "device-sequence" and "press" in evidence


def test_the_remotes_own_settings_come_in_with_it(configs_1100, unpacked):
    for config in configs_1100:
        settings = _import(config, unpacked)["settings"]
        for key in remotes.get("harmony-1100").preferences:
            assert key in settings, key


def test_a_toggle_protocol_keeps_both_of_its_variants(configs_1100, unpacked):
    """RC6 flips one bit per press and the 1100 does not: it keeps one recording per
    toggle state. Importing one of them only would lose every second press."""
    toggling = 0
    for config in configs_1100:
        for device in _import(config, unpacked)["devices"]:
            for signal in device["signals"].values():
                variants = signal["native"]["harmony-pk"]["press"]["variants"]
                if len(variants) == 2:
                    toggling += 1
                    first, second = (bytes.fromhex(v["words"]) for v in variants)
                    assert first != second and len(first) == len(second)
    if not toggling:
        pytest.skip("no toggling device in these configurations")


def test_a_frame_is_what_the_remote_sends_after_its_lead_in(configs_1100):
    """The portable waveform starts at the first mark: the lead-in silence is the
    device's PressPreSilence, recorded into the sequence, not part of the signal."""
    for config in configs_1100:
        for sequences in ssir_sequence.parse(_payload(config).read("userconfig/SsIr.bin")):
            frame = ssir_sequence.first_frame(sequences[0])
            assert frame and frame[0] > 0
            lead = struct.unpack_from("<H", bytes.fromhex(
                sequences[0].to_native()["variants"][0]["words"]))[0]
            assert not lead & 0x8000, "a sequence begins with silence"


def test_remote_settings_for_an_1100_show_its_settings_and_no_blasters(qapp_or_skip):
    from afterglow.gui.tabs import SettingsTab
    tab = SettingsTab({"settings": {"remote": "harmony-1100", "backlight_level": "10"},
                       "devices": [], "activities": []})
    assert list(tab.prefs) == list(remotes.get("harmony-1100").preferences)
    assert tab.prefs["backlight_level"].maximum() == 255
    assert tab.prefs["backlight_level"].value() == 10
    assert not tab.form.isRowVisible(tab.blaster_row)


def test_every_property_the_1100_writes_is_declared_for_it(configs_1100, unpacked):
    """Shown as a setting of this remote, not as an unrecognised carry-over."""
    from afterglow import properties
    catalog = properties.catalog(remotes.get("harmony-1100"))
    for config in configs_1100:
        project = _import(config, unpacked)
        for scope, items in (("device", project["devices"]),
                             ("activity", project["activities"])):
            for item in items:
                for name in item.get("properties") or {}:
                    assert properties.describe(scope, name, catalog)["known"], (scope, name)
