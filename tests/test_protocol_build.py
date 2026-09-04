"""Regression tests for the safe, donor-block-based build path."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from afterglow.backends.harmony_pk import builder as build_config
from afterglow.backends.harmony_pk import donor_profiles, irproto

ROOT = Path(__file__).resolve().parents[1]
import reference_devices as ref  # noqa: E402  (device specs, beside this file)


class ProtocolBuildTests(unittest.TestCase):
    """The donor-profile build path. Needs the maintainer's donor profiles, which are
    never committed, so it skips rather than fails without them."""

    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / "configs" / "profiles").is_dir():
            raise unittest.SkipTest("donor profiles not available")

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="harmony-test-"))
        self.old_cwd = Path.cwd()
        os.chdir(ROOT)

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        shutil.rmtree(self.temp_dir)

    def test_builder_writes_a_wrapped_irproto_file(self) -> None:
        work = self.temp_dir / "work"
        build_config.build([ref.NEC_DEVICE.copy()], str(work))
        payload = irproto.read_payload(work / "userconfig" / "IrProto.bin")
        blocks, starts = irproto.parse_proto(payload)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(starts, [10])
        self.assertEqual(irproto.block_info(blocks[0])["lead_mark_us"], 8990)

    def test_legacy_samsung_index_migrates_to_canonical_block(self) -> None:
        spec = {"id": "40009999", "label": "Test", "type": "Television", "mfr": "Test", "model": "Test",
                "codec": "samsung", "protocol": 1,
                "commands": [("Power", "Power", "07", "02", None)]}
        work = self.temp_dir / "work"
        build_config.build([spec], str(work))
        blocks, _ = irproto.parse_proto(irproto.read_payload(work / "userconfig" / "IrProto.bin"))
        self.assertEqual(irproto.block_info(blocks[0])["lead_mark_us"], 4500)

    def test_unvalidated_donor_block_is_rejected(self) -> None:
        spec = {**ref.NEC_DEVICE, "protocol": "9f379fe650c8"}
        with self.assertRaisesRegex(ValueError, "donor-only"):
            build_config.build([spec], str(self.temp_dir / "work"))

    def test_mixed_blocks_and_command_indexes_stay_aligned(self) -> None:
        samsung = {"id": "40009998", "label": "Samsung", "type": "Television", "mfr": "Test", "model": "Test",
                   "codec": "samsung", "protocol": "e8f716b9ee19",
                   "commands": [("Power", "Power", "07", "02", None)]}
        nec = {"id": "40009997", "label": "NEC", "type": "Receiver", "mfr": "Test", "model": "Test",
               "codec": "nec", "protocol": "a7b8a0e6c639",
               "commands": [("Power", "Power", "7A", "1F", None)]}
        work = self.temp_dir / "work"
        build_config.build([samsung, nec], str(work))
        blocks, _ = irproto.parse_proto(irproto.read_payload(work / "userconfig" / "IrProto.bin"))
        # NEC is pinned to index 0 regardless of the order the devices were given in,
        # so its leader (8990) comes first and Samsung's (4500) second. This is what
        # home.ezhex - built by this code and flashed successfully - actually contains.
        self.assertEqual([irproto.block_info(block)["lead_mark_us"] for block in blocks], [8990, 4500])
        root = ET.parse(work / "userconfig" / "UserConfiguration.xml").getroot()
        commands = root.findall("Device/Commands/Command/Data")
        # The Samsung device was listed first but uses block 1; each command's Code must
        # start with its own block index, not its position in the device list.
        self.assertEqual([data.findtext("Protocol") for data in commands], ["1", "0"])
        self.assertTrue(commands[0].findtext("Code").startswith("0x01"))
        self.assertTrue(commands[1].findtext("Code").startswith("0x00"))

    def test_known_nec_normalizes_identically_from_all_sources(self) -> None:
        locations = [
            ("configs/mine/extracted/userconfig/IrProto.bin", 0),
            ("configs/donor-1/extracted/userconfig/IrProto.bin", 2),
            ("configs/donor-2/extracted/userconfig/IrProto.bin", 0),
        ]
        normalized = []
        for filename, index in locations:
            blocks, starts = irproto.parse_proto(irproto.read_payload(filename))
            normalized.append(irproto.relocate_block(blocks[index], starts[index], irproto.CANON_POS))
        self.assertEqual(normalized[0], normalized[1])
        self.assertEqual(normalized[1], normalized[2])

    def test_donor_profile_preserves_raw_codes_and_remaps_only_index(self) -> None:
        profile = donor_profiles.extract(ROOT / "configs/donor-1/extracted")
        yamaha = next(device for device in profile["devices"] if device["manufacturer"] == "Yamaha")
        sample = yamaha["commands"][0]
        remapped = donor_profiles.remap_protocol_index(sample["raw_code"], 7)
        self.assertTrue(remapped.startswith("0x07"))
        self.assertEqual(remapped[4:], sample["raw_code"][4:])


if __name__ == "__main__":
    unittest.main()


def test_every_emittable_family_is_also_manufacturable():
    """A family we can emit a program for must also be one we can frame Codes for.

    These were two hand-maintained lists and the second went stale: `ir_emit` gained
    Sony, JVC and RC5, `mappings` gained their `code_codec`s, and
    `codes.SYNTHESIZABLE_PROTOCOLS` still named only NEC, Samsung and RC6. The visible
    symptom was a build refusing a generated Sony device as "donor-only" while every
    piece needed to make it was present. `native_registry.code_codecs()` now derives the
    set, so this asserts the two can no longer drift.
    """
    from afterglow.backends.harmony_pk import mappings, native_registry
    from afterglow.backends.harmony_pk.builder import codes

    synthesizable = codes.synthesizable_protocols()
    generated = native_registry.catalog()
    assert generated, "no generated blocks to check"
    for block_id in generated:
        assert block_id in synthesizable, (
            f"block {block_id} can be emitted but not manufactured; a device using it "
            "would be refused as donor-only")

    emittable = {name for name, mapping in mappings.PROTOCOLS.items()
                 if mapping.get("emitter")}
    assert emittable, "no emittable families"
    for name in emittable:
        assert mappings.PROTOCOLS[name].get("code_codec"), (
            f"{name} declares an emitter but no code_codec, so its commands cannot be "
            "built even though its program can be generated")


def test_one_block_may_serve_several_code_codecs():
    """NEC1 and NEC-extended share a pulse program and differ only in Code framing.

    The block id identifies the program, never the Code format, so two codecs naming one
    block is normal rather than a conflict.
    """
    from afterglow.backends.harmony_pk import ir_emit, mappings

    nec1 = ir_emit.emit("nec1", mappings.protocol("nec1"))
    necext = ir_emit.emit("nec-ext", mappings.protocol("nec-ext"))
    assert nec1["id"] == necext["id"]
    assert (mappings.protocol("nec1")["code_codec"]
            != mappings.protocol("nec-ext")["code_codec"])


GENERIC_CODE_CASES = (
    # protocol, parameters, {frame: element index}, minimum repeats, pre-silence us
    ("sony12", {"code": 0x5A5}, {"data": 0}, 3, 500),
    ("sony15", {"code": 0x5A5A}, {"data": 0}, 3, 500),
    ("sony20", {"code": 0xA5A5A}, {"data": 0}, 3, 500),
    ("rc5-13", {"code": 0x15A}, {"data": 0}, 0, 500),
    ("rc6-mce", {"code": 0x1234567}, {"data": 0}, 0, 500),
    ("jvc16", {"code": 0x5A5A}, {"leader": 0, "data": 1}, 0, 500),
    ("nec1", {"address": 0x7A, "command": 0x1A}, {"press": 0, "repeat": 1}, 1, 1000),
    ("nec-ext", {"address_low": 0x12, "address_high": 0x34, "command": 0x56},
     {"press": 0, "repeat": 1}, 1, 1000),
)


def test_generic_code_reproduces_every_hand_written_codec():
    """One generic function must produce what eight bespoke codecs produce.

    A generated block plays nothing without a Code: the Code chooses which elements run,
    in which stage, and supplies their payload. The grammar was read off the VM by
    tracing Codes already proven on hardware -

        Code    = <protocol index:1> <header:4> <stream>
        stream  = stage sections; a leading 0x00 advances the stage
        section = <element count:1> then count x ( <element index:1> <payload...> )

    - and this asserts the reading was right. Byte-for-byte agreement with NEC and
    RC6-MCE matters most, because those Codes are hardware-proven; if the generic path
    reproduces them exactly it inherits that evidence instead of asserting something new.
    """
    from afterglow import ir_protocol
    from afterglow.backends.harmony_pk import mappings
    from afterglow.backends.harmony_pk.builder import codes

    for name, parameters, elements, repeats, silence in GENERIC_CODE_CASES:
        mapping = mappings.protocol(name)
        expected = codes.encode_parameters(
            mapping["code_codec"], parameters, 0,
            repeat_data_copy=mapping.get("repeat_data_copy", False))
        produced = codes.generic_code(
            ir_protocol.protocol(name), elements, parameters, 0,
            pre_silence_us=silence, minimum_repeats=repeats)
        assert produced == expected, name


def test_generic_code_applies_the_invert_transform():
    """NEC's check bytes are the same parameter complemented, and must stay so.

    Dropping `transform: invert` produced a perfectly well-formed Code carrying the
    address where its check byte belongs - a frame a receiver would simply reject, with
    nothing in the build or the VM objecting.
    """
    from afterglow import ir_protocol
    from afterglow.backends.harmony_pk.builder import codes

    produced = codes.generic_code(
        ir_protocol.protocol("nec1"), {"press": 0, "repeat": 1},
        {"address": 0x7A, "command": 0x1A}, 0, pre_silence_us=1000, minimum_repeats=1)
    # byte 0 protocol, 1-4 header, 5 element count, 6 element index, 7-10 payload
    payload = produced[2:][14:22]
    assert payload == "5EA158A7"
    # 0x5E and 0xA1 are bit-reversed 0x7A and its complement 0x85.
    assert codes.bitrev(0x7A) == 0x5E and codes.bitrev(0x7A ^ 0xFF) == 0xA1


def test_an_unknown_transform_is_rejected_at_validation():
    """The guard belongs to the schema, not to each consumer of it.

    `codes._frame_payload` deliberately does not re-check this: it calls the renderer's
    own `_segment_value`, so the Code and the waveform cannot disagree about what a
    field means. That makes validation the only correct place to refuse a transform
    nobody implements - otherwise it would render as identity and emit a plausible,
    wrong frame.
    """
    import copy

    import pytest as _pytest

    from afterglow import ir_protocol

    definition = copy.deepcopy(ir_protocol.protocol("sony12"))
    definition["frames"]["data"]["segments"][1]["transform"] = "gray"
    with _pytest.raises(ValueError, match="transform"):
        ir_protocol.validate(definition)


def _generic_test_protocol(*, ragged=False, oversized_mark=False):
    """A minimal generic protocol.

    `ragged` gives its two symbols unequal word counts. That is **no longer** a refusal:
    the native format pads the shorter symbol with a zero word to a uniform
    `words_per_symbol`, as donor-1 block 6 does.

    `oversized_mark` used to mean a carrier burst longer than one 15-bit word. That is no
    longer a refusal either - `Zenith 11 Bit Quad` emits a 99,999 us mark and Logitech's
    Pronto confirms it, so marks split like spaces. The flag now produces a symbol needing
    more words than the element header's one-byte `words_per_symbol` can count, which is a
    real limit of the format rather than an assumption about hardware.
    """
    from afterglow import ir_protocol

    symbols = ({"0": "zero", "1": "ragged"} if ragged
               else {"0": "zero", "1": "oversized"} if oversized_mark
               else {"0": "zero", "1": "one"})
    return {
        "schema": ir_protocol.SCHEMA,
        "id": "test-generic-lowering",
        "modulation": {"kind": "carrier", "carrier_hz": 38_000},
        "parameters": {"usual": {"bits": 2}},
        "bursts": {
            "zero": [100, -100], "one": [100, -300],
            "ragged": [100, -100, 100, -100],
            # ~400 words once split: the split itself is fine, counting it is not.
            "oversized": [-13_000_000, 100],
        },
        "alphabets": {"bits": {"bits_per_symbol": 1, "symbols": symbols}},
        "frames": {"data": {
            "parameters": {"payload": {"bits": 2}},
            "segments": [{"field": "payload", "order": "msb"}],
        }},
        "transmission": {
            "press": [{"frame": "data", "bind": {"payload": "usual"}}],
            "hold": [{"frame": "data", "bind": {"payload": "usual"}}],
            "release": [],
        },
    }


def _generic_test_device(signal):
    from afterglow import project_devices

    return {
        "schema": project_devices.SCHEMA,
        "id": "40000001", "label": "Generic", "type": "Misc",
        "mfr": "Test", "model": "Generic",
        "commands": [["Probe", "Probe", "", "", None]],
        "signals": {"Probe": signal},
    }


def test_generic_portable_signal_reaches_transient_native_block_and_code(tmp_path):
    """Bindings and command overrides survive the real backend lowering boundary."""
    from afterglow import ir_protocol, ir_signal, remotes
    from afterglow.backends.harmony_pk import backend, ir_vm, protocol_json
    import xml.etree.ElementTree as ET

    definition = _generic_test_protocol()
    transmission = {
        "press": [
            {"frame": "data", "arguments": {"payload": 1}},
            {"frame": "data", "arguments": {"payload": 2}},
        ],
        "hold": [], "release": [],
    }
    signal = ir_signal.protocol_signal(
        definition["id"], {}, transmission=transmission)
    generic_device = _generic_test_device(signal)
    nec_device = _generic_test_device(ir_signal.protocol_signal(
        "nec1", {"address": 0x7A, "command": 0x1A}))
    nec_device.update(id="40000002", label="NEC")
    library = ir_protocol.catalog()
    library[definition["id"]] = definition
    lowered_devices = backend.lower_devices(
        [generic_device, nec_device], remotes.get("harmony-900"), library=library)
    lowered = lowered_devices[0]

    code = lowered["raw_codes"]["Probe"]
    block = next(iter(lowered["protocol_definitions"].values()))
    simulation = ir_vm.simulate_transmission(protocol_json.assemble([block]), code)
    expected, _state = ir_protocol.transmission(
        definition, {}, sequence=transmission)

    assert lowered["protocol"] == block["id"]
    assert ir_vm.normalise_pulses(simulation.pulses_us) == tuple(expected)

    # NEC is forced to runtime index 0, so the generic Code must be rewritten to index 1
    # when the complete tree is assembled.
    work = tmp_path / "tree"
    backend.build_tree(lowered_devices, work, activities=[], settings={})
    root = ET.parse(work / "userconfig/UserConfiguration.xml").getroot()
    command = next(node for node in root.findall(".//Command")
                   if node.findtext("Name") == "Probe")
    built_code = command.findtext("Data/Code")
    assert bytes.fromhex(built_code.removeprefix("0x"))[0] == 1
    built_payload = (work / "userconfig/IrProto.bin").read_bytes()[8:]
    built = ir_vm.simulate_transmission(built_payload, built_code)
    assert ir_vm.normalise_pulses(built.pulses_us) == tuple(expected)


def test_catalogue_capability_accepts_a_vm_gated_native_release():
    """A release-capable command remains admissible after the per-command index seam."""
    from afterglow import ir_protocol, ir_signal, remotes
    from afterglow.backends.harmony_pk import backend

    definition = _generic_test_protocol()
    definition["transmission"]["release"] = [
        {"frame": "data", "bind": {"payload": "usual"}}]
    library = ir_protocol.catalog()
    library[definition["id"]] = definition
    signal = ir_signal.protocol_signal(definition["id"], {"usual": 1})

    result = backend.capability(
        signal, remotes.get("harmony-900"), library=library)

    assert result["supported"]
    assert result["strategy"] == "native-protocol"


def test_reviewed_family_release_uses_generic_stage_five():
    """A mapped family's bespoke Code must never silently discard a release override."""
    from afterglow import ir_protocol, ir_signal, remotes
    from afterglow.backends.harmony_pk import backend, ir_vm, protocol_json

    definition = ir_protocol.protocol("nec1")
    transmission = {
        "press": definition["transmission"]["press"],
        "hold": definition["transmission"]["hold"],
        "release": [{"frame": "repeat"}],
    }
    signal = ir_signal.protocol_signal(
        "nec1", {"address": 0x7A, "command": 0x1A}, transmission=transmission)
    lowered = backend.lower_devices(
        [_generic_test_device(signal)], remotes.get("harmony-900"))[0]

    code = lowered["raw_codes"]["Probe"]
    block = lowered["protocol_definitions"][lowered["command_protocols"]["Probe"]]
    simulation = ir_vm.simulate_transmission(protocol_json.assemble([block]), code)

    assert 5 in simulation.sequence_stages
    assert simulation.sequence_elements[-1] == (1,)


