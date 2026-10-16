# harmony-800 scaffold

Everything a Harmony 800 draws, as PNG files you can edit. `assets.json` lists them all
and is the only place names, sizes and glyph positions are declared.

The display is 240 x 320. A screen the build lays out (backends/harmony_800/pages.py) is
the backdrop, a title bar across the top, three rows of frames 4 pixels in from the edges
and 4 apart - four shorter rows on the number keypad - and a softkey bar across the foot:

    images/backdrop.png              240x320  black: what clears the display first
    images/chrome/header.png         240x44   the title bar: title on the light band,
                                              page counter on the dark one
    images/chrome/softkeys.png       240x26   the softkey bar at y 294, split in two
    images/button-frame/0..5.png     114x78   the six command buttons, top-left first
    images/numpad-frame.png           74x58   a device's number keypad's twelve keys
    images/row-frame*.png            232x78   full-width menu rows
    images/activity/...                       the same frames for the activities' screens
    images/options/...                        and for Options'
    images/activity/sending.png       62x33   the waves over a starting activity's icon
    images/icons/devices/<Type>.png           one icon per device type, any size
    images/icons/activities/<Type>.png        one icon per activity type, any size
    images/status/battery-0..7.png    20x11   the eight battery levels, at (217,4)
    images/status/charge-*.png        20x11   the charge animation
    images/status/indicator-*.png     22x18   the IR indicator at (192,0)
    images/status/progress.png        88x10   what the clock is drawn on, at (152,19)
    images/charging/battery.png      240x320  shown while the remote charges, for a few
                                              seconds at a time, the screen dark between
    images/charging/photo-<n>.png    240x320  optional: shown after the battery, in turn
    images/tutorial/<n>.png                   the Tutorial's pictures of the remote
    fonts/galmuri/                            the typeface every slot is drawn from
    fonts/font.ttf                            optional: your own font for all text

A picture the manifest does not name is not loaded; one it names but that is missing is an
error rather than a silent omission.

## The 800's look, as vector art

The frames, both bars, the keypad keys, the status icons and the waves are drawn as SVG
in `art/`, after the 800's own screens in its Getting Started Guide: colour above a
horizon halfway down each frame and black below it, inside a thin edge - blue on the
activities' screens, and on the rest their softkey's colour, green for Options and orange
for the devices; a grey title bar and softkey bar. `tools/harmony_800_art.py` writes the SVG and renders each file into
`images/` at the size the remote draws it, with its colours already reduced to RGB565:

    python3 tools/harmony_800_art.py

It needs `rsvg-convert` (librsvg). To restyle, change the tool's colours and run it, or
edit an SVG and render that one yourself. The status icons sit on the title bar and the
display cannot blend, so each one's SVG draws the slice of the title bar it covers behind
the icon: restyle the bar in the tool and the icons follow.

## Row icons

A device row draws its icon over the left end of the row frame. The display cannot blend,
so a build makes each row icon itself: it cuts the 56x74 patch the icon covers out of
`row-frame.png`, scales the type's icon to fit inside 47x40 keeping its proportions, and
blends it onto the patch. The row's name is centred on what the icon leaves of the row.
The icon is chosen by the device's `type` (`Television`, `Amplifier`, ...); a missing or
unknown type shows `activities/VirtualGeneric.png`.

The icons are the glossy family the 800's guide shows - Watch TV the television with a
remote beside it, Play Game the white gamepad - as MyHarmony, the setup software that
followed, carries it: `tools/harmony_800_myharmony_icons.py` writes one per type from
MyHarmony's icons, without the reflection they stand on. A type MyHarmony has no icon for
is two of its icons together: watching something is the television with that thing in
front of it, a combined unit its two parts stacked.

To change an icon, replace its PNG - at any size, with soft edges if you like, since the
blending happens before the remote sees it. To add a type, add `<Type>.png`. Restyling
`row-frame.png` restyles every icon's background with it. The icons are not listed in
`assets.json`: the folder is the list.

## Editing a picture

Replace the PNG, keeping the size the manifest declares. Anything an image editor writes
is readable: greyscale, palette or truecolour, with or without alpha, at any bit depth.
Interlaced files are refused - save without Adam7.

A picture may also be redrawn at another size - change `size` in the manifest to match -
but it stays where it is drawn. Button labels are centred on the button frame's own width,
and a frame bigger than its place (118x82, before it reaches the next button) is refused,
as is a menu row frame wider than the screen or taller than its row.

Two things about the display are worth knowing before you draw:

- **Colour is RGB565.** Five bits of red, six of green, five of blue. Flat fills and hard
  edges survive; gradients band. The loader counts pixels it had to change and reports
  them, so you can tell whether yours did. What ships reports none.
- **Transparency is one bit.** A picture either draws a pixel or leaves what was
  underneath alone; there is no blending. A soft edge becomes a hard one at half opacity,
  and those are counted too.

The `mode` in the manifest chooses storage: `raw` writes every pixel, `runs` skips the
transparent ones, `shorter` picks the smaller. A picture with any transparency cannot be
`raw`.

## Fonts

There are no font pictures. A build draws every one of the eighteen font slots from the
scaffold's typeface: a few sizes of one face, each in its slot's colour over a one-pixel
shadow down and to the right.

The typeface is **Galmuri** (`fonts/galmuri/`, SIL Open Font License): Galmuri 11 for the
18-pixel slots, Galmuri 9 for the 13-pixel ones (the clock, page counters), and Galmuri 11
at twice its size, a font pixel a block of four, for the 30-pixel one (the number keypad).
`assets.json` names them under `typeface`. It covers Latin with accents, Greek, Cyrillic,
Japanese and Korean, so translations draw without anything else. Each built image
carries only the glyphs its own text uses.

Each slot in `assets.json` is a height and a `look`:

    "look": {"colour": [255, 255, 255], "shadow": [49, 52, 49]}

Change `colour` or `shadow` (`null` for none) to recolour a slot. To draw all text from a
font of your own, put a TrueType file at `fonts/font.ttf` (and optionally
`fonts/font-small.ttf` for the small slots) - see `fonts/README.md`.

## The firmware's own screens

The first forty screens of every configuration belong to the firmware: the battery
warning, "USB Connected", update progress, and thirty diagnostics including "Invalid
Configuration". A build has to supply them at exactly those ordinals, so they ship here
too, and a project's own screens are numbered after them. They were drawn for the One's
176 x 220 and are placed in the middle of the 800's display; their status bar sits at its
top right.

    platform/system-screens.json    their drawing programs, 329 blocks, as a model
    platform/system-templates.json  the three touch templates they use, by index

A screen is a drawing program, not a picture, and every configuration links it afresh, so
`system-screens.json` holds blocks whose targets are names - a block number, a picture
role from this directory, an object number - rather than addresses. The pictures it names
are the ones under `images/`, so changing the backdrop changes every screen that draws it.

Their words are not in that file: each is a label naming an entry in
`backends/harmony_800/platform_text.py`, drawn by the build in your fonts - so to reword or
translate a notice or the clock's weekday names, edit that table. `assets.json` records
which font plays which part (`font_roles`), so a build emits the fonts in attribute order
and still knows which one labels a button.

When a notice is showing, its physical keys are not carried: in a donor they lead into
that owner's own help flow. The OK button on the battery and charging notices opens the
first screen the project owns instead.
