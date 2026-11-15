# harmony-650 scaffold

Everything a Harmony 650 draws, as PNG files you can edit. `assets.json` lists them all and
is the only place names, sizes and colours are declared. The screen is 128x128.

    images/backdrop.png            128x128  the screen behind most screens
    images/softkey.png             128x128  the softkey: only its button at the bottom is drawn
    images/title-bar.png           128x16   the strip a page's title sits on
    images/page/0..7.png           128x128  the backdrops of the pages a configuration draws
    images/corner/0..3.png                  the small marks at a page's bottom right
    images/platform/screen-NN-k.png         pictures only a firmware screen draws, by screen
    fonts/galmuri/Galmuri9.bdf.gz, Galmuri7.bdf.gz   the typeface every slot is drawn from

The `page/` and `corner/` pictures are numbered in the order the donor's screens first
draw them; which page each is for is named once the 650's generator draws them.

A picture the manifest does not name is not loaded; one it names but that is missing is an
error rather than a silent omission.

## Editing a picture

As for the Harmony One (`../harmony-one/README.md`): replace the PNG, keeping its size.
Colour is RGB565 and transparency is one bit; the loader counts the pixels it had to
change.

## Fonts

There are no font pictures. A build draws each font slot from Galmuri - Galmuri 9 for the
13- to 15-pixel slots and Galmuri 7 for the smaller ones - each in its
slot's colour over its shadow (`look` in `assets.json`; a slot with no shadow is drawn in
one colour). The heights and colours are the donor's.

## The firmware's own screens

The first 44 screens of every Harmony 650 configuration belong to the firmware: the
battery and USB notices, the update and learning notices and the diagnostics. A build has to supply them at exactly those ordinals, so they ship here as a
model, `platform/system-screens.json`, whose targets are names - a block, a picture role,
an object - rather than addresses. Their words are labels naming entries in
`backends/harmony_650/catalogue.py` (`system.screen.<n>`, and `system.exit` for the
softkey).

Two variables are the firmware screens' own though a configuration numbers them among its
own: the battery notice flag and the USB screen's state. The model names them by position
in its `variables` list (`{"write": n}`, `{"variable": n}`), with their initial values and
limits, and a build gives them numbers of its own.

## Reading text back

`platform/glyph-shapes.json` is how an import reads a 650's text: a fingerprint of each
glyph shape Logitech's fonts draw, with its character - fingerprints, not pixels. Rebuild or
extend it from configurations you have; it lists any code it cannot read yet, to name with
`--read`:

    python3 tools/arch14_glyph_shapes.py --remote harmony-650 yours.EZHex [...]

## Regenerating

From a configuration of your own:

    python3 tools/arch14_extract_assets.py --remote harmony-650 yours.EZHex \
        src/afterglow/scaffolds/harmony-650

It overwrites what is there, so copy anything of yours out first.