def test_a_ragged_alphabet_is_now_emitted_natively():
    """Unequal symbol widths are padded, not refused.

    Donor-1 block 6 stores `[198, -17200, -17200, 198, -27800, 0]` - three words per
    symbol, a 34,400 us space split across two of them, and a zero word padding the
    shorter symbol. The runtime skips zero-duration words, so the padding never reaches
    the wire. Refusing this shape is what left 6,601 archive commands unreachable.
    """
    from afterglow import ir_signal, remotes
    from afterglow.backends.harmony_pk import backend, ssir

    definition = _generic_test_protocol(ragged=True)
    signal = ir_signal.protocol_signal(definition["id"], {"usual": 1})
    lowered = backend.lower_devices(
        [_generic_test_device(signal)], remotes.get("harmony-900"),
        library={definition["id"]: definition})[0]

    assert lowered["protocol"], "a ragged alphabet should now lower to a native block"
    # `raw_codes` carries the generated native Code here, which is the point; what must
    # NOT appear is an SsIr reference, because that would mean a frozen waveform.
    code = (lowered.get("raw_codes") or {})["Probe"]
    assert not ssir.is_raw(code), f"fell back to a recorded waveform: {code}"


def test_unexpressible_generic_protocol_still_uses_safe_waveform_fallback():
    """Native refusal must not remove the existing fixed-waveform escape hatch.

    The refusal used here is a symbol needing more words than the element header's
    one-byte `words_per_symbol` can count. It replaced "a mark longer than one duration
    word", which was not a real refusal at all - see
    `test_a_carrier_burst_longer_than_one_word_splits_instead_of_refusing`.
    """
    from afterglow import ir_signal, remotes
    from afterglow.backends.harmony_pk import backend, ssir

    definition = _generic_test_protocol(oversized_mark=True)
    signal = ir_signal.protocol_signal(definition["id"], {"usual": 1})
    lowered = backend.lower_devices(
        [_generic_test_device(signal)], remotes.get("harmony-900"),
        library={definition["id"]: definition})[0]

    assert lowered["protocol"] is None
    assert ssir.is_raw(lowered["raw_codes"]["Probe"])


