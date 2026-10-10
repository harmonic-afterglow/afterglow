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

from afterglow import ezhex, ir_signal, project_devices, remotes
from afterglow.backends.harmony_pk import ssir, ssir_sequence

from conftest import ROOT


def _payload(path):
    raw = path.read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    return zipfile.ZipFile(io.BytesIO(raw[start:start + size]))


def _build(project, out):
    from afterglow.build_service import ConfigBuildService
    project["settings"].update(out_file=str(out), remote="harmony-1100")
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(ROOT, lambda _m: None).build(project)
    return _payload(out)


def _xml(archive):
    import xml.etree.ElementTree as ET
    return ET.fromstring(archive.read("userconfig/UserConfiguration.xml"))


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


def test_it_builds_but_is_written_only_through_the_test_write_flow():
    """Experimental until a build has been flashed to one and booted."""
    profile = remotes.get("harmony-1100")
    profile.require_buildable()
    with pytest.raises(remotes.NotWritable):
        profile.require_writable()


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
    """Per variant, in every sequence the format document describes: a hold either
    carries its repeat segment or points at one the device shares."""
    for config in configs_1100:
        for sequences in ssir_sequence.parse(_payload(config).read("userconfig/SsIr.bin")):
            for sequence in sequences:
                shapes = {(len(v.segments()), v.repeat_at is not None,
                           v.shared_repeat is not None) for v in sequence.variants}
                assert shapes in ({(1, False, False)}, {(2, True, False)},
                                  {(1, False, True)})


def test_a_shared_repeat_is_pointed_at_where_its_device_first_wrote_it():
    """Logitech stores an NEC repeat frame once per device and points later holds at
    it. Rebuilt, they must still point at that frame, not at bytes that happen to sit
    where it used to be."""
    lead, frame = [0x7FFF, 0x8000 | 9000, 4500], [0x8000 | 560, 560]
    repeat = (0x8000 | 9000, 2250, 0x8000 | 560, *ssir_sequence.SEGMENT_END)
    carrier = (ssir_sequence.carrier_descriptor(38000),)
    start = tuple(lead + frame + list(ssir_sequence.SEGMENT_END))
    own = ssir_sequence.Variant(start + repeat, len(start))
    shared = ssir_sequence.Variant(tuple(lead + frame * 2 + list(ssir_sequence.SEGMENT_END)),
                                   None, shared_repeat=repeat)
    other = ssir_sequence.Sequence(carrier, (ssir_sequence.Variant(start, None),))
    devices = [[ssir_sequence.Sequence(carrier, (own,)), ssir_sequence.Sequence(carrier, (shared,))],
               [other, ssir_sequence.Sequence(carrier, (shared,))]]
    built = ssir_sequence.build(devices)
    assert ssir_sequence.parse(built) == devices
    assert ssir_sequence.build(ssir_sequence.parse(built)) == built
    native = devices[0][1].to_native()
    assert ssir_sequence.Sequence.from_native(native) == devices[0][1]


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


# building for one
def test_a_sequence_table_is_rebuilt_byte_for_byte(configs_1100):
    for config in configs_1100:
        stored = _payload(config).read("userconfig/SsIr.bin")
        assert ssir_sequence.build(ssir_sequence.parse(stored)) == stored


