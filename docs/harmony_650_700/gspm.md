# Harmony 700 GSPM configuration

The Harmony 700 and 650 are architecture 14. Their configuration payload is the same indexed
`GSPM` image family as the Harmony One's ([../harmony_one/README.md](../harmony_one/README.md)),
and almost everything that document establishes holds unchanged: the checksum and `PTYY` seal,
section 5's command index and its records, the object table, contexts, the activity engine,
fonts, key registers, the IR waveform records, and the picture and glyph codecs. This
document records only where arch 14 differs.

Measured on one Harmony 700 user configuration, two Harmony 650 user configurations (board
revisions 1.2.0 and 1.4.0), and the factory configurations (`Region_3.EZHex`) in the 650's
firmware 0.4 and the 700's firmware 2.8. The 650 and 700 agree on everything below.

## Identity

| Field | Harmony 700 | Harmony 650 |
| --- | --- | --- |
| architecture (`PROTOCOL`) | 14 | 14 |
| skin | 66 | 72 |
| flash | `0x15:0x1C` | `0x15:0x1C` |
| model name in the firmware package | `Harmony066` | `Harmony072` |

The one 700 user configuration declares board `0.0.0`.

The 665 (skin 75) and the 600 (skins 71 and 73) are the 650 under other skins: the same
firmware program and configuration format. A Polish 600 sample differs in two things a build
takes from `scaffolds/harmony-600/look.json`: grey pictures in place of the 650's colour ones,
and section 15's tail, its light levels `01 03 05 20` where a 650's are `0a 14 08 20`.

## Outer structure

| Offset | Shape | Meaning |
| ---: | --- | --- |
| `0x00` | `GSPM` | configuration cookie |
| `0x04` | `u32` | absolute address of the final `PTYY` marker |
| `0x08` | `u32` | `0x1400` in every image |
| `0x0c` | 18 x `u32` | master section index, every slot present |
| `0x5b` | `LWJL` | marker; the byte after it counts mode 0's list |
| end - 6 | 2 bytes | the two-lane XOR checksum, as on the One |
| end - 4 | `PTYY` | final marker addressed by the end vector |

Pointers are absolute addresses based at `0x030000`.

The eighteen slots are the One's sections in the same order with two left out: slots 0-7 are
the One's sections 0-7, slots 8-16 its sections 9-17, and slot 17 its section 19. The One
leaves section 8 empty and its section 18 is two bytes; arch 14 has neither. Afterglow's
arch-14 code addresses the sections by the One's numbers.

The last slot (the One's section 19) holds no touch templates - it opens with two zero
bytes where the One's opens with a template count, as the 650 and 700 have no touchscreen -
and the pictures follow. Every byte after those two decodes as a contiguous run of
pictures: 24 in the 700, 17 and 18 in the 650s.

Mode 0's list (see the One's document, "Mode 0's list follows `LWJL`") holds 162 entries in
both 650s and 163 in the 700. The 700's extra entry is event code `06`, which the One also
carries; the key codes are the same set in all three.

## Screen slots

A screen slot record is six bytes - the key register's absolute pointer, then the drawing
program's - where the One's is seven, with a touch-template byte first.

## Command objects

The object that sends a command is the One's `{command 7D}{device 7C}` pair, preceded by one
or more `{object 7F}` atoms: on arch 14 every command runs another object first. All of
section 5's commands have exactly one such object in all three user configurations.

## Drawing

The screen is 128x128. Two opcodes are added to the One's drawing language, and with them
every drawing block reachable from every screen slot and from the One's section-12 table, in
all three user configurations, decodes and re-encodes byte for byte.

| Opcode | Operands | Meaning |
| --- | --- | --- |
| `03` | `x`, `y`, two bytes, `width`, `height`, `u24` picture | a picture drawn at a declared size; the two bytes are zero in every image, and the declared size equals the picture's own |
| `13` | selector, `u16` case count, cases of `{u16 value, u24 target}`, `u16` range count | the switch with 16-bit case values; each image has one, with 451 cases and no ranges, so the shape of a range is not measured |

The One's section-12 table - its status overlays - is on arch 14 a table of thousands of
drawing programs (2,853 to 4,753), all reached through the `73` atom as on the One. Entry 0
is the one wide switch.