def test_one_device_can_use_an_established_and_a_generic_protocol(tmp_path):
    """Each command selects its own block in both XML and its native Code prefix."""
    from afterglow import ir_protocol, ir_signal, remotes
    from afterglow.backends.harmony_pk import backend, ir_vm, protocol_json
    import xml.etree.ElementTree as ET

    definition = _generic_test_protocol()
    device = _generic_test_device(ir_signal.protocol_signal(
        "nec1", {"address": 0x7A, "command": 0x1A}))
    device["commands"].append(["Extra", "Extra", "", "", None])
    device["signals"]["Extra"] = ir_signal.protocol_signal(
        definition["id"], {"usual": 1})
    library = ir_protocol.catalog()
    library[definition["id"]] = definition

    lowered = backend.lower_devices(
        [device], remotes.get("harmony-900"), library=library)[0]

    generic_id = lowered["command_protocols"]["Extra"]
    assert lowered["protocol"] is None
    assert lowered["command_protocols"] == {
        "Probe": "a7b8a0e6c639", "Extra": generic_id}
    assert "Probe" not in lowered.get("raw_codes", {})

    work = tmp_path / "tree"
    backend.build_tree([lowered], work, activities=[], settings={})
    root = ET.parse(work / "userconfig/UserConfiguration.xml").getroot()
    data = {
        command.findtext("Name"): command.find("Data")
        for command in root.findall(".//Device/Commands/Command")
    }
    assert data["Probe"].findtext("Protocol") == "0"
    assert data["Extra"].findtext("Protocol") == "1"
    assert bytes.fromhex(data["Probe"].findtext("Code").removeprefix("0x"))[0] == 0
    assert bytes.fromhex(data["Extra"].findtext("Code").removeprefix("0x"))[0] == 1

    payload = (work / "userconfig/IrProto.bin").read_bytes()[8:]
    simulated = ir_vm.simulate_transmission(payload, data["Extra"].findtext("Code"))
    expected, _state = ir_protocol.transmission(definition, {"usual": 1})
    assert ir_vm.normalise_pulses(simulated.pulses_us) == tuple(expected)

    # Import must read each command's XML Protocol. Remembering only the last one made
    # every command in a mixed device inherit one block and corrupted the next rebuild.
    # The unknown generic block is then promoted from its block+Code pair instead of
    # leaking a native definition across the portable project boundary.
    imported = backend.import_project(str(work))["devices"][0]
    assert imported["signals"]["Probe"]["protocol"] == "nec1"
    extra = imported["signals"]["Extra"]
    assert extra["kind"] == "protocol"
    assert extra["provenance"]["kind"] == "structural-native-import"
    assert "native" not in extra
    promoted_id = extra["protocol"]
    promoted = imported["portable_protocol_definitions"][promoted_id]
    ir_protocol.validate(promoted)

    # The portable result must survive the seam in the other direction. Its newly
    # compiled native program need not have the source block's storage bytes, but the VM
    # must observe the same complete transmission.
    rebuilt_library = ir_protocol.catalog()
    rebuilt_library[promoted_id] = promoted
    rebuilt = backend.lower_devices(
        [imported], remotes.get("harmony-900"), library=rebuilt_library)[0]
    rebuilt_block_id = rebuilt["command_protocols"]["Extra"]
    rebuilt_block = rebuilt["protocol_definitions"][rebuilt_block_id]
    rebuilt_code = rebuilt["raw_codes"]["Extra"]
    rebuilt_simulation = ir_vm.simulate_transmission(
        protocol_json.assemble([rebuilt_block]), rebuilt_code)
    assert ir_vm.normalise_pulses(rebuilt_simulation.pulses_us) == tuple(expected)


