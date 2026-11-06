# The image: address space, sections and layout

## Identity and address space

The donor envelopes declare:

| Field | Value |
| --- | --- |
| architecture (`PROTOCOL`) | 12 |
| skin | 54 |
| flash | `0x1F:0xC8` |
| board | `0.5.0` |
| software type | 0 |

Firmware version is not an EZHex intended-identity field. Afterglow therefore validates the native
structure rather than restricting Harmony One support to the one archived firmware version.

Pointers inside the payload are absolute addresses based at `0x040000`. Integer fields described
here are little-endian.

## Validated outer structure

| Offset | Shape | Meaning |
| ---: | --- | --- |
| `0x00` | `GSPM` | arch-12 configuration cookie |
| `0x04` | `u32` | absolute address of the final `PTYY` marker |
| `0x08` | `u32` | `0x1600` in every donor |
| `0x0c` | 20 × `u32` | master section index; section 8 is absent |
| `0x63` | `LWJL7` | Harmony One button/function-map marker |
| end − 6 | 2 bytes | native two-lane XOR checksum |
| end − 4 | `PTYY` | final marker addressed by the end vector |

The 19 present master-index pointers are unique and point before the checksum. They are ascending
in every donor, but this is an observed layout rather than a validity rule: the readers accept
them in any order. The end
vector points at the final marker and no donor carries bytes after it.

The native checksum starts with lanes `0x21` and `0x43`, then XORs complete byte pairs from the
start of the payload up to—but excluding—the stored checksum. If the covered length is odd, the
last unpaired byte is ignored. Pairing it with the first stored checksum byte is incorrect and was
the cause of RE-HARMONY's former odd-length rejections.

Payloads must be smaller than `0x390000` bytes. At that size a configuration beginning at
`0x040000` reaches the normal application's backup copy at `0x3d0000`; libconcord's erase-sector
walk also ceases to be safely bounded above `0x3b0000`.

## Absolute pointers and objects

Sections 9 (key registers), 10 (contexts and objects) and 11 (the object table) are reached
through absolute pointers: section 11's entries point into section 10, and section-6 slot records
point into section 9. Every such pointer is found through owned structures - the 20-slot master
index, the counted section-11 object table and the complete counted section-6
screen/trailer/slot chain - never by scanning for aligned three-byte values, because
address-sized coincidences are common in waveform and bitmap data. The two broader donors hold
843 and 1,626 of them: 214/440 into section 9, 628/1,185 into section 10, and one into section 11.

An image is closed by the end vector at offset 4, the two checksum lanes over every whole pair
before them, and `PTYY` (`gspm.seal`).

The measured object and index primitives carry no fixed donor counts. A command button uses a
seven-byte command/device object followed by a seven-byte indirection object, allocated in that
B/A order. Device IDs are `(device index << 8) | 1`, and command IDs are the device index and the
command ordinal. Command pages use the observed physical layout order `b2 b3 b0 b1 b4 b5`.
Section 5 is a one-byte device count and absolute sub-table pointers; each sub-table has a zero
byte, a `u16` command count, and absolute pointers to command-record byte `+11`. The opcode-`75`
IR object kind a build writes is `0x0fca`.

The inventory also bounds two native structures without assigning portable meaning to them:

- section 11 begins with a `u16` count followed by that many absolute `u24` object pointers;
- an object starts with an atom count; each atom is an operand `u16` and opcode `u8`;
- a native command record is 25 bytes containing carrier period and half-period in nanoseconds, a
  self-pointer, press and optional hold/release waveform pointers, and fixed framing bytes;
- a press-waveform target begins with the little-endian word `0x7fff`, the split leading space
  used by the remote's IR representation; a hold waveform omits that lead-in and begins with a
  carrier-gated mark.

Object-table order is object identity, not an address sort requirement. Donor tables happen to be
ascending, but nothing requires it, so readers require unique, bounded, non-overlapping object
bodies while accepting non-monotonic pointers.

## Where a build starts

A build should start from the remote's own platform layer and generate everything else from the
project, so a new configuration is never a copy of an old one. What that platform layer is, and
where it comes from, is a property of the architecture rather than a choice.

Four independent Harmony One images agree on almost nothing. Their glyph repertoires are 72, 73, 77
and 79; their fonts, chrome strings, background bitmaps, button frames, page selectors and prologue
atoms all differ; even the seven base contexts differ in content, and one image places them at
different addresses. Between any two, 7 to 19 per cent of bytes match at the same offset.

That is not evidence that nothing can be shipped. It is evidence of how these images were made. The
producer had an asset library and emitted a subset of it into every configuration - which is also
why each font carries exactly the glyphs its own labels needed, why nothing sits at the same
address twice, and why half the object table is emitted and never referenced. A remote fresh out of
its box had no previous configuration either, and it still got a first one.

So the platform layer here is assets, not calibration, and the assets do not have to be the
producer's. A glyph is a width byte followed by runs - `80` closes a row, a high-bit run skips that
many transparent pixels, a low-bit run carries that many big-endian RGB565 pixels, `00` closes the
glyph - and a mode-0 bitmap is a four-byte header followed by raw RGB565. Both are written here as
the exact inverse of the readers, and the readers accept what they produce. The glyph repertoire
stops being a constraint at the same moment: 72, 73, 77 and 79 matter only for reading text
somebody else wrote, and an image whose font and text are both authored here chooses its own codes.

A Harmony One scaffold is therefore synthesisable, with no vendor artwork in it, and every section
now has a way of being produced.

