#!/usr/bin/env python3
"""Portable IR protocol grammar: semantic parameters -> emitted waveform.

Most modulated IR protocols are combinations of a small vocabulary: named bursts,
fixed-width fields, a symbol alphabet, bit order, and one or more frame shapes. A
transmission then composes those frames as a key is pressed, held, and released, with
optional sender-owned state such as an RC5 toggle bit. NEC and JVC use pulse distance,
Sony SIRC uses pulse width, RC5/RC6 use biphase symbols, and RCMM/XMP use symbols wider
than one bit. Keeping the grammar at that level describes the signal without assuming
that a particular remote knows how to encode it.

This module answers only two questions: is the protocol definition well formed, and what
waveform does a parameter set mean? Remote backends separately declare whether they can
lower that meaning to native protocol bytecode, fall back to a raw waveform, or must
refuse it. A protocol being describable here is therefore never a claim that every remote
can reproduce it.
"""
from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
import os
from pathlib import Path

from . import ir_signal, paths

SCHEMA = "afterglow-ir-protocol/1"
# The application ships no protocol definitions: every protocol it uses is reconstructed
# from the IrProto blocks of the configuration being imported, or generated from an
# archive record. `AFTERGLOW_PROTOCOLS` points at a directory of them anyway - an external
# database, or the suite's own fixtures - and is read at import so a subprocess inherits
# the choice.
LIBRARY = Path(os.environ["AFTERGLOW_PROTOCOLS"]).expanduser() \
    if os.environ.get("AFTERGLOW_PROTOCOLS") else paths.library("protocols")
ORDERS = ("lsb", "msb")
PHASES = ir_signal.PHASES
TRANSMISSION_FIELDS = ir_signal.TRANSMISSION_FIELDS
# Everything a frame may carry. `minimum_period_us` pads the frame to a repeat period,
# which is how every inter-frame gap in this library is expressed.
FRAME_FIELDS = frozenset({"segments", "parameters", "minimum_period_us"})
MEANING_FIELDS = (
    "modulation", "parameters", "state", "bursts", "alphabets", "frames",
    "transmission",
)


