#!/usr/bin/env python3
"""Write the snapshots of every IR protocol the public sources and Logitech's archive use.

    tools/ir_source_snapshot.py IRDB_CHECKOUT FLIPPER_CHECKOUT ARCHIVE_CHECKOUT

IRDB (github.com/probonopd/irdb), Flipper-IRDB (github.com/Lucaslhm/Flipper-IRDB) and the
Harmony IR archive are read from local checkouts; nothing is fetched. For each protocol
name the snapshot says how many commands use it, how many Afterglow can send, and how it
handles the name (public_ir_sources.protocol_handling, or for the archive the Pronto or
the reviewed definition). tests/test_ir_source_coverage.py fails when a name has no
handling, so a protocol a source starts using is seen when the snapshot is refreshed,
not when someone's device turns out to have no commands.

Writes tests/fixtures/ir-sources/{irdb,flipper,logitech}-protocols.json.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import logitech_archive, public_ir_sources  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "ir-sources"


def _revision(checkout: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _write(name: str, source: dict, protocols: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = {"schema": "afterglow-ir-source-snapshot/1", "source": source,
            "protocols": dict(sorted(protocols.items(), key=lambda kv: kv[0].casefold()))}
    (OUT / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")


def _tally(rows) -> dict:
    """rows: (protocol name, file, sent?) -> {name: {commands, sent, files, handling}}"""
    commands, sent, files = Counter(), Counter(), defaultdict(set)
    for name, path, ok in rows:
        commands[name] += 1
        sent[name] += ok
        files[name].add(path)
    return {name: {"commands": commands[name], "sent": sent[name],
                   "files": len(files[name])} for name in commands}


def irdb(checkout: Path) -> None:
    def rows():
        for path in sorted((checkout / "codes").rglob("*.csv")):
            with open(path, newline="", encoding="utf-8", errors="replace") as handle:
                for row in csv.DictReader(handle):
                    signal, _why = public_ir_sources._irdb_signal(row)
                    yield (row.get("protocol") or "").strip(), \
                        str(path.relative_to(checkout)), signal is not None
    protocols = _tally(rows())
    for name, entry in protocols.items():
        entry["handling"] = public_ir_sources.protocol_handling("irdb", name)
    _write("irdb-protocols.json", {"kind": "irdb", "revision": _revision(checkout)},
           protocols)


def flipper(checkout: Path) -> None:
    def rows():
        for path in sorted(checkout.rglob("*.ir")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for block in text.split("#"):
                record = dict(re.findall(r"^(\w+):\s*(.*)$", block, re.M))
                if record.get("type") != "parsed":
                    continue
                signal, _why = public_ir_sources._flipper_signal(record)
                yield record.get("protocol", "").strip(), \
                    str(path.relative_to(checkout)), signal is not None
    protocols = _tally(rows())
    for name, entry in protocols.items():
        entry["handling"] = public_ir_sources.protocol_handling("flipper", name)
    _write("flipper-protocols.json",
           {"kind": "flipper-irdb", "revision": _revision(checkout),
            "note": "parsed signals only; raw captures are sent as they were recorded"},
           protocols)


def logitech(checkout: Path) -> None:
    api = checkout / "docs" / "api" / "v1"
    records = json.loads((api / "protocols.json").read_text(encoding="utf-8"))
    commands, pronto, codesets = Counter(), Counter(), defaultdict(set)
    for path in sorted((api / "codesets").glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for codeset, items in json.load(handle).items():
                for command in items:
                    key = command.get("ProtocolId")
                    key = "learned" if key is None else str(key)
                    commands[key] += 1
                    pronto[key] += bool(command.get("pronto"))
                    codesets[key].add(codeset)
    protocols = {}
    for key in sorted(set(records) | set(commands), key=lambda k: (k == "learned", k)):
        record = records.get(key) or {}
        name = record.get("Name")
        entry = {"id": None if key == "learned" else int(key), "name": name,
                 "commands": commands[key], "with_pronto": pronto[key],
                 "codesets": len(codesets[key])}
        entry["handling"] = logitech_archive.protocol_handling(
            entry["id"], name, commands=entry["commands"], with_pronto=entry["with_pronto"])
        protocols[key if key == "learned" else f"{int(key):04d} {name}"] = entry
    _write("logitech-protocols.json",
           {"kind": "logitech-harmony-ir-archive", "revision": _revision(checkout)},
           protocols)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("irdb", type=Path)
    parser.add_argument("flipper", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    irdb(args.irdb)
    flipper(args.flipper)
    logitech(args.archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
