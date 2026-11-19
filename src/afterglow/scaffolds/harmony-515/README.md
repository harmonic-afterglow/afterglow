# harmony-515

The Harmony 515 and 510 (skins 67 and 68: one remote in two colours). Their platform is
the Harmony 555's (`../harmony-555`), read from Logitech's empty 555 configuration, with
their own skin, keys and words and the parts their firmware build wires otherwise grafted
in: `platform/derived.json`.

No empty configuration of these models survives. Their households, walked side by side
with the empty 555 from the platform's roots, hold the same firmware screens, constant
sections and most of the wiring; what differs is their global key set (an object for
every key, reaching the firmware through other calls), the firmware keys' objects, two
firmware objects and the backlight and sleep timers. Those parts are taken from the
households, after leaving out every part a household changes in any platform
(`../harmony-555/platform/household.json`), and all five households measured give the
same parts (docs/harmony_5xx/ahcm.md, "Other models' platforms"). The file is measured
by:

    python3 tools/arch9_derive_platform.py --remote harmony-515 HOUSEHOLD.EZHex [...]

It names its evidence by hash only.
