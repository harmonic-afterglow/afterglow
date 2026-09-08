"""Lower portable IR meaning into Harmony One waveform and carrier records.

This module stops at native, relocatable pieces. Object indexes and placement in a GSPM
image belong to later build stages and must not be inferred from waveform bytes.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from dataclasses import dataclass

from ... import ir_protocol, ir_signal


MARK = 0x8000
MAX_DURATION_US = 0x7FFF
DEFAULT_ENTRY_US = 50_000
CLOSE_US = 1


@dataclass(frozen=True)
class LoweredSignal:
    """Relocatable native pieces for one command record."""

    carrier_period_ns: int
    carrier_half_period_ns: int
    press_waveform: bytes
    hold_waveform: bytes | None
    release_waveform: bytes | None


def split_space(duration_us: int) -> list[int]:
    """Split a space using the distribution measured in Harmony One images."""
    if isinstance(duration_us, bool) or not isinstance(duration_us, int):
        raise ValueError("Harmony One IR durations must be integers")
    if duration_us <= 0:
        raise ValueError("Harmony One IR durations must be positive")
    if duration_us <= MAX_DURATION_US:
        return [duration_us]

    full, remainder = divmod(duration_us, MAX_DURATION_US)
    if not remainder:
        return [MAX_DURATION_US] * full
    if remainder >= MAX_DURATION_US // 2:
        return [MAX_DURATION_US] * full + [remainder]

    # The native producer avoids a short final word by sharing it with the previous
    # full word. Four independently observed lead-in lengths follow this rule.
    combined = MAX_DURATION_US + remainder
    return [MAX_DURATION_US] * (full - 1) + [combined // 2, combined - combined // 2]


def _normalise_pulses(pulses_us) -> list[int]:
    out: list[int] = []
    for pulse in pulses_us:
        if isinstance(pulse, bool) or not isinstance(pulse, int) or pulse == 0:
            raise ValueError("Harmony One waveform pulses must be non-zero integers")
        if out and (out[-1] > 0) == (pulse > 0):
            out[-1] += pulse
        else:
            out.append(pulse)
    return out


def encode_pulses(pulses_us) -> list[int]:
    """Encode signed portable pulses as native little-endian u16 values."""
    words = []
    for pulse in _normalise_pulses(pulses_us):
        if pulse > 0:
            if pulse > MAX_DURATION_US:
                raise ValueError(
                    f"Harmony One mark {pulse} us exceeds the measured 15-bit field")
            words.append(MARK | pulse)
        else:
            words.extend(split_space(-pulse))
    return words


def _bytes(words: list[int]) -> bytes:
    return b"".join(word.to_bytes(2, "little") for word in words)


def encode_waveform(pulses_us, *, entry_us: int | None) -> bytes:
    """Encode one complete native waveform, including its short terminator."""
    pulses = _normalise_pulses(pulses_us)
    if not pulses or pulses[0] < 0:
        raise ValueError("Harmony One command waveforms must begin with a mark")
    if pulses[-1] > 0:
        raise ValueError(
            "Harmony One command waveforms need a final protocol gap before termination")

    words = []
    if entry_us is not None:
        entry = split_space(entry_us)
        if entry[0] != MAX_DURATION_US:
            raise ValueError(
                "Harmony One press lead-in must begin with the measured 0x7fff word")
        words.extend(entry)
    words.extend(encode_pulses(pulses))
    # This deliberately remains a second consecutive space. Firmware readers use the
    # short space following the final protocol gap as the waveform terminator.
    words.append(CLOSE_US)
    return _bytes(words)


def encode_release_waveform(pulses_us) -> bytes:
    """Encode the measured mark-ending release form and its zero sentinel."""
    pulses = _normalise_pulses(pulses_us)
    if not pulses or pulses[0] < 0:
        raise ValueError("Harmony One release waveforms must begin with a mark")
    if pulses[-1] < 0:
        raise ValueError("Harmony One release waveforms must end with a mark")
    return _bytes(encode_pulses(pulses) + [0])


def carrier_fields(carrier_hz: int) -> tuple[int, int]:
    """Convert a carrier to the truncated nanosecond fields used by the One."""
    if isinstance(carrier_hz, bool) or not isinstance(carrier_hz, int) or carrier_hz <= 0:
        raise ValueError("Harmony One commands need a positive integer carrier")
    period = 1_000_000_000 // carrier_hz
    if not 0 < period <= 0xFFFFFF:
        raise ValueError("Harmony One carrier period does not fit its native u24 field")
    return period, period // 2


def _waveform_phases(
        signal: dict) -> tuple[list[int], list[int] | None, list[int] | None]:
    pulses = signal["pulses_us"]
    sections = signal.get("sections")
    if not sections:
        return pulses, None, None
    intro_count = sections["intro_pulses"]
    repeat_count = sections["repeat_pulses"]
    release_count = sections.get("release_pulses", 0)
    intro = pulses[:intro_count]
    repeat = pulses[intro_count:intro_count + repeat_count]
    release = pulses[
        intro_count + repeat_count:intro_count + repeat_count + release_count]
    # A repeat-only Pronto-style signal must still emit once on initial press.
    return (intro or repeat), (repeat or None), (release or None)


def lower(signal: dict, *, library=None, entry_us: int = DEFAULT_ENTRY_US) -> LoweredSignal:
    """Lower a portable signal without assigning addresses or mutating a GSPM image."""
    ir_signal.validate(signal)
    if signal["kind"] == "backend-opaque":
        raise ValueError("an opaque command has no portable IR meaning to lower")

    if signal["kind"] == "waveform":
        carrier = signal.get("carrier_hz")
        if carrier is None:
            raise ValueError("Harmony One cannot lower a waveform without a carrier")
        press_pulses, hold_pulses, release_pulses = _waveform_phases(signal)
    else:
        definition = ir_protocol.protocol(signal["protocol"], library)
        if definition.get("state"):
            raise ValueError(
                f"protocol {signal['protocol']!r} has sender state; Harmony One state "
                "selection is not yet mapped")
        modulation = definition["modulation"]
        if modulation["kind"] != "carrier":
            raise ValueError(
                f"protocol {signal['protocol']!r} is unmodulated; Harmony One command "
                "records require a measured carrier")
        carrier = modulation["carrier_hz"]
        press, state = ir_protocol.render_transmission(
            signal, phase="press", library=library)
        hold, state = ir_protocol.render_transmission(
            signal, phase="hold", state=state, library=library)
        release, _state = ir_protocol.render_transmission(
            signal, phase="release", state=state, library=library)
        if press is None:
            raise ValueError(f"protocol {signal['protocol']!r} has an empty press phase")
        press_pulses = list(press["pulses_us"])
        hold_pulses = list(hold["pulses_us"]) if hold is not None else None
        release_pulses = list(release["pulses_us"]) if release is not None else None
        minimum = ir_protocol.hold_minimum(definition, signal.get("transmission"))
        if minimum and hold_pulses is None:
            raise ValueError(
                f"protocol {signal['protocol']!r} requires hold frames but has none")
        for _ in range(minimum):
            press_pulses.extend(hold_pulses or [])

    period, half = carrier_fields(carrier)
    return LoweredSignal(
        carrier_period_ns=period,
        carrier_half_period_ns=half,
        press_waveform=encode_waveform(press_pulses, entry_us=entry_us),
        hold_waveform=(encode_waveform(hold_pulses, entry_us=None)
                       if hold_pulses is not None else None),
        release_waveform=(encode_release_waveform(release_pulses)
                          if release_pulses is not None else None),
    )
