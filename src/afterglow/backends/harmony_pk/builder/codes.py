"""Harmony PK command framing: portable parameters into a native `Code`.

A `Code` is what the remote's IR generator plays. Its **first byte is the protocol
index** - which block in `IrProto.bin` to run - and the rest is the framed payload.
Getting byte 0 wrong makes the remote transmit the right data with the wrong timing.

The Harmony sends each payload byte in REVERSED BIT ORDER (confirmed with a VS1838B
capture), so every logical byte is bit-reversed on the way in.

Only protocols whose framing we can actually generate live here. Everything else must
arrive with real captured codes; see SYNTHESIZABLE_PROTOCOLS.
"""

# codes start 01). The <Protocol>N</Protocol> XML tag alone is NOT enough -- the Code's byte0
# must ALSO be N or the remote grabs the wrong block. `code_pre(proto)` builds the prefix.
PRE, SUF = "0000E803010100", "010100"     # NEC framing; PRE[0:2]='00' is the protocol-0 byte
def code_pre(proto): return "%02X%s" % (proto & 0xFF, PRE[2:])   # byte0 = protocol index

def _b(x): return int(x, 16) if isinstance(x, str) else x

def bitrev(x):
    x = _b(x); r = 0
    for i in range(8):
        r = (r << 1) | ((x >> i) & 1)
    return r & 0xFF

def nec_code(addr, cmd, pre=PRE, repeat=False):
    """Standard NEC (addr + ~addr, cmd + ~cmd), each byte stored bit-reversed."""
    a, c = _b(addr), _b(cmd)
    frame = [a, a ^ 0xFF, c, c ^ 0xFF]
    data = "".join("%02X" % bitrev(b) for b in frame)
    return "0x" + pre + data + SUF[:-2] + (data if repeat else "") + ("" if repeat else SUF[-2:])

def necext_code(addr_lo, addr_hi, cmd, pre=PRE, repeat=False):
    """Extended NEC (two raw address bytes, cmd + ~cmd), each byte stored bit-reversed."""
    lo, hi, c = _b(addr_lo), _b(addr_hi), _b(cmd)
    frame = [lo, hi, c, c ^ 0xFF]
    data = "".join("%02X" % bitrev(b) for b in frame)
    return "0x" + pre + data + SUF[:-2] + (data if repeat else "") + ("" if repeat else SUF[-2:])

def samsung_code(addr, cmd, pre=PRE, repeat=True):
    """Samsung32: addr repeated (NOT complemented), cmd + ~cmd, each byte bit-reversed.
    e.g. addr 0x07 cmd 0x02 -> frame 07 07 02 FD -> stored E0 E0 40 BF (=0xE0E040BF).

    repeat=True appends a SECOND copy of the data after the framing (minus the suffix's trailing
    byte, to align it), so on HOLD the block's full-frame-repeat element (see irproto) re-reads
    real command data instead of zeros -> the TV keeps stepping. VERIFIED on hardware."""
    a, c = _b(addr), _b(cmd)
    data = "".join("%02X" % bitrev(b) for b in [a, a, c, c ^ 0xFF])
    if repeat:
        return "0x" + pre + data + SUF[:-2] + data     # 2nd data copy at the hold-repeat cursor
    return "0x" + pre + data + SUF


def rc6_mce_code(code, proto=0):
    """Microsoft 30-bit/RC6-MCE payload in Harmony PK's native Code framing.

    The 30-bit keycode is left-shifted into the 32-bit field. This exact relationship
    holds for every command shared by the archive MCE EU set and two independent donor
    configurations; the native block and Volume Up path were hardware-validated.
    """
    value = _b(code)
    if not 0 <= value < 1 << 30:
        raise ValueError(f"RC6-MCE code must fit 30 bits, got {value!r}")
    return f"0x{proto:02X}00F40100000100{value << 2:08X}00"


def sony_code(code, bits, proto=0):
    """Frame one Sony SIRC value, aligned to its enclosing native bytes."""
    value = _b(code)
    if not 0 <= value < 1 << bits:
        raise ValueError(f"Sony{bits} code must fit {bits} bits, got {value!r}")
    octets = (bits + 7) // 8
    aligned = value << (octets * 8 - bits)
    return f"0x{proto:02X}00F40103000100{aligned:0{octets * 2}X}00"


