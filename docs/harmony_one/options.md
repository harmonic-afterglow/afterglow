# Options

Upstairs' Options screen (mode 276) has two pages: Turn Remote Assistant On, Tutorial and
Date and Time, then Turn Screen Sounds Off and Screen Sensitivity. Date and Time, Screen
Sensitivity and Screen Sounds are the builder's boilerplate - they set the remote's clock
and its touch screen - while Remote Assistant runs a configuration's power checks and help
flow and Tutorial names its own activities, so those two are left out until activities exist.

The rest is generated (`backends/harmony_one/options.py`). It was first copied from upstairs,
which copied upstairs' language and the years it offered (2023 to 2025), and did register
arithmetic on upstairs' own variable 47, a number that means something else in a generated
image. Read from upstairs' 16 screens, it is a chain of pickers and one list:

| screen | buttons | each writes | then |
|---|---|---|---|
| Year | the build year and either side, one a row | clock variable 6 := year - 2000 | Month, the leap one in a leap year |
| Month (two: leap and not) | twelve, six a page | variable 5 := month - 1 | the Day screen with that month's days |
| Day (28, 29, 30, 31) | six a page | variable 3 := day - 1, then `07 FFF8` | Hour |
| Hour | 12:00, 1:00 ... 11:00 | variable 2 := 0 to 11 | Minute |
| Minute | 00 to 59, ten pages | variable 1 | Time of Day |
| Time of Day | AM, PM | PM adds 12 to the hour if it is below 12; both set a flag and `07 FFF9` | Options |
| Screen Sensitivity | Very Low, Low, Medium, High, Very High | `3F F508`, `F50C`, `F500`, `F504`, `F507` | a screen saying so; its OK returns |

Every write is silent (`07 FFFF` before it) and every button clicks (`75 0FCA`). Back steps
to the previous picker; from Day it goes to the Day screen's own month, chosen by tests on
variables 5 and 6. Screen Sounds is a row of Options itself: a switch on its flag whose two
programs write `3F F300` or `F301`, flip the flag and redraw (`07 FFF7`).

**A 24-hour clock.** Logitech's European One (skin 59) has no Time of Day picker: its
Hour picker offers 00:00 to 23:00 and the minute sets the clock, and the status bar
draws the hour 00 to 23 (Danny Bloe's harmony-explorations, architectures/harmony-one/
compiler.md, "the clock header" and "the Year picker"). A project chooses it with the
preference `time_format: "Military"`, the key and value the Harmony 1100 keeps it under;
the Hour picker then writes variable 2 := 0 to 23, and Minute sets the clock (`07 FFF9`)
and goes back to Options.

A picker opens on the page holding the clock's current value and frames that value's button.
Its enter handler loads the variable into the accumulator (`1F EF`), takes the first value
off (`79`, adds), divides by the buttons a page (`77`) and queues `(accumulator, 76)`, show
that page (`1F F7 76`); the Hour screen first folds an afternoon hour back by 12. Each time a
page is drawn (event `0x29`) the handler reads the page shown (`1F E7 00`), and on the value's
own page leaves the value's index in a scratch variable and runs a switch on it whose
programs draw four 2-pixel bars round that button in `0xEC07`. The 800's interpreter gives
these: `77`/`78`/`79` divide, multiply and add to the accumulator and `7A` loads it; `0x1F`
bands `EF` accumulator := variable, `ED` variable := accumulator, `EE` variable := byte
register, `F0` byte register := variable, `F1`/`F2` decrement/increment, `F7` queue
`(accumulator, low)`, `F8`/`F9`/`FA` divide, multiply, add to the byte register.

The screens' text is a table of labels and the years come from the build date, which also
stamps the clock; their pictures are `images/options/`. Their touch zones follow one rule:
buttons take tags from `0x30` in reading order, Back the next tag (`0x2B` after six), the
side strips `0x2E`/`0x2F`. Each picker's enter handler lights zones 1 and 3 when it has
pages and 5 always, which with the testers' photos places the zones: 0/1 and 2/3 the side
arrows, 4/5 the left softkey bar, 6/7 the right one, orange and white.

Built as of 2024, every one of the 125 buttons writes what upstairs' button of the same label
writes (`one-tools`' comparison, by label and screen title).

**Section 15 is a set of switch tables.** Opcode `0x72` with operand `group << 8 | variable`
reads the variable and runs, in the drawing VM, the program the group assigns to its value:
`u8 lead (2), u8 n, n {u16 value, u24 program}, u8 m, m {u16 low, u16 high, u24 program}`.
A program queues its action through drawing atoms, so one key does different things by state
- Screen Sounds toggles its flag this way, and the date picker steps through its fields.
Section 15's pointers come first and the 151-byte platform table after them, so section 16's
pointers move with the count. A generated image had no tables at all before.

A generated image numbers it all afresh: Options at 41, the Options screens from 42, the
device list after them; the carried variables after the platform's 18 in section 14, before
the terminator; the carried timers after the platform's. The Options screen itself is drawn
by the build on upstairs' three row frames, labels centred in its row font (attribute 5),
with Screen Sounds' label a drawing switch on its flag ("Off" at 0, "On" at 1) placed last so
each case can end the program. Activities gains its Options softkey.
