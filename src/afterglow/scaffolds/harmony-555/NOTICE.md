# NOTICE

`platform/glyph-shapes.json` maps glyph fingerprints to characters. It holds no glyph
pixels, configuration, device name or other vendor artwork.

The fingerprint-to-character entries come from `tools/arch9_glyphs.json` in
[trelowney/harmony-decompiler](https://github.com/trelowney/harmony-decompiler), distributed
under GPL-3.0-or-later, the same licence as Afterglow. Its characters were read by eye by
that project from the Harmony 525, 515 and 555 configurations named in its
`build_arch9_glyphs.py`.

`platform/wiring.json`, `platform/screens.json` and `images/` are read from Logitech's empty
Harmony 555 configuration by `tools/arch9_extract_platform.py`: the firmware's notices and
the frame Logitech's software builds every household in, so a generated configuration
supplies them as the remote expects. They hold no device, activity or owner's data.

**The fonts are not Logitech's.** Every glyph is drawn at build time from Galmuri
(`fonts/galmuri/`), Copyright (c) 2019-2025 Lee Minseo, under the SIL Open Font License
1.1 (`fonts/galmuri/OFL.txt`); only the slots' eleven-row height was read from the donor.