def _integer(value, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer, not bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            # Device definitions traditionally store bare hexadecimal bytes ("7A").
            try:
                return int(value, 16)
            except ValueError as exc:
                raise ValueError(f"{label} is not an integer: {value!r}") from exc
    raise ValueError(f"{label} is not an integer: {value!r}")


def _validate_transmission(transmission: dict, frames: dict, parameters: dict, *,
                           label: str) -> None:
    if not isinstance(transmission, dict):
        raise ValueError(f"{label} must be an object")
    unknown_phases = set(transmission) - set(TRANSMISSION_FIELDS)
    if unknown_phases:
        raise ValueError(f"{label} has unknown phases {sorted(unknown_phases)}")
    if not transmission.get("press"):
        raise ValueError(f"{label} needs a non-empty press sequence")
    minimum = transmission.get("hold_minimum", 0)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
        raise ValueError(f"{label} hold_minimum must be a non-negative integer")
    if minimum > 1 and not transmission.get("hold"):
        raise ValueError(
            f"{label} sets hold_minimum {minimum} but has no hold sequence to repeat")
    for phase in PHASES:
        sequence = transmission.get(phase, [])
        if not isinstance(sequence, list):
            raise ValueError(f"{label} phase {phase!r} must be a list")
        for item in sequence:
            if not isinstance(item, dict) or not item.get("frame"):
                raise ValueError(f"{label} phase {phase!r} needs frame references")
            unknown_keys = set(item) - {"frame", "count", "bind", "arguments"}
            if unknown_keys:
                raise ValueError(
                    f"{label} phase {phase!r} item has unknown keys "
                    f"{sorted(unknown_keys)}")
            if item["frame"] not in frames:
                raise ValueError(
                    f"{label} phase {phase!r} names unknown frame {item['frame']!r}")
            count = item.get("count", 1)
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise ValueError(f"{label} phase {phase!r} frame count must be positive")
            bindings = item.get("bind", {})
            arguments = item.get("arguments", {})
            if not isinstance(bindings, dict):
                raise ValueError(f"{label} phase {phase!r} frame bindings must be an object")
            if not isinstance(arguments, dict):
                raise ValueError(f"{label} phase {phase!r} frame arguments must be an object")
            overlap = set(bindings) & set(arguments)
            if overlap:
                raise ValueError(
                    f"{label} phase {phase!r} supplies frame parameters twice "
                    f"{sorted(overlap)}")
            local = frames[item["frame"]].get("parameters") or {}
            supplied = set(bindings) | set(arguments)
            if supplied != set(local):
                raise ValueError(
                    f"{label} phase {phase!r} must supply exactly frame parameters "
                    f"{sorted(local)}")
            for local_name, source_name in bindings.items():
                if not isinstance(source_name, str) or source_name not in parameters:
                    raise ValueError(
                        f"{label} phase {phase!r} binding {local_name!r} names "
                        f"unknown protocol parameter {source_name!r}")
                if local[local_name]["bits"] != parameters[source_name]["bits"]:
                    raise ValueError(
                        f"{label} phase {phase!r} binding {local_name!r} has a "
                        "different bit width")
            for local_name, value in arguments.items():
                width = local[local_name]["bits"]
                number = _integer(value, f"frame argument {local_name!r}")
                if number < 0 or number >= 1 << width:
                    raise ValueError(
                        f"{label} phase {phase!r} argument {local_name!r} does not "
                        f"fit in {width} bits")


def _validate_modulation(modulation: dict) -> None:
    if modulation.get("kind") not in ("carrier", "unmodulated"):
        raise ValueError("modulation.kind must be 'carrier' or 'unmodulated'")
    if modulation.get("kind") == "carrier":
        carrier = modulation.get("carrier_hz")
        if not isinstance(carrier, int) or carrier <= 0:
            raise ValueError("carrier modulation needs a positive integer carrier_hz")
        duty = modulation.get("duty_cycle")
        if duty is not None and not isinstance(duty, (int, float)):
            raise ValueError("duty_cycle must be numeric")
        if duty is not None and not 0 < duty <= 1:
            raise ValueError("duty_cycle must be greater than zero and at most one")


def _validate_bursts(bursts: dict) -> None:
    for name, pulses in bursts.items():
        if not isinstance(pulses, list) or not pulses:
            raise ValueError(f"burst {name!r} needs a non-empty duration list")
        if any(not isinstance(pulse, int) or pulse == 0 for pulse in pulses):
            raise ValueError(f"burst {name!r} durations must be non-zero integers")


def _validate_alphabets(alphabets: dict, bursts: dict) -> None:
    for name, alphabet in alphabets.items():
        width = alphabet.get("bits_per_symbol")
        symbols = alphabet.get("symbols")
        if not isinstance(width, int) or not 1 <= width <= 8:
            raise ValueError(f"alphabet {name!r} needs bits_per_symbol in 1..8")
        expected = {format(value, f"0{width}b") for value in range(1 << width)}
        if not isinstance(symbols, dict) or set(symbols) != expected:
            raise ValueError(f"alphabet {name!r} must define exactly {sorted(expected)}")
        missing = set(symbols.values()) - set(bursts)
        if missing:
            raise ValueError(f"alphabet {name!r} names unknown bursts {sorted(missing)}")


def _validate_parameters(parameters) -> None:
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    for name, parameter in parameters.items():
        bits = parameter.get("bits")
        if not isinstance(bits, int) or bits <= 0:
            raise ValueError(f"parameter {name!r} needs a positive bit width")


def _validate_state(state) -> None:
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    for name, definition in state.items():
        if definition.get("kind") != "toggle":
            raise ValueError(f"state {name!r} has an unknown kind")
        initial = definition.get("initial", 0)
        if isinstance(initial, bool) or not isinstance(initial, int) or initial not in (0, 1):
            raise ValueError(f"toggle state {name!r} initial value must be 0 or 1")
        if definition.get("advance", "press") not in PHASES:
            raise ValueError(f"toggle state {name!r} has an invalid advance phase")


def validate(spec: dict) -> None:
    """Reject protocol definitions whose waveform meaning is ambiguous.

    The sections below run in a fixed order, and it is part of the behaviour: a
    definition wrong in two ways reports the earlier one, and the tests name the message
    they expect. Reordering these calls changes which error a caller sees.
    """
    if spec.get("schema") != SCHEMA:
        raise ValueError(f"expected schema {SCHEMA!r}, got {spec.get('schema')!r}")
    if not spec.get("id"):
        raise ValueError("a portable IR protocol needs an id")
    bursts = spec.get("bursts") or {}
    parameters = spec.get("parameters") or {}
    state = spec.get("state") or {}
    alphabets = spec.get("alphabets") or {}
    _validate_modulation(spec.get("modulation") or {})
    _validate_bursts(bursts)
    _validate_alphabets(alphabets, bursts)
    _validate_parameters(parameters)
    _validate_state(state)

    frames = spec.get("frames") or {}
    if not isinstance(frames, dict) or not frames:
        raise ValueError("a portable IR protocol needs frames")
    for frame_name, frame in frames.items():
        # A key nobody reads is a silently wrong waveform: it validates, is never
        # emitted, and the frames it was meant to affect come out unchanged.
        unknown = set(frame) - FRAME_FIELDS
        if unknown:
            raise ValueError(
                f"frame {frame_name!r} has unknown fields {sorted(unknown)}; "
                f"a frame carries {sorted(FRAME_FIELDS)}")
        frame_parameters = frame.get("parameters") or {}
        if not isinstance(frame_parameters, dict):
            raise ValueError(f"frame {frame_name!r} parameters must be an object")
        overlap = set(frame_parameters) & set(parameters)
        if overlap:
            raise ValueError(
                f"frame {frame_name!r} parameters shadow protocol parameters "
                f"{sorted(overlap)}")
        for name, parameter in frame_parameters.items():
            bits = parameter.get("bits")
            if not isinstance(bits, int) or bits <= 0:
                raise ValueError(
                    f"frame {frame_name!r} parameter {name!r} needs a positive bit width")
        segments = frame.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ValueError(f"frame {frame_name!r} needs segments")
        for segment in segments:
            choices = set(segment) & {"burst", "field", "constant", "state"}
            if len(choices) != 1:
                raise ValueError(
                    f"frame {frame_name!r} segment needs one of "
                    "burst/field/constant/state")
            if "burst" in segment:
                if segment["burst"] not in bursts:
                    raise ValueError(f"frame {frame_name!r} names unknown burst "
                                     f"{segment['burst']!r}")
                continue
            available_parameters = {**parameters, **frame_parameters}
            if "field" in segment and segment["field"] not in available_parameters:
                raise ValueError(f"frame {frame_name!r} names unknown parameter "
                                 f"{segment['field']!r}")
            if "state" in segment and segment["state"] not in state:
                raise ValueError(f"frame {frame_name!r} names unknown state "
                                 f"{segment['state']!r}")
            if "state" in segment and segment.get("bits", 1) != 1:
                raise ValueError(f"frame {frame_name!r} toggle state must be one bit")
            if segment.get("order", "lsb") not in ORDERS:
                raise ValueError(f"frame {frame_name!r} has invalid field order")
            if segment.get("alphabet", "bits") not in alphabets:
                raise ValueError(f"frame {frame_name!r} names an unknown alphabet")
            bits = segment.get("bits")
            if bits is not None and (not isinstance(bits, int) or bits <= 0):
                raise ValueError(f"frame {frame_name!r} field bits must be positive")
            offset = segment.get("offset", 0)
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValueError(f"frame {frame_name!r} field offset must be non-negative")
            if offset and "field" not in segment:
                raise ValueError(
                    f"frame {frame_name!r} only parameter fields can have an offset")
            if "field" in segment:
                width = available_parameters[segment["field"]]["bits"]
                selected = bits if bits is not None else width - offset
                if selected <= 0 or offset + selected > width:
                    raise ValueError(
                        f"frame {frame_name!r} field slice exceeds parameter width")
            if segment.get("transform", "identity") not in ("identity", "invert"):
                raise ValueError(f"frame {frame_name!r} has an unknown transform")
        minimum = frame.get("minimum_period_us")
        if (minimum is not None
                and (isinstance(minimum, bool) or not isinstance(minimum, int)
                     or minimum <= 0)):
            raise ValueError(
                f"frame {frame_name!r} minimum_period_us must be positive")

    transmission = spec.get("transmission")
    if transmission is None:
        if "press" not in frames:
            raise ValueError(
                "a protocol without transmission sequences needs a press frame")
        return
    _validate_transmission(transmission, frames, parameters, label="transmission")


class Protocol:
    """One portable protocol definition whose waveform meaning is known to be well formed.

    `validate` runs once, here. Holding a `Protocol` is therefore the proof that it
    passed, and no consumer needs to re-check a definition it was handed - a definition
    cannot become invalid, and re-validating on every render walks every frame, segment
    and alphabet again to reach the same answer.

    The source mapping is retained and exposed unchanged as `raw`. A field this revision
    does not model must survive being loaded and written back, so nothing here
    normalises, reorders or fills in what it read.
    """

    __slots__ = ("_spec",)

    def __init__(self, spec: dict) -> None:
        validate(spec)
        self._spec = spec

    def __repr__(self) -> str:
        return f"Protocol({self._spec['id']!r})"

    @property
    def raw(self) -> dict:
        """The definition exactly as it was supplied."""
        return self._spec

    @property
    def id(self) -> str:
        return self._spec["id"]

    @property
    def modulation(self) -> dict:
        return self._spec["modulation"]

    @property
    def carrier_hz(self) -> int | None:
        """The carrier, or None for an unmodulated protocol."""
        modulation = self._spec["modulation"]
        return modulation.get("carrier_hz") if modulation["kind"] == "carrier" else None

    def fingerprint(self) -> str:
        """Stable identity of this protocol's waveform meaning, excluding prose."""
        meaning = {field: self._spec[field]
                   for field in MEANING_FIELDS if field in self._spec}
        canonical = json.dumps(
            meaning, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return hashlib.sha256(canonical).hexdigest()[:12]

    def initial_state(self) -> dict[str, int]:
        """The sender state before its first transmission."""
        return _state_values(self._spec)

    def hold_minimum(self, sequence: dict | None = None) -> int:
        """How many times the hold phase must run, even for a tap."""
        return _hold_minimum(self._spec, sequence)

    def frame(self, parameters: dict, frame_name: str = "press", *,
              state: dict | None = None, bindings: dict | None = None,
              arguments: dict | None = None) -> list[int]:
        """Render one named frame to signed microsecond durations."""
        _definition, values, declarations = _frame_context(
            self._spec, parameters, frame_name, bindings=bindings, arguments=arguments)
        return _render_occurrence(self._spec, {
            "phase": "frame", "frame": frame_name, "count": 1,
            "values": values, "declarations": declarations,
        }, _state_values(self._spec, state))

    def resolve_transmission(self, parameters: dict, *,
                             sequence: dict | None = None) -> tuple[dict, ...]:
        """Resolve a lifecycle into backend-neutral frame occurrences."""
        if sequence is not None:
            _validate_transmission(
                sequence, self._spec["frames"], self._spec.get("parameters") or {},
                label="signal transmission")
        resolved = []
        for phase in PHASES:
            items = (sequence.get(phase, []) if sequence is not None
                     else _phase_sequence(self._spec, phase))
            for item in items:
                _definition, values, declarations = _frame_context(
                    self._spec, parameters, item["frame"],
                    bindings=item.get("bind"), arguments=item.get("arguments"))
                resolved.append({
                    "phase": phase,
                    "frame": item["frame"],
                    "count": item.get("count", 1),
                    "values": values,
                    "declarations": declarations,
                })
        return tuple(resolved)

    def transmission(self, parameters: dict, phase: str = "press", *,
                     state: dict | None = None,
                     sequence: dict | None = None) -> tuple[list[int], dict[str, int]]:
        """Render one key-lifecycle phase and return its updated sender state."""
        if phase not in PHASES:
            raise ValueError(f"unknown transmission phase {phase!r}")
        occurrences = self.resolve_transmission(parameters, sequence=sequence)
        state_values = _state_values(self._spec, state)
        for name, definition in (self._spec.get("state") or {}).items():
            if definition.get("advance", "press") == phase:
                state_values[name] ^= 1

        out: list[int] = []
        for occurrence in occurrences:
            if occurrence["phase"] != phase:
                continue
            pulses = _render_occurrence(self._spec, occurrence, state_values)
            for _ in range(occurrence["count"]):
                _append(out, pulses)
        return out, state_values


class Catalog:
    """The installed portable protocols, each validated once as it is read.

    A lookup used to mean re-reading and re-validating the whole library, which is why
    callers grew their own prevalidated mappings to hand around. Reading the library is
    the expensive step and it happens here, once per catalogue.

    The source is resolved when a catalogue is built, never bound as a default, so
    reassigning `LIBRARY` - which is how the suite points at fixtures, and how a protocol
    database outside this repository is selected - still takes effect.
    """

    __slots__ = ("_protocols", "_source")

    def __init__(self, source=None) -> None:
        self._source = LIBRARY if source is None else source
        found: dict[str, Protocol] = {}
        if isinstance(self._source, Mapping):
            for protocol_id, spec in self._source.items():
                entry = spec if isinstance(spec, Protocol) else Protocol(spec)
                if entry.id != protocol_id:
                    raise ValueError(
                        f"portable protocol key {protocol_id!r} contains id {entry.id!r}")
                found[protocol_id] = entry
        else:
            for path in sorted(Path(self._source).glob("*.json")):
                entry = Protocol(json.loads(Path(path).read_text()))
                if entry.id in found:
                    raise ValueError(f"duplicate portable protocol id {entry.id!r}")
                found[entry.id] = entry
        self._protocols = found

    def __getitem__(self, protocol_id: str) -> Protocol:
        """One protocol, or a failure that says which problem it is.

        An empty library and a library missing one particular protocol are different
        situations with different fixes, and reporting both as "no portable IR protocol
        'nec1'" sends someone looking for a corrupt entry when the real answer is that
        there are no entries at all. That message reached the interface verbatim.
        """
        try:
            return self._protocols[protocol_id]
        except KeyError:
            if not self._protocols:
                raise LookupError(
                    f"no IR protocol definitions are installed, so {protocol_id!r} cannot "
                    f"be resolved. Afterglow looks for them in {self._source}. Install or "
                    "select a protocol database before importing or building a "
                    "configuration."
                ) from None
            raise LookupError(
                f"no portable IR protocol {protocol_id!r} in {self._source} "
                f"({len(self._protocols)} installed)") from None

    def get(self, protocol_id: str, default=None) -> Protocol | None:
        return self._protocols.get(protocol_id, default)

    def __contains__(self, protocol_id: object) -> bool:
        return protocol_id in self._protocols

    def __iter__(self):
        return iter(self._protocols)

    def __len__(self) -> int:
        return len(self._protocols)

    def items(self):
        return self._protocols.items()

    def raw(self) -> dict[str, dict]:
        """A plain, mutable id -> definition mapping of the same objects."""
        return {protocol_id: entry.raw
                for protocol_id, entry in self._protocols.items()}


def semantic_fingerprint(spec: dict) -> str:
    """Stable identity of a protocol's waveform meaning, excluding prose metadata.

    Backends may calibrate native output against a particular semantic revision. This
    fingerprint lets them refuse a changed definition instead of silently continuing to
    emit timings calibrated for the old one. Names and provenance do not affect meaning.
    """
    return Protocol(spec).fingerprint()


def load(path) -> dict:
    return Protocol(json.loads(Path(path).read_text())).raw


def catalog(library=None) -> dict[str, dict]:
    """Every installed portable protocol, keyed by id.

    `library` resolves to `LIBRARY` at *call* time, not at import time. Binding it as a
    default parameter froze the path when this module was first imported, so reassigning
    `ir_protocol.LIBRARY` - which is how a test points at an empty directory, and how a
    protocol database living outside this repository would ever be selected - changed
    nothing at all.

    Returns plain definitions. Callers that hold the result and look protocols up in it
    want `Catalog`, which keeps them validated.
    """
    return Catalog(library).raw()


def protocol(protocol_id: str, library=None) -> dict:
    """One portable protocol definition, or a failure that says which problem it is."""
    return Catalog(library)[protocol_id].raw


def _append(out: list[int], pulses) -> None:
    """Append durations, coalescing adjacent equal levels at symbol boundaries."""
    for pulse in pulses:
        if out and (out[-1] > 0) == (pulse > 0):
            out[-1] += pulse
        else:
            out.append(pulse)


def _state_values(spec: dict, values: dict | None = None) -> dict[str, int]:
    definitions = spec.get("state") or {}
    supplied = dict(values or {})
    unknown = set(supplied) - set(definitions)
    if unknown:
        raise ValueError(f"unknown protocol state {sorted(unknown)}")
    out = {}
    for name, definition in definitions.items():
        value = supplied.get(name, definition.get("initial", 0))
        if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1):
            raise ValueError(f"toggle state {name!r} value must be 0 or 1")
        out[name] = value
    return out


def initial_state(spec: dict) -> dict[str, int]:
    """The sender state before its first transmission."""
    return Protocol(spec).initial_state()


def _segment_value(segment: dict, parameters: dict, definitions: dict,
                   state: dict) -> tuple[int, int]:
    if "field" in segment:
        name = segment["field"]
        if name not in parameters:
            raise ValueError(f"missing protocol parameter {name!r}")
        value = _integer(parameters[name], f"parameter {name!r}")
        source_bits = definitions[name]["bits"]
        if value < 0 or value >= 1 << source_bits:
            raise ValueError(
                f"parameter {name!r} value {value} does not fit in {source_bits} bits")
        offset = segment.get("offset", 0)
        bits = segment.get("bits", source_bits - offset)
        value = (value >> offset) & ((1 << bits) - 1)
    elif "state" in segment:
        name = segment["state"]
        value = state[name]
        # The only state primitive currently justified by real examples is a one-bit
        # toggle. Keeping that explicit avoids silently inventing counter semantics.
        bits = 1
    else:
        value = _integer(segment["constant"], "constant field")
        bits = segment.get("bits")
        if bits is None:
            raise ValueError("a constant frame field needs bits")
    if value < 0 or value >= 1 << bits:
        raise ValueError(f"field value {value} does not fit in {bits} bits")
    if segment.get("transform", "identity") == "invert":
        value ^= (1 << bits) - 1
    return value, bits


def frame(spec: dict, parameters: dict, frame_name: str = "press", *,
          state: dict | None = None, bindings: dict | None = None,
          arguments: dict | None = None) -> list[int]:
    """Render one named frame to signed microsecond durations."""
    return Protocol(spec).frame(
        parameters, frame_name, state=state, bindings=bindings, arguments=arguments)


def _hold_minimum(spec: dict, sequence: dict | None = None) -> int:
    source = sequence if sequence is not None else (spec.get("transmission") or {})
    return int(source.get("hold_minimum", 0) or 0)


def hold_minimum(spec: dict, sequence: dict | None = None) -> int:
    """How many times the hold phase must run, even for a tap.

    A signal-level lifecycle replaces the protocol's default wholesale, so the count
    comes from whichever object supplied the phases.

    Reads the count without validating the definition, which is what lets a caller ask
    about a lifecycle it is still assembling.
    """
    return _hold_minimum(spec, sequence)


def _phase_sequence(spec: dict, phase: str) -> list[dict]:
    """Explicit lifecycle sequence, or the compatible v1 frame convention."""
    transmission = spec.get("transmission")
    if transmission is not None:
        return transmission.get(phase, [])
    if phase == "press":
        return [{"frame": "press"}]
    if phase == "hold":
        return [{"frame": "repeat" if "repeat" in spec["frames"] else "press"}]
    return []


def _frame_context(spec: dict, parameters: dict, frame_name: str, *,
                   bindings: dict | None = None,
                   arguments: dict | None = None) -> tuple[dict, dict, dict]:
    """Resolve protocol and frame-local values once for every semantic consumer."""
    try:
        definition = spec["frames"][frame_name]
    except KeyError:
        raise ValueError(
            f"protocol {spec['id']!r} has no {frame_name!r} frame") from None

    declarations = dict(spec["parameters"])
    values = {
        name: _integer(value, f"parameter {name!r}")
        for name, value in parameters.items()
        if name in declarations
    }
    local = definition.get("parameters") or {}
    supplied_bindings = dict(bindings or {})
    supplied_arguments = dict(arguments or {})
    if set(supplied_bindings) & set(supplied_arguments):
        raise ValueError(
            f"frame {frame_name!r} supplies local parameters as both bindings and "
            "arguments")
    if set(supplied_bindings) | set(supplied_arguments) != set(local):
        raise ValueError(
            f"frame {frame_name!r} must supply exactly frame parameters {sorted(local)}")
    for local_name, source_name in supplied_bindings.items():
        if source_name not in spec["parameters"]:
            raise ValueError(
                f"frame {frame_name!r} binding {local_name!r} names unknown protocol "
                f"parameter {source_name!r}")
        declarations[local_name] = local[local_name]
        if source_name not in parameters:
            raise ValueError(f"missing protocol parameter {source_name!r}")
        values[local_name] = _integer(
            parameters[source_name], f"parameter {source_name!r}")
    for local_name, value in supplied_arguments.items():
        declarations[local_name] = local[local_name]
        values[local_name] = _integer(value, f"frame argument {local_name!r}")
    return definition, values, declarations


def resolve_transmission(spec: dict, parameters: dict, *,
                         sequence: dict | None = None) -> tuple[dict, ...]:
    """Resolve a lifecycle into backend-neutral frame occurrences.

    Each occurrence retains its phase and count while replacing bindings and literal
    arguments with one concrete value/declaration context. Waveform rendering and native
    compilers consume this result so a frame-local payload cannot mean one thing in each.
    A signal-level ``sequence`` replaces the protocol's default lifecycle.
    """
    return Protocol(spec).resolve_transmission(parameters, sequence=sequence)


def _render_occurrence(spec: dict, occurrence: dict, state: dict) -> list[int]:
    definition = spec["frames"][occurrence["frame"]]
    out: list[int] = []
    for segment in definition["segments"]:
        if "burst" in segment:
            _append(out, spec["bursts"][segment["burst"]])
            continue
        value, bits = _segment_value(
            segment, occurrence["values"], occurrence["declarations"], state)
        order = segment.get("order", "lsb")
        emitted = ([(value >> index) & 1 for index in range(bits)] if order == "lsb"
                   else [(value >> index) & 1 for index in range(bits - 1, -1, -1)])
        alphabet = spec["alphabets"][segment.get("alphabet", "bits")]
        width = alphabet["bits_per_symbol"]
        if len(emitted) % width:
            raise ValueError(f"field width {bits} is not divisible by {width}-bit symbols")
        for start in range(0, len(emitted), width):
            key = "".join(str(bit) for bit in emitted[start:start + width])
            burst = alphabet["symbols"][key]
            _append(out, spec["bursts"][burst])

    minimum = definition.get("minimum_period_us")
    elapsed = sum(abs(pulse) for pulse in out)
    if minimum is not None and elapsed < minimum:
        _append(out, [-(minimum - elapsed)])
    return out


def transmission(spec: dict, parameters: dict, phase: str = "press", *,
                  state: dict | None = None,
                  sequence: dict | None = None) -> tuple[list[int], dict[str, int]]:
    """Render one key-lifecycle phase and return its updated sender state.

    Toggle state advances before the named phase is emitted. The returned value is then
    reused for hold/release and passed back on the next press, so one press and all of its
    repeats carry the same toggle while the next distinct press carries the other value.
    """
    return Protocol(spec).transmission(
        parameters, phase, state=state, sequence=sequence)


def _resolved(signal: dict, library) -> Protocol:
    """The validated protocol a semantic signal names."""
    ir_signal.validate(signal)
    if signal["kind"] != "protocol":
        raise ValueError(f"expected a protocol signal, got {signal['kind']!r}")
    return Catalog(library)[signal["protocol"]]


def render(signal: dict, *, frame_name: str = "press", library=None) -> dict:
    """Render a semantic protocol signal as a portable waveform signal."""
    spec = _resolved(signal, library)
    return ir_signal.waveform(
        spec.frame(signal["parameters"], frame_name),
        name=signal.get("name", ""),
        carrier_hz=spec.carrier_hz,
        provenance={"kind": "synthesized", "protocol": spec.id},
    )


def render_transmission(signal: dict, *, phase: str = "press", state: dict | None = None,
                        library=None) -> tuple[dict | None, dict[str, int]]:
    """Render a press/hold/release phase; an empty release returns ``None``."""
    spec = _resolved(signal, library)
    pulses, next_state = spec.transmission(
        signal["parameters"], phase, state=state,
        sequence=signal.get("transmission"))
    if not pulses:
        return None, next_state
    waveform = ir_signal.waveform(
        pulses,
        name=signal.get("name", ""),
        carrier_hz=spec.carrier_hz,
        provenance={"kind": "synthesized", "protocol": spec.id, "phase": phase},
    )
    return waveform, next_state
