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
in every donor, but this is an observed layout rather than a validity rule: safely relocated
sections 9–11 sit at the tail and therefore make those three master slots non-monotonic. The end
vector points at the final marker and no donor carries bytes after it.

The native checksum starts with lanes `0x21` and `0x43`, then XORs complete byte pairs from the
start of the payload up to—but excluding—the stored checksum. If the covered length is odd, the
last unpaired byte is ignored. Pairing it with the first stored checksum byte is incorrect and was
the cause of RE-HARMONY's former odd-length rejections.

Payloads must be smaller than `0x390000` bytes. At that size a configuration beginning at
`0x040000` reaches the normal application's backup copy at `0x3d0000`; libconcord's erase-sector
walk also ceases to be safely bounded above `0x3b0000`.

## Current ownership

Afterglow owns structural validation plus read-only section-5 command indexing, exact command
objects, press/hold/release waveform records, screen/key ownership, drawing-program inventory,
section-7 font resources, section-19 touch geometry, device-menu row ownership, activity contexts,
and state transitions. Every unmodeled native byte remains opaque and is preserved unchanged.
Mutation remains outside the enabled backend boundary. A separately tested relocation primitive
exists for the three sections that must grow during authoring, and the screen index can be extended
by one ordinal, but no normal build or write gate uses either yet.

## Relocation safety

Sections 9 (pages), 10 (objects), and 11 (the object table) can be copied to the end of the image
without compacting or overwriting their old bytes. The master index is then repointed. Section 11
must be rebuilt because its entries are absolute pointers into section 10, while section-6 slot
records hold absolute key-register pointers into section 9.

Afterglow enumerates those affected pointers only through owned structures: the 20-slot master
index, the counted section-11 object table, and the complete counted section-6
screen/trailer/slot chain. It does not scan arbitrary aligned three-byte values, because valid
address-sized coincidences are common in waveform and bitmap data. The two broader donors contain
843 and 1,626 affected fields respectively: 214/440 into section 9, 628/1,185 into section 10,
and one into section 11.

A relocation map is expressed in section-local coordinates as contiguous
`(old start, old end, delta)` runs covering every old byte. Appending accepts an identity map;
inserting in the middle requires a piecewise map so targets after the insertion receive the extra
delta. Undeclared content differences, gaps, overlaps, deleted pointer targets, and destinations
outside the new body abort. After rebuilding, every affected field is read back and must target
the mapped address. Up to 24 bytes behind every non-table target must still match its old pointed
content, except for explicitly declared edit ranges. No live owned pointer may remain aimed at a
vacated section range.

The closer pads the pre-checksum body to even length, writes the complete 32-bit end vector,
recomputes the two checksum lanes, and restores `PTYY`. A no-content-change relocation of both
broader donors passes the native validator and reproduces the same command, screen-key, and
activity inventory after repairing all affected references. This is a software invariant, not a
claim that a relocated image has been accepted by hardware.

The authoring layer also serializes the measured object and index primitives without fixed donor
counts. A command button uses a seven-byte command/device object followed by a seven-byte
indirection object; new object IDs are allocated in that B/A order. Device IDs use
`(device index << 8) | 1`, while command IDs use the device index and command ordinal. Command
pages use the observed physical layout order `b2 b3 b0 b1 b4 b5`. Section 5 is emitted as a
one-byte device count and absolute sub-table pointers; each sub-table has a zero byte, a `u16`
command count, and absolute pointers to command-record byte `+11`. The opcode-`75` IR object kind
is derived from the current image's dominant value, retaining `0x0fca` only as the fallback used
when an image contains no such evidence.

These serializers are not an enabled device-creation path. Screen drawings, touch geometry,
section-6 allocation, and a complete post-mutation audit must join them before the backend can
expose authoring.

