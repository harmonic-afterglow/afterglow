# `IrProto.bin` - IR protocol bytecode

Each entry in `IrProto.bin` is a small bytecode program the remote's IR generator runs to
produce a pulse train. A command supplies the parameters; the block says how to shape
them.

## Container

    6 bytes     prefix
    u16         block count
    u16 * n     one offset per block; the block begins at offset + 5

The same envelope as [`SsIr.bin`](ssir.md).

## How a command selects a block

A device command carries a `<Code>`, and the code's bytes address both the block and the
data:

    byte 0      protocol index into IrProto.bin
    byte 4      minimum repeat count

NEC is assigned index 0 so that NEC codes keep byte 0 = `00`; the remaining protocols
follow in first-use order. Codes beginning `0xFFFF` are not protocol-encoded at all - see
[ssir.md](ssir.md).

## Block structure

| Field | Meaning |
|---|---|
| `flag` | Leading flag byte |
| `carrier_period_ns` | The IR carrier, as the block stores it - a period, not a frequency |
| `pwm_parameter` | Raw byte passed to the carrier/PWM setup calculation |
| `element_count` | Number of element-table entries |
| `leader[]` | Two leader duration slots, where the family has them: `{at, kind, us}` |
| *element bytecode* | The program itself |

### Leader slots are not always mark-then-space

The bit-15 mark flag is recorded per slot rather than assumed, because the order varies
between protocol families. Some families use those bytes for element pointers instead and
have no leader slots at all.

### Element pointers are absolute

A block's element pointers are **absolute offsets into the assembled payload**, so the
same protocol has different bytes depending on where it lands in the file.

This is the single most important property of the format. It means a block cannot be
copied from one configuration into another, and relocating one by patching bytes is
fragile. The workable approach is to *generate* each block at the position it will
occupy.

## Text form

Stored as `.bin` a block is opaque, unreviewable and impossible to diff, so Afterglow
keeps protocol definitions as JSON and converts them to bytes. Two properties make that
safe:

**Lossless.** Re-encoding a decoded block reproduces it byte for byte. Bytes whose
meaning is not yet known are preserved verbatim as `body_hex` rather than guessed at.

**Position independent.** The JSON stores element pointers relative to the block's own
start, and encoding writes absolute values for wherever the block is being placed.

### What is decoded

Editable: `carrier_period_ns`, `pwm_parameter`, `element_count`, `flag`, `leader[]`.

Derived and ignored when encoding: `carrier_hz` (a frequency does not always round-trip
back to the stored period) and `durations`.

Preserved verbatim: the element bytecode, as `body_hex`. Its layout is understood well
enough to relocate but not to rewrite. Inventing a schema for bytes that cannot be
regenerated would be a lie in a file format.

## Code framing

A generated block plays nothing on its own. The `<Code>` selects which elements run, in
which stage, and supplies their payload bits.

    Code    = <protocol index:1> <header:4> <stream>
    stream  = stage sections, where a leading 0x00 byte advances the stage
    section = <element count:1> then count x ( <element index:1> <payload...> )

The VM reads the stream from byte 5 (`CarrierVm.command`); `sequence_init` takes the
count, `element_init` takes each index, and the data section pulls payload bytes as it
consumes symbols. Observed directly:

    nec1    01 00 5EA158A7 | 01 01          stage 2: element 0 + 32 bits
                                            stage 3: element 1, no payload
    jvc16   02 00 01 5A5A  | 01 01 5A5A     stage 2: leader element then data
    rc5-13  00 | 01 00 0AD0                 leading zero, so stage 3 only

Payload bits are packed MSB-first and **left-aligned in whole bytes**, which is why RC5's
13 bits appear as `value << 3` and RC6-MCE's 30 as `value << 2`.

This grammar was read off the VM by tracing how it consumes Codes already proven on
hardware, not inferred from their shape.

## Repeats

The VM's stages, established by tracing the interpreter:

| Stage | Meaning |
|---|---|
| 2 | Press |
| 3 | Repeat - the only stage carrying a repeat condition |
| 4, 5 | Once-through sections |
| 6 | Terminate |

The repeat count is `max(minimum, held + 1)`, where the minimum comes from byte 4 of the
code.
