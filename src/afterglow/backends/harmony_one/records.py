"""Build relocatable Harmony One command records and command objects.

Addresses passed here are offsets in the GSPM image. Placement, table insertion, and
relocation remain separate operations so a valid record cannot imply a safe image edit.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from . import gspm


NEW_COMMAND_FLAG = 0x01
PRESERVED_FLAGS = (0x01, 0x04)
PREFIX_SIZE = 5
RECORD_SIZE = 25
# A toggling command (RC5/RC6) is a record with two sets of waveform pointers, and its
# waveform mode at +15 says 2. Read from the Harmony 800's firmware (the routine at
# 0x08015540 skips 9 bytes - one set - when the device's toggle bit is clear) and matched
# by every RC5/RC6 command in the One donors: 221 records, each with a second set whose
# press waveform differs from the first only in the toggle bit.
TOGGLING_RECORD_SIZE = RECORD_SIZE + 9


def record_size(alternate: bool) -> int:
    return TOGGLING_RECORD_SIZE if alternate else RECORD_SIZE


def _u24(value: int, label: str) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFF:
        raise ValueError(f"{label} must fit in an unsigned 24-bit field")
    return value.to_bytes(3, "little")


def _pointer(offset: int, label: str) -> bytes:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError(f"{label} must be a non-negative GSPM offset")
    return _u24(gspm.BASE + offset, label)


def _pointers(press_offset: int, hold_offset: int | None, release_offset: int | None,
              which: str) -> bytes:
    return (_pointer(press_offset, f"{which}press waveform pointer")
            + (_pointer(hold_offset, f"{which}hold waveform pointer")
               if hold_offset is not None else bytes(3))
            + (_pointer(release_offset, f"{which}release waveform pointer")
               if release_offset is not None else bytes(3)))


def command_record(record_offset: int, press_offset: int, hold_offset: int | None,
                   carrier_period_ns: int, carrier_half_period_ns: int, *,
                   release_offset: int | None = None,
                   alternate: tuple[int, int | None, int | None] | None = None,
                   flag: int = NEW_COMMAND_FLAG, prefix: bytes | None = None) -> bytes:
    """Build the measured 25-byte record after placement offsets are known.

    With `alternate` - the (press, hold, release) offsets of a toggling command's other
    state - the record is the 34-byte one Logitech writes for RC5/RC6: waveform mode 2
    and a second pointer set. The remote keeps one toggle bit per device, flips it on
    each command it starts for that device, and sends the first set when the bit is set,
    so a device's first press after power-on sends the first set and the next the other.

    A record authored here opens with one of the flags this backend writes. A record
    being rebuilt from one that already exists passes its own five opening bytes
    instead: the donors carry 0, 1, 4, 5, 6 and 7 there, and one record opens `2f 81`,
    so reconstructing those bytes from a flag alone would not put them back.
    """
    if prefix is not None:
        if len(prefix) != PREFIX_SIZE:
            raise ValueError(
                f"a command record opens with {PREFIX_SIZE} bytes, not {len(prefix)}")
    elif flag not in PRESERVED_FLAGS:
        raise ValueError(f"unknown Harmony One command flag {flag:#04x}")
    if carrier_half_period_ns != carrier_period_ns // 2:
        raise ValueError("Harmony One carrier half-period must be period // 2")

    out = bytearray(prefix if prefix is not None else bytes([flag, 0, 0, 0, 0]))
    out += _u24(carrier_period_ns, "carrier period")
    out += _u24(carrier_half_period_ns, "carrier half-period")
    out += b"\x01" + _pointer(record_offset + 4, "command self-pointer")
    out += b"\x02" if alternate is not None else b"\x01"
    out += _pointers(press_offset, hold_offset, release_offset, "")
    if alternate is not None:
        out += _pointers(*alternate, "alternate ")
    assert len(out) == record_size(alternate is not None)
    return bytes(out)


def command_object(command_id: int, device_id: int) -> bytes:
    """Build the seven-byte object joining a command ID to its device field.

    Both fields are packed, and both carry the device in their high byte: across the four
    donors 1,471 command objects agree on that and none disagrees, and no high byte ever
    reaches the image's device count. The command field's low byte is the command's
    ordinal within its device. The device field's low byte is a repeat count - it is 1 in
    1,297 of the 1,502 atoms measured, with 0, 5, 8, 10, 15, 20, 25, 30, 40, 50 and 100
    making up the rest, which is what a device that needs a command held rather than
    tapped would carry.
    """
    for value, label in ((command_id, "command ID"), (device_id, "device ID")):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
            raise ValueError(f"{label} must fit in an unsigned 16-bit field")
    return (b"\x02" + command_id.to_bytes(2, "little") + b"\x7d"
            + device_id.to_bytes(2, "little") + b"\x7c")
