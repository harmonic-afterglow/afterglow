#!/usr/bin/env python3
"""What does importing a config and rebuilding it lose?

    python3 tools/audit_import.py home.ezhex

Reads a config, turns it into a project the way the GUI's import does, builds it back,
and reports everything that did not survive the trip.

## Why this exists

An importer that silently drops what it does not understand is the most expensive kind
of bug in this project. A device's discrete power actions, its input states, an RF
blaster assignment - each of those is invisible in the UI, absent from the rebuilt
config, and only shows up as hardware behaving wrongly days later. Whole debugging
sessions have gone into symptoms whose real cause was a setting that was never
surfaced.

So: measure it. Anything this reports as lost is either a feature to model or a
deliberate, written-down decision - never a surprise.

Exit status is 1 if anything was lost, so it can gate a release.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex  # noqa: E402
from afterglow.build_service import ConfigBuildService  # noqa: E402
from afterglow.importer import build_project  # noqa: E402

# Elements the builder is expected to regenerate rather than carry across, with the
# reason. Anything NOT listed here that goes missing is a genuine gap.
EXPECTED = {}


def counts(xml: str, pattern: str) -> collections.Counter:
    return collections.Counter(re.findall(pattern, xml))


# --- what a device and an activity actually DO ------------------------------------
#
# Element counts can only say "something went missing". They cannot say a television
# lost its power-on, because the counts are dominated by the hundreds of <Parameter>
# elements under it. This reads the behaviour instead, per device, so a loss names the
# thing it broke.
def device_behaviour(element) -> dict:
    """The behaviour of one <Device>, in a form two configs can be compared by."""
    states = {}
    for state in element.findall("States/State"):
        ident = state.findtext("Id") or "?"
        # A state's actions may sit under DiscreteActions (pick a value directly) or
        # RelativeActions (step to the next one), and either may be Set/Change/Next.
        actions = set()
        for kind in ("DiscreteActions", "RelativeActions"):
            for group in element.findall(f"States/State[Id='{ident}']/{kind}"):
                for action in group:
                    name = action.findtext("Name")
                    actions.add(f"{action.tag}:{name}" if name else action.tag)
        states[ident] = actions
    numeric = element.find("Numeric")
    return {
        "type": element.findtext("Type"),
        "states": states,
        "digits": len(numeric.findall(".//Digit")) if numeric is not None else 0,
        "commands": {c.findtext("Name") for c in element.findall("Commands/Command")},
    }


def activity_behaviour(element) -> dict:
    return {
        "type": element.findtext("Type"),
        "roles": {r.tag: r.text for r in element.findall("Roles/*")},
        "buttons": {b.findtext("Name") for b in element.findall(".//Button")},
        "groups": {g.attrib.get("name") for g in element.findall(".//ControlGroup")},
    }


def behaviour_of(xml: str) -> dict:
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    return {
        "devices": {d.findtext("Id"): device_behaviour(d) for d in root.findall("Device")},
        "activities": {a.findtext("Id"): activity_behaviour(a)
                       for a in root.findall("Activity")},
    }


def report_behaviour(src: str, out: str) -> int:
    """Differences in what devices and activities do. Returns the number found."""
    before, after = behaviour_of(src), behaviour_of(out)
    findings = 0
    for kind in ("devices", "activities"):
        for ident, was in before[kind].items():
            now = after[kind].get(ident)
            if now is None:
                continue                      # reported separately as an outright loss
            for field, old in was.items():
                new = now.get(field)
                if old == new:
                    continue
                findings += 1
                label = f"{kind[:-1]} {ident} ({was.get('type')})"
                if isinstance(old, dict):
                    for key, value in old.items():
                        if new.get(key) != value:
                            print(f"  {label}: {field}[{key}] "
                                  f"{sorted(value) if isinstance(value, set) else value} "
                                  f"-> {sorted(new[key]) if key in new else 'GONE'}")
                elif isinstance(old, set):
                    missing = old - (new or set())
                    if missing:
                        print(f"  {label}: {field} lost {sorted(missing)}")
                    else:
                        findings -= 1         # gained only; not a loss
                else:
                    print(f"  {label}: {field} {old!r} -> {new!r}")
    return findings


def audit(config: Path) -> int:
    work = Path(tempfile.mkdtemp())
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(config), str(work / "src"))
    project = build_project(str(work / "src"))
    project["settings"].update(out_file=str(work / "rebuilt.ezhex"),
                               remote="harmony-900")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ConfigBuildService(ROOT, lambda _m: None).build(project)
            ezhex.unpack(str(work / "rebuilt.ezhex"), str(work / "out"))
    except Exception as exc:
        print(f"REBUILD FAILED: {type(exc).__name__}: {exc}")
        return 1

    original = config.read_bytes()
    rebuilt = (work / "rebuilt.ezhex").read_bytes()
    print(f"{config.name}: {len(original)} bytes -> {len(rebuilt)} rebuilt "
          f"({'byte-identical' if original == rebuilt else 'differs'})\n")

    src = (work / "src" / "userconfig" / "UserConfiguration.xml").read_text(errors="replace")
    out = (work / "out" / "userconfig" / "UserConfiguration.xml").read_text(errors="replace")

    findings = 0
    checks = [
        ("XML elements", r"<([A-Za-z]+)[ />]"),
        ("device / activity properties", r'<Property name="([^"]+)"'),
        ("control groups", r'<ControlGroup name="([^"]+)"'),
        ("button icons", r"<Icon>([^<]*)</Icon>"),
    ]
    for title, pattern in checks:
        lost = counts(src, pattern) - counts(out, pattern)
        lost = {k: v for k, v in lost.items() if k not in EXPECTED}
        if lost:
            findings += sum(lost.values())
            print(f"  LOST {title}:")
            for name, n in sorted(lost.items(), key=lambda kv: -kv[1]):
                print(f"      {name} x{n}")

    # Per-device and per-activity presence, which the raw counts can hide.
    for tag, key in (("Device", "devices"), ("Activity", "activities")):
        before = set(re.findall(rf"<{tag}><Id>(\d+)</Id>", src))
        after = set(re.findall(rf"<{tag}><Id>(\d+)</Id>", out))
        if before - after:
            findings += len(before - after)
            print(f"  LOST {tag.lower()}s entirely: {sorted(before - after)}")

    behaviour = report_behaviour(src, out)
    if behaviour:
        findings += behaviour

    print("\nNothing lost." if not findings else f"\n{findings} item(s) not carried across.")
    return 1 if findings else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("configs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    status = 0
    for config in args.configs:
        status |= audit(config)
        print()
    return status


if __name__ == "__main__":
    sys.exit(main())
