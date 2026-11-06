# The firmware's own configuration and screens

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
| 13 | one byte, `00`: no timers (see [image.md](image.md#section-13-is-the-timer-table)) |
| 14 | 65 bytes |
| 15 | `00`, then its 151-byte tail |
| 16 | 11 pointers, into section 15's tail |
| 19 | one touch template |

The two sections nothing could be generated for are answered by their counts being zero,
so their contents never have to be understood. Section 16's pointers land inside section
15's own tail at the same eleven offsets here as in every donor, and that tail differs
from the donors' in exactly three of its 151 bytes - it is a platform table with three
parameters, not a constant.

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
