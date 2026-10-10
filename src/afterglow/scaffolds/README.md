# scaffolds

One base tree per remote, named after its profile id (`library/remotes/*.json`).

A scaffold holds the parts of a configuration that are **properties of the remote, not of
your setup**: its persisted settings (`platformconfig/system_*.dat`), its hardware
calibration (battery discharge curve, PMIC, sleep and tilt configuration), the install
scripts it executes at flash time, and an empty `UserConfiguration.xml` shell.

Where that layer comes from depends on **what kind of thing it is**, and there are two
answers:

- **Undocumented per-model state** - calibration curves, persisted settings, install
  scripts - cannot be synthesised, so the scaffold is a sanitised copy taken from a real
  config of that remote. It is model-specific: a Harmony 900's battery curve is not a
  Harmony 1100's. `harmony-900` is this, and `NOTICE.md` explains what that means for
  licensing.
- **Assets rendered through a documented interpreter** - fonts, bitmaps, screen layouts.
  Where the format is a drawing VM the artwork *could* be ours. `harmony-one` is this:
  its pictures are the vendor's, extracted as PNG files anyone can open and replace, and its
  text is drawn by each build from an openly licensed typeface, with its own `README.md`
  and `NOTICE.md`. Only artwork is taken, never anything identifying a remote or its owner.

Which one applies is measured across several real configurations, not assumed.

**To add a remote** of an already-supported architecture: unpack a config from it, delete
its `userconfig/` devices and activities, clear any personal data (owner name, RF blaster
MAC, favourites), and drop the tree in here under the profile id.
