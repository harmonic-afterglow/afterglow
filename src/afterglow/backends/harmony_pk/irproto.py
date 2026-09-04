#!/usr/bin/env python3
r"""
irproto.py - encoder/decoder for the IrProto.bin protocol blob (PK payloads).

Format (reverse-engineered from irgen via Ghidra + verified byte-exact against the
Rotel dump and the 3-block factory OOB config; see VM_NOTES.md):

  FILE:     [0:4] u32 CRC32(payload)   [4:8] u32 len(payload)   [8:] payload
  PAYLOAD:  [0:6]  fixed prefix  01 01 05 00 00 01
            [6:8]  u16  block count N
            [8 + 2i : ] u16 offset_i     ->  block i starts at (offset_i + 5)
            [ ... ] the N block bodies, concatenated

  BLOCK (NEC/Samsung family, 38 kHz):
            [0]     flag (0x01)
            [1:5]   u32  carrier period in ns   (26315 -> 38.00 kHz)
            [5]     u8   PWM parameter (50 in every currently known block)
            [6]     u8   element-table count
            [7:9]   u16  LEADER-MARK repeat count in units:
                         16 * 562 = 8992 ~= 9000  (NEC leader mark)
                          8 * 562 = 4496 ~= 4500  (Samsung leader mark)
            ...     element defs (durations 4490 lead-space / 2230 repeat live here)

Build a Samsung protocol by cloning the working NEC block (Protocol 0) and dropping
the leader-mark count 16 -> 8, then appending it as a new protocol index.
"""
import struct
import zlib
import sys

PREFIX = bytes.fromhex("010105000001")     # 6-byte protocol-table prefix
PROTOCOL_BASE = 5                           # firmware's base for every stored pointer
U16 = lambda b, o: b[o] | (b[o + 1] << 8)
# Supported native programs are compiled from portable protocol definitions. Unknown
# imported programs are materialized transiently and carried with backend-opaque evidence.


class IrProtoError(ValueError):
    """The payload is not a well-formed IrProto table.

    These are checks on *data read from a file*, not on this module's own logic, so they
    are raised rather than asserted: `python -O` removes assertions, and the length and
    CRC checks below are the only thing standing between a corrupt IrProto.bin and a
    configuration built from it.
    """


def read_payload(path):
    with open(path, "rb") as file:
        raw = file.read()
    if len(raw) < 8:
        raise IrProtoError(f"IrProto payload is {len(raw)} bytes, too short for its header")
    crc, n = struct.unpack_from("<I", raw, 0)[0], struct.unpack_from("<I", raw, 4)[0]
    payload = raw[8:]
    if len(payload) != n:
        raise IrProtoError(f"len mismatch: header={n} actual={len(payload)}")
    if (zlib.crc32(payload) & 0xffffffff) != crc:
        raise IrProtoError("CRC32 mismatch")
    return payload


def parse_proto(payload):
    """Split the payload into its list of block bodies (bytes)."""
    if payload[:6] != PREFIX:
        raise IrProtoError(f"bad prefix {payload[:6].hex()}")
    count = U16(payload, 6)
    starts = [U16(payload, 8 + 2 * i) + 5 for i in range(count)]   # block start = offset + 5
    bounds = starts + [len(payload)]
    blocks = [payload[bounds[i]:bounds[i + 1]] for i in range(count)]
    return blocks, starts


# element-offset RELOCATION
# Element defs are addressed as (base + offset) where base is the protocol-data pointer
# at payload+5, set once at load, NOT per-block. So a block's internal element-table
# offsets are ABSOLUTE and must be rewritten when (and ONLY when) the block MOVES.
#
# For the NEC/Samsung-family block, the offset fields are exactly these 7 u16 slots -- VERIFIED
# byte-exact against factory firmware: relocating precisely these by the block's position delta
# reproduces the factory's relocated NEC block. (element table {7,9} + the two element defs.)
# We only ever move the Samsung clone (a copy of the NEC block), so these are the right fields.
# NOTE: repacking a donor's blocks unchanged needs NO offset knowledge -- each block lands at its
# original position (delta 0), so nothing is rewritten and the payload round-trips byte-exact.
CANON_POS = 10                                 # canonical NEC block position in our template
NEC_OFFSET_FIELDS = (7, 9, 21, 23, 25, 55, 57)

