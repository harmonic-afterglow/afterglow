# Fonts

Every piece of text the remote draws - your labels, the menus, Options, the firmware's own
notices and the clock - is drawn by the build from a typeface, in each font slot's colour
and shadow (`assets.json`, each slot's `look`).

## The default: Galmuri

`galmuri/` holds Galmuri 11 (the 18-pixel slots: labels, rows, titles, softkeys) and
Galmuri 9 (the 13-pixel slots: the clock, page counters), drawn at their own sizes on the
Harmony 800's 240 x 320 screen, as gzipped BDF bitmap fonts, under the SIL Open Font License
(`galmuri/OFL.txt`). Galmuri 7 is the Harmony One's small face, kept with them. `assets.json` names them under `typeface`. They cover Latin with
accents, Greek and Cyrillic. Each built image carries only the glyphs its own text uses,
at most 127 different characters in one slot.

The slots the Harmony One draws bold - every regular-size slot but the message font, each
with `"bold": true` in its `look` - are drawn from **Galmuri Afterglow 11 Bold**: Lee
Minseo's own Galmuri 11 Bold (`galmuri/Galmuri11-Bold.bdf.gz`), and for the Latin Extended-A,
Greek and Cyrillic it lacks, bold letters drafted and then checked and corrected by hand
(`tools/galmuri/galmuri11-bold.txt`; `tools/galmuri_afterglow.py` builds it). Put the bold
of your own font beside `font.ttf` as `font-bold.ttf` to replace it.

## Your own font

Put a TrueType font here named exactly

    font.ttf

and it replaces Galmuri in every slot; remove it to go back. Optionally add

    font-small.ttf

for the small slots, if your font comes in a smaller size, and `font-bold.ttf` for the bold
ones (without it they use your `font.ttf`).

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
- Your `font.ttf`, `font-small.ttf` and `font-bold.ttf` are yours: git ignores them here.
