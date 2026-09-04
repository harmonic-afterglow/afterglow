# What is in this scaffold, and how much of it is fixed

Measured across five real Harmony 900 configurations (one own dump, four donors).

## Identical in all five - genuine model constants

    .preinstall  .postinstall  .version  META-INF/MANIFEST.MF
    platformconfig/batt_lvls.dat      battery millivolts -> bar level
    platformconfig/pmiccfg.dat        power-management IC
    platformconfig/sleepcfg.dat       sleep timing
    platformconfig/tiltcfg.dat        motion sensor
    platformconfig/system_firsttimedownload.dat  system_newdevicefound.dat
    platformconfig/system_remoteassistant.dat    system_seenrftutorial.dat
    platformconfig/system_rtd_initbattset.dat    system_rtd_maxbattset.dat
    platformconfig/system_shouldlogevents.dat    system_sound.dat

These are the reason a scaffold exists: undocumented per-model calibration that cannot be
synthesised.

## Present in only some configurations

    system_backlightlevel.dat / system_backlighttimeout.dat   2 of 5
    system_uselargefont.dat                                   4 of 5
    system_favstart.dat                                       3 of 5
    system_childlock.dat                                      1 of 5

So the file *set* is not fixed either - the remote copes with these being absent, which is
why the build does not insist on them.

## Differ between configurations - user state, deliberately neutral here

RF blaster settings, `help.db` (per-activity help text), `system_statetracker.dat`,
theme/time-format/large-font preferences, and `userconfig/SsIr.bin`.
