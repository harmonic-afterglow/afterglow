#!/usr/bin/env python3
"""Readable IR protocol definitions: JSON <-> IrProto block bytecode.

Format reference: docs/harmony_pk/irproto.md

A block stored as bytes is opaque, unreviewable and impossible to diff. This module gives
every block a text form that a human can read and a pull request can review, and converts
it back to the exact bytes. Two properties make that safe: encoding a decoded block
reproduces it byte for byte, and pointers are stored relative to the block's own start so
a block can be generated at whatever position it will occupy.

    python -m afterglow.backends.harmony_pk.protocol_json build definition.json ...
"""
from __future__ import annotations

import json
import hashlib
import struct
from pathlib import Path

from . import irproto

SCHEMA = "harmony-ir-protocol/1"

# Block layout (see irproto for provenance). Offsets are block-relative.
FLAG_OFF = 0
PERIOD_OFF = 1          # u32, carrier period in nanoseconds
PWM_PARAMETER_OFF = 5   # u8, consumed by ProcessIrCmd's PWM calculation
ELEMENT_COUNT_OFF = 6   # u8, consumed independently by ir_carrier_element_init
LEADER_MARK_OFF = 28    # u16 duration word
LEADER_SPACE_OFF = 30   # u16 duration word

_DUR_MARK = 0x8000
_DUR_US = 0x7FFF


def _u16(b, off):
    return b[off] | (b[off + 1] << 8)


def _duration(word):
    return {"kind": "mark" if word & _DUR_MARK else "space", "us": word & _DUR_US}


def decode(block: bytes, *, block_id: str, name: str = "", position: int = irproto.CANON_POS,
           offset_fields=irproto.NEC_OFFSET_FIELDS) -> dict:
    """Block bytes -> a readable, position-independent definition.

    `position` is where this block currently sits (its element pointers are absolute,
    so we must know it to make them relative). Library blocks are stored at CANON_POS.
    """
    period_ns = struct.unpack_from("<I", block, PERIOD_OFF)[0]
    body = bytearray(block)
    # Normalise the absolute element pointers to be relative to the block start, so the
    # hex below is the same no matter where the block was found.
    for off in offset_fields:
        if off + 1 < len(body):
            struct.pack_into("<H", body, off, (_u16(body, off) - position) & 0xFFFF)

    # Bytes occupied by element pointers. Nothing may be decoded as a duration there:
    # in several protocol families a pointer sits at offset 29, straddling what is the
    # leader slot in the NEC family.
    pointer_bytes = {o + d for o in offset_fields for d in (0, 1) if o + 1 < len(block)}

    # The two leader slots, but only where the NEC-family layout actually applies.
    # `kind` is the word's bit-15 flag and is NOT always mark-then-space, so it is
    # recorded per slot rather than assumed.
    leader = None
    if not pointer_bytes & {LEADER_MARK_OFF, LEADER_MARK_OFF + 1,
                            LEADER_SPACE_OFF, LEADER_SPACE_OFF + 1}:
        leader = [{"at": LEADER_MARK_OFF, **_duration(_u16(block, LEADER_MARK_OFF))},
                  {"at": LEADER_SPACE_OFF, **_duration(_u16(block, LEADER_SPACE_OFF))}]

    # Every other duration word, for reading. Reported, never used to encode.
    durations = []
    for off in range(LEADER_MARK_OFF, len(block) - 1, 2):
        if off in pointer_bytes or off + 1 in pointer_bytes:
            continue
        word = _u16(block, off)
        if word & _DUR_US and (word & _DUR_US) < 20000:
            durations.append({"at": off, **_duration(word)})

    return {
        "schema": SCHEMA,
        "id": block_id,
        "name": name or block_id,
        # carrier_period_ns is what the block actually stores and is authoritative;
        # carrier_hz is derived for reading and is ignored when encoding, because
        # round-tripping a frequency back to a period does not always land on the
        # original integer.
        "carrier_period_ns": period_ns,
        "carrier_hz": round(1e9 / period_ns) if period_ns else 0,
        "pwm_parameter": block[PWM_PARAMETER_OFF],
        "element_count": block[ELEMENT_COUNT_OFF],
        "leader": leader,
        "flag": block[FLAG_OFF],
        "size": len(block),
        # Element pointers live at these block-relative byte offsets; `body_hex` holds
        # them relative to the block start, and encode() re-absolutises them.
        "pointer_fields": list(offset_fields),
        "durations": durations,
        "body_hex": bytes(body).hex(),
    }


