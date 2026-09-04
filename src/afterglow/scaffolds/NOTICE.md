# About these trees

Each scaffold is a **sanitised copy of a real configuration** from that remote, reduced to
the parts that describe the hardware rather than anyone's setup: persisted settings, the
battery discharge curve, PMIC/sleep/tilt calibration, the install scripts the remote runs,
and an empty `UserConfiguration.xml` shell.

They are here because those files cannot be synthesised - the formats are undocumented and
the values are per-model - and a config built without them will not run.

Personal data has been removed: the owner name and account id are placeholders, the RF
blaster registration is stripped, and no devices, activities or favourites remain. What is
left is Logitech-authored platform data, **not covered by this project's GPL-3.0 licence**.

To rebuild one from your own remote instead:

    python3 -m afterglow.ezhex unpack configs/mine/dump.ezhex scaffolds/harmony-900
    # then clear userconfig/ of devices and activities, and your name from the User block
