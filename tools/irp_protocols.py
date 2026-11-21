#!/usr/bin/env python3
"""Write src/afterglow/library/irp/protocols.json from IrpTransmogrifier's IrpProtocols.xml.

    python3 tools/irp_protocols.py path/to/IrpProtocols.xml

IrpTransmogrifier (https://github.com/bengtmartensson/IrpTransmogrifier) defines
every IR protocol DecodeIR and IRDB name, in IRP notation. Afterglow renders that notation
(src/afterglow/irp.py); this keeps each protocol's name, its other names and its IRP, and
leaves out what only decoding needs. Run it again when IrpTransmogrifier adds protocols.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"irp": "http://www.harctoolbox.org/irp-protocols"}
OUT = Path(__file__).resolve().parents[1] / "src" / "afterglow" / "library" / "irp" / \
    "protocols.json"


def main(source: str) -> int:
    root = ET.parse(source).getroot()
    version = root.get("version") or "unknown"
    protocols = []
    for element in root.findall("irp:protocol", NS):
        irp = element.find("irp:irp", NS)
        if irp is None or not (irp.text or "").strip():
            continue
        others = [p.text.strip() for p in element.findall("irp:parameter", NS)
                  if p.get("name") == "alt_name" and p.text]
        entry = {"name": element.get("name"), "irp": " ".join(irp.text.split())}
        if others:
            entry["other_names"] = others
        if any(p.get("name") == "decode-only" and (p.text or "").strip() == "true"
               for p in element.findall("irp:parameter", NS)):
            entry["decode_only"] = True
        protocols.append(entry)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "schema": "afterglow-irp-protocols/1",
        "source": f"IrpTransmogrifier's IrpProtocols.xml, version {version}, by Bengt "
                  "Martensson and contributors, under the all-permissive notice it "
                  "carries; see NOTICE.md",
        "protocols": protocols}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(protocols)} protocols -> {OUT}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="IrpTransmogrifier's IrpProtocols.xml")
    sys.exit(main(parser.parse_args().source))