def test_native_promotion_recovers_start_hold_release_and_literal_payloads():
    """The block alone is insufficient; real Codes supply lifecycle and values."""
    from afterglow.backends.harmony_pk import ir_emit, native_portable
    from afterglow.backends.harmony_pk.builder import codes

    definition = _generic_test_protocol()
    transmission = {
        "press": [{"frame": "data", "arguments": {"payload": 1}}],
        "hold": [{"frame": "data", "arguments": {"payload": 2}}],
        "release": [{"frame": "data", "arguments": {"payload": 3}}],
    }
    block = ir_emit.emit_generic(
        definition, parameters={}, transmission=transmission)
    code = codes.generic_code(
        definition, ir_emit.element_order(definition), {}, 0,
        transmission=transmission)

    promoted = native_portable.promote(block, [code])
    recipe = promoted.transmissions[native_portable.code_key(code)]

    assert [item["arguments"]["payload"] for item in recipe["press"]] == [1]
    assert [item["arguments"]["payload"] for item in recipe["hold"]] == [2]
    assert [item["arguments"]["payload"] for item in recipe["release"]] == [3]


def test_a_protocol_frozen_into_a_waveform_reports_itself(capsys):
    """The build direction needs the same error the import direction has.

    A portable protocol that cannot be lowered natively is still sent, as a recorded
    waveform, and that is a downgrade rather than an equivalent encoding: one frozen shape
    cannot hold a distinct repeat frame, a toggle alternating between presses, or a
    release emission. It used to happen in silence, so the button worked and the held-key
    behaviour quietly did not.
    """
    from afterglow.backends.harmony_pk import ir_compile

    ir_compile._report_frozen(
        [("Living Room TV", "VolumeUp", "logitech-999-abc")], "Harmony 900")
    out = capsys.readouterr().out

    assert "ERROR" in out
    assert "Living Room TV" in out and "VolumeUp" in out
    assert "logitech-999-abc" in out, "the protocol must be named for the report"
    assert "Issue" in out, "the message must say what to open"
    assert "release" in out, "it must say what was lost, not just that something was"
    ir_compile._report_frozen([], "Harmony 900")
    assert capsys.readouterr().out == ""


