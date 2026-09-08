"""Build relocatable Harmony One command records and command objects.

Addresses passed here are offsets in the GSPM image. Placement, table insertion, and
relocation remain separate operations so a valid record cannot imply a safe image edit.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from . import gspm


NEW_COMMAND_FLAG = 0x01
PRESERVED_FLAGS = (0x01, 0x04)


def _u24(value: int, label: str) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFF:
        raise ValueError(f"{label} must fit in an unsigned 24-bit field")
    return value.to_bytes(3, "little")


def _pointer(offset: int, label: str) -> bytes:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError(f"{label} must be a non-negative GSPM offset")
    return _u24(gspm.BASE + offset, label)


def command_record(record_offset: int, press_offset: int, hold_offset: int | None,
                   carrier_period_ns: int, carrier_half_period_ns: int, *,
                   release_offset: int | None = None,
                   flag: int = NEW_COMMAND_FLAG) -> bytes:
    """Build the measured 25-byte record after placement offsets are known."""
    if flag not in PRESERVED_FLAGS:
        raise ValueError(f"unknown Harmony One command flag {flag:#04x}")
    if carrier_half_period_ns != carrier_period_ns // 2:
        raise ValueError("Harmony One carrier half-period must be period // 2")

    out = bytearray([flag, 0, 0, 0, 0])
    out += _u24(carrier_period_ns, "carrier period")
    out += _u24(carrier_half_period_ns, "carrier half-period")
    out += b"\x01" + _pointer(record_offset + 4, "command self-pointer")
    out += b"\x01" + _pointer(press_offset, "press waveform pointer")
    out += (_pointer(hold_offset, "hold waveform pointer")
            if hold_offset is not None else bytes(3))
    out += (_pointer(release_offset, "release waveform pointer")
            if release_offset is not None else bytes(3))
    assert len(out) == 25
    return bytes(out)


def command_object(command_id: int, device_id: int) -> bytes:
    """Build the seven-byte object joining a command ID to its device ID."""
    for value, label in ((command_id, "command ID"), (device_id, "device ID")):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
            raise ValueError(f"{label} must fit in an unsigned 16-bit field")
    return (b"\x02" + command_id.to_bytes(2, "little") + b"\x7d"
            + device_id.to_bytes(2, "little") + b"\x7c")
