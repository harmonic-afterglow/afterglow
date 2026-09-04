"""Portable protocol semantics stay separate from any one remote's native encoding."""
import json

import pytest

from afterglow import device_json, ir_protocol, ir_signal, remotes
from afterglow.backends.harmony_pk import ir_compile
from afterglow.backends.harmony_pk.builder.codes import (
    code_pre, nec_code, necext_code, portable_code, samsung_code,
)


def test_every_portable_protocol_definition_is_well_formed():
    found = ir_protocol.catalog()
    assert {"nec1", "nec-ext", "nec2", "nec2-ext", "samsung32", "sony12", "sony15",
            "sony20", "jvc16",
            "rc5-13", "rc6-mce"} <= set(found)
    for spec in found.values():
        ir_protocol.validate(spec)


def test_waveform_sections_must_cover_complete_mark_space_pairs():
    signal = ir_signal.waveform(
        [100, -100, 200, -200],
        sections={"intro_pulses": 2, "repeat_pulses": 2},
    )
    ir_signal.validate(signal)

    signal["sections"]["intro_pulses"] = 1
    with pytest.raises(ValueError, match="cover every stored pulse"):
        ir_signal.validate(signal)


def test_harmony_pk_refuses_to_flatten_distinct_waveform_intro_and_repeat_sections():
    class RawOnlyProfile:
        model = "Test Harmony PK"
        infrared = {"backend": "harmony-pk"}

        @staticmethod
        def ir_strategy(_signal):
            return "native-waveform"

    signal = ir_signal.waveform(
        [100, -100, 200, -200],
        sections={"intro_pulses": 2, "repeat_pulses": 2},
    )
    device = {"commands": [["PowerToggle", "PowerToggle"]],
              "signals": {"PowerToggle": signal}}

    with pytest.raises(ValueError, match="distinct intro and repeat"):
        ir_compile.prepare_devices([device], RawOnlyProfile())


def test_nec_semantics_render_the_logical_bits_and_repeat_frame():
    signal = ir_signal.protocol_signal("nec1", {"address": "7A", "command": "1F"})
    waveform = ir_protocol.render(signal)
    pulses = waveform["pulses_us"]

    assert waveform["carrier_hz"] == 38000
    assert pulses[:2] == [9000, -4500]
    # 0x7A transmitted least-significant bit first: 0,1,0,1,1,1,1,0.
    assert [abs(pulses[3 + bit * 2]) for bit in range(8)] == [
        562, 1686, 562, 1686, 1686, 1686, 1686, 562]
    assert sum(abs(pulse) for pulse in pulses) == 108000

    repeat = ir_protocol.render(signal, frame_name="repeat")["pulses_us"]
    assert repeat[:3] == [9000, -2250, 562]
    assert sum(abs(pulse) for pulse in repeat) == 108000


def test_samsung_semantics_repeat_the_full_data_frame():
    signal = ir_signal.protocol_signal("samsung32", {"address": "07", "command": "02"})
    press = ir_protocol.render(signal)["pulses_us"]
    repeat = ir_protocol.render(signal, frame_name="repeat")["pulses_us"]
    assert press == repeat
    assert press[:2] == [4500, -4500]


def test_nec2_extended_uses_the_full_data_frame_for_press_and_hold():
    parameters = {"address_low": "7A", "address_high": "00", "command": "1A"}
    nec2 = ir_protocol.protocol("nec2-ext")
    ordinary = ir_protocol.protocol("nec-ext")
    press, _state = ir_protocol.transmission(nec2, parameters, "press")
    hold, _state = ir_protocol.transmission(nec2, parameters, "hold")

    ordinary_press = ir_protocol.frame(ordinary, parameters, "press")
    assert press[:-1] == ordinary_press[:-1]
    assert sum(abs(pulse) for pulse in press) == 95000
    assert hold == press


def test_nec2_uses_the_standard_complemented_address_and_full_frame_hold():
    parameters = {"address": "7A", "command": "1A"}
    nec2 = ir_protocol.protocol("nec2")
    ordinary = ir_protocol.protocol("nec1")
    press, _state = ir_protocol.transmission(nec2, parameters, "press")
    hold, _state = ir_protocol.transmission(nec2, parameters, "hold")

    ordinary_press = ir_protocol.frame(ordinary, parameters, "press")
    assert press[:-1] == ordinary_press[:-1]
    assert sum(abs(pulse) for pulse in press) == 95000
    assert hold == press