def test_a_block_that_will_not_convert_reports_itself_instead_of_vanishing(capsys):
    """An unconvertible block must produce an error naming what to send, not silence.

    Swallowing the error still imports the commands, as opaque native codes, with
    nothing saying a conversion failed - leaving the only person holding the file that
    would explain it unaware there is anything to report. Promotion succeeds on all 29
    donor blocks and all 675 archive families, so a failure is worth interrupting
    someone about.
    """
    from afterglow.backends.harmony_pk import importer

    importer._report_unpromotable(
        {"abc123": ("native element 2 declares a second toggle position", 47)})
    out = capsys.readouterr().out

    assert "ERROR" in out
    assert "abc123" in out and "47 command(s)" in out
    assert "second toggle position" in out, "the reason must survive to the reader"
    assert "Issue" in out and ".ezhex" in out, (
        "the message must say what to open and what to attach")
    # Silence is the bug being fixed; nothing to say must still say nothing.
    importer._report_unpromotable({})
    assert capsys.readouterr().out == ""


def test_native_promotion_carries_a_mandatory_repeat_count_rather_than_inlining_it():
    """A block whose hold stage must run N times promotes, and stays right when held.

    Six donor blocks used to refuse here: a distinct start stage plus a stage-3 minimum
    repeat count had nowhere to live in the portable model. The obvious repair - spell the
    mandatory runs out in `press` - matches a tap and then diverges the moment the key is
    held, because the firmware plays stage 3 `max(minimum, held + 1)` times while an
    inlined press would play the mandatory runs *and* every held one. Only a carried count
    reproduces both, which is what `hold_minimum` is.

    The assertion that matters is the last one: held past the minimum, the two must still
    agree. A run of held=(0, 1) cannot see this, since both clamp to the minimum.
    """
    from afterglow.backends.harmony_pk import ir_emit, ir_vm, native_portable
    from afterglow.backends.harmony_pk.builder import codes

    definition = _generic_test_protocol()
    transmission = {
        "press": [{"frame": "data", "arguments": {"payload": 1}}],
        "hold": [{"frame": "data", "arguments": {"payload": 2}}],
        "hold_minimum": 4,
    }
    block = ir_emit.emit_generic(
        definition, parameters={}, transmission=transmission)
    code = codes.generic_code(
        definition, ir_emit.element_order(definition), {}, 0,
        transmission=transmission)

    # The count reaches the native Code's minimum-repeat byte instead of being unrolled.
    raw = native_portable._code_bytes(code)
    assert raw[4] == 4, "hold_minimum must land in Code byte 4"

    promoted = native_portable.promote(block, [code])
    recipe = promoted.transmissions[native_portable.code_key(code)]
    assert recipe["hold_minimum"] == 4
    assert [item["arguments"]["payload"] for item in recipe["press"]] == [1], (
        "the mandatory runs must not be unrolled into the press stage")

    from afterglow.backends.harmony_pk import protocol_json
    payload = protocol_json.assemble([block])
    for held in (0, 1, 4, 9):
        emitted = ir_vm.simulate_transmission(payload, raw, held_replays=held)
        runs = sum(1 for stage in emitted.sequence_stages if stage == 3)
        assert runs == max(4, held + 1), (
            f"held={held} ran the hold stage {runs} times, expected {max(4, held + 1)}")


