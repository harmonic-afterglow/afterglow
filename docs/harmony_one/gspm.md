# Harmony One GSPM configuration

Harmony One configuration payloads are indexed binary images beginning `GSPM`. They are carried
inside the same XML-header EZHex envelope as other direct Harmony remotes, but they are not ZIP
files and do not share the Harmony 900 configuration semantics.

The observations below agree across four independent Harmony One donor configurations. They are
also consistent with the arch-12 configuration base and cookie in Concordance and with the remote
validator analysis performed by RE-HARMONY.

## The factory configuration in firmware

Harmony One firmware `54.2.5` ships six regions, and `Region_3.EZHex` is a raw `GSPM` image of
8,902 bytes: the configuration a remote leaves the factory with. It declares no devices and no
commands, 30 screens and one section-10 context. Reading it corrected three things that four
household images had agreed on only by coincidence.

**The base address is not a format constant.** It is where the image is mapped in flash. Household
configurations sit at `0x040000`; this one sits at `0x2000`, and every pointer in it is relative to
that. The end vector, the checksum and all nineteen sections resolve once the right base is used.

**The marker is `LWJL`, not `LWJL7`.** The byte after it is the image's button count, which is 55
in every household configuration - hence the apparent `7` - and 2 here.

**Section 4's leading table is generated, not constant.** It is a `u24` first key, the `u24` count
30, then thirty `{u24 key, u8 value}` records whose keys run up from that first key and whose
values run 1 to 30, cut to 125 bytes. Household configurations start their keys at 10 and this one
starts at 0. It also settled the shape of what follows: every device run opens with a zero byte,
the first included, which is why a configuration with no devices is the key table alone. The writer
now reproduces section 4 byte for byte in all five images.

## What the factory configuration draws

Its 30 screens draw text and nothing else - `call`, `attribute`, `text`, `inline_text`, `end`, no
bitmaps at all - and every one of its 9 pointer-text targets resolves inside the image. The whole
platform layer of a virgin remote is 8 KB: one 14-pixel font of 46 glyphs and 56 strings. So the
button frames and chrome bitmaps in a household configuration are produced per configuration, not
resident in firmware.

Its font settles the subsetting rule. The 46 glyphs are exactly the 46 distinct characters its
messages need - `Go to Website`, `to update settings`, `FLASH Memory Erase`, `Battery
Trickle\Charge`, `Invalid Configuration` and the rest - and no others; there is not a single digit,
because no message contains one. The codes run in first-use order across those strings, offset by
two, with `H` and `y` occupying codes 1 and 2 before anything this configuration draws. Every
household layout begins `H`, `y` as well, so a 2008 firmware corroborates tables derived from
images made between 2015 and 2026.

Two font-record headers are therefore established. Household images count their glyphs in a
little-endian `u16` after the height; this one counts in the byte after that, which is what makes
its 46 pointers land exactly on the start of section 7. Neither reading is applied blind: the count
is the one whose whole index resolves, and a font where neither does is refused.

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

## Current ownership

Afterglow validates an image, indexes what it can prove of it - section-5 command ownership,
command objects, press/hold/release waveform records, screen and key ownership, drawing programs,
section-7 fonts, section-19 touch geometry, device-menu rows, activity contexts and state
transitions - and imports the portable part. Every unmodelled native byte is preserved unchanged
alongside the project. A build never starts from that image: it generates the whole configuration
from the project ("Generating a configuration from a project"). Earlier versions edited the
imported image in place instead - relocating sections, cloning screens, patching pointers; that
path was removed once generation covered everything it did, and the findings it produced are kept
below as format facts.

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

## IR waveform representation

The IR player consumes little-endian `u16` words. Bit 15 selects a carrier-gated mark; bits 0–14
are a duration in microseconds. A zero bit 15 is a space. Adjacent source atoms of the same kind
are merged before encoding, which is necessary for biphase protocols.

Spaces longer than `0x7fff` microseconds occupy multiple words. When the remainder would be less
than half a word, the native producer redistributes the last full word and remainder into two
near-equal words. This rule reproduces the observed 50, 100, 300, and 500 ms command lead-ins and
long inter-frame gaps. Marks longer than the 15-bit duration field have not been observed and are
not truncated.

A press waveform begins with a lead-in space; 50 ms is the measured majority default. It ends in
the protocol's final gap followed by a separate 1 microsecond space. A hold waveform has no
lead-in and contains one hold-phase transmission followed by the same short terminator. Both
then end with a zero `u16`: every press and hold waveform in every donor ends `... 1 0`. Without
the zero a reader runs on past the `1` into whatever block or record follows, so a generated
waveform carries its own.

A release waveform uses a distinct representation. It begins directly with a mark, ends with a
mark, and is followed by a literal zero `u16` sentinel. It has no press lead-in, final protocol
gap, or 1 microsecond close word. This is the form stored in the third command-record pointer.

Portable carrier protocols can therefore be rendered into separate press, hold, and release
waveforms without knowing their protocol family. The command record stores the carrier period in
nanoseconds, truncated from `1,000,000,000 / Hz`, and half that integer period. Portable
waveforms with intro/repeat sections map to the two waveform pointers in the same way.

This mapping does not yet cover sender-owned state such as RC5/RC6 toggle bits or unmodulated
signals. Those cases remain rejected until the corresponding native lifecycle mechanism is
evidenced. Lowering also does not assign record addresses, command IDs, or object references;
the generator places the records and numbers them.

## Section 5 command ownership

Master-index section 5 is the firmware's authoritative two-level command index. It begins with a
one-byte device count and one absolute `u24` pointer per device. Each device sub-table begins with
`00`, a little-endian `u16` command count, and one absolute `u24` pointer per command. A command
pointer targets byte `+11` of its record; subtracting 11 reaches the carrier fields and waveform
table. The device ordinal is the high byte of the command ID and the command ordinal is its low
byte.

The byte at record `+15` is `1` or `2` in the current donors; its meaning is not yet assigned.
Three pointer-sized slots follow at `+16`, `+19`, and `+22`. The first always points to a press
waveform. The second is optional and points to the independently established hold waveform. The
third was zero throughout RE-HARMONY's original corpus but is populated on 230 commands in two
broader donors. It is the release waveform pointer. All 120 affected commands in one donor share
one target, all 110 in the other share one target, and the two targets are byte-identical.