def sony12_code(code, proto=0):
    """Compatibility wrapper for callers that named the first Sony width."""
    return sony_code(code, 12, proto)


def jvc16_code(code, proto=0):
    """Frame a JVC leader+data press followed by its leaderless hold frame."""
    value = _b(code)
    if not 0 <= value < 1 << 16:
        raise ValueError(f"JVC16 code must fit 16 bits, got {value!r}")
    data = f"{value:04X}"
    return f"0x{proto:02X}00F40100020001{data}0101{data}00"


def rc5_13_code(code, proto=0):
    """Pack RC5's data around the native toggle at transmitted bit position 1."""
    value = _b(code)
    if not 0 <= value < 1 << 13:
        raise ValueError(f"RC5-13 code must fit 13 bits, got {value!r}")
    transmitted = (((value >> 12) & 1) << 12) | (value & 0x7FF)
    return f"0x{proto:02X}00F40100000100{transmitted << 3:04X}00"

CODECS = {"nec": nec_code, "samsung": samsung_code}


def encode_parameters(codec: str, parameters: dict, proto: int, *,
                      repeat_data_copy: bool = False) -> str:
    """Encode portable parameters with one already-selected native Code codec."""
    pre = code_pre(proto)
    if codec == "nec":
        return nec_code(
            parameters["address"], parameters["command"], pre, repeat=repeat_data_copy)
    if codec == "necext":
        return necext_code(parameters["address_low"], parameters["address_high"],
                           parameters["command"], pre, repeat=repeat_data_copy)
    if codec == "samsung":
        return samsung_code(parameters["address"], parameters["command"], pre,
                            repeat=repeat_data_copy)
    if codec == "rc6-mce":
        return rc6_mce_code(parameters["code"], proto)
    if codec == "sony12":
        return sony_code(parameters["code"], 12, proto)
    if codec == "sony15":
        return sony_code(parameters["code"], 15, proto)
    if codec == "sony20":
        return sony_code(parameters["code"], 20, proto)
    if codec == "jvc16":
        return jvc16_code(parameters["code"], proto)
    if codec == "rc5-13":
        return rc5_13_code(parameters["code"], proto)
    raise ValueError(f"unknown Harmony PK code codec {codec!r}")

# Blocks whose *Code framing* this builder knows, not merely whose pulse program it can
# emit. A block alone is not enough to manufacture commands: the Code format is
# protocol-specific, and inventing one would produce a config that builds, flashes and
# transmits something plausible and wrong.
#
# The three below are the hardware-anchored families, kept explicit because their block
# ids are proven constants. Everything else is derived from `mappings.PROTOCOLS` at call
# time - see `native_registry.code_codecs()`. This list was previously the whole answer
# and went stale: Sony, JVC and RC5 gained emitters and codecs while it still said NEC,
# Samsung and RC6, so building a generated Sony device was refused as "donor-only".
PROVEN_SYNTHESIZABLE = {
    "a7b8a0e6c639": "nec",
    "e8f716b9ee19": "samsung",
    "6bd42e0eea79": "rc6-mce",
}


def synthesizable_protocols() -> dict[str, str]:
    """``{block id: Code codec}`` for every family this builder can manufacture."""
    from ..native_registry import code_codecs

    out = dict(PROVEN_SYNTHESIZABLE)
    out.update(code_codecs())
    return out


class _SynthesizableView(dict):
    """Backwards-compatible mapping that resolves generated families lazily.

    Importing `ir_emit` at module import time would make the builder pay for emitting
    twelve protocol programs just to be imported, so the set is computed on first use.
    """

    def _resolved(self):
        return synthesizable_protocols()

    def get(self, key, default=None):
        return self._resolved().get(key, default)

    def __getitem__(self, key):
        return self._resolved()[key]

    def __contains__(self, key):
        return key in self._resolved()

    def __iter__(self):
        return iter(self._resolved())

    def __len__(self):
        return len(self._resolved())

    def items(self):
        return self._resolved().items()

    def keys(self):
        return self._resolved().keys()

    def values(self):
        return self._resolved().values()


SYNTHESIZABLE_PROTOCOLS = _SynthesizableView()


