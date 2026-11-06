# What the Harmony 800's firmware says about the format

## The instructions and lists

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
  nibble of the operand's high byte picks the test) and drop the next instruction when it
  fails; `07` with `FD`/`FC` pushes and pops the current mode. The 800's handler reads bit 7
  of the high byte as inverting the test. The One's configurations do not use it that way:
  upstairs chooses the Remote Assistant's first note with `== 0` *with* bit 7 and skips it
  with `== 3` *without*, shows its welcome on `<= 1` with bit 7, and Kāt's waits for a smart
  TV's apps on `OnlinePower == 0` with bit 7 before marking them up - each the obvious intent
  only if the test runs the next instruction when it holds. A build copies bit 7 only where
  a donor has it, and new logic uses plain tests.
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

## What a build had carried without knowing

Instructions a build had carried from the donors without knowing what they do, read in
the Harmony 800's firmware (`discord_reports/asdfgpio/ghidra`, decompiled with
`decomp_at.sh`) and each checked against what the donors do with it:

- **The key stack.** A key or event (`0x65` in the queue, `FUN_0800b154`) is looked up from
  the top of the stack down, and the first context that answers it ends the search. An
  entry is a context number, or one of three that stand for something else: `0xFE` the
  running context (the one `1F FFxx` selected), `0xFD` the shown screen's lists, `0xFC` the
  context in the byte `1F E8xx` sets. Every donor pushes events (1), `0xFE`, `0xFD`, `0xFC`
  and the key light, so a running activity answers below the screen and above the events.
- **`1F E8xx` is not a charge byte.** It puts context xx under `0xFC`. The donors choose
  among three on every charging event: 0 normally, 5 on USB, 6 on a low battery. All three
  donors' contexts 0, 5 and 6 are the same: 0 and 6 choose again on battery events
  `0x1A`-`0x1D` and `0x18`/`0x19`, 5 stops the timers on `0x1E`, every row passed on. A
  build writes `E8` with its own numbers for the same three (`CHARGE_CONTEXTS`), and the
  platform model names them (`{"charge": "usb"}`) rather than carrying upstairs' numbers;
  `one-tools/refcheck.py` checks every `E8` names a context. Before this, generated images
  selected 5 and 6 with nothing there, which mattered only once `0xFC` was on the stack.
- **`07` with low byte:** `FF` the next write is silent; `FE` runs the running context's
  tag 5; `FD`/`FC` push and pop the mode; `FB` stops every running timer - the firmware runs
  at most four, in the same slots `1F EB` starts them in; `FA` marks the USB link (the
  donors' answer to event `0x2D`, a USB change); `F7` redraws the page; `F6` drops the top
  of the mode stack without entering it.
- **`3F F0`-`FF` are the firmware's settings**, `index = high & 0xF`: 0 is 10 at reset and
  every donor sets 100 first thing (the handbook reads it as the timers' unit); 1 arms the
  motion sensor, so the next movement posts event `0x17` once and disarms - upstairs writes
  `F101` as the keypad goes dark, which is how picking the remote up wakes it; 3 is the
  button sound (`F300`/`F301`, what Screen Sounds writes); 4, 6 and 7 are bytes the 800
  starts at 75, 50 and 21. Setting 2 (`F200`/`F201`, written with USB) has no handler on
  the 800, so it is the One's own.
- **`3F D0`** queues the next instruction's bytes for the host link; the donors' activities
  run `3F D000`, a build does not.
- **`0F FFE1`/`FFE3`**, which both donors run on the motion event, do nothing on the 800;
  they are the One's own and stay as upstairs has them.
- **Platform variable 17 is the infrared engine's state**: the 800's sender sets it to 1
  while a wait holds, 2 while a code goes out, 3 while one finishes, and back to 0 idle
  (`FUN_0800c77c` and its callers). The idle layer's arm step tests it, so the keypad's off
  timer follows whether infrared is going out. Setting 1 (`3F F1`) is variable 7.
- **The instruction queue holds 40 and drops what does not fit** (`FUN_0800ae3e`, a ring of
  120 bytes). A send or a wait the infrared side cannot take yet puts itself back at the
  head and is tried again, which is why a starting screen stays up until its codes are out.
  Running an object puts all of its atoms at the head at once (`FUN_08018e2c`, then
  `FUN_0800b18e` moving them in front), so a long object queues deep: `one-tools/queue_depth.py`
  runs every handler that way, and no handler in the three household donors goes past 16.
  A build cuts every object longer than eight atoms into a chain of short ones
  (`generate.bounded_objects`, never after a test or a silent mark) and shares identical
  touch templates (section 19 indexes 255); a test checks a fifteen-device project stays
  within 16. Before this, a generated Options picker queued 28.
- **Text codes past 0x7F take two bytes**: the 800's text VM reads a byte with its high bit
  set and the next as `((first << 8) | second) & 0x7FFF`, one less than that indexing the
  font's glyph table, whose count every donor stores as a `u16`. So a slot can hold more
  than 127 characters; a build numbers each slot's characters from 1 and writes codes past
  0x7F that way (`drawing.GlyphCodes`). The second byte may be zero, so a reader skips it
  rather than taking it for the terminator. Not yet seen on a One.