The command allocator can now lower a complete portable signal list, place each command's press,
hold, and optional release waveforms with its 25-byte record inside one 64 KiB address window,
append a per-device command sub-table, and repoint a rebuilt section-5 top index. It then appends
the measured command/device and wrapper object pair for every command and extends section 11.
The new device index and every command ordinal are derived from the current image rather than a
donor count. Final verification requires section 5 to resolve every newly allocated record and
the command inventory to own all of them. Adding one copied portable waveform succeeds on both
broader donors, producing device indexes 3 and 6 respectively and preserving native validation.
The resulting device has command ownership but deliberately has no claimed menu row or reachable
command screen yet; that UI linkage is the next authoring layer.

Existing section-9 page keys can be reassigned in one relocation pass. Pages are recognized by
their counted four-byte entries and known tags while unrelated section bytes remain opaque. The
requested command must resolve through section 5. A new exact command/device object is appended,
then the key's existing indirection object is cloned with only its single opcode-`7f` target
changed. Cloning is required because the wrapper can also carry navigation or other native atoms;
replacing it with a minimal template would silently discard them. The page entry's two-byte object
ID is the only declared in-place edit.

The postcondition requires the complete recognized page/key set to remain identical, every
unrequested command resolution to remain identical, and every requested key to resolve to the
specified command and runtime device. A same-command dry reassignment passes on both broader
donors, including relocation and checksum validation. This mechanism covers section-9 page keys;
hard keys routed through section-10 activity contexts use a separate operation.

Context-key reassignment accepts only rows already classified as complete direct or one-hop
command/device actions. The context records themselves normally live outside section 10 even
though its index points to them, so their object-ID fields are patched at their own absolute
locations after section 10 has been relocated. A direct action is cloned with its command and
runtime-device atoms replaced. For a one-hop action, both the nested command object and its outer
wrapper are cloned, retaining sibling atoms such as page transitions. The full set of editable
context rows must remain identical; all unrequested command/device pairs must remain unchanged and
each requested row must resolve exactly to its replacement. Same-command dry edits preserve all
62 and 138 editable rows in the two broader donors and pass native validation.

Activity property assignments use another clone-and-repoint operation. The editor follows the
context's ENTER and optional REFRESH hook, and recognizes a property SET either on that object or
one object hop below it. Changing or removing a SET clones the exact containing object; adding a
SET appends it to a clone of the top-level hook. An edit is rejected if the property is outside
section 14, its value exceeds the declared limit, no transition can reach the requested value, a
SET is ambiguous, or removal would create a zero-atom object. The existing section-11 object ID is
repointed to the clone rather than allocating a new identity. Same-value dry edits on both broader
donors pass relocation and native validation.

Every imported Harmony One project records a same-device baseline contract. It names the
preserved unpacked payload directory, the selected remote profile and full intended identity,
payload size, and SHA-256 digest. A future build must reload through the profile's payload carrier,
match all of those values, and pass structural validation before it can mutate anything. Missing,
moved, or modified baseline bytes are fatal. The project stores a reference rather than embedding
the copyrighted native image in JSON; keeping or redistributing the user's own backup remains a
separate choice.

The read-only inventory additionally bounds two native structures without assigning portable
meaning to them:

- section 11 begins with a `u16` count followed by that many absolute `u24` object pointers;
- an object starts with an atom count; each atom is an operand `u16` and opcode `u8`;
- a native command record is 25 bytes containing carrier period and half-period in nanoseconds, a
  self-pointer, press and optional hold/release waveform pointers, and fixed framing bytes;
- a press-waveform target begins with the little-endian word `0x7fff`, the split leading space
  used by the remote's IR representation; a hold waveform omits that lead-in and begins with a
  carrier-gated mark.

Object-table order is object identity, not an address sort requirement. Donor tables happen to be
ascending, but clone-and-repoint edits place an existing object ID at the tail. Readers therefore
require unique, bounded, non-overlapping object bodies while accepting non-monotonic pointers.

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
those belong to the still read-only indexing and relocation work.

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

### Extending the screen index

Section 6 is the only index a new screen has to enter, and it is the easiest to move: the census
finds exactly one parser-owned pointer targeting it in either broader donor, the master slot at
`0x24`. Its own entries are absolute, so the index can be rebuilt one entry longer at the end of
the image and the master slot repointed, without touching the trailers, slots, key registers or
drawing programs it addresses. Those live below the first master-indexed section in both donors,
not inside section 6's computed range. Appending an ordinal cannot renumber an existing one, so
`0x7e` navigation objects keep their meaning.

