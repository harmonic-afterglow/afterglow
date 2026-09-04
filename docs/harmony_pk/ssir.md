# `SsIr.bin` - recorded waveforms

Most commands are *generated*: a block in [`IrProto.bin`](irproto.md) says how to shape a
pulse train and the command supplies address and data. Some equipment cannot be described
that way, so its buttons carry a recorded waveform instead. Those waveforms live in
`SsIr.bin`.

## Evidence

The remote's own `ir_mgr` binary contains the string `/SsIr.bin`, the source file name
`source/ir_raw_data.c`, the functions `raw_ir_data_init`, `raw_ir_get_sequence_length`
and `raw_ir_get_sequence_string`, and the error `Can't find raw IR index in SsIr.bin
file`.

## How a command selects an entry

A `<Code>` beginning `0xFFFF` is not protocol-encoded. Its third byte is an index into
this file:

    <Code>0xFFFF0A00</Code>     ->  raw entry 0x0A

Confirmed against a real configuration: a lighting controller with eleven such commands,
`0xFFFF0000` through `0xFFFF0A00`, in a configuration whose `SsIr.bin` holds exactly
eleven entries.

Two unrelated owners' configurations carry byte-identical `SsIr.bin` files together with
the same device id, so a waveform set travels with the device definition rather than
being learned per user.

## Container

The same envelope as `IrProto.bin`:

    6 bytes     prefix
    u16         entry count
    u16 * n     one offset per entry; the entry begins at offset + 5

## Entry contents

Pulse data, not protocol programs. The entries are carried whole and nothing attempts to
interpret them. That is sufficient to keep a raw-IR device working, which is the only
thing depending on this file.