def encode(spec: dict, position: int = irproto.CANON_POS) -> bytes:
    """Definition -> block bytes, with element pointers absolute for `position`."""
    if spec.get("schema") not in (None, SCHEMA):
        raise ValueError(f"unknown protocol schema {spec['schema']!r}")
    block = bytearray(bytes.fromhex(spec["body_hex"]))

    # Apply the editable fields, so changing them in the JSON changes the bytes.
    block[FLAG_OFF] = spec.get("flag", block[FLAG_OFF])
    if spec.get("carrier_period_ns"):
        struct.pack_into("<I", block, PERIOD_OFF, spec["carrier_period_ns"])
    # Older JSON called bytes 5..6 one ``unit_us`` u16 because NEC's 0x0232 happens
    # to equal 562. Firmware disproves that interpretation: ProcessIrCmd reads byte 5
    # for PWM setup while element_init reads byte 6 as the table count. Accept the old
    # field at import boundaries, but never emit it from decode/new definitions.
    if spec.get("pwm_parameter") is not None:
        block[PWM_PARAMETER_OFF] = spec["pwm_parameter"]
    elif spec.get("unit_us") is not None:
        block[PWM_PARAMETER_OFF] = spec["unit_us"] & 0xFF
    if spec.get("element_count") is not None:
        block[ELEMENT_COUNT_OFF] = spec["element_count"]
    elif spec.get("unit_us") is not None:
        block[ELEMENT_COUNT_OFF] = spec["unit_us"] >> 8
    for slot in spec.get("leader") or []:
        word = (slot["us"] & _DUR_US) | (_DUR_MARK if slot["kind"] == "mark" else 0)
        struct.pack_into("<H", block, slot["at"], word)

    fields = spec.get("pointer_fields", irproto.NEC_OFFSET_FIELDS)
    for off in fields:
        if off + 1 < len(block):
            struct.pack_into("<H", block, off, (_u16(block, off) + position) & 0xFFFF)
    _check_pointers(spec, block, position, fields)
    return bytes(block)


def _check_pointers(spec, block, position, fields):
    """Every field called a pointer has to end up pointing into this block.

    A field that is not really a pointer holds ordinary data, and adding the block's
    position to it silently rewrites that data. Fields copied from another block and
    flagged "assumed" are the usual source: five of seven in one 36.2 kHz protocol were
    durations, and relocating it turned a zero at offset 23 into 65489, freezing the
    remote the moment a device using it transmitted.

    So the claim is checked rather than trusted. A pointer that lands outside the block
    was not a pointer, and building a configuration on it would produce one that cannot
    safely be flashed.
    """
    end = position + len(block)
    wrong = []
    for off in fields:
        if off + 1 >= len(block):
            continue
        value = _u16(block, off)
        if not (position <= value <= end):
            wrong.append((off, value))
    if wrong:
        listed = ", ".join(f"offset {off} holds {value}" for off, value in wrong)
        raise ValueError(
            f"protocol {spec.get('id', '?')} ({spec.get('name', '')}) declares pointer "
            f"fields that do not point into its own block once placed at {position}: "
            f"{listed}; the block covers {position}-{end}.\n"
            "Those fields hold data, not pointers, and writing a position into them "
            "corrupts the block - a remote sent one of these freezes and reboots. Work "
            "out the real fields (every offset whose 16-bit value lands inside the "
            "block is a candidate) before building with it."
        )


def assemble(specs: list[dict]) -> bytes:
    """Merge protocol definitions into one IrProto payload.

    Each block is *generated at* the position it will occupy, which is what makes this
    safe: there is no relocation step to get wrong. The runtime protocol index of a
    device's commands is this list's order, so `specs[0]` is protocol 0.
    """
    count = len(specs)
    pos = 8 + 2 * count
    offsets, blocks = [], []
    for spec in specs:
        block = encode(spec, position=pos)
        offsets.append(pos - 5)              # a block starts at (stored offset + 5)
        blocks.append(block)
        pos += len(block)
    out = bytearray(irproto.PREFIX + struct.pack("<H", count))
    for off in offsets:
        out += struct.pack("<H", off)
    for block in blocks:
        out += block
    return bytes(out)


