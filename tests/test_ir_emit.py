"""Portable definitions compile into proven native carrier programs."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from afterglow import ir_protocol
from afterglow.backends.harmony_pk import ir_emit, mappings, protocol_json


@pytest.mark.parametrize("protocol_id", sorted(ir_emit.SUPPORTED))
def test_every_supported_portable_definition_enters_the_generated_registry(protocol_id):
    emitted = ir_emit.emit(protocol_id, mappings.protocol(protocol_id))
    stored = protocol_json.catalog()[emitted["id"]]

    assert "unit_us" not in emitted
    assert emitted["pwm_parameter"] == 50
    expected_elements = 1 if protocol_id in (
        "rc5-13", "rc6-mce", "sony12", "sony15", "sony20") else 2
    assert emitted["element_count"] == expected_elements
    assert protocol_json.encode(emitted, 10) == protocol_json.encode(stored, 10)


@pytest.mark.parametrize("protocol_id, block_id", [
    ("nec1", "a7b8a0e6c639"),
    ("samsung32", "e8f716b9ee19"),
    ("rc6-mce", "6bd42e0eea79"),
])
def test_hardware_proven_programs_are_reconstructed_byte_for_byte(protocol_id, block_id):
    assert ir_emit.emit(protocol_id, mappings.protocol(protocol_id))["id"] == block_id


def test_emitter_does_not_read_the_prederived_native_catalogue(monkeypatch):
    monkeypatch.setattr(
        protocol_json, "catalog",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("native catalogue was read")),
    )

    emitted = ir_emit.emit("nec1", mappings.protocol("nec1"))

    assert emitted["id"] == "a7b8a0e6c639"


def test_the_only_protocol_json_the_suite_uses_is_portable():
    """Whatever library is active holds portable definitions and nothing else.

    Nothing is shipped, so the statement is about the library in use: the suite's
    fixtures here, an external database in the field. Either way a native block must
    never be mistaken for a protocol definition.
    """
    from afterglow import ir_protocol

    definitions = sorted(Path(ir_protocol.LIBRARY).glob("*.json"))
    assert definitions, "the active protocol library must not be empty"
    for path in definitions:
        spec = json.loads(path.read_text())
        assert spec.get("schema") == ir_protocol.SCHEMA, path.name
        ir_protocol.validate(spec)

def test_emitter_rejects_a_semantic_revision_its_calibration_does_not_cover():
    definition = deepcopy(ir_protocol.protocol("nec1"))
    definition["bursts"]["leader"] = [9270, -4500]
    library = {"nec1": definition}

    with pytest.raises(ir_emit.NativeEmissionError, match="review and recalibrate"):
        ir_emit.emit("nec1", mappings.protocol("nec1"), library=library)


def test_non_semantic_protocol_metadata_does_not_invalidate_calibration():
    definition = deepcopy(ir_protocol.protocol("nec1"))
    definition["name"] = "A clearer display name"
    definition["provenance"] = {"note": "prose does not change the waveform"}

    emitted = ir_emit.emit(
        "nec1", mappings.protocol("nec1"), library={"nec1": definition})

    assert emitted["id"] == "a7b8a0e6c639"


@pytest.mark.parametrize("protocol_id", sorted(ir_emit.SUPPORTED))
def test_emitter_verification_includes_zero_one_and_mixed_parameter_edges(protocol_id):
    definition = ir_protocol.protocol(protocol_id)
    vectors = dict(ir_emit._parameter_vectors(definition))
    maximums = {name: (1 << parameter["bits"]) - 1
                for name, parameter in definition["parameters"].items()}

    assert vectors["all-zero"] == {name: 0 for name in definition["parameters"]}
    assert vectors["all-one"] == maximums
    assert "mixed" in vectors


def test_every_emitter_declares_its_portable_revision_and_evidence_tier():
    for protocol_id in ir_emit.SUPPORTED:
        definition = ir_protocol.protocol(protocol_id)
        mapping = mappings.protocol(protocol_id)
        assert mapping["portable_signature"] == ir_protocol.semantic_fingerprint(definition)
        assert mapping["validation"] in mappings.VALIDATION_TIERS


def test_native_json_separates_pwm_byte_from_element_count():
    for name, spec in protocol_json.catalog().items():
        body = bytes.fromhex(spec["body_hex"])
        assert spec["pwm_parameter"] == body[5] == 50, name
        assert spec["element_count"] == body[6], name
        assert "unit_us" not in spec, name


def test_legacy_overlapping_unit_field_remains_read_compatible():
    current = protocol_json.catalog()["a7b8a0e6c639"]
    legacy = deepcopy(current)
    legacy["unit_us"] = legacy.pop("pwm_parameter") | legacy.pop("element_count") << 8

    assert protocol_json.encode(legacy, 10) == protocol_json.encode(current, 10)


def test_validation_tiers_are_a_closed_ordered_vocabulary():
    """Every lowering declares one of the known tiers, and they mean different things.

    The tier is what the UI shows a user deciding whether to trust a command, so an
    unknown or invented value is worse than a pessimistic one. `vm-validated` is the
    floor because our emitter and our VM are both our code: agreement between them
    cannot detect a systematic error in the port. `emission-measured` means an
    independent probe captured the real infrared and the structure matched, which rules
    that out but says nothing about carrier frequency (a demodulator strips it) or about
    any appliance responding. `hardware-anchored` is both, plus a byte-exact donor block.
    """
    from afterglow.backends.harmony_pk import mappings

    assert mappings.VALIDATION_TIERS == (
        "vm-validated", "emission-measured", "hardware-anchored")
    for name, mapping in mappings.PROTOCOLS.items():
        assert mapping.get("validation") in mappings.VALIDATION_TIERS, name

    # A family with no proven block id cannot be hardware-anchored: that tier's meaning
    # includes reproducing a donor block byte-for-byte.
    for name, mapping in mappings.PROTOCOLS.items():
        if mapping["validation"] == "hardware-anchored":
            assert mapping.get("block_id"), (
                f"{name} claims a hardware anchor but names no proven block")


def test_bench_measured_families_are_recorded_as_such():
    """Guards the bench result against a silent downgrade or overclaim.

    These four were captured off a real Harmony 900 and matched their portable
    definitions, including JVC's leaderless hold frame and RC5's toggle flipping between
    presses. `sony15` was not on the bench config and must stay `vm-validated`;
    promoting it by association is the drift this test exists to stop.
    """
    from afterglow.backends.harmony_pk import mappings

    for name in ("sony12", "sony20", "jvc16", "rc5-13"):
        assert mappings.PROTOCOLS[name]["validation"] == "emission-measured", name
    for name in ("sony15", "nec2", "nec2-ext"):
        assert mappings.PROTOCOLS[name]["validation"] == "vm-validated", (
            f"{name} was never measured on hardware")


GENERIC_EXACT = {"sony12": ["data"], "sony15": ["data"], "sony20": ["data"],
                 "rc5-13": ["data"]}


def test_generic_builder_reproduces_hand_written_blocks_exactly():
    """The generic path must derive what a hand-written builder was doing.

    These four are the check that the generic element layout is *right* rather than
    merely plausible: given only the portable definition and the carrier, it produces
    byte-identical blocks to the hand-written builders, with no calibration input. If
    this ever diverges, the generic layout has drifted and every protocol emitted through
    it is suspect - not just these.

    RC5 is the one that matters most, because it carries sender state. Its toggle sits
    between two data fields, and the element header's toggle byte (1) is *derived* from
    the segment's bit offset rather than hardcoded - the same derivation gives RC6 its
    14. Getting that wrong would transmit a valid-looking frame with the toggle in the
    wrong place, which no software check downstream would catch.

    NEC, Samsung and RC6 deliberately do NOT match: they carry measured timings (an 8990
    us leader where the definition says 9000) and a pinned `block_id` tying them to a
    hardware-proven block, so they keep their own builders until calibration is wired
    into the generic path.
    """
    import hashlib

    from afterglow import ir_protocol
    from afterglow.backends.harmony_pk import irproto

    for name, frames in GENERIC_EXACT.items():
        mapping = mappings.protocol(name)
        definition = ir_protocol.protocol(name)
        carrier = definition["modulation"]["carrier_hz"]
        body, pointers = ir_emit._generic_body(
            definition, frames, period_ns=round(1_000_000_000 / carrier))
        spec = {
            "schema": protocol_json.SCHEMA, "backend": "harmony-pk", "id": "pending",
            "name": definition["name"], "carrier_period_ns": round(1e9 / carrier),
            "pwm_parameter": ir_emit.PWM_PARAMETER,
            "element_count": len(frames), "flag": 1,
            "size": len(body), "pointer_fields": list(pointers), "body_hex": body.hex(),
        }
        generic = hashlib.sha256(protocol_json.encode(
            spec, position=irproto.CANON_POS)).hexdigest()[:12]
        assert generic == ir_emit.emit(name, mapping)["id"], name


def test_generic_builder_derives_toggle_positions_from_the_definition():
    """Sender state becomes an element toggle byte at its own bit offset.

    RC5's toggle follows one data bit, RC6's follows fourteen, and both numbers come out
    of the segment list rather than a table. Across the Logitech corpus this one
    construct accounted for 184,319 of the 185,156 commands the generic path could not
    emit before this.
    """
    from afterglow import ir_protocol

    expected = {"rc5-13": (1, 0xFF), "rc6-mce": (14, 0xFF)}
    for name, toggles in expected.items():
        layout = ir_emit._frame_layout(ir_protocol.protocol(name), "data")
        assert layout["toggles"] == toggles, name

    # A frame with no sender state must declare no toggle, or the firmware would
    # substitute a bit into ordinary payload.
    layout = ir_emit._frame_layout(ir_protocol.protocol("sony12"), "data")
    assert layout["toggles"] == (0xFF, 0xFF)


def test_emit_generic_passes_its_own_gate_for_every_shipped_family():
    """Exercise the *combined* path, which is what was never tested.

    `_generic_body` and `generic_code` were each validated in isolation, with element
    orders and repeat counts supplied by hand, and that was reported as "both halves
    proven". Calling `emit_generic` - the function that actually composes them - failed
    for five families. The isolated tests could not catch it because the fault was in the
    seam: the verifier compared one native stage against a whole multi-frame press.

    Any protocol this backend ships must survive the integrated path, or the generic
    compiler cannot be trusted with one nobody has hand-written.
    """
    from afterglow import ir_protocol

    for name in mappings.PROTOCOLS:
        ir_emit.emit_generic(ir_protocol.protocol(name))


@pytest.mark.parametrize("with_hold, stages", [
    (True, (3, 3, 3, 5)),
    (False, (2, 5)),
])
def test_generic_gate_compiles_release_as_native_stage_five(with_hold, stages):
    """The finish frame runs after every required press/repeat execution."""
    import copy

    from afterglow import ir_protocol
    from afterglow.backends.harmony_pk import ir_vm
    from afterglow.backends.harmony_pk.builder import codes

    definition = copy.deepcopy(ir_protocol.protocol("sony12"))
    if not with_hold:
        definition["transmission"]["hold"] = []
    definition["transmission"]["release"] = [{"frame": "data"}]
    spec = ir_emit.emit_generic(definition)
    parameters = {"code": 0x5A5}
    code = codes.generic_code(
        definition, ir_emit.element_order(definition), parameters, 0)

    result = ir_vm.simulate_transmission(protocol_json.assemble([spec]), code)

    assert result.sequence_stages == stages
    assert result.sequence_elements[-1] == (0,)


def test_generic_gate_rejects_a_compiler_that_drops_sender_state(monkeypatch):
    """The gate observes the VM output, so an ignored RC5 toggle cannot certify itself."""
    original = ir_emit._frame_layout

    def without_toggle(definition, frame_name):
        layout = original(definition, frame_name)
        return {**layout, "toggles": (0xFF, 0xFF)}

    monkeypatch.setattr(ir_emit, "_frame_layout", without_toggle)
    with pytest.raises(ir_emit.NativeEmissionError, match="pulse"):
        ir_emit.emit_generic(ir_protocol.protocol("rc5-13"))


def test_generic_gate_checks_the_complete_sony_press_count():
    """Sony's portable press is three frames; one plausible frame is not enough."""
    definition = ir_protocol.protocol("sony12")
    ir_emit.emit_generic(definition)

    for wrong_count in (0, 4):
        with pytest.raises(ir_emit.NativeEmissionError, match=r"press .* expected 78"):
            ir_emit.emit_generic(definition, minimum_repeats=wrong_count)