Afterglow emits the index, trailer and slot records from the same fields it parses. Re-emitting
every donor screen reproduces the original bytes exactly: 157 and 339 trailers, 213 and 439 slots,
and both screen indexes. The trailer flag is `00` on most screens and `01` on nine in each donor,
so it is copied from the screen being cloned rather than fixed.

A new screen can therefore be built by cloning one owned slot: its template, drawing program and
trailer flag are reused, and its key register is copied with only the command entries repointed at
other objects. Entries that bind no command survive byte for byte, and a slot that opens another
screen with `0x7e` is refused as a source, because a clone would inherit navigation belonging to
the screen it was copied from. Every command key the source declares must be rebound; a partial
rebinding would leave keys firing the source device. The donors offer 28 and 52 such slots.

A clone alone reuses the source screen's artwork, so the labels drawn on it are still the source
device's. Naming the new commands means re-emitting the slot's drawing program.

### Labelling a command screen

A command-screen slot's program is a prologue `call`, then one button frame bitmap per command,
one font attribute, the label instructions that name each frame, and finally a selector and the
chrome that draws the bottom softkey and page indicator. Only the labels are rewritten; every other
instruction is copied byte for byte, absolute pointers included.

The layout comes from the image, not from constants. Each button's own frame bitmap gives its
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

Re-emitting each donor slot with the labels it already draws reproduces its meaning exactly - the
same instructions, positions and text - in all 80 cases, and reproduces its bytes exactly in the 29
slots whose labels are all inline text. The rest differ only because the native producer drew some
labels through a shared string pointer where the emitter writes inline text.

A screen of several pages is built the same way, one slot per page, each cloned from a source slot
whose button count matches that page. Both donors offer slots of several widths - 6, 4 and 2
downstairs, 6, 5, 3 and 2 upstairs - so how a device's commands divide into pages is a choice
between the shapes that image actually contains. All the pages share one prologue, cloned from the
first source's, carrying the new total and, when asked, a new title.

A prologue draws its screen's title at (6,4), twice in every prologue that has one and always
agreeing - 122 of 122 and 298 of 298 - so both copies are rewritten together. Pages are numbered
only if the source slots are: a screen either numbers every page or none, and a multi-page screen
built from unnumbered slots is refused rather than left unable to say which page it is on. Both
donors contain unnumbered six-button slots, so a single-page screen can be cloned without
inheriting a counter.

A font indexes the repertoire sparsely: every font in both donors declares the full repertoire slot
count and leaves a null pointer for each glyph its own labels never needed. The downstairs menu font
draws 36 characters and the upstairs one 48, while their button fonts draw 66 and 70. Knowing a
character's repertoire code is therefore not enough to draw it, and a label is refused when the font
it would be drawn in has no glyph for one of its characters.

### Completing a font

The missing glyphs are usually in the image already, in another font that needed them. Two fonts
are the same typeface when they declare the same height and every code they both carry decodes to
an identical shape; where two compatible fonts disagree about a code, that code stays unresolved
rather than being taken from one of them. Both donors hold 18 fonts in four height families, and
the height-14 family is one face of eight to ten fonts whose union is the whole repertoire.

Filling a null slot with a pointer to a glyph the image already holds is the smallest useful
change: no glyph data is written, the record keeps its address, height and slot count, and nothing
drawn today can be affected, because a label using that code could not have been drawn before.
Completing every font in the donors fills 472 and 464 slots, changing 1,423 and 1,390 bytes; every
label already drawn stays byte-identical and the declared repertoire is unchanged. The title and
button fonts reach the full repertoire, so a screen can be titled and its buttons named freely.

The menu-row font is the exception. Its height-15 family holds only two fonts of that face, so it
gains 2 characters downstairs and 14 upstairs and stays restricted. Drawing an arbitrary menu row
name would need a glyph the image does not contain at that size and weight.

### Changing a device-menu row