@pytest.mark.parametrize("protocol_id,bits", [
    ("sony12", 12), ("sony15", 15), ("sony20", 20),
])
def test_sony_production_definitions_have_pulse_width_symbols_and_three_press_frames(
        protocol_id, bits):
    spec = ir_protocol.protocol(protocol_id)
    code = (1 << (bits - 1)) | 1
    one = ir_protocol.frame(spec, {"code": code}, "data")
    press, _state = ir_protocol.transmission(spec, {"code": code}, "press")
    hold, _state = ir_protocol.transmission(spec, {"code": code}, "hold")

    assert one[:5] == [2400, -600, 1200, -600, 600]
    assert sum(abs(pulse) for pulse in one) == 45000
    assert press == one * 3
    assert hold == one


def test_jvc16_production_definition_separates_leader_from_hold_frames():
    spec = ir_protocol.protocol("jvc16")
    data = ir_protocol.frame(spec, {"code": 0xC004}, "data")
    press, _state = ir_protocol.transmission(spec, {"code": 0xC004}, "press")
    hold, _state = ir_protocol.transmission(spec, {"code": 0xC004}, "hold")

    assert press[:2] == [8400, -4200]
    assert press[2:] == data
    assert hold == data
    assert sum(abs(pulse) for pulse in data) == 45000


def test_rc5_production_definition_embeds_and_advances_the_toggle_bit():
    spec = ir_protocol.protocol("rc5-13")
    first, state = ir_protocol.transmission(spec, {"code": 0}, "press")
    held, state = ir_protocol.transmission(spec, {"code": 0}, "hold", state=state)
    second, _state = ir_protocol.transmission(spec, {"code": 0}, "press", state=state)

    assert sum(abs(pulse) for pulse in first) == 113792
    assert held == first
    assert second != first


def test_rc6_mce_definition_matches_the_30_bit_header_and_embedded_toggle_shape():
    spec = ir_protocol.protocol("rc6-mce")
    code = 0x3FF07BEF  # Microsoft Windows Media Center Volume Up
    zero = ir_protocol.frame(spec, {"code": code}, "data", state={"toggle": 0})
    one = ir_protocol.frame(spec, {"code": code}, "data", state={"toggle": 1})

    assert zero[:13] == spec["bursts"]["leader"]
    assert sum(abs(pulse) for pulse in zero) == 105850
    assert sum(abs(pulse) for pulse in one) == 105850
    assert zero != one
    # Logitech's ToggleBit 14 is counted from the low end: 14 high payload bits,
    # toggle, then 15 low payload bits. The independently derived Pronto is state 0.
    assert zero[41] == -892 and one[41] == -446

    active = dict(spec)
    active["frames"] = {name: dict(frame) for name, frame in spec["frames"].items()}
    active["frames"]["data"].pop("minimum_period_us")
    assert ir_protocol.frame(
        active, {"code": code}, "data", state={"toggle": 0})[-1] == -2664


def test_symbol_grammar_represents_biphase_and_coalesces_boundaries():
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-biphase",
        "modulation": {"kind": "carrier", "carrier_hz": 36000},
        "parameters": {},
        "bursts": {"zero": [-100, 100], "one": [100, -100]},
        "alphabets": {
            "bits": {"bits_per_symbol": 1,
                     "symbols": {"0": "zero", "1": "one"}}
        },
        "frames": {"press": {"segments": [
            {"constant": 2, "bits": 2, "order": "msb"}
        ]}},
    }
    # Symbols `1` then `0` meet space-to-space and form one 200 us half-bit pair.
    assert ir_protocol.frame(spec, {}) == [100, -200, 100]


def test_symbol_grammar_represents_more_than_one_bit_per_symbol():
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-four-level",
        "modulation": {"kind": "carrier", "carrier_hz": 36000},
        "parameters": {},
        "bursts": {"s0": [100, -100], "s1": [100, -200],
                   "s2": [100, -300], "s3": [100, -400]},
        "alphabets": {"dibits": {"bits_per_symbol": 2,
                      "symbols": {"00": "s0", "01": "s1",
                                  "10": "s2", "11": "s3"}}},
        "frames": {"press": {"segments": [
            {"constant": 6, "bits": 4, "order": "msb", "alphabet": "dibits"}
        ]}},
    }
    assert ir_protocol.frame(spec, {}) == [100, -200, 100, -300]


