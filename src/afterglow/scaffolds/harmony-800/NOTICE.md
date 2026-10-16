# About this tree

**This project's own artwork.** The frames (`button-frame/`, `row-frame*`, `numpad-frame`,
and their `activity/` and `options/` copies), the title and softkey bars (`chrome/`), the
status icons (`status/`), the backdrop and `activity/sending.png` are drawn by
`tools/harmony_800_art.py` from the SVG in `art/`, after the look of Logitech's Harmony
800 screens in its Getting Started Guide. No Logitech pixels are in them; they are under
this project's GPL-3.0 licence.

**Drawn here from Logitech's.** The Tutorial's pictures of the remote (`tutorial/2`, `3`,
`8`, `10`) show `art/tutorial/harmony-800-front.svg`, a shaded drawing made from the line
art in the Harmony 800's Getting Started Guide, and those of devices (`tutorial/5`, `9`) the
type icons below; the tool draws the frames and the screen around them. What they show is
Logitech's, under the same restriction as Logitech's artwork below.

**The 800's own.** The battery warning's and USB's icons (`platform/battery-low`,
`platform/usb-connected`), the charging screen (`charging/battery`) and the charging
problem's cross (`platform/screen-09-0`) were taken from the Harmony 800's factory
configuration - the one a remote carries before it is set up - by
`tools/harmony_800_status_art.py`. Artwork only; the configuration is not kept. They are
Logitech's, under the same restriction as below.

**Logitech's artwork.** The rest of the pictures were **extracted from a real Harmony One
configuration** - the firmware's notice pictures under `platform/`,
the Tutorial's hand and thumb (`tutorial/1`, `11`) - or are Logitech's type icons
(`images/icons/`). The icons are MyHarmony's, as Logitech serves them to that software
(`https://files.myharmony.com/Assets/Images/`), written by
`tools/harmony_800_myharmony_icons.py`: each with its reflection cut away and trimmed, and
for the sixteen types MyHarmony has no icon for, two of its icons drawn together. None of
these are covered by this project's GPL-3.0 licence, and
they are here for the same reason `../../icons/` is: the remote cannot be driven without
them.

The forty screens the firmware itself shows - notices and diagnostics - are carried too,
as drawing programs in `platform/system-screens.json` - their pictures and logic; their
words are this project's, drawn from `backends/harmony_800/platform_text.py` - along with
the touch geometry and the 151-byte platform table under `platform/`. Those are
Logitech's as well.

Only artwork and platform state were taken. Nothing that identifies a remote or its
owner - no device names, activities, favourites, account data or RF registration - was
read from the donor configuration, and none of it appears here.

**The fonts are not Logitech's.** Every glyph is drawn at build time from Galmuri
(`fonts/galmuri/`), Copyright (c) 2019-2025 Lee Minseo, under the SIL Open Font License
1.1 (`fonts/galmuri/OFL.txt`); only each slot's two colours were read from the donor.

## Replacing them

Everything in here is a PNG. See `README.md`.