Sections 1, 2, 17 and 18 are byte-identical in all four images - 19 bytes together - and are
carried. Section 3 is two markers, `dfad` and `bfef000000`, around seven bytes that read as a
timestamp: second, minute, hour and day all in range, months 7, 11, 7 and 4, and years 23, 24, 15
and 26, matching when those backups were taken. One of the seven is unexplained; it is 3, 6, 0 and
3 where the weekdays are Saturday, Wednesday, Wednesday and Sunday, so two identical weekdays carry
different values and it is not a day of the week.

Section 4 holds every command again, grouped by device, and section 5's sub-tables are its
device runs rather than copies of them
([commands.md](commands.md#section-5-points-into-section-4)). It opens with 126
bytes identical in all four - two `u24` headers and thirty `{u24 key, u8 value}` records mapping
keys 10 to 39 onto 1 to 29 and 0 - and then lists every command record again, grouped by device:
a `u16` count and that many `u24` pointers to the record plus eleven, each run after the first
introduced by a zero byte. The grouping matched section 5's exactly in all four images, and the
writer reproduces all four sections byte for byte.

Sections 13, 15 and 16 are counted tables of `u24` pointers, the same shape as every other index
here. They address drawing programs that no screen reaches - section 16 holds exactly 11 in every
image measured - so they are structures rather than opaque data, and the drawing encoder can write
what they point at.

What is left is not a format gap but a semantic one: the activity engine in sections 10 and 14 has
no portable model, so a generated configuration could carry devices before it could carry
activities.

## Section 9 opens with the list that starts the image

Section 9 is not only key registers. It opens with one ordinary action list of its own,
`u8 count; {u16 operand; u8 opcode}[count]`, and the page registers follow it. On the Harmony
One the list is a single call, `01 xx xx 7f`: object 0 in the factory image (`Region_3.EZHex`)
and object `0xEE` in all four household images (both donors and both of Kate's). Danny Bloe's
reading (`harmony-explorations`, config-format "Base slot 8", findings sections 83 and 286) has
the firmware use this list as a table of entry points it indexes and queues, and on the 650 it is
what starts the introduction tour after a reload.

The factory routine is three objects:

```
obj 0  (FE00 1F) (0 7E) (F064 3F) (3 7F)     push context 0, enter mode 0, ?, call 3
obj 3  (FB01 1F) (4 7F)                      byte register = 1, call 4
obj 4  (0010 71) (1C 7E)                     if variable 0x10 matches, enter mode 28
```

Mode 0 there is "Go to Website to update settings" and mode 28 is "USB CONNECTED"; variable
`0x10` is the USB flag (section 14 property 16, `(0, 1)`). The household routine is 86 objects
that also initialise the configuration's own state variables, but it ends with the same USB
check: `FB01`, compare `0x10`, enter mode 1, which is the platform's "USB Connected" screen.
Band `0xFE` of opcode `0x1F` pushes a section-10 context onto the key stack, and `FD` stands
for the current mode.

**Every probe that failed to boot lacked this list**, B to L included: the firmware read their
first page register as it (M read `[0x00 0x99B1]`). A, the donor control, has it and boots.
B also had other faults, so this is a strong candidate rather than a proven cause. A generated
image now writes the factory's shape: push its context and the current mode, enter the first
screen it owns (the one every OK button opens), carry `F064 3F` as the factory has it, and
show the platform's USB screen when variable `0x10` is set.

## Section 13 is the timer table

`u8 count`, then a `u24` pointer per timer, each a 7-byte record: `u8 flags` (1 in every donor),
a `u24` duration, and the instruction it runs when it expires (`u16 operand, u8 opcode`).
Opcode `0x1F` band `EB` starts timer `n` and band `EA` stops it; there are four running slots.
Read on the Harmony 800's firmware ([harmony-800-firmware.md](harmony-800-firmware.md)) and
borne out by every One donor, 30 to 32 timers each. Upstairs' timer 3 is "after 4, call object 0x1023", whose atoms redraw status overlays 3
and 0 and start timer 3 again: the status bar's refresh. Every platform screen starts timer 3
when it is entered and stops it when it is left, and two platform objects use timers 0 and 9.

The factory image's section 13 is empty, and generated images copied that - but they also
carry the platform screens' handlers, which the factory's screens do not have. So every
generated mode started a timer past the end of an empty table, reading whatever followed as
its record. The platform model now carries the timers its handlers name, with their actions,
and a generated section 13 holds those three, renumbered.

## Laying out a whole image

Laying out every structure afresh, rather than reading one, settled a few things about the format.

Section 9 must hold every key register, and no donor shares a register between slots - 213 and
439 slots to as many registers. A slot that binds no key still has a register, and 50 and 62 of
them are empty, so a zero-entry register (`00 00`) is a shape the format uses rather than a
mistake. Nothing lies between the registers either - a single pad zero would read as a wide
header - so the section is placed whole and any 64 KiB window padding falls before it.

A command record's five opening bytes are not derived from a flag: the donors open records with
0, 1, 4, 5, 6 and 7, and one opens `2f 81`. A screen trailer's header is another key register,
holding the physical buttons that screen answers - four to six rows usually, and the whole
55-button vocabulary the `LWJL` marker counts in a few - so the 39-row limit was a rule for
recognising a page while scanning section 9, never a rule of the format; the count is a byte, so
the limit is 255. Pictures are the one structure placed without the 64 KiB window rule: 15 to 19
of them cross a boundary in every image and 7 to 9 are larger than the window itself, a 176x220
backdrop stored whole being 77,445 bytes. Whatever that rule protects, it is not pixel data.