def extract_definition(block: bytes, payload: bytes, position: int, *, name: str = "") -> dict:
    """Make one imported native block self-contained and relocatable.

    Real Logitech payloads sometimes let an element point into another block's duration
    data. A file containing only the apparent block then preserves an absolute address
    into a configuration that no longer exists. Import materializes every referenced run
    and alphabet into this transient definition instead. The result may have different
    storage bytes, but executes the same element program and can safely move in a rebuild.

    This function is an import boundary, not a second protocol catalogue. Its result is
    carried only as backend-opaque evidence when no portable semantic decoder exists.
    """
    if len(block) < 9:
        raise ValueError("native protocol block is too short")
    body = bytearray(block)
    original_end = position + len(block)
    pointer_fields: list[int] = []

    def target(field: int) -> int:
        if field < 0 or field + 1 >= len(body):
            raise ValueError(f"native protocol pointer field {field} is outside its block")
        return irproto.PROTOCOL_BASE + _u16(body, field)

    def retain(field: int, source: int, size: int, label: str) -> None:
        if size <= 0:
            raise ValueError(f"native protocol {label} has no data")
        if not 0 <= source <= len(payload) - size:
            raise ValueError(
                f"native protocol {label} points outside IrProto payload at {source}")
        if position <= source and source + size <= original_end:
            relative = source - position
        else:
            relative = len(body)
            body.extend(payload[source:source + size])
            struct.pack_into(
                "<H", body, field, position + relative - irproto.PROTOCOL_BASE)
        pointer_fields.append(field)

    elements = []
    for index in range(body[ELEMENT_COUNT_OFF]):
        field = 7 + index * 2
        source = target(field)
        if not position <= source <= original_end - 16:
            raise ValueError(
                f"native protocol element {index} points outside its block at {source}")
        retain(field, source, 16, f"element {index}")
        elements.append(source - position)

    # Two table slots may name the *same* element - `home_logi_dump.ezhex` block 1 has
    # both of its entries pointing at offset 93, the only such block in any configuration
    # available here. Materialising it once per slot relocated its run pointers twice: the
    # second pass read back the address the first pass had already rewritten, treated it
    # as a fresh source, and copied again. The rebuilt block then carried 65499 where a
    # pointer belonged and the safety check refused it - correctly, because that block
    # would have been unflashable.
    #
    # Deduplicate by offset. The pointer table is untouched, so both slots still resolve
    # to the same element; only the copying happens once.
    for index, element in enumerate(dict.fromkeys(elements)):
        alphabet_size = body[element + 8]
        words_per_symbol = body[element + 9]
        for relative, kind in ((10, "alphabet"), (12, "before run"), (14, "after run")):
            field = element + relative
            if _u16(body, field) == 0:
                continue
            source = target(field)
            if kind == "alphabet":
                size = alphabet_size * words_per_symbol * 2
                if size == 0:
                    # An element that reads no symbols never dereferences its alphabet,
                    # so a non-zero pointer there is vestigial - left over from whatever
                    # the block was built from. Refusing it cost a real configuration:
                    # `my-remote.ezhex` block 4 was rejected outright while all 40 of its
                    # commands execute cleanly in `ir_vm`, which is the arbiter for what
                    # the runtime actually reads.
                    #
                    # Null it rather than retain it. This function's whole purpose is to
                    # make an imported block self-contained, and keeping an absolute
                    # address into a configuration that will not exist after the rebuild
                    # is exactly the hazard it was written to remove.
                    struct.pack_into("<H", body, field, 0)
                    continue
            else:
                if not 0 <= source < len(payload):
                    raise ValueError(
                        f"native protocol element {index} {kind} points outside payload")
                size = 1 + payload[source] * 2
            retain(field, source, size, f"element {index} {kind}")

    spec = decode(
        bytes(body), block_id="pending", name=name or "Imported native protocol",
        position=position, offset_fields=tuple(pointer_fields))
    spec["backend"] = "harmony-pk"
    canonical = encode(spec, irproto.CANON_POS)
    spec["id"] = hashlib.sha256(canonical).hexdigest()[:12]
    spec["origin"] = "imported-irproto"
    spec["materialized_external_data"] = len(body) != len(block)
    return spec


def catalog() -> dict:
    """Native build products generated from the portable protocol catalogue."""
    from . import native_registry
    return native_registry.catalog()


def block(block_id: str, position: int = irproto.CANON_POS) -> bytes:
    """One protocol's bytecode, generated for `position`."""
    try:
        return encode(catalog()[block_id], position)
    except KeyError:
        raise LookupError(f"no generated protocol block {block_id!r}") from None


def pointer_fields(block_id: str) -> tuple:
    spec = catalog().get(block_id)
    return tuple(spec["pointer_fields"]) if spec else irproto.NEC_OFFSET_FIELDS


def names() -> dict:
    return {bid: spec.get("name", bid) for bid, spec in catalog().items()}


def load(path) -> dict:
    return json.loads(Path(path).read_text())


def save(spec: dict, path) -> None:
    Path(path).write_text(json.dumps(spec, indent=2) + "\n")




def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    bld = sub.add_parser("build", help="JSON definitions -> an IrProto.bin")
    bld.add_argument("specs", nargs="+")
    bld.add_argument("-o", "--out", required=True)
    args = parser.parse_args(argv)

    payload = assemble([load(p) for p in args.specs])
    irproto.write_payload(args.out, payload)
    print(f"wrote {args.out}: {len(args.specs)} block(s), payload {len(payload)} B")


if __name__ == "__main__":
    main()