def test_native_promotion_recovers_sender_state_as_a_portable_toggle():
    """A native toggle position becomes a portable state segment, not a refusal.

    This used to refuse, on the reasoning that a waveform description would strand the
    XML metadata driving the toggle. That is no longer true: `ir_emit._frame_layout`
    derives an element's toggle byte from a state segment, so the rebuild carries it, and
    `promote()` proves it by executing both the source block and the rebuilt one and
    requiring the same waveform.

    The recovered shape is the one RC5 itself uses - payload, one-bit state, payload -
    with offsets taken from the toggle's bit position in the run.
    """
    from afterglow.backends.harmony_pk import ir_emit, mappings, native_portable
    from afterglow.backends.harmony_pk.builder import codes

    block = ir_emit.emit("rc5-13", mappings.protocol("rc5-13"))
    code = codes.encode_parameters("rc5-13", {"code": 0x15A}, 0)

    promotion = native_portable.promote(block, [code])
    definition = promotion.definition
    assert definition.get("state"), "a toggling protocol must declare sender state"

    segments = [segment for frame in definition["frames"].values()
                for segment in frame["segments"]]
    assert any("state" in segment for segment in segments), (
        f"no state segment recovered: {segments}")

    # Two toggle values must render two different waveforms, or the state does nothing.
    from afterglow import ir_protocol

    # The frames carry local parameters bound by the transmission, so render through
    # `transmission()` rather than poking one frame directly.
    shapes = set()
    for value in (0, 1):
        state = dict.fromkeys(definition["state"], value)
        pulses, _after = ir_protocol.transmission(
            definition, {}, "press", state=state)
        shapes.add(tuple(pulses or ()))
    assert len(shapes) == 2, "the toggle does not change the emitted waveform"


