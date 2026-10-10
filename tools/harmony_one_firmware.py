#!/usr/bin/env python3
"""Unpack and disassemble Harmony One firmware.

    python3 tools/harmony_one_firmware.py list 54.2.5.zip
    python3 tools/harmony_one_firmware.py extract 54.2.5.zip /tmp/fw
    python3 tools/harmony_one_firmware.py disasm 54.2.5.zip Firmware_Main 0x23042 40
    python3 tools/harmony_one_firmware.py find 54.2.5.zip Firmware_Main fe fd

## Why this exists

Some questions about the format cannot be answered from configurations, because nothing in
a configuration explains them: what section 14's platform properties are for, or what the
operand namespace above `0xf800` means. The firmware is the only remaining witness, and
getting to a point where it can be read at all took long enough that it should not have to
be done twice.

Nothing here writes into the repository. Firmware is not ours to redistribute and the
project does not commit it, so extraction always goes to a path you name.

## What is established

The `.EZUpgrade` regions are XML with the payload as hex inside `<DATA>` elements, and a
region may hold more than one phase - Region_2 holds the factory configuration and the
application firmware together, which is why its decoded size is 62,728 rather than the
53,826 of code.

It is PIC18, and the load addresses are not in the XML. They are recovered from the code:
`GOTO` and `CALL` carry absolute targets, so the distribution of those targets says where
a phase believes it lives. Boot's land in 0x0000 to 0x1fff, SafeMode's in 0x1000 to
0xa630, and the application's in 0x1e00c to 0x2d23c against a size of 53,826, which puts
it at 0x20000 and accounts for its last byte.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import zipfile


# Recovered from the distribution of absolute branch targets, not from any metadata.
BASES = {
    "Firmware_Boot": 0x00000,
    "Firmware_Default": 0x01000,
    "Firmware_PicLib": 0x1E000,
    "Firmware_Main": 0x20000,
}

_LIT_OPS = {0x08: "SUBLW", 0x09: "IORLW", 0x0A: "XORLW", 0x0B: "ANDLW",
            0x0C: "RETLW", 0x0D: "MULLW", 0x0E: "MOVLW", 0x0F: "ADDLW"}
_BYTE_OPS = {0x02: "MULWF", 0x04: "DECF", 0x10: "IORWF", 0x14: "ANDWF", 0x18: "XORWF",
             0x1C: "COMF", 0x20: "ADDWFC", 0x24: "ADDWF", 0x28: "INCF", 0x2C: "DECFSZ",
             0x30: "RRCF", 0x34: "RLCF", 0x38: "SWAPF", 0x3C: "INCFSZ", 0x40: "RRNCF",
             0x44: "RLNCF", 0x48: "INFSNZ", 0x4C: "DCFSNZ", 0x50: "MOVF", 0x54: "SUBFWB",
             0x58: "SUBWFB", 0x5C: "SUBWF"}
_F_OPS = {0x60: "CPFSLT", 0x62: "CPFSEQ", 0x64: "CPFSGT", 0x66: "TSTFSZ",
          0x68: "SETF", 0x6A: "CLRF", 0x6C: "NEGF", 0x6E: "MOVWF"}
_COND = {0xE0: "BZ", 0xE1: "BNZ", 0xE2: "BC", 0xE3: "BNC",
         0xE4: "BOV", 0xE5: "BNOV", 0xE6: "BN", 0xE7: "BNN"}
_INHERENT = {0x0000: "NOP", 0x0003: "SLEEP", 0x0004: "CLRWDT", 0x0005: "PUSH",
             0x0006: "POP", 0x0007: "DAW", 0x0008: "TBLRD*", 0x0009: "TBLRD*+",
             0x000A: "TBLRD*-", 0x000B: "TBLRD+*", 0x000C: "TBLWT*", 0x000D: "TBLWT*+",
             0x000E: "TBLWT*-", 0x000F: "TBLWT+*", 0x0010: "RETFIE",
             0x0011: "RETFIE FAST", 0x0012: "RETURN", 0x0013: "RETURN FAST",
             0x00FF: "RESET"}


def regions(archive: pathlib.Path) -> dict[str, bytes]:
    """Every phase in a firmware archive, decoded, keyed by its declared type."""
    blobs = {}
    if archive.suffix.lower() in (".zip", ".hfw"):
        with zipfile.ZipFile(archive) as bundle:
            names = [n for n in bundle.namelist() if n.lower().endswith((".hfw", ".zip"))]
            if names:
                import tempfile
                with tempfile.TemporaryDirectory() as tmp:
                    inner = pathlib.Path(bundle.extract(names[0], tmp))
                    return regions(inner)
            payloads = {n: bundle.read(n) for n in bundle.namelist()}
    else:
        payloads = {archive.name: archive.read_bytes()}
    for name, data in sorted(payloads.items()):
        for phase in re.findall(rb"<PHASE>(.*?)</PHASE>", data, re.S):
            kind = re.search(rb"<TYPE>(.*?)</TYPE>", phase, re.S)
            text = b"".join(
                item[1].strip()
                for item in re.findall(rb"<DATA(\s[^>]*)?>(.*?)</DATA>", phase, re.S))
            if not text:
                continue
            blobs[kind.group(1).decode() if kind else name] = bytes.fromhex(text.decode())
    return blobs


def _word(code: bytes, at: int) -> int:
    return code[at] | (code[at + 1] << 8)


def branch_targets(code: bytes) -> list[tuple[int, str, int]]:
    """Every absolute GOTO and CALL, as (offset, kind, program byte address)."""
    out = []
    for at in range(0, len(code) - 3, 2):
        first, second = _word(code, at), _word(code, at + 2)
        if second & 0xF000 != 0xF000:
            continue
        if first & 0xFF00 == 0xEF00:
            kind = "goto"
        elif first & 0xFE00 == 0xEC00:
            kind = "call"
        else:
            continue
        out.append((at, kind, ((first & 0xFF) | ((second & 0x0FFF) << 8)) * 2))
    return out


def infer_base(code: bytes) -> int | None:
    """Where a phase believes it lives, from where its own branches point.

    A phase's targets nearly all land inside it, so the 4 KiB page most of them share,
    rounded down to where the whole span fits, is its base.
    """
    targets = [address for _at, _kind, address in branch_targets(code)]
    if not targets:
        return None
    for shift in (16, 12):
        candidate = min(targets) >> shift << shift
        if max(targets) < candidate + len(code) + (1 << shift):
            return candidate
    return min(targets) >> 12 << 12


def disassemble(code: bytes, base: int, start: int, count: int):
    """Yield (address, text) for ``count`` instructions from offset ``start``."""
    at = start
    emitted = 0
    while at < len(code) - 1 and emitted < count:
        value = _word(code, at)
        high, low = value >> 8, value & 0xFF
        size, text = 2, f".word {value:#06x}"
        following = _word(code, at + 2) if at + 3 < len(code) else 0
        wide = following & 0xF000 == 0xF000
        if value in _INHERENT:
            text = _INHERENT[value]
        elif high in _LIT_OPS:
            text = f"{_LIT_OPS[high]} {low:#04x}"
        elif high == 0x01:
            text = f"MOVLB {low & 0xF:#x}"
        elif high & 0xFC in _BYTE_OPS:
            text = (f"{_BYTE_OPS[high & 0xFC]} {low:#04x}, "
                    f"{'F' if high & 2 else 'W'}, {high & 1}")
        elif high & 0xFE in _F_OPS:
            text = f"{_F_OPS[high & 0xFE]} {low:#04x}, {high & 1}"
        elif 0x80 <= high <= 0xBF:
            name = {0x8: "BSF", 0x9: "BCF", 0xA: "BTFSS", 0xB: "BTFSC"}[high >> 4]
            text = f"{name} {low:#04x}, {(high >> 1) & 7}, {high & 1}"
        elif 0x70 <= high <= 0x7F:
            text = f"BTG {low:#04x}, {(high >> 1) & 7}, {high & 1}"
        elif high in _COND:
            offset = low - 256 if low > 127 else low
            text = f"{_COND[high]} {base + at + 2 + offset * 2:#07x}"
        elif 0xD0 <= high <= 0xDF:
            offset = value & 0x7FF
            offset -= 0x800 if offset > 0x3FF else 0
            text = (f"{'BRA' if high < 0xD8 else 'RCALL'} "
                    f"{base + at + 2 + offset * 2:#07x}")
        elif high in (0xEC, 0xED, 0xEF) and wide:
            where = (low | ((following & 0x0FFF) << 8)) * 2
            text = f"{'GOTO' if high == 0xEF else 'CALL'} {where:#07x}"
            size = 4
        elif high == 0xEE and wide:
            text = (f"LFSR {(low >> 4) & 3}, "
                    f"{((low & 0xF) << 8) | (following & 0xFF):#06x}")
            size = 4
        elif 0xC0 <= high <= 0xCF and wide:
            text = f"MOVFF {((high & 0xF) << 8) | low:#05x}, {following & 0xFFF:#05x}"
            size = 4
        yield base + at, text
        at += size
        emitted += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("list", "extract", "disasm", "find"))
    parser.add_argument("archive", type=pathlib.Path)
    parser.add_argument("rest", nargs="*")
    args = parser.parse_args()

    found = regions(args.archive)
    if not found:
        raise SystemExit(f"{args.archive} holds no firmware phases this can read")

    if args.action == "list":
        for kind, code in sorted(found.items()):
            base = BASES.get(kind, infer_base(code))
            span = f"{base:#07x}..{base + len(code):#07x}" if base is not None else "?"
            print(f"  {kind:22s} {len(code):7d} bytes  base {span}"
                  f"  {len(branch_targets(code))} absolute branches")
        return 0

    if args.action == "extract":
        if not args.rest:
            raise SystemExit("extract needs a directory to write into")
        out = pathlib.Path(args.rest[0])
        out.mkdir(parents=True, exist_ok=True)
        for kind, code in sorted(found.items()):
            (out / f"{kind}.bin").write_bytes(code)
            print(f"  wrote {out / (kind + '.bin')} ({len(code)} bytes)")
        return 0

    if not args.rest:
        raise SystemExit(f"{args.action} needs a phase name; try 'list'")
    kind = args.rest[0]
    if kind not in found:
        raise SystemExit(f"no phase {kind!r}; this archive holds {sorted(found)}")
    code = found[kind]
    base = BASES.get(kind, infer_base(code)) or 0

    if args.action == "find":
        wanted = [int(x, 16) for x in args.rest[1:]]
        if not wanted:
            raise SystemExit("find needs one or more literal bytes, in hex")
        # A 16-bit constant is loaded as consecutive MOVLW instructions.
        for at in range(0, len(code) - 1, 2):
            if code[at] != wanted[0] or code[at + 1] != 0x0E:
                continue
            where, ok = at, True
            for value in wanted[1:]:
                nxt = next(
                    (j for j in range(where + 2, min(where + 26, len(code) - 1), 2)
                     if code[j] == value and code[j + 1] == 0x0E), None)
                if nxt is None:
                    ok = False
                    break
                where = nxt
            if ok:
                print(f"  {base + at:#07x} .. {base + where:#07x}")
        return 0

    start = int(args.rest[1], 16) - base if len(args.rest) > 1 else 0
    count = int(args.rest[2]) if len(args.rest) > 2 else 40
    for address, text in disassemble(code, base, start, count):
        print(f"  {address:#07x}  {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