def portable_code(signal: dict, proto: int) -> str:
    """Lower a portable protocol signal to a proven Harmony PK Code representation.

    Describable does not imply native support. Only the explicit backend mappings in
    `library/protocols` reach this function; other semantic protocols can still
    be rendered to waveforms for a backend with understood raw-waveform construction.
    """
    from .... import ir_signal
    from ..mappings import protocol as protocol_mapping

    ir_signal.validate(signal)
    if signal["kind"] != "protocol":
        raise ValueError(f"Harmony protocol lowering needs a protocol signal, got "
                         f"{signal['kind']!r}")
    backend = protocol_mapping(signal["protocol"])
    if backend is None:
        raise ValueError(
            f"protocol {signal['protocol']!r} has no proven Harmony PK native lowering")
    return encode_parameters(
        backend["code_codec"], signal["parameters"], proto,
        repeat_data_copy=backend.get("repeat_data_copy", False))

def esc(s): return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")


# generic Code framing
#
# Format reference: docs/harmony_pk/irproto.md - the Code selects which elements run, in which
# stage, and supplies their payload bits, packed MSB-first and left-aligned.

HEADER_PRESS = bytes.fromhex("00E80301")     # 1000 ms press pre-silence
HEADER_HOLD = bytes.fromhex("00F40100")      # 500 ms variant used by the newer families


