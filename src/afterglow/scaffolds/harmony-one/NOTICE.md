# About this tree

The pictures here were **extracted from a real Harmony One configuration**.
They are Logitech-authored artwork, **not covered by this project's GPL-3.0 licence**, and
they are here for the same reason `../../icons/` is: the remote cannot be driven without
them, and nothing else looks right on it.

The forty screens the firmware itself shows - notices and diagnostics - are carried too,
as drawing programs in `platform/system-screens.json` - their pictures and logic; their
words are this project's, drawn from `backends/harmony_one/platform_text.py` - along with
the touch geometry
(including the device menu's) and the 151-byte platform table under `platform/`. Those are
Logitech's as well.

The type icons under `images/icons/` are copies of `../../icons/devices` and
`../../icons/activities`: Logitech's, from a Harmony 900 firmware image (`app-main.swf`),
under the same restriction as everything else here.

Only artwork and platform state were taken. Nothing that identifies a remote or its owner - no device names,
activities, favourites, account data or RF registration - was read from the donor
configuration, and none of it appears here.

**The fonts are not Logitech's.** Every glyph is drawn at build time from Galmuri
(`fonts/galmuri/`), Copyright (c) 2019-2025 Lee Minseo, under the SIL Open Font License
1.1 (`fonts/galmuri/OFL.txt`); only each slot's two colours were read from the donor.

The pictures are Logitech's. `tools/harmony_one_default_assets.py` draws a plain set from
nothing if you would rather have no vendor artwork at all. It is not what ships.

## Replacing them

Everything in here is a PNG. See `README.md`.
