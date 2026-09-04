#!/usr/bin/env python3
"""The remote's own preferences: `platformconfig/system_*.dat`.

These are the settings a user changes on the remote itself - brightness, sounds, the
clock, the font. Each lives in its own plain-text file, read at boot through a local
`/system/<name>` API (see `SysService.lua`).

## Why this module exists

The time format is stored in **two** places: `<Property name="TimeDisplayFormat">` in
`UserConfiguration.xml` *and* `platformconfig/system_timeformat.dat`. Every real
configuration has them agreeing. Afterglow used to write only the XML, so choosing a
12-hour clock produced a config that contradicted itself - and the `.dat` is the one the
remote actually reads at boot.

Writing a preference means writing every home it has. Anything not set is left exactly as
the scaffold had it, so a build never invents a preference the user did not choose.
"""
from __future__ import annotations

import os

# name -> (file, values or None for free text, also-in-UserConfiguration property)
PREFERENCES = {
    "time_format": ("system_timeformat.dat", ("Military", "Civilian"), "TimeDisplayFormat"),
    "sound": ("system_sound.dat", ("0", "1"), None),
    "theme": ("system_theme.dat", ("0", "1", "2", "3"), None),
    "large_font": ("system_uselargefont.dat", ("0", "1"), None),
    "backlight_level": ("system_backlightlevel.dat", None, None),
    "backlight_timeout": ("system_backlighttimeout.dat", None, None),
    "child_lock": ("system_childlock.dat", ("0", "1"), None),
}

# What the GUI shows. Kept here so the interface and the writer cannot drift apart.
LABELS = {
    "time_format": "Clock",
    "sound": "Key beep",
    "theme": "Theme",
    "large_font": "Large font",
    "backlight_level": "Backlight brightness (%)",
    "backlight_timeout": "Backlight timeout (s)",
    "child_lock": "Child lock",
}
# What a configuration built from nothing starts with. An imported config always brings
# its own values (see `read`), so these only apply to a new project. Where every dump
# here agrees on a value it is used; `backlight_level` is additionally the firmware's
# own initial value in SysService.lua.
DEFAULTS = {
    "time_format": "Military",
    "sound": "0",
    "theme": "0",
    "large_font": "0",
    "backlight_level": "60",
    "backlight_timeout": "10",
    "child_lock": "0",
}
# Bounds for the preferences that are a number rather than a choice.
#
# `backlight_level` is a master brightness on 0-100, not a step setting: SysService.lua
# ramps `0..backlightlevel` and passes it to `env_set_backlight_master_level`. The
# remote's own settings screen offers only three steps - it writes 33/66/100 and reads
# the value back in bands (<40 Low, <70 Medium, else High, `GeneralOptions.as`) - but
# any value in range is honoured, and the dumps here store 60.
#
# `backlight_timeout` is capped at two digits on purpose. The remote parses its own
# field with `int(DurationTF.text.substr(0,2))`, so a stored 120 would read back as 12
# the next time the user opens that screen and silently change the setting.
RANGES = {
    "backlight_level": (0, 100),
    "backlight_timeout": (1, 99),
}
# The four screen themes, named as the remote names them: `content_enu.txt` maps
# `Button_Hennessey` to "Default". The stored values are NOT the on-screen order -
# `GeneralOptions.done_theme()` writes hennessey 0, diode 1, polymer 2, tron 3, while
# the menu lists them Default, Diode, Tron, Polymer and the artwork is prefixed in a
# third order again (01_DIODE_, 02_TRON_, 03_POLYMER_, 04_HENNESSEY_). Only
# `done_theme` decides what lands in system_theme.dat.
CHOICES = {
    "theme": [("Default (Hennessey)", "0"), ("Diode", "1"),
              ("Polymer", "2"), ("Tron", "3")],
    "time_format": [("24-hour", "Military"), ("12-hour", "Civilian")],
    "sound": [("Off", "0"), ("On", "1")],
    "large_font": [("Off", "0"), ("On", "1")],
    "child_lock": [("Off", "0"), ("On", "1")],
}


def apply(work: str, settings: dict) -> list[str]:
    """Write every preference the project sets. Returns the files touched.

    A preference the project does not mention is left alone: the scaffold's value is a
    real remote's value, and replacing it with a guess is worse than leaving it.
    """
    folder = os.path.join(work, "platformconfig")
    written = []
    for key, (filename, _values, _xml) in PREFERENCES.items():
        value = settings.get(key)
        if value in (None, ""):
            continue
        path = os.path.join(folder, filename)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(value))
        written.append(filename)
    return written


def read(extracted_dir: str) -> dict:
    """The preferences a configuration carries, for import."""
    folder = os.path.join(extracted_dir, "platformconfig")
    out = {}
    for key, (filename, _values, _xml) in PREFERENCES.items():
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as handle:
                out[key] = handle.read().strip()
    return out