def test_a_frame_field_nobody_reads_is_refused():
    """An unknown frame key is a silently wrong waveform, so it must not validate.

    A key such as `lead_out_us`, added to put a gap between frames, validates, is never
    read, and leaves the frames it was meant to separate emitted as one continuous burst
    train. Nothing but counting the VM output by hand catches it.
    """
    import pytest

    from afterglow import ir_protocol

    definition = {
        "schema": ir_protocol.SCHEMA, "id": "unknown-frame-field",
        "modulation": {"kind": "carrier", "carrier_hz": 38_000},
        "parameters": {},
        "bursts": {"zero": [600, -600], "one": [600, -1800]},
        "alphabets": {"bits": {"bits_per_symbol": 1,
                               "symbols": {"0": "zero", "1": "one"}}},
        "frames": {"data": {
            "parameters": {"payload": {"bits": 4}},
            "segments": [{"field": "payload", "order": "msb"}],
            "lead_out_us": 20_000,
        }},
        "transmission": {
            "press": [{"frame": "data", "arguments": {"payload": 1}}],
            "hold": [], "release": [],
        },
    }
    with pytest.raises(ValueError, match="unknown fields"):
        ir_protocol.validate(definition)

    # The real field with the same intent still validates.
    definition["frames"]["data"].pop("lead_out_us")
    definition["frames"]["data"]["minimum_period_us"] = 20_000
    ir_protocol.validate(definition)


def test_an_empty_protocol_library_says_so_rather_than_naming_one_protocol():
    """Two different problems must not share one message.

    Wiping the library and importing a configuration through the interface produced
    "no portable IR protocol 'nec1' in <internal path>" - which reads as a corrupt or
    missing entry in an otherwise working library, and sends someone looking for the
    wrong thing. There were simply no definitions installed at all.

    That distinction matters more once the protocol database lives outside this
    repository, because "none installed" becomes an ordinary first-run state rather
    than an impossible one.
    """
    import tempfile

    import pytest

    from afterglow import ir_protocol

    with tempfile.TemporaryDirectory() as empty:
        with pytest.raises(LookupError, match="no IR protocol definitions are installed"):
            ir_protocol.protocol("nec1", Path(empty))

    # A populated library missing one protocol is the other problem, and says the count
    # so it is obvious the library itself loaded.
    with pytest.raises(LookupError, match=r"no portable IR protocol .*\(\d+ installed\)"):
        ir_protocol.protocol("no-such-protocol")


