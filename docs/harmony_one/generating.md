# Generating a configuration from a project

`generate.skeleton` builds an image without reading one. It lays out the header, every
section and the bodies they point at; the artwork comes from the scaffold and the commands
from a project. Empty it is 517 bytes - one screen, one context, one object, and a count of
zero everywhere the factory image has one. Built from the scaffold with an empty project
it is 421,331 bytes, nearly all of it pictures and the glyphs its own words use.

The layout follows from how a section's range is derived. `section_ranges` ends a section
where the next begins and `_sections` refuses duplicate pointers, so the bodies are placed
first, then the nineteen tables contiguously in ascending order, then the checksum and
`PTYY`. Each section's range then covers its own table and nothing else - and no section
may be empty, because a zero-byte section would share a pointer with its neighbour.

A command's waveforms are placed before its record, because the record points at them, and
its section-0 name follows. Its objects are numbered with all the others and placed after the
modes. Every pulse of a generated command reads back
identical to the project's own; the carrier returns 38,001 Hz for 38,000 because the period
is stored in whole nanoseconds.

## Only the pictures something draws

A generated image places a picture only when a program draws it: a platform block, a menu
page or a command page. Every donor's pictures are all reached, so Logitech's builder evidently
does the same, and the scaffold carries more than any one image needs - fifteen row icons where
three devices draw three, and the menu's artwork where a project has no devices. Placing them
all cost about 250 KB. The upstairs round trip went from 852,654 bytes at 88.9 % coverage to
761,062 at 99.6 %, and the empty, one- and three-device probes from 58-79 % to 99.8 %. What
is left uncovered is 64 KiB window padding and platform blocks no reachable program enters.

## First hardware results, and what they changed (2026-10-09)

W, X and Y boot on a tester's One (MickBim, #test-one): W shows "No devices", X and Y show
their device menus and send without crashing. Q to S, from before the timer and variable
fixes, froze or rebooted when a button was pressed. Two things were left, both fixed here:

- **The clock came late.** Every platform fragment draws the status bar itself, with two
  drawing atoms (opcode `11`, which queues an instruction): `(2, 0x73)` draws overlay 2 and
  an object of `(3, 0x73) (0, 0x73)` draws overlays 3 and 0. Owned fragments drew only the
  backdrop, so the clock and battery waited for the refresh timer and vanished whenever a
  page redrew. Owned fragments now queue the same two.
- **No way back from a device.** The right side strip led back to the menu, with nothing on
  screen to say so. Command pages now carry the donors' "Devices" softkey: the bottom strip's
  right half (raw touch `x 2406, y 271`, tag `0x2B`), its label at (110, 202) in the
  scaffold's softkey font, bound to the device's menu page.

## The hub: Activities, Devices and back

Every Logitech configuration boots into its Activities screen, devices or not, and OK on a
firmware notice opens it. Its bottom strip carries Options on the left and Devices on the
right; the device list carries Activities on the left; a device's pages carry Activities
on the left and Devices on the right. Upstairs draws the labels in their own fonts and
colours - Options in attribute 13 at (22, 202), Activities in 6 at (16, 202), Devices in 9
at (110, 202) - and binds them through the screen's touch template: zones 0x30/0x31 on
Activities, the menu template's 0x33 on the device list, 0x2B/0x2C on a device page. On the
device list Logitech's Activities runs a section-15 switch that reads "Current Activity"
while one is running; with no activities it is a plain navigation.

