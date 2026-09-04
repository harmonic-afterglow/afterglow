"""Promote an imported carrier program into a proved portable protocol.

An unknown ``IrProto`` block is not itself a protocol description: its element table
only acquires a lifecycle and command values when paired with the real ``Code`` records
that select it.  This module reads that pair structurally, writes the smallest portable
definition that describes it, then compiles the result back through the generic Harmony
backend and executes both versions in :mod:`ir_vm`.

Promotion is all-or-nothing per block.  Every Code using the block must parse, compile
and reproduce its native carrier output for both a press and a continued hold.  Anything
outside the proved subset raises :class:`PromotionError`; the importer then keeps the
original block and Code as backend-opaque evidence.  That fallback is intentional: a
portable-looking approximation is less safe than an honestly native command.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log2

from ... import ir_protocol
from . import ir_emit, ir_vm, protocol_json
from .builder import codes as code_builder


class PromotionError(ValueError):
    """The imported native program cannot yet be represented without loss."""


@dataclass(frozen=True)
class Promotion:
    """One portable definition and the signal recipe for each native Code."""

    definition: dict
    transmissions: dict[str, dict]


def code_key(code: str | bytes | bytearray) -> str:
    """Canonical identity for a Code within one protocol block."""
    return _code_bytes(code).hex().upper()


def _code_bytes(code: str | bytes | bytearray) -> bytes:
    if isinstance(code, (bytes, bytearray)):
        raw = bytes(code)
    else:
        text = str(code).strip()
        if text.lower().startswith("0x"):
            text = text[2:]
        try:
            raw = bytes.fromhex(text)
        except ValueError as exc:
            raise PromotionError(f"invalid native Code {code!r}") from exc
    if len(raw) < 7:
        raise PromotionError("native Code is too short")
    return raw


def _u16(data: bytes, offset: int) -> int:
    if not 0 <= offset <= len(data) - 2:
        raise PromotionError(f"native u16 read outside payload at {offset}")
    return data[offset] | data[offset + 1] << 8


def _u32(data: bytes, offset: int) -> int:
    return _u16(data, offset) | _u16(data, offset + 2) << 16


def _pulses(data: bytes, pointer: int, count: int) -> list[int]:
    out = []
    for index in range(count):
        word = _u16(data, pointer + index * 2)
        duration = word & 0x7FFF
        if duration:
            out.append(duration if word & 0x8000 else -duration)
    return out


def _run(data: bytes, stored_pointer: int) -> list[int]:
    if not stored_pointer:
        return []
    pointer = ir_vm.PROTOCOL_BASE + stored_pointer
    if not 0 <= pointer < len(data):
        raise PromotionError(f"native duration run points outside payload at {pointer}")
    return _pulses(data, pointer + 1, data[pointer])


def _element_table(definition: dict) -> tuple[bytes, list[dict]]:
    """Materialise a native definition and decode the element headers it exposes."""
    try:
        payload = protocol_json.assemble([definition])
    except ValueError as exc:
        raise PromotionError(str(exc)) from exc
    block = ir_vm.PROTOCOL_BASE + _u16(payload, ir_vm.PROTOCOL_BASE + 3)
    if block + 7 > len(payload):
        raise PromotionError("native protocol block starts outside its payload")

    elements = []
    for index in range(payload[block + 6]):
        element = ir_vm.PROTOCOL_BASE + _u16(payload, block + 7 + index * 2)
        if element + 16 > len(payload):
            raise PromotionError(f"native element {index} starts outside its payload")
        iterations = _u16(payload, element)
        toggles = (payload[element + 2], payload[element + 3])
        if toggles[1] != 0xFF:
            raise PromotionError(
                f"native element {index} declares a second toggle position {toggles}; "
                "the portable grammar carries one sender state per frame")
        toggle_at = None if toggles[0] == 0xFF else toggles[0]
        alphabet_size = payload[element + 8]
        words_per_symbol = payload[element + 9]
        alphabet_pointer = _u16(payload, element + 10)
        before = _run(payload, _u16(payload, element + 12))
        after = _run(payload, _u16(payload, element + 14))
        period = _u32(payload, element + 4)

        if alphabet_pointer:
            if alphabet_size < 2 or alphabet_size & (alphabet_size - 1):
                raise PromotionError(
                    f"native element {index} has a non-power-of-two alphabet of "
                    f"{alphabet_size} symbols")
            bits_per_symbol = int(log2(alphabet_size))
            if not 1 <= bits_per_symbol <= 8 or not words_per_symbol or not iterations:
                raise PromotionError(f"native element {index} has unusable symbol data")
            pointer = ir_vm.PROTOCOL_BASE + alphabet_pointer
            symbols = [
                _pulses(payload, pointer + symbol * words_per_symbol * 2,
                        words_per_symbol)
                for symbol in range(alphabet_size)
            ]
            if any(not symbol for symbol in symbols):
                raise PromotionError(f"native element {index} has an empty symbol")
            total_bits = iterations * bits_per_symbol
        else:
            if alphabet_size or words_per_symbol or iterations:
                raise PromotionError(
                    f"native element {index} has incomplete symbol metadata")
            bits_per_symbol = 0
            symbols = []
            total_bits = 0
        if not before and not symbols and not after:
            raise PromotionError(f"native element {index} has no playable carrier data")
        elements.append({
            "index": index,
            "before": before,
            "after": after,
            "symbols": symbols,
            "bits_per_symbol": bits_per_symbol,
            "total_bits": total_bits,
            "payload_bytes": (total_bits + 7) // 8,
            "toggle_at": toggle_at,
            "minimum_period_us": None if period in (0, 0xFFFFFFFF) else period,
        })
    return payload, elements


def _occurrence(element: dict, payload: bytes) -> dict:
    item = {"frame": f"element-{element['index']}"}
    bits = element["total_bits"]
    if bits:
        padding = (-bits) % 8
        value = int.from_bytes(payload, "big") >> padding
        item["arguments"] = {"payload": value}
    return item


def _parse_code(code: str | bytes, elements: list[dict]) -> tuple[dict, int]:
    raw = _code_bytes(code)
    stream = raw[5:]
    cursor = 0
    stage = 2
    sections: dict[int, list[dict]] = {}
    while cursor < len(stream) and stage < 6:
        if stream[cursor] == 0:
            while cursor < len(stream) and stream[cursor] == 0 and stage < 6:
                cursor += 1
                stage += 1
            if cursor >= len(stream) or stage >= 6:
                break
        count = stream[cursor]
        cursor += 1
        occurrences = []
        for _ in range(count):
            if cursor >= len(stream):
                raise PromotionError("native Code ends before its element index")
            index = stream[cursor]
            cursor += 1
            if index >= len(elements):
                raise PromotionError(
                    f"native Code selects element {index}, block has {len(elements)}")
            element = elements[index]
            size = element["payload_bytes"]
            if cursor + size > len(stream):
                raise PromotionError(
                    f"native Code ends inside element {index} payload")
            occurrences.append(_occurrence(element, stream[cursor:cursor + size]))
            cursor += size
        if stage not in (2, 3, 4, 5):
            raise PromotionError(f"native Code uses unsupported carrier stage {stage}")
        sections[stage] = occurrences
        stage += 1

    if cursor < len(stream) and any(stream[cursor:]):
        raise PromotionError("native Code has unparsed command bytes")
    minimum_repeats = raw[4]
    start = sections.get(2, [])
    repeat = sections.get(3, [])
    # Stages 4 and 5 are both once-through sections played after the repeats end, in
    # order - confirmed against `decompiled.c`, where only stage 3 has a repeat condition.
    # The portable `release` phase carries them in sequence.
    release = sections.get(4, []) + sections.get(5, [])
    if not start and not repeat:
        raise PromotionError("native Code has no press or repeat sequence")
    if start:
        press = start
    else:
        # A stage-3-only Code executes its repeat sequence at least once. Repeating the
        # entire occurrence list here lets generic_code derive byte 4 again.
        press = [dict(item) for _ in range(max(1, minimum_repeats)) for item in repeat]
    transmission = {
        "press": press,
        "hold": repeat,
        "release": release,
    }
    # Carried rather than spelled out. Inlining the mandatory runs into `press` matches a
    # tap and then diverges the moment the key is actually held: the firmware plays stage
    # 3 `max(minimum, held + 1)` times, while an inlined press would play the mandatory
    # runs *and* the held ones. Only a count reproduces both.
    if start and repeat and minimum_repeats > 1:
        transmission["hold_minimum"] = minimum_repeats
    return transmission, int.from_bytes(raw[2:4], "little")


def _portable_definition(native: dict, elements: list[dict], used: set[int],
                         default_transmission: dict) -> dict:
    bursts: dict[str, list[int]] = {}
    alphabets: dict[str, dict] = {}
    frames: dict[str, dict] = {}
    for index in sorted(used):
        element = elements[index]
        name = f"element-{index}"
        segments = []
        if element["before"]:
            burst = f"{name}-before"
            bursts[burst] = element["before"]
            segments.append({"burst": burst})
        parameters = {}
        if element["symbols"]:
            alphabet_name = f"{name}-alphabet"
            symbols = {}
            width = element["bits_per_symbol"]
            for value, pulses in enumerate(element["symbols"]):
                burst = f"{name}-symbol-{value}"
                bursts[burst] = pulses
                symbols[format(value, f"0{width}b")] = burst
            alphabets[alphabet_name] = {
                "bits_per_symbol": width,
                "symbols": symbols,
            }
            parameters["payload"] = {"bits": element["total_bits"]}
            segments.append({
                "field": "payload",
                "bits": element["total_bits"],
                "order": "msb",
                "alphabet": alphabet_name,
            })
            at = element.get("toggle_at")
            if at is not None:
                # The firmware substitutes sender state at this bit offset of the run
                # (`ir_vm._toggle` reads element+2). Portable form is the shape RC5 uses:
                # the payload either side of a one-bit state segment. Offsets are
                # most-significant-first, so the leading field starts at
                # `total_bits - at` and the trailing one covers what remains after the
                # toggle's own bit.
                total = element["total_bits"]
                if not 0 <= at < total:
                    raise PromotionError(
                        f"native element {element['index']} places its toggle at bit "
                        f"{at} of a {total}-bit run")
                segments.pop()
                if at:
                    segments.append({"field": "payload", "offset": total - at,
                                     "bits": at, "order": "msb",
                                     "alphabet": alphabet_name})
                segments.append({"state": "toggle", "order": "msb",
                                 "alphabet": alphabet_name})
                trailing = total - at - 1
                if trailing:
                    segments.append({"field": "payload", "offset": 0,
                                     "bits": trailing, "order": "msb",
                                     "alphabet": alphabet_name})
        if element["after"]:
            burst = f"{name}-after"
            bursts[burst] = element["after"]
            segments.append({"burst": burst})
        frame = {"segments": segments}
        if parameters:
            frame["parameters"] = parameters
        if element["minimum_period_us"] is not None:
            frame["minimum_period_us"] = element["minimum_period_us"]
        frames[name] = frame

    period = native.get("carrier_period_ns")
    if not isinstance(period, int) or period <= 0:
        raise PromotionError("native carrier period is missing")
    definition = {
        "schema": ir_protocol.SCHEMA,
        "id": "pending",
        "name": "Structurally imported carrier protocol",
        "modulation": {
            "kind": "carrier",
            "carrier_hz": round(1_000_000_000 / period),
        },
        "parameters": {},
        "bursts": bursts,
        "alphabets": alphabets,
        "frames": frames,
        "transmission": default_transmission,
    }
    if any(element.get("toggle_at") is not None for element in elements):
        definition["state"] = {
            "toggle": {"kind": "toggle", "initial": 0, "advance": "press"}}
    try:
        fingerprint = ir_protocol.semantic_fingerprint(definition)
    except ValueError as exc:
        raise PromotionError(str(exc)) from exc
    definition["id"] = f"structural-{fingerprint}"
    ir_protocol.validate(definition)
    return definition


def _normalised_stages(simulation: ir_vm.Simulation) -> tuple[tuple[bool, tuple[int, ...]], ...]:
    """Emission per section, tagged only by whether that section repeats.

    Comparing raw stage *numbers* rejects correct mappings: a native Code running stages
    (3, 4) rebuilt as (3, 5) emits identical infrared, because the firmware treats every
    stage except 3 as a once-through section. `decompiled.c` gates the repeat condition on
    `stage == 3` and otherwise just increments, so the index of a non-repeating section
    carries no behaviour.

    What must still match is *which* section repeats - putting the tail where the repeats
    go would turn a finish sequence into something a held key emits over and over. Hence
    the flag rather than dropping the stage entirely.
    """
    out = []
    offset = 0
    for stage, count in zip(simulation.sequence_stages, simulation.sequence_word_counts):
        words = simulation.words[offset:offset + count]
        offset += count
        pulses = tuple(
            (word & 0x7FFF) * (1 if word & 0x8000 else -1)
            for word in words if word & 0x7FFF)
        out.append((stage == 3, ir_vm.normalise_pulses(pulses)))
    return tuple(out)


def _prove(native_payload: bytes, native_code: str | bytes, definition: dict,
           transmission: dict, pre_silence_us: int) -> None:
    try:
        # Keep the compiler's own portable-render/VM gate enabled, then independently
        # compare that rebuilt VM result with the source VM below. Both seams have to
        # hold; source-vs-rebuilt agreement alone could preserve a shared compiler bug.
        emitted = ir_emit.emit_generic(
            definition, parameters={}, transmission=transmission)
        emitted_payload = protocol_json.assemble([emitted])
        emitted_code = code_builder.generic_code(
            definition, ir_emit.element_order(definition), {}, 0,
            pre_silence_us=pre_silence_us, transmission=transmission)
        original = bytearray(_code_bytes(native_code))
        original[0:2] = b"\0\0"
        # Held counts at or below the block's mandatory minimum all clamp to that
        # minimum, so a run of (0, 1) alone cannot tell a carried repeat count apart from
        # one inlined into the press stage - both emit the same thing until the key is
        # held longer than the protocol demands. Reach past it.
        for held in sorted({0, 1, 2, original[4] + 1}):
            native = ir_vm.simulate_transmission(
                native_payload, original, held_replays=held)
            rebuilt = ir_vm.simulate_transmission(
                emitted_payload, emitted_code, held_replays=held)
            if native.carrier_hz != rebuilt.carrier_hz:
                raise PromotionError(
                    f"carrier changed from {native.carrier_hz} to {rebuilt.carrier_hz} Hz")
            if _normalised_stages(native) != _normalised_stages(rebuilt):
                raise PromotionError(
                    f"portable rebuild changes native lifecycle when held={held}")
    except (KeyError, ValueError, ir_vm.IrVmError) as exc:
        if isinstance(exc, PromotionError):
            raise
        raise PromotionError(str(exc)) from exc


def promote(definition: dict, native_codes) -> Promotion:
    """Return a proved portable replacement for one block and all Codes using it."""
    unique = {}
    for code in native_codes:
        unique.setdefault(code_key(code), code)
    if not unique:
        raise PromotionError("native protocol has no command Codes")

    native_payload, elements = _element_table(definition)
    parsed = {}
    used: set[int] = set()
    pre_silence = {}
    for key, code in unique.items():
        transmission, silence = _parse_code(code, elements)
        parsed[key] = transmission
        pre_silence[key] = silence
        for phase in ir_protocol.PHASES:
            used.update(int(item["frame"].removeprefix("element-"))
                        for item in transmission.get(phase, []))

    first = next(iter(parsed.values()))
    portable = _portable_definition(definition, elements, used, first)
    for key, code in unique.items():
        _prove(native_payload, code, portable, parsed[key], pre_silence[key])
    return Promotion(portable, parsed)
