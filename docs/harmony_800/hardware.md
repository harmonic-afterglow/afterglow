# Lights, keys and battery

## Lights

A light is `3F` with band `C0`-`CF` (`FUN_0800b61a`): the operand's low byte holds the channel
(high nibble), the level (bits 1-3) and a flag (bit 0). Channels 0-6 are LEDs
(`FUN_080128fa`); **channel 7 is the display's backlight**, a driver of its own
(`FUN_0800b274`, then `FUN_0800e770`). Its levels are not all brightnesses: 1-5 wake the panel
(`FUN_0800e614`) and set a brightness, 0 darkens it and puts the panel to sleep (Display Off,
Sleep In), and **6 and 7 set the display's orientation** (`0x36`, portrait 240x320 and
landscape). Logitech's image lights the screen at 4 and dims through 3 and 1. The One's
screen level, 6, therefore woke the backlight's LEDs but left the panel asleep: builds map it
to 4 (`lights.backlight_level`). The One reads five bits of
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

## Keys

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

## Battery levels

The firmware's battery level (variable 9, 0-7) is the battery's voltage looked up in two of
section 16's property tables: table 6 on battery, table 7 on the cradle (`FUN_0800f398`, which
reads them through `FUN_080149d4`). Each holds sixteen `u16` millivolt values, eight
(lower, upper) pairs: above a pair's upper value the level passes it, between the two it stays
where it was. The voltage is the ADC's reading times a factor from `/sys/battery`
(`FUN_0800f238`, `FUN_0800f63e`); on a unit whose record is blank (0xFF) the firmware uses
1 + 0x9C80/65536, the nominal 3.3 V reference over a halving divider. Tables missing from the
configuration fall back to a copy in the firmware.

The factory configuration's tables, and the firmware's copy, are one evenly spaced table for
both: 3.70 V to 4.20 V, full above 4.20 V. A charged battery settles below that (tester's
unit: 4.13 V asleep, 3.96 V with the screen on), so the remote never shows full, and level 2 -
where the configuration warns of a low battery - begins near half charge. Afterglow writes the
Harmony One's tables instead, Logitech's curve for the same kind of cell: on battery
3.00-4.05 V, on the cradle full above 4.17 V. The level itself was measured correct: the
tester's 4.13 V read as level 6, as the factory table says.

## Settings a build carries

The 800 has no settings store a configuration tool writes, so a project's choices are built
into the image, as on the Harmony One ([idle.md](../harmony_one/idle.md),
[options.md](../harmony_one/options.md)):

- **How long the screen stays lit** (`backlight_timeout`, 1 to 300 seconds, 10 by default) is
  the idle layer's off timer, which darkens the backlight and every LED. Danny Bloe's
  harmony-explorations (MIT) measured a One kept lit a minute with 60; under emulation of
  firmware 0.7.1 a build at 15 turned the backlight off between 12 and 16 seconds after the
  last touch, where 10 would have before 12.
- **A 24-hour clock** (`time_format`, `Military`) draws the status bar's hour 00 to 23 and
  gives Date and Time an Hour picker of 00:00 to 23:00 whose minute sets the clock, with no
  Time of Day picker - the clock of Logitech's European One, as harmony-explorations reads
  it. Under emulation the picker opened on the current hour and set the time it was given.