def pack_bits(chunks, total_bits: int) -> bytes:
    """Pack (value, width, order) chunks MSB-first, left-aligned into whole bytes.

    `order` is the portable field's own bit order. A field declared ``lsb`` is reversed
    within its width here rather than at emission time, because the wire is always sent
    most-significant-first; the ordering is a property of the field, not of the remote.
    """
    accumulator = 0
    for value, width, order in chunks:
        if width <= 0:
            continue
        value &= (1 << width) - 1
        if order == "lsb":
            value = int(f"{value:0{width}b}"[::-1], 2)
        accumulator = (accumulator << width) | value
    if total_bits <= 0:
        return b""
    padding = (-total_bits) % 8
    accumulator <<= padding
    return accumulator.to_bytes((total_bits + padding) // 8, "big")


def _expanded(occurrences, phase: str) -> list[dict]:
    out = []
    for occurrence in occurrences:
        if occurrence["phase"] != phase:
            continue
        for _ in range(occurrence["count"]):
            out.append({**occurrence, "count": 1})
    return out


def _occurrence_key(definition: dict, occurrence: dict) -> tuple[str, bytes]:
    """The native meaning relevant when deciding whether two stages are identical."""
    return occurrence["frame"], _frame_payload(definition, occurrence)


def transmission_plan(definition: dict, parameters: dict, *,
                      transmission: dict | None = None,
                      minimum_repeats: int | None = None) -> dict:
    """Resolve portable occurrences into native press/repeat/finish stages.

    Bindings and literal arguments are already concrete in the occurrences returned by
    `ir_protocol.resolve_transmission`. Counts remain semantic until this lowering: a
    press made from repetitions of the complete hold stage uses the firmware's stage-3
    minimum count, as does a protocol declaring `hold_minimum`; other repetitions stay as
    distinct element occurrences in their stage.
    """
    from .... import ir_protocol

    resolved = ir_protocol.resolve_transmission(
        definition, parameters, sequence=transmission)
    release = _expanded(resolved, "release")
    press = _expanded(resolved, "press")
    hold = _expanded(resolved, "hold")
    if not press:
        raise ValueError(
            f"portable protocol {definition['id']!r} has no resolved press occurrences")

    press_keys = [_occurrence_key(definition, item) for item in press]
    hold_keys = [_occurrence_key(definition, item) for item in hold]
    repeated_hold = 0
    if (hold_keys and len(press_keys) % len(hold_keys) == 0
            and press_keys == hold_keys * (len(press_keys) // len(hold_keys))):
        repeated_hold = len(press_keys) // len(hold_keys)

    if repeated_hold:
        sections = [{"stage": 3, "occurrences": hold}]
        derived_repeats = repeated_hold if repeated_hold > 1 else 0
    elif hold:
        sections = [
            {"stage": 2, "occurrences": press},
            {"stage": 3, "occurrences": hold},
        ]
        derived_repeats = 0
    else:
        sections = [{"stage": 2, "occurrences": press}]
        derived_repeats = 0
    if release:
        sections.append({"stage": 5, "occurrences": release})

    # A protocol may mandate a number of hold runs that the occurrence lists alone do not
    # show: `press` is a distinct start and `hold` appears once, yet a tap must still emit
    # the hold frame several times. `derived_repeats` only sees repetition already spelled
    # out in the press list, so take whichever count is larger.
    declared = ir_protocol.hold_minimum(definition, transmission)
    repeats = (max(derived_repeats, declared) if minimum_repeats is None
               else minimum_repeats)
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not 0 <= repeats <= 0xFF:
        raise ValueError("native minimum repeat count must be an integer in 0..255")
    return {
        "occurrences": resolved,
        "sections": sections,
        "minimum_repeats": repeats,
    }


def generic_code(definition: dict, element_index, parameters: dict, proto: int, *,
                 pre_silence_us: int = 500, minimum_repeats: int | None = None,
                 transmission: dict | None = None) -> str:
    """Frame any portable definition's command for a generically emitted block.

    ``element_index`` maps a frame name to its index in the block's element table, which
    `ir_emit._generic_body` assigns by construction.

    Byte 4 is the minimum stage-3 execution count. A repeated one-frame portable press
    therefore lowers directly to it: Sony's three-frame press carries 3 and executes
    three frames. Values 0 and 1 both execute a single frame, so the canonical generic
    encoding uses 0 unless the portable press explicitly requires more than one.

    An explicit value remains available for lossless imported metadata, but the VM gate
    rejects it if it changes the portable press lifecycle.

    Stage placement follows what the traced Codes do. A protocol whose press and hold are
    the same single frame emits no stage-2 section at all - the stream opens with 0x00 to
    step straight to the repeat stage, which is what RC5, RC6 and Sony do. Anything with
    a distinct press emits stage 2 then stage 3, like NEC and JVC.
    """
    def section(occurrences) -> bytearray:
        out = bytearray()
        if not occurrences:
            return out
        if len(occurrences) > 0xFF:
            raise ValueError("a native Code stage can contain at most 255 elements")
        out.append(len(occurrences))
        for occurrence in occurrences:
            name = occurrence["frame"]
            if name not in element_index:
                raise ValueError(f"frame {name!r} has no element in the emitted block")
            out.append(element_index[name])
            out += _frame_payload(definition, occurrence)
        return out

    plan = transmission_plan(
        definition, parameters, transmission=transmission,
        minimum_repeats=minimum_repeats)
    stream = bytearray()
    encoded_stage = 2
    for native_section in plan["sections"]:
        while encoded_stage < native_section["stage"]:
            stream.append(0x00)
            encoded_stage += 1
        stream += section(native_section["occurrences"])
        encoded_stage += 1
    stream.append(0x00)

    header = (bytes((0x00,)) + int(pre_silence_us).to_bytes(2, "little")
              + bytes((plan["minimum_repeats"],)))
    return "0x" + bytes((proto & 0xFF,)).hex().upper() + header.hex().upper() \
        + stream.hex().upper()


def _frame_payload(definition: dict, occurrence: dict) -> bytes:
    """The payload bits one element consumes, in transmission order.

    Field semantics come from `ir_protocol._segment_value`, the renderer's own function,
    rather than a copy. Reimplementing it produces a Code whose bits disagree with the
    waveform the same definition renders: a segment with an `offset` and no explicit
    `bits` takes `source_bits - offset`, not the whole parameter, and `constant` segments
    need handling. A checker must call what it checks, not model it.
    """
    from .... import ir_protocol

    frame = (definition.get("frames") or {})[occurrence["frame"]]
    # Sender state is substituted by the firmware at the element's toggle position, so
    # the Code carries a zero placeholder wherever state appears.
    state = {name: 0 for name in (definition.get("state") or {})}

    chunks, total = [], 0
    for segment in frame.get("segments") or []:
        if "burst" in segment:
            continue
        value, bits = ir_protocol._segment_value(
            segment, occurrence["values"], occurrence["declarations"], state)
        chunks.append((value, bits, segment.get("order", "msb")))
        total += bits
    return pack_bits(chunks, total)