Menu rows are laid out differently from command-screen buttons. A row label is left-aligned at
x=63 rather than centred, and its lines sit 12 pixels apart centred on the row band's centre;
both donors draw one- and two-line rows only, so a third line is refused rather than extrapolated.
Every one of the 102 replica rows re-renders to the same meaning, and the 11 rows drawn entirely
with inline text re-render byte for byte.

All 102 row objects have the same shape: three atoms, exactly one `0x7e` and no `0x7f` jump, so
repointing a row is a clone with the `0x7e` operand replaced. Each menu slot's key register lives
in section 9, which makes that repoint an in-place edit inside a relocated section; a register
found elsewhere is refused rather than patched blind.

The menu is replicated and the replicas are only recognized as one menu because they agree, so a
row is changed in every replica at once - four occurrences downstairs, ten upstairs. Changing one
and not the others would break that agreement and leave the remote showing different device lists
depending on how the menu was reached. The change is verified by re-reading the menu: the replicas
must still agree, the row set must be unchanged, every occurrence of the row must carry the request,
and no other row may move.

Both donors fill every menu page, so adding a row means adding a page. A page's rows are the
equally sized content zones of its touch template; the bottom softkey shares the template but is a
different size, and one replica in each donor binds it in the navigation class like a row, so
binding class alone cannot tell them apart.

### Paging

A paged screen states its total in the prologue every one of its slots calls, at (23,18) followed
by the word `pages` at (35,18), and numbers each slot at (13,18) followed by `/` at (18,18). A
single-slot screen draws neither. Across both donors the slot number is the slot's own index plus
one in all 152 numbered slots, the prologue total equals the screen's slot count in all 40 screens
that state one, and the prologue and its slots always agree on the font attribute - which varies
by screen, so it is read from the screen rather than fixed. No prologue is shared between screens
in either donor: 157 of 157 and 339 of 339 serve exactly one, so a screen's total can be advanced
without touching another screen.

Growing a menu therefore clones the replica's own last page - same template, same prologue, same
chrome - drops every row but the new one, advances the page counter, and re-emits the prologue with
the new total and every slot of that screen calling it. Only a menu that already numbers its pages
can grow: building a counter for a screen that has none would mean constructing the prologue's
number block and the attribute restore that follows it, which no single-page screen evidences.
The upstairs menu grows from three pages to four and carries a seventh device; the downstairs menu
is a single unnumbered page and is refused.

A row is added to every replica at once, and afterwards the replicas must still agree, the menu's
own reader must reject no more than it did before, and exactly one row per replica must reach the
new screen. A screen that already has a menu row is refused a second one, because a device with
two rows has two names and the reader cannot own either.

### Removing a row, and reusing the band it leaves

Removing a row re-emits its page without it and drops its key-register entry, in every replica. The
device's commands and its screen stay in the image, unreachable: removing the screen instead would
renumber every ordinal above it and break the `0x7e` objects that name them, which is the same
reason relocation leaves the bytes it moves past in place. A removal that would leave a page with
no rows at all is refused rather than producing an empty page.

That leaves a band free, and a later row fills it instead of growing a page: the new row is drawn
with the frames of a row the page already has, moved by the distance between the two band centres,
and the free band's touch key is bound to a new navigation object. Both donors draw every one of
their 102 rows with its frames at the same offsets from its band centre, and every page in band
order, so a rebuilt page is the shape the producer would have drawn. The new row carries the icon
of the row its frames came from.

This is what lets the downstairs donor take a new device at all: its single unnumbered menu page
cannot grow, but a row removed from it can be replaced.

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

## Building from a project

An authored Harmony One is the user's own image with a bounded set of edits, so a build starts from
the authenticated same-device baseline the project was imported from and never from a scaffold.

Planning compares the project's devices with the ones the baseline's Devices menu already names.
A device the baseline has is left alone. A new one is added only if the image can express it: its
commands must divide into page sizes the image has slot shapes for, its menu must have room or be
able to grow a page, and its name and every command name must be drawable in the fonts those texts
would use. Drawability is judged against the fonts the build will have rather than the ones the
image starts with, because completing fonts is the build's own first step. Anything refused is
named with its reason instead of being dropped.