def test_named_frame_sequences_represent_double_start_and_short_hold_repeat():
    """The Hub's Cambridge example sends data twice, then a different hold frame."""
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-double-start",
        "modulation": {"kind": "carrier", "carrier_hz": 38000},
        "parameters": {},
        "bursts": {"data": [100, -200], "short-repeat": [300, -400]},
        "alphabets": {},
        "frames": {
            "data": {"segments": [{"burst": "data"}]},
            "short-repeat": {"segments": [{"burst": "short-repeat"}]},
        },
        "transmission": {
            "press": [{"frame": "data", "count": 2}],
            "hold": [{"frame": "short-repeat"}],
            "release": [],
        },
    }

    press, state = ir_protocol.transmission(spec, {}, "press")
    hold, state = ir_protocol.transmission(spec, {}, "hold", state=state)
    release, state = ir_protocol.transmission(spec, {}, "release", state=state)

    assert press == [100, -200, 100, -200]
    assert hold == [300, -400]
    assert release == []
    assert state == {}


def test_one_frame_shape_can_bind_different_command_values_per_occurrence():
    """The archive's Cambridge commands use one segment with Code0 then Code1."""
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-bound-frame",
        "modulation": {"kind": "carrier", "carrier_hz": 38000},
        "parameters": {"code0": {"bits": 2}, "code1": {"bits": 2}},
        "bursts": {"zero": [100, -100], "one": [100, -300]},
        "alphabets": {"bits": {"bits_per_symbol": 1,
                      "symbols": {"0": "zero", "1": "one"}}},
        "frames": {"data": {
            "parameters": {"payload": {"bits": 2}},
            "segments": [{"field": "payload", "bits": 2, "order": "msb"}],
        }},
        "transmission": {
            "press": [
                {"frame": "data", "bind": {"payload": "code0"}},
                {"frame": "data", "bind": {"payload": "code1"}},
            ],
            "hold": [],
            "release": [],
        },
    }

    pulses, _state = ir_protocol.transmission(
        spec, {"code0": 1, "code1": 2}, "press")
    assert pulses == [100, -100, 100, -300, 100, -300, 100, -100]

    resolved = ir_protocol.resolve_transmission(spec, {"code0": 1, "code1": 2})
    press = [item for item in resolved if item["phase"] == "press"]
    assert [item["frame"] for item in press] == ["data", "data"]
    assert [item["values"]["payload"] for item in press] == [1, 2]
    assert all(item["declarations"]["payload"] == {"bits": 2} for item in press)


def test_field_slices_place_toggle_state_inside_a_wider_payload():
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-embedded-toggle",
        "modulation": {"kind": "carrier", "carrier_hz": 36000},
        "parameters": {"payload": {"bits": 4}},
        "state": {"toggle": {"kind": "toggle", "initial": 0,
                              "advance": "press"}},
        "bursts": {"zero": [100, -100], "one": [100, -300]},
        "alphabets": {"bits": {"bits_per_symbol": 1,
                      "symbols": {"0": "zero", "1": "one"}}},
        "frames": {"data": {"segments": [
            {"field": "payload", "offset": 3, "bits": 1, "order": "msb"},
            {"state": "toggle", "order": "msb"},
            {"field": "payload", "offset": 0, "bits": 2, "order": "msb"},
        ]}},
        "transmission": {"press": [{"frame": "data"}],
                         "hold": [{"frame": "data"}], "release": []},
    }

    first, state = ir_protocol.transmission(spec, {"payload": 0b1011}, "press")
    held, held_state = ir_protocol.transmission(
        spec, {"payload": 0b1011}, "hold", state=state)
    second, _state = ir_protocol.transmission(
        spec, {"payload": 0b1011}, "press", state=held_state)

    # The original second bit is replaced by toggle: 1 1 1 1, then 1 0 1 1.
    assert first == [100, -300] * 4
    assert held == first
    assert second == [100, -300, 100, -100, 100, -300, 100, -300]