## Firmware-owned screens

As on the One, a configuration's first screens belong to the firmware: 49 on the 700 and 44
on the 650. Both blocks end with "Needs to be setup. Battery Charging", and the user's own
screens follow it. They are the same screens in the same order except that the 700 has five
more: four charging screens first - a battery filling - and a "battery full" screen among
the battery notices, so each later firmware screen sits five ordinals further on a 700. The
700's low-battery screen asks for the remote to be charged; the 650's does not.

The factory configuration each firmware package carries (`Region_3.EZHex`) is a raw `GSPM`
image of 7,115 bytes based at `0x020000`, with 35 text-only screens and no pictures; the
650's and the 700's have the same layout. Its screens are the tail of each user
configuration's firmware block, in the same order - "Update Successful" through "Needs to be
setup. Battery Charging" - but the user configurations add two among them, "Command
Received" and "Terminate Entry", and draw the update and learning notices with pictures
where the factory image has a single line of text.

## Text

Text is glyph codes, numbered across the whole image, as on the One. The first 57 codes are
the same in every arch-14 image measured - `H`, `y`, `/`, then the platform's characters in a
fixed order, the digits at 12 to 20 and 6 - and the household's own characters follow,
numbered as each is first used, so they differ between images. The 700's fonts are not the
One's typeface: none of their glyph shapes is one of the One's. `platform/glyph-shapes.json`
in each arch-14 scaffold holds them (`tools/arch14_glyph_shapes.py`), learned from the
firmware screens, whose words are known, and from household characters named by their
codes; with it every glyph drawn in all three user configurations reads.

## Pages

A page is four labels, one in each corner of the screen, beside the four keys that press
them: a label's lines start left of x 40 or end right of it, and sit above y 60 or below it,
between the title strip (the title at 0,2 and the page counter, `n/m`, at its right) and the
softkey at the bottom. A device's pages are one screen's slots, one slot a page. A menu's
row spans the screen: both keys of a side open it, and its label is centred across them.

| Key code | Key |
| --- | --- |
| `88`, `82`, `89`, `A2` | beside the screen: top left, top right, bottom left, bottom right |
| `99` | the centre key below the screen, under the softkey |
| `8B`, `A3` | the arrows either side of the centre key: previous and next page |
| `84`, `86`, `83` | More Activities, Off, Help |
| `81`, `85`, `87` | the activity keys; `85` is Watch TV |

The rest are the keys that send a device's commands, `0x80 | scan` with the scans in
`backends/harmony_650/keys.py`. They were named by the codes devices are sent - NEC codes of
an LG and a Vizio television, a Samsung receiver's - looked up in Logitech's database, and the
firmware's own keys by the Tutorial screens that ask for each. `9A` and `9B` are bound only
in activities' contexts, where they send the display device's DirectionUp and DirectionDown -
an LG's in the 700, a Samsung's in a 650 - as Logitech fills an activity's UpArrow and
DownArrow.

## The battery notice flag

Arch 14 keeps one state variable of its own, unnamed in section 0: property `0x31` in the
700 measured, `0x2A` and `0x2B` in the 650s, limit 1. Every battery screen the firmware owns -
on the 700 the four charging frames, Low Battery, the charge request, battery full, Insert
batteries and Unable to charge; on the 650 its four battery notices - sets it to 1 as it is
entered (a `0x06` header row, `:= 1`). On the 700 mode 0 is a charging frame, so mode 0's list
carries the same row, which is why its list has one entry more than the 650's, whose mode 0
is a setup notice. It is
cleared by the Exit key on Low Battery, together with `07 FFFC`, and by the event context's
handler for event `0x1E`, external power removed. The objects that run when the battery level
falls - the ones that enter Low Battery and the charge request - test it first and step back
(`07 FFFD`) when it is clear. It is the 700's "a battery notice is up" flag: the One's event
table has the same behaviour, going back to what was shown on `0x1E` only if the charging
screens are up. The variable's number is the configuration's to choose; what a build has to
keep is that the battery screens' rows and the objects testing it name the same one.

## IR waveforms

