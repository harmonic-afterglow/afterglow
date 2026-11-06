# Drawing, fonts, pictures and touch

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
height use; see [generating.md](generating.md#words-are-the-builds-own-and-so-are-the-font-codes).

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
