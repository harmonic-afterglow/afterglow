#!/usr/bin/env python3
"""Portable IR signals: the boundary between a device and a remote backend.

A device command says *what* to transmit. A remote backend says how to encode it in
that remote's configuration. Keeping those separate is what lets one device library
serve Harmony PK remotes now and other architectures later.

Signals are a discriminated union:

``protocol``
    A named protocol plus semantic parameters such as address and command.
``waveform``
    A measured carrier and signed microsecond durations. Positive values are marks;
    negative values are spaces. Optional ``sections`` retain an intro/repeat boundary
    when a source format such as Pronto carries one; the durations remain stored once.
``backend-opaque``
    Native evidence an importer can preserve but cannot yet translate.

Backend details may live under ``native`` as optional lossless import evidence. The
portable meaning never depends on those fields.
Derived values such as pulse count and total duration are deliberately not serialized:
two authoritative copies of the same fact eventually disagree.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "afterglow-ir-signal/1"
LEGACY_CAPTURE_SCHEMA = "afterglow-ir-capture/1"
KINDS = ("protocol", "waveform", "backend-opaque")

# The key lifecycle, and the keys a `transmission` object may carry beside it. Defined
# here rather than in `ir_protocol` because both modules validate transmissions and
# `ir_protocol` imports this one; two hand-kept copies drifted apart the moment a field
# was added. `ir_protocol` re-exports these under the same names.
PHASES = ("press", "hold", "release")
# How many times the hold phase must run before a key counts as released - a tap on a
# protocol that mandates four frames still emits four. It is a property of the protocol,
# not of any remote: it says what a receiver needs to see, and every backend has to
# honour it somehow, whether by a repeat counter or by emitting the frames outright.
TRANSMISSION_FIELDS = PHASES + ("hold_minimum",)


def protocol_signal(protocol: str, parameters: dict, *, name: str = "",
                    repeat: dict | None = None, provenance: dict | None = None,
                    native: dict | None = None,
                    transmission: dict | None = None) -> dict:
    """Create a semantic protocol signal, independent of any remote's byte format."""
    out = {
        "schema": SCHEMA,
        "kind": "protocol",
        "protocol": protocol,
        "parameters": dict(parameters),
    }
    if name:
        out["name"] = name
    if repeat:
        out["repeat"] = dict(repeat)
    if transmission is not None:
        # A transmission carries phase lists plus scalar settings such as
        # `hold_minimum`; only the lists need copying element by element.
        out["transmission"] = {
            key: ([dict(item) for item in value] if isinstance(value, list) else value)
            for key, value in transmission.items()
        }
    if provenance:
        out["provenance"] = dict(provenance)
    if native:
        out["native"] = dict(native)
    validate(out)
    return out


def waveform(pulses_us, *, name: str = "", carrier_hz: int | None = None,
             sections: dict | None = None, provenance: dict | None = None,
             native: dict | None = None) -> dict:
    """Create a portable waveform signal without redundant derived fields."""
    out = {
        "schema": SCHEMA,
        "kind": "waveform",
        "name": name or f"capture-{len(pulses_us)}",
        "pulses_us": [int(pulse) for pulse in pulses_us],
    }
    if carrier_hz is not None:
        out["carrier_hz"] = int(carrier_hz)
    if sections is not None:
        out["sections"] = dict(sections)
    if provenance:
        out["provenance"] = dict(provenance)
    if native:
        out["native"] = dict(native)
    validate(out)
    return out


def backend_opaque(native: dict, *, name: str = "",
                   provenance: dict | None = None) -> dict:
    """Preserve a source backend's command when no portable meaning is known."""
    out = {"schema": SCHEMA, "kind": "backend-opaque", "native": dict(native)}
    if name:
        out["name"] = name
    if provenance:
        out["provenance"] = dict(provenance)
    validate(out)
    return out


def normalise(spec: dict) -> dict:
    """Return the current signal shape, accepting the old capture schema on input.

    An old importer mistook a container's u16 word count for the first negative pulse. Its
    checked-in captures can be recognised exactly: ``pulse_count == len(pulses)`` and
    the first value is ``-(len(pulses)-1)``. Removing that value makes the portable
    waveform semantic; a source backend may separately retain its exact native header.
    """
    if spec.get("schema") == SCHEMA:
        out = dict(spec)
        validate(out)
        return out
    if spec.get("schema") not in (None, LEGACY_CAPTURE_SCHEMA):
        raise ValueError(f"unknown IR signal schema {spec.get('schema')!r}")

    pulses = [int(pulse) for pulse in spec.get("pulses_us") or []]
    if (spec.get("pulse_count") == len(pulses)
            and pulses
            and pulses[0] == -(len(pulses) - 1)):
        pulses = pulses[1:]

    provenance = dict(spec.get("provenance") or {})
    if spec.get("learned_with") and not provenance:
        provenance = {"kind": "measured", "tool": spec["learned_with"]}

    out = waveform(
        pulses,
        name=spec.get("name", ""),
        carrier_hz=spec.get("carrier_hz"),
        provenance=provenance,
        native=dict(spec.get("native") or {}),
    )
    if spec.get("fingerprint"):
        out["fingerprint"] = spec["fingerprint"]
    return out


