# Fonts

Every piece of text the remote draws - your labels, the menus, Options, the firmware's own
notices and the clock - is drawn by the build from a typeface, in each font slot's colour
and shadow (`assets.json`, each slot's `look`).

## The default: Galmuri

`galmuri/` holds Galmuri 11 (the 18-pixel slots: labels, rows, titles, softkeys) and
Galmuri 9 (the 13-pixel slots: the clock, page counters), drawn at their own sizes on the
Harmony 800's 240 x 320 screen, as gzipped BDF bitmap fonts, under the SIL Open Font License
(`galmuri/OFL.txt`). Galmuri 7 is the Harmony One's small face, kept with them. `assets.json` names them under `typeface`. They cover Latin with
accents, Greek, Cyrillic, Japanese and Korean. Each built image carries only the glyphs
its own text uses, at most 127 different characters in one slot.

## Your own font

Put a TrueType font here named exactly

    font.ttf

and it replaces Galmuri in every slot; remove it to go back. Optionally add

    font-small.ttf

for the 11-pixel slots, if your font comes in a smaller size.

- **TrueType only** (`.ttf`). A font with PostScript outlines (most `.otf` files) or a
  collection (`.ttc`) is refused with a message saying so.
- A pixel font - one whose letters sit on a grid of square pixels - is drawn at its own
  size, one grid square a pixel, and stays crisp. Any other font is scaled so its capital
  letters are 7, 8 or 9 pixels tall depending on the slot. Fine detail disappears at that
  size and the display has no grey, so a pixel is either drawn or not: fonts with thick,
  simple strokes survive best, and an ornate one will look rough, which is allowed.
- Weight comes from the font file. Want bold text? Use the font's bold `.ttf`.
- A character your font does not have is drawn from Galmuri, so a themed font with
  capitals only, or no punctuation, still draws every screen. A character neither has is
  refused with a message naming it.
- Your `font.ttf` and `font-small.ttf` are yours: git ignores them here.
