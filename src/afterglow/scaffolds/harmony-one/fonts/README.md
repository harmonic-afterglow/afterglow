# Fonts

Every piece of text the remote draws - your labels, the menus, Options, the firmware's own
notices and the clock - is drawn by the build from a typeface, in each font slot's colour
and shadow (`assets.json`, each slot's `look`).

## The default: Galmuri, and Galmuri Afterglow

`galmuri/` holds gzipped BDF bitmap fonts under the SIL Open Font License
(`galmuri/OFL.txt`), named in `assets.json` under `typeface`:

- **Galmuri 9** (Lee Minseo) for the 14- to 16-pixel slots;
- **Galmuri Afterglow 9 Bold** for the slots Logitech's own One draws bold - every 14- to
  16-pixel slot but the message font, each with `"bold": true` in its `look`. Galmuri has
  no bold at this size, so each letter was drafted and then checked and corrected by hand
  (`tools/galmuri/galmuri9-bold.txt`): Latin with its accents, Greek and Cyrillic. A
  letter it lacks comes from Galmuri 9.
- **Galmuri Afterglow 7** for the 11-pixel slots (the clock, page counters): Galmuri 7
  with the Cyrillic and Greek it lacked, drawn in its style
  (`tools/galmuri/galmuri7-additions.txt`).

`tools/galmuri_afterglow.py` builds the two Afterglow fonts from those files. Together they
draw Latin with accents, Greek and Cyrillic in every slot. Each built image carries only
the glyphs its own text uses, at most 127 different characters in one slot.

## Your own font

Put a TrueType font here named exactly

    font.ttf

and it replaces Galmuri in every slot; remove it to go back. Optionally add

    font-small.ttf

for the 11-pixel slots, if your font comes in a smaller size, and

    font-bold.ttf

for the bold slots. Without one, those slots use your `font.ttf` as it is.

- **TrueType only** (`.ttf`). A font with PostScript outlines (most `.otf` files) or a
  collection (`.ttc`) is refused with a message saying so.
- A pixel font - one whose letters sit on a grid of square pixels - is drawn at its own
  size, one grid square a pixel, and stays crisp. Any other font is scaled so its capital
  letters are 7, 8 or 9 pixels tall depending on the slot. Fine detail disappears at that
  size and the display has no grey, so a pixel is either drawn or not: fonts with thick,
  simple strokes survive best, and an ornate one will look rough, which is allowed.
- Weight comes from the font file: nothing is made bold by the build. For bold slots,
  add the font's bold `.ttf` as `font-bold.ttf`.
- A character your font does not have is drawn from Galmuri, so a themed font with
  capitals only, or no punctuation, still draws every screen. A character neither has is
  refused with a message naming it.
- Your `font.ttf`, `font-small.ttf` and `font-bold.ttf` are yours: git ignores them here.