def validate(spec: dict) -> None:
    """Reject ambiguous signals before a backend tries to compile them."""
    if spec.get("schema") != SCHEMA:
        raise ValueError(f"expected schema {SCHEMA!r}, got {spec.get('schema')!r}")
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown IR signal kind {kind!r} (expected one of {KINDS})")
    if kind == "protocol":
        if not spec.get("protocol") or not isinstance(spec.get("parameters"), dict):
            raise ValueError("a protocol signal needs protocol and parameters")
        transmission = spec.get("transmission")
        if transmission is not None:
            if not isinstance(transmission, dict):
                raise ValueError("a protocol signal transmission must be an object")
            unknown = set(transmission) - set(TRANSMISSION_FIELDS)
            if unknown:
                raise ValueError(
                    f"a protocol signal transmission has unknown phases {sorted(unknown)}")
            if not transmission.get("press"):
                raise ValueError(
                    "a protocol signal transmission needs a non-empty press sequence")
            for phase in PHASES:
                sequence = transmission.get(phase, [])
                if not isinstance(sequence, list):
                    raise ValueError(
                        f"protocol signal transmission phase {phase!r} must be a list")
                for item in sequence:
                    if (not isinstance(item, dict)
                            or not isinstance(item.get("frame"), str)
                            or not item["frame"]):
                        raise ValueError(
                            f"protocol signal transmission phase {phase!r} needs "
                            "frame references")
                    count = item.get("count", 1)
                    if (isinstance(count, bool) or not isinstance(count, int)
                            or count <= 0):
                        raise ValueError(
                            f"protocol signal transmission phase {phase!r} frame count "
                            "must be positive")
                    for key in ("bind", "arguments"):
                        value = item.get(key, {})
                        if (not isinstance(value, dict)
                                or any(not isinstance(name, str) for name in value)):
                            raise ValueError(
                                f"protocol signal transmission {key} must be an object")
        return
    if kind == "backend-opaque":
        if not isinstance(spec.get("native"), dict) or not spec["native"]:
            raise ValueError("a backend-opaque signal needs native evidence")
        return

    pulses = spec.get("pulses_us")
    if not isinstance(pulses, list) or not pulses:
        raise ValueError("a waveform signal needs a non-empty pulses_us list")
    if any(not isinstance(pulse, int) or pulse == 0 for pulse in pulses):
        raise ValueError("waveform pulses_us must contain non-zero integers")
    carrier = spec.get("carrier_hz")
    if carrier is not None and (not isinstance(carrier, int) or carrier <= 0):
        raise ValueError("waveform carrier_hz must be a positive integer")
    sections = spec.get("sections")
    if sections is not None:
        if not isinstance(sections, dict):
            raise ValueError("waveform sections must be an object")
        if set(sections) != {"intro_pulses", "repeat_pulses"}:
            raise ValueError(
                "waveform sections need exactly intro_pulses and repeat_pulses")
        counts = list(sections.values())
        if any(isinstance(count, bool) or not isinstance(count, int) or count < 0
               for count in counts):
            raise ValueError("waveform section sizes must be non-negative integers")
        if sum(counts) != len(pulses):
            raise ValueError("waveform section sizes must cover every stored pulse")
        if any(count % 2 for count in counts):
            raise ValueError("waveform intro/repeat sections must contain mark/space pairs")


def statistics(spec: dict) -> dict:
    """Derived presentation data, intentionally absent from serialized JSON."""
    signal = normalise(spec)
    pulses = signal.get("pulses_us") or []
    return {"pulse_count": len(pulses),
            "total_us": sum(abs(pulse) for pulse in pulses)}


def load(path) -> dict:
    return normalise(json.loads(Path(path).read_text()))


def save(spec: dict, path) -> None:
    Path(path).write_text(json.dumps(normalise(spec), indent=2) + "\n")


def main(argv=None) -> int:
    """Small migration utility for checked-in v1 capture assets."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--migrate", nargs="+", type=Path,
                        help="rewrite legacy capture JSON in the portable signal schema")
    args = parser.parse_args(argv)
    for path in args.migrate or []:
        save(json.loads(path.read_text()), path)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