def relocate_block(block, old_pos, new_pos, offset_fields=NEC_OFFSET_FIELDS):
    """Shift a block's absolute element-offset fields by (new_pos - old_pos). No-op when the
    block doesn't move. offset_fields defaults to the verified NEC/Samsung set."""
    b = bytearray(block)
    delta = new_pos - old_pos
    if delta:
        for o in offset_fields:
            if o + 1 < len(b):
                struct.pack_into("<H", b, o, (U16(b, o) + delta) & 0xffff)
    return bytes(b)

def build_proto(blocks, starts=None, offset_fields=NEC_OFFSET_FIELDS):
    """Reassemble a payload from a list of block bodies. `starts` = each block's ORIGINAL position
    (from parse_proto); a block only gets its offsets relocated if its new position differs. When
    `starts` is omitted, every block is assumed to have come from CANON_POS (our NEC/Samsung case)."""
    if starts is None:
        starts = [CANON_POS] * len(blocks)
    count = len(blocks)
    out = bytearray(PREFIX + struct.pack("<H", count))
    pos = 8 + 2 * count
    placed, offs = [], []
    for i, b in enumerate(blocks):
        offs.append(pos - 5)                   # block start = stored offset + 5
        placed.append(relocate_block(b, starts[i], pos, offset_fields))
        pos += len(b)
    for o in offs:
        out += struct.pack("<H", o)
    for b in placed:
        out += b
    return bytes(out)


# multi-protocol ASSEMBLER (donor blocks)
# Combine generated programs and legacy evidence into one IrProto. Each block's
# element-offset fields are relocated to its assembled position using its verified
# per-block pointer set. Runtime protocol index = list order.
def load_offset_fields(lib_dir=None):
    """{block_id: [pointer field offsets]} from the protocol library."""
    from . import protocol_json
    return {bid: list(spec["pointer_fields"]) for bid, spec in protocol_json.catalog().items()}

def load_block(block_id, lib_dir=None):
    """A canonical block (at CANON_POS), generated from its JSON definition."""
    from . import protocol_json
    return protocol_json.block(block_id, CANON_POS)

def assemble(block_ids, definitions=None, lib_dir=None):
    """Assemble an IrProto payload from an ordered list of canonical block IDs.

    Each block is generated at the position it will occupy; see protocol_json.assemble,
    which this delegates to.
    """
    from . import protocol_json
    cat = protocol_json.catalog()
    for block_id, definition in (definitions or {}).items():
        if definition.get("id") != block_id:
            raise ValueError(
                f"protocol definition key {block_id!r} contains id "
                f"{definition.get('id')!r}")
        if block_id in cat:
            built_in = protocol_json.encode(cat[block_id], position=CANON_POS)
            external = protocol_json.encode(definition, position=CANON_POS)
            if built_in != external:
                raise ValueError(
                    f"External protocol block {block_id} conflicts with the built-in block")
        else:
            cat[block_id] = definition
    missing = [block_id for block_id in block_ids if block_id not in cat]
    if missing:
        # A block the importer could not make self-contained reaches here as an id with
        # no definition. `cat[bid]` then raised a bare KeyError naming a hex digest,
        # which tells nobody anything. Say which device cannot be rebuilt and why the
        # block is unusable, because the honest outcome is a named refusal rather than
        # a config assembled around a block cannot be reproduce.
        raise ValueError(
            "cannot assemble IrProto: no self-contained definition for protocol "
            f"block(s) {', '.join(sorted(set(missing)))}. They were imported as "
            "native-only evidence because the source block could not be made "
            "relocatable; the devices using them can be read but not rebuilt.")
    return protocol_json.assemble([cat[bid] for bid in block_ids])


def _assemble_from_binaries(block_ids, lib_dir=None):
    """Historical path, kept only as the cross-check the tests compare against."""
    offsets_map = load_offset_fields(lib_dir)
    count = len(block_ids)
    out = bytearray(PREFIX + struct.pack("<H", count))
    pos = 8 + 2 * count
    offs, placed = [], []
    for bid in block_ids:
        block = load_block(bid, lib_dir)
        fields = tuple(offsets_map.get(bid, NEC_OFFSET_FIELDS))
        offs.append(pos - 5)                                  # block start = stored offset + 5
        placed.append(relocate_block(block, CANON_POS, pos, fields))
        pos += len(block)
    for o in offs:
        out += struct.pack("<H", o)
    for b in placed:
        out += b
    return bytes(out)


