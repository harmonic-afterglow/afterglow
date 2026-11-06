# Screens, modes and pages

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