def test_legacy_press_and_repeat_frames_still_define_the_lifecycle():
    spec = dict(ir_protocol.protocol("nec1"))
    spec.pop("transmission")
    parameters = {"address": "7A", "command": "1F"}

    press, _state = ir_protocol.transmission(spec, parameters, "press")
    hold, _state = ir_protocol.transmission(spec, parameters, "hold")
    release, _state = ir_protocol.transmission(spec, parameters, "release")

    assert press == ir_protocol.frame(spec, parameters, "press")
    assert hold == ir_protocol.frame(spec, parameters, "repeat")
    assert release == []


def test_toggle_state_changes_on_new_press_and_remains_stable_while_held():
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-toggle",
        "modulation": {"kind": "carrier", "carrier_hz": 36000},
        "parameters": {},
        "state": {
            "toggle": {"kind": "toggle", "initial": 0, "advance": "press"}
        },
        "bursts": {
            "leader": [300],
            "zero": [-100, 100],
            "one": [100, -100],
        },
        "alphabets": {
            "bits": {"bits_per_symbol": 1,
                     "symbols": {"0": "zero", "1": "one"}}
        },
        "frames": {"data": {"segments": [
            {"burst": "leader"},
            {"state": "toggle", "order": "msb"},
        ]}},
        "transmission": {
            "press": [{"frame": "data"}],
            "hold": [{"frame": "data"}],
            "release": [],
        },
    }

    assert ir_protocol.initial_state(spec) == {"toggle": 0}
    first, state = ir_protocol.transmission(spec, {}, "press")
    held, held_state = ir_protocol.transmission(spec, {}, "hold", state=state)
    second, state = ir_protocol.transmission(spec, {}, "press", state=held_state)

    assert first == [400, -100] and state == {"toggle": 0}
    assert held == first and held_state == {"toggle": 1}
    assert second == [300, -100, 100]


def test_public_transmission_renderer_returns_waveform_and_empty_release(tmp_path):
    definition = ir_protocol.protocol("nec1")
    (tmp_path / "nec1.json").write_text(json.dumps(definition))
    signal = ir_signal.protocol_signal(
        "nec1", {"address": "7A", "command": "1F"}, name="Power")

    waveform, state = ir_protocol.render_transmission(
        signal, phase="hold", library=tmp_path)
    release, state = ir_protocol.render_transmission(
        signal, phase="release", state=state, library=tmp_path)

    assert waveform["pulses_us"] == ir_protocol.frame(
        definition, signal["parameters"], "repeat")
    assert waveform["carrier_hz"] == 38000
    assert waveform["provenance"]["phase"] == "hold"
    assert release is None and state == {}


def test_protocol_signal_can_override_a_recipe_with_occurrence_arguments(tmp_path):
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-command-recipe",
        "modulation": {"kind": "carrier", "carrier_hz": 38_000},
        "parameters": {"usual": {"bits": 2}},
        "bursts": {"zero": [100, -100], "one": [100, -300]},
        "alphabets": {"bits": {"bits_per_symbol": 1,
                      "symbols": {"0": "zero", "1": "one"}}},
        "frames": {"data": {
            "parameters": {"payload": {"bits": 2}},
            "segments": [{"field": "payload", "bits": 2, "order": "msb"}],
        }},
        "transmission": {
            "press": [{"frame": "data", "bind": {"payload": "usual"}}],
            "hold": [{"frame": "data", "bind": {"payload": "usual"}}],
            "release": [],
        },
    }
    (tmp_path / "test-command-recipe.json").write_text(json.dumps(spec))
    signal = ir_signal.protocol_signal(
        spec["id"], {},
        transmission={
            "press": [
                {"frame": "data", "arguments": {"payload": "0x1"}},
                {"frame": "data", "arguments": {"payload": "0x2"}},
            ],
            "hold": [],
            "release": [],
        },
    )

    waveform, state = ir_protocol.render_transmission(signal, library=tmp_path)
    hold, state = ir_protocol.render_transmission(
        signal, phase="hold", state=state, library=tmp_path)

    assert waveform["pulses_us"] == [100, -100, 100, -300, 100, -300, 100, -100]
    assert hold is None and state == {}

    resolved = ir_protocol.resolve_transmission(
        spec, signal["parameters"], sequence=signal["transmission"])
    assert [(item["phase"], item["frame"], item["count"],
             item["values"]["payload"]) for item in resolved] == [
        ("press", "data", 1, 1),
        ("press", "data", 1, 2),
    ]