def write_payload(path, payload):
    """Write payload back with a correct [CRC32][len] header (rehash still syncs the XML)."""
    crc = zlib.crc32(payload) & 0xffffffff
    with open(path, "wb") as f:
        f.write(struct.pack("<I", crc))
        f.write(struct.pack("<I", len(payload)))
        f.write(payload)
    return crc


# leader duration edit (VERIFIED on hardware)
# The IR emitter (IrgenIntrHandler) plays durations as u16 words read from the block:
#   bit 15 = mark(1)/space(0),  bits 0..14 = microseconds.
# The leader's two durations are a plain u16 pair at block-rel 28 (mark) and 30 (space):
#   NEC:      block[28:30]=0xA31E (8990us MARK)   block[30:32]=0x118A (4490us SPACE)
#   Samsung:  block[28:30]=0x9194 (4500us MARK)   block[30:32]=0x1194 (4500us SPACE)
# Confirmed on the remote: editing block[30:32] moved the emitted leader space 4490->3000,
# and setting block[28:30]=0x9194 made the TV/capture decode genuine Samsung (addr 0x07).
LEADER_MARK_OFF, LEADER_SPACE_OFF = 28, 30      # block-relative u16 offsets
ELEM_COUNT_OFF = 6                              # block-relative: number of elements

def _dur(us, mark):
    return (us & 0x7fff) | (0x8000 if mark else 0)

ELEM0_OFF, ELEM1_OFF = 7, 9                    # block-rel u16 element-table slots (elem0, elem1)

def samsung_from_nec(nec_block, mark_us=4500, space_us=4500, full_frame_repeat=True):
    """Clone the working NEC block into a Samsung block (VERIFIED end-to-end on hardware):
      * leader 9000/4500 -> 4500/4500  (block-rel 28/30 u16 durations, bit15 = mark flag), and
      * full_frame_repeat: point the HOLD-repeat element (element-table slot 1) at the main
        element (slot 0), so on hold the frame is re-played as a full 4500-leader frame instead
        of the dataless NEC short-repeat that Samsung ignores.
    For the repeat to carry the real command data, the Code must include a SECOND copy of the
    data at the repeat cursor (build_config.samsung_code repeat=True does this). Together: hold
    ramps volume/channel like a real Samsung remote. Carrier/bit timing untouched; NEC gear on
    Protocol 0 unaffected."""
    b = bytearray(nec_block)
    struct.pack_into("<H", b, LEADER_MARK_OFF, _dur(mark_us, True))
    struct.pack_into("<H", b, LEADER_SPACE_OFF, _dur(space_us, False))
    if full_frame_repeat:
        b[ELEM1_OFF], b[ELEM1_OFF + 1] = b[ELEM0_OFF], b[ELEM0_OFF + 1]   # elem1 slot -> elem0
    return bytes(b)

def block_info(block):
    period = struct.unpack_from("<I", block, 1)[0]
    lm, ls = U16(block, LEADER_MARK_OFF), U16(block, LEADER_SPACE_OFF)
    return dict(flag=block[0], period_ns=period, khz=1e9 / period / 1000,
                pwm_parameter=block[5], element_count=block[6],
                lead_mark_us=lm & 0x7fff, lead_space_us=ls & 0x7fff, size=len(block))


if __name__ == "__main__":
    # self-test: round-trip the dump payload and print block info
    p = sys.argv[1] if len(sys.argv) > 1 else "configs/mine/extracted/userconfig/IrProto.bin"
    payload = read_payload(p)
    blocks, starts = parse_proto(payload)
    if build_proto(blocks, starts) != payload:
        raise SystemExit("round-trip FAILED")
    print(f"round-trip OK: {len(blocks)} block(s), payload {len(payload)} B")
    for i, b in enumerate(blocks):
        info = block_info(b)
        print(f"  block {i}: {info['size']}B  {info['khz']:.2f}kHz  "
              f"pwm={info['pwm_parameter']} elements={info['element_count']}  "
              f"leader {info['lead_mark_us']}us mark / {info['lead_space_us']}us space")
    sam = samsung_from_nec(blocks[0])
    si = block_info(sam)
    print(f"  samsung clone: leader -> {si['lead_mark_us']}us mark / {si['lead_space_us']}us space")
