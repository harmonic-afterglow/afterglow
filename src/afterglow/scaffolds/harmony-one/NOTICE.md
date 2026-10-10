# About this tree

The pictures and fonts here were **extracted from a real Harmony One configuration**.
They are Logitech-authored artwork, **not covered by this project's GPL-3.0 licence**, and
they are here for the same reason `../../icons/` is: the remote cannot be driven without
them, and nothing else looks right on it.

The forty screens the firmware itself shows - notices and diagnostics - are carried too,
as drawing programs in `platform/system-screens.json`, along with the touch geometry
(including the device menu's) and the 151-byte platform table under `platform/`. Those are
Logitech's as well.

Only artwork and platform state were taken. Nothing that identifies a remote or its owner - no device names,
activities, favourites, account data or RF registration - was read from the donor
configuration, and none of it appears here.

**The 14-pixel fonts are not purely Logitech's.** No configuration ever drew `$%&;<=>@`,
`[]^_`, a backtick or `{|}~`, so those glyphs are this project's, added by
`tools/harmony_one_font_fill.py` - mostly built out of the font's own strokes (a
backslash is its slash mirrored, an equals is its hyphen twice, a dollar is its `S` with
a bar through it) and the rest drawn on the same grid. They are under this repository's
GPL-3.0 licence; everything else in the fonts is Logitech's.

## Why they are not synthesised

The Harmony One keeps no artwork in firmware; every frame, icon and glyph it draws is
stored in the configuration, so a generated one has to supply them. The format is a
general drawing VM, so they *can* be ours - the fonts are drawn for an RGB565 panel at 11
to 16 pixels and hinted by hand, which a scaled desktop font does not survive, and
matching that by hand is a large piece of work that would leave the remote looking wrong
until it was finished.

`tools/harmony_one_default_assets.py` draws a plain set from nothing if you would rather
have no vendor artwork at all. It is not what ships.

## Replacing them

Everything in here is a PNG. See `README.md`.
