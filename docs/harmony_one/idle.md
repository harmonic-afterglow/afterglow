# The idle layer: key lights, events, start-up and charging

**The keypad lights only when the configuration lights it.** The factory image (`Region_3`)
has no light instruction at all, and generated images had none either, so testers saw the
screen work and the keys stay dark. Opcode `0x3F` band `0xC0` drives one light channel:
channel `(operand >> 4) & 0x1F`, level `(operand >> 1) & 7`, bit 0 a flag (set only on the
screen backlight when the off timer is armed). The 800's handler passes `low >> 4`, but the One's
donors use both `0xC0xx` and `0xC1xx` in the same sequence, so the high bit is part of the
channel. Upstairs uses 15 channels:

| channel | what upstairs does with it |
|---|---|
| `0x11` | level 6 on every wake, 0 when the off timer fires: the screen backlight |
| `0x08`-`0x0C`, `0x10` | level 1 on every wake, 0 when the timer fires: the keypad itself |
| `0x00`-`0x07` | zones a screen lights on entry and clears on leaving, level 1 |

Which keys a zone lights is not known yet; the screens that light them are, the same in
all three household donors (every screen's enter handler, `one-tools`):

| screen (upstairs) | zones |
|---|---|
| Activities (197) | 1 3 5 7 |
| Options (276) | 1 3 5 |
| Date and Time (176), Screen Sensitivity (104) | 5 |
| the device list (72) | 0 2 4 |
| a device's commands, one page (88) | 4 6 |
| a device's commands, several pages (97) | 0 2 4 6 |
| an activity's screen, one page (153) | 7 |
| an activity's screen, several pages (230) | 1 3 7 |

So the arrows light only where there are pages to turn, and a softkey's bar only where the
screen has that softkey. A first reading of this table swapped the two command rows, and
generated images lit the arrows on single pages until the three donors were tabulated.

Zones {0, 2} and {1, 3} never light together: each guards the other's flag.

**Each zone has a flag**, a configuration variable (upstairs packs zones 1 and 3 into one
three-valued variable, 0 and 2 into another, and 4 to 7 into one each). A screen's enter
handler (`0x06`) lights its zones and sets their flags; its leave handler (`0x07`) turns them
off and clears them. Start-up clears every flag.

**Every key wakes the keypad.** A context (upstairs' 4) holds a row for each of the 52
physical keys, every row flags bit 0 - run it, then keep looking - so the key goes on down
the stack to the screen it was meant for. Both donors add two codes below the keys: `0x17`,
which runs `0F FFE1` with the byte register at 1 and then 0, `0F FFE3` twice, the wake and
`3F F101`, and `0x30`, which runs the wake alone. A first generated machine left both out,
and a tester's remote woke on its keys but not when picked up, which makes `0x17` the
firmware's motion event. Each key row runs the wake:

1. stop the off timer (2); screen backlight to 6; keypad channels to 1;
2. each zone whose flag is set to 1;
3. arm: stop the off timer; if platform variable 17 is not 0, screen backlight to 6 with bit 0
   set and start the off timer; start the poll timer (13), whose action is this step again.

The off timer (duration 10) turns every channel to 0 and writes `0x3F F101`. Upstairs wraps
the wake in tests of platform variables 13, 16 and 9; run under every combination of their
values (`one-tools/effects.py`), the tests only change how many times the same writes repeat,
never the end state, so a generated wake does not need them.

**The platform variables are the firmware's.** No configuration writes 0-17; the factory
image declares their ranges. 0-6 count the clock (seconds and minutes to 59, hours to 23,
days to 30, weekday to 6, months to 11, then the year); 9 runs 0 to 7 and the donors treat 2
or less as a low battery; 16 is set while USB is connected (the start-up USB check reads it);
13 (initially 1) holds back the plug-in's switch to the charging screen; 17 (0 to 3) gates the
off timer - its meaning is not confirmed.

**Events go through the key stack too.** The firmware queues them as opcode `0x65` with the
event code as operand; upstairs' context 1 holds them, and the factory image's single context
holds the same codes:

| event | factory image | upstairs |
|---|---|---|
| `0x26` charge state changed (USB in) | enter the USB screen (28) | beep `0x4664`; the charge context (`1F E8`: 5 unless 13 is set and USB is in, 0 unless the battery is low, then 6 - see [harmony-800-firmware.md](harmony-800-firmware.md)); wake; push the mode, enter the USB screen (1), `07 FFFB`; if 13 is set start timer 7 (5 later: the charging screen 174) |
| `0x27` charging stopped | enter screen 0 | beeps `4664 1FF 1FF 1FF 4664`; the charge context; wake; if 13 and 15 are set, `3F F200`/`F201` by USB; pop the mode if the USB screen marked itself shown; `07 FFF6` when the battery is at 1 |
| `0x10` | nothing | when the battery is at 2 or less, wake; `3F F200` if 13 and 16 are set |
| `0x19` | nothing | `07 FFF6` |
| `0x2D` | `07 FFFA` | `07 FFFA` |
| `0x25` | enter screen 17 | nothing |
| `0x1F` on external power | a beep | `3F F100` (the motion sensor disarmed); beep; the charge context; wake; if 13 is set, timer 5 (5 later: push the mode, the charging screens - see "Charging") |
| `0x1E` off external power | beeps, screen 0 | beeps `4664 1FF 1FF 1FF 4664`; back to what was shown if the charging screens are up; the charge context; wake |
| `0x23` charge fault | - | beep; screen 9 (the charging-problem notice); `07 FFFB`; timer 14 (20 later: lights out) |
| `0x0F` battery level up | beeps | the current activity's screen, then the charging screens 5 later if 13 is set - `0x1F`'s second half: a build beeps, goes back to what was shown and starts that timer again |
| `0xAE`, `0xAF` | - | beep `0x0FCA`, previous / next page (`0F FFA0`/`FFA1`) |

**Where the events come from.** The One's application firmware (Region 2 of the 54.2.5 and
3.4 `.hfw` files, PIC18 code loaded at `0x20000`, disassembled with Ghidra) posts an event
by queueing `1F FCxx` - the event through the key stack - from a few routines that each
compare a reading with the last one:

| events | posted when |
|---|---|
| `0x0F` / `0x10` | the battery level (0-7) went up / down, then `0x18`-`0x1D` for levels 0-5, `0x0D` for 6, `0x0E` for 7 |
| `0x15` / `0x16` | a second reading (0-3; the light sensor, it seems) went up / down, then `0x11`-`0x14` for its level |
| `0x17` | the remote moved, while the motion sensor is armed |
| `0x20`, then `0x1F` / `0x1E` | external power (pin RB1 low): connected - the cradle or a charger - / removed |
| `0x21`, then `0x22` / `0x24` / `0x25` / `0x23` | the charger's state: off external power / charging / charged / a fault |
| `0x28`, then `0x26` / `0x27` | USB connected / disconnected |

Both firmware versions post the same numbers. The 800's differ - it posts `0x18` plus the
level for every level, and its own codes for power - so its numbering is not the One's.
The charge contexts fit the One's: the low one answers levels 0-1, the normal one 2-5, the
USB one external power removed.

The USB screen's enter handler sets a flag and its leave handler clears it; `0x27` pops only
when the flag is set, so unplugging never pops a screen the user opened themselves.

**Start-up** (upstairs' object `0x46C`, run by section 9's start-up list): `0F FFE1` four times,
`3F F064`, silent resets (`07 FFFF` then a write) of its own flags, push contexts 1, `0xFE`,
then the wake with `07 FFFB`, push `0xFD` (the current mode), `0xFC` and 4 (the key light); the
charge context; clear every zone flag; the wake; button sound flag to 0 and `3F F301`.

**How a generated image gets it.** `dabe16d` carried all of this from upstairs, cutting
what led into donor screens to the null instruction: about 80 objects of donor logic. It is
now generated: `backends/harmony_one/idle.py` builds the machine from the tables above - a
flag per zone, a wake, the off and poll timers, the charge context, the events, the USB
screen's shown flag, and enter and leave handlers per kind of screen - as a model in the
carried-screens form, and `idle.attach` appends it to the Options model so one namespace
holds both. Nothing about lights is in a project: a screen's zones follow from its kind.

The Options extractor no longer carries any of it. A carried screen's handlers named
upstairs' zone objects (lights on channels 0-7 and a flag write); the extractor recognises
those and writes `{"zones": [...], "on": bool}` instead, which the build resolves to its own
zone objects. The scaffold's Options model shrank from 690 objects, 11 timers and 19
variables to 504, 4 and 3.

`one-tools/compare_idle.py` runs a generated image and upstairs side by side - the key
light, the eight events and both timers, under every combination of variables 9, 13, 15, 16
and 17, five sets of lit zones, and the USB screen shown or not: 5,280 runs, none differ
(upstairs' timer 7, the charging screens, set aside; they are generated now, below). The
screens' enter and leave handlers
light and darken the same zones as their upstairs counterparts. One ordering was fixed on
the way: the carried start-up entered Activities before clearing the zone flags, so the
first timeout lost Activities' zones; start-up now clears them first and enters last, as
upstairs does.

## Charging

While a One charges, every donor shows the same four whole-screen pictures in a ring: a
battery for 5, then three photographs for 1 each, round again (upstairs' screens 174, 178,
177, 179; downstairs' and Kāt's are the same pictures). Each is a screen of one bitmap at
(0, 0) and nothing else - no title, no status bar - and each screen's enter handler runs
`07 FFFB` (which also stops the keypad's off timer, so the screen stays lit), pushes a
context binding every key to "enter the battery again", puts the USB charge context under
`0xFC`, and starts the timer that enters the next; its leave handler stops that timer and
chooses the charge context again. The last photo's enter handler also counts a lap
(`1F F2xx`, a variable of limit 2 that the ring's opening clears); its first lap, when
platform variable 10 is above 1, runs `07 FFFB` - the ring stops where it is - and a
timer 1 later darkens the keypad and the zones, fades the screen out (`C117`, `C111`) and
arms the motion sensor only when 13 is clear. Variable 10 is the firmware's charge state
machine (3.4 copies RAM `0xF10` into `0x112`, platform variable N living at `0x108 + N`),
which holds 2 to 7 while it looks after a charge, so on the cradle the ring is seen once.
External power connected (`0x1F`) - the remote set on
its cradle - opens the ring after timer 5 (5), over what was shown; removed (`0x1E`) goes
back. Upstairs' USB-in handler
also starts a timer into the ring when 13 is set (timer 7).

A build generates the same (`backends/harmony_one/charging.py`, `idle.py`): the scaffold's
`charging/battery` and `charging/photo-<n>` pictures - extracted by
`tools/harmony_one_extract_assets.py`, which follows the ring from the screens' own timers -
as bare owned screens straight after the screens carried behind Options, every key bound
in the screen's own list to the battery's screen rather than in a pushed context, and a
flag the enter and leave handlers keep so that `0x1E` pops the mode only while the ring is
up. The lap is a flag the battery clears and the last picture sets, so a key pressed on the
dark cradle shows one more round rather than a ring that never stops. USB in does not open the ring: the USB screen's own flag would no longer be the one
shown, and unplugging would leave the ring up. A theme without `charging/battery` gets no
charging screens and no `0x1E`/`0x1F`/`0x23` rows.