def test_vm_reports_the_elements_the_code_actually_executes():
    """JVC proves that one native stage can execute more than one block element."""
    from afterglow.backends.harmony_pk import ir_vm
    from afterglow.backends.harmony_pk.builder import codes

    definition = ir_protocol.protocol("jvc16")
    order = ir_emit.element_order(definition)
    spec = ir_emit.emit_generic(definition, verify=False)
    payload = protocol_json.assemble([spec])
    code = codes.generic_code(
        definition, order, {"code": 0x1234}, 0)
    simulation = ir_vm.simulate_transmission(payload, code, held_replays=1)

    assert simulation.sequence_elements == ((0, 1), (1,), (1,))


def _local_payload_protocol():
    return {
        "schema": ir_protocol.SCHEMA,
        "id": "test-local-payload",
        "modulation": {"kind": "carrier", "carrier_hz": 38_000},
        "parameters": {"code0": {"bits": 2}, "code1": {"bits": 2}},
        "bursts": {"zero": [100, -100], "one": [100, -300]},
        "alphabets": {"bits": {"bits_per_symbol": 1,
                      "symbols": {"0": "zero", "1": "one"}}},
        "frames": {
            "data": {
                "parameters": {"payload": {"bits": 2}},
                "segments": [{"field": "payload", "order": "msb"}],
            },
            "alternate": {
                "parameters": {"payload": {"bits": 2}},
                "segments": [{"field": "payload", "order": "msb"}],
            },
        },
        "transmission": {
            "press": [
                {"frame": "data", "bind": {"payload": "code0"}},
                {"frame": "data", "bind": {"payload": "code1"}},
            ],
            "hold": [],
            "release": [],
        },
    }