def test_an_imported_configuration_rebuilds_as_logitech_wrote_it(configs_1100, unpacked,
                                                                  tmp_path):
    """Every command plays the sequences it played, every key and touchscreen button is
    where it was, and nothing the 1100 does not have is added."""
    from collections import Counter
    import xml.etree.ElementTree as ET

    def text(element):
        return ET.tostring(element, encoding="unicode")

    for config in configs_1100:
        original = _payload(config)
        built = _build(_import(config, unpacked), tmp_path / f"{config.stem}.ezhex")
        assert built.read("userconfig/SsIr.bin") == original.read("userconfig/SsIr.bin")
        names = set(built.namelist())
        assert not names & {"userconfig/IrProto.bin", "userconfig/ActionLists.xml",
                            "platformconfig/XmlUserRfSetting.xml"}
        header, *_rest = ezhex._split((tmp_path / f"{config.stem}.ezhex").read_bytes())
        donor_header, *_rest = ezhex._split(config.read_bytes())
        assert remotes.identity_of(header) == remotes.identity_of(donor_header)

        want, got = _xml(original), _xml(built)
        assert text(want.find("Controller")) == text(got.find("Controller"))
        for before, after in zip(want.findall("Device"), got.findall("Device")):
            assert [c.tag for c in before] == [c.tag for c in after]
            assert ([text(c) for c in before.findall("Commands/Command")]
                    == [text(c) for c in after.findall("Commands/Command")])
        rebuilt = {a.findtext("Id"): a for a in got.findall("Activity")}
        for activity in want.findall("Activity"):
            again = rebuilt[activity.findtext("Id")]
            groups = {g.get("name"): text(g)
                      for g in again.findall("Presentation/ControlGroup")}
            for group in activity.findall("Presentation/ControlGroup"):
                if group.get("name") == "HardButtons":
                    keys = {b.get("name"): b.findtext("ActionId") for b in group}
                    assert keys == {b.get("name"): b.findtext("ActionId") for b in
                                    again.find("Presentation/ControlGroup[@name="
                                               "'HardButtons']")}
                else:
                    assert groups[group.get("name")] == text(group)
        assert (Counter(text(a) for a in want.findall("ActionList"))
                == Counter(text(a) for a in got.findall("ActionList")))


def _device(device_id, signals):
    return {"schema": "afterglow-project-device/1", "id": device_id,
            "label": f"D{device_id}", "type": "Television", "mfr": "T", "model": "M",
            "commands": [[name, name, "", "", None] for name in signals],
            "signals": signals, "press_presilence": 500, "hold_presilence": 50}


def test_a_device_from_anywhere_is_rendered_into_sequences(tmp_path):
    """No protocol programs on the 1100: a protocol signal is played from a recording
    the build makes - one per toggle state, the hold restarting at its repeat."""
    project = {"settings": {}, "activities": [], "devices": [
        _device("1", {"PowerToggle": ir_signal.protocol_signal(
            "nec1", {"address": 4, "command": 8})}),
        _device("2", {"PowerToggle": ir_signal.protocol_signal(
            "rc6-mce", {"code": 0x0F040C | 0x8000000}),
                      "Mute": ir_signal.protocol_signal("rc6-mce", {"code": 0x0F040E | 0x8000000})})]}
    built = _build(project, tmp_path / "rendered.ezhex")
    nec, rc6 = ssir_sequence.parse(built.read("userconfig/SsIr.bin"))
    assert len(nec) == 2 and len(rc6) == 4                 # presses, then holds
    assert len(nec[0].variants) == 1 and len(rc6[0].variants) == 2
    assert 37000 < nec[0].carrier_hz < 39000 and 35000 < rc6[0].carrier_hz < 37000
    for press, hold in ((nec[0], nec[1]), (rc6[0], rc6[2]), (rc6[1], rc6[3])):
        for variant in press.variants:
            assert len(variant.segments()) == 1 and variant.repeat_at is None
            assert variant.segments()[0][0] == -500_000    # PressPreSilence, recorded
        for variant in hold.variants:
            assert len(variant.segments()) == 2 and variant.repeat_at
    xml = _xml(built)
    data = xml.find("Device[Id='2']/Commands/Command[Name='Mute']/Data")
    assert data.findtext("Press/SequenceIndex") == "1"
    assert data.findtext("Hold/SequenceIndex") == "3"
    assert data.findtext("Press/DeviceIndex") == "1"
    assert xml.find("Device/ControllerId").text == "0"


def test_a_build_for_the_skin_it_was_imported_from(tmp_path):
    """The same remote sold as 62 and 63: the header names the one it is."""
    project = {"settings": {"skin": 62}, "activities": [], "devices": [_device("1", {
        "PowerToggle": ir_signal.protocol_signal("nec1", {"address": 4, "command": 8})})]}
    _build(project, tmp_path / "62.ezhex")
    header, *_rest = ezhex._split((tmp_path / "62.ezhex").read_bytes())
    assert remotes.identity_of(header)["skin"] == 62
    project["settings"]["skin"] = 61
    with pytest.raises(ValueError, match="skin 61"):
        _build(project, tmp_path / "61.ezhex")

