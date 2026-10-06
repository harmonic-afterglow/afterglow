# What is in this scaffold, and where it came from

Taken from Logitech's own files, not from a household's configuration: every file kept is
byte-identical in the factory configuration inside firmware 63.7.7 (Region 4) and in the
one Logitech-generated user configuration examined.

    .version  .postinstall  META-INF/MANIFEST.MF
    userconfig/SsRf.bin               no RF devices
    platformconfig/batt_lvls.dat      battery millivolts -> bar level
    platformconfig/pmiccfg.dat        power-management IC
    platformconfig/sleepcfg.dat       sleep timing
    platformconfig/tiltcfg.dat        motion sensor

`.preinstall` is the user configuration's: it clears `userconfig/` only. The factory
configuration's also deletes the backlight, clock and volume preferences, which a user
configuration must not do.

## Built, not copied

- `userconfig/UserConfiguration.xml` - the shell: placeholder owner, the `Device Sequence`
  controller every 1100 configuration declares. Devices, activities and their action lists
  (inline here; the 1100 has no `ActionLists.xml`) are added by the build.
- `userconfig/SsIr.bin` - an empty device-sequence table; the build writes the real one
  (docs/harmony_pk/ssir-sequences.md).

## Left out

- `platformconfig/system_*.dat` - the remote's preferences. Without them the remote keeps
  the values it has; a build writes the ones the project sets.
- `userconfig/RamInitialise.bin` - present in the user configuration, absent from the
  factory one, and read by nothing in the application filesystem (Region 12).
- `userconfig/region_7_*.bin` - factory-only regional data, which a user configuration's
  `.preinstall` deletes anyway.
- No `IrProto.bin`: the 1100 has no protocol programs.