A generated image now has the same hub: ordinal 40 is Activities ("No activities" until
activities exist), the device list starts at 41 and is there with no devices ("No
devices"), and command pages carry both softkeys. Options follows with the Options screens.

## Words are the build's own, and so are the font codes

A text instruction names glyphs by code in the font its attribute selects, and nothing in
the firmware fixes those codes: a generated image carries no character table, and the
firmware draws whatever the codes point at. The donors' fonts each carry a sparse table of
their own (the codes the donor's text happened to need), and a build had to keep them only
because the firmware's 40 screens, copied from upstairs, drew their words in those codes.

Those words are now the build's too. `platform/system-screens.json` keeps the screens'
pictures and logic, but each word is a `label` item - `{"key", "font", "y", "align", "x"}`
with `line` or `value` - naming an entry in `backends/harmony_one/platform_text.py`: a
screen's lines by ordinal, the 30 system messages' numbered title, OK, and the status
bar's clock (weekday, hour on a 12-hour face, minutes). A build draws each in its slot's
font: centred, from a left edge, or against a right edge (the clock's weekday ends at 141,
its hour at 158, its minutes start there), as the donors placed them.
`tools/harmony_one_extract_assets.py` writes the model that way from any donor; run on
upstairs it reproduces the shipped file exactly.

So the codes are each image's own, as they were in every Logitech configuration: a slot
carries exactly the characters that image draws in it, numbered from 1 in code-point order.
`generate.build` lays the image out twice. The first pass gives every slot each character
its words could need (the catalogue in the project's language, the device and command
names, printable ASCII) and `fit_label` records what each slot was asked to draw - the
whole label, since a label's characters are checked before it is cut to fit. The second
pass builds the image with exactly those, and returns `characters`, one `{code: char}`
table per font attribute, for anything that has to read the text back. A slot holds at
most 127 characters (`assets.MAX_CODES`); a build that needs more is refused by name.
That bound is generous for any alphabetic script - the busiest slot of a project mixing
Japanese, Greek, Russian, German, Chinese and Korean drew 59 - but a CJK project with many
long names could reach it. A slot that is a sheet keeps the codes its manifest entry gives.

## The device menu

A generated configuration's first owned screen is the device menu, at ordinal 40, so every
firmware notice's OK button reaches it. It draws one row per device - a full-width frame,
the device's icon, and its name - three rows to a page, and each row's touch key opens that
device's first command page.

A menu row is bound the same way a command button is, through an object, and in a generated
image that object is a navigation, `(kind, 0x75) (screen, 0x7e)`: the row's screen is the
ordinal a press opens. Donor rows carry one more atom, `(1, 0x99)`, which this section used to
call a constant device-row marker. It is an instruction: opcodes from `0x80` write variable
`opcode & 0x7f`, so it sets the donor's own variable 25, whose range and readers differ from
donor to donor (limit 121, 3 and 1 in the three). A generated image has 19 variables, so its
rows write nothing.

## A page you can press

A command page is four things, and a generated one now builds all four. Its drawing program
draws the backdrop, then each button's frame and a label centred over it - nothing in the
format clears the screen, so a page that draws no backdrop shows whatever the last one
drew. Its key register binds one key code per button, from `0xb0` upward in reading order.
Its section-19 template gives each button a touch zone. And its slot joins the three.

A button is bound to a command through two objects, not one. The key register row names an
object whose atoms are a constant `(0xfca, 0x75)` - present in all 185 command rows of a
donor and never absent - and a reference to the command object proper, which is the
`(command, device)` pair. So the chain is key, wrapper, command.

Touch zones are raw panel coordinates rather than pixels: x runs about 1173 + 14 per pixel
and y about 3630 - 16 per pixel, measured upwards, with different scales per axis. That is
calibration rather than layout, so it lives in the scaffold beside the platform table, and
a page takes the smallest of the donors' templates that covers its buttons - they carry
geometry for 1, 2, 3, 5 and 6, so a page of 4 uses the 5-button template with the zone for
the button it does not draw removed.

A label wider than its button is refused rather than drawn over the edge, because nothing
in the format clips: `Sony BDP-S5000ES` is 100 pixels against 81. Splitting or shortening a
name that long is a decision for whatever builds the project, not for the writer.

## Labels that do not fit

A generated label wider than its place wraps rather than being refused, by the donors' own
rules ([screens.md](screens.md#how-a-command-screen-is-drawn)): a button's two lines sit 11
pixels apart around its single-line baseline (53 and 64 for 58), a menu row's 12 apart (51 and 63 for 57). Words wrap at spaces, a word wider than a
whole line is split where it stops fitting, and anything left after the second line is cut and
marked `..`. The upstairs round trip now keeps every device name whole - "Game Console (With
DVD)" and "AV Receiver- Room 1" draw on two lines - where it used to trim them.

## Nothing a generated image names is missing

`afterglow-research/one-tools/refcheck.py` resolves every instruction in an image - objects,
mode and page lists, timers, section 9's leading list - against the table it indexes, by the
Harmony 800's reading: objects, modes, overlays, contexts, timers and variables. The three
donors come out clean over about 13,000 references, which is what makes the reading credible
for the One. Generated images had three kinds of dangling reference: the menu rows' variable
25, the platform timers ([image.md](image.md#section-13-is-the-timer-table)), and platform
handlers carried from upstairs that set and test the donor's own variables (24, 30, 32, 41, 19) and push its contexts 2 and 3 - screens 0, 1,
2, 3 and 9 marking themselves shown. The extractor now leaves that bookkeeping out (17 atoms,
with the `07 FFFF` modifier before a write and the instruction a test guards), and generated
images resolve every reference.

The menu's touch geometry - three device rows, a header strip and two side strips - is
identical in every donor, so it is carried in the scaffold like the platform screens' own
templates and emitted at whatever index a generated menu slot needs.

A menu holds three rows a page and a device's commands six a page, and both page with the
same primitive: the two side-strip touch zones every screen template carries, `0xae` and
`0xaf`, bound to go-to-screen objects. Menu pages form a cycle, so from the last you reach
the first; a device's command pages run forward and lead back to the menu the device sits
on. Every command is reachable however many devices a project has and however many commands
a device has, up to the format's own ceilings - 255 devices, 256 commands each.

The section-6 ordinal is what makes this straightforward: an ordinal is a screen's position
in the index, not its emission order, so every page's ordinal is assigned before any page is
written and a navigation can name a page that does not exist yet. The menu pages take the
first owned ordinals, the command pages follow device by device, and each row and side strip
is given the ordinal it should open directly.

The donors page differently - one screen with a slot per page and a `0x72` page-control atom
that the firmware advances in place - and that native mechanism is not reproduced here.
Navigation between whole screens is instead the one primitive already proven to work, since
it is exactly what a menu row and a notice's OK button do. Which of the two a real remote
prefers on the side strips is a question for the first hardware test.
