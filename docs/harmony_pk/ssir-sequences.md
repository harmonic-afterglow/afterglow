# `SsIr.bin` - device sequences (Harmony 1100)

On the Harmony 1100 every command is a recording. Its firmware has no protocol programs
(no `IrProto.bin`) and sends a command with `ir_send_device_ir(deviceIndex, sequence,
usePresilence)` (`IRQueue.lua`): it plays back a stored sequence. The configuration's
controller declares this with `<Type>Device Sequence</Type>`, where the 900's says
`Protocol Code`. `SsIr.bin` keeps the 900's file name but not its layout - see
[ssir.md](ssir.md) for that one.

## Evidence

Decoded from a Logitech-generated Harmony 1100 configuration (skin 62): five devices and
518 sequences, every pointer resolving and every sequence fitting the layout below. The
first Samsung sequence decodes to an exact Samsung32 frame; the Xbox 360's decode to RC6
mode 6 frames. The firmware compared against is 63.7.7 (skin 63), byte-identical to 62.7.7.

## How a command selects a sequence

```xml
<Command><Name>PowerOff</Name><Data><ControllerId>0</ControllerId>
  <Press><DeviceIndex>0</DeviceIndex><SequenceIndex>0</SequenceIndex></Press>
  <Hold><DeviceIndex>0</DeviceIndex><SequenceIndex>64</SequenceIndex></Hold></Data></Command>
```

`DeviceIndex` is a position in this file's device directory, not the device's `<Id>`.
`<Press>` and `<Hold>` are separate sequences. `Device.lua` also reads an optional
`<Type>` in `<Data>` and an optional `<Duration>` beside each index; neither appears in
the configuration examined. Each device carries `<ControllerId>0</ControllerId>`, which
must match the command's.

## Layout

All integers are little-endian. Pointers are 3-byte absolute offsets into the file.

    0   u16   version (1)
    2   u24   -> root directory
    5   ...   data pool: waveform words, carrier descriptors and sequence records

    root        u8 device count, then one u24 -> device table per device
    device      u8 0, u16 sequence count, then one u24 -> sequence record per sequence
    sequence    u8 n, then n x u24 -> carrier descriptor
                u8 m, then m variants of 9 bytes each:
                  u24 -> waveform
                  u24 -> repeat point inside that waveform (0 when none)
                  3 bytes, zero in every sequence seen (preserved verbatim)
    carrier     u8 0, u24 carrier period in ns, u24 on-time in ns (7 bytes)
    waveform    u16 words: bit 15 set for a mark, bits 0-14 the duration in us

`n` was 1 in every sequence seen. A waveform has no length of its own: it runs up to the
next structure in the pool, whichever that is.

## Segments

A waveform is a list of segments, each ended by the two words `0x0001 0x0000`. Each
segment begins with its lead-in silence: the device's `PressPreSilence` before a press
(1000 ms on the Samsung, 500 ms on the others), its `HoldPreSilence` before the first
hold segment, none before a repeat segment. Durations longer than 32767 us are written as
several space words.

| Sequence | Segments per variant | Repeat point |
|---|---|---|
| Press | 1 | none |
| Hold | 2: start, then the part repeated while held | start of the repeat segment |

Variants are the alternatives a command plays in turn. A protocol with a toggle bit (RC5,
RC6) has one per toggle state, in the order the firmware plays them: the Xbox 360's
PowerOff press is `800ff429` then `800f7429`, identical but for RC6's toggle bit. The
firmware does no toggling of its own. Other protocols have one variant. In the
configuration examined, all 518 sequences follow this table exactly.
