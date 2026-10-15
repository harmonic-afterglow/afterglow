# Harmony 800 `GSGD` configuration image

The Harmony 800 ("Ravenswood", USB `046d:c127`, arch `0x12`, skin `0x56`) is a touchscreen
remote with a slide-out QWERTY keyboard and a Unifying radio. Its configuration is a sibling of
the Harmony One's `GSPM` image ([gspm.md](../harmony_one/gspm.md)); everything here was read from
the 800's own firmware (0.7.1, STM32F102, dumped over SWD) and checked against the two images a
factory remote carries - `/cfg/usercfg` and `/fw/embeddedcfg`. Function names are the firmware's
addresses (`FUN_08xxxxxx`).

## Where the images live

The remote serves files over the MH protocol (Concordance's `remote_mh.cpp`). Its file table
(firmware `0x08016300`) places the two configurations on the SPI flash:

| File | SPI flash | Size | Base address |
| --- | --- | --- | --- |
| `/cfg/usercfg` | `0x050000` | `0x390000` | `0x050000` |
| `/fw/embeddedcfg` | `0x030000` | `0x10000` | `0x030000` |

Addresses inside an image are absolute (`base + offset`, `u24`). At boot `FUN_080146fc` uses the
user configuration when its checksum holds and falls back to the embedded one otherwise.

## Header and close

| Offset | Bytes | Meaning |
| --- | --- | --- |
| `0x00` | `GSGD` | magic (the One: `GSPM`) |
| `0x04` | `u32` | end vector: absolute address of the close marker |
| `0x08` | `u32` `0x1600` | constant |
| `0x0C` | 20 x `u32` | absolute section pointers, sections 0 to 19 - **all twenty present** |
| `0x5C` | 7 x `00` | zero |
| `0x63` | `CHJL` | marker (the One: `LWJL`) |
| `0x67` | `u8` | `00` in both factory images |

The image closes with a two-byte checksum and `OGSA` (the One: `PTYY`); the end vector points at
`OGSA`. The checksum is the One's: two XOR lanes seeded `0x21` and `0x43` over the bytes before
the checksum - but where the One's tools and Concordance skip an odd last byte, the 800's firmware
(`FUN_0800f144`, called from `FUN_0800efd0`) XORs it into the low lane. Logitech's images have an
even length, so the difference never shows in them; a generated image is padded with a zero to an
even length, so every reading agrees. A user configuration whose checksum fails is not used: the
remote boots its embedded one, which raises message 0, "Go to Website to update settings"
(`main()`, `FUN_0801148c`). This happened to the first generated image written to a remote.

## The Afterglow mark

Every image Afterglow builds ends its body - after the last section's contents, before the
checksum - with the project it was built from and a trailer naming it. Nothing points at
them, so the firmware never reads them; they are inside the checksummed bytes, and the end
vector alone finds them:

| Bytes | Meaning |
| --- | --- |
| `N` | the project: compact, key-sorted JSON (UTF-8), compressed with zlib |
| 16 | `AFTERGLOW-800` padded with zeros |
| `u16` | mark version, `1` |
| `u16` | zero |
| `u32` | `N` |
| `u32` | CRC-32 of the `N` bytes |
| 4 | `AGLW` |

The trailer's last byte is the one before the checksum; a zero before the project keeps the
whole of even length. Settings that only say where a build was written (`out_file`) are left
out of the project. An image without a sound mark - every configuration Logitech's software
made - is not read back; only Afterglow's own configurations are supported.

## Sections

`FUN_080147c0(n)` positions the reader at section *n*'s header pointer. What each section holds,
as the firmware reads it:

| Section | Contents | Reader |
| --- | --- | --- |
| 0 | name records (`Root`, `State`) | - |
| 1, 2, 3 | platform constants; 3 is the clock stamp | - |
| 4 | firmware message table: `u24` default mode, `u16` count, `{u8 id, u24 mode}` | `FUN_0801385c` |
| 5 | command index: device count, `u24` per device; device: `00`, `u16` count, `u24` per command (record `+11`) | `FUN_08015540` |
| 6 | screens: `u16` count, `00`, `u24` trailer per screen | `FUN_0801363c` |
| 7 | fonts: `u16` count, `u24` per font | `FUN_08013a76` |
| 8 | radio commands (empty, `00`, in both factory images) | `FUN_08010406` |
| 9 | start-up list, then the screens' key registers | `FUN_0800ba44` |
| 10 | contexts: `u8` count, `u24` per context | - |
| 11 | objects: `u16` count, `u24` per object | `FUN_08018e2c` |
| 12 | status overlays: `u16` count, `u24` each | `FUN_08013cc8` |
| 13 | timers: `u8` count | `FUN_0801697c` |
| 14 | engine records (state variables) | - |
| 15 | switch tables, then platform property tables | `FUN_0801886c` |
| 16 | `u8` count, `u24` per platform property table (into section 15's tail) | - |
| 17, 18 | `00`, `00 00` | - |
| 19 | touch templates: `u8` count, `u24` each | `FUN_0800d248` |

Section 4's opening bytes are the same bytes the One's notes read as a "key table": read as the
800 firmware reads them, they map firmware message ids (`FUN_080138bc(id)`) to screens.

## Lists

A screen's handler list, its key register and a context are lists, searched by
`FUN_08017f1c(tag)`:

- first byte `n` non-zero: `n` narrow rows `{u16 tag, instruction}`;
- `00 n`, `n` non-zero: `n` wide rows `{u8 flags, u16 tag, instruction}`;
- `00 00 n`: `n` wide rows.

An instruction is `{u16 operand, u8 opcode}`. The first row whose tag matches is queued; a wide
row whose flags have bit 0 set lets the search report the event as not handled.

Tags are `u16` (the One's are `u8`): `0xC000 | code` is a key or touch zone going down and
`0x8000 | code` the same coming up (`FUN_0800d38c`). Hard keys and touch zones share the code
space, as on the One; keyboard keys arrive as `0xC400 | code`, with `0x100`, `0x200`, `0x800` or
`0x1000` added for the keyboard's modifiers (`FUN_080120f2`). Small tags are events: `06` a mode
entered, `07` left, `2E` a page drawn, and the ones below; a context answers `01`, `02` and `05`
when it is selected, left and selected again (`FUN_0800b1b4`).

### Events

The firmware posts these through one routine (the pointer at `0x20001824`), each when a reading
changes:

| Events | Posted when | Posted by |
| --- | --- | --- |
| `20` / `21` | the battery level (0-7) went up / down, then `18`+level (`18`-`1F`) | `FUN_0800f764` |
| `24`, then `23` / `22` | external power changed: connected / removed | `FUN_0800f880` |
| `26`, then `27` / `25` / `28` / `2A` / `29` | the charger's state changed, to 0 (no external power) / 1 / 2 / 3 / 4 | `FUN_0800f816` |
| `2D`, then `2B` / `2C` | USB changed: connected / disconnected | `FUN_08018c40` |
| `17` | the remote moved | `FUN_08018788` |
| `31` | the touch controller (it wakes the remote) | `FUN_0800d724` |
| `34`, then `32` / `33` | a switch closed / opened | `FUN_080183a0` |

Logitech's image answers them in its context 1 as the One's answers the One's: `2B` beeps and
shows the USB screen, `2C` returns, `23` beeps on external power, `2A` (charger state 3) shows
the charged battery (screen 4), `29` (state 4) the charging-problem notice (screen 5); its
context 2 wakes on `31` and every key, and `07 FFFA` answers `30`.

**The One numbers its events differently** (`harmony_one/gspm.md`, "Where the events come
from"): USB is `26` / `27` / `28`, external power `1F` / `1E` / `20`, the battery's direction
`0F` / `10`. A configuration built with the One's numbers reads the 800's battery and charger
reports at boot as USB plugged in, charging started and a charging fault, and runs through
the screens those open - which the first generated image did. The backend renumbers each One
event to the 800's (`structures.EVENTS`); levels 0-5, motion, `2D`, `06` and `07` are the same
on both. The One's charger state "charging" (`24`) has no confirmed counterpart and is left
unbound.

## Instructions

Run by `FUN_0800b9fc`; opcodes below `0x80` (`FUN_0800b290`, `FUN_0800b61a`, `FUN_0800b8b0`):

| Opcode | Meaning |
| --- | --- |
| `7F` | run object *operand* (section 11) |
| `7E` | enter screen *operand* |
| `7D` | send IR: operand = device `<< 8` \| command ordinal (`FUN_0800cd38`) |
| `7C` | IR repeat: operand = device `<< 8` \| repeat count (`FUN_0800cd54`) |
| `75` | blink |
| `73` | status overlay |
| `72` | switch table (section 15) |
| `70`, `71` | compare a variable; when false the next instruction is dropped |
| `66` | radio command from section 8 |
| `1F` | `FB nn` load the byte register; `FE nn` / `FD` push / pop a key-stack entry |
| `80`+*v* | write variable *v* |

### Lights

A light is `3F` with band `C0`-`CF` (`FUN_0800b61a`): the operand's low byte holds the channel
(high nibble), the level (bits 1-3) and a flag (bit 0). Channels 0-6 are LEDs
(`FUN_080128fa`); **channel 7 is the display's backlight**, a driver of its own
(`FUN_0800b274`), which Logitech's image sets only with the flag. The One reads five bits of
channel and has its backlight on `0x11`, its keypad on `0x08`-`0x0C` and `0x10`, and eight key
zones on 0-7 - so the One's zone 7 is the 800's backlight, and the first generated images
switched the display off whenever a screen darkened that zone.

Logitech's image lights them all together, never per screen: every key and wake sets LEDs 4-6
to level 4 and LEDs 0-3 to level 1 (with the backlight), and idling darkens them all. The light
test on asdfgpio's 800 (2026-10-15) named them: **0 the left arrow, 1 the right arrow, 2 and 3
the touch areas below the display, left and right, 4 the remote's keys, 5 the keyboard, 6 the
power key**. Each is one register on a pulse-counted LED driver, so each has one colour and
only a level (`FUN_080128fa`, `FUN_080126a6`); levels 1 and 4 drive the same current.

Generated images put the backlight on 7 and light LEDs 4-6 while awake, as Logitech's image
does, and light the touch areas per screen as the One's zones: zones 0/1 on LED 0, 2/3 on
LED 1, 4/5 on LED 2 and 6/7 on LED 3, each pair the One's two colours of one light
(`lights.py`, `idle.py`). The key test still opens with the light test.

### Keys

Each front-panel key posts `0xC000 | scan` (key_test.py names what it gets); `keys.py` holds
the table from asdfgpio's 800:

| scan | key | scan | key | scan | key | scan | key |
|---|---|---|---|---|---|---|---|
| `01` | Back (bottom row) | `0A` | Play | `13` | Menu | `1C` | D-pad left |
| `02` | Record | `0B` | Page down | `14` | Info | `1D` | Channel down |
| `03` | Skip back | `0C` | Page up | `15` | Back | `1E` | DVR |
| `04` | Rewind | `0D` | D-pad down | `16` | TV | `1F` | Channel up |
| `05` | Exit | `0E` | OK | `17` | Activities | `20` | Help |
| `06` | Guide | `0F` | PIP (bottom row) | `18` | Volume up | `21` | D-pad up |
| `07` | Mute | `10` | Stop | `19` | Off | `22` | Mouse |
| `08` | Home (bottom row) | `11` | Skip forward | `1A` | Volume down | `23` | D-pad right |
| `09` | Pause | `12` | Fast forward | `1B` | 123 | | |

The project names them as every Harmony's software does; the 800's own are `TV`, `DVR`,
`Back`, `Home` and `PIP`, the names Logitech's database gives the commands for them,
and the Back key beside the D-pad is `PrevChannel`, the key the Harmony 900 prints "Return".
Page up and down are `UpArrow` and `DownArrow`, as on the 900. There are no number keys: 123
opens the keypad on screen. Mouse is kept by the remote, like Activities, Off, Help and 123:
it is for the touchpad, which Afterglow does not drive yet. The keyboard (`0xC4xx`) is not
bound yet.

## Screens

A trailer is `{u8 flag, u24 list, u16 slot count, u24 slot...}`; a slot is `{u8 template,
u24 key register, u24 drawing program}`. Entering a screen runs its list's tag `06`, posts event
`2E` and draws the page unless the trailer flag has bit 0 set.

The factory images lay each screen out contiguously - `[list][fragment][program][slot][trailer]`
- with the fragment drawing the backdrop and ending `17 00`, and the page program calling it.

## Drawing

The display is 240 x 320, RGB565. The drawing VM (`FUN_08013c1c`) takes **16-bit coordinates**
(the One's are bytes):

| Opcode | Operands | Meaning |
| --- | --- | --- |
| `01` | `x, y, w, h, colour` (`u16` each) | filled rectangle - but see below |
| `02` | `x, y` (`u16`), `u24` picture | picture |
| `03` | 6 x `u16`, `u24` picture, `u8` | clipped picture |
| `04` | `x, y` (`u16`), `u24` string | text |
| `05` | `x, y` (`u16`), codes, `00` | inline text |
| `10` | `u8` font (section 7) | select a font |
| `11` | instruction | queue an instruction |
| `12`, `13` | switch (`u8` / `u16` cases) | |
| `14`, `16`, `17` | `u24`, `u24`, - | jump, call (one level), return |
| `00` | - | end |

Text codes are 1-based glyph indexes into the current font; a code with its high bit set is two
bytes. Pictures are the One's: `{u8 mode, u16 width, u16 height}`, mode 0 raw big-endian RGB565,
mode 1 runs. A font is `{u8 height, u16 count, u24 glyph...}` and a glyph `{u8 width, runs}`.

**The rectangle does not clear the screen.** The LCD (an ILI9341-type panel on SPI1, chip
select PA4, D/C PC14) is selected by the picture routine and the start-up self-test, which
release it when they finish. The rectangle's line routine (`FUN_08010dc4`) and the command and
window routines only toggle D/C, so once a picture has been drawn a rectangle's pixels go to a
deselected panel and nothing changes. Logitech's images never use it: every screen starts with a
full-screen picture, as the One's start with their black backdrop. Generated screens do the same
with a 240 x 320 black backdrop. Found by running firmware 0.7.1 under emulation with the LCD,
flash and touch controller modelled: drawn with rectangles, each screen was drawn over the last.

## Touch

Section 19's templates are the One's: `u8` zone count, `u24` per zone; a zone is `{u16 x, u16 width,
u16 y, u16 height, u8 tag, u24 self}`. A screen slot's template byte selects one. Coordinates are
the touch controller's raw units: x about 6.65 per pixel from the left, y inverted at about 6.1
per pixel, raw 2040 at the top (calibrated from the factory images' zones against what they
draw). The first zone containing the touch wins (`FUN_0800d248`); its tag is posted as a key.

## The embedded image

`/fw/embeddedcfg` is the 800's minimal configuration, the counterpart of the One's
`Region_3.EZHex`: thirty text screens (the firmware's messages), one font, one context, five
objects, no devices. Its start-up object pushes context 0, enters screen 0 ("Go to Website to
update settings") and enters screen 28 ("USB CONNECTED") when variable `0x10` (USB) is set.
