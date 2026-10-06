#!/usr/bin/env python3
"""The remote's own preferences: `platformconfig/system_*.dat`.

These are the settings a user changes on the remote itself - brightness, sounds, the
clock, the font. Each lives in its own plain-text file, read at boot through a local
`/system/<name>` API (see `SysService.lua`).

Which ones a remote has, what they are called, their values and their ranges differ by
model - the Harmony 900 has a theme and a child lock, the 1100 has neither and keeps its
backlight on a different scale - so they are defined in the remote's profile
(`preferences` in `library/remotes/<id>.json`), and every function here takes the
profile they apply to.

## Why this module exists

The time format is stored in **two** places: `<Property name="TimeDisplayFormat">` in
`UserConfiguration.xml` *and* `platformconfig/system_timeformat.dat`. Every real
configuration has them agreeing. Afterglow used to write only the XML, so choosing a
12-hour clock produced a config that contradicted itself - and the `.dat` is the one the
remote actually reads at boot. A definition's `xml_property` names that second home.

Writing a preference means writing every home it has. Anything not set is left exactly as
the scaffold had it, so a build never invents a preference the user did not choose.
"""
from __future__ import annotations

import os


def definitions(profile) -> dict:
    """{key: definition} for `profile`'s remote, in the order the interface shows them."""
    return profile.preferences


def choices(definition: dict) -> list[tuple[str, str]]:
    """[(label, stored value)] for a preference that is a choice, else []."""
    return [tuple(pair) for pair in definition.get("choices") or []]


def bounds(definition: dict) -> tuple[int, int] | None:
    """(low, high) for a preference that is a number, else None."""
    low_high = definition.get("range")
    return (int(low_high[0]), int(low_high[1])) if low_high else None


def apply(work: str, settings: dict, profile) -> list[str]:
    """Write every preference the project sets. Returns the files touched.

    A preference the project does not mention is left alone: the scaffold's value is a
    real remote's value, and replacing it with a guess is worse than leaving it. One the
    remote does not have is never written, whatever the project carries.
    """
    folder = os.path.join(work, "platformconfig")
    written = []
    for key, definition in definitions(profile).items():
        value = settings.get(key)
        if value in (None, ""):
            continue
        path = os.path.join(folder, definition["file"])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(value))
        written.append(definition["file"])
    return written


def read(extracted_dir: str, profile) -> dict:
    """The preferences a configuration carries, for import."""
    folder = os.path.join(extracted_dir, "platformconfig")
    out = {}
    for key, definition in definitions(profile).items():
        path = os.path.join(folder, definition["file"])
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as handle:
                out[key] = handle.read().strip()
    return out
