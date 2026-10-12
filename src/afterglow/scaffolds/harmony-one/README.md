# harmony-one scaffold

Everything a Harmony One draws, as PNG files you can edit. `assets.json` lists them all
and is the only place names, sizes and glyph positions are declared.

    images/backdrop.png             176x220  the screen behind everything
    images/button-frame/0..5.png     81x50   the six command buttons, top-left first
    images/row-frame*.png           164x50   full-width menu rows
    images/icons/devices/<Type>.png          one icon per device type, any size
    images/icons/activities/<Type>.png       one icon per activity type, any size
    images/status/battery-0..7.png   20x11   the eight battery levels
    images/status/charge-*.png       20x11   the charge animation
    images/status/indicator-*.png    22x18   the indicator at (128,0)
    images/status/progress*.png      88x10   the bar at (88,19)
    images/options/button-frame/0..5.png  81x50  the green buttons of Date and Time
    images/options/row-frame/0..2.png    164x50  the green rows of Options
    images/charging/battery.png     176x220  shown while the remote charges, then...
    images/charging/photo-1..3.png  176x220  ...each photo in turn, round again
    fonts/galmuri/Galmuri9.bdf.gz, Galmuri7.bdf.gz   the typeface every slot is drawn from
    fonts/font.ttf                           optional: your own font for all text

A picture the manifest does not name is not loaded; one it names but that is missing is an
error rather than a silent omission.

The charging screens are the battery for five seconds, then each `charging/photo-<n>` for
one, numbered from 1; to show fewer photos or more, remove or add them in `assets.json`
too. Without `charging/battery` the remote shows nothing while it charges.

## Row icons

A device row draws its icon over the left end of the row frame. The display cannot blend,
so a build makes each row icon itself: it cuts the 51x48 patch the icon covers out of
`row-frame.png`, scales the type's icon to fit inside 47x40 keeping its proportions, and
blends it onto the patch. The icon is chosen by the device's `type` (`Television`,
`Amplifier`, ...); a missing or unknown type shows `activities/VirtualGeneric.png`.

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
and a frame bigger than its place (83x54, before it reaches the next button) is refused, as
is a menu row frame wider than the screen or taller than its row. Device-row labels get the
room the row frame leaves to the right of the icon.

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
scaffold's typeface, the way Logitech's eighteen fonts relate to each other: a few sizes
of one face, each in its slot's colour over a one-pixel shadow down and to the right.

The typeface is **Galmuri** (`fonts/galmuri/`, SIL Open Font License): Galmuri 9 for the
14- to 16-pixel slots and Galmuri 7 for the 11-pixel ones (the clock, page counters).
`assets.json` names them under `typeface`. It covers Latin with accents, Greek, Cyrillic,
Japanese and Korean, so translations draw without anything else. Each built image
carries only the glyphs its own text uses.

Each slot in `assets.json` is a height and a `look`:

    "look": {"colour": [255, 255, 255], "shadow": [49, 52, 49]}

Change `colour` or `shadow` (`null` for none) to recolour a slot. To draw all text from a
font of your own, put a TrueType file at `fonts/font.ttf` (and optionally
`fonts/font-small.ttf` for the small slots) - see `fonts/README.md`.

A slot may still be a sheet instead - a PNG with its glyphs side by side and each glyph's
`x`, `width`, `code` and `char` in the manifest, as `tools/harmony_one_extract_assets.py`
writes them - and a build uses it as it is.

## The firmware's own screens

The first forty screens of every configuration belong to the firmware: the battery
warning, "USB Connected", update progress, and thirty diagnostics including "Invalid
Configuration". A build has to supply them at exactly those ordinals, so they ship here
too, and a project's own screens are numbered after them.

    platform/system-screens.json    their drawing programs, 329 blocks, as a model
    platform/system-templates.json  the three touch templates they use, by index
    platform/menu-template.json     the device-menu touch geometry (three rows + strips)

A screen is a drawing program, not a picture, and every configuration links it afresh, so
`system-screens.json` holds blocks whose targets are names - a block number, a picture
role from this directory, an object number - rather than addresses. The pictures it names
are the ones under `images/`, so changing the backdrop changes every screen that draws it.

Their words are not in that file: each is a label naming an entry in
`backends/harmony_one/platform_text.py`, drawn by the build in your fonts - so to reword or
translate a notice or the clock's weekday names, edit that table. One thing about them is
fixed:
`assets.json` records which font plays which part (`font_roles`), so a build emits the
fonts in attribute order and still knows which one labels a button.

When a notice is showing, its physical keys are not carried: in a donor they lead into
that owner's own help flow. The OK button on the battery and charging notices opens the
first screen the project owns instead.

## Regenerating

From a configuration of your own:

    python3 tools/harmony_one_extract_assets.py yours.EZHex \
        src/afterglow/scaffolds/harmony-one --complete-fonts

That writes the donor's own fonts back as sheets, in place of Galmuri: with them a build
can only draw the characters the donor drew. `--complete-fonts` fills each font's gaps from
another font of the same typeface and recolours what it borrows, so a word does not come
out in two colours.

Or draw a plain set from nothing, with no vendor artwork in it:

    python3 tools/harmony_one_default_assets.py somewhere-else

Both overwrite what is there, so copy anything of yours out first.
