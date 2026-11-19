"""Reading an RF Wireless Extender, which is not a remote.

An extender (skins 20 and 24) answers on the 890's USB protocol but has no user
configuration region, and Logitech's software never read back what it wrote to one
(it checked a checksum). So Read tries the three read-only ways in that software,
decompiled (afterglow-research/harmony-1100.md, "The RF Wireless Extender"), and saves
whatever comes, with every answer, in one zip:

1. memory, with the Diagnostic service's READ_MEMORY: probed every 64 KB, and each
   block that answers read whole;
2. configuration region 0 with Harmony Remote 6.0's READ_CONFIG_REGION;
3. the regions the unit lists (`library/remotes/models.json` `read_regions` if it lists
   none), region 7 last: it is read off the Z-Wave chip, and a unit still busy with it
   refuses what comes next.

Nothing is written.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from . import concord, remotes

BLOCK = 0x10000          # memory probed and read in blocks this size
ADDRESS_LIMIT = 0x1000000  # READ_MEMORY takes a 24-bit address
MEMORY_LIMIT = 4 << 20   # at most this much memory is read
INVALID_ADDRESS = 0x08


def regions_for(skin) -> list[int]:
    """The regions to fall back on for a unit of this skin, or [] for a remote's own read."""
    try:
        entry = remotes.models().get(str(int(skin))) or {}
    except (TypeError, ValueError):
        return []
    return [int(region) for region in entry.get("read_regions") or []]


def order(listed: list[int], fallback: list[int]) -> list[int]:
    """The regions to read: those the unit listed, else `fallback`; region 7 last."""
    regions = sorted(set(listed)) or list(fallback)
    return [region for region in regions if region != 7] + ([7] if 7 in regions else [])


def _memory(remote, notes: dict, log) -> dict[int, bytes]:
    """The blocks of memory that answer, by start address.

    A block that is not there answers INVALID_ADDRESS and the next is probed. Any
    other no, or no answer, ends the memory part: the service is not there.
    """
    blocks: dict[int, bytes] = {}
    total = 0
    for address in range(0, ADDRESS_LIMIT, BLOCK):
        try:
            probe, status = remote.read_memory(address, 16)
        except (concord.NotAvailable, concord.RemoteError) as exc:
            notes["memory"] = f"at {address:06X}: {exc}"
            log(f"Memory: {exc}")
            break
        if not probe:
            if status != INVALID_ADDRESS:
                notes["memory"] = f"refused at {address:06X}, status {status:02X}"
                log(f"Memory refused, status {status:02X}")
                break
            continue
        log(f"Memory at {address:06X} answers; reading {BLOCK // 1024} KB...")
        try:
            data, status = remote.read_memory(address, BLOCK)
        except concord.RemoteError as exc:
            data, status = probe, 0
            notes.setdefault("memory_errors", {})[f"{address:06X}"] = str(exc)
        blocks[address] = data or probe
        total += len(blocks[address])
        if status:
            notes.setdefault("memory_stopped", {})[
                f"{address + len(data):06X}"] = f"status {status:02X}"
        if total >= MEMORY_LIMIT:
            notes["memory"] = f"stopped after {total:,} bytes"
            break
    return blocks


def save(remote, target: Path, regions: list[int], identity: dict,
         on_progress=None, log=lambda line: None) -> tuple[Path, int]:
    """Read the unit the three ways into a zip beside `target`; (the zip, bytes read).

    What the unit refuses is noted and the next thing tried. Raises RemoteError only
    if nothing at all came.
    """
    files: dict[str, bytes] = {}
    notes: dict = {}

    log("Reading memory...")
    for address, data in _memory(remote, notes, log).items():
        files[f"memory-{address:06X}.bin"] = data

    log("Reading configuration region 0 the 6.0 way...")
    try:
        data, status = remote.read_legacy_config(0)
        if data:
            files["config6-00.bin"] = data
            log(f"Configuration region 0: {len(data):,} bytes")
        else:
            notes["config6"] = f"refused, status {status:02X}"
            log(f"Configuration region 0 refused, status {status:02X}")
    except (concord.RemoteError, concord.NotAvailable) as exc:
        notes["config6"] = str(exc)
        log(f"Configuration region 0 not read: {exc}")

    for region in regions:
        log(f"Reading region {region}...")
        try:
            data = remote.read_region(region, on_progress)
            files[f"region-{region:02d}.bin"] = data
            log(f"Region {region}: {len(data):,} bytes")
        except concord.RemoteError as exc:
            notes.setdefault("regions_refused", {})[str(region)] = str(exc)
            log(f"Region {region} not read: {exc}")

    if not files:
        raise concord.RemoteError(
            "The unit answered but handed over nothing: no memory, no configuration, "
            "none of its regions. Nothing was changed.")
    out = Path(target).with_suffix(".zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("identity.json", json.dumps(
            {"identity": {key: value for key, value in identity.items()
                          if isinstance(value, (str, int, float, bool, type(None)))},
             "regions_tried": regions, "files": sorted(files), "notes": notes},
            indent=2))
    out.write_bytes(buffer.getvalue())
    return out, sum(len(data) for data in files.values())