def test_generic_compiler_keeps_bound_values_on_each_occurrence():
    """One frame with Code0 then Code1 must remain two differently populated elements."""
    from afterglow.backends.harmony_pk.builder import codes

    definition = _local_payload_protocol()
    parameters = {"code0": 1, "code1": 2}

    ir_emit.emit_generic(definition, parameters=parameters)
    plan = codes.transmission_plan(definition, parameters)

    occurrences = plan["sections"][0]["occurrences"]
    assert plan["sections"][0]["stage"] == 2
    assert [item["values"]["payload"] for item in occurrences] == [1, 2]


def test_generic_compiler_accepts_a_command_override_using_a_nondefault_frame():
    """A protocol block contains every frame, including ones selected only by commands."""
    definition = _local_payload_protocol()
    transmission = {
        "press": [
            {"frame": "alternate", "arguments": {"payload": 1}, "count": 2},
            {"frame": "data", "arguments": {"payload": 2}},
        ],
        "hold": [],
        "release": [],
    }

    spec = ir_emit.emit_generic(
        definition, parameters={}, transmission=transmission)
    assert spec["element_count"] == 2

    from afterglow.backends.harmony_pk.builder import codes
    plan = codes.transmission_plan(definition, {}, transmission=transmission)
    occurrences = plan["sections"][0]["occurrences"]
    assert [item["frame"] for item in occurrences] == [
        "alternate", "alternate", "data"]
    assert [item["values"]["payload"] for item in occurrences] == [1, 1, 2]