Applying a plan completes the fonts, then for each new device allocates its commands, builds its
titled screen of pages, and adds the menu row that opens it - in that order, because a screen
cannot bind objects that do not exist and a menu row cannot open a screen that has not been added.

The result carries a confinement report: the steps taken and each one's own report, the baseline
and artifact digests, the number of changed ranges and bytes, how many bytes were appended, and the
device, menu-row and menu-replica counts and reader reject counts before and after. Whether that
artifact may be written at all remains the profile's decision; `require_buildable` is checked
before any of this runs, so a read-only Harmony One describes a plan and writes nothing.

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
  nibble of the operand's high byte picks the test, bit 7 inverts it) and drop the next
  instruction when it fails; `07` with `FD`/`FC` pushes and pops the current mode.
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
the project owns instead, through `authoring.navigation_object`.

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
zero everywhere the factory image has one. With the scaffold's ten 14-pixel fonts and 41
pictures it is 366,350, and with a two-device project of ten NEC commands 368,471.

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

`tools/harmony_one_extract_options.py` carries the rest into the scaffold as
`platform/options.json`, as the firmware's screens are carried: the 16 screens Date and Time
and Screen Sensitivity reach, their 72 drawing blocks, 510 objects, 4 timers, 3 section-15
switch tables and 6 state variables, every reference a name, and the 9 green frames they draw
as `images/options/`. The walk stops where a screen leads back to Options or to the hub.

**Section 15 is a set of switch tables.** Opcode `0x72` with operand `group << 8 | variable`
reads the variable and runs, in the drawing VM, the program the group assigns to its value:
`u8 lead (2), u8 n, n {u16 value, u24 program}, u8 m, m {u16 low, u16 high, u24 program}`.
A program queues its action through drawing atoms, so one key does different things by state
- Screen Sounds toggles its flag this way, and the date picker steps through its fields.
Section 15's pointers come first and the 151-byte platform table after them, so section 16's
pointers move with the count. A generated image had no tables at all before.

A generated image numbers it all afresh: Options at 41, the carried screens from 42, the
device list after them; the carried variables after the platform's 18 in section 14, before
the terminator; the carried timers after the platform's. The Options screen itself is drawn
by the build on upstairs' three row frames, labels centred in its row font (attribute 5),
with Screen Sounds' label a drawing switch on its flag ("Off" at 0, "On" at 1) placed last so
each case can end the program. Activities gains its Options softkey.

### A device's power and inputs are state variables

As downstairs and upstairs build them (arch 12):

- **Sending a command** is an object `(command id, 0x7D) (device << 8 | tenths, 0x7C)`: on arch
  12 `0x7C`'s high byte is the device and its low byte a wait in tenths of a second.
