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
                  u24 -> repeat point (0 when none): inside that waveform, or
                         inside another waveform of the same device (shared repeat)
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
| Hold, shared repeat | 1: start | start of a repeat segment in another waveform |

A shared repeat is how Logitech stores a frame every hold of a device repeats, such as
NEC's repeat burst (9000 us mark, 2250 us space, 560 us mark): the device's first hold
carries it as its own second segment, and later holds of that device point their repeat
at it. A second real configuration (Nokia_guy123's) has 100 such holds across three
devices; Jdunbar's has none. They are read as `Variant.shared_repeat`, the words from
the repeat point to the end of the waveform it lies in, and written back pointing at the
repeat point the device wrote first for exactly those words.

Variants are the alternatives a command plays in turn. A protocol with a toggle bit (RC5,
RC6) has one per toggle state, in the order the firmware plays them: the Xbox 360's
PowerOff press is `800ff429` then `800f7429`, identical but for RC6's toggle bit. The
firmware does no toggling of its own. Other protocols have one variant. In the two
configurations examined, all 518 + 428 sequences follow this table exactly.

## Building

A build for the 1100 (`"playback": "device-sequence"` in its profile) gives every
command a press and a hold sequence and numbers them as Logitech does: a device with
`n` commands has its presses at `0..n-1` and its holds at `n..2n-1`, in command order;
`DeviceIndex` is the device's position in the configuration.

- A command imported from an 1100 keeps the sequences it was read from, unchanged.
- Anything else is rendered from its signal (`ssir_sequence.for_signal`): one variant
  per toggle state, until the protocol's state comes back round; a press is the device's
  `PressPreSilence` and one frame; a hold is its `HoldPreSilence` and one frame, then the
  frame repeated while held, where the repeat point is. The carrier descriptor's on-time
  is half its period, as in every descriptor seen.

The table is laid out as Logitech's are - each sequence's waveforms, its carrier
descriptors, its record; then the device tables; the root last - and a waveform
identical to one already written is pointed at rather than written again. Rebuilt this
way, both configurations examined reproduce their `SsIr.bin` byte for byte.

The rest of the configuration differs from the 900's only where the 1100 does: each
device has `<ControllerId>0</ControllerId>` and its Properties before its Presentation;
the action lists go inside `UserConfiguration.xml`, after the activities; there is no
`ActionLists.xml`, `IrProto.bin` or RF map. An activity's touchscreen pages (Transport,
Numbers, GameController, Discs, and buttons pinned to SideBar places) are kept page by
page.