The target exactly matches the `Finish` segment generated by Logitech's archived `Microsoft 36
Bit` definition: 36 kHz carrier, a 2795/270/303 microsecond header, 36 Manchester bits using
303/310 microsecond cells, and a zero finish payload. The command-specific first frames have the
same duration and word count; only paired Manchester cells for nonzero key data differ. Linux's
MCIR-2 keyboard decoder independently treats a zero keyboard scancode as releasing all keys. The
agreement between two native images, Logitech's protocol definition, and the receiver-side Linux
implementation establishes lifecycle meaning without relying on a guessed opcode. Bytes preceding
the carrier vary between donors and are preserved without being treated as flags.

An exact command object in section 11 has two atoms: `{command_id, 0x7d}` followed by
`{device_id, 0x7c}`. Every section-5 command in all four donors has at least one such object.
Some commands have multiple objects and more than one low-byte variant of the runtime device ID;
the high byte still agrees with the section-5 device ordinal. Consequently section 5 owns command
grouping, while all observed object indexes and device IDs are retained as native evidence.

## Section 6 screen key ownership

Master-index section 6 begins with a little-endian `u16` screen count, one zero reserved byte, and
one absolute `u24` trailer pointer per screen. A trailer contains a flag byte, an absolute header
pointer, a little-endian `u16` slot count, and that many absolute slot pointers. Each seven-byte
slot contains a template byte plus absolute pointers to its key register and drawing program.

A key register begins with a one-byte count followed by entries of `{key code u8, object index u16,
class u8}`. A leading zero is not a count of zero: it selects the wide form, `00 count {flags, tag,
u16 operand, opcode}`, whose count is the next byte. An empty register is therefore `00 00`, as
every empty list in the donors is; a lone `00` makes the reader take the following byte as a
count. Class `0x7f` selects a section-11 object. A command binding resolves either directly or
through one further `0x7f` object reference to a `0x7d` command ID and optional `0x7c` runtime
device ID. The command ID must exist in section 5, and any device ID must have the same high byte.
The importer retains screen ordinal, slot, template, raw key code, object index, key-register
offset, drawing-program offset, and any page transition as native evidence on that command.

### The screen index

Section 6's own entries are absolute, and the trailers, slots, key registers and drawing programs
it addresses live below the first master-indexed section in both donors, not inside section 6's
computed range. A screen's ordinal is its position in the index, which `0x7e` navigation objects
name, so an ordinal is never renumbered while anything can still name it.

Afterglow emits the index, trailer and slot records from the same fields it parses: re-emitting
every donor screen reproduces the original bytes exactly - 157 and 339 trailers, 213 and 439
slots, and both screen indexes. The trailer flag is `00` on most screens and `01` on nine in each
donor.

### How a command screen is drawn

A command-screen slot's program is a prologue `call`, then one button frame bitmap per command,
one font attribute, the label instructions that name each frame, and finally a selector and the
chrome that draws the bottom softkey and page indicator.

The layout was measured rather than assumed. Each button's own frame bitmap gives its
position and width, and the label is centred on that frame: `x = floor((2*frame x + frame width -
label width) / 2)`, where the label width is the sum of the drawn widths of its glyphs in the font
the slot's attribute selects. That rule reproduces the position of every button label on both
broader donors, 527 of 527. Label lines sit 11 pixels apart, centred 20 pixels below the frame's
top edge and rounded half up, which reproduces every one- two- and three-line label, 456 of 456.
A label wider than its frame is refused rather than drawn across it.

Key registers do not store their entries in reading order, so which label belongs to which key is
established through section-19 geometry: content zones sorted by descending Y then ascending X pair
one for one with the frames in drawing order. Across all 80 clonable donor slots this yields a
single consistent mapping, and the two donors agree on it: `b0`-`b5` map to `(6,38)`, `(89,38)`,
`(6,92)`, `(89,92)`, `(6,146)`, `(89,146)`.

Drawing each donor slot again with the labels it already draws reproduces its meaning exactly -
the same instructions, positions and text - in all 80 cases, and its bytes exactly in the 29 slots
whose labels are all inline text. The rest differ only because the native producer drew some
labels through a shared string pointer where inline text is written here.

A screen of several pages has one slot per page, all calling one prologue that states the total.
Both donors use slots of several widths - 6, 4 and 2 downstairs, 6, 5, 3 and 2 upstairs. A
prologue draws its screen's title at (6,4), twice in every prologue that has one and always
agreeing - 122 of 122 and 298 of 298. A screen either numbers every page or none.

A font indexes the repertoire sparsely: every font in both donors declares the full repertoire slot
count and leaves a null pointer for each glyph its own labels never needed. The downstairs menu font
draws 36 characters and the upstairs one 48, while their button fonts draw 66 and 70. Knowing a
character's repertoire code is therefore not enough to draw it, and a label is refused when the font
it would be drawn in has no glyph for one of its characters.

### Fonts of one typeface

Two fonts are the same typeface when they declare the same height and every code they both carry
decodes to an identical shape. Both donors hold 18 fonts in four height families, and the
height-14 family is one face of eight to ten fonts whose union is the whole repertoire; the
height-15 menu-row family holds only two fonts of its face. A generated image does not depend on
this: each of its fonts carries every character its own text draws.

### How a device-menu row is drawn

Menu rows are laid out differently from command-screen buttons. A row label is left-aligned at
x=63 rather than centred, and its lines sit 12 pixels apart centred on the row band's centre;
both donors draw one- and two-line rows only, so a third line is refused rather than extrapolated.
Every one of the 102 replica rows re-renders to the same meaning, and the 11 rows drawn entirely
with inline text re-render byte for byte.

All 102 row objects have the same shape: three atoms, exactly one `0x7e` and no `0x7f` jump. Each
menu slot's key register lives in section 9.

The donors replicate their device menu - four occurrences downstairs, ten upstairs - and the
replicas are only recognised as one menu because they agree. A page's rows are the equally sized
content zones of its touch template; the bottom softkey shares the template but is a different
size, and one replica in each donor binds it in the navigation class like a row, so binding class
alone cannot tell them apart.

### Paging

A paged screen states its total in the prologue every one of its slots calls, at (23,18) followed
by the word `pages` at (35,18), and numbers each slot at (13,18) followed by `/` at (18,18). A
single-slot screen draws neither. Across both donors the slot number is the slot's own index plus
one in all 152 numbered slots, the prologue total equals the screen's slot count in all 40 screens
that state one, and the prologue and its slots always agree on the font attribute - which varies
by screen, so it is read from the screen rather than fixed. No prologue is shared between screens
in either donor: 157 of 157 and 339 of 339 serve exactly one, so a screen's total can be advanced
without touching another screen.

### Row bands

Both donors draw every one of their 102 rows with its frames at the same offsets from its band
centre, and every page in band order.

The two broader donors contain 339/157 screens, 439/213 slots, and 1,281/673 key-register entries.
The indexed walk resolves 443/199 unambiguous command bindings and 624/363 page bindings. It finds
no command outside section 5. Entries in other classes, objects with neither a command nor page,
and 3/6 genuinely multi-command actions are counted separately. Raw key codes are not yet mapped
to portable button names: doing so requires proving screen context and physical/touch vocabulary,
not merely observing that a byte occurs beside a command.

## Drawing programs, fonts, and touch geometry

A screen slot's drawing-program pointer addresses bytecode for the native display interpreter.
The bounded reader recognizes end (`00`), rectangle (`01`), bitmap (`02`), pointer text (`04`),
inline text (`05`), font attribute (`10`), queued atom (`11`), switch (`12`), jump (`14`), call
(`16`), and return (`17`). It does not execute calls or selectors. An unknown opcode terminates
that program's inventory and is reported rather than assigned a length.

Section 7 begins with a `u16` font count and absolute `u24` pointers. Each font has a one-byte
height, a `u16` glyph-slot count, and nullable absolute glyph pointers. A glyph begins with its
width followed by row-oriented run data: `80` closes a row, high-bit runs skip transparent pixels,
low-bit runs carry that many big-endian RGB565 pixels, and `00` closes the glyph. Afterglow checks
the declared and decoded widths and records a palette-independent shape fingerprint. The numeric
code cipher is selected from the image's declared repertoire rather than frozen globally. Four
layouts are currently established: RE-Harmony's 71-code factory layout and independent 72-, 77-,
and 79-code images. Their first 60 codes agree, but their suffixes are permutations rather than
extensions; for example `V` is `3d` in the 72/77 layouts and `42` in the 79 layout. Unknown
repertoire sizes remain undecoded instead of borrowing the closest table.

Section 19 begins with a template count and absolute template pointers. A template is a one-byte
zone count and absolute zone pointers. Each 12-byte zone stores four `u16` geometry fields, a tag,
and an absolute self-pointer at `+9`; the self-pointer must resolve to that zone. The key code used
by a slot is `tag | 0x80`. Tags `2e` and `2f` are paging strips. The touch Y axis is inverted, so
content zones sort into screen reading order by descending Y and then ascending X.

Device-menu rows are established by three independent relationships: text drawn in the measured
row band, a touch-zone key entry, and its section-11 object opening exactly one screen with opcode
`7e`. The target screen's section-5 command bindings identify the IR device when there is exactly
one. Multiple text lines within one row are retained in vertical order. Replicas must contain the
same raw glyph lines, target screens, and device ownership, but their visible row order may differ.
When the section-7 repertoire is established, the lines also provide the portable device label;
the raw glyph bytes remain alongside it as native evidence.

This broader rule finds four and ten mutually agreeing contextual replicas in the downstairs and
upstairs donors respectively. RE-HARMONY's narrower pointer-text-only search found three and nine;
the additional replica uses inline text. The upstairs set contains six section-5-backed devices
and three native-only rows whose target screens contain no indexed IR commands. Those rows are
retained separately instead of being forced into the portable IR device list.

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
device runs rather than copies of them (see below). It opens with 126
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

## The pictures a configuration draws

Bitmaps are most of a configuration: 1.1 to 1.5 MB of the 1.3 to 1.8 MB in the four images
measured, around 85 per cent. Every backdrop, frame, softkey and icon the remote shows is stored
in the configuration rather than in firmware, which is why a generated one has to supply them.

Both encodings open with the same five-byte header: the mode, then width and height as
little-endian `u16`s. Pixels are RGB565 and big-endian in both. Mode 0 stores every pixel of
every row after the header. Mode 1 runs them - a byte with the high bit set leaves that many
pixels untouched, a byte without it introduces that many stored pixels, `80` closes a row and
`00` closes the picture - which is the same run encoding, and the same byte order, that a font
glyph uses. The last row carries no separator, because the picture's terminator closes it. There is no alpha channel: a run simply declines to write, and whatever was
on the screen shows through.

The byte order is measurable from the images: taking the mean difference between horizontally
neighbouring pixels, run-encoded pictures average 33 read little-endian against 14 to 15 read
big-endian, and a 163x83 panel stored whole reads 98 little-endian against 47 big-endian. This
section used to say the two encodings disagree, stored-whole pictures being little-endian. That
was the four-byte header below: read a byte early, little-endian takes each pixel's high byte
correctly and its low byte from the pixel before, which looks nearly right.

The encoder is the reader's exact inverse. Every picture the four donors draw rebuilds its own
bytes: 294 pictures, 268 stored whole and 26 run-encoded.

That round trip once hid a wrong header. Mode 0 was read with four bytes - mode, width, a zero,
height - so the height's high byte was taken as part of the first pixel and every stored pixel
was read a byte out. Writing it back the same way rebuilt the donor's bytes all but the last, so
the check passed while every generated stored-whole picture came out one byte short, its last
byte read from whatever followed: the 17 one-byte overlaps Danny Bloe's coverage reported in the
upstairs round trip. Donor pictures sit exactly `5 + 2 * width * height` apart, and the
scaffold's 33 stored-whole pictures were re-extracted with the corrected reader.

The same eight shapes appear in all four images, at the same places:

| size | per image | drawn at | what it is |
| --- | --- | --- | --- |
| 176x220 | 7-9 | (0,0) | full-screen backdrops |
| 81x50 | 18-25 | the six-button grid | command button frames |
| 164x50 | 7-9 | (6,38) (6,92) (6,146) | full-width row frames |
| 51x48 | 5-13 | (11,39) (11,93) (11,147) | menu row icons |
| 62x42 | 3-17 | (57,67) | centred panel |
| 88x22 | up to 6 | (0,198) (88,198) | softkey backgrounds |
| 22x18 | 2-6 | (128,0) | small indicator |
| 164x85, 62x33 | 1-2 | (3,118), (57,95) | larger panels |

## What a configuration generated from nothing contains

`Region_3.EZHex` inside firmware 54.2.5 is the configuration a Harmony One ships with:
8,902 bytes, and by definition what the vendor produced with no previous configuration to
work from. It maps at `0x2000` rather than `0x040000`, and it settles what a generated
image is actually obliged to contain.

| section | in the factory image |
| --- | --- |
| 0 | 7 bytes: a `FEED` header and a `BEEF` terminator, no records |
| 4 | the 125-byte head alone, no device runs |
| 5 | one byte, `00`: no devices |
| 6 | 5,815 bytes: 30 screens, all the platform ones |
| 7 | one font |
| 10 | one context |
| 11 | five objects |
| 12 | `00 00`: no status overlays at all |
| 13 | one byte, `00`: no timers (see "Section 13 is the timer table") |
| 14 | 65 bytes |
| 15 | `00`, then its 151-byte tail |
| 16 | 11 pointers, into section 15's tail |
| 19 | one touch template |

The two sections nothing could be generated for are answered by their counts being zero,
so their contents never have to be understood. Section 16's pointers land inside section
15's own tail at the same eleven offsets here as in every donor, and that tail differs
from the donors' in exactly three of its 151 bytes - it is a platform table with three
parameters, not a constant.

## Section 13 is the timer table

`u8 count`, then a `u24` pointer per timer, each a 7-byte record: `u8 flags` (1 in every donor),
a `u24` duration, and the instruction it runs when it expires (`u16 operand, u8 opcode`).
Opcode `0x1F` band `EB` starts timer `n` and band `EA` stops it; there are four running slots.
Read on the Harmony 800's firmware (below) and borne out by every One donor, 30 to 32 timers
each. Upstairs' timer 3 is "after 4, call object 0x1023", whose atoms redraw status overlays 3
and 0 and start timer 3 again: the status bar's refresh. Every platform screen starts timer 3
when it is entered and stops it when it is left, and two platform objects use timers 0 and 9.

The factory image's section 13 is empty, and generated images copied that - but they also
carry the platform screens' handlers, which the factory's screens do not have. So every
generated mode started a timer past the end of an empty table, reading whatever followed as
its record. The platform model now carries the timers its handlers name, with their actions,
and a generated section 13 holds those three, renumbered.

## What the Harmony 800's firmware says about the format

The Harmony 800 (STM32F102, firmware 0.7.1) reads `GSGD`, a sibling of this format, and its
code is plain ARM, so the reader can be read rather than inferred. Its findings are hints for
the One until a One donor bears them out; each one below has been checked against the donors.

- **Boot.** Once a configuration's checksum passes, `main()` runs section 9's leading list
  with index 1: if its count is at least 1, its first instruction is queued, and nothing else
  starts the interface. Danny Bloe read the same call with a literal 1 on the Harmony 700.
  Every One image carries `01 xx xx 7f`; every probe that failed to boot read its first page
  register here instead, and with opcode `00` that is an instruction that does nothing.
- **Instructions** are `u16 operand, u8 opcode`, run from a queue. Opcodes from `0x80` write
  variable `opcode & 0x7f`; `7F` runs an object (section 11); `7E` enters a mode; `73` draws a
  section-12 program; `70`/`71` compare a variable with the accumulator or byte register (low
  nibble of the operand's high byte picks the test) and drop the next instruction when it
  fails; `07` with `FD`/`FC` pushes and pops the current mode. The 800's handler reads bit 7
  of the high byte as inverting the test. The One's configurations do not use it that way:
  upstairs chooses the Remote Assistant's first note with `== 0` *with* bit 7 and skips it
  with `== 3` *without*, shows its welcome on `<= 1` with bit 7, and Kāt's waits for a smart
  TV's apps on `OnlinePower == 0` with bit 7 before marking them up - each the obvious intent
  only if the test runs the next instruction when it holds. A build copies bit 7 only where
  a donor has it, and new logic uses plain tests.
  `1F` bands: `FF` select the running context, `FE`/`FD` push and pop the key stack, `FB` load
  the byte register, `FA`/`F9`/`F8` add, multiply, divide, `EB`/`EA` start and stop a timer.
  `3F` bands: `F0` sets a timer length (`F064` = 100, as the factory and both donors have it),
  `B0` runs entry n of section 9's leading list.
- **Entering a mode** runs the old mode's tag 7 (page list, then mode list), then the new
  mode's tag 6 from its own list, posts event `2E`, and draws the page unless the entry flag
  has bit 0 set. Nothing computes a list's end. A USB change posts `2D`, then `2B` or `2C`.
- **Drawing.** `16` call saves a single return address, so a fragment cannot call further;
  any opcode the VM does not know ends the program.
- **Lists differ.** The 800's wide list header is `00 00 count` and its narrow entries carry a
  `u16` tag; the One's are `00 count` and a `u8` key. All 164 empty One registers in three
  donors are exactly `00 00`, so the One reader stops there.

`afterglow-research/one-tools/boot_trace.py` follows a One image's boot by these rules.

## Section 14, the activity engine

Section 14 is a counted index - `u16` count, the count less one, a one, the count less one
again, then a pointer per record - over records that are state machines. A record is a
`u16` initial value, a `u16` limit, a `u16` transition count and a padding byte, then that
many eight-byte transitions of `{u8 flags, u16 from, u16 to, u16 operand, u8 category}`.
`0xfffe` appears as `from` throughout and behaves as "whatever the current state is".

Not one field in a record is an address. States are numbers, and a transition's operand is
an index into section 11 rather than a pointer, so a record moves without anything being
repaired: all 45, 48, 51 and 44 records in the four donors re-encode byte for byte from
their fields alone. That is what lets composition model section 14 instead of carrying it,
and a generated image emit whatever records it is given.

An operand whose high byte is `0xf8` or above is not a value but an expression. The
application firmware dispatches on it from 0x23042: `0xfb` loads the low byte into an
accumulator, `0xfa` adds to it, `0xf9` loads through the table pointer, and each of
`0xf8` to `0xff` has its own handler. That is what the `0xf202` and `0xfb01` operands seen
with category `0x1f` are. See `tools/harmony_one_firmware.py`.

The table has three parts. Records 0 to 6 are the real-time clock. Records 7 to 17 are
platform properties, byte-identical in the factory configuration and all four donors -
limits 2, 3, 7, 7, 32, 1, 1, 4, 3, 1, 3, initial values 0, 0, 5, 0, 0, 0, 1, 2, 0, 0, 0,
no transitions - except record 14, which is identical across the donors and differs from
the factory. The last record is a terminator: limit `0xfefd`, initial zero, no
transitions, in every image. What lies between record 17 and the terminator is what a
household configuration adds.

### What a household property is

A household property is one device's discrete state. Its limit is the highest state it
reaches, and each transition names a section-11 object holding the commands that get
there. One donor's record is an input selector, and the objects say so plainly: limit 4,
and five transitions whose objects send a setup command, then the input command as many
times as the state number, then a confirm. That is how a device whose input is cycled by a
single button is driven.

Every household property that sends anything sends it to exactly one device - 5, 8, 11 and
5 records across the four donors, and never two devices in one record. The rest send
nothing at all: 21, 21, 21 and 20 properties the remote tracks but cannot drive.

One property counts the activities. Its limit is one less than how many the configuration
has - 2 against 3, 8 against 9, 10 against 11, 1 against 2 - and its initial value is the
activity that was running when the configuration was saved: 2, 8, 9 and 1, each a valid
index. Where a configuration has few activities that limit is shared with the boolean
properties, so a non-zero initial is what singles it out, which means an image saved in
activity zero cannot be told from one naming no activity at all.

An earlier hypothesis was tested and refused. The records with a limit of 1 number 17, 20,
21 and 19 against 3, 6, 7 and 4 devices - devices plus fourteen in three of the four -
which looked like a power flag per device. It is not: none of them drives a device. The
first attempt to check this also looked only at transitions whose category is `7f` and
read the device out of the atom directly, missing both the transitions whose category is
zero - whose operand is always zero, a null action - and the fact that a device is named
in the high byte of a nested object's atom rather than by the atom itself.

### How an activity reaches its commands, and where All Off does not

A context's rows carry hooks by key code: `01` on entering, `02` on leaving, `05` on
refresh. A hook names an object, that object writes `(property, value)` pairs, and each
write is resolved by finding the property's transition whose `to` matches the value and
following its object to the commands it sends. That path is what makes an activity
determined, and it works: 2 of 3, 8 of 9, 10 of 11 and 1 of 2 activities in the four
donors resolve to between 5 and 9 indexed commands across 4 to 6 devices.

The one context per donor that resolves to nothing is All Off, and it is not unresolved.
It writes exactly eight properties in every image, **none of them a property that drives
a device**, and its set is always a subset of what a real activity writes - a real
activity writes those eight and adds the driving ones, 5, 7, 8 and 5 of them.

All Off stores no commands because it does not need to. **Every property that drives a
device has exactly one transition to state zero, and that transition carries a command** -
5, 8, 11 and 5 properties across the four donors, without a single exception - so turning
everything off is driving every property to zero, using the transitions the activities
themselves installed. `all_off` returns those commands: 6, 9, 11 and 5 of them, covering
every device that has a driving property at all.

A property whose limit is 1 and which drives a device is a power toggle, state 1 on and
state 0 off, and most devices have one: 3 of 3, 5 of 6, 7 of 7 and 4 of 4. Where a device
has none its power sits inside a property with more states, which is why counting limit-1
records alone never gave the device count - and why the earlier attempt at that failed. It
counted every limit-1 record, and the silent ones outnumber the driving ones four to one.

The leave hook was checked for it and does not hold it either. Every activity but All Off
carries one, each writing eight properties, and in all four donors not one of those writes
reaches an indexed command. `inspect` follows it anyway rather than reading it and dropping
it, and reports an activity that reaches no command as `state_only` rather than
undetermined, so that determined and state-only together account for every context.

### The clock, and section 3's unexplained byte

Records 0 to 6 have limits 59, 59, 23, 30, 6, 11 and a year, and their initial values are
section 3's timestamp fields: second, minute, hour, day, weekday, month, year. All 35
fields agree across the factory configuration and all four donors.

Those limits settle how the fields count. A day whose limit is 30 counts from zero, and so
does a month whose limit is 11. Read that way the fifth byte of section 3 - the one nothing
had accounted for - is the weekday with Sunday as zero, and every image agrees:

| image | date | weekday | stored |
| --- | --- | --- | --- |
| factory | 2007-10-25 | Thursday | 4 |
| downstairs | 2023-08-23 | Wednesday | 3 |
| upstairs | 2024-12-28 | Saturday | 6 |
| backup-One | 2015-08-02 | Sunday | 0 |
| HarmonyONE | 2026-05-06 | Wednesday | 3 |

Read one-based instead, two of those dates fall on the same weekday and carry different
values, which is exactly why the byte stayed unexplained. `stamp` now derives the weekday
from the date, refuses one that disagrees with it, and takes the day and month from zero -
so it accepts a zeroth day and month, which it used to reject, and refuses month twelve,
which it used to accept and no remote could hold.

## Both fields of a command object are packed

A command object is `02`, a `u16`, `7d`, a `u16`, `7c`, and the second field has been read
here as a device id. It is not one. Both fields carry the device index in their high byte -
1,471 command objects across the four donors agree and none disagrees - and no high byte
ever reaches the image's device count, over 1,502 atoms. The first field's low byte is the
command's ordinal within its device. The second field's low byte is a repeat count: 1 in
1,297 of the atoms measured, the rest 0, 5, 8, 10, 15, 20, 25, 30, 40, 50 and 100, which
is what a device needing a command held rather than tapped would carry.

## Section 12, the status overlays

A picture is reachable only from a `bitmap` instruction, and for a long time the only programs this
backend rooted were the ones a screen slot names. That left 14 to 18 pictures per image apparently
undrawn, almost all of them 20x11. They are not undrawn. They belong to section 12, which no screen
calls, and every one of them is reached once the section-12 table is used as a root set: 14 of 14 in
three images and 18 of 18 in the fourth.

Section 12 opens with overlay programs, and the four kinds are identical in shape in every image
measured, differing only in their order in the table and in how many copies of each an image carries.

| blocks | switches, as (selector, cases, ranges) | draws | at |
| --- | --- | --- | --- |
| 10 | (9, 8, 0) | 8 pictures of 20x11 | (153, 4) |
| 140 | (15,2,1) (9,1,2) (0,60,0) (0,60,0) (9,8,0) | 13 pictures of 20x11 | (153, 4) |
| 4 | (17, 1, 1) | 2 pictures of 22x18 | (128, 0) |
| 95 | (4,7,0) (2,24,0) (1,60,0) (1,60,0) (2,24,0) (1,60,0) | 1 picture of 88x10 | (88, 19) |

A 20x11 icon at (153, 4) is the top right corner of a 176 wide screen, which is the status bar. The
`switch` opcode dispatches on a firmware state rather than on anything the configuration holds:
selector 9 has exactly eight cases, which is a battery level; selector 15 chooses between power
modes; and the two sixty-case switches cycle three icons each, which is why three of the pictures
are pointed at 50, 50 and 20 times.

The order of these entries is not fixed. Two images open the table with the eight-case battery
program and two do not, and one image carries five copies of the 88x10 program and four of the
22x18 one. Whatever selects an overlay, it is not the section-12 ordinal.

After the overlays the table holds five-byte stubs, roughly four per activity plus twelve, then
eight entries of 29 bytes and one of 38. What those do is not established.

Two consequences follow. A generated configuration has to emit section 12 and its pictures, because
the remote draws its own battery and charge state out of the configuration like everything else. And
a coverage or composition pass that roots drawing programs only at screens is measuring the wrong
thing: section 12 is a root set of its own.

## There are no standalone strings

A `text` instruction carries a pointer where `inline_text` carries its glyphs directly, which reads
like a string table. There is no string table. Every text target in the four images - 229, 300, 305
and 194, 1,028 in all - lands exactly on the glyph bytes of an `inline_text` instruction somewhere
in the program graph, with matching content, and not one lands anywhere else. A shared string is
another instruction's inline payload.

That is why a layout has to map those addresses and not only the blocks. Redirecting each pointer to
a freshly placed copy renders the same glyphs, but it gives the image a pool of standalone strings
that no native configuration has, and it duplicates every string that more than one screen draws.
`lay_out` therefore registers each `inline_text`'s glyph address alongside its block's, and
composition places no strings of its own.

## Section 5 points into section 4

Section 4 was described here as a second index of the same commands section 5 reaches. It is not a
second copy. Each of section 5's per-device sub-tables begins exactly where that device's run inside
section 4 begins - all 20 sub-tables across the four images - and the two have the same shape, a
zero byte, a `u16` count and one pointer to record-plus-eleven per command. Section 5's top-level
table is a list of pointers into section 4, so a composed image emits section 4 once and points
section 5 at it.

## A waveform terminator can be a record's first word

Press and hold waveforms end with the word `1`, a space of one microsecond, and then a zero word,
in every waveform in every image. Where a command record begins immediately after one, it begins
at the `1`, four bytes *before* the waveform ends, so the `1 0` terminator and the record's first
four bytes are the same bytes. The record's own self-pointer at plus eleven confirms where it
starts, so both readings are right and the overlap is real.

It is deliberate rather than accidental. Every record that starts on a waveform terminator opens
`01 00 00 00 00` - 220, 400, 388 and 189 of them, without exception - while records that do not
share carry the other prefixes the donors use: 0, 4, 5, 6 and one `2f 81`. The producer overlapped
the two only when the record's flag made those bytes identical anyway. Composition emits them
separately, which costs two bytes per command and is otherwise faithful.

## The first forty screens belong to the firmware

A screen's ordinal is not free. The firmware selects its own screens by index, and the
first forty are its: both household donors draw the same text with the same instruction
shape in all forty, and nothing an owner owns appears before ordinal 40 in one or 44 in
the other.

| ordinals | what they are |
| --- | --- |
| 0, 9 | notices with an OK button: the battery warning, the charging-problem screen with a support URL |
| 1 to 8 | "USB Connected", "Update Successful", "Upgrade Success", "Update in progress", "Learning...", "Firmware upgrade in progress" |
| 10 to 39 | the thirty diagnostics the factory configuration carries as its own screens 0 to 29 |

The factory configuration is those thirty and nothing else - 30 screens with no devices -
which is what makes it the witness for this. They run from "Go to Website to update
settings" through the FLASH memory and ADC calibration failures to "Missing License", and
they include **"Invalid Configuration"** and **"Configuration Corrupted"**: the two screens
the remote would use to say it had rejected the configuration it was given.

So a generated image that starts its own screens at ordinal 0 is not merely missing the
platform's; its first command page stands where the low-battery notice belongs.

These forty are Logitech's own work, delivered rather than dumped. Both donor containers
carry `TRANSFERTYPE Winsock` and post to `members.harmonyremote.com`, hold exactly one
payload member, and match their own declared checksum: they are what the vendor's server
generated and sent to a remote, and the screens are in it. The firmware keeps its own copy
of thirty of them in `Configuration_Static`, which is how a remote with no configuration
at all can still say `Battery Low`.

They are structurally constant but not byte-constant. All forty draw the same text with
the same instruction shape in both donors and their programs occupy the same address range
- `0x00015a` to `0x0012f7` in each - yet only 2 of the 40 programs are byte-identical,
because each one points at pictures and glyph strings that sit elsewhere in each
configuration. So the vendor emitted them from a fixed template and linked them afresh
every time, and carrying them means carrying a model and linking it, not copying bytes.

### How a build carries them

A screen is linked to the rest of an image in two ways. Addresses - to blocks, pictures and
glyph strings - move with layout and the linker repairs them. Indices do not: a program's
`atom` names a section-11 object by number, a section-12 overlay by number, a font by
attribute, and a slot names a section-19 template by number. So the question was what the
forty screens reach through indices, and whether it is theirs.

It mostly is. The 37 objects their programs queue are leaves - `(3, 73) (X, 73)`, "draw the
progress overlay and the status bar" - and the only value in them that differs between
donors is X, which names the status program and differs exactly as far as each donor orders
its overlays. Emitting the overlays in one donor's order carries them unchanged. The two OK
buttons, on screens 0 and 9, lead into the rest of the donor's interface. And each screen's
trailer header - what the physical keys do while it shows - is where the per-owner content
comes in: 204 of their 348 rows bind objects whose chains reach that owner's help flow, and
screens 0, 1 and 9 bind the whole keypad.

So `platform/system-screens.json` holds the forty as a model: 329 blocks whose targets are
names - a block number, a picture role, an object number - with `text` rewritten as
`inline_text`, the 37 status objects, the four overlays, and each screen's header rows by
category. Null bindings are identical in all four donors, 74 of 74, and carried. Category
`1f` bindings carry that donor's constants - only `eb03`/`eb07` on key 6 and `ea03`/`ea07`
on key 7 ever appear - which is coherent because the fonts, pictures and overlay order all
come from the same donor. Object bindings are dropped. The OK buttons open the first screen
the project owns instead, through a navigation object (`structures.navigation_object`).

A build then emits the platform's objects first, the overlays into section 12, the fonts in
attribute order so the programs' attribute numbers mean what they meant, templates 0 to 2
ahead of any page's, and the forty screens at ordinals 0 to 39. Against the donor it was
taken from, all 40 draw the same text with the same instruction shape, and a render of a
generated configuration leaves no pixel undrawn. The thirty diagnostics each draw a
`System Message: N` heading, numbered 0 to 29; screens 2 and 3 draw no text of their own in
any donor either.

Planning this caught a defect in the command pages that preceded it. A page measured its
labels in the button font but set no attribute before drawing them, so it drew in whichever
attribute the previous program left - correct only while that happened to be the font it
had measured with. A page now sets its attribute first, as every donor page does.

Two more things a real configuration has that a generated one does not. The activities
menu carries an `Options` softkey, so there is a settings path. And a quarter of a
household configuration is the help flow: "Is the Amplifier on?" with Yes and No, one
screen per device per activity, behind "Attemping to fix the problem..." - 25 screens of
157 in one donor and 81 of 339 in the other.

## Mode 0's list follows `LWJL`

The byte after `LWJL` counts the entries of **mode 0's own list**, and the entries follow it
directly: `u8` event code, `u16` operand, `u8` instruction. Mode 0 is the "battery level is
low" screen, and the firmware reads the list at that fixed place rather than through a
pointer. Every Harmony One user configuration carries the same 55 entries - 52 key presses
and three mode events (codes `06`, `07`, `2D` at positions 7, 9 and 46) - each calling, with
instruction `0x7F`, the object numbered by its own position. So objects 0 to 54 are mode 0's
handlers; in the user configurations they are three empty atoms, a deliberate swallow, except
46, which draws the status overlays. The safe-mode configuration counts 2.

Generated images used to write the count of 55 and none of the entries, so the firmware read
the first 220 bytes of objects as this list. None of those probes booted (2026-10-04). They
now carry the list byte for byte and number their own objects from 55. Source: Danny Bloe's
`harmony-explorations`, `docs/config-format.md`, "The key table".

## Every mode has an enter and a leave handler

Every mode record on a Harmony One carries exactly one tag 6 entry, run when the mode is
entered, and one tag 7, run when it is left; the firmware's own screens also bind tag 2D,
which draws the status overlays. These are object bindings, and the platform model used to
drop every object binding as part of the per-device help flow - so 6 of a generated image's
41 modes had no enter or leave handler and none of the forty platform screens redrew its
overlays. The extractor now carries a platform screen's 6, 7 and 2D rows with the objects
they reach (one to eight each; tag 30 on screen 9 reaches 48 and stays dropped, as do key
rows), and a screen a build owns gets the platform's enter, leave and redraw. Mode 0's
record is the list after `LWJL` itself, so its table entry points there. Checked with Danny
Bloe's reader (`harmony-explorations`): 0 of 41 generated modes lack either handler, against
0 of 157 and 0 of 339 in the two donors.

## A mode is laid out contiguously

Every mode in every donor is one run of bytes, in this order:

```
[handler list] then per page: [fragment] [page program] [7-byte page record]
then the entry: flag, u24 -> list, u16 page count, u24 per page record
```

The page program opens with a call (`16`) to the fragment that sits right after the list,
and the fragment ends with a return and then an end byte (`17 00`). Upstairs' mode 0 is list
`0x67`, fragment `0x144`, page program `0x15a`, page record `0x186`, entry `0x18d`, and mode
1's list follows at `0x196`. Each of the forty platform screens has a fragment that no other
program calls. Danny Bloe's reader takes a mode's program to be the bytes after its list, so
whether or not the firmware ever computes "list end" itself, nothing else may sit there.

Generated images used to scatter these pieces: lists, page records, entries and programs in
separate runs, with objects 0 to 54 right after mode 0's list. Now each mode is reserved whole
and its programs are written once the pictures they draw have addresses; a program's size
does not depend on its addresses. The objects follow the modes. A mode the image owns gets a
fragment that draws the backdrop, and its page program calls it. Generated mode 0 lands at
exactly the donor's addresses.

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

## Generating a configuration from a project

`generate.skeleton` builds an image without reading one. It lays out the header, every
section and the bodies they point at; the artwork comes from the scaffold and the commands
from a project. Empty it is 517 bytes - one screen, one context, one object, and a count of
zero everywhere the factory image has one. Built from the scaffold with an empty project
it is 421,331 bytes, nearly all of it pictures and the glyphs its own words use.

The layout follows from how a section's range is derived. `section_ranges` ends a section
where the next begins and `_sections` refuses duplicate pointers, so the bodies are placed
first, then the nineteen tables contiguously in ascending order, then the checksum and
`PTYY`. Each section's range then covers its own table and nothing else - and no section
may be empty, because a zero-byte section would share a pointer with its neighbour.

A command's waveforms are placed before its record, because the record points at them, and
its section-0 name follows. Its objects are numbered with all the others and placed after the
modes. Every pulse of a generated command reads back
identical to the project's own; the carrier returns 38,001 Hz for 38,000 because the period
is stored in whole nanoseconds.

### Only the pictures something draws

A generated image places a picture only when a program draws it: a platform block, a menu
page or a command page. Every donor's pictures are all reached, so Logitech's builder evidently
does the same, and the scaffold carries more than any one image needs - fifteen row icons where
three devices draw three, and the menu's artwork where a project has no devices. Placing them
all cost about 250 KB. The upstairs round trip went from 852,654 bytes at 88.9 % coverage to
761,062 at 99.6 %, and the empty, one- and three-device probes from 58-79 % to 99.8 %. What
is left uncovered is 64 KiB window padding and platform blocks no reachable program enters.

### First hardware results, and what they changed (2026-10-09)

W, X and Y boot on a tester's One (MickBim, #test-one): W shows "No devices", X and Y show
their device menus and send without crashing. Q to S, from before the timer and variable
fixes, froze or rebooted when a button was pressed. Two things were left, both fixed here:

- **The clock came late.** Every platform fragment draws the status bar itself, with two
  drawing atoms (opcode `11`, which queues an instruction): `(2, 0x73)` draws overlay 2 and
  an object of `(3, 0x73) (0, 0x73)` draws overlays 3 and 0. Owned fragments drew only the
  backdrop, so the clock and battery waited for the refresh timer and vanished whenever a
  page redrew. Owned fragments now queue the same two.
- **No way back from a device.** The right side strip led back to the menu, with nothing on
  screen to say so. Command pages now carry the donors' "Devices" softkey: the bottom strip's
  right half (raw touch `x 2406, y 271`, tag `0x2B`), its label at (110, 202) in the
  scaffold's softkey font, bound to the device's menu page.

### The hub: Activities, Devices and back

Every Logitech configuration boots into its Activities screen, devices or not, and OK on a
firmware notice opens it. Its bottom strip carries Options on the left and Devices on the
right; the device list carries Activities on the left; a device's pages carry Activities
on the left and Devices on the right. Upstairs draws the labels in their own fonts and
colours - Options in attribute 13 at (22, 202), Activities in 6 at (16, 202), Devices in 9
at (110, 202) - and binds them through the screen's touch template: zones 0x30/0x31 on
Activities, the menu template's 0x33 on the device list, 0x2B/0x2C on a device page. On the
device list Logitech's Activities runs a section-15 switch that reads "Current Activity"
while one is running; with no activities it is a plain navigation.

A generated image now has the same hub: ordinal 40 is Activities ("No activities" until
activities exist), the device list starts at 41 and is there with no devices ("No
devices"), and command pages carry both softkeys. Options follows with the Options screens.

### Options

Upstairs' Options screen (mode 276) has two pages: Turn Remote Assistant On, Tutorial and
Date and Time, then Turn Screen Sounds Off and Screen Sensitivity. Date and Time, Screen
Sensitivity and Screen Sounds are the builder's boilerplate - they set the remote's clock
and its touch screen - while Remote Assistant runs a configuration's power checks and help
flow and Tutorial names its own activities, so those two are left out until activities exist.

The rest is generated (`backends/harmony_one/options.py`). It was first copied from upstairs,
which copied upstairs' language and the years it offered (2023 to 2025), and did register
arithmetic on upstairs' own variable 47, a number that means something else in a generated
image. Read from upstairs' 16 screens, it is a chain of pickers and one list:

| screen | buttons | each writes | then |
|---|---|---|---|
| Year | the build year and either side, one a row | clock variable 6 := year - 2000 | Month, the leap one in a leap year |
| Month (two: leap and not) | twelve, six a page | variable 5 := month - 1 | the Day screen with that month's days |
| Day (28, 29, 30, 31) | six a page | variable 3 := day - 1, then `07 FFF8` | Hour |
| Hour | 12:00, 1:00 ... 11:00 | variable 2 := 0 to 11 | Minute |
| Minute | 00 to 59, ten pages | variable 1 | Time of Day |
| Time of Day | AM, PM | PM adds 12 to the hour if it is below 12; both set a flag and `07 FFF9` | Options |
| Screen Sensitivity | Very Low, Low, Medium, High, Very High | `3F F508`, `F50C`, `F500`, `F504`, `F507` | a screen saying so; its OK returns |

Every write is silent (`07 FFFF` before it) and every button clicks (`75 0FCA`). Back steps
to the previous picker; from Day it goes to the Day screen's own month, chosen by tests on
variables 5 and 6. Screen Sounds is a row of Options itself: a switch on its flag whose two
programs write `3F F300` or `F301`, flip the flag and redraw (`07 FFF7`).

A picker opens on the page holding the clock's current value and frames that value's button.
Its enter handler loads the variable into the accumulator (`1F EF`), takes the first value
off (`79`, adds), divides by the buttons a page (`77`) and queues `(accumulator, 76)`, show
that page (`1F F7 76`); the Hour screen first folds an afternoon hour back by 12. Each time a
page is drawn (event `0x29`) the handler reads the page shown (`1F E7 00`), and on the value's
own page leaves the value's index in a scratch variable and runs a switch on it whose
programs draw four 2-pixel bars round that button in `0xEC07`. The 800's interpreter gives
these: `77`/`78`/`79` divide, multiply and add to the accumulator and `7A` loads it; `0x1F`
bands `EF` accumulator := variable, `ED` variable := accumulator, `EE` variable := byte
register, `F0` byte register := variable, `F1`/`F2` decrement/increment, `F7` queue
`(accumulator, low)`, `F8`/`F9`/`FA` divide, multiply, add to the byte register.

The screens' text is a table of labels and the years come from the build date, which also
stamps the clock; their pictures are `images/options/`. Their touch zones follow one rule:
buttons take tags from `0x30` in reading order, Back the next tag (`0x2B` after six), the
side strips `0x2E`/`0x2F`. Each picker's enter handler lights zones 1 and 3 when it has
pages and 5 always, which with the testers' photos places the zones: 0/1 and 2/3 the side
arrows, 4/5 the left softkey bar, 6/7 the right one, orange and white.

Built as of 2024, every one of the 125 buttons writes what upstairs' button of the same label
writes (`one-tools`' comparison, by label and screen title).

**Section 15 is a set of switch tables.** Opcode `0x72` with operand `group << 8 | variable`
reads the variable and runs, in the drawing VM, the program the group assigns to its value:
`u8 lead (2), u8 n, n {u16 value, u24 program}, u8 m, m {u16 low, u16 high, u24 program}`.
A program queues its action through drawing atoms, so one key does different things by state
- Screen Sounds toggles its flag this way, and the date picker steps through its fields.
Section 15's pointers come first and the 151-byte platform table after them, so section 16's
pointers move with the count. A generated image had no tables at all before.

A generated image numbers it all afresh: Options at 41, the Options screens from 42, the
device list after them; the carried variables after the platform's 18 in section 14, before
the terminator; the carried timers after the platform's. The Options screen itself is drawn
by the build on upstairs' three row frames, labels centred in its row font (attribute 5),
with Screen Sounds' label a drawing switch on its flag ("Off" at 0, "On" at 1) placed last so
each case can end the program. Activities gains its Options softkey.

### Words are the build's own, and so are the font codes

A text instruction names glyphs by code in the font its attribute selects, and nothing in
the firmware fixes those codes: a generated image carries no character table, and the
firmware draws whatever the codes point at. The donors' fonts each carry a sparse table of
their own (the codes the donor's text happened to need), and a build had to keep them only
because the firmware's 40 screens, copied from upstairs, drew their words in those codes.

Those words are now the build's too. `platform/system-screens.json` keeps the screens'
pictures and logic, but each word is a `label` item - `{"key", "font", "y", "align", "x"}`
with `line` or `value` - naming an entry in `backends/harmony_one/platform_text.py`: a
screen's lines by ordinal, the 30 system messages' numbered title, OK, and the status
bar's clock (weekday, hour on a 12-hour face, minutes). A build draws each in its slot's
font: centred, from a left edge, or against a right edge (the clock's weekday ends at 141,
its hour at 158, its minutes start there), as the donors placed them.
`tools/harmony_one_extract_assets.py` writes the model that way from any donor; run on
upstairs it reproduces the shipped file exactly.

So the codes are each image's own, as they were in every Logitech configuration: a slot
carries exactly the characters that image draws in it, numbered from 1 in code-point order.
`generate.build` lays the image out twice. The first pass gives every slot each character
its words could need (the catalogue in the project's language, the device and command
names, printable ASCII) and `fit_label` records what each slot was asked to draw - the
whole label, since a label's characters are checked before it is cut to fit. The second
pass builds the image with exactly those, and returns `characters`, one `{code: char}`
table per font attribute, for anything that has to read the text back. A slot holds at
most 127 characters (`assets.MAX_CODES`); a build that needs more is refused by name.
That bound is generous for any alphabetic script - the busiest slot of a project mixing
Japanese, Greek, Russian, German, Chinese and Korean drew 59 - but a CJK project with many
long names could reach it. A slot that is a sheet keeps the codes its manifest entry gives.

### A device's power and inputs are state variables

As downstairs and upstairs build them (arch 12):

- **Sending a command** is an object `(command id, 0x7D) (device << 8 | tenths, 0x7C)`: on arch
  12 `0x7C`'s high byte is the device and its low byte a wait in tenths of a second.
- **`<Label>_Power_2`**, values 0 and 1: going 1 to 0 runs the device's off send, 0 to 1 a list
  of its on send and then the power-on delay as `0x7C` waits a hundred tenths at a time
  (downstairs' amplifier waits `0x264` then `0x214`, 12 s). A device with one power command
  sends it both ways.
- **`<Label>_Input_<n>`**, values 0 to n-1: inputs chosen directly get one transition each from
  "any value" to the input, running its send; inputs reached by stepping get one transition
  per ordered pair, stepping as many times as it takes. Every input variable in upstairs and
  in Kāt's configuration writes "any" as `0xFFFE`, and downstairs' amplifier does too; only
  downstairs' television uses `0xFFFD`. An activity's tag 5 writes its inputs again to re-send
  them, which only works if the transition fires on the value already held, so `0xFFFE` is
  read as "from any value, the same included" and is what a build writes.
- **Section 0 names them**: `Root` and `State` containers, then one leaf per state variable
  whose id is the variable's index - `TV_Power_2`, `TV_Input_11`, `CurrentLocation_1`,
  `CurrentActivityState_0_3`, `ButtonSoundVolume_2` (the Screen Sounds flag). No donor names
  a command. Generated images used to name every command there, whose ids collide with the
  variables'; they now name the variables, as the donors do.

A generated image builds them from the project's device fields - `power_on_cmd`,
`power_off_cmd` or a toggle `power_cmd`, `power_delay`, `inputs`, `input_cycle`,
`input_delay`, `online_inputs` and `app_power_delay` - after the Options screens'
variables, and activities set them by writing a device's power and input variables.

**The input delay and a smart TV's apps.** Logitech keeps a device's input delay (the
archive's `InputDelay`) in each input's own command object: Kāt's Hisense 50R6 has
InputDelay 1000 and its ten input sends carry `0x7C` low byte 10, which no other command of
it does (its power send has 1) - so there the low byte is the wait after, in tenths, as
arch 12 reads it. Its apps' delay (`ConnectedAppPowerOnDelay`, 45 s) is a variable
`Kate_TV_OnlinePower_2`: power-on starts timer 2 (`1F EB02`), which after 45 s writes it 1;
power-off writes it 0; the Netflix input loads the byte register with 0 and, behind a test
of it, waits 45.2 s and writes it 1, then sends. A generated image has `<Label>_Online_2`
instead, with no timer: power-on clears it, and the first app after waits only what the
power-on wait has not, `app_power_delay - power_delay`, then sets it. An import reads both,
and the input delay either way (importing.py).

### The idle layer: key lights, USB, start-up

**The keypad lights only when the configuration lights it.** The factory image (`Region_3`)
has no light instruction at all, and generated images had none either, so testers saw the
screen work and the keys stay dark. Opcode `0x3F` band `0xC0` drives one light channel:
channel `(operand >> 4) & 0x1F`, level `(operand >> 1) & 7`, bit 0 a flag (set only on the
screen backlight when the off timer is armed). The 800's handler passes `low >> 4`, but the One's
donors use both `0xC0xx` and `0xC1xx` in the same sequence, so the high bit is part of the
channel. Upstairs uses 15 channels:

| channel | what upstairs does with it |
|---|---|
| `0x11` | level 6 on every wake, 0 when the off timer fires: the screen backlight |
| `0x08`-`0x0C`, `0x10` | level 1 on every wake, 0 when the timer fires: the keypad itself |
| `0x00`-`0x07` | zones a screen lights on entry and clears on leaving, level 1 |

Which keys a zone lights is not known yet; the screens that light them are, the same in
all three household donors (every screen's enter handler, `one-tools`):

| screen (upstairs) | zones |
|---|---|
| Activities (197) | 1 3 5 7 |
| Options (276) | 1 3 5 |
| Date and Time (176), Screen Sensitivity (104) | 5 |
| the device list (72) | 0 2 4 |
| a device's commands, one page (88) | 4 6 |
| a device's commands, several pages (97) | 0 2 4 6 |
| an activity's screen, one page (153) | 7 |
| an activity's screen, several pages (230) | 1 3 7 |

So the arrows light only where there are pages to turn, and a softkey's bar only where the
screen has that softkey. A first reading of this table swapped the two command rows, and
generated images lit the arrows on single pages until the three donors were tabulated.

Zones {0, 2} and {1, 3} never light together: each guards the other's flag.

**Each zone has a flag**, a configuration variable (upstairs packs zones 1 and 3 into one
three-valued variable, 0 and 2 into another, and 4 to 7 into one each). A screen's enter
handler (`0x06`) lights its zones and sets their flags; its leave handler (`0x07`) turns them
off and clears them. Start-up clears every flag.

**Every key wakes the keypad.** A context (upstairs' 4) holds a row for each of the 52
physical keys, every row flags bit 0 - run it, then keep looking - so the key goes on down
the stack to the screen it was meant for. Both donors add two codes below the keys: `0x17`,
which runs `0F FFE1` with the byte register at 1 and then 0, `0F FFE3` twice, the wake and
`3F F101`, and `0x30`, which runs the wake alone. A first generated machine left both out,
and a tester's remote woke on its keys but not when picked up, which makes `0x17` the
firmware's motion event. Each key row runs the wake:

1. stop the off timer (2); screen backlight to 6; keypad channels to 1;
2. each zone whose flag is set to 1;
3. arm: stop the off timer; if platform variable 17 is not 0, screen backlight to 6 with bit 0
   set and start the off timer; start the poll timer (13), whose action is this step again.

The off timer (duration 10) turns every channel to 0 and writes `0x3F F101`. Upstairs wraps
the wake in tests of platform variables 13, 16 and 9; run under every combination of their
values (`one-tools/effects.py`), the tests only change how many times the same writes repeat,
never the end state, so a generated wake does not need them.

**The platform variables are the firmware's.** No configuration writes 0-17; the factory
image declares their ranges. 0-6 count the clock (seconds and minutes to 59, hours to 23,
days to 30, weekday to 6, months to 11, then the year); 9 runs 0 to 7 and the donors treat 2
or less as a low battery; 16 is set while USB is connected (the start-up USB check reads it);
13 (initially 1) holds back the plug-in's switch to the charging screen; 17 (0 to 3) gates the
off timer - its meaning is not confirmed.

**Events go through the key stack too.** The firmware queues them as opcode `0x65` with the
event code as operand; upstairs' context 1 holds them, and the factory image's single context
holds the same codes:

| event | factory image | upstairs |
|---|---|---|
| `0x26` charge state changed (USB in) | enter the USB screen (28) | beep `0x4664`; the charge context (`1F E8`: 5 unless 13 is set and USB is in, 0 unless the battery is low, then 6 - see below); wake; push the mode, enter the USB screen (1), `07 FFFB`; if 13 is set start timer 7 (5 later: the charging screen 174) |
| `0x27` charging stopped | enter screen 0 | beeps `4664 1FF 1FF 1FF 4664`; the charge context; wake; if 13 and 15 are set, `3F F200`/`F201` by USB; pop the mode if the USB screen marked itself shown; `07 FFF6` when the battery is at 1 |
| `0x10` | nothing | when the battery is at 2 or less, wake; `3F F200` if 13 and 16 are set |
| `0x19` | nothing | `07 FFF6` |
| `0x2D` | `07 FFFA` | `07 FFFA` |
| `0x25` | enter screen 17 | nothing |
| `0x1F` on external power | a beep | `3F F100` (the motion sensor disarmed); beep; the charge context; wake; if 13 is set, timer 5 (5 later: push the mode, the charging screens - see "Charging") |
| `0x1E` off external power | beeps, screen 0 | beeps `4664 1FF 1FF 1FF 4664`; back to what was shown if the charging screens are up; the charge context; wake |
| `0x23` charge fault | - | beep; screen 9 (the charging-problem notice); `07 FFFB`; timer 14 (20 later: lights out) |
| `0x0F` battery level up | beeps | the current activity's screen, then the charging screens 5 later if 13 is set - `0x1F`'s second half: a build beeps, goes back to what was shown and starts that timer again |

**Where the events come from.** The One's application firmware (Region 2 of the 54.2.5 and
3.4 `.hfw` files, PIC18 code loaded at `0x20000`, disassembled with Ghidra) posts an event
by queueing `1F FCxx` - the event through the key stack - from a few routines that each
compare a reading with the last one:

| events | posted when |
|---|---|
| `0x0F` / `0x10` | the battery level (0-7) went up / down, then `0x18`-`0x1D` for levels 0-5, `0x0D` for 6, `0x0E` for 7 |
| `0x15` / `0x16` | a second reading (0-3; the light sensor, it seems) went up / down, then `0x11`-`0x14` for its level |
| `0x17` | the remote moved, while the motion sensor is armed |
| `0x20`, then `0x1F` / `0x1E` | external power (pin RB1 low): connected - the cradle or a charger - / removed |
| `0x21`, then `0x22` / `0x24` / `0x25` / `0x23` | the charger's state: off external power / charging / charged / a fault |
| `0x28`, then `0x26` / `0x27` | USB connected / disconnected |

Both firmware versions post the same numbers. The 800's differ - it posts `0x18` plus the
level for every level, and its own codes for power - so its numbering is not the One's.
The charge contexts fit the One's: the low one answers levels 0-1, the normal one 2-5, the
USB one external power removed.
| `0xAE`, `0xAF` | - | beep `0x0FCA`, previous / next page (`0F FFA0`/`FFA1`) |

The USB screen's enter handler sets a flag and its leave handler clears it; `0x27` pops only
when the flag is set, so unplugging never pops a screen the user opened themselves.

**Start-up** (upstairs' object `0x46C`, run by section 9's start-up list): `0F FFE1` four times,
`3F F064`, silent resets (`07 FFFF` then a write) of its own flags, push contexts 1, `0xFE`,
then the wake with `07 FFFB`, push `0xFD` (the current mode), `0xFC` and 4 (the key light); the
charge context; clear every zone flag; the wake; button sound flag to 0 and `3F F301`.

**How a generated image gets it.** `dabe16d` carried all of this from upstairs, cutting
what led into donor screens to the null instruction: about 80 objects of donor logic. It is
now generated: `backends/harmony_one/idle.py` builds the machine from the tables above - a
flag per zone, a wake, the off and poll timers, the charge context, the events, the USB
screen's shown flag, and enter and leave handlers per kind of screen - as a model in the
carried-screens form, and `idle.attach` appends it to the Options model so one namespace
holds both. Nothing about lights is in a project: a screen's zones follow from its kind.

The Options extractor no longer carries any of it. A carried screen's handlers named
upstairs' zone objects (lights on channels 0-7 and a flag write); the extractor recognises
those and writes `{"zones": [...], "on": bool}` instead, which the build resolves to its own
zone objects. The scaffold's Options model shrank from 690 objects, 11 timers and 19
variables to 504, 4 and 3.

`one-tools/compare_idle.py` runs a generated image and upstairs side by side - the key
light, the eight events and both timers, under every combination of variables 9, 13, 15, 16
and 17, five sets of lit zones, and the USB screen shown or not: 5,280 runs, none differ
(upstairs' timer 7, the charging screens, set aside; they are generated now, below). The
screens' enter and leave handlers
light and darken the same zones as their upstairs counterparts. One ordering was fixed on
the way: the carried start-up entered Activities before clearing the zone flags, so the
first timeout lost Activities' zones; start-up now clears them first and enters last, as
upstairs does.

### Charging

While a One charges, every donor shows the same four whole-screen pictures in a ring: a
battery for 5, then three photographs for 1 each, round again (upstairs' screens 174, 178,
177, 179; downstairs' and Kāt's are the same pictures). Each is a screen of one bitmap at
(0, 0) and nothing else - no title, no status bar - and each screen's enter handler runs
`07 FFFB` (which also stops the keypad's off timer, so the screen stays lit), pushes a
context binding every key to "enter the battery again", puts the USB charge context under
`0xFC`, and starts the timer that enters the next; its leave handler stops that timer and
chooses the charge context again. External power connected (`0x1F`) - the remote set on
its cradle - opens the ring after timer 5 (5), over what was shown; removed (`0x1E`) goes
back. Upstairs' USB-in handler
also starts a timer into the ring when 13 is set (timer 7).

A build generates the same (`backends/harmony_one/charging.py`, `idle.py`): the scaffold's
`charging/battery` and `charging/photo-<n>` pictures - extracted by
`tools/harmony_one_extract_assets.py`, which follows the ring from the screens' own timers -
as bare owned screens straight after the screens carried behind Options, every key bound
in the screen's own list to the battery's screen rather than in a pushed context, and a
flag the enter and leave handlers keep so that `0x1E` pops the mode only while the ring is
up. USB in does not open the ring: the USB screen's own flag would no longer be the one
shown, and unplugging would leave the ring up. A theme without `charging/battery` gets no
charging screens and no `0x1E`/`0x1F`/`0x23` rows.

### Activities

An activity is a value of `CurrentActivityState`, a context in section 10, and four kinds of
screen; everything it does is a state write, as Danny Bloe's "how an activity is built"
found and the three household donors agree. Read from upstairs, downstairs and Kāt's
configuration with `one-tools/disasm.py` (contexts, modes and now switch tables), and
checked where it matters against the Harmony 800's firmware:

- **The counter.** `CurrentActivityState_0_<n+1>`: values 0 to n-1 are the activities and n
  is nothing running, its initial value. Every "go back to what is running" is a section-15
  switch on it: an activity's value enters its first page, the idle value the Activities
  menu.
- **Selecting.** `1F FFxx` selects context xx. The 800's handler (`FUN_0800b1b4`) runs the
  old context's tag 2 and the new one's tag 1, or the running one's tag 5 when it is picked
  again. A menu row is a click (`75 0FCA`) and the select; Off (`0xA5`, in the events
  context) selects Off's context. `07 FFFE` runs the running context's tag 5 again.
- **Enter (tag 1)**: enter the activity's starting screen, `07 FFFB` (stop every running
  timer: the 800's `07` handler with low byte `FB` calls its timer reset), write 1 to the
  power of each device it uses in order, its inputs, 0 to every other device's power, the
  counter, then enter its first page. A transition sends each command; an activity names
  none itself. **Leave (tag 2)**: `07 FFFB` and its leave steps. **Picked again (tag 5)**:
  `07 FFFB`, its inputs again, its first page.
- **Keys.** The context binds each key the activity routes - volume and mute to the volume
  device, the rest to the control device, by each command's hard slot - to that command's
  own object, as a device page binds it, and Help (`0xA6`) to its Help screen. A device page
  binds every key of the keypad in its own list (a command, or nothing), so device mode
  never falls through to the running activity; the stack is the donors': events (1), `0xFE`,
  the current mode, `0xFC`, the key light, and start-up selects Off's context last.
- **Off's context** has tags 1 and 5 and no tag 2, as every donor's has: the counter to
  idle, `07 FFFB`, the Activities menu, every device's power to 0.
- **Screens.** The starting screen draws the infrared waves (62x33 at 57,33), the
  activity's icon (62x42 at 57,67), "Starting ..." in attribute 11 and "Keep the remote
  pointed at your system." in attribute 0, and swallows every key. The activity's pages
  are its buttons, six to a page on blue frames, a Devices softkey, the side strips turning
  pages. Help draws its name, "Attempting to fix the problem...", the waves and the same
  reminder; entering it re-sends what the activity set and goes back. The device list's and
  device pages' left softkey reads "Current Activity" while one runs.

**Keys by scan code.** A row binds key `0x80 | scan`. Danny's key table gives 32 scans;
the rest are read here. Scan 34 (`0xA2`) opens the Activities menu from Kāt's events
context, 37 (`0xA5`) selects Off's context in all three, 38 (`0xA6`) enters Help in every
activity context, and 13 is the remaining keypad scan, `NumberEnter`. Danny left two pairs
undecided because every activity binds both members the same way; upstairs' Xbox One page
does not: scan 36 sends its `Chptr+` and 26 its `Chptr-`, while 27 and 29 send its
direction keys, so 27/29 are `DirectionUp`/`DirectionDown` and 36/26 `UpArrow`/`DownArrow`.

**Favourite channels.** Kāt's configuration opens a favourites activity on its favourites:
a page of buttons, "Commands" on the left softkey and Devices on the right. Logitech tunes
each one by writing a channel variable whose transition loads the number (`7A`) and runs
the firmware's number sender (`1F F3`) over a digit table in section 17. A build sends the
digits instead - the control device's digit commands, each followed by its key delay
(`press_interkey`), then the confirm key (`channel_confirm`) - which sends the same codes
without the table. A favourite's logo is composed onto the frame of the button place it is
drawn in; a favourite without one shows its name. An activity with favourites and buttons
opens on its favourites, the left softkey going between them ("Commands"/"Favorites"),
lighting zones 5 and 7 as the donors' screens with both softkeys do.

**Help.** Upstairs' Help, read with `one-tools/flow.py` (which follows a screen's keys,
touches and handlers to every screen they enter), re-sends the activity's power and inputs
under "Attempting to fix the problem... Keep the remote pointed to your system.", then asks
"Did that fix the problem? If not, the remote will ask you questions to help correct the
problem." No asks after each device's power and then each input in turn - "Is the AV
Receiver on?", "Is the TV set to the TV input?" - over the activity's icon, Yes and No the
softkeys. Yes moves on to the next; No sends it again and asks "Now is ...?", whose Yes asks
"Did that fix the problem?" (Yes: the activity; No: the next question) and whose No sends it
again and asks the first question once more. After the last, the activity. Help on any of
these screens goes back to the activity. Off's Help is the same about each device being off.
A build generates exactly that: Help's screen, the first question, and four screens per
question (`ordinals.QUESTION`), the words Logitech's.

**The Remote Assistant.** Upstairs keeps one state for the whole remote (its variable 19,
0-3, unnamed): 0 never shown, 1 welcomed, 2 shown before, 3 hidden. After an activity
starts - or is picked again - a switch on it opens a note titled with the activity's name
and a colon, under "Remote Assistant:": at 0, "If any devices are not set up correctly,
press "Help" now." (entering it sets 2), OK to the activity; at 1, "The remote has now set
up your system for this Activity." (also sets 2), OK to that note; at 2, that note, OK to "Do
you want to hide the Remote Assistant?", whose Yes sets 3 and says "To hide the remote
assistant, use the software to update the display settings for your remote."; at 3,
nothing. Off has its own: at 0 or 1, "Welcome to your remote." (OK sets 1), then "Ensure all
your devices are off. If any devices are still on, press "Help" now."; at 2, that and the
offer to hide it. Start-up runs Off, so a new remote opens on the welcome. Options' first row
is a switch on the same state: at 3 it reads "Turn Remote Assistant On" and sets 1, else
"Turn Remote Assistant Off" and sets 3. A build generates all of it, its state
`RemoteAssistant_4` (activity_screens.Flow._notes).

**Options and the Tutorial.** Both household donors' Options have two pages: the Remote
Assistant, the Tutorial and Date and Time, then Screen Sounds and Screen Sensitivity. A
build with activities lays them out the same; without activities, Options is one page of
Date and Time, Screen Sounds and Screen Sensitivity. Every donor's Tutorial is the same
eleven pages (upstairs' screens 218, 219, 215, 216, 208, 209, 206, 207, 211, 222, 223): a
black screen - its fragment a filled rectangle, not the backdrop - one of Logitech's pictures
of the remote, the words from the left at x 10 in attribute 14, eleven pixels a line, and
Exit bottom right. Each is moved on by the key it teaches (the right arrow, Activities,
Help, Off) or by touching the page, the left arrow back, Exit back to what is running. A
build generates the same from a page table (options_screens.TUTORIAL: the picture and
where, where the words start, the keys and touch zones that move on, the labels drawn over
the picture) with the scaffold's `tutorial/<n>` pictures, which the extractor finds as the
black-screen pages and orders by their own left arrows, and Logitech's words from the
catalogue; it adds a small page counter, top right.

**Held steps.** A sequence step held for a duration becomes a record of its own: the
command's press, then its repeat frame (or the press again) until the hold has lasted that
long, then its release - the One holds a code only while a key is down, so this is how a
sequence can give a television its two-second power-off. The record is in its device's
section-4 run but on no screen.

**Where a build improves on the donors.** Help re-sends a device's power only where it has
a separate on and off command, since sending a toggle again turns a device off that Help
was asked to fix; Logitech's Help resent toggles too. Off's Help likewise sends only
discrete offs.

**The pictures.** Activities are drawn in blue where devices are orange and Options green:
the Activities menu's row frame and the six button frames, found from the menu screen and
from the screens the counter's switches enter, and the waves, the one picture every
starting screen shares, are extracted by `tools/harmony_one_extract_assets.py` as
`activity/*`. An activity's icon is composed from its type's icon onto the patch of the
frame or backdrop it is drawn over (`row_icons.py`).

### What the 800's firmware says about the rest

Instructions a build had carried from the donors without knowing what they do, read in
the Harmony 800's firmware (`discord_reports/asdfgpio/ghidra`, decompiled with
`decomp_at.sh`) and each checked against what the donors do with it:

- **The key stack.** A key or event (`0x65` in the queue, `FUN_0800b154`) is looked up from
  the top of the stack down, and the first context that answers it ends the search. An
  entry is a context number, or one of three that stand for something else: `0xFE` the
  running context (the one `1F FFxx` selected), `0xFD` the shown screen's lists, `0xFC` the
  context in the byte `1F E8xx` sets. Every donor pushes events (1), `0xFE`, `0xFD`, `0xFC`
  and the key light, so a running activity answers below the screen and above the events.
- **`1F E8xx` is not a charge byte.** It puts context xx under `0xFC`. The donors choose
  among three on every charging event: 0 normally, 5 on USB, 6 on a low battery. All three
  donors' contexts 0, 5 and 6 are the same: 0 and 6 choose again on battery events
  `0x1A`-`0x1D` and `0x18`/`0x19`, 5 stops the timers on `0x1E`, every row passed on. A
  build writes `E8` with its own numbers for the same three (`CHARGE_CONTEXTS`), and the
  platform model names them (`{"charge": "usb"}`) rather than carrying upstairs' numbers;
  `one-tools/refcheck.py` checks every `E8` names a context. Before this, generated images
  selected 5 and 6 with nothing there, which mattered only once `0xFC` was on the stack.
- **`07` with low byte:** `FF` the next write is silent; `FE` runs the running context's
  tag 5; `FD`/`FC` push and pop the mode; `FB` stops every running timer - the firmware runs
  at most four, in the same slots `1F EB` starts them in; `FA` marks the USB link (the
  donors' answer to event `0x2D`, a USB change); `F7` redraws the page; `F6` drops the top
  of the mode stack without entering it.
- **`3F F0`-`FF` are the firmware's settings**, `index = high & 0xF`: 0 is 10 at reset and
  every donor sets 100 first thing (the handbook reads it as the timers' unit); 1 arms the
  motion sensor, so the next movement posts event `0x17` once and disarms - upstairs writes
  `F101` as the keypad goes dark, which is how picking the remote up wakes it; 3 is the
  button sound (`F300`/`F301`, what Screen Sounds writes); 4, 6 and 7 are bytes the 800
  starts at 75, 50 and 21. Setting 2 (`F200`/`F201`, written with USB) has no handler on
  the 800, so it is the One's own.
- **`3F D0`** queues the next instruction's bytes for the host link; the donors' activities
  run `3F D000`, a build does not.
- **`0F FFE1`/`FFE3`**, which both donors run on the motion event, do nothing on the 800;
  they are the One's own and stay as upstairs has them.
- **Platform variable 17 is the infrared engine's state**: the 800's sender sets it to 1
  while a wait holds, 2 while a code goes out, 3 while one finishes, and back to 0 idle
  (`FUN_0800c77c` and its callers). The idle layer's arm step tests it, so the keypad's off
  timer follows whether infrared is going out. Setting 1 (`3F F1`) is variable 7.
- **The instruction queue holds 40 and drops what does not fit** (`FUN_0800ae3e`, a ring of
  120 bytes). A send or a wait the infrared side cannot take yet puts itself back at the
  head and is tried again, which is why a starting screen stays up until its codes are out.
  Running an object puts all of its atoms at the head at once (`FUN_08018e2c`, then
  `FUN_0800b18e` moving them in front), so a long object queues deep: `one-tools/queue_depth.py`
  runs every handler that way, and no handler in the three household donors goes past 16.
  A build cuts every object longer than eight atoms into a chain of short ones
  (`generate.bounded_objects`, never after a test or a silent mark) and shares identical
  touch templates (section 19 indexes 255); a test checks a fifteen-device project stays
  within 16. Before this, a generated Options picker queued 28.
- **Text codes past 0x7F take two bytes**: the 800's text VM reads a byte with its high bit
  set and the next as `((first << 8) | second) & 0x7FFF`, one less than that indexing the
  font's glyph table, whose count every donor stores as a `u16`. So a slot can hold more
  than 127 characters; a build numbers each slot's characters from 1 and writes codes past
  0x7F that way (`drawing.GlyphCodes`). The second byte may be zero, so a reader skips it
  rather than taking it for the terminator. Not yet seen on a One.

### Labels that do not fit

A generated label wider than its place wraps rather than being refused, by the donors' own
rules above: a button's two lines sit 11 pixels apart around its single-line baseline (53 and
64 for 58), a menu row's 12 apart (51 and 63 for 57). Words wrap at spaces, a word wider than a
whole line is split where it stops fitting, and anything left after the second line is cut and
marked `..`. The upstairs round trip now keeps every device name whole - "Game Console (With
DVD)" and "AV Receiver- Room 1" draw on two lines - where it used to trim them.

### The device menu

A generated configuration's first owned screen is the device menu, at ordinal 40, so every
firmware notice's OK button reaches it. It draws one row per device - a full-width frame,
the device's icon, and its name - three rows to a page, and each row's touch key opens that
device's first command page.

A menu row is bound the same way a command button is, through an object, and in a generated
image that object is a navigation, `(kind, 0x75) (screen, 0x7e)`: the row's screen is the
ordinal a press opens. Donor rows carry one more atom, `(1, 0x99)`, which this section used to
call a constant device-row marker. It is an instruction: opcodes from `0x80` write variable
`opcode & 0x7f`, so it sets the donor's own variable 25, whose range and readers differ from
donor to donor (limit 121, 3 and 1 in the three). A generated image has 19 variables, so its
rows write nothing.

### Nothing a generated image names is missing

`afterglow-research/one-tools/refcheck.py` resolves every instruction in an image - objects,
mode and page lists, timers, section 9's leading list - against the table it indexes, by the
Harmony 800's reading: objects, modes, overlays, contexts, timers and variables. The three
donors come out clean over about 13,000 references, which is what makes the reading credible
for the One. Generated images had three kinds of dangling reference: the menu rows' variable
25, the platform timers (above), and platform handlers carried from upstairs that set and test
the donor's own variables (24, 30, 32, 41, 19) and push its contexts 2 and 3 - screens 0, 1,
2, 3 and 9 marking themselves shown. The extractor now leaves that bookkeeping out (17 atoms,
with the `07 FFFF` modifier before a write and the instruction a test guards), and generated
images resolve every reference.

The menu's touch geometry - three device rows, a header strip and two side strips - is
identical in every donor, so it is carried in the scaffold like the platform screens' own
templates and emitted at whatever index a generated menu slot needs.

A menu holds three rows a page and a device's commands six a page, and both page with the
same primitive: the two side-strip touch zones every screen template carries, `0xae` and
`0xaf`, bound to go-to-screen objects. Menu pages form a cycle, so from the last you reach
the first; a device's command pages run forward and lead back to the menu the device sits
on. Every command is reachable however many devices a project has and however many commands
a device has, up to the format's own ceilings - 255 devices, 256 commands each.

The section-6 ordinal is what makes this straightforward: an ordinal is a screen's position
in the index, not its emission order, so every page's ordinal is assigned before any page is
written and a navigation can name a page that does not exist yet. The menu pages take the
first owned ordinals, the command pages follow device by device, and each row and side strip
is given the ordinal it should open directly.

The donors page differently - one screen with a slot per page and a `0x72` page-control atom
that the firmware advances in place - and that native mechanism is not reproduced here.
Navigation between whole screens is instead the one primitive already proven to work, since
it is exactly what a menu row and a notice's OK button do. Which of the two a real remote
prefers on the side strips is a question for the first hardware test.

### A page you can press

A command page is four things, and a generated one now builds all four. Its drawing program
draws the backdrop, then each button's frame and a label centred over it - nothing in the
format clears the screen, so a page that draws no backdrop shows whatever the last one
drew. Its key register binds one key code per button, from `0xb0` upward in reading order.
Its section-19 template gives each button a touch zone. And its slot joins the three.

A button is bound to a command through two objects, not one. The key register row names an
object whose atoms are a constant `(0xfca, 0x75)` - present in all 185 command rows of a
donor and never absent - and a reference to the command object proper, which is the
`(command, device)` pair. So the chain is key, wrapper, command.

Touch zones are raw panel coordinates rather than pixels: x runs about 1173 + 14 per pixel
and y about 3630 - 16 per pixel, measured upwards, with different scales per axis. That is
calibration rather than layout, so it lives in the scaffold beside the platform table, and
a page takes the smallest of the donors' templates that covers its buttons - they carry
geometry for 1, 2, 3, 5 and 6, so a page of 4 uses the 5-button template with the zone for
the button it does not draw removed.

A label wider than its button is refused rather than drawn over the edge, because nothing
in the format clips: `Sony BDP-S5000ES` is 100 pixels against 81. Splitting or shortening a
name that long is a decision for whatever builds the project, not for the writer.

## Where the artwork comes from

The pictures are not in firmware, so a generated configuration has to carry them. They
live as PNG files in `scaffolds/harmony-one/`, listed by `assets.json`, and anyone can
replace them: that directory is the whole of what a Harmony One looks like. The pictures
that ship are Logitech's own, extracted from a configuration, because the format is a
drawing VM and the artwork can be read out of it exactly: 41 of 41 pictures and 527 of 527
glyphs re-encoded to the donor's own bytes after a trip through PNG.

The text does not come from a donor. Every Logitech configuration drew only the characters
it needed - across all four donors 78 of the 95 printable ASCII characters appear, and
seventeen (`$%&;<=>@`, `[]^_`, a backtick and `{|}~`) at no size at all - and a generated one
has to draw whatever its owner typed, in any language. So each font slot is drawn by the
build from a typeface (`scaffolds/harmony-one/fonts/`, Galmuri by default, or the owner's
own TrueType font), in the slot's two colours, on the baseline Logitech's fonts of that
height use; see "Words are the build's own, and so are the font codes".

A font is one colour plus a shadow exactly one pixel down and to the right, in every glyph
of every font measured - which is why there are eighteen slots: one typeface at 11, 14, 15
and 16 pixels in each colour the interface uses. The manifest gives each slot its height
and its `look` (colour and shadow), and `faces.py` draws each glyph as a shape and shades
it. Galmuri 9 fills the 14-, 15- and 16-pixel slots and Galmuri 7 the 11-pixel ones (the
clock and page counters); both are bitmap fonts, read from gzipped BDF by `afterglow.bdf`
and placed one font pixel to a screen pixel. An owner's `fonts/font.ttf` replaces them -
any character it lacks still drawn from Galmuri - read by `afterglow.ttf`: a pixel TrueType font is drawn on its own grid, any other outline
font scaled to the slot's cap height and thresholded, since the display cannot blend.

PNG is read by `afterglow.imaging`, which uses only `zlib` and `struct` from the standard
library, because the format layer takes no third-party dependency and Pillow may only be
imported from the GUI. It reads what an image editor writes - greyscale, palette or
truecolour, with or without alpha, at any bit depth, reducing 16-bit channels to 8 - and
refuses interlaced files by name. Checked against Pillow over 1,351 real files, every one
decodes pixel for pixel.

Two properties of the display constrain an asset, and the loader counts both rather than
applying them quietly. Colour is RGB565, so a gradient bands. Transparency is one bit -
a run-encoded picture writes a pixel or leaves what was underneath alone, and there is no
blending - so a soft edge hardens, at half opacity. The artwork this project ships is
drawn from a palette that is already RGB565-exact and reports neither.

## Emitting drawing programs

Drawing programs are bytecode carrying absolute pointers to other programs, to bitmaps and to
glyph strings. The encoder is the reader's exact inverse. Re-encoding every instruction of every program reachable
from a screen slot reproduces its own bytes: 479 and 1,040 blocks, 12,309 instructions in total,
covering all eleven opcodes the reader recognizes. Only four instruction shapes hold an address -
`call`, `jump`, `bitmap` and `text` - plus a switch's case and range targets; everything else an
instruction carries is a literal that travels with it.

Every block ends at `end`, `return` or `jump`, so none falls through into its neighbour and the
graph can be laid out in any order. Emitting the whole graph at a fresh address and remapping each
internal reference re-disassembles to the same programs in both donors, 479 of 479 and 1,040 of
1,040. The graph is 21,493 and 43,188 bytes, one and two per cent of the image.

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

## The interface parts an image contains

The parts a screen is made of turn out to be constant within an image, so they can be named -
which is how the scaffold's artwork was extracted (`resources.py`,
`tools/harmony_one_extract_assets.py`) - rather than copied screen by screen.

Both donors agree on all of these across every command page they have, 28 and 52:

- one frame bitmap per button position, six positions;
- one font per role - title, button, softkey, page counter, menu row - each a single attribute;
- one shared `Devices` softkey string, one `pages` word, one background bitmap at (0,0), one
  section-12 prologue atom `(2, 73)`, one page selector (37 and 45);
- one touch template per page size, and one menu template;
- one prologue shape: title, background, atom, the page-total block, atom, title again, return,
  with attributes `3, indicator, 3`.

A page's chrome is a resource too. Every command page ends with a two-way switch whose arms label
the left softkey `Activities` or `Current Activity`, both jumping to a common tail that draws the
`Devices` softkey and the page counter. All 28 and 52 pages draw the identical shape from the
identical shared strings.

The page counter is right-aligned: its right edge is 18 on every page, which is why a one-digit
`1` sits at x=13, a wider `4` at 12 and a two-digit `10` at 8. The prologue's total is left-aligned
at x=23 instead. A resource the image does not agree on is reported as absent rather than guessed.

Menu row icons are the exception: they belong to the devices that used them, five and fifteen
distinct sets.

## The Activities menu

Both donors draw a second menu of the same shape - equally sized touch zones in reading order,
paired band for band with labels at x=63 - but its rows start an activity instead of opening a
screen: the row's object carries opcode `0x1f` with `0xff` in the operand's high byte and the
activity ordinal in the low one. That is also what keeps the two menus apart, because a device-menu
row containing it is refused.

Neither donor replicates its Activities menu: one screen holds all of it, two rows downstairs and
eight across three pages upstairs, each activity on exactly one row and every ordinal matching one
the activity index already owns. Its labels come from the same restricted menu font as the device
rows.

### What an activity ordinal is

An activity ordinal is a position in the section-10 context table, so removing a context would
renumber every one above it. Section 10 opens with 7 contexts that hold no activity in all four
images measured, and activities occupy 7 upwards. Those seven are not otherwise constant: they were
byte-identical at identical offsets in the first two images compared, but across four only one of
them - a seven-byte context 5 - is identical, and one image places them 12 bytes further along.
Their count is a format property; their contents are not. Exactly one context row starts an
activity directly - the Off key (`a5`) in context 1 - and it names the one activity each donor keeps
off its menu: a long-form five-row context, referenced by a single object where menu activities have
two. That is the All Off path, and a row for it is refused.

The references to an activity ordinal that this backend can find are few: 5 object atoms downstairs
and 17 upstairs, carrying opcode `0x1f` with `0xff` in the operand's high byte, plus that one
context row. Opcode `0x1f` is not only this action - the donors use fifteen other high-byte values
with it - and section-14 transitions name no activity at all.

Following every reference this backend owns leaves 45% and 50% of the object table reachable from
nothing, and each activity's second object sits in that set. Four measurements show it is emitted
slack rather than a structure something else indexes. The drawing graph walks to completion with no
rejects, so nothing hides behind unfollowed control flow. Of the unreferenced objects, 149 and 463
are entirely zero atoms and 671 and 1,597 are byte-identical to an object that is referenced,
leaving 223 and 327 distinct bodies. Three-byte values equal to an object body address number 3,210
and 5,884, of which section 11's own table is 3,015 and 5,647; the excess is at or below the 209 and
934 measured for random addresses in the same region. Outside the bytes this backend parses, a `u16`
below the object count followed by `0x7f` occurs 116 and 139 times, against 104 and 219 for `0x73`
and a mean of 2,219 and 2,423 over all 256 possible following bytes. Finally, every section with no
model totals 1,520 and 2,419 bytes, where a bare `u16` index over the objects would need 6,030 and
11,294.

That is evidence and not proof - firmware computing an index rather than reading one would
overturn it - which is one more reason a build generates every ordinal afresh rather than
renumbering somebody else's.

## Activities and state contexts

Section 10 begins with a one-byte context count and absolute `u24` pointers indexed by activity
ordinal. A short context is a count followed by four-byte `{key code, object u16, class}` rows. A
zero first count selects the long form: a second count followed by five-byte rows that add a flags
byte before the short-form fields. Codes `01`, `02`, and `05` are the observed ENTER, LEAVE, and
REFRESH hooks. Afterglow retains every context row and resolves only class `7f` object references.

Section 14's complete section body is `8 + 3*n` bytes: a `u16` property count, six header bytes,
then one absolute `u24` pointer per property. A property record contains `u16 initial`, `u16 limit`,
`u16 transition count`, one preserved padding byte, and eight-byte transitions. Each transition is
`{flags u8, from u16, to u16, operand u16, class u8}`. Class `7f` operands enter the section-11
object graph and may ultimately reach indexed command IDs.

An activity row is a touch/key object containing `{0xff00 | ordinal, 1f}`. Its label is retained as
one or more raw glyph lines using the same geometry-based association as device menus. Activity
attribution starts at the context's ENTER and REFRESH objects. Object atoms with a class at least
`80` set property `class & 7f` to the atom's operand; section 14 then supplies the transitions and
commands for that value. An activity that reaches no indexed command is marked undetermined, not
as using no devices, because the separate All Off/default-state mechanism remains unexplained.

The downstairs donor has 10 contexts, 45 properties, 73 transitions, and three ENTER activities;
two can be attributed to indexed commands. The upstairs donor has 16 contexts, 48 properties, 47
transitions, and nine ENTER activities; eight can be attributed. These differing populations
confirm that neither RE-HARMONY's ten-context observation nor one factory activity count is a
format constant.

Section 0 owns the names of state properties used by this engine. It begins with `ed fe`, a `u24`
length equal to the section size minus two, then a contiguous chain of A7 records and a final
little-endian `beef`. An A7 record is `{a7, length u16, type u16, id u16, name}`; `length` counts
the four bytes occupied by type and ID plus the name. Type zero records are containers and type
one records are leaves. Ownership depends on the enclosing section and contiguous close, not an
unbounded A7 byte scan. Names are decoded as UTF-8 when possible and always retained as raw bytes.
The broader upstairs donor contains a valid name with parentheses that RE-HARMONY's restricted
name regular expression omitted.

Section-10 rows also provide the physical-key mapping for active activity contexts. A binding is
complete evidence only when its class-`7f` object is either a direct `{command,7d}/{device,7c}`
shape or has exactly one `7f` jump to that shape, the command is owned by section 5, and command
and runtime-device high bytes agree. All other rows remain visible with their rejection reason.
The downstairs and upstairs donors contain 62 and 138 such complete rows respectively.

The button inventory begins at header offset `67`: a one-byte count followed by four-byte
`{code, sequential index u16, tag}` rows. Both broader donors contain 55 rows with sequential
indexes. This is a vocabulary, not a dispatch table. Comparing its codes to all section-19 zones
classifies 43 as physical candidates, two as lifecycle hooks, two as established touch controls,
two as paging strips, and six as physically/touch ambiguous. English silkscreen names are not in
the image and are therefore not assigned from this table.

Drawing inventory follows calls, jumps, every switch target, and class-`73` atoms through the
section-12 subprogram index. Referenced bitmap resources have either a four-byte mode-0 header and
flat RGB565 pixels or a five-byte mode-1 header and the row-run encoding used by sprites. Every
referenced resource must decode to its declared width and height. The downstairs donor reaches 64
distinct valid bitmaps; the upstairs donor reaches 75, with no invalid referenced resource.

## Reading a configuration back

An import reads what a configuration does, not only what it holds (`importing.py`), and the
same reading serves Logitech's images and generated ones. What it relies on, measured on the
three household configurations and on generated ones:

- **Text is read by shape.** The glyph code a character gets is each image's own - Kāt's
  living-room configuration numbers 74 codes in an order none of the established layouts
  has - but Logitech's faces are the same in every image, so a glyph's pixel fingerprint
  names its character (`labels.py`, `platform/glyph-shapes.json`). Two faces draw a capital
  I and a small l alike; Logitech's codes are image-wide, so the code another font already
  reads as one is not the other. A letter with an accent no known image draws is the
  image's own letter with ink only above it: Kāt's Finnish ä and ö read that way.
- **A button's place is its touch zone's rectangle, not its key code.** Logitech numbers a
  page's zones its own way - on Kāt's activity page `b0` is the Devices softkey and `ab` a
  button - while the zones always sit in the same two columns (raw x 1257 and 2422) and
  three rows (raw y 3016, 2144 and 1272) as the frames the page draws.
- **A device's pages are often one screen.** Logitech draws a device's command pages as
  slots of one screen - Kāt's television is screen 148, four slots - and this backend as a
  screen per page; both are reached from a device-menu row, whose object also writes a
  variable of its own in Logitech's images.
- **Command names are the buttons' labels.** A name too long for a button's line is split
  without a space where it has none ("Power" over "Toggle" is PowerToggle), where this
  backend wraps at spaces. Commands a device page does not show are bound to physical keys,
  and are named by them. Logitech keeps a press-only copy of a device's power and input
  commands - the same code without its repeat - which its state variables send.
- **A device's state variables carry its label.** `<Label>_Power_2` sends the off command
  going 1 to 0 and the on command and the power-on delay going 0 to 1; `<Label>_Input_<n>`
  either sends each input's command from any value, or steps, and some inputs are a
  sequence - wake, step there, confirm - which a project's inputs cannot hold.
- **An activity is the context whose enter writes `CurrentActivityState`.** Its writes to
  device variables are what it turns on and the inputs it sets; an instruction a test
  guards is not something it always does. Logitech's activities then open their own page
  through the Remote Assistant's screens and a switch on `CurrentLocation_1`, not on
  `CurrentActivityState`; an activity's pages are found by their title instead. Logitech's
  Off turns off what is on, by tests, rather than writing a list.
- **A favourite's logo is a picture of its own** in Logitech's images, drawn over the
  button's frame; this backend composes it onto the frame, inside a centred 73x42 box.
- **A held code is a repeat count** in Logitech's images - the low byte of a command
  object's device field, 1 for a tap - and a record of its own in this backend's: the press,
  its repeat frame until the hold has lasted, then a gap.
- **A row's icon is its type's**, the same pixels in every Logitech configuration, so a
  fingerprint of it names the type (`platform/type-icons.json`, written by
  `tools/harmony_one_type_icons.py` from the household configurations).

## What validation proves

Opcode operands are reported as possible references only when every operand for that opcode is
within the current object-table range. This is an inventory heuristic, not enough evidence to
rewrite those atoms.

Passing the validator proves that an image matches the measured arch-12 container and integrity
rules. Inventory counts prove only that these bounded native shapes can be walked. Neither proves
that a particular remote has accepted an image; that is what the hardware probes are for.

