"""Protocols, raw waveforms, and the codes that point at them.

The rule underneath all of this: **an index is a position, never an identity**. A
protocol's index is where it sits in that config's table; a waveform's index is where it
sits in `SsIr.bin`. Both change when a config is rebuilt, and every bug in this area came
from treating one of them as though it meant something.
"""
import struct

import pytest

from afterglow import ir_signal
from afterglow.backends.harmony_pk import irproto, protocol_json, ssir


@pytest.fixture(scope="module")
def catalog():
    found = protocol_json.catalog()
    if not found:
        pytest.skip("no protocol library")
    return found


def test_protocol_roundtrip_is_byte_exact(catalog):
    for block_id, spec in catalog.items():
        block = protocol_json.encode(spec, irproto.CANON_POS)
        again = protocol_json.decode(block, block_id=block_id,
                                     offset_fields=tuple(spec["pointer_fields"]))
        assert protocol_json.encode(again, irproto.CANON_POS) == block, block_id


def test_protocol_generates_correctly_at_any_position(catalog):
    """Encoding at a position must equal relocating there.

    This is what let the binary block library be deleted: a block is *generated* where it
    lands, so there is no relocation step that can be got wrong.
    """
    for block_id, spec in catalog.items():
        pointers = tuple(spec["pointer_fields"])
        canonical = protocol_json.encode(spec, irproto.CANON_POS)
        for position in (10, 27, 64, 133, 512):
            assert protocol_json.encode(spec, position) == irproto.relocate_block(
                canonical, irproto.CANON_POS, position, pointers), f"{block_id}@{position}"


def test_assembled_irproto_reparses(catalog):
    chosen = list(catalog.values())[:3]
    payload = protocol_json.assemble(chosen)
    blocks, starts = irproto.parse_proto(payload)
    assert len(blocks) == len(chosen)
    for spec, block, position in zip(chosen, blocks, starts):
        assert protocol_json.encode(spec, position) == block


def test_import_materializes_a_shared_pulse_table_into_transient_evidence():
    from afterglow.backends.harmony_pk import ir_emit, ir_vm, mappings
    from afterglow.backends.harmony_pk.builder import codes

    generated = ir_emit.emit("rc6-mce", mappings.protocol("rc6-mce"))
    payload = protocol_json.assemble([generated])
    blocks, starts = irproto.parse_proto(payload)
    block = bytearray(blocks[0])
    position = starts[0]

    source = irproto.PROTOCOL_BASE + struct.unpack_from("<H", block, 19)[0]
    alphabet = payload[source:source + 8]
    apparent_block = block[:52]
    external = position + len(apparent_block) + 20
    struct.pack_into("<H", apparent_block, 19, external - irproto.PROTOCOL_BASE)
    shared_payload = bytearray(payload[:position]) + apparent_block
    shared_payload.extend(b"\0" * (external - len(shared_payload)))
    shared_payload.extend(alphabet)

    extracted = protocol_json.extract_definition(
        bytes(apparent_block), bytes(shared_payload), position)
    code = codes.rc6_mce_code(0x3FF07BEF)
    original = ir_vm.simulate_transmission(
        bytes(shared_payload), code, toggle_state=1, held_replays=1)
    rebuilt = ir_vm.simulate_transmission(
        protocol_json.assemble([extracted]), code, toggle_state=1, held_replays=1)

    assert extracted["materialized_external_data"] is True
    assert extracted["id"] == generated["id"]
    assert original.sequence_stages == rebuilt.sequence_stages
    assert ir_vm.normalise_pulses(original.pulses_us) == \
        ir_vm.normalise_pulses(rebuilt.pulses_us)


def test_every_library_protocol_has_one_file():
    """Two files for one protocol means one is silently ignored."""
    from afterglow import library
    assert library.duplicate_ids() == {}


def test_assumed_pointers_are_declared(catalog):
    """A guess must never read as a measurement."""
    for block_id, spec in catalog.items():
        if spec.get("pointers") == "assumed":
            assert spec["pointer_fields"] == list(irproto.NEC_OFFSET_FIELDS)


# raw waveforms
def test_raw_code_detection():
    assert ssir.is_raw("0xFFFF0A00")
    assert ssir.raw_index("0xFFFF0A00") == 10
    assert ssir.make_code(10) == "0xFFFF0A00"
    assert not ssir.is_raw("0x0400F401030001002A4C028A008800")
    assert ssir.raw_index("0x0400F4") is None


def test_empty_waveform_table_is_valid():
    assert ssir.parse(ssir.build([])) == []


def test_waveform_table_roundtrip():
    entries = [bytes(range(8)) * 3, bytes(range(16))]
    assert ssir.parse(ssir.build(entries)) == entries