- **`<Label>_Power_2`**, values 0 and 1: going 1 to 0 runs the device's off send, 0 to 1 a list
  of its on send and then the power-on delay as `0x7C` waits a hundred tenths at a time
  (downstairs' amplifier waits `0x264` then `0x214`, 12 s). A device with one power command
  sends it both ways.
- **`<Label>_Input_<n>`**, values 0 to n-1: inputs chosen directly get one transition each from
  `0xFFFD` ("from any value") to the input, running its send; inputs reached by stepping get
  one transition per ordered pair, stepping as many times as it takes.
- **Section 0 names them**: `Root` and `State` containers, then one leaf per state variable
  whose id is the variable's index - `TV_Power_2`, `TV_Input_11`, `CurrentLocation_1`,
  `CurrentActivityState_0_3`, `ButtonSoundVolume_2` (the Screen Sounds flag). No donor names
  a command. Generated images used to name every command there, whose ids collide with the
  variables'; they now name the variables, as the donors do.

A generated image builds them from the project's device fields - `power_on_cmd`,
`power_off_cmd` or a toggle `power_cmd`, `power_delay`, `inputs`, `input_cycle` - after the
Options screens' variables. Nothing sets them yet: activities will, by writing a device's
power and input variables on entry.

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
replace them: that directory is the whole of what a Harmony One looks like. What ships is
Logitech's own, extracted from a configuration - 41 pictures and 18 fonts - because the
format is a drawing VM and the artwork can be read out of it exactly. The loop is
lossless: 527 of 527 glyphs and 41 of 41 pictures re-encode to the donor's own bytes after
a trip through PNG.

A font shipped this way is not limited to the repertoire a donor had. Every configuration
Logitech generated drew only the characters it needed, so across all four donors 78 of the
95 printable ASCII characters appear and seventeen - `$%&;<=>@`, `[]^_`, a backtick and
`{|}~` - appear at no size at all. A generated configuration has to label a button with
whatever its owner typed, so the ten 14-pixel fonts are completed to all 95. Most of the
additions are built from the font's own strokes, which is the only way a new character
looks like it belongs: a backslash is its slash mirrored, an equals its hyphen twice, an
underscore its hyphen at the descender, a semicolon its colon's dot over its comma's tail,
a dollar its `S` with a bar through it, a bracket a stem with two arms cut from its hyphen.
The nine with no relative in the font are drawn on the same grid. Their codes continue past
the largest repertoire any donor uses, so the manifest rather than `glyph_codec` is the
authority on what a generated font's codes mean.

Heights are not interchangeable: the 14 and 15 pixel faces are different designs, sharing
only two of 46 letterforms, so a build draws the owner's own words at 14 pixels everywhere
including menu rows, where the donors used 15.

A font is stored as one sheet of glyphs side by side, with each glyph's position and width
in the manifest. Colour is never drawn by hand: a font is one colour plus a shadow exactly
one pixel down and to the right, in every glyph of every font measured, so a new glyph is
designed as a shape and shaded afterwards. Glyphs are coloured rather than masked - every font in the donors uses
exactly two colours, a stroke and a shadow - which is why there are eighteen of them: one
typeface at 11, 14, 15 and 16 pixels in each colour the interface uses. Filling a font's
gaps from another of the same typeface therefore has to recolour what it borrows, or a
single word comes out in two colours.

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

Every other structure this backend authors is a counted table it can serialize. Drawing programs
were the exception: bytecode carrying absolute pointers to other programs, to bitmaps and to glyph
strings, which could be copied but not laid out afresh. That is what kept authoring to patching.

The encoder is the reader's exact inverse. Re-encoding every instruction of every program reachable
from a screen slot reproduces its own bytes: 479 and 1,040 blocks, 12,309 instructions in total,
covering all eleven opcodes the reader recognizes. Only four instruction shapes hold an address -
`call`, `jump`, `bitmap` and `text` - plus a switch's case and range targets; everything else an
instruction carries is a literal that travels with it.

Every block ends at `end`, `return` or `jump`, so none falls through into its neighbour and the
graph can be laid out in any order. Emitting the whole graph at a fresh address and remapping each
internal reference re-disassembles to the same programs in both donors, 479 of 479 and 1,040 of
1,040. The graph is 21,493 and 43,188 bytes, one and two per cent of the image.

An address the layout does not name is left alone, which is what lets a program keep pointing at
bitmaps and glyph strings it does not own while the blocks around it move.

## Composing a configuration

Every operation before this one edits an image in place: relocate a section, append a record,
repoint a pointer. That cannot delete, cannot compact, and grows the file on every change, because
nothing is ever laid out afresh.

Composition reads the structures this backend owns into a model with no addresses in it - the
object bodies, the section-10 contexts, the screen chain with each slot's key bindings, and the
drawing-program graph - then emits them all together at chosen addresses and fixes every reference
in one pass. What is not modelled stays exactly where it is and is referenced from the new layout:
command records and their waveforms, fonts, bitmaps, glyph strings, touch templates, and the
sections with no model at all. An authored image is still the owner's own image.

The four composed sections are emitted last and in ascending order - 9, 10, 11, then 6 - so each
one's computed range covers its own table and nothing else. Section 9 must hold every key register,
which is why the slots that point at them are emitted first and filled in afterwards; no donor
shares a register between slots, 213 and 439 slots to as many registers. A slot that binds no key
still has a register, and 50 and 62 of them are empty, so a zero-entry register (`00 00`) is a
shape the format uses rather than a mistake. Nothing lies between the registers either - a single
pad zero would read as a wide header - so the section is placed whole and any 64 KiB window
padding falls before it.

The model also holds the pictures and glyph strings those programs draw, the commands with their
own waveforms, every font with its glyphs' own bytes, and each screen's button map, so they move
with everything else and the references to them are repaired in the same pass. Sections 4, 5, 6, 7,
9, 10 and 11 are emitted from it.

Three things about the format came out of rebuilding rather than reading. A command record's five
opening bytes are carried, not rebuilt from a flag: the donors open records with 0, 1, 4, 5, 6 and
7, and one opens `2f 81`. A screen trailer's header is another key register, holding the physical
buttons that screen answers - four to six rows usually, and the whole 55-button vocabulary the
`LWJL` marker counts in a few - so the 39-row limit was a rule for recognising a page while
scanning section 9, never a rule of the format; the count is a byte, so the limit is 255. Pictures are the
one structure placed without the 64 KiB window rule: 15 to 19 of them cross a boundary in every
image and 7 to 9 are larger than the window itself, a 176x220 backdrop stored whole being 77,445
bytes. Whatever that rule protects, it is not pixel data.

The gate is a no-change re-emission: the model that goes in must be the model that comes back, with
only addresses different. A picture is compared by what it draws and a string by its glyphs, not by
where either is kept. Both donors pass, laying out 479 and 1,040 programs, 3,015 and 5,647
objects, 10 and 16 contexts, 157 and 339 screens and 213 and 439 key registers - 65,086 and 124,682
emitted bytes - with command, key, activity, device-menu and activity-menu inventories unchanged.

## The interface parts an image contains

Screens have been built here by cloning one the image already has. That cannot build a screen for
a configuration that has none, which is what generating from a project rather than from a previous
image requires. The parts a screen is made of turn out to be constant within an image, so they can
be named instead of copied.

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
at x=23 instead. A resource the image does not agree on is reported as absent rather than guessed,
and a caller is told exactly what a page still needs before it can be generated.

Menu row icons are the exception: they belong to the devices that used them, five and fifteen
distinct sets, so a generated row borrows one rather than drawing an icon the image does not have.

## The Activities menu

Both donors draw a second menu of the same shape - equally sized touch zones in reading order,
paired band for band with labels at x=63 - but its rows start an activity instead of opening a
screen: the row's object carries opcode `0x1f` with `0xff` in the operand's high byte and the
activity ordinal in the low one. That is also what keeps the two menus apart, because a device-menu
row containing it is refused.

Neither donor replicates its Activities menu: one screen holds all of it, two rows downstairs and
eight across three pages upstairs, each activity on exactly one row and every ordinal matching one
the activity index already owns. Renaming a row therefore changes only the drawn text on the page
it is found on - three changed byte ranges in either donor - and the row keeps the object that
starts the activity, so what a row does cannot move while its name does. Its labels come from the
same restricted menu font as the device rows.

### What an activity ordinal is, and why one is not reclaimed

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

That makes renumbering defensible, but it is evidence and not proof - firmware computing an index
rather than reading one would overturn it - so an activity is still deleted by taking it off the
menu and dropping its key entry, leaving its context and objects in place and named in the report,
the same treatment a removed device's commands get.

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
editable evidence only when its class-`7f` object is either a direct `{command,7d}/{device,7c}`
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

## Differential reconstruction

An imported portable command is checked by lowering it again with its measured lead-in and
comparing both carrier fields and waveform slots. The audit distinguishes byte identity from
on-air waveform identity. Native data may contain adjacent words with the same carrier level;
portable decoding coalesces them and canonical lowering emits their summed duration as one word.
That storage difference is waveform-equivalent, while any difference in the normalized signed
durations or carrier period is a mismatch.

Opcode operands are reported as possible references only when every operand for that opcode is
within the current object-table range. This is an inventory heuristic, not enough evidence to
rewrite those atoms.

Passing this validator proves that an image matches the measured arch-12 container and integrity
rules. Inventory counts prove only that these bounded native shapes can be walked. Neither proves
that Afterglow can safely modify the image or that a particular remote has accepted it.