@pytest.mark.parametrize(("change", "message"), [
    ({"transmission": {"press": [{"frame": "missing"}]}}, "unknown frame"),
    ({"transmission": {"press": [{"frame": "press", "count": 0}]}},
     "count must be positive"),
    ({"state": {"toggle": {"kind": "counter"}}}, "unknown kind"),
])
def test_invalid_transmission_programs_are_rejected(change, message):
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "bad-transmission",
        "modulation": {"kind": "carrier", "carrier_hz": 38000},
        "parameters": {},
        "bursts": {"pulse": [100, -100]},
        "alphabets": {},
        "frames": {"press": {"segments": [{"burst": "pulse"}]}},
    }
    spec.update(change)
    with pytest.raises(ValueError, match=message):
        ir_protocol.validate(spec)


def test_invalid_frame_bindings_and_slices_are_rejected():
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "bad-binding",
        "modulation": {"kind": "carrier", "carrier_hz": 38000},
        "parameters": {"source": {"bits": 4}},
        "bursts": {"zero": [100, -100], "one": [100, -200]},
        "alphabets": {"bits": {"bits_per_symbol": 1,
                      "symbols": {"0": "zero", "1": "one"}}},
        "frames": {"data": {
            "parameters": {"payload": {"bits": 4}},
            "segments": [{"field": "payload", "offset": 3, "bits": 2}],
        }},
        "transmission": {"press": [
            {"frame": "data", "bind": {"payload": "source"}}
        ]},
    }
    with pytest.raises(ValueError, match="slice exceeds"):
        ir_protocol.validate(spec)

    spec["frames"]["data"]["segments"][0] = {"field": "payload", "bits": 4}
    spec["transmission"]["press"][0]["bind"] = {}
    with pytest.raises(ValueError, match="must supply exactly"):
        ir_protocol.validate(spec)


@pytest.mark.parametrize(("signal", "expected"), [
    (ir_signal.protocol_signal("nec1", {"address": "7A", "command": "1F"}),
     nec_code("7A", "1F", code_pre(3))),
    (ir_signal.protocol_signal("nec-ext", {"address_low": "E5", "address_high": "87",
                                           "command": "0A"}),
     necext_code("E5", "87", "0A", code_pre(3))),
    (ir_signal.protocol_signal("samsung32", {"address": "07", "command": "02"}),
     samsung_code("07", "02", code_pre(3))),
])
def test_portable_signals_lower_to_the_existing_proven_harmony_codes(signal, expected):
    assert portable_code(signal, 3) == expected


def test_device_translation_produces_only_portable_fields(tmp_path):
    source = {
        "schema": device_json.PORTABLE_SCHEMA,
        "manufacturer": "Test", "model": "Portable NEC", "type": "Receiver",
        "commands": [{
            "name": "VolumeUp", "label": "VOL+", "hard_key": "VolumeUp",
            "signal": ir_signal.protocol_signal(
                "nec1", {"address": "7A", "command": "1A"}),
        }],
    }
    built = device_json.to_project_device(source, "40009001", library=tmp_path)
    volume = built["signals"]["VolumeUp"]
    assert volume["protocol"] == "nec1"
    assert volume["parameters"] == {"address": "7A", "command": "1A"}
    assert portable_code(volume, 0) == "0x0000E8030101005EA158A7010100"
    assert built["commands"] == [["VolumeUp", "VOL+", "7A", "1A", "VolumeUp"]]
    assert "codec" not in built and "protocol" not in built


def test_public_v2_device_commands_resolve_portable_signal_references(tmp_path):
    signal_path = tmp_path / "signals" / "volume-up.json"
    signal_path.parent.mkdir()
    signal = ir_signal.protocol_signal(
        "nec-ext", {"address_low": "7A", "address_high": "00", "command": "1A"})
    signal_path.write_text(json.dumps(signal))
    device = {
        "schema": device_json.PORTABLE_SCHEMA,
        "manufacturer": "Yamaha",
        "model": "RAV16",
        "type": "Receiver",
        "commands": [{"name": "VolumeUp", "label": "VOL+",
                      "hard_key": "VolumeUp", "signal": "signals/volume-up.json"}],
    }
    device_path = tmp_path / "devices" / "rav16.json"
    device_path.parent.mkdir()
    device_path.write_text(json.dumps(device))

    loaded = device_json.load(device_path)
    built = device_json.to_project_device(loaded, "40009001", library=tmp_path)

    assert built["signals"]["VolumeUp"] == signal
    assert built["commands"] == [["VolumeUp", "VOL+", "7A", "1A", "VolumeUp"]]
    assert "protocol" not in built


