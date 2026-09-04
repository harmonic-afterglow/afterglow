"""Parse Flipper Zero / Flipper-IRDB ``.ir`` signal files.

Files contain hash-delimited records. Parsed records name a protocol plus little-endian
address and command byte strings; raw records carry carrier frequency, duty cycle, and
alternating positive mark/space durations. Unknown fields are retained so importing a
newer Flipper file does not silently erase evidence.
"""
from __future__ import annotations

from pathlib import Path


def parse_ir_text(text: str) -> list[dict]:
    records = []
    current = {}
    continued = None

    def finish():
        nonlocal current, continued
        if current.get("name"):
            command = current.get("command")
            if isinstance(command, str):
                current["command_bytes"] = command
                current["command"] = command.split()[0]
            records.append(current)
        current = {}
        continued = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "#":
            finish()
            continue
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().casefold()
            if key in {"filetype", "version"} and not current:
                continue
            current[key] = value.strip()
            continued = key
        elif continued == "data":
            current["data"] = f"{current['data']} {line}".strip()
    finish()
    return records


def parse_ir(path) -> list[dict]:
    return parse_ir_text(Path(path).read_text(encoding="utf-8", errors="replace"))
