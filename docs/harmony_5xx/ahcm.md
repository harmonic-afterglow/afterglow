# Harmony 5xx `AHCM` configuration (architecture 9)

The Harmony 510, 515, 520, 522, 525, 550, 552, 555 and the Harmony for Xbox 360 are one
architecture, 9. This document says where its configuration image differs from the arch-14
image the 650 and 700 use ([gspm.md](../harmony_650_700/gspm.md)), which is its descendant:
everything not named here reads as it does there.

Read from 21 configurations - 510 x3, 515 x2, 520, 525 x3, 550 x2, 555 x9 and an Xbox 360 -
and checked against two independent readers: trelowney's
[harmony-decompiler](https://github.com/trelowney/harmony-decompiler) (GPL-3.0) and Danny
Bloemendaal's [harmony-explorations](https://github.com/dannybloe/harmony-explorations) (MIT),
whose findings this document uses with attribution where it says so.

## Identity

| Field | Value |
|---|---|
| architecture (`PROTOCOL`) | 9 |
| flash | `0xFF:0x12`, a 512 KiB serial part |
| skins | 18 (520), 22 (525), 36 (Xbox 360), 41 (550), 46 (522), 48 (555), 51 (552), 67 (515), 68 (510) |
| section 1 | `09 09 <skin> 0d 00 00 00` |

## Outer structure

| Offset | Shape | Meaning |
| ---: | --- | --- |
| `0x00` | `AHCM` | configuration cookie |
| `0x04` | `u32` | absolute address of the final `MCHA` marker |
| `0x08` | `u32` | `0x1400`: the byte at `0x09` counts the section table's items, 20 |
| `0x0b` | 20 x `{u8 spare; u24 address}` | section table: the One's sections 0-7, 9-17 and 19, then two empty items |
| `0x5b` | `CMAH` | marker; **no key table follows it**, the byte after it is 0 |
| end - 6 | 2 bytes | the two-lane XOR checksum seeded `21 43`, as arch 14 |
| end - 4 | `MCHA` | final marker addressed by the end vector |

Pointers are absolute addresses based at `0x020000`. On the remote the configuration is read
and written at `0x820000`; its region ends where the log area starts, `0x870000`
(`0x070000` in the image's own addresses), so an image is at most 320 KiB. Every spare byte
is zero in every configuration; a reader checks it rather than reading the item as a `u32`.

Section 2 is the log area's descriptor: capacity 8192, start `0x070000`, limit `0x080000`,
a stride of 8 (Danny Bloemendaal, `reference/config-format/state.md`).

The sections' structures - the name tree, the command index, objects, contexts, screens,
fonts, state variables - read with the arch-14 readers unchanged: on all 21 configurations
the section-11 object count equals the decompiler's action-list count and the section-6
screen count its mode count.

## Glyphs

A glyph is two bits a pixel, 1 the ink and 2 the paper, in rows of runs:

```
+0x00  u8   width in pixels
       per row, until a 0x00 stands where a row's leader would:
         u8   0x20 | n        n: the bytes of commands this row takes
         n bytes of commands, each  kind << 4 | (count - 1):
           0x5  count literal pixels, two bits each, big endian, ceil(2 * count / 8) bytes follow
           0x6  a run of count paper pixels
           0xA  a run of count ink pixels
           0x8  a run of count pixels of value 0
```

Value 0 is a second ink. Of the 22 configurations read, Logitech's in-store demonstration
for the 550 (a "demo loop", no devices or activities) alone draws with it: 25 glyphs of
its large faces use literal 0s and kind 8 runs where every other glyph uses 1 and kind
0xA. On the monochrome panel it is read as ink. Value 3 is seen nowhere.

Every row draws exactly the declared width. Logitech's compiler chose the commands by one
rule: a run of 5 or more pixels of one colour is a run command (16 pixels at most each),
and the pixels between such runs are literals, 16 at most each - except that a literal all
of one colour is written as a run. That rule gives back the bytes of all 3,464 glyphs
Logitech wrote in the 21 configurations. Read this way, all 3,465 glyphs of the 21
configurations decode to the decompiler's pixels. The family draws two typefaces: one 11 rows
high (520, 525, 550, 555, Xbox 360) and one 12 rows high (510, 515), which share no glyph.
Codes are numbered per configuration, so a character is read by its shape
(`scaffolds/harmony-555/platform/glyph-shapes.json`).

## Switch tables

Section 15's tables, which a `0x72` instruction numbers, count their cases in a byte, where
arch 14 counts them in a `u16`:

```
02                     (every table measured)
u8   case count
     {u16 value, u24 block} per case
u8   range count
```

A table with no cases is `02 00 00`. The first case's value is always 0, so a reader that
takes the count as a `u16` reads the right number and then every case one byte early.

## Pointers

Every pointer is a `u24` absolute address. They are held by: the section table; the counted
indexes of sections 5, 6, 7, 10, 11, 12, 13, 14 (after its 6-byte header), 15 and 16; each
screen record (its key list and its pages) and page (key list and program); a drawing
program's `text`, picture and jump instructions and its switches' cases; a font's glyphs; an
infrared record (its own address + 4 at +12, and each body), a body (its symbol table) and a
symbol table (its symbols); and a switch table's cases. Walking those finds every pointer
harmony-decompiler's census finds on the 15 configurations it reads, and in the one it wrote itself one more; bytes
inserted between structures, with each of them moved, leave all 21 configurations reading
the same.

## Pictures

A picture is one bit a pixel, 1 the ink:

```
+0x00  u8   kind, 2
+0x01  u16  width
+0x03  u16  height
+0x05       height rows of ceil(width / 8) bytes, most significant bit leftmost
```

All 95 pictures the 21 configurations draw read and write back this way. Section 19 begins
`00 00` and holds them, the first a 96 x 64 backdrop (harmony-decompiler, `parse_bitmap`).

## Infrared

A command record has the arch-14 header - carrier period and half period, a class byte, a
pointer to itself, one or two pointer groups of press, hold and release - with class 5, not
1. Each pointer names a body that spells the code from a shared dictionary of pulse blocks
(Danny Bloemendaal, `reference/config-format/infrared-records.md`, "Class 5"):

```
body:    u24 table      the symbol table's address
         u16 n          bytes of index stream
         u8  index[n]   into that table
table:   u8  count
         u24 symbol[count]
symbol:  u16 count
         u16 pulse[count]    bit 15 a mark, bits 14-0 microseconds
         u16 0x0000
```

The table's count is its size modulo 256. An Xbox 360's factory demo configuration holds a
table of 287 symbols with the count 31, and its commands name symbols up to 255; an index
is one byte, so a reader takes one past the count from a table that wrapped. Its commands
each end in a symbol of their own, a one-microsecond space, and past 255 those wrap too:
the commands that land on another one-microsecond space play as written, but one lands on
a pulse block, ends in a mark and does not decode (93 commands, 92 read).

A body spelled out is the arch-14 waveform word stream - silence before a press, its frames,
the closing gap and its one-microsecond end - and reads with the arch-14 decoders. Bodies,
tables and symbols are shared between records.

On a 5xx a hold or a release may begin with silence: the gap before each repeat, or before
the release frame. Two Logitech-built 555s carry 60 such codes, for an XMP-style set-top box
(210 us marks). An import moves that gap to the end of what precedes it, the press and each
repeat, so press to repeat and repeat to repeat keep their timing.

Section 5 counts the devices and points at each one's sub-table, `00, u16 n`, then the
address of each command record plus 11, in command order. Unlike arch 14, section 4 is only
its 125-byte head: there is no flat list of every record after it, and the symbols follow.

Logitech's symbols are mark-led chunks of a waveform: a mark and the spaces after it, a
leading run of silence a symbol of its own, each distinct chunk once per table. This
backend writes the same: one dictionary per device, a second table once a first holds 255
symbols. A symbol must stay under the firmware's pulse queue of 127 words; a 39-command
device harmony-decompiler wrote with a whole waveform a symbol (69 to 154 words) sent
nothing (its FORMAT.md, 5af).

Of the 6,685 commands in the 21 configurations, every one in a Logitech-built configuration
decodes. The 39 that do not are a device harmony-decompiler wrote into a 525 itself, whose
symbols carry a zero-length word.

## Names

The name table (section 0) names each state variable `<device>_<state>_<values>`, as on arch
14, with a space written as `_`. A letter beyond ASCII is stored in two bytes, little endian,
beside one-byte ASCII: Cyrillic "ТВ" is `22 04 12 04` and "Мини-система (DVD, CD, радио)"
keeps its brackets, commas and Latin letters in one byte each. A name has no character
below `0x20`, so a byte there is the high half of the letter before it. One configuration
has such names, a Russian 550.

## Pages

The screen is 96 x 64 and a page is drawn in eight bands of 8 rows. Each band selects its
row, copies the backdrop's row into it and draws what crosses the band:

```
16 <row>                          select display row 0-7
03 00 <8*row> 00 <8*row> 60 08 <u24 picture>    copy that row of the backdrop
...                               text and pictures
17                                transfer the row to the display
```

Opcode `0x16` takes one byte and `0x17` none here; on arch 14 they are a call with a `u24`
target and its return. A line of text that two bands cross is drawn in each.

On a page the title sits on the top row (y 0), centred, over a one-row line at y 12 (a
96 x 1 picture). Each of the four soft keys labels its corner: lines at y 13 and 24 above,
35 and 46 below, left-aligned at x 0 on the left and right-aligned on the right. The bottom
row (y 56) holds the "n OF m" counter, in a font eight rows high where the others are
eleven. A page's backdrop has a dotted line across row 36, every third pixel, broken by a
two-pixel mark at x 47 and 48 on rows 35 to 37, only on a page whose bottom row has a
label: one of two buttons or fewer draws on the platform's blank backdrop, with the
title's underline alone - 368 of the 381 such pages in the 25 configurations, the others
later pages of a screen of several. The Devices list and the Activities menu
give one row to each key, the same four corners, their title on the left.

A label too wide for one line is broken in two with the first line as long as fits: at
a space, after a word's hyphen ("AUX-" over "Eingang", "InputBlu-" over "ray"), or where
a capital starts a word in a command's name ("Channel" over "Select"); a second line
still too wide is cut with "..". Help's question fills a line up to a word's hyphen the
same way ("Now is the BD-" over "Panasonic off?"). A build draws in Galmuri, whose
letters are narrower than Logitech's font, so the same rule fits more on a line than
Logitech's did and its lines break in other places; the rule is Logitech's, the widths
are the font's. Of the 242 labels in the 20 configurations whose break can be told, the
longest first line explains more than the break nearest the middle does.

A glyph of the eleven-row fonts has two rows above the capitals, seven of capitals and two
of descenders; text is drawn from its top row, so a line at y 13 has its capitals on rows
15 to 21.

A device's screen lists every command key in the order the idle key set does: the bound
ones run the command's object, the others `00 0000`, nothing, so a key never falls through
to an activity's binding. Its pages bind the four soft keys to the commands their corners
name. The Devices list's corner runs `[0x7E <device's screen>, flag := 1]`, the flag being
the variable the Devices key's own object sets.

## Keys

A key binds as event `0x80 | scan` (press) or `0x40 | scan` (release), the scan code being
`group * 8 + column`; no scan is a multiple of 8. The keys the firmware's flow owns are on
the same scans on every model:

| Scan | Key | Evidence |
|---:|---|---|
| 39, 38 | soft keys, top left and top right | the Devices list's rows (harmony-decompiler, FORMAT 5ae); Danny Bloemendaal |
| 31, 30 | soft keys, bottom left and bottom right | same |
| 22, 23 | page forward, page back | the only page-turn actions (`0x0F`, operand low byte `0xA1`/`0xA0`), at the bottom of every model's context stack |
| 46 | Help | enters each activity's Help screens |
| 47 | Devices | the Devices / Activities toggle |
| 54 | Off | selects the idle key set, whose start is the stop sequence |
| 55 | Activities | the Activities menu |

A command key's scan depends on the model: the 550 and 555 bind the same scans under
different labels. What a scan is, was measured by what Logitech's compiler put on it: each
device page binds its commands to keys, and the IR archive's reverse index
([harmony-ir-archive](https://github.com/harmonic-afterglow/harmony-ir-archive)) names each
command by its code. On the 21 configurations:

- **525, 520:** as harmony-decompiler's presses on a real 525 (`compose525.KEYS`); the 520
  binds none of the colour keys (27, 33, 34, 35).
- **510, 515:** the 525's, with 21 sending Menu and 28 Guide, the other way round.
- **555:** the 525's, with the layout switch (`0x7E`) on 36 and 37 (Picture, Sound), Mute on
  61 (25 devices) and Prev on 58 (16 devices, ChannelPrev or Return). Clear, left of 0, is
  19: Logitech binds whatever a device has there (Subtitle, "-", Exit), so only the remote
  could say. A key test on a real 555 (every key showing its own scan) confirmed Sound 37,
  Picture 36, Mute 61, Prev 58, Clear 19, Enter 25 and the soft keys 39/38/31/30.
- **550:** the 555's grid, the layout switch on 27 and 35; A on 34, B on 33, page up on 36
  (PageUp, PresetNext, ChapterNext) and page down on 37 (PageDown, PresetPrev, ChapterPrev).
- **Harmony for Xbox 360:** A on 60 and B on 20: its one configuration's DVD player names
  its colour commands A to D, and binds A and B there while its screen offers C and D.
  Clear is 27 and Display 35. Its face is the 525/555 grid relabelled, and those four
  sit where the grid puts them (B where the 555 has Info, the bottom row where it has
  its colour keys), so the rest are taken from their places: Y 21 (the 555's Guide;
  the Xbox prints Guide under Y), X 59 (the scan beside A's 60), Back 37 and Info 36
  (the 555's Sound and Picture bar), title 34 and enter 33, Mute 61 and Prev 58, * 19
  and # 25. A key test on a real Xbox 360 confirmed every one, and 42 is its Glow key.

Each model's profile holds its own table (`vocabulary.hard_key_scans`).

## Activities

Measured on Logitech's empty 555 and its 4-device household 555, and as harmony-decompiler
found them on a 525 (its FORMAT.md, 5ae to 5am).

An activity is a context of section 10, a key set. The Activities menu's corners select it
(`1F FFnn`, with the device flag set to 0), and the firmware then raises event `0x01` in it,
its start; picked again while it runs, event `0x05`; left for another or for Off, event
`0x02`. Off (`1F FFnn` in the global context) selects the idle context, whose start is the
stop.

A start is one object: the "Starting" screen; the power variables of the devices it uses
set to 1; an object of its enter steps - input variables set and commands sent, in the
order the activity has them; the power variables of the others set to 0;
`CurrentActivityState` set to the activity's number; then a chain - a pause (`3F D000`),
the byte register cleared (`1F FB00`), and `71 8008, 7E <battery warning>, 7E <activity's
screen>`, which shows "Replace the batteries" first when the battery variable says so. Each
chain has its own copy of the battery warning, its keys leading on to where the chain was
going. Picked again, an activity runs its enter steps again and ends in the same check
without the pause. A last Play or Pause, the step that starts a film, is not in what runs
again: in the six such activities of the household 555s, 510s and others measured, picked
again leaves out that step alone.

Off ends the same way. Its start shows "Stopping Activity", sets the state to idle, runs
the chain and switches everything off; pressed again, it runs the chain without the pause.
In the fourteen later households (525s, 555s, 510s) the chain's battery check ends in the
location's switch to the Activities menu (`71 8008, 7E <its battery warning>, 72 <menu>`),
the warning's keys going there too, and the start-up list's idle entry opens the same menu.
Logitech's empty 555 - and the decompiler-composed images and two early households, seven
in all - goes on from the check into the welcome tour instead: `1F FB01`, then
`71 84vv, 7E <"Welcome to your remote.">`, a test of an unnamed 0-to-3 variable against the
byte register, which shows the welcome until the tour is done. A build with activities ends
Off and start-up in the menu as the later households do; one remote showed the welcome
screen after every Off before it did.

In the household configurations, the stop (and Off pressed again) also looks up
`CurrentLocation` in the menu's switch table, so once everything is off the Activities
menu shows; the empty 555 has no activities and leaves that out.

A command object is `7D command, 7C (device << 8) | count`. A code with a hold phase is
sent with a count of 1, or more for a send held a while (a held send). A code with no hold
phase is sent with a count of its own wherever it is sent: 0 for an RC6 press that already
holds three frames, 3 for a one-frame NEC press in the household 555. What the count does
for such a code is not settled, so it is preserved as found.

A device's power is a variable limited to 1 whose transitions send: 0 to 1 its on code and
its delay (`7C (device << 8) | tenths`, at most 100 tenths an instruction), 1 to 0 its off
code. An input is a variable whose transitions run from any value (`0xFFFE`) to each value,
so writing the value already set sends it again. The name table calls them
`<Device>_Power_2` and `<Device>_Input_<n>`. They stand before the terminator, the one wide
variable that ends section 14.

`CurrentActivityState` counts the activities from 0; its idle value, its initial value and
its limit are the number of activities, and the name table calls it
`CurrentActivityState_0_<n + 1>`. The switch tables that answer by it - looked up as `72
(table << 8) | variable` - give each activity's screen, its key set (`1F FFnn`) and the
Devices screen its Devices key opens; those that answer by `CurrentLocation`, which has one
value, give the menu, the idle value to set and the all-off list, which sets every device's
power to 0.

## Help

Help in an activity's key set opens a tree of Yes/No screens Logitech wrote for that
activity; Yes is the bottom-left soft key (`0x9F`), No the bottom-right (`0x9E`), and Help
on any of them returns to the activity's screen. Its first screen, shown (event `0x06`),
sends the inputs again, and the power codes - never a power toggle, which would switch
the device off (in all ten household configurations measured) - and asks "Did that fix
the problem?". No walks the devices it switches on - "Is the TV on?" - then the inputs it
sets - "Is the Amplifier set to the HDMI 2 input?" - asking of an input that sets a
device's other state about that state - "Is the TV Screen set to HDMI2?" - and Yes goes
on to the next. No sends that one code again and asks "Now is the TV on?", whose Yes asks
"Did that fix the problem?" again and whose No sends it once more and asks from a copy of
the first question, whose Yes asks whether that fixed it. Yes on "Did that fix the
problem?" returns to the activity; No goes on to the next question. Each screen is a copy
of the platform's Yes/No page.

The names in the questions - "CBL/SAT", "My TV", "HDMI2", "Antenna" - are Logitech's
names for the inputs and states, which a configuration keeps nowhere else: the commands
that select them are InputCbl/Sat, MyTV and InputHdmi2.

Once everything is off, Help in the idle key set opens the same tree over the devices Off
switches off: shown, it sends their off codes again (not a toggle's) and asks "Did that
fix the problem?"; No asks "Is the TV off?" of each, and Yes and Help go back to the
Activities menu, looked up by `CurrentLocation`. The empty 555 answers Help there with
"Nothing to do".

## Sound and Picture

The 555's Sound and Picture keys (scans 37 and 36; 27 and 35 on the 550, by its profile's
`vocabulary.layout_key_scans`) switch an activity's or a device's screen to another
layout: a screen of its own whose key list binds what that layout's keys send, and the
same key back.

**An activity's layouts.** Logitech's activity screen binds each key as a `7E` row to a
screen of the activity's own, titled "Watch TV (Sound)", whose key list binds only the
keys the layout changes; every other key falls through to the activity's key set. Measured
over the eleven household 555 and 550 configurations (55 activity layouts):

- Sound is the activity's audio device (its amplifier, else the TV) and binds Volume up,
  down and Mute (31 of 31); when that device is the TV too, also its direction pad, OK,
  Menu and Exit (5 of 5). Picture is the TV or projector, never the source box, and binds
  the direction pad, OK, Exit, Info and Guide (24 of 24). An activity with no screen
  (radio, music) has no Picture layout.
- A layout's page holds a few buttons of its device: "Effect", "Settings" on Sound;
  "List", the colour keys, "Home" on Picture.
- Owners changed these: one household rebinds its receiver's sound modes onto the colour
  keys of every Sound layout.

A project says the same in `activity["layouts"]` (src/afterglow/activity_layouts.py),
only where it differs from those defaults, and a build draws one screen per activity and
layout as Logitech's do. An import reads the screens the activity's layout keys open,
straight (Logitech's) or through a switch table on `CurrentActivityState`; a Picture
layout names the activity's display, which a 5xx import cannot tell by device type.

**A device's layouts.** On a device's own screen, Logitech binds Sound and Picture as `7E`
rows to that device's "Device (Sound)" and "Device (Picture)" screens, separate from the
ones an activity shows; each layout key goes straight back to the device's screen. Which
devices have which layout follows the device's category: in the households, an amplifier
or receiver has Sound only, a TV, disc player, console or PC both, a set-top box Sound
only (the 688 gives it Picture only), and a streamer or climate device neither. A build
gives each device the layouts its type calls for, or the project's `device["layouts"]`,
each keeping the device's keys. Their screens show the device's sound or picture
settings as buttons, most often none: Logitech's PVR (Sound) and TV (Picture) are empty,
a DVD player's Sound shows one button. A build shows what
`activity_layouts.device_layout` picks, and draws each screen of its own: none of the ten
households measured shares a page drawing or key register between screens.

## Backlight

Section 13 holds five timers on every household, in no fixed order; what each does is read
from the calls its object makes (`graft.timer_role`). The backlight's turns the light off
(`1F E900`) and arms no motion sensor: its duration is how long the screen stays lit, the
owner's one remote setting - 5, 10, 15 or 20 seconds on the Grande and Decaf households, 10
on all five Minis. A build writes the project's `backlight_timeout` there.

The `1F E910` timer the 650 reads its glow time from is a 1-second timer here, the one that
stops another. There is no tilt setting: a 5xx lights with the Glow key, not when picked
up, and its `3F F101` sits in the two-hour deep-sleep timer (on the Minis, the 20-second
sleep timer), which lets motion wake it (the 525's manual, as Danny Bloemendaal's
harmony-explorations quotes it). No Logitech software offered to turn it off.

## Favourites

No 5xx has favourite channels: Logitech's model table gives every 5xx skin none
(harmony-explorations, `reference/remotes/harmony-525/features.md`), and no household
holds one. A button that dials digits is an activity's on-screen button like any other,
and an import keeps it as one; a project's favourites, moved from another remote, become
buttons after the activity's own, named by station or number, without their logos.

## Other models' platforms

Only the 555's empty configuration survives. Walked side by side with it from the
platform's roots - contexts 0 to 3, the idle context the Off key selects, firmware screens
0 to 40, the start-up list and the timers - the households of the 525 (two, one Swedish),
the 520, the 550 (two, one Russian) and the Harmony for Xbox 360 hold the same platform:
the same firmware screens (their words translated in the Swedish and Russian ones), the same
wiring, sections 2 and 17, the head of section 4 and the tail of section 15. They differ in:

- the skin in section 1;
- the keys the whole-keypad key lists name (the idle key set, "Stopping Activity", the
  USB screen): the 525 has no scans 58 and 61, the 520 neither those nor the colour keys
  27, 33, 34 and 35, the Harmony for Xbox 360 has 59 and 60 besides, the 550 the 555's;
- the menu's title, "Choose an Activity" on all but the 555, whose "Choose an activi.." is
  lower case;
- the order of the five timers, whose `1F EAnn`/`1F EBnn` start and stop timer nn, and the
  backlight timer's length, which households set differently (20, 15, 10 and 5 measured).

What a household itself changes in the platform is the same in the seven 555 households
with activities, compared with references translated and timers paired by what they do
(`scaffolds/harmony-555/platform/household.json`): the idle key set, the start-up object,
the idle start and re-pick, the battery warnings' chains and the objects opening the menu
and the Devices screen - ten parts. A 555 household with no activity changes none.

The 515 and 510 (skins 67 and 68, one remote in two colours) run firmware 3.4, where the
others run 3.0. Their five households, walked the same way, hold the 555's platform in every
other part and differ in the same parts, all five alike:

- the global key set: an object for every key - `0F FF60` then an object restarting the
  sleep timer (`1F EAnn, 1F EBnn`) - where the 555 runs one object for all of them, which
  first calls `1F FB01` and tests a variable;
- the firmware keys' objects (the soft keys, Help, Devices, Off, Activities), the objects
  behind keys `0x17` and `0x27`, and one in the start-up list's chain, one atom shorter;
- the backlight timer, which restarts the sleep timer too, and the sleep timer: 20
  seconds and a test of variable 11, where the 555's is two hours;
- no scans 58 and 61.

So their platform is the 555's with those parts grafted in from their households
(`graft.py`): a part is taken when, its references translated into the platform's numbers,
it is not the platform's, never from the ten a household changes. An empty project built on
it differs from each of the five households only in those ten. Their typeface, twelve rows
high, does not matter to a build, which draws its own.
