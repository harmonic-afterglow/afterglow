# Lists, events and instructions

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
entered, `07` left, `2E` a page drawn, and the ones under Events; a context answers `01`, `02`
and `05` when it is selected, left and selected again (`FUN_0800b1b4`).

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
| `30` | the infrared engine's state changed (`FUN_0800c77c`) | the engine itself |

**`30` must be answered.** The engine queues it as `65 0030` and stops (its byte at `+0xD`
set) until the answer has run; Logitech's image answers `07 FFFA`. The One has no such event -
the One's `30` is the touch screen, the 800's `31` - so a build carrying the One's rows left it
unanswered: the first command of an activity's start went out and nothing after it, the IR
indicator stayed up, and with the engine never idle (variable 17) the remote never slept. The
idle context answers it now (`idle.IR_STATE`, a code marked `structures.NATIVE`). Measured in the
emulator: four sends queued, one transmitted before; all four after.

Logitech's image answers them in its context 1 as the One's answers the One's: `2B` beeps and
shows the USB screen, `2C` returns, `23` beeps on external power, `2A` (charger state 3) shows
the charged battery (screen 4), `29` (state 4) the charging-problem notice (screen 5); its
context 2 wakes on `31` and every key, and `07 FFFA` answers `30`.

**The One numbers its events differently** ([`harmony_one/idle.md`](../harmony_one/idle.md),
"Where the events come from"): USB is `26` / `27` / `28`, external power `1F` / `1E` / `20`, the
battery's direction `0F` / `10`. A configuration built with the One's numbers reads the 800's
battery and charger reports at boot as USB plugged in, charging started and a charging fault,
and runs through the screens those open - which the first generated image did. The backend
renumbers each One event to the 800's (`structures.EVENTS`); levels 0-5, motion, `2D`, `06` and
`07` are the same on both. The One's charger state "charging" (`24`) has no confirmed
counterpart and is left unbound.

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
