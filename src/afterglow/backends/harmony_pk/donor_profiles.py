"""Extract safe donor profiles: block identity plus the original raw Code payloads.

These profiles are deliberately data, not generated protocol definitions.  The
raw code is retained because a block's carrier/timing program does not define
its command-string framing.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import irproto


def _canonical_hash(block: bytes, source_start: int) -> str:
    canonical = irproto.relocate_block(block, source_start, irproto.CANON_POS)
    return hashlib.sha256(canonical).hexdigest()[:12]


def extract(path: Path) -> dict[str, Any]:
    """Return a serialisable profile from an extracted donor directory."""
    xml_path = path / "userconfig" / "UserConfiguration.xml"
    ir_path = path / "userconfig" / "IrProto.bin"
    blocks, starts = irproto.parse_proto(irproto.read_payload(ir_path))
    block_ids = [_canonical_hash(block, start) for block, start in zip(blocks, starts)]
    root = ET.parse(xml_path).getroot()

    devices = []
    for device in root.findall("Device"):
        commands = []
        for command in device.findall("Commands/Command"):
            data = command.find("Data")
            if data is None:
                continue
            protocol = int(data.findtext("Protocol", "-1"))
            commands.append({
                "name": command.findtext("Name", ""),
                "protocol_index": protocol,
                "protocol_block": block_ids[protocol] if 0 <= protocol < len(block_ids) else None,
                "raw_code": data.findtext("Code", ""),
            })
        devices.append({
            "source_id": device.findtext("Id", ""),
            "type": device.findtext("Type", "GenericDevice"),
            "manufacturer": device.findtext("Manufacturer", ""),
            "model": device.findtext("Model", ""),
            "label": device.findtext("Presentation/Label", ""),
            "commands": commands,
        })

    return {
        "format": 1,
        "source": path.name,
        "protocol_blocks": [{"index": i, "block_id": block_id,
                             "info": irproto.block_info(block)}
                            for i, (block_id, block) in enumerate(zip(block_ids, blocks))],
        "devices": devices,
    }


def export(extracted_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(extract(extracted_dir), indent=2) + "\n")


def remap_protocol_index(raw_code: str, protocol_index: int) -> str:
    """Change only the runtime block selector (Code byte 0).

    Claude's firmware work established that the XML <Protocol> and byte 0 must
    agree.  The remainder of a donor raw code is deliberately left byte-exact:
    it is protocol-specific framing and must not be regenerated from generic
    NEC/Samsung assumptions.
    """
    if not 0 <= protocol_index <= 0xFF:
        raise ValueError("Protocol index must fit in one byte")
    prefix = "0x" if raw_code.lower().startswith("0x") else ""
    hex_code = raw_code[len(prefix):]
    if len(hex_code) < 2 or len(hex_code) % 2 or any(c not in "0123456789abcdefABCDEF" for c in hex_code):
        raise ValueError(f"Invalid raw donor Code: {raw_code!r}")
    return f"{prefix}{protocol_index:02X}{hex_code[2:]}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export a safe Harmony donor profile")
    parser.add_argument("extracted_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.extracted_dir, args.output)
