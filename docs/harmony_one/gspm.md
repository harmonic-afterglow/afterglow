# Harmony One GSPM configuration

Harmony One configuration payloads are indexed binary images beginning `GSPM`. They are carried
inside the same XML-header EZHex envelope as other direct Harmony remotes, but they are not ZIP
files and do not share the Harmony 900 configuration semantics.

The observations below agree across four independent Harmony One donor configurations. They are
also consistent with the arch-12 configuration base and cookie in Concordance and with the remote
validator analysis performed by RE-HARMONY.

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

The 19 present master-index pointers are unique, ascending, and point before the checksum. The end
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
section-7 font resources, section-19 touch geometry, and device-menu row ownership. Every
unmodeled native byte remains opaque and is preserved unchanged. Activities, state transitions,
and mutation/relocation remain outside the implemented ownership boundary.

The read-only inventory additionally bounds two native structures without assigning portable
meaning to them:

- section 11 begins with a `u16` count followed by that many absolute `u24` object pointers;
- an object starts with an atom count; each atom is an operand `u16` and opcode `u8`;
- a native command record is 25 bytes containing carrier period and half-period in nanoseconds, a
  self-pointer, press and optional hold/release waveform pointers, and fixed framing bytes;
- a press-waveform target begins with the little-endian word `0x7fff`, the split leading space
  used by the remote's IR representation; a hold waveform omits that lead-in and begins with a
  carrier-gated mark.

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
the declared and decoded widths and records a palette-independent shape fingerprint. It does not
assign a Unicode character from the numeric glyph code: the two broader donors declare different
slot counts and place an identical shape at different codes, disproving a single frozen cipher.

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

This broader rule finds four and ten mutually agreeing contextual replicas in the downstairs and
upstairs donors respectively. RE-HARMONY's narrower pointer-text-only search found three and nine;
the additional replica uses inline text. The upstairs set contains six section-5-backed devices
and three native-only rows whose target screens contain no indexed IR commands. Those rows are
retained separately instead of being forced into the portable IR device list.

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
