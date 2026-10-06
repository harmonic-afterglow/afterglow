# About these images

These are **Logitech's icons**, extracted from a Harmony 900 firmware image
(`app-main.swf` inside `61.hfw`) by `tools/export_icons.py`, then replaced picture by
picture with the same drawings from a Harmony 1100 firmware (`app/assets/global/` in
`63.hfw`, 63.7.7) by `tools/export_icons.py 63.hfw --refine`. The 1100 keeps them as plain
PNG files rather than SWF bitmaps, so they come out without the speckle that undoing the
SWF's premultiplied alpha leaves in every shadow. Five buttons the 1100 names differently
(`live`, `podcasts`, `teletext_off`, `teletext_on`, `teletext_onoff`) are still the 900's. They are included because
they are the pictures the remote itself draws, and a configuration tool that shows a
device something other than what its owner sees on the remote is harder to use.

They are **not covered by this project's GPL-3.0 licence**. No permission to use them has
been granted by Logitech. If you are redistributing this project, or if Logitech asks,
these are the files to remove.

## Removing or replacing them

Nothing in the code knows where they came from. `afterglow/gui/icons.py` looks for one
PNG per type, named after the type:

    icons/devices/<DeviceType>.png        e.g. Television.png
    icons/activities/<ActivityType>.png   e.g. VirtualDvd.png
    icons/buttons/<IconName>.png          e.g. myTV.png

so drawing your own set is a matter of dropping files in with the same names. The type
names are listed in `TYPES.md`. Delete the folder and the interface shows no icons.

## How they were processed

Two corrections are applied to the SWF bitmaps on the way out, both visible if you skip
them (the 1100's PNGs need only the second):

* **Un-premultiplied alpha.** The colour in the source bitmaps is already multiplied by
  the alpha, so compositing them normally darkens the drop shadow twice - icons appear to
  have a double shadow.
* **Trimmed margins.** The sprites sit on a fixed canvas that is roughly half empty (a
  television occupies 80x56 of a 90x90 box, top-aligned), which makes them look tiny once
  scaled down.