A command record with a hold waveform has a press waveform that begins with the One's
lead-in space; one without a hold - a press-only copy of a command, as an activity's or a
sequence's step sends it - begins at its first mark. Every record of all three user
configurations is one or the other: 49, 18 and 39 records have no hold. A Harmony 600's
sample breaks the rule: 148 of its records begin at their first mark with a hold after them,
a NEC repeat frame that several records share. The reader takes either form, and a build
always writes the lead-in.

## The USB screen's state

The USB Connected screen keeps a second variable of the platform's in the household's
numbering - `0x24` in the 700, limit 3. Any key sets it to 1 (`07 FFFF`, then the write);
its left arrow, Exit and OK keys load 0, 2 and 3 into the byte register (`1F FB0n`) and run
an object that tests the variable against it and steps it to the next value, the last of
them stepping back (`07 FFFC`). The 650 has the same, with its own number. A build carries
both platform variables - this and the battery notice flag - and numbers them itself.

## The wiring

What connects the firmware's events to a configuration is the same in every arch-14 image
but for the household's parts, and the scaffold carries it as a model
(`platform/wiring.json`, `tools/arch14_extract_assets.py`):

- **The start-up list** (section 9's leading list), eleven entries the firmware queues by
  index: enter Terminate Entry, the normal start, the start on USB, the tour's start, the
  start after an upgrade, enter the blank after Upgrade Successful, the quiet list, enter
  Ready to learn, after a code is learned, enter the blank after Command Received, the
  quiet list. Entry 1's object selects the Off context first.
- **The platform's contexts**, before the household's: the battery events `1A`-`1D`; the
  events context - USB, charging, the redraw `2D`, the paging arrows, the activity keys,
  More Activities and Off; two contexts every key passes down through, which relight the
  screen; and the low battery events `18` and `19`.
- **The timers**: the light's 10 s, on the 700 four 2 s timers cycling the charging
  frames, the screen's 20 s, a 2 s tick, 10 s, and the 3 s return to USB Connected; the
  650 has five, without the charging cycle. A smart TV's online gate is a timer of the
  household's among them.
- **The platform's variables**, numbered among the household's but written by no device:
  the battery notice flag, the USB screen's state, one wide variable of limit 65277 whose
  use is not read, and flags of limit 1, 3 and 5 - ten on the 700, nine on the 650.

The household's parts are holes in the model: the Off context, each activity's context and
the activity keys' rows, the switch on `CurrentLocation` that More Activities and the start
run - one case, 0, the Activities menu: Logitech's `CurrentLocation_1` is only ever 0, so
More Activities opens the menu with an activity running - the Help flow's per-device switches on Off's way, the Remote Assistant's screen and a
device's own variables. Danny Bloe's harmony-explorations reads the same start-up list,
timers and wiring off its own compiles (`docs/findings.md`, sections 286, 347, 357, 360).

## Switch tables

A section-15 switch table opens with `02` and counts its cases in a `u16`, where the One's
counts them in a byte: `02`, `u16` count, `{u16 value, u24 target}` cases, then a byte
counting ranges. Every table of all three user configurations has that `02` and no ranges.
Their cases run to 450, which a byte could not count.

## Delays

A device's delays are state variables the remote can change, not waits in its commands:
`PowerOnDelay_<id>_65278` and `InterDeviceDelay_<id>_65278`, with
`DefaultPowerOnDelay_<id>_255` and `DefaultInterDeviceDelay_<id>_255` beside them, `<id>`
being Logitech's id for the device. Each is in tenths of a second: a switch table on the
variable has a case for every value up to 450, whose block waits that many tenths (`7C`;
past the largest a single wait holds, an object of several). A device's power-on transition
switches on its own `PowerOnDelay`, and both its power transitions on its own
`InterDeviceDelay` (behind a test of whether another device follows); the Help flow's
Power On delay and Inter-device delay screens are what change them. A device with no power
or inputs of its own - an HDMI switch - names its delays in no transition; its delays are
the ones whose id no other device's are. In the 700 measured the delays are 0 to 280 (28 seconds), 15 - Logitech's
default 1.5 seconds - for most.

## Remote settings

MyHarmony's Remote Backlight Settings live in the wiring (Danny Bloemendaal's
harmony-explorations, `reference/remotes/harmony-650/features.md`, found it first; read
again here on all fourteen dumps). **GlowTime**, how long the screen stays lit, is the
duration in seconds of the first section-13 timer whose list opens `1F E910`: timer 1 on a
650 (20; 5 in one dump, 15 in another), timer 5 on a 700 (20; 10 in one dump). **TiltSensor**,
waking when the remote is picked up, is the `3F F101` that arms the sensor, run by the
start-up list, timer 0's list and one more; Logitech compiles none of them with it off, and
a build leaves every `3F F101` out. Every dump has it on. An import reads both into the
project's settings (`backlight_timeout`, `tilt`); a build without them keeps the donor's 20 and on.