def test_rc6_mce_has_the_hardware_proven_native_code_lowering():
    from afterglow.backends.harmony_pk.builder.codes import portable_code

    signal = ir_signal.protocol_signal("rc6-mce", {"code": 0x3FF07BEF})
    assert portable_code(signal, 2) == "0x0200F40100000100FFC1EFBC00"


def test_public_v2_supports_inline_waveform_and_backend_opaque_signals(tmp_path):
    wave = ir_signal.waveform([900, -450, 100], carrier_hz=38000)
    opaque = ir_signal.backend_opaque({"harmony-pk": {
        "format": "command-code", "protocol_block_id": "bfd45b094543",
        "code": "0x00010200",
    }})
    device = {
        "schema": device_json.PORTABLE_SCHEMA,
        "manufacturer": "Example", "model": "Mixed", "commands": [
            {"name": "Learned", "signal": wave},
            {"name": "Native", "signal": opaque},
        ],
    }
    built = device_json.to_project_device(device, "40009001", library=tmp_path)

    assert built["signals"] == {"Learned": wave, "Native": opaque}
    assert not ({"protocol", "raw_ir", "raw_codes"} & set(built))


def test_legacy_raw_commands_gain_backend_opaque_signal_evidence():
    source = {
        "schema": device_json.SCHEMA,
        "manufacturer": "Test", "model": "Opaque", "type": "Receiver",
        "protocol": "samsung32-38-0-khz.json", "encoding": {"codec": "nec"},
        "commands": [{
            "name": "VolumeUp", "label": "Volume Up",
            "raw": "0x0000E80301010001020304010101020304",
        }],
    }
    source["protocol"] = "e8f716b9ee19"
    built = device_json.to_project_device(source, "40009001")
    signal = built["signals"]["VolumeUp"]
    assert signal["kind"] == "backend-opaque"
    assert signal["native"]["harmony-pk"]["code"] == source["commands"][0]["raw"]


def test_describable_and_reproducible_are_separate_remote_capabilities():
    remote = remotes.get("harmony-900")
    nec = ir_signal.protocol_signal("nec1", {"address": 1, "command": 2})
    unknown = ir_signal.protocol_signal("some-future-protocol", {"data": 1})
    observed = ir_signal.waveform(
        [100, -100], native={"harmony-pk": {"ssir_carrier_period_ns": 32572}})
    measured = ir_signal.waveform([100, -100], carrier_hz=38000)

    assert remote.ir_strategy(nec) == "native-protocol"
    assert remote.ir_strategy(unknown) == "render-waveform"
    assert remote.ir_strategy(observed) == "native-waveform"
    assert remote.ir_strategy(measured) == "native-waveform"


def test_every_generated_portable_family_uses_native_lifecycle_support():
    remote = remotes.get("harmony-900")
    probes = {
        "nec2": {"address": 1, "command": 2},
        "nec2-ext": {"address_low": 1, "address_high": 2, "command": 3},
        "sony12": {"code": 0x123},
        "sony15": {"code": 0x4567},
        "sony20": {"code": 0xABCDE},
        "jvc16": {"code": 0x1234},
        "rc5-13": {"code": 0x1234},
    }

    for protocol_id, parameters in probes.items():
        assert remote.ir_strategy(
            ir_signal.protocol_signal(protocol_id, parameters)) == "native-protocol"


def test_backend_capability_distinguishes_hardware_anchors_from_vm_validation():
    from afterglow import backends

    remote = remotes.get("harmony-900")
    backend = backends.for_profile(remote)
    anchored = backend.capability(
        ir_signal.protocol_signal("nec1", {"address": 1, "command": 2}), remote)
    vm_only = backend.capability(
        ir_signal.protocol_signal("sony15", {"code": 0x4567}), remote)

    assert anchored["validation"] == "hardware-anchored"
    assert vm_only["validation"] == "vm-validated"
    assert "native" not in anchored["reason"]
    assert "native" not in vm_only["reason"]


