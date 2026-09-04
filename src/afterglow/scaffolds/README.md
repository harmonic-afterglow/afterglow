# scaffolds

One base tree per remote, named after its profile id (`library/remotes/*.json`).

A scaffold holds the parts of a configuration that are **properties of the remote, not of
your setup**: its persisted settings (`platformconfig/system_*.dat`), its hardware
calibration (battery discharge curve, PMIC, sleep and tilt configuration), the install
scripts it executes at flash time, and an empty `UserConfiguration.xml` shell.

None of that can be synthesised - the formats are undocumented and the values are
per-model - so a scaffold is a sanitised copy taken from a real config of that remote.
It is model-specific: a Harmony 900's battery curve is not a Harmony 1100's.

**To add a remote** of an already-supported architecture: unpack a config from it, delete
its `userconfig/` devices and activities, clear any personal data (owner name, RF blaster
MAC, favourites), and drop the tree in here under the profile id.
