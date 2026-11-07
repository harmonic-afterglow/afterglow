# Reading a configuration back

An import reads what a configuration does, not only what it holds (`importing.py`), and the
same reading serves Logitech's images and generated ones. What it relies on, measured on the
three household configurations and on generated ones:

- **Text is read by shape.** The glyph code a character gets is each image's own - Kāt's
  living-room configuration numbers 74 codes in an order none of the established layouts
  has - but Logitech's faces are the same in every image, so a glyph's pixel fingerprint
  names its character (`labels.py`, `platform/glyph-shapes.json`). Two faces draw a capital
  I and a small l alike; Logitech's codes are image-wide, so the code another font already
  reads as one is not the other. A letter with an accent no known image draws is the
  image's own letter with ink only above it: Kāt's Finnish ä and ö read that way.
- **A button's place is its touch zone's rectangle, not its key code.** Logitech numbers a
  page's zones its own way - on Kāt's activity page `b0` is the Devices softkey and `ab` a
  button - while the zones always sit in the same two columns (raw x 1257 and 2422) and
  three rows (raw y 3016, 2144 and 1272) as the frames the page draws.
- **A device's pages are often one screen.** Logitech draws a device's command pages as
  slots of one screen - Kāt's television is screen 148, four slots - and this backend as a
  screen per page; both are reached from a device-menu row, whose object also writes a
  variable of its own in Logitech's images.
- **Command names are the buttons' labels.** A name too long for a button's line is split
  without a space where it has none ("Power" over "Toggle" is PowerToggle); this backend
  splits a pad's label the same way, and reads its own back by widths (generating.md,
  "A pad's label is Logitech's"). Commands a device page does not show are bound to physical keys,
  and are named by them. Logitech keeps a press-only copy of a device's power and input
  commands - the same code without its repeat - which its state variables send.
- **A device's state variables carry its label.** `<Label>_Power_2` sends the off command
  going 1 to 0 and the on command and the power-on delay going 0 to 1; `<Label>_Input_<n>`
  either sends each input's command from any value, or steps, and some inputs are a
  sequence - wake, step there, confirm - which a project's inputs cannot hold.
- **An activity is the context whose enter writes `CurrentActivityState`.** Its writes to
  device variables are what it turns on and the inputs it sets; an instruction a test
  guards is not something it always does. Logitech's activities then open their own page
  through the Remote Assistant's screens and a switch on `CurrentLocation_1`, not on
  `CurrentActivityState`; an activity's pages are found by their title instead. Logitech's
  Off turns off what is on, by tests, rather than writing a list.
- **A favourite's logo is a picture of its own** in Logitech's images, drawn over the
  button's frame; this backend composes it onto the frame, inside a centred 73x42 box.
- **A held code is a repeat count** in Logitech's images - the low byte of a command
  object's device field, 1 for a tap - and a record of its own in this backend's: the press,
  its repeat frame until the hold has lasted, then a gap.
- **A row's icon is its type's**, the same pixels in every Logitech configuration, so a
  fingerprint of it names the type (`platform/type-icons.json`, written by
  `tools/harmony_one_type_icons.py` from the household configurations).

## What validation proves

Opcode operands are reported as possible references only when every operand for that opcode is
within the current object-table range. This is an inventory heuristic, not enough evidence to
rewrite those atoms.

Passing the validator proves that an image matches the measured arch-12 container and integrity
rules. Inventory counts prove only that these bounded native shapes can be walked. Neither proves
that a particular remote has accepted an image; that is what the hardware probes are for.
