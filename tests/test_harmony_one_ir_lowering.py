"""Harmony One IR lowering preserves portable lifecycle meaning in native pieces."""

from __future__ import annotations

import json
import struct

import pytest

from afterglow import ir_protocol, ir_signal
from afterglow.backends.harmony_one import gspm, ir_lowering, records


def words(payload: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(payload) // 2}H", payload))


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (50_000, [32767, 17233]),
        (100_000, [32767, 32767, 17233, 17233]),
        (300_000, [32767] * 8 + [18932, 18932]),
        (500_000, [32767] * 14 + [20631, 20631]),
        (40_222, [20111, 20111]),
        (96_077, [32767, 32767, 30543]),
    ],
)
def test_long_spaces_follow_the_distribution_measured_on_the_one(duration, expected):
    assert ir_lowering.split_space(duration) == expected


def test_a_portable_press_and_hold_become_separate_one_waveforms():
    signal = ir_signal.protocol_signal(
        "nec1", {"address": 0x12, "command": 0x34}, name="Power")

    lowered = ir_lowering.lower(signal)
    press, state = ir_protocol.render_transmission(signal, phase="press")
    hold, _state = ir_protocol.render_transmission(signal, phase="hold", state=state)

    assert lowered.carrier_period_ns == 26315
    assert lowered.carrier_half_period_ns == 13157
    assert words(lowered.press_waveform) == (
        [32767, 17233]
        + ir_lowering.encode_pulses(press["pulses_us"])
        + [ir_lowering.CLOSE_US]
    )
    assert words(lowered.hold_waveform) == (
        ir_lowering.encode_pulses(hold["pulses_us"])
        + [ir_lowering.CLOSE_US]
    )
    assert lowered.release_waveform is None


def test_a_minimum_hold_count_is_materialised_in_the_press_waveform():
    signal = ir_signal.protocol_signal(
        "nec1", {"address": 1, "command": 2},
        transmission={
            "press": [{"frame": "press"}],
            "hold": [{"frame": "repeat"}],
            "release": [],
            "hold_minimum": 2,
        },
    )
    definition = ir_protocol.protocol("nec1")
    press, state = ir_protocol.render_transmission(signal, phase="press")
    hold, _state = ir_protocol.render_transmission(signal, phase="hold", state=state)

    lowered = ir_lowering.lower(signal)

    expected = press["pulses_us"] + hold["pulses_us"] * 2
    assert words(lowered.press_waveform)[2:-1] == ir_lowering.encode_pulses(expected)
    assert ir_protocol.hold_minimum(definition, signal["transmission"]) == 2


def test_waveform_intro_and_repeat_sections_use_the_two_native_slots():
    signal = ir_signal.waveform(
        [9000, -4500, 560, -40_000, 2400, -42_600],
        carrier_hz=38_000,
        sections={"intro_pulses": 4, "repeat_pulses": 2},
    )

    lowered = ir_lowering.lower(signal)

    assert words(lowered.press_waveform)[2:-1] == ir_lowering.encode_pulses(
        signal["pulses_us"][:4])
    assert words(lowered.hold_waveform)[:-1] == ir_lowering.encode_pulses(
        signal["pulses_us"][4:])


def test_a_portable_release_section_uses_the_zero_terminated_third_slot():
    signal = ir_signal.waveform(
        [9000, -40_000, 560, -40_000, 2795, -270, 303],
        carrier_hz=36_000,
        sections={"intro_pulses": 2, "repeat_pulses": 2, "release_pulses": 3},
    )

    lowered = ir_lowering.lower(signal)

    assert words(lowered.release_waveform) == [
        0x8000 | 2795, 270, 0x8000 | 303, 0,
    ]


def test_a_protocol_release_recipe_uses_the_zero_terminated_third_slot(tmp_path):
    definition = {
        "schema": ir_protocol.SCHEMA,
        "id": "test-release",
        "modulation": {"kind": "carrier", "carrier_hz": 36_000},
        "parameters": {},
        "bursts": {"key": [900, -1000], "finish": [300]},
        "alphabets": {},
        "frames": {
            "key": {"segments": [{"burst": "key"}]},
            "finish": {"segments": [{"burst": "finish"}]},
        },
        "transmission": {
            "press": [{"frame": "key"}],
            "hold": [],
            "release": [{"frame": "finish"}],
        },
    }
    (tmp_path / "test-release.json").write_text(json.dumps(definition))
    signal = ir_signal.protocol_signal("test-release", {})

    lowered = ir_lowering.lower(signal, library=tmp_path)

    assert words(lowered.release_waveform) == [0x8000 | 300, 0]


def test_toggle_protocols_wait_for_a_native_state_mapping():
    signal = ir_signal.protocol_signal("rc5-13", {"code": 0x123})

    with pytest.raises(ValueError, match="sender state"):
        ir_lowering.lower(signal)


def test_marks_are_not_silently_truncated_to_the_native_field():
    signal = ir_signal.waveform([40_000, -10_000], carrier_hz=38_000)

    with pytest.raises(ValueError, match="mark 40000"):
        ir_lowering.lower(signal)


def test_lowered_carrier_and_placed_waveforms_form_the_exact_command_record():
    signal = ir_signal.protocol_signal("sony12", {"code": 0xABC})
    lowered = ir_lowering.lower(signal)

    record = records.command_record(
        0x230, 0x260, 0x300,
        lowered.carrier_period_ns, lowered.carrier_half_period_ns,
        release_offset=0x340,
    )

    assert len(record) == 25
    assert record[:5] == b"\x01\x00\x00\x00\x00"
    assert int.from_bytes(record[5:8], "little") == 25_000
    assert int.from_bytes(record[8:11], "little") == 12_500
    assert record[11] == record[15] == 1
    assert int.from_bytes(record[12:15], "little") == gspm.BASE + 0x234
    assert int.from_bytes(record[16:19], "little") == gspm.BASE + 0x260
    assert int.from_bytes(record[19:22], "little") == gspm.BASE + 0x300
    assert int.from_bytes(record[22:], "little") == gspm.BASE + 0x340


def test_a_command_object_retains_both_native_ids_and_tags():
    assert records.command_object(0x0203, 0x0201) == b"\x02\x03\x02\x7d\x01\x02\x7c"


def test_command_records_refuse_unmeasured_flags_and_inconsistent_carriers():
    with pytest.raises(ValueError, match="unknown Harmony One command flag"):
        records.command_record(0x100, 0x200, None, 26315, 13157, flag=2)
    with pytest.raises(ValueError, match="half-period"):
        records.command_record(0x100, 0x200, None, 26315, 13158)
