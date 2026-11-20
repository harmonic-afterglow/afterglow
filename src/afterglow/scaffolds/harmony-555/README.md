# harmony-555

The platform layer the Harmony 5xx backend (`backends/harmony_555`) builds and reads images
against.

## What a build takes from here

- `platform/wiring.json`: the platform's wiring as numbers - its state variables, contexts,
  objects, timers, switch tables and their programs, the start-up list and the small
  constant tables. A build numbers the household's own after them.
- `platform/screens.json`: every screen of the platform as its key lists and, per page, a
  backdrop picture, the pictures drawn over it and its lines of text - their font, place
  and English words. The firmware's own notices are screens 0 to 40; 41 to 51 are the frame
  a household is built in: the Remote Assistant, Devices, "Nothing to do", "Stopping
  Activity", the Activities menu, the welcome and "all your devices should be off" screens,
  the battery warnings and the question that hides the Assistant.
- `images/*.png`: the pictures those pages draw, by what they are (`assets.json`, each
  with the box it is drawn in), and `images/page.png`, a household page's backdrop.
- `fonts/galmuri/GalmuriAfterglow7.bdf.gz`: the typeface every font slot is drawn in, on
  the remote's eleven-row grid (`backends/harmony_555/typeface.py`).

The pictures and the typeface are what a theme can change (`THEME.md`; `assets.json`
lists them, and the other 5xx scaffolds' point here). The extractor writes the pictures
as `images/picture-<n>.png`, numbered as the configuration it reads holds them; they are
renamed here by what they draw, and `platform/screens.json` names each file.

The three platform files come from Logitech's empty 555 configuration - the one its
software writes for a remote with no device or activity - read by:

    python3 tools/arch9_extract_platform.py --remote harmony-555 EMPTY.EZHex \
        src/afterglow/scaffolds/harmony-555

An empty project builds back to that configuration's wiring, key lists and words
(tests/test_harmony_5xx.py).

## Reading text back

`platform/glyph-shapes.json`: which character each glyph shape draws. Fingerprints of
pixels (SHA-256 of width, height and the ink mask), never the pixels. It covers both
typefaces the family draws: the 11-row face of the 520, 525, 550, 555 and Harmony for Xbox
360, and the 12-row face of the 510 and 515.

It is regenerated with `afterglow-research/555-tools/build_glyph_shapes.py`, outside this
repository. That script reads every glyph of the configurations it is given with both this
backend and harmony-decompiler, refuses any glyph the two decode differently, and takes
each character from the decompiler's alphabet.