def test_capture_roundtrip_is_byte_exact():
    blob = bytes.fromhex("3c7f0000") + int.to_bytes(3, 2, "little") + b"".join(
        int.to_bytes(w, 2, "little") for w in (0x80E4, 0x092C, 0x8100))
    assert ssir.encode_capture(ssir.decode_capture(blob)) == blob


def test_capture_pulses_are_signed_microseconds():
    """Positive is a mark, negative a space - the LIRC/Flipper convention."""
    blob = bytes.fromhex("00000000") + int.to_bytes(2, 2, "little") + b"".join(
        int.to_bytes(w, 2, "little") for w in (0x8064, 0x0064))
    capture = ssir.decode_capture(blob)
    assert capture["pulses_us"] == [100, -100]
    assert "carrier_hz" not in capture
    assert ir_signal.statistics(capture) == {"pulse_count": 2, "total_us": 200}


def test_capture_decodes_its_native_carrier_period():
    period_ns = 26355
    blob = period_ns.to_bytes(4, "little") + b"\x02\x00\x64\x80\x64\x00"
    capture = ssir.decode_capture(blob)
    assert capture["carrier_hz"] == round(1e9 / period_ns)
    assert ssir.encode_capture(capture) == blob


def test_portable_waveform_does_not_serialize_derived_values():
    signal = ir_signal.waveform([100, -200], carrier_hz=38000)
    assert signal["schema"] == ir_signal.SCHEMA and signal["kind"] == "waveform"
    assert "pulse_count" not in signal and "total_us" not in signal


def test_ssir_never_truncates_an_oversized_duration():
    """The invariant is that a duration is never silently shortened.

    An SsIr word holds 15 bits, and the format represents a longer space as
    **consecutive off words**, which real Logitech entries do. Refusing an oversized
    space instead costs 296,272 archive commands, 27.7% of everything the Harmony 900
    would otherwise not transmit.

    Dropping the space is known-wrong: an RC6 waveform with its final silence discarded
    fails against a real MCE receiver while every software check passes, because the
    lead-out separates one frame from the next. Split it, never shorten it, never drop
    it.
    """
    signal = ir_signal.waveform([100, -75838], carrier_hz=38000)
    decoded = ssir.decode_capture(ssir.encode_capture(signal))
    assert decoded["pulses_us"] == [100, -32767, -32767, -10304]
    assert sum(map(abs, decoded["pulses_us"])) == 100 + 75838
    # Sign is preserved: the tail is silence, not a 32 ms carrier burst.
    assert all(pulse < 0 for pulse in decoded["pulses_us"][1:])


def test_ssir_still_refuses_an_impossible_mark():
    """A carrier burst longer than 32.767 ms is not a real signal; do not invent one.

    Marks are deliberately not chunked. Two adjacent on words would read as one
    continuous burst, so silently producing that from a bad input would be exactly the
    "plausible and wrong" output this project refuses to emit.
    """
    signal = ir_signal.waveform([40000, -600], carrier_hz=38000)
    with pytest.raises(ValueError, match="15 bits"):
        ssir.encode_capture(signal)


def test_ssir_word_budget_counts_words_after_splitting():
    """The 0x7FFF limit applies to stored words, not to input pulses."""
    signal = ir_signal.waveform([100, -32767 * 40000], carrier_hz=38000)
    with pytest.raises(ValueError, match="pulse words"):
        ssir.encode_capture(signal)


def test_legacy_capture_migration_keeps_the_original_ssir_bytes():
    legacy = {"schema": ir_signal.LEGACY_CAPTURE_SCHEMA, "name": "old",
              "header_hex": "3c7f0000", "pulse_count": 3,
              "total_us": 500, "pulses_us": [-2, 100, -400]}
    original = bytes.fromhex("3c7f0000020064809001")
    migrated = ssir.normalise_signal(legacy)
    assert migrated["pulses_us"] == [100, -400]
    assert ssir.encode_capture(migrated) == original


def test_collect_renumbers_and_deduplicates():
    """Waveforms are renumbered to their new position, and an identical waveform used
    twice is stored once."""
    prefix = int.to_bytes(26315, 4, "little")
    wave_a = ssir.decode_capture(prefix + b"\x01\x00\x64\x80")
    wave_b = ssir.decode_capture(prefix + b"\x01\x00\xc8\x80")
    spec = {"id": "1",
            "raw_codes": {"A": ssir.make_code(5), "B": ssir.make_code(9),
                          "C": ssir.make_code(5)},
            "raw_ir": {"5": wave_a, "9": wave_b}}
    entries, remap = ssir.collect([spec])
    assert len(entries) == 2, "the same waveform was stored twice"
    assert remap[("1", "A")] == remap[("1", "C")]
    assert {ssir.raw_index(c) for c in remap.values()} == {0, 1}