## Remote Assistant

MyHarmony's Remote Assistant, as a 700 of Logitech's has it (700-backup screens 100 and 119;
the chain is in Danny Bloemendaal's harmony-explorations, `architectures/harmony-600-650-700/
compiler.md`, "The welcome tour and the Remote Assistant"). An activity's enter list ends,
deferred, on `1F FB00` then `[71 80vv, 7E note, 7E screen]`: the activity's own note while
variable `vv` - unnamed, 0 to 1, no transition - is 0, else its screen. The note is titled
"Remote Assistant" and says "If any devices are not setup correctly, press "Help" now.", with
"Turn off Assistant" over the left side key - which writes 1 into `vv` and enters the
activity's screen - and Exit, the centre key, entering it too; Help is the activity's own.
Only five of the fourteen dumps carry it (three 650s and two 700s):
the rest had it turned off in MyHarmony. A build makes it unless the project's settings say
`remote_assistant: false`; an import says which. The welcome tour, and the note after All
Off ("If any devices are still On"), are not built.

## The welcome tour

Ten pages Logitech's 650, 665 and 700 configurations all carry - "Welcome to your Harmony 650
remote." to "You can now enjoy your entertainment system with one-touch activity control." -
each going on with the key it names (the right arrow, Watch TV, a side key, the centre, Help,
More Activities, All Off; the left arrow back) and the last one's Exit leaving it. The
wiring's third entry list (section 8's leading list, entry 3) runs `[mark := 1, call the
tour's exit]`: the mark, a platform variable seeded 0 by every write, and in that form the
tour never shows. MyHarmony compiles it so after an account's first sync; on the first it
enters the tour's first page instead (`7E`), which only 650-a of our fourteen dumps does
(Danny Bloemendaal's harmony-explorations, finding 286). A build shows it - its own pages,
Logitech's words in our font - unless the project's settings say `welcome: never`; the app
decides "first flash only" before a write (afterglow/welcome.py): the remote's current
configuration not one of ours (`backend.afterglow_built`, our letters rather than Logitech's)
means the welcome goes on.

## Favourites

MyHarmony's favourite channels, in one tester's 650 (the only dump with any): the activity's
first page gains a "Favorite Channels" button, which enters a screen of its own titled with
the activity's name, "Commands" first (back to the activity's buttons) and the favourites
after, four a page, each its name or nothing. A favourite's key writes a channel variable -
`write 60 = n`, one value a favourite, and an object of context atoms after it - whose
section-14 transition from any value to `n` tunes: `7A number` then `1F F3tt`, the firmware's
number sender running record `tt` of section 17 on it. Channel 0 is the digit's object
itself. Section 17 is a count and a `u24` pointer per record, one per device that takes a
number, as Danny Bloemendaal's harmony-explorations lays it out (`config-format/state.md`,
"Base slot 16: the number sender"): flags, a `u24` base added to the number, the minimum
number of digits (zero-padded), the instructions sent first (+5), last (+8, a confirm) and as
a prefix (+11; flags bit 2 from 100, bit 1 from 10, else from 10000), then pointers to three
tables of ten `{u16, u8}` instructions - the first place's, the middle ones' and the last's.
The transition then writes a twin variable silently (`07 FFFF` first), which fires nothing.
That 650's Humax pads to three digits, so its channel 1 goes out 0, 0, 1 and reads back
as "001". The importer is the Harmony One's (one-explorations 5c3be6d), the same code. A build sends the digits itself instead - each followed by the
project's key delay when it has one - which needs no table and no channel variable, and a
favourite without a name is named "Channel <number>". Logos are not in the sample.

## The help flow's placeholder

Where the help flow says "The remote will try to turn your ... on", its Continue key sends a
command filed under one of the household's devices that is not that device's: a frame of
Logitech's own 32-bit protocol carrying 0 - a 4000/4500 lead, 24 bits of 400/1000, a
50,000 trail, once or three times - at 38 kHz. It is in all three user configurations,
under an HDMI switch, a Vizio and a Samsung television, and no codeset in Logitech's
database names code 0 of that protocol. An import leaves it out of the device, and says so.

## Building an image

A build (`backends/harmony_650/compose.py`, for the 650 and the 700 alike) numbers everything itself:
the firmware's screens at their ordinals from the scaffold's model, the wiring's objects,
contexts, timers, start-up list and mode 0's list with every hole filled from the project,
then the household's screens. The engine numbers the clock and the platform's properties,
then the narrow variables - the household's, then the platform's - then every wide one,
and section 14's header counts them so (`count, narrow, wide, narrow`). Section 4's head is
the firmware's map of its thirty status screens, keyed from the first of them: the screen
count less thirty. Small structures are kept inside one 64 KiB window: of the 6,062
objects and 767 drawing blocks of the 700 measured, none crosses one.

The household's part follows Logitech's. A device's power and inputs are the One's state
variables (`<Label>_Power_2`, `<Label>_Input_<n>`), whose transitions send; its command
objects wait its inter-device delay first while the sequence flag (variable `0x34` in the
700 measured) is set. An activity is a context after the platform's and Off: its enter
(event `01`) sets the flag, writes the devices' power and inputs and the activity's
number in `CurrentActivityState`, runs its start steps, clears the flag and shows the
activity's screen; event `05`, the activity picked again, re-sends its inputs; `02`
runs its stop steps. The 700 measured writes them so, with a "Starting" screen first and
the Help flow's rows (`43`, `C3`) beside them; a build draws both (see "Help" and "Help
held"). The
Activities menu holds two activities a page, each row started by both keys of its side,
its label centred - rows at y 35 and 79. The activity keys are Watch a Movie (`81`), Watch
TV (`85`) and Listen to Music (`87`): every configuration measured binds them so (a 700's
"Watch Roku" on the key its owner calls Watch a Movie, a 665's "Radio" and a Dutch 650's
"Radio FM" on `87`), each selecting its activity's context, and a key with no activity
shows "add an Activity". An import names each activity's key (`activity_button`: "Movie",
"TV", "Music") and a build binds them so; a project that names none gets its first three
activities on `81`, `85`, `87` in that order.
In the two contexts every key passes down through, the activity keys relight the screen
as every other key does; only the events context's rows are the household's.

A build names no variable it does not have. The firmware's variable store checks no bound,
so a write past the last variable lands in other memory. The wiring's start restores each
device's saved delays (`7A key`, `0F FF40`, `1F EDvv`: the accumulator into variable `vv`),
and a donor's `vv` are its own devices' delay variables: carried as numbers, they had a
built 650 write ten variables past its last at every start, and it hung at the logo and
restarted. They are holes in the wiring, which a build fills with its own devices' restore
(see "Help held").

Text is placed as Logitech's pages place it, the same on all three configurations measured:
a corner label 3 px in from the left or ending at 125 on the right; one line low in its
corner, beside its key, at y 40 above the middle and 90 below, two lines from 25 or 75 a
font's height apart; the page counter ending at 125. Corner labels and the Activities
menu's rows are set in the button font (15 px), and a label wider than 59 px goes down
through the smaller fonts of its look - 14, 13, 11, 10 - before it is cut with "..". A
name is broken where its words meet only when it does not fit on one line.

### A device's other states

Beside `<Label>_Power_2` and `<Label>_Input_<n>`, a device can have other state variables,
`<Label>_<State>_<values>`: the states Logitech's database declares for it, most often
`Screen`, `TVInput`, `InputType` and `VideoInput` (corpus_provider, `_archive_states`). A
Dutch 650's television has two: `TV_Screen_8`, each value reached from any other by its own
code (`FFFE` transitions), and `TV_TVInput_3`, stepped through by pressing TV, each pair's
transition that many presses. Its `TV_Input_10` sends nothing itself: each input writes
`Screen`, and for the first three `TVInput` too - as a write of the variable alone (`C6`)
when that is all it does, else an object of writes. An import carries them as the
project's `control_states` and `{"set", "to"}` steps, as the Harmony 900's builder already
takes them, and a build writes them back so. Power can go off in more than one code - Exit,
then PowerOff, on a Vizio and on that television - which a project says as
`power_off_steps`.

### Starting an activity

As Logitech's enter lists (harmony-explorations, `docs/config-format.md`, "The enter list in
full"): the activity's start-up screen first - "Starting <activity>" centred from y 5 in the
firmware's message font (`notice`, font 2), "Please keep the remote pointed at your system"
from y 82, every key 0x81 to 0xB6 bound to nothing - then the sequence flag, the devices'
power and inputs, the activity's number, its own steps, a call to `[3F D000, 7E screen]`,
which enters the activity's screen once the codes queued before it have gone, and the flag
cleared. All Off is the same with "Turning system off" and the Activities menu.

### The sending mark

Section 12 is the screen program table a `73` instruction runs, by the operand's low byte.
Logitech's first entry is the Help flow's delay countdown, a 451-case wide switch; the next
three are corner programs, one per background: a switch on the firmware's sending flag,
variable 17, that draws the page's own 12 by 10 patch at 114, 112 while it is 0 and the
sending mark there while it is 1 to 3, then `07 FFFA`. A device page and the Devices list
queue entry 1 (`73 0001`) after their backdrop, an activity's pages and the Activities menu
entry 2, other screens entry 3, and each such screen binds `2D` - the firmware's sending flag
changing - to the same entry in its header (`2D -> 73 n`), which redraws the corner as codes
start and stop going; without it the mark changes only when the page is drawn again. A
build numbers them the same, its entry 0 the power-on delay's countdown; the scaffold names the patches and the mark `corner/device`,
`corner/activity`, `corner/idle` and `corner/mark` by which pages queue them.

### Help

Help released (`43`) in an activity's context enters that activity's "Attempting to fix
the problem..." screen, Logitech's working picture (scaffold `page/working`) and the notice
font: lines centred at y 5 and 19, "Please keep your / remote pointed at the / system" at
82, 96 and 110. Its only row is the screen's own entry (`06`), an object that sets the
sequence flag, sends the activity's power-on commands (those with one each way) and direct
inputs again, and once they have gone (`3F D000`) shows "Did that fix the problem?". A
question (650-b screens 75 and 111) is the backdrop, the idle corner (`73`), its words in
the message font centred so the last line is at y 47, 14 apart, "No" at 5, 82 and "Yes"
ending at 123, 82 in the answer font, and "Exit Help" on the softkey. The screen's header
binds the centre key (`99`) and Help (`83`) to the activity's screen and `2D` to the corner;
its page binds No (`89`) and Yes (`A2`). No to the first question asks about each device
the activity powers - "Is the TV on?", No sends its power (a toggle too) and asks "Now is
the TV on?" until Yes, then "Did that fix the problem?" - then each input the same way
("Is the TV set to the HDMI 1 input?", No sends the input or one step of a cycle); every
Yes to a fix goes back to the activity, and Yes to a device's question goes on to the next.
An answer writes the variable it was about. Off is the same with "off" and the Activities
menu (Logitech's Off binds `43` through a switch). A build leaves Help out where there is
nothing to ask about, and lays the screens out after "Turning system off": per activity
then Off, the attempting screen, the first question and three per device or input.

### Help held

Help held (`C3`) in an activity's or Off's context runs `[07 FFFD, 7E warning]`: "Delay
Fixing" (650-b screen 49), a title strip, "You are in an / advanced delay / fixing mode. Do
you / want to continue?" centred from y 21 in the message font, No and Yes, "Exit". Its
centre key and No step back out (`07 FFFC`); Yes enters "Select device" (screen 115), the
devices four a page on Logitech's own dotted backdrop (scaffold `page/select`), each opening
its menu: "Set to default" over "Change Delay" (128), then "Power On Delay" over
"Inter-device Delay" (127), the top two keys the first row, No and Yes the second, on
`page/delays` in its own font (`delay_row`). Every one of these screens binds Help, the
activity keys and `84` to `07 FFF5`, `C3` to nothing and Off (`86`) to Off's context -
"Select device" excepted, whose Off does nothing too.

A delay screen (62, 106) edits a copy of the device's delay - `1F EF` the device's
variable, `1F ED` the copy - which a section-12 program draws, queued `73` after the title:
entry 0 a wide switch on the power-on copy, a case a tenth from "( 0 sec )" to
"( 45 sec )", centred at y 80 in the answer font; the inter-device copy's, 21 cases, after
the corners (Logitech's is entry 4). "-" and "+" are No and Yes. `7A` loads the accumulator,
`79` adds to it and `6E` takes its remainder; `70 0cvv` tests variable `vv` against the
accumulator (`c`: 1 not equal, 2 less, 3 more) and runs the next instruction only if it
holds, and test 7 takes the accumulator off the variable; `71` is the same against the byte
register (`1F FBnn`). The power-on delay's +: below 450, round the copy down to a whole
second through a scratch variable (`copy % 10` off it), add 10 and redraw (`07 FFF7`); its
-: above 10, round down, then take 10 off unless it is 10. The inter-device delay's, in
fives: + below 20, - above 0, and not below 0. Done (the centre key) copies the edit back,
saves it and returns to Change Delay; "Set to default" writes the project's delays, saves
them and says "Delay settings for ... are now set to default" (126), OK going back.

A delay is saved in the remote's own store by a switch table on its variable: a case per
value running `[7A key, 6C value]` - the inter-device delay's `value | 8000`. The start
restores each device's (the wiring's `delay-restore` hole): `7A key, 0F FF40` (`FF41`
the inter-device one) loads the saved value, `1F ED` keeps it in the scratch, and unless it
is `FEFD` - nothing saved - the same load goes into the device's variable. Logitech's keys
are its device ids; a build's are a hash of the device's id and its project delays, so a
delay set on the remote outlives a rebuild of the same household while one changed in the
project starts from the project's. A device's power-on wait is a switch on its
`PowerOnDelay_<n>_65278` over a table of its own, a case per tenth to 450, as Logitech's;
the inter-device wait was one already.

### What the wiring carries

Every instruction the scaffold carries from the donor is either a constant of the model or a
reference a build renumbers, and nothing names a donor's household. `1F`'s bands, as
harmony-explorations reads them (`docs/config-format.md`): `E8` and `FE` select and push one
of the platform's own contexts, which keep their numbers; `E9` the screen light (`E910` lit
for a while, `E900` off); `EA` and `EB` stop and start a timer by number, the platform's
timers keeping theirs; `ED` and `EE` the accumulator into a variable; `FB` a byte register;
`FF` a context. `3F` `F0`, `F1`, `F2`, `F6` and `F7` are settings flags the same on every
compile (the sound gate, the tilt sensor, the 700's boot step); `0F FF40` and `FF41` read the
remote's settings store; `07 FFxx` work the mode stack and the timers. The start's restore
of saved delays - `07 FFF3`, one list per device keyed by its id, `07 FFF2` - is the donor's
whole and is a hole. A test checks every object, screen, context, switch table, timer and
variable an image names against what it has.

### The Harmony 665

A Harmony 665 is a 650 under skin 75. Logitech's spec pages give both one model number,
N-10003, and the same hardware; only the device limit differs, 10 for the 665 and 8 for the
650, which MyHarmony enforced rather than the remote. A 665's configuration is a 650's -
the same firmware screens, wiring, pictures (pixel for pixel) and key codes - but for its
skin, 75 for 72, in its header and in section 1's third byte (the 700's is 66 there). One
profile, "Harmony 650 / 665", takes both skins; an import keeps the skin it came off in the
project's settings, and a build says it in both places.

## Not yet established

- Whether a 650 accepts a 700 configuration, or the reverse, has not been tried.
- The flash size, and so the largest safe configuration, is not measured on arch 14; the
  One's limit is applied.