def test_generic_builder_compiles_constants_with_the_named_default_alphabet():
    """A constant is data, and an omitted alphabet means `bits`, not first-in-object."""
    definition = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-constant-default-alphabet",
        "modulation": {"kind": "carrier", "carrier_hz": 36_000},
        "parameters": {},
        "bursts": {
            "wrong-zero": [900, -900], "wrong-one": [900, -1800],
            "zero": [100, -100], "one": [100, -300],
        },
        "alphabets": {
            "wrong": {"bits_per_symbol": 1,
                      "symbols": {"0": "wrong-zero", "1": "wrong-one"}},
            "bits": {"bits_per_symbol": 1,
                     "symbols": {"0": "zero", "1": "one"}},
        },
        "frames": {"press": {"segments": [
            {"constant": 2, "bits": 2, "order": "msb"},
        ]}},
    }

    ir_emit.emit_generic(definition, parameters={})


def test_a_carrier_burst_longer_than_one_word_splits_instead_of_refusing():
    """A long mark splits across words exactly as a long space does.

    A carrier burst that long is a real signal. `Zenith 11 Bit Quad` symbol 2 is a
    single 99,999 us mark, and Logitech's own Pronto for a command selecting it opens
    with a 100,484 us mark - that burst merged with the 484 following it. Refusing costs
    three protocol families and 322 archive commands, all of which agree with Logitech's
    Pronto once emitted.

    Splitting is invisible on the wire because adjacent words with the same carrier state
    concatenate, which is what `normalise_pulses` folds back when comparing.
    """
    from afterglow.backends.harmony_pk import ir_emit, ir_vm

    words = ir_emit._even_mark(99999)
    assert all(word > 0 for word in words), "a split mark stays a mark"
    assert all(word <= ir_vm.MAX_GAP_US for word in words), "every word must fit"
    assert sum(words) == 99999, "splitting must not change the duration"
    assert ir_vm.normalise_pulses(words) == (99999,), (
        "the split must be invisible once carrier-state transitions are compared")
    # Marks and spaces split the same way apart from sign.
    assert words == tuple(-word for word in ir_emit._even_space(99999))
