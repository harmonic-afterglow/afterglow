"""Emit verified carrier programs from portable intent plus backend calibration.

This is deliberately the first, narrow native-emission family. The byte layout below is
not copied from a stored block: it constructs the two element headers, length-prefixed
duration runs, symbol alphabet and relocatable pointers that the literal carrier VM uses.
The timing profiles are Harmony PK backend calibration: for NEC, Samsung and RC6 they
reproduce programs exercised on real hardware; the other families are currently proved
only against the recovered carrier VM. Portable definitions remain the semantic contract,
but their nominal timings are not copied byte-for-byte into a program whose measured
durations intentionally differ. A semantic fingerprint binds each calibration to the exact
portable revision it was verified against, so editing that revision can never silently keep
emitting the old timing profile.

Emission is accepted only after the resulting program is executed by :mod:`ir_vm` and
its initial and held stages agree with the corresponding portable frames. This module is
a compiler component, not a simulator exposed by the application or GUI.
"""
from __future__ import annotations

import hashlib
import struct

from ... import ir_protocol
from . import ir_vm, irproto, protocol_json


SUPPORTED = frozenset({
    "nec1", "nec1-toshiba", "nec-ext", "nec2", "nec2-ext", "samsung32", "rc6-mce",
    "sony12", "sony15", "sony20",
    "jvc16",
    "rc5-13",
})
POINTER_BASE = 5
PWM_PARAMETER = 50
PERIOD_NS = 26315
DATA_PERIOD_US = 107870
REPEAT_PERIOD_US = 107865
DATA_ZERO = (568, -552)
DATA_ONE = (568, -1662)
DATA_TRAILER = (568,)
NEC_LEADER = (8990, -4490)
SAMSUNG_LEADER = (4500, -4500)
NEC_REPEAT_LEADER = (8990, -2230)
RC6_PERIOD_NS = 27624
RC6_FRAME_PERIOD_US = 105850
RC6_LEADER = (2632, -900, 441, -443, 441, -439, 441, -887, 441, -879,
              1323, -889, 441)
RC6_ZERO = (441, -446)
RC6_ONE = (-446, 441)
SONY_PERIOD_NS = 25000
SONY_FRAME_PERIOD_US = 45000
SONY_LEADER = (2400,)
SONY_ZERO = (-600, 600)
SONY_ONE = (-600, 1200)
JVC_PERIOD_NS = 26315
JVC_FRAME_PERIOD_US = 45000
JVC_LEADER = (8400, -4200)
JVC_DATA_HEADER = (500,)
JVC_ZERO = (-500, 500)
JVC_ONE = (-1600, 500)
RC5_PERIOD_NS = 27778
RC5_FRAME_PERIOD_US = 113792
RC5_LEADER = (889,)
RC5_ZERO = (889, -889)
RC5_ONE = (-889, 889)


class NativeEmissionError(ValueError):
    """The portable definition cannot be proven equivalent to the emitted program."""


def _word(pulse: int) -> int:
    duration = abs(pulse)
    if not 0 < duration <= ir_vm.MAX_GAP_US:
        raise NativeEmissionError(f"native duration {duration} us does not fit one word")
    return duration | (0x8000 if pulse > 0 else 0)


def _run(pulses) -> bytes:
    if not pulses or len(pulses) > 0xFF:
        raise NativeEmissionError("native duration run must contain 1..255 words")
    return bytes((len(pulses),)) + b"".join(
        struct.pack("<H", _word(pulse)) for pulse in pulses)


def _even_mark(duration: int) -> tuple[int, ...]:
    """Split a long mark into equal words, mirroring `_even_space`.

    Marks and spaces store identically apart from the carrier bit, and adjacent words of
    the same state concatenate, so the same even split applies.
    """
    return tuple(-word for word in _even_space(duration))