def test_pre_rename_harmony_z_waveform_evidence_remains_reproducible():
    remote = remotes.get("harmony-900")
    for old_name in ("harmony-z", "harmony-ziptree"):
        legacy = ir_signal.waveform(
            [100, -100], native={old_name: {"ssir_carrier_period_ns": 32572}})

        assert remote.ir_strategy(legacy) == "native-waveform"
        assert ir_compile.ssir.capture_header(legacy) == (32572).to_bytes(4, "little")


def test_stateless_same_frame_protocol_falls_back_to_harmony_ssir(tmp_path):
    definition = {
        "schema": ir_protocol.SCHEMA,
        "id": "raw-fallback",
        "modulation": {"kind": "carrier", "carrier_hz": 38000},
        "parameters": {"command": {"bits": 1}},
        "bursts": {"zero": [100, -100], "one": [100, -200]},
        "alphabets": {"bits": {"bits_per_symbol": 1,
                      "symbols": {"0": "zero", "1": "one"}}},
        "frames": {"data": {"segments": [{"field": "command"}]}},
        "transmission": {"press": [{"frame": "data", "count": 2}],
                         "hold": [{"frame": "data", "count": 2}], "release": []},
    }
    (tmp_path / "raw-fallback.json").write_text(json.dumps(definition))
    signal = ir_signal.protocol_signal("raw-fallback", {"command": 1})
    device = {"id": "1", "label": "Fallback", "protocol": None,
              "commands": [["Power", "Power", "", "", None]],
              "signals": {"Power": signal}}

    ir_compile.prepare_devices(
        [device], remotes.get("harmony-900"), library=tmp_path)

    assert device["protocol"] is None
    assert device["raw_codes"]["Power"] == "0xFFFF0000"
    assert device["raw_ir"]["0"]["pulses_us"] == [100, -200, 100, -200]


@pytest.mark.parametrize("difference", ["state", "hold", "release"])
def test_raw_fallback_refuses_lifecycle_it_cannot_preserve(tmp_path, difference):
    definition = {
        "schema": ir_protocol.SCHEMA,
        "id": "unsafe-fallback",
        "modulation": {"kind": "carrier", "carrier_hz": 38000},
        "parameters": {},
        "bursts": {"a": [100, -100], "b": [100, -200]},
        "alphabets": {},
        "frames": {"a": {"segments": [{"burst": "a"}]},
                   "b": {"segments": [{"burst": "b"}]}},
        "transmission": {"press": [{"frame": "a"}],
                         "hold": [{"frame": "a"}], "release": []},
    }
    if difference == "state":
        definition["state"] = {"toggle": {"kind": "toggle"}}
    elif difference == "hold":
        definition["transmission"]["hold"] = [{"frame": "b"}]
    else:
        definition["transmission"]["release"] = [{"frame": "b"}]
    (tmp_path / "unsafe-fallback.json").write_text(json.dumps(definition))
    device = {"id": "1", "commands": [["Power", "Power", "", "", None]],
              "signals": {"Power": ir_signal.protocol_signal("unsafe-fallback", {})}}

    with pytest.raises(ValueError, match="state|hold lifecycle|release"):
        ir_compile.prepare_devices(
            [device], remotes.get("harmony-900"), library=tmp_path)


def test_capability_reason_does_not_leak_the_evidence_tier_to_users():
    """`reason` is a table column in the Add Device wizard, one row per command.

    It used to read "portable protocol (vm validated)" - our internal evidence tier -
    which meant adding a 77-command television printed it 77 times. The tier changes
    nothing a user would do: they add the device either way, and pressing the button is
    a faster and better test than any label we could print. It also misleads, because an
    anchor was measured against somebody else's appliance.

    The tier stays in the payload for tooling; this asserts it stays out of the prose.
    """
    from afterglow import ir_signal, remotes
    from afterglow.backends.harmony_pk import backend, mappings

    profile = remotes.get("harmony-900")
    for name in ("nec1", "sony12", "rc5-13"):
        signal = ir_signal.protocol_signal(
            name, {key: 1 for key in
                   ir_protocol.protocol(name)["parameters"]}, name="Probe")
        answer = backend.capability(signal, profile)
        assert answer["supported"]
        assert answer["validation"] == mappings.PROTOCOLS[name]["validation"]
        for tier in mappings.VALIDATION_TIERS:
            assert tier not in answer["reason"], answer
            assert tier.replace("-", " ") not in answer["reason"], answer
