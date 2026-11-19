# harmony-520

This model's platform is the Harmony 555's (`../harmony-555`), read from Logitech's empty
555 configuration, with this model's own skin, keys and words: `platform/derived.json`.
No empty configuration of this model survives; its households, walked side by side with
the empty 555 from the platform's roots, hold the same firmware screens, wiring and
constant sections and differ only in those (docs/harmony_5xx/ahcm.md, "Other models'
platforms"). The file is measured from them by:

    python3 tools/arch9_derive_platform.py --remote harmony-520 HOUSEHOLD.EZHex [...]

It names its evidence by hash only.
