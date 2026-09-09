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
lead-in and contains one hold-phase transmission followed by the same short terminator. The two
consecutive final spaces let the native reader find the end of the waveform.

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
class u8}`. Class `0x7f` selects a section-11 object. A command binding resolves either directly or
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

Section 4 turned out to be a second index of the same commands section 5 reaches. It opens with 126
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

Pixels are RGB565, and the two encodings disagree about their byte order. Mode 0 stores every pixel
of every row after a four-byte header, little-endian. Mode 1 runs them big-endian - a byte with the
high bit set leaves that many pixels untouched, a byte without it introduces that many stored
pixels, `80` closes a row and `00` closes the picture - which is the same run encoding, and the
same byte order, that a font glyph uses. The last row carries no separator, because the picture's
terminator closes it. There is no alpha channel: a run simply declines to write, and whatever was
on the screen shows through.

The images are the only authority on that split, and it is measurable. Taking the mean difference
between horizontally neighbouring pixels, a 62x42 panel stored whole reads at 14.4; the six
run-encoded panels of the same size in the same image read at 48 to 53 little-endian and 17 to 27
big-endian. Across the two broader donors, run-encoded pictures average 33 read little-endian
against 14 to 15 read big-endian, where stored-whole pictures average 7.8.

The encoder is the reader's exact inverse. Every picture the four donors draw rebuilds its own
bytes: 294 pictures, 268 stored whole and 26 run-encoded.

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
still has a register, and 50 and 62 of them are empty, so a zero-entry register is a shape the
format uses rather than a mistake.

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
image and 7 to 9 are larger than the window itself, a 176x220 backdrop stored whole being 77,444
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
