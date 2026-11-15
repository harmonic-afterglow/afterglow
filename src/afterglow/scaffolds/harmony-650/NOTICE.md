# About this tree

The pictures here were **extracted from a real Harmony 650 configuration**.
They are Logitech-authored artwork, **not covered by this project's GPL-3.0 licence**, and
they are here for the same reason `../harmony-one/`'s are: the remote cannot be driven
without them, and nothing else looks right on it.

The 44 screens the firmware itself shows - battery and USB notices
and diagnostics - are carried too, as drawing programs in `platform/system-screens.json`:
their pictures and logic. Their words are this project's, drawn from
`backends/harmony_650/catalogue.py`. Those programs are Logitech's as well.

Only artwork and platform state were taken. Nothing that identifies a remote or its owner -
no device names, activities, favourites or account data - was read from the donor
configuration, and none of it appears here.

**The fonts are not Logitech's.** Every glyph is drawn at build time from Galmuri
(`fonts/galmuri/`), Copyright (c) 2019-2025 Lee Minseo, under the SIL Open Font License
1.1 (`fonts/galmuri/OFL.txt`); only each slot's height and two colours were read from the
donor.

## Replacing them

Everything in here is a PNG. See `README.md`.
