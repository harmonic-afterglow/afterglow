#!/usr/bin/env python3
"""Compile portable device signals into one remote backend's build inputs.

This is deliberately a capability gate, not a best-effort converter. Harmony PK can
store one fixed raw waveform for a command. It can therefore fall back from a portable
protocol only when press and hold mean the same waveform and the protocol has no sender
state. A toggle protocol or a distinct repeat frame needs native lifecycle support; using
one frozen SsIr entry would appear to work while transmitting the wrong thing.
"""
from __future__ import annotations

from ... import ir_protocol, ir_signal
from . import BACKEND_NAMES
from . import ssir


def _next_raw_index(spec: dict) -> int:
    indexes = [int(index) for index in (spec.get("raw_ir") or {})]
    index = max(indexes, default=-1) + 1
    if index > 0xFF:
        raise ValueError("Harmony PK SsIr command indexes are limited to one byte")
    return index


def _add_waveform(spec: dict, name: str, signal: dict) -> None:
    raw_codes = spec.setdefault("raw_codes", {})
    raw_ir = spec.setdefault("raw_ir", {})
    existing = ssir.raw_index(raw_codes.get(name, ""))
    if existing is not None and str(existing) in raw_ir:
        return
    index = _next_raw_index(spec)
    raw_codes[name] = ssir.make_code(index)
    raw_ir[str(index)] = signal


def _require_fixed_waveform(signal: dict) -> None:
    """Refuse an intro/repeat lifecycle that one Harmony PK SsIr entry would erase."""
    sections = signal.get("sections")
    if not sections:
        return
    intro = sections["intro_pulses"]
    repeat = sections["repeat_pulses"]
    if intro and repeat:
        raise ValueError(
            "waveform has distinct intro and repeat sections; Harmony PK SsIr can "
            "store only one fixed waveform for this command")


def _fallback_waveform(signal: dict, library) -> dict:
    definition = ir_protocol.protocol(signal["protocol"], library)
    if definition.get("state"):
        raise ValueError(
            f"protocol {signal['protocol']!r} has sender state; a fixed raw waveform "
            "cannot preserve its lifecycle")

    press, state = ir_protocol.render_transmission(
        signal, phase="press", library=library)
    hold, state = ir_protocol.render_transmission(
        signal, phase="hold", state=state, library=library)
    release, _state = ir_protocol.render_transmission(
        signal, phase="release", state=state, library=library)
    if press is None:
        raise ValueError(f"protocol {signal['protocol']!r} has an empty press sequence")
    if hold is None or hold["pulses_us"] != press["pulses_us"]:
        raise ValueError(
            f"protocol {signal['protocol']!r} has a distinct hold lifecycle; Harmony PK "
            "SsIr can store only one fixed waveform for this command")
    if release is not None:
        raise ValueError(
            f"protocol {signal['protocol']!r} emits on release; Harmony PK SsIr cannot "
            "represent that lifecycle")
    return press


def _report_frozen(frozen: list[tuple[str, str, str]], model: str) -> None:
    """Say loudly when a portable protocol had to be frozen into a fixed waveform.

    This is the other direction of the same rule as `importer._report_unpromotable`.
    Importing must turn every native block into a portable protocol; building must turn
    every portable protocol back into a native one. When the second fails, the command is
    still sent - as a recorded waveform - and that is a real downgrade, not an equivalent
    encoding: a frozen waveform has one shape, so it cannot carry a distinct hold frame,
    a toggle that alternates between presses, or anything emitted on release.

    Reporting it matters because the failure is otherwise invisible: the button works,
    the held-key behaviour does not, and nothing in the build says which commands lost
    it.
    """
    if not frozen:
        return
    print()
    print("=" * 72)
    print(f"ERROR: {len(frozen)} command(s) could not be built as a native protocol for")
    print(f"       the {model} and were frozen into fixed waveforms.")
    print()
    for device, command, protocol in sorted(frozen):
        print(f"  {device} / {command}   (protocol {protocol})")
    print()
    print("  They will transmit, and a single press should work. What is lost is every")
    print("  part of the key lifecycle a single frozen shape cannot hold: a distinct")
    print("  repeat frame while the key is held, a toggle bit that alternates between")
    print("  presses, and anything the protocol emits on release.")
    print()
    print("  This is a bug in Afterglow. Every protocol in the reference archive builds")
    print("  natively, so these use something no available sample does.")
    print()
    print("  Please open an Issue in the Afterglow repository with the protocol name")
    print("  above, or the .ezhex if these commands came from an imported configuration.")
    print("=" * 72)
    print()


def prepare_devices(specs: list[dict], profile, *, library=None) -> None:
    """Add exact backend Codes/waveforms required by each portable command in place."""
    library = ir_protocol.LIBRARY if library is None else library
    backend_name = profile.infrared.get("backend")
    frozen: list[tuple[str, str, str]] = []
    for spec in specs:
        for name, signal in (spec.get("signals") or {}).items():
            ir_signal.validate(signal)
            # Generic native lowering is command-specific because a signal may override
            # the protocol lifecycle. `backend.lower_devices` has already VM-gated and
            # materialized this transient Code; the builder later rewrites byte 0 to the
            # block's assigned runtime index.
            native_code = (spec.get("raw_codes") or {}).get(name)
            if (signal["kind"] == "protocol" and native_code
                    and not ssir.is_raw(native_code)):
                continue
            strategy = profile.ir_strategy(signal)
            if strategy == "native-protocol":
                continue
            if signal["kind"] == "waveform" and strategy == "native-waveform":
                _require_fixed_waveform(signal)
                _add_waveform(spec, name, signal)
                continue
            if signal["kind"] == "backend-opaque":
                evidence = signal.get("native") or {}
                native = next((evidence[name] for name in BACKEND_NAMES
                               if evidence.get(name)), {})
                code = native.get("code")
                if not code:
                    raise ValueError(
                        f"command {name!r} is opaque and has no {backend_name!r} code")
                block = native.get("protocol_block_id")
                if block:
                    spec.setdefault("command_protocols", {})[name] = block
                spec.setdefault("raw_codes", {}).setdefault(name, code)
                continue
            if strategy == "render-waveform":
                if signal["kind"] == "protocol":
                    # A waveform signal rendered as a waveform is what it already was;
                    # a *protocol* arriving here has lost its lifecycle.
                    frozen.append((spec.get("label") or spec.get("id") or "?",
                                   name, signal.get("protocol") or "?"))
                _add_waveform(spec, name, _fallback_waveform(signal, library))
                continue
            raise ValueError(
                f"{profile.model} cannot reproduce command {name!r}: signal kind "
                f"{signal['kind']!r}, protocol {signal.get('protocol')!r}")

        # A device made entirely from generated/raw waveforms needs no IrProto block.
        command_names = {command[0] for command in spec.get("commands") or []}
        raw_names = set(spec.get("raw_codes") or {})
        if command_names and command_names <= raw_names:
            if all(ssir.is_raw(spec["raw_codes"][name]) for name in command_names):
                spec["protocol"] = None
    _report_frozen(frozen, profile.model)
