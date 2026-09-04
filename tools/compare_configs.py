#!/usr/bin/env python3
"""Compare two configurations by what they *do*, not byte by byte.

    python3 tools/compare_configs.py reference.ezhex mine.ezhex

Two configurations describing the same setup are never byte-identical - ids are
assigned in creation order, and the same activity built twice gets different numbers.
So this matches devices and activities by their labels and compares behaviour:
commands, power handling, states, number entry, roles, power plans, startup and
shutdown actions, favourites, buttons and their macros, RF routing, and preferences.

Ids are reported where they differ but are not treated as a difference in themselves.
Exit status is 1 if anything differs, so it can gate a check.
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex, rf as rf_module          # noqa: E402


def _open(path):
    raw = Path(path).read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    archive = zipfile.ZipFile(io.BytesIO(raw[start:start + size]))
    root = ET.fromstring(archive.read("userconfig/UserConfiguration.xml"))
    return archive, root


def _operation(action):
    operation = action.find("Operation")
    return (operation.findtext("Name"),
            tuple(sorted((p.attrib["name"], p.text)
                         for p in operation.findall("Parameter")
                         if p.attrib["name"] != "DeviceId")),
            _device_of(action))


def _device_of(action):
    found = action.find('Operation/Parameter[@name="DeviceId"]')
    return found.text if found is not None else None


def _action_lists(archive):
    root = ET.fromstring(archive.read("userconfig/ActionLists.xml"))
    return {lst.attrib["name"]: [_operation(a) for a in lst.findall("Action")]
            for lst in root.findall("ActionList")}


def read(path):
    """Everything worth comparing, keyed by label rather than by id."""
    archive, root = _open(path)
    lists = _action_lists(archive)
    names = {d.findtext("Id"): d.find("Presentation/Label").text
             for d in root.findall("Device")}

    def named(device_id):
        return names.get(device_id, device_id)

    def steps(actions):
        return [(name, params, named(device)) for name, params, device in actions]

    devices = {}
    for element in root.findall("Device"):
        numeric = element.find("Numeric")
        devices[element.find("Presentation/Label").text] = {
            "type": element.findtext("Type"),
            "commands": sorted(c.findtext("Name")
                               for c in element.findall("Commands/Command")),
            "states": sorted(s.findtext("Id")
                             for s in element.findall("States/State")),
            "digits": len(element.findall("Numeric//Digit")),
            "numeric_finish": numeric is not None
                              and numeric.find("Finish") is not None,
            "properties": {p.attrib["name"]: p.text
                           for p in element.findall("Properties/Property")},
            "hard_keys": sorted(
                b.attrib["name"] for b in element.findall(
                    'Presentation/ControlGroup[@name="HardButtons"]/Button')),
        }

    activities = {}
    for element in root.findall("Activity"):
        label = element.find("Presentation/Label").text
        buttons = {}
        for button in element.findall(
                'Presentation/ControlGroup[@name="Misc"]/Button'):
            action_id = button.findtext("ActionId")
            buttons[button.findtext("Label")] = {
                "icon": button.findtext("Icon"),
                "steps": steps(lists.get(action_id, [])) or f"-> {action_id}",
            }
        identifier = element.findtext("Id")
        activities[label] = {
            "type": element.findtext("Type"),
            "roles": sorted((r.findtext("Name"), named(r.findtext("DeviceId")))
                            for r in element.findall("Role")),
            "power_on": [named(e.text) for e in element.findall("Power/On")],
            "power_off": sorted(named(e.text)
                                for e in element.findall("Power/Off")),
            "enter": steps([_operation(a)
                            for a in element.findall("EnterActions/Action")]),
            "leave": steps([_operation(a)
                            for a in element.findall("LeaveActions/Action")]),
            "favourites": [(c.findtext("Station"), c.findtext("Number"),
                            c.findtext("Image"),
                            steps([_operation(a)
                                   for a in c.findall("Actions/Action")]))
                           for c in element.findall(".//Channel")],
            "buttons": buttons,
            "hard_macros": {
                name.split("_hardmacro_")[-1]: steps(actions)
                for name, actions in lists.items()
                if name.startswith(f"{identifier}_hardmacro_")},
            "properties": {p.attrib["name"]: p.text
                           for p in element.findall("Properties/Property")},
        }

    settings = {name.split("/")[-1]: archive.read(name).decode().strip()
                for name in archive.namelist()
                if name.startswith("platformconfig/system_")}
    images = sorted(name.split("/")[-1] for name in archive.namelist()
                    if name.startswith("userconfig/image/") and "." in name)
    rf = rf_module.parse_rf_xml(
        archive.read("platformconfig/XmlUserRfSetting.xml").decode())
    routing = {}
    if rf:
        by_label = {str(r["label"]): r["mac"] for r in rf["receivers"]}
        for device_id, token in (rf.get("assign") or {}).items():
            label, _, port = token.partition("-")
            routing[named(device_id)] = (by_label.get(label, label), port or "all")
    return {"devices": devices, "activities": activities, "settings": settings,
            "images": images, "routing": routing,
            "bases": sorted(str(r["label"]) for r in (rf or {}).get("receivers", []))}


def compare_section(title, left, right, findings):
    print(f"\n{title}\n" + "=" * 66)
    for name in sorted(set(left) | set(right)):
        if name not in left:
            print(f"  + {name}: only in the second"); findings.append(name); continue
        if name not in right:
            print(f"  - {name}: MISSING from the second"); findings.append(name); continue
        differences = {key: (left[name][key], right[name][key])
                       for key in left[name] if left[name][key] != right[name][key]}
        if not differences:
            print(f"  = {name}")
            continue
        findings.append(name)
        print(f"  ! {name}")
        for key, (a, b) in differences.items():
            print(f"      {key}:")
            print(f"         first : {a}")
            print(f"         second: {b}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args(argv)

    left, right = read(args.first), read(args.second)
    findings: list[str] = []
    print(f"{args.first.name}  vs  {args.second.name}")
    compare_section("DEVICES", left["devices"], right["devices"], findings)
    compare_section("ACTIVITIES", left["activities"], right["activities"], findings)

    for title, key in (("PREFERENCES", "settings"), ("IR ROUTING", "routing")):
        print(f"\n{title}\n" + "=" * 66)
        a, b = left[key], right[key]
        for name in sorted(set(a) | set(b)):
            if a.get(name) == b.get(name):
                continue
            findings.append(f"{key}:{name}")
            print(f"  ! {name}: first={a.get(name)!r}  second={b.get(name)!r}")
        if not any(f.startswith(f"{key}:") for f in findings):
            print(f"  = all {len(a)} match")

    print("\nFAVOURITE IMAGES\n" + "=" * 66)
    if left["images"] == right["images"]:
        print(f"  = {left['images']}")
    else:
        findings.append("images")
        print(f"  first : {left['images']}")
        print(f"  second: {right['images']}")

    print("\n" + "=" * 66)
    print("Identical in behaviour." if not findings
          else f"{len(findings)} difference(s).")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
