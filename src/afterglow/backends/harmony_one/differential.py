"""Compare imported Harmony One commands with freshly lowered portable meaning.

Byte identity and transmitted-waveform identity are reported separately. Native images
may retain adjacent words at the same carrier level; lowering canonically merges them,
which changes storage without changing the on-air envelope.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from collections import Counter

from . import command_index, ir_lowering


def _native_bytes(payload: bytes, waveform: dict | None) -> bytes | None:
    if waveform is None:
        return None
    start = waveform["offset"]
    return payload[start:start + 2 * waveform["word_count"]]


def _equivalent(
        native: dict | None, lowered: bytes | None, *, phase: str) -> bool:
    if native is None:
        return lowered is None
    if lowered is None:
        return False
    if phase == "release":
        decoded = command_index._decode_release_waveform(lowered, 0)
    else:
        decoded = command_index._decode_waveform(lowered, 0, press=phase == "press")
    return (decoded["pulses_us"] == native["pulses_us"]
            and decoded["entry_us"] == native["entry_us"])


def audit(payload: bytes) -> dict:
    """Audit every indexed command without modifying the supplied payload."""
    ownership = command_index.inspect(payload)
    devices = command_index.portable_devices(ownership)
    records = {
        command["command_id"]: command
        for device in ownership["devices"] for command in device["commands"]
    }
    counts = Counter()
    failures = []
    for device in devices:
        for name, signal in device["signals"].items():
            counts["commands"] += 1
            if signal["kind"] != "waveform":
                counts["opaque"] += 1
                continue
            counts["portable"] += 1
            evidence = signal["native"]["harmony-one"]
            record = records[evidence["command_id"]]
            try:
                lowered = ir_lowering.lower(signal, entry_us=evidence["entry_us"])
            except ValueError as exc:
                counts["mismatch"] += 1
                failures.append({
                    "command_id": evidence["command_id"],
                    "command": name,
                    "reason": f"lowering failed: {exc}",
                })
                continue

            carrier_exact = (
                lowered.carrier_period_ns == record["carrier_period_ns"]
                and lowered.carrier_half_period_ns == record["carrier_half_period_ns"]
            )
            press = record["waveforms"]["press"]
            hold = record["waveforms"].get("hold")
            release = record["waveforms"].get("release")
            bytes_exact = (
                carrier_exact
                and lowered.press_waveform == _native_bytes(payload, press)
                and lowered.hold_waveform == _native_bytes(payload, hold)
                and lowered.release_waveform == _native_bytes(payload, release)
            )
            if bytes_exact:
                counts["byte_exact"] += 1
                continue
            waveform_exact = (
                carrier_exact
                and _equivalent(press, lowered.press_waveform, phase="press")
                and _equivalent(hold, lowered.hold_waveform, phase="hold")
                and _equivalent(release, lowered.release_waveform, phase="release")
            )
            if waveform_exact:
                counts["waveform_equivalent"] += 1
                continue
            counts["mismatch"] += 1
            failures.append({
                "command_id": evidence["command_id"],
                "command": name,
                "reason": "carrier or normalized press/hold/release waveform differs",
            })

    for key in (
            "commands", "portable", "opaque", "byte_exact", "waveform_equivalent",
            "mismatch"):
        counts[key] += 0
    return {"counts": dict(counts), "failures": failures}