def test_two_table_slots_naming_one_element_materialise_it_once():
    """A block may point two element slots at the same definition.

    `home_logi_dump.ezhex` block 1 does - both entries point at offset 93, and it is the
    only such block in any configuration available here, which is why 38 donor blocks
    extracted cleanly and it did not.

    Materialising once per *slot* relocated the shared element's pointers twice: the
    second pass read back the address the first pass had already written, took it for a
    fresh source, and copied again. The rebuilt block carried 65499 where a pointer
    belonged and `_check_pointers` refused it - correctly, since a mis-declared pointer
    has frozen a real remote before.

    The fixture is built by emitting a real two-element protocol and then pointing both
    table slots at the first element, rather than hand-writing block bytes.
    """
    import struct

    from afterglow.backends.harmony_pk import ir_emit, irproto, mappings, protocol_json

    # NEC1 has a distinct press frame and repeat frame, so its block has two elements.
    block = ir_emit.emit("nec1", mappings.protocol("nec1"))
    payload = protocol_json.assemble([block])

    position = irproto.PROTOCOL_BASE + _u16_at(payload, irproto.PROTOCOL_BASE + 3)
    body = bytearray(payload[position:])
    assert body[6] >= 2, "the fixture needs at least two element slots"
    first = _u16_at(body, 7)
    struct.pack_into("<H", body, 9, first)          # second slot -> the first element

    patched = bytearray(payload)
    patched[position:position + len(body)] = body
    extracted = protocol_json.extract_definition(
        bytes(body), bytes(patched), position, name="shared element")

    # The real assertion is that this did not raise: `extract_definition` re-encodes at
    # the canonical position and validates every pointer, which double relocation fails.
    assert extracted["element_count"] == body[6], "both slots must survive"


def _u16_at(data, offset: int) -> int:
    return int.from_bytes(bytes(data)[offset:offset + 2], "little")


def test_the_config_is_written_as_utf8_whatever_the_platform_encoding(tmp_path):
    """Both XML files declare UTF-8, so neither may take the platform's encoding.

    `ActionLists.xml` was written with no `encoding=`, so it took whatever
    `locale.getpreferredencoding()` said. On Linux that is UTF-8 and nothing showed;
    on Windows it is the ANSI code page, and a command name outside it stops the build
    with a UnicodeEncodeError while one inside it is written as cp1252 bytes in a file
    whose header says UTF-8. `esc()` escapes only & < >, so a non-ASCII command name
    arrives here unchanged.

    Run in a subprocess under a C locale because an in-process check cannot see this:
    the default encoding here is already UTF-8, so the bug is invisible locally - which
    is exactly why it survived. The name is written as an escape so the script itself
    stays ASCII.
    """
    import json
    import subprocess
    import sys

    script = tmp_path / "build_once.py"
    script.write_text(
        "import sys, io, contextlib, json, pathlib\n"
        f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
        f"sys.path.insert(0, {str(ROOT / 'tests')!r})\n"
        "import conftest\n"
        "from test_protocol_build import _generic_test_protocol, _generic_test_device\n"
        "from afterglow import ir_protocol, ir_signal, remotes\n"
        "from afterglow.backends.harmony_pk import backend\n"
        "name = 'Lautst\\u00e4rke+'\n"
        "device = _generic_test_device(ir_signal.protocol_signal(\n"
        "    'nec1', {'address': 0x7A, 'command': 0x1A}))\n"
        "device['commands'].append([name, name, '', '', None])\n"
        "device['signals'][name] = ir_signal.protocol_signal(\n"
        "    'nec1', {'address': 0x7A, 'command': 0x2B})\n"
        "library = ir_protocol.catalog()\n"
        "definition = _generic_test_protocol()\n"
        "library[definition['id']] = definition\n"
        "lowered = backend.lower_devices(\n"
        "    [device], remotes.get('harmony-900'), library=library)[0]\n"
        f"work = pathlib.Path({str(tmp_path / 'tree')!r})\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    backend.build_tree([lowered], work, activities=[], settings={})\n"
        "written = (work / 'userconfig/ActionLists.xml').read_bytes()\n"
        "print(json.dumps({'utf8': name.encode('utf-8') in written}))\n",
        encoding="ascii")

    # ANSI_X3.4-1968 here, the ANSI code page on Windows: anything but UTF-8.
    environment = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0"}
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          env=environment, cwd=tmp_path)
    assert done.returncode == 0, (
        "the build must not depend on the platform encoding:\n" + done.stderr)
    assert json.loads(done.stdout.strip().splitlines()[-1])["utf8"], (
        "ActionLists.xml declares UTF-8 and must be written as UTF-8")
