"""Report the oldest macOS each Mach-O file in a tree will load on.

    python3 packaging/macos/minos.py <path> [--max 10.13] [--arch x86_64]

A wheel's platform tag and a bundle's `LSMinimumSystemVersion` are both claims. What
the loader enforces is the version each binary was linked for, recorded in its
`LC_BUILD_VERSION` (or, for older toolchains, `LC_VERSION_MIN_MACOSX`) load command. One
library linked for a newer system than the rest is enough to stop the app starting, and
it says nothing about it until a user on that system tries.

That is exactly what the first macOS bundles did: they declared 11.0 while carrying a Qt
built for 13 and Homebrew libraries built for 14 and 15. With `--max`, any file over the
limit is listed and the exit status is 1, so the bundle job fails on it.

`--arch` looks only at that architecture's slice of universal files: an Intel build for
10.13 may carry universal libraries whose arm64 half says 11.0, since no Apple Silicon Mac
runs anything older, and that half is never loaded on an Intel Mac.

Plain Python, no `otool`, so it also runs on Linux against a downloaded wheel.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
MH_MAGIC = 0xFEEDFACE
MH_MAGIC_64 = 0xFEEDFACF
LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32
PLATFORM_MACOS = 1
CPU_NAMES = {7: "i386", 0x01000007: "x86_64", 0x0100000C: "arm64"}


def _version(packed: int) -> tuple[int, int, int]:
    return packed >> 16, (packed >> 8) & 0xFF, packed & 0xFF


def _slice(data: bytes, offset: int) -> tuple[str, tuple[int, int, int]] | None:
    """The architecture and minimum macOS of the thin Mach-O at `offset`."""
    magic = struct.unpack_from("<I", data, offset)[0]
    if magic not in (MH_MAGIC, MH_MAGIC_64):
        return None
    cpu, _sub, _type, ncmds, _size = struct.unpack_from("<iiiII", data, offset + 4)
    cursor = offset + (32 if magic == MH_MAGIC_64 else 28)
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, cursor)
        if cmd == LC_BUILD_VERSION:
            platform, minos = struct.unpack_from("<II", data, cursor + 8)
            if platform == PLATFORM_MACOS:
                return CPU_NAMES.get(cpu, hex(cpu)), _version(minos)
        elif cmd == LC_VERSION_MIN_MACOSX:
            minos = struct.unpack_from("<I", data, cursor + 8)[0]
            return CPU_NAMES.get(cpu, hex(cpu)), _version(minos)
        cursor += size
    return CPU_NAMES.get(cpu, hex(cpu)), (0, 0, 0)


def minimums(data: bytes) -> list[tuple[str, tuple[int, int, int]]]:
    """Every slice of a thin or universal Mach-O; empty for anything else."""
    if len(data) < 8:
        return []
    magic = struct.unpack_from(">I", data)[0]
    if magic in (FAT_MAGIC, FAT_MAGIC_64):
        count = struct.unpack_from(">I", data, 4)[0]
        width = 32 if magic == FAT_MAGIC_64 else 20
        found = []
        for index in range(count):
            entry = 8 + index * width
            offset = (struct.unpack_from(">Q", data, entry + 8)[0] if magic == FAT_MAGIC_64
                      else struct.unpack_from(">I", data, entry + 8)[0])
            thin = _slice(data, offset)
            if thin:
                found.append(thin)
        return found
    thin = _slice(data, 0)
    return [thin] if thin else []


def scan(root: Path):
    paths = [root] if root.is_file() else sorted(p for p in root.rglob("*")
                                                 if p.is_file() and not p.is_symlink())
    for path in paths:
        with path.open("rb") as handle:
            head = handle.read(4)
            if struct.unpack(">I", head.ljust(4, b"\0"))[0] not in (
                    FAT_MAGIC, FAT_MAGIC_64) and struct.unpack(
                    "<I", head.ljust(4, b"\0"))[0] not in (MH_MAGIC, MH_MAGIC_64):
                continue
            data = head + handle.read()
        for arch, version in minimums(data):
            yield path, arch, version


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--max", help="fail if any file needs a newer macOS than this")
    parser.add_argument("--arch", help="only this architecture (x86_64 or arm64)")
    args = parser.parse_args(argv)
    limit = tuple(int(part) for part in args.max.split(".")) if args.max else None
    over = 0
    highest = (0, 0, 0)
    for path, arch, version in scan(args.path):
        if args.arch and arch != args.arch:
            continue
        highest = max(highest, version)
        shown = ".".join(map(str, version))
        if limit and version[:len(limit)] > limit:
            over += 1
            print(f"TOO NEW {shown:>8} {arch:<6} {path}")
        elif not limit:
            print(f"{shown:>8} {arch:<6} {path}")
    print(f"highest minimum: {'.'.join(map(str, highest))}")
    if over:
        print(f"{over} file(s) need a newer macOS than {args.max}")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
