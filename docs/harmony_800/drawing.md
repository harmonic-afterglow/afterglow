# Screens, drawing and touch

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