def _even_space(duration: int) -> tuple[int, ...]:
    """Split a long space into equal words, the way Logitech splits one *inside a symbol*.

    Their B&O block stores 34,400 us as `-17200, -17200`; splitting greedily gives
    `-32767, -1633`. Adjacent space words concatenate, so both emit identical infrared -
    but matching their convention makes a generated block byte-comparable with a proven
    one, which is the strongest evidence tier this project has.

    Deliberately *not* used by `_split_space`. The hardware-anchored NEC and Samsung
    blocks contain a greedily split repeat gap, and their block ids are pinned constants;
    changing that would break byte-identity with a program known to run. Logitech evidently
    used both conventions in different parts of their compiler, so we follow the evidence
    per site rather than picking one and imposing it.
    """
    if duration <= ir_vm.MAX_GAP_US:
        return (-duration,)
    count = -(-duration // ir_vm.MAX_GAP_US)          # ceil
    base, remainder = divmod(duration, count)
    return tuple(-(base + 1) if index < remainder else -base
                 for index in range(count))


def _split_space(duration: int) -> tuple[int, ...]:
    words = []
    while duration:
        chunk = min(duration, ir_vm.MAX_GAP_US)
        words.append(-chunk)
        duration -= chunk
    return tuple(words)


def _element(symbols: int, period_us: int, alphabet_size: int,
             words_per_symbol: int, *, toggles=(0xFF, 0xFF)) -> bytes:
    return struct.pack(
        "<HBBIBBHHH", symbols, toggles[0], toggles[1], period_us,
        alphabet_size, words_per_symbol, 0, 0, 0)


def _body(*, full_frame_repeat: bool, data_leader=NEC_LEADER,
          data_period_us=DATA_PERIOD_US) -> tuple[bytes, tuple[int, ...]]:
    """Construct the verified two-element NEC/Samsung carrier-program shape."""
    body = bytearray(struct.pack("<BI", 1, PERIOD_NS))
    body += bytes((PWM_PARAMETER, 2))       # PWM byte, then element-table count
    body += b"\0\0\0\0"                   # two u16 element pointers
    pointer_fields: list[int] = []

    def pointer(field: int, target: int) -> None:
        # Runtime addresses are relative to payload+5. protocol_json later adds the
        # block's assembled position, so body_hex stores target-5.
        struct.pack_into("<H", body, field, target - POINTER_BASE)
        pointer_fields.append(field)

    data_element = len(body)
    body += _element(32, data_period_us, 2, 2)
    data_before = len(body)
    body += _run(data_leader)
    data_after = len(body)
    body += _run(DATA_TRAILER)
    data_alphabet = len(body)
    body += b"".join(struct.pack("<H", _word(pulse))
                     for pulse in (*DATA_ZERO, *DATA_ONE))

    # Keep the short-repeat element even when Samsung's element-table entry points back
    # to the full-data element. That reconstructs the hardware-validated block exactly;
    # the dormant element is harmless and lets emission replace, rather than change,
    # the production native artifact.
    repeat_element = len(body)
    body += _element(0, 0xFFFFFFFF, 0, 0)
    repeat_before = len(body)
    body += _run(NEC_REPEAT_LEADER)
    repeat_after = len(body)
    gap = REPEAT_PERIOD_US - sum(map(abs, (*NEC_REPEAT_LEADER, *DATA_TRAILER)))
    body += _run((*DATA_TRAILER, *_split_space(gap)))

    pointer(7, data_element)
    pointer(9, data_element if full_frame_repeat else repeat_element)
    pointer(data_element + 10, data_alphabet)
    pointer(data_element + 12, data_before)
    pointer(data_element + 14, data_after)
    pointer(repeat_element + 12, repeat_before)
    pointer(repeat_element + 14, repeat_after)
    return bytes(body), tuple(pointer_fields)


def _rc6_body() -> tuple[bytes, tuple[int, ...]]:
    """Construct the proven one-element RC6-MCE carrier program."""
    body = bytearray(struct.pack("<BI", 1, RC6_PERIOD_NS))
    body += bytes((PWM_PARAMETER, 1))
    body += b"\0\0"
    pointer_fields: list[int] = []

    def pointer(field: int, target: int) -> None:
        struct.pack_into("<H", body, field, target - POINTER_BASE)
        pointer_fields.append(field)

    element = len(body)
    body += _element(
        30, RC6_FRAME_PERIOD_US, 2, 2, toggles=(14, 0xFF))
    before = len(body)
    body += _run(RC6_LEADER)
    alphabet = len(body)
    body += b"".join(
        struct.pack("<H", _word(pulse)) for pulse in (*RC6_ZERO, *RC6_ONE))

    pointer(7, element)
    pointer(element + 10, alphabet)
    pointer(element + 12, before)
    return bytes(body), tuple(pointer_fields)


def _sony_body(symbols: int) -> tuple[bytes, tuple[int, ...]]:
    """Construct a one-element Sony SIRC pulse-width carrier program."""
    body = bytearray(struct.pack("<BI", 1, SONY_PERIOD_NS))
    body += bytes((PWM_PARAMETER, 1))
    body += b"\0\0"
    pointer_fields: list[int] = []

    def pointer(field: int, target: int) -> None:
        struct.pack_into("<H", body, field, target - POINTER_BASE)
        pointer_fields.append(field)

    element = len(body)
    body += _element(symbols, SONY_FRAME_PERIOD_US, 2, 2)
    before = len(body)
    body += _run(SONY_LEADER)
    alphabet = len(body)
    body += b"".join(
        struct.pack("<H", _word(pulse)) for pulse in (*SONY_ZERO, *SONY_ONE))

    pointer(7, element)
    pointer(element + 10, alphabet)
    pointer(element + 12, before)
    return bytes(body), tuple(pointer_fields)


def _jvc16_body() -> tuple[bytes, tuple[int, ...]]:
    """Construct separate JVC leader and data elements for press/hold sequencing."""
    body = bytearray(struct.pack("<BI", 1, JVC_PERIOD_NS))
    body += bytes((PWM_PARAMETER, 2))
    body += b"\0\0\0\0"
    pointer_fields: list[int] = []

    def pointer(field: int, target: int) -> None:
        struct.pack_into("<H", body, field, target - POINTER_BASE)
        pointer_fields.append(field)

    leader_element = len(body)
    body += _element(0, 0xFFFFFFFF, 0, 0)
    leader_before = len(body)
    body += _run(JVC_LEADER)

    data_element = len(body)
    body += _element(16, JVC_FRAME_PERIOD_US, 2, 2)
    data_before = len(body)
    body += _run(JVC_DATA_HEADER)
    alphabet = len(body)
    body += b"".join(
        struct.pack("<H", _word(pulse)) for pulse in (*JVC_ZERO, *JVC_ONE))

    pointer(7, leader_element)
    pointer(9, data_element)
    pointer(leader_element + 12, leader_before)
    pointer(data_element + 10, alphabet)
    pointer(data_element + 12, data_before)
    return bytes(body), tuple(pointer_fields)


def _rc5_body() -> tuple[bytes, tuple[int, ...]]:
    """Construct a one-element RC5 program with native toggle position 1."""
    body = bytearray(struct.pack("<BI", 1, RC5_PERIOD_NS))
    body += bytes((PWM_PARAMETER, 1))
    body += b"\0\0"
    pointer_fields: list[int] = []

    def pointer(field: int, target: int) -> None:
        struct.pack_into("<H", body, field, target - POINTER_BASE)
        pointer_fields.append(field)

    element = len(body)
    body += _element(
        13, RC5_FRAME_PERIOD_US, 2, 2, toggles=(1, 0xFF))
    before = len(body)
    body += _run(RC5_LEADER)
    alphabet = len(body)
    body += b"".join(
        struct.pack("<H", _word(pulse)) for pulse in (*RC5_ZERO, *RC5_ONE))

    pointer(7, element)
    pointer(element + 10, alphabet)
    pointer(element + 12, before)
    return bytes(body), tuple(pointer_fields)


def _referenced_fields(definition: dict) -> dict[str, int]:
    """Protocol-global command parameters, excluding frame-local occurrence payloads.

    Converted definitions deliberately bind globals such as ``Code0`` into a local
    ``payload``. The resolved-occurrence layer performs that binding; inventing a global
    payload test value here bypasses the portable lifecycle and recreates the converter
    misdiagnosis recorded in the research journal.
    """
    return {
        name: entry["bits"]
        for name, entry in (definition.get("parameters") or {}).items()
    }


def _parameter_vectors(definition: dict) -> tuple[tuple[str, dict[str, int]], ...]:
    """Edge and mixed values that every emitter/codec pair must reproduce."""
    widths = _referenced_fields(definition)
    patterns = (0x5A5A5A5A, 0xA5A5A5A5, 0x3C3C3C3C)
    patterned = {
        name: patterns[index % len(patterns)] & ((1 << bits) - 1)
        for index, (name, bits) in enumerate(widths.items())
    }
    candidates = (
        ("mixed", patterned),
        ("all-zero", {name: 0 for name in widths}),
        ("all-one", {name: (1 << bits) - 1 for name, bits in widths.items()}),
        ("low-edge", {name: 1 for name in widths}),
        ("high-edge", {
            name: max(0, (1 << bits) - 2) for name, bits in widths.items()}),
        ("split-edge", {
            name: (0 if index % 2 == 0 else (1 << bits) - 1)
            for index, (name, bits) in enumerate(widths.items())
        }),
    )
    unique = []
    seen = set()
    for label, parameters in candidates:
        identity = tuple(parameters.items())
        if identity not in seen:
            unique.append((label, parameters))
            seen.add(identity)
    return tuple(unique)


def _frame_for_phase(definition: dict, phase: str) -> str:
    transmission = definition.get("transmission") or {}
    sequence = transmission.get(phase) or []
    if not sequence:
        raise NativeEmissionError(
            f"portable protocol {definition['id']!r} has no {phase} frame")
    item = sequence[0]
    if item.get("count", 1) != 1 or item.get("bind"):
        raise NativeEmissionError(
            f"portable protocol {definition['id']!r} has a compound {phase} frame")
    return item["frame"]


def _pulses(words) -> tuple[int, ...]:
    return tuple((word & 0x7FFF) * (1 if word & 0x8000 else -1)
                 for word in words if word & 0x7FFF)


def _equivalent(expected, actual, *, phase: str) -> None:
    expected = ir_vm.normalise_pulses(expected)
    actual = ir_vm.normalise_pulses(actual)
    if len(expected) != len(actual):
        raise NativeEmissionError(
            f"emitted {phase} topology has {len(actual)} transitions, expected "
            f"{len(expected)}")
    for index, (wanted, emitted) in enumerate(zip(expected, actual)):
        tolerance = max(30, round(abs(wanted) * 0.06))
        if ((wanted > 0) != (emitted > 0)
                or abs(abs(wanted) - abs(emitted)) > tolerance):
            raise NativeEmissionError(
                f"emitted {phase} pulse {index} is {emitted} us, expected {wanted} us "
                f"within {tolerance} us")


def _verify_vector(portable: ir_protocol.Protocol, spec: dict, mapping: dict,
                   vector: str, parameters: dict[str, int]) -> None:
    from .builder import codes

    definition = portable.raw
    code = codes.encode_parameters(
        mapping["code_codec"], parameters, 0,
        repeat_data_copy=mapping.get("repeat_data_copy", False))
    payload = protocol_json.assemble([spec])
    if mapping["emitter"] == "jvc16":
        expected_press, state = portable.transmission(parameters, "press")
        expected_hold, _state = portable.transmission(
            parameters, "hold", state=state)
        simulation = ir_vm.simulate_transmission(payload, code)
        if simulation.sequence_stages != (2, 3):
            raise NativeEmissionError(
                f"emitted JVC lifecycle is {simulation.sequence_stages}, expected 2/3")
        expected_phases = (("press", expected_press), ("hold", expected_hold))
        phase_counts = simulation.sequence_word_counts
    elif mapping["emitter"] == "sony":
        expected_press, state = portable.transmission(parameters, "press")
        expected_hold, _state = portable.transmission(
            parameters, "hold", state=state)
        simulation = ir_vm.simulate_transmission(payload, code, held_replays=3)
        if simulation.sequence_stages != (3, 3, 3, 3):
            raise NativeEmissionError(
                f"emitted Sony12 lifecycle is {simulation.sequence_stages}, "
                "expected four stage-3 frames")
        expected_phases = (("press", expected_press), ("hold", expected_hold))
        phase_counts = (
            sum(simulation.sequence_word_counts[:3]),
            simulation.sequence_word_counts[3],
        )
    elif mapping["emitter"] in ("rc5", "rc6"):
        expected_press, state = portable.transmission(parameters, "press")
        expected_hold, _state = portable.transmission(
            parameters, "hold", state=state)
        simulation = ir_vm.simulate_transmission(
            payload, code, toggle_state=state["toggle"], held_replays=1)
        if simulation.sequence_stages != (3, 3):
            raise NativeEmissionError(
                f"emitted toggle lifecycle is {simulation.sequence_stages}, expected 3/3")
        expected_phases = (("press", expected_press), ("hold", expected_hold))
        phase_counts = simulation.sequence_word_counts[:2]
    else:
        if definition.get("state"):
            raise NativeEmissionError("NEC-family emitter does not support sender state")
        simulation = ir_vm.simulate_transmission(payload, code)
        if simulation.sequence_stages[:2] != (2, 3):
            raise NativeEmissionError(
                f"emitted lifecycle starts with stages {simulation.sequence_stages}, "
                "expected 2/3")
        expected_phases = tuple(
            (phase, portable.frame(parameters, _frame_for_phase(definition, phase)))
            for phase in ("press", "hold")
        )
        phase_counts = simulation.sequence_word_counts[:2]
    if abs(simulation.carrier_hz - definition["modulation"]["carrier_hz"]) > 400:
        raise NativeEmissionError(
            f"emitted carrier {simulation.carrier_hz} Hz does not match portable carrier")

    offset = 0
    for (phase, expected), count in zip(expected_phases, phase_counts):
        words = simulation.words[offset:offset + count]
        offset += count
        _equivalent(expected, _pulses(words), phase=f"{phase} [{vector}]")


def _verify(portable: ir_protocol.Protocol, spec: dict, mapping: dict) -> None:
    definition = portable.raw
    if (definition.get("transmission") or {}).get("release"):
        raise NativeEmissionError("native emitter does not support a release frame")
    for vector, parameters in _parameter_vectors(definition):
        _verify_vector(portable, spec, mapping, vector, parameters)


def emit(protocol_id: str, mapping: dict, *, library=None) -> dict:
    """Return a lossless native block definition generated from one portable protocol."""
    library = ir_protocol.LIBRARY if library is None else library
    if (protocol_id not in SUPPORTED
            or mapping.get("emitter") not in (
                "nec-family", "rc5", "rc6", "sony", "jvc16")):
        raise NativeEmissionError(f"no native emitter for portable protocol {protocol_id!r}")
    portable = ir_protocol.Catalog(library)[protocol_id]
    definition = portable.raw
    actual_signature = portable.fingerprint()
    expected_signature = mapping.get("portable_signature")
    if actual_signature != expected_signature:
        raise NativeEmissionError(
            f"portable protocol {protocol_id!r} meaning is {actual_signature}, but this "
            f"backend calibration was verified against {expected_signature or 'no revision'}; "
            "review and recalibrate the emitter before accepting the changed definition")
    if mapping["emitter"] == "rc6":
        body, pointers = _rc6_body()
        period_ns = RC6_PERIOD_NS
        element_count = 1
    elif mapping["emitter"] == "sony":
        body, pointers = _sony_body(definition["parameters"]["code"]["bits"])
        period_ns = SONY_PERIOD_NS
        element_count = 1
    elif mapping["emitter"] == "jvc16":
        body, pointers = _jvc16_body()
        period_ns = JVC_PERIOD_NS
        element_count = 2
    elif mapping["emitter"] == "rc5":
        body, pointers = _rc5_body()
        period_ns = RC5_PERIOD_NS
        element_count = 1
    else:
        body, pointers = _body(
            full_frame_repeat=mapping.get("repeat_data_copy", False),
            data_leader=(SAMSUNG_LEADER
                         if mapping.get("leader") == "samsung" else NEC_LEADER),
            data_period_us=mapping.get("data_period_us", DATA_PERIOD_US))
        period_ns = PERIOD_NS
        element_count = 2
    spec = {
        "schema": protocol_json.SCHEMA,
        "backend": "harmony-pk",
        "id": "pending",
        "name": f"{definition['name']} (emitted)",
        "carrier_period_ns": period_ns,
        "pwm_parameter": PWM_PARAMETER,
        "element_count": element_count,
        "flag": 1,
        "size": len(body),
        "pointer_fields": list(pointers),
        "body_hex": body.hex(),
    }
    canonical = protocol_json.encode(spec, position=irproto.CANON_POS)
    spec["id"] = hashlib.sha256(canonical).hexdigest()[:12]
    expected_id = mapping.get("block_id")
    if expected_id and spec["id"] != expected_id:
        raise NativeEmissionError(
            f"emitted {protocol_id} block is {spec['id']}, expected proven block {expected_id}")
    _verify(portable, spec, mapping)
    return spec


# generic emission
#
# Everything above is one hand-written builder per protocol family. That does not scale:
# the Logitech archive holds hundreds of protocols, and 673,366 of the commands this
# backend currently refuses (87.2% of them) have a frame shape a native element can
# express directly. Logitech's own tooling clearly produced blocks for all of them, so
# the limit is this module, not the hardware.
#
# A native element plays `[before-run] + N symbols + [after-run]`, repeated to a period.
# A portable frame maps onto that exactly when it has at most one `field` segment, with
# bursts only before and after it, and when its alphabet's symbols are all the same
# number of pulses (the element header stores one `words_per_symbol` for all of them).
#
# Timings are NOT taken from the portable definition when a calibration exists. The
# hand-written families use measured values - NEC's leader is 8990 us where the portable
# definition says 9000 - and four of the five carrier periods derive exactly from the
# carrier while NEC and JVC are 1 ns off a clean round. Those differences are evidence,
# not noise; hardware-anchored families therefore keep their calibrated bespoke builders
# until a keyed generic calibration model exists.


class GenericShapeError(NativeEmissionError):
    """This portable frame is not expressible as a native element program."""


def _frame_layout(definition: dict, frame_name: str) -> dict:
    """Split one portable frame into before-run / field / after-run, or refuse."""
    frame = (definition.get("frames") or {}).get(frame_name)
    if frame is None:
        raise GenericShapeError(f"no frame {frame_name!r} in {definition['id']!r}")
    segments = frame.get("segments") or []
    # A `state` segment is part of the symbol run, not a burst: RC5 is
    # leader / 1 data bit / toggle / 11 data bits, and its proven element is 13 symbols
    # with the element header's toggle byte set to 1. The firmware substitutes the
    # sender's toggle at that bit offset (`ir_vm._toggle` reads element+2 and element+3),
    # so the position is derived, never guessed.
    field_positions = [index for index, segment in enumerate(segments)
                       if any(key in segment for key in ("field", "state", "constant"))]
    # Several *contiguous* fields sharing one alphabet are a single symbol run: NEC's
    # frame is four fields - address, ~address, command, ~command - and its proven block
    # is one element of 32 symbols, because the element supplies timing while the Code
    # supplies the bits. Refusing multi-field frames therefore rejected NEC itself, which
    # is a good sign the rule was wrong rather than the protocol being exotic.
    if field_positions and field_positions[-1] - field_positions[0] + 1 != len(field_positions):
        raise GenericShapeError(
            f"frame {frame_name!r} interleaves bursts between its data segments; one "
            "element plays a single uninterrupted symbol run")
    bursts = definition.get("bursts") or {}

    def run_for(chunk) -> tuple[int, ...]:
        pulses: list[int] = []
        for segment in chunk:
            name = segment.get("burst")
            if name is None:
                raise GenericShapeError(
                    f"frame {frame_name!r} has a segment that is neither burst nor field")
            for pulse in bursts[name]:
                if pulse < 0 and abs(pulse) > ir_vm.MAX_GAP_US:
                    # A duration word holds 15 bits, so a long lead-out is written as
                    # consecutive off words - the same construction `_body` uses for
                    # NEC's repeat gap and `ssir.encode_capture` for a raw waveform.
                    # Without it a 96,077 us Toshiba lead-out simply refused to emit,
                    # taking 441,156 corpus commands with it.
                    pulses.extend(_split_space(abs(pulse)))
                else:
                    pulses.append(pulse)
        return tuple(pulses)

    if not field_positions:
        return {"before": run_for(segments), "field": None, "after": (),
                "toggles": (0xFF, 0xFF),
                "period_us": frame.get("minimum_period_us", 0)}

    first, last = field_positions[0], field_positions[-1]
    fields = [segments[index] for index in field_positions]
    alphabets = definition.get("alphabets") or {}
    named = {field.get("alphabet") for field in fields}
    if len(named) != 1:
        raise GenericShapeError(
            f"frame {frame_name!r} mixes alphabets {sorted(n or '<default>' for n in named)} "
            "in one symbol run")
    name = named.pop()
    alphabet = alphabets.get(name or "bits")
    if alphabet is None:
        raise GenericShapeError(f"frame {frame_name!r} names no usable alphabet")

    # How the native format stores an alphabet whose symbols are not the same width,
    # read off a real donor block (donor-1, block 6, Ctrl1=3):
    #
    #     [198, -17200, -17200,   198, -27800, 0]
    #      +-- symbol 0 -------+  +-- symbol 1 --+
    #
    # Two things at once. A space longer than one 15-bit word is **split across words
    # inside the symbol** (-17200, -17200 is 34,400 us), and a symbol that then needs
    # fewer words than the widest one is **zero-padded**. `words_per_symbol` is the
    # uniform width, and the runtime skips zero-duration words - which is why padding is
    # invisible on the wire.
    #
    # Refusing ragged alphabets and long symbol spaces was what blocked the last 6,601
    # archive commands. Both are the same construct, and the format already had it.
    expanded = []
    for key in sorted(alphabet["symbols"], key=lambda text: int(text, 2)
                      if set(text) <= {"0", "1"} else int(text)):
        entry = alphabet["symbols"][key]
        pulses = tuple(bursts[entry]) if isinstance(entry, str) else tuple(entry)
        words: list[int] = []
        for pulse in pulses:
            if pulse < 0 and abs(pulse) > ir_vm.MAX_GAP_US:
                words.extend(_even_space(abs(pulse)))
            elif pulse > 0 and pulse > ir_vm.MAX_GAP_US:
                # A mark splits exactly as a space does. This used to refuse, on the
                # reasoning that "a carrier burst that long is not a real signal" - which
                # `Zenith 11 Bit Quad` disproves. Its symbol 2 is a single 99,999 us mark,
                # and Logitech's own Pronto for a command selecting it opens with a
                # 100,484 us mark: the 99,999 burst merged with the 484 that follows it.
                # A 100 ms carrier burst is unusual, and it is what that device wants.
                #
                # Splitting is invisible on the wire for the same reason it is for spaces:
                # adjacent words with the same carrier state concatenate, which is exactly
                # what `ir_vm.normalise_pulses` folds back together when comparing.
                words.extend(_even_mark(pulse))
            else:
                words.append(pulse)
        expanded.append(tuple(words))
    if not expanded:
        raise GenericShapeError(f"frame {frame_name!r} has an empty symbol alphabet")
    # Named `symbol_words`, not `width`: the field-width loop below binds `width`, and
    # letting the two share a name silently emitted Sony's 12-bit code length as its
    # words-per-symbol.
    symbol_words = max(len(words) for words in expanded)
    if symbol_words > 0xFF:
        raise GenericShapeError(
            f"frame {frame_name!r} needs {symbol_words} words per symbol; the element "
            "header stores that in one byte")
    # 0 is the pad: it is not a duration, and `_pulses` drops it when reading back.
    symbols = [words + (0,) * (symbol_words - len(words)) for words in expanded]

    parameters = {
        **(definition.get("parameters") or {}),
        **(frame.get("parameters") or {}),
    }
    declared_state = definition.get("state") or {}
    per_symbol = alphabet.get("bits_per_symbol", 1)
    total_bits = 0
    toggle_offsets: list[int] = []
    for segment in fields:
        if "state" in segment:
            name = segment["state"]
            if name not in declared_state:
                raise GenericShapeError(
                    f"frame {frame_name!r} uses undeclared sender state {name!r}")
            width = segment.get("bits", declared_state[name].get("bits", 1))
            if width != 1:
                raise GenericShapeError(
                    f"frame {frame_name!r} has a {width}-bit state segment; the element "
                    "header carries single-bit toggle positions")
            toggle_offsets.append(total_bits)
            total_bits += width
            continue
        if "constant" in segment:
            total_bits += segment["bits"]
            continue
        source = segment["field"]
        width = segment.get("bits")
        if width is None:
            holder = parameters.get(source)
            if holder is None:
                raise GenericShapeError(
                    f"frame {frame_name!r} fields unknown parameter {source!r}")
            width = holder["bits"]
        total_bits += width
    # element+2 and element+3 hold one toggle position each, for toggle_state bits 1
    # and 2 respectively; 0xFF means "no toggle at all".
    if len(toggle_offsets) > 2:
        raise GenericShapeError(
            f"frame {frame_name!r} has {len(toggle_offsets)} state segments; the element "
            "header holds at most two toggle positions")
    if any(offset > 0xFE for offset in toggle_offsets):
        raise GenericShapeError(
            f"frame {frame_name!r} places sender state past bit 254")
    toggles = tuple(toggle_offsets) + (0xFF,) * (2 - len(toggle_offsets))
    if total_bits % per_symbol:
        raise GenericShapeError(
            f"{total_bits}-bit run does not divide into {per_symbol}-bit symbols")
    return {
        "before": run_for(segments[:first]),
        "after": run_for(segments[last + 1:]),
        "field": {"symbols": total_bits // per_symbol,
                  "alphabet": tuple(symbols),
                  "words_per_symbol": symbol_words},
        "toggles": toggles,
        "period_us": frame.get("minimum_period_us", 0),
    }


def _generic_body(definition: dict, frame_names, *,
                  period_ns: int) -> tuple[bytes, tuple[int, ...]]:
    """Build an element program for any portable definition of an expressible shape.

    One element per named frame, laid out in a canonical order: every element header
    first, then each element's data sections. The hand-written builders above each chose
    a slightly different order, so this does **not** reproduce them byte-for-byte, and it
    deliberately does not try. Byte equality only matters for the families whose
    `block_id` is pinned to a hardware-proven block; those keep their own builder, and
    this one is what lets a protocol nobody has hand-written reach the remote at all.

    """
    frame_names = list(frame_names)
    if not 1 <= len(frame_names) <= 0xFF:
        raise GenericShapeError(
            f"a block needs 1..255 elements, got {len(frame_names)}")
    body = bytearray(struct.pack("<BI", 1, period_ns))
    body += bytes((PWM_PARAMETER, len(frame_names)))
    body += b"\0\0" * len(frame_names)
    pointer_fields: list[int] = []

    def pointer(field: int, target: int) -> None:
        struct.pack_into("<H", body, field, target - POINTER_BASE)
        pointer_fields.append(field)

    layouts, offsets = [], []
    for name in frame_names:
        layout = _frame_layout(definition, name)
        field = layout["field"]
        offsets.append(len(body))
        layouts.append(layout)
        body += _element(
            field["symbols"] if field else 0,
            layout["period_us"] or 0xFFFFFFFF,
            len(field["alphabet"]) if field else 0,
            field["words_per_symbol"] if field else 0,
            toggles=layout["toggles"])

    for offset, layout in zip(offsets, layouts):
        before = layout["before"]
        after = layout["after"]
        if before:
            position = len(body)
            body += _run(before)
            pointer(offset + 12, position)
        if after:
            position = len(body)
            body += _run(after)
            pointer(offset + 14, position)
        if layout["field"]:
            position = len(body)
            for symbol in layout["field"]["alphabet"]:
                # A zero word is padding, not a duration, so it bypasses `_word`, which
                # rejects zero as an unrepresentable interval.
                body += b"".join(
                    struct.pack("<H", 0 if pulse == 0 else _word(pulse))
                    for pulse in symbol)
            pointer(offset + 10, position)

    for index, offset in enumerate(offsets):
        pointer(7 + index * 2, offset)
    return bytes(body), tuple(pointer_fields)


def element_order(definition: dict) -> dict[str, int]:
    """Frame name -> element table index for every frame the protocol can select.

    The block and the Code must agree on these indices or the remote plays the wrong
    element. Signal-level recipes can select frames absent from the default lifecycle, so
    emitting only default frames made one portable protocol depend on which command was
    compiled first. A protocol block instead contains its complete frame vocabulary.
    """
    names = list((definition.get("frames") or {}).keys())
    if not names:
        raise GenericShapeError(
            f"portable protocol {definition['id']!r} transmits no frames")
    return {name: index for index, name in enumerate(names)}


def emit_generic(definition: dict, *, minimum_repeats: int | None = None,
                 pre_silence_us: int = 500, verify: bool = True,
                 parameters: dict | None = None,
                 transmission: dict | None = None) -> dict:
    """Emit a native block for a portable protocol with no hand-written builder.

    This is the path that lets a protocol nobody has curated reach the remote. It is
    gated the same way the hand-written families are: the program is executed by the
    literal carrier VM and its press and hold stages must reproduce the portable frames.
    A definition whose shape an element cannot express is refused, not approximated.
    """

    order = element_order(definition)
    carrier = (definition.get("modulation") or {}).get("carrier_hz")
    if not carrier:
        raise GenericShapeError(
            f"portable protocol {definition['id']!r} declares no carrier frequency")
    period_ns = round(1_000_000_000 / carrier)
    body, pointers = _generic_body(definition, list(order), period_ns=period_ns)
    spec = {
        "schema": protocol_json.SCHEMA,
        "backend": "harmony-pk",
        "id": "pending",
        "name": f"{definition.get('name', definition['id'])} (generic)",
        "carrier_period_ns": period_ns,
        "pwm_parameter": PWM_PARAMETER,
        "element_count": len(order),
        "flag": 1,
        "size": len(body),
        "pointer_fields": list(pointers),
        "body_hex": body.hex(),
    }
    spec["id"] = hashlib.sha256(
        protocol_json.encode(spec, position=irproto.CANON_POS)).hexdigest()[:12]
    if verify:
        _verify_generic(definition, spec, order,
                        minimum_repeats=minimum_repeats, pre_silence_us=pre_silence_us,
                        parameters=parameters, transmission=transmission)
    return spec


def _verify_generic(definition: dict, spec: dict, order: dict, *,
                    minimum_repeats: int | None, pre_silence_us: int,
                    parameters: dict | None = None,
                    transmission: dict | None = None) -> None:
    """Execute the generated program and require it to mean the portable definition.

    The previous version compared only the *first* native stage against the whole press
    transmission, which is not an alignment at all: Sony's press is three frames, so it
    reported 26 transitions against 78 and called five working families broken. Worse, it
    supplied no toggle state and never looked at hold or release, so a protocol whose
    sender state did nothing would have passed.

    The VM reports both waveform boundaries and the actual element indices consumed from
    the Code. The gate compares those observations with complete portable press and hold
    transmissions, including repetition counts, sender state and a stage-5 release.
    """
    from .builder import codes

    payload = protocol_json.assemble([spec])
    vectors = (("command", parameters),) if parameters is not None \
        else _parameter_vectors(definition)

    for label, vector in vectors:
        expected_press, state = ir_protocol.transmission(
            definition, vector, "press", sequence=transmission)
        expected_hold, _state = ir_protocol.transmission(
            definition, vector, "hold", state=state, sequence=transmission)
        expected_release, _state = ir_protocol.transmission(
            definition, vector, "release", state=state, sequence=transmission)
        toggle_state = sum(
            (state.get(name, 0) & 1) << index
            for index, name in enumerate((definition.get("state") or {})))
        plan = codes.transmission_plan(
            definition, vector, transmission=transmission,
            minimum_repeats=minimum_repeats)
        code = codes.generic_code(definition, order, vector, 0,
                                  pre_silence_us=pre_silence_us,
                                  minimum_repeats=minimum_repeats,
                                  transmission=transmission)

        def simulate(held_replays: int):
            try:
                return ir_vm.simulate_transmission(
                    payload, code, toggle_state=toggle_state,
                    held_replays=held_replays)
            except ir_vm.IrVmError as exc:
                raise NativeEmissionError(
                    f"generated program for {definition['id']!r} does not execute "
                    f"[{label}]: {exc}") from None

        def stages(simulation):
            out: list[tuple[int, ...]] = []
            offset = 0
            for count in simulation.sequence_word_counts:
                out.append(_pulses(simulation.words[offset:offset + count]))
                offset += count
            return out

        expected_elements = {
            section["stage"]: tuple(
                order[item["frame"]] for item in section["occurrences"])
            for section in plan["sections"]
        }

        def check_elements(simulation):
            for index, (stage, actual) in enumerate(zip(
                    simulation.sequence_stages, simulation.sequence_elements)):
                wanted = expected_elements.get(stage)
                if wanted is None:
                    raise NativeEmissionError(
                        f"native stage {stage} of {definition['id']!r} [{label}] was not "
                        "present in the resolved portable plan")
                if actual != wanted:
                    raise NativeEmissionError(
                        f"native stage {stage} occurrence {index} of "
                        f"{definition['id']!r} [{label}] executes "
                        f"elements {actual}, expected {wanted}")

        baseline = simulate(0)
        baseline_pulses = stages(baseline)
        check_elements(baseline)

        section_stages = tuple(section["stage"] for section in plan["sections"])
        expected_stages = tuple(
            stage
            for section in plan["sections"]
            for stage in ((section["stage"],) * (
                max(1, plan["minimum_repeats"])
                if section["stage"] == 3 else 1)))
        if baseline.sequence_stages != expected_stages:
            raise NativeEmissionError(
                f"{definition['id']!r} [{label}] executes native stages "
                f"{baseline.sequence_stages}, expected {expected_stages}")

        if abs(baseline.carrier_hz - definition["modulation"]["carrier_hz"]) > 400:
            raise NativeEmissionError(
                f"emitted carrier {baseline.carrier_hz} Hz does not match the portable "
                f"carrier for {definition['id']!r} [{label}]")

        expected_by_stage = {
            2: expected_press,
            3: expected_hold,
            5: expected_release,
        }

        def check_waveforms(simulation, emitted_stages):
            for index, (stage, emitted) in enumerate(zip(
                    simulation.sequence_stages, emitted_stages)):
                _equivalent(
                    expected_by_stage[stage], emitted,
                    phase=f"native stage {stage} occurrence {index} [{label}]")

        check_waveforms(baseline, baseline_pulses)
        if section_stages[0] == 3:
            emitted_press = tuple(
                pulse
                for stage, pulses in zip(baseline.sequence_stages, baseline_pulses)
                if stage == 3
                for pulse in pulses)
            _equivalent(expected_press, emitted_press, phase=f"press [{label}]")

        # Request exactly one execution beyond the baseline stage-3 minimum. A finish
        # stage remains last; the extra hold is inserted immediately before it.
        stage3_count = baseline.sequence_stages.count(3)
        held = simulate(max(1, stage3_count))
        held_pulses = stages(held)
        check_elements(held)
        added = 1 if expected_hold else 0
        if len(held_pulses) != len(baseline_pulses) + added:
            raise NativeEmissionError(
                f"holding {definition['id']!r} [{label}] adds "
                f"{len(held_pulses) - len(baseline_pulses)} stages, expected {added}")
        held_expected_stages = list(expected_stages)
        if added:
            finish = held_expected_stages.index(5) if 5 in held_expected_stages \
                else len(held_expected_stages)
            held_expected_stages.insert(finish, 3)
        if held.sequence_stages != tuple(held_expected_stages):
            raise NativeEmissionError(
                f"holding {definition['id']!r} [{label}] executes native stages "
                f"{held.sequence_stages}, expected {tuple(held_expected_stages)}")
        check_waveforms(held, held_pulses)
