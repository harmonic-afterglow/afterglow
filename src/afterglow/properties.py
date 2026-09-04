#!/usr/bin/env python3
"""Device and activity `<Property>` entries: what they are, and what they may be set to.

A configuration carries around forty of these. They are how a device says what it *is*
(a tuner's input, a changer's disc count, whether a recorder has an on-screen guide) and
how an activity says how it should *behave* (which page it opens on, which help to show,
whether unused devices power off). The remote changes its behaviour based on them.

The failure this module exists to prevent is a setting that is present in the config,
invisible in the interface, and therefore impossible to find when it is the cause of a
problem.

## The rule

**Preserve everything, describe what is known, and never hide the rest.** A property with
no description is still listed, still editable and still written back - it is shown with
its raw name rather than quietly discarded. `library/properties.json` records the values
actually observed across real configurations, which is evidence, not a closed set: a
config may legitimately use a value not seen before, and that is not an error.

## Casing is load-bearing

Devices write `true`/`false`; activities write `True`/`False`. The same word in the wrong
case is a different string to the remote, so the catalog records which convention each
scope uses and `format_value()` applies it.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths

CATALOG_PATH = paths.library("properties.json")

DEVICE = "device"
ACTIVITY = "activity"


def definitions(path: Path | str = CATALOG_PATH) -> dict:
    """What each property IS - type, casing, label, meaning. Shared across models."""
    path = Path(path)
    if not path.is_file():
        return {DEVICE: {}, ACTIVITY: {}}
    return json.loads(path.read_text())


def catalog(remote=None, path: Path | str = CATALOG_PATH) -> dict:
    """The properties one remote has, each described as fully as it is known.

    Two sources, deliberately. A property called AlwaysOn means the same thing on any
    Harmony, so its type, its casing and its description are shared. But *which*
    properties a model has, which of its device types use each one, and what its
    firmware does when one is missing are facts about that model - and the sets differ,
    so a remote can offer options the 900 has never heard of and lack ones it has.

    A property the remote declares but nothing describes still comes through, with
    whatever the remote knows about it; a description with no remote declaring it does
    not, because it is not a setting on this remote.
    """
    from . import remotes as _remotes

    described = definitions(path)
    if hasattr(remote, "vocabulary"):
        profile = remote
    elif remote:
        try:
            profile = _remotes.get(remote)
        except LookupError:
            # Named a remote the library does not have. Describing everything is the
            # right answer; raising would leave the interface with no property list at
            # all because one lookup missed.
            profile = None
    else:
        # Nothing named: the first verified profile, if the library has one. An empty
        # library, or one where every profile is still `untested`, is an ordinary state
        # rather than a failure - `load_all` already reports the profiles it skipped.
        profile = next((p for p in _remotes.load_all() if p.verified), None)
    # A profile is not required to declare properties, and `remote` may be any object
    # with a vocabulary. Both mean "nothing declared", which is not the same as an error
    # - and a bare `except` here used to report a genuine fault as exactly that.
    declared = getattr(profile, "properties", None) or {}
    if not declared:                 # nothing said: fall back to describing everything
        return {scope: dict(described.get(scope, {})) for scope in (DEVICE, ACTIVITY)}

    merged = {}
    for scope in (DEVICE, ACTIVITY):
        merged[scope] = {
            name: {**described.get(scope, {}).get(name, {}), **facts}
            for name, facts in (declared.get(scope) or {}).items()
        }
    return merged


def describe(scope: str, name: str, cat: dict | None = None) -> dict:
    """What is known about one property. Always returns something usable, so an unknown
    name is still presentable rather than a hole in the interface."""
    cat = cat if cat is not None else catalog()
    entry = dict(cat.get(scope, {}).get(name) or {})
    entry.setdefault("type", "text")
    entry.setdefault("label", name)
    entry.setdefault("description", "")
    entry["known"] = name in cat.get(scope, {})
    return entry


def known(scope: str, cat: dict | None = None) -> dict:
    cat = cat if cat is not None else catalog()
    return cat.get(scope, {})


def format_value(scope: str, name: str, value, cat: dict | None = None) -> str:
    """A Python value as this property's XML text, in the casing its scope uses."""
    entry = describe(scope, name, cat)
    if entry["type"] == "bool":
        text = "true" if (value if isinstance(value, bool) else str(value).lower() == "true") else "false"
        return text.capitalize() if entry.get("casing") == "title" else text
    return str(value)


def parse_value(scope: str, name: str, text, cat: dict | None = None):
    """XML text as a Python value, for editing."""
    entry = describe(scope, name, cat)
    if entry["type"] == "bool":
        return str(text).strip().lower() == "true"
    if entry["type"] == "int":
        try:
            return int(text)
        except (TypeError, ValueError):
            return 0
    return "" if text is None else str(text)


def suggestions(scope: str, name: str, cat: dict | None = None) -> list:
    """Values seen in real configurations - offered, never enforced."""
    entry = describe(scope, name, cat)
    if entry["type"] == "enum" and entry.get("values"):
        return list(entry["values"])
    return list((entry.get("observed") or {}).keys())


def unmodelled(scope: str, properties: dict, cat: dict | None = None) -> list:
    """Names in `properties` that this build of Afterglow has no description for."""
    have = known(scope, cat)
    return sorted(n for n in properties if n not in have)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="List the known configuration properties.")
    parser.add_argument("scope", nargs="?", choices=[DEVICE, ACTIVITY])
    args = parser.parse_args(argv)
    cat = catalog()
    for scope in ([args.scope] if args.scope else [DEVICE, ACTIVITY]):
        print(f"== {scope} ==")
        for name, entry in sorted(cat.get(scope, {}).items()):
            kind = entry["type"]
            if kind == "enum":
                kind += " " + "/".join(entry.get("values", []))
            print(f"  {entry.get('label', name):28} {kind:28} {name}")
            if entry.get("description"):
                print(f"  {'':28} {entry['description']}")
        print()


if __name__ == "__main__":
    main()
