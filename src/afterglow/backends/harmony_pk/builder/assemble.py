"""Assembling a finished Harmony PK config tree.

Takes the device and activity XML, drops it into a copy of the base tree, applies the
IR routing, and writes the IrProto the devices need. The result is a directory ready
for `afterglow.ezhex` to pack.
"""
from copy import deepcopy
from dataclasses import dataclass
import os
import shutil
import xml.etree.ElementTree as ET

from .... import paths
from ....preferences import apply as apply_preferences
from ....rf import apply_rf_setting
from .. import irproto, ssir
from . import protocols
from .activities import _gen_activity
from .codes import esc
from .devices import _gen_device

# The config skeleton copied into the work tree: platformconfig, boot scripts and a
# UserConfiguration carrying the Properties/User shell.
#
# This defaults to the bundled scaffold and must never default to a real config. It used
# to point at the user's own dump, so any caller that forgot to pass `base_dir` silently
# inherited that remote's state - its RF blaster registration, its device-to-blaster map,
# anything else unmodelled - into a supposedly fresh build, without saying so.
BASE = str(paths.scaffolds("harmony-900"))


@dataclass(frozen=True)
class BuildRequest:
    """Everything a build needs besides the devices and the directory to write into.

    These six travelled as optional positional parameters, where the call site said
    nothing about which was which and adding a seventh meant touching every caller.
    `build_tree` remains the portable contract and keeps its keyword form; this is the
    shape those keywords take once inside this backend.
    """

    activities: list | None = None
    settings: dict | None = None
    base_dir: str | None = None
    protocol_meta_by_id: dict | None = None
    power_off_all: list | None = None
    power_off_label: str | None = None


def _check_unique_ids(specs, activities):
    """Two things sharing an id is silent data loss.

    The remote keys everything by id: activities and devices reference each other by
    it, and it stores one entry per id. Give two activities the same one and it keeps
    a single activity - the config builds, verifies, flashes, and the others are
    simply not there. That happened: an id generator counting from zero each time the
    application started handed the same id to the first activity of every session.
    """
    from collections import Counter

    for kind, items in (("device", specs or []), ("activity", activities or [])):
        counts = Counter(str(item.get("id")) for item in items)
        clashes = {ident: n for ident, n in counts.items() if n > 1}
        if not clashes:
            continue
        named = []
        for ident in clashes:
            labels = [item.get("label", "?") for item in items
                      if str(item.get("id")) == ident]
            named.append(f"{ident} is shared by {', '.join(repr(l) for l in labels)}")
        plural = "activities" if kind == "activity" else "devices"
        raise ValueError(
            f"Two or more {plural} share an id, and the remote would keep only one of "
            "each:\n  " + "\n  ".join(named))


def _repair_scaffold_line_endings(work) -> None:
    """Put back the line endings the remote needs, and say so.

    Format reference: docs/harmony_pk/configuration.md - the tree mixes LF and CRLF deliberately,
    and the install scripts fail unreadably if converted.

    Nothing later in the build can see this: the copy is faithful, the container is well
    formed, `unpack -> pack` round-trips, and the damage is invisible until a remote
    refuses the result. A checkout with `core.autocrlf` is enough to cause it.

    Repairs the *working copy*, never the source, so a mangled checkout still yields a
    configuration that flashes. Reported rather than done quietly, because the fault is
    upstream in whatever converted the files - `.gitattributes` marks the scaffold
    `-text` for that reason.

    Narrow on purpose: `.version` and `META-INF/MANIFEST.MF` are CRLF on the remote
    itself, so converting everything would be its own corruption.
    """
    repaired = []
    for root, _dirs, files in os.walk(work):
        for name in files:
            path = os.path.join(root, name)
            relative = os.path.relpath(path, work).replace(os.sep, "/")
            if not (relative in (".preinstall", ".postinstall")
                    or relative.startswith("platformconfig/")):
                continue
            with open(path, "rb") as handle:
                data = handle.read()
            if b"\x00" in data or b"\r\n" not in data:
                continue
            with open(path, "wb") as handle:
                handle.write(data.replace(b"\r\n", b"\n"))
            repaired.append(relative)
    if repaired:
        print(f"Warning: {len(repaired)} scaffold file(s) had Windows line endings and "
              f"were converted back to Unix line endings for this build: "
              f"{', '.join(sorted(repaired))}. The remote runs .preinstall/.postinstall "
              f"with /bin/sh and would have rejected the configuration. Your checkout of "
              f"the scaffold is affected - see .gitattributes.")


def build(specs, work, request: BuildRequest | None = None):
    """Build a complete config tree from device specs and activities."""
    request = request or BuildRequest()
    activities = request.activities
    protocol_meta_by_id = request.protocol_meta_by_id
    power_off_all = request.power_off_all
    power_off_label = request.power_off_label
    base = request.base_dir or BASE
    settings = request.settings or {}
    # Assembly stamps its own transient fields onto these specs: the runtime protocol
    # index each command resolved to, the block ids behind them, and raw codes renumbered
    # to their place in the rebuilt table. Those belong to this build, not to whatever the
    # caller intends to do with its own data afterwards. Every current caller happens to
    # pass a transient it owns; copying here makes that a property of this function
    # instead of something each caller has to know.
    specs = deepcopy(specs)
    # Recorded waveforms: carry only the ones the devices actually use, renumbered to
    # their place in the rebuilt table. An index is a position, not an identity - the
    # same rule the protocol assembler follows.
    raw_entries, raw_remap = ssir.collect(specs)
    for spec in specs:
        for name, code in list((spec.get("raw_codes") or {}).items()):
            new = raw_remap.get((spec["id"], name))
            if new:
                spec["raw_codes"][name] = new

    _check_unique_ids(specs, activities)
    protocols.validate(specs)
    block_order = protocols.resolve(specs)
    # Per-protocol metadata (toggle bits) re-emitted at whatever index each block
    # landed at this time round. Carried by id, written by position.
    protocol_meta = {block_id: (protocol_meta_by_id or {}).get(block_id)
                     for block_id in block_order}
    protocol_entries = "".join(
        f'<Protocol index="{index}">{inner}</Protocol>'
        for index, (block_id, inner) in enumerate(protocol_meta.items()) if inner)

    # The all-off activity. When a config was imported it says which devices it turns
    # off; otherwise every device that can be powered off is listed.
    carried_off = [str(d) for d in (power_off_all or [])]
    devices=[]; actionlists=[]; poff_enter=[]; poff_off=[]
    for spec in specs:
        dev, al = _gen_device(spec)
        devices.append(dev); actionlists.append(al)
        # Anything that can be turned off belongs here, including a device with a
        # discrete Off and no discrete On - ordinary for a stereo with a dedicated
        # standby key. Requiring a matched pair leaves such devices running.
        has_power = (spec.get("power_cmd") or spec.get("power_off_cmd")
                     or spec.get("power_on_cmd"))
        # A union, not a choice: the imported list is frozen at whatever the config
        # said when read, so a device added afterwards would be left running by the one
        # activity whose job is turning everything off. Every donor's all-off activity
        # lists every device it has, so nothing is lost by adding.
        wanted = (str(spec["id"]) in carried_off
                  or (has_power and not spec.get("always_on")))
        if wanted:                                    # AlwaysOn devices never get powered off
            poff_enter.append(
                f"<Action><Target>Device</Target><Operation><Name>SetValue</Name>"
                f'<Parameter name="DeviceId">{spec["id"]}</Parameter>'
                f'<Parameter name="State">Power</Parameter>'
                f'<Parameter name="Value">Off</Parameter></Operation></Action>')
            poff_off.append(spec["id"])

    with open(f"{base}/userconfig/UserConfiguration.xml", encoding="utf-8", errors="replace") as file:
        uc = file.read()
    root = ET.fromstring(uc)

    user = root.find("User/Presentation")
    if user is not None:
        if settings.get("first_name"):
            user.find("FirstName").text = settings["first_name"]
        if settings.get("last_name"):
            user.find("LastName").text = settings["last_name"]
            
    time_fmt_node = root.find("User/Properties/Property[@name='TimeDisplayFormat']")
    if time_fmt_node is not None and settings.get("time_format"):
        time_fmt_node.text = settings["time_format"]
        
    locale_node = root.find("User/Properties/Property[@name='LocaleId']")
    if locale_node is not None and settings.get("locale"):
        locale_node.text = settings["locale"]

    # NewDeviceFound runs the remote's new-device walkthrough over the devices carrying
    # IsNewDevice, so the two have to agree. Claiming one while flagging none is a state
    # no real configuration is in and the remote does not cope: the walkthrough starts
    # with an empty list, the power-on test shows nothing, and Next offers to turn off
    # "undefined". The scaffold carries the flag, so it is removed unless a device is
    # genuinely new.
    new_found = root.find("User/Properties/Property[@name='NewDeviceFound']")
    if new_found is not None:
        anybody_new = any(str((spec.get("properties") or {}).get("IsNewDevice", ""))
                          .lower() == "true" for spec in specs)
        if not anybody_new:
            root.find("User/Properties").remove(new_found)

    for d in root.findall("Device"): root.remove(d)
    for a in root.findall("Activity"): root.remove(a)
    for dev in devices: root.append(ET.fromstring(dev))
    by_id = {s["id"]: s for s in specs}
    for act in (activities or []):                 # user activities (Watch TV, ...)
        act_xml, macro_als = _gen_activity(act, by_id, settings.get("remote"))
        root.append(ET.fromstring(act_xml))
        actionlists.extend(macro_als)              # macro buttons need their own ActionLists
    activity = (f"<Activity><Id>-1</Id><Type>PowerOff</Type>"
                f"<Presentation><Label>{esc(power_off_label or 'PowerOff')}</Label>"
                "</Presentation>"
                f"<EnterActions>{''.join(poff_enter)}</EnterActions>"
                f"<Power>{''.join('<Off>%s</Off>'%i for i in poff_off)}</Power></Activity>")
    root.append(ET.fromstring(activity))

    # Every real configuration ends with <Protocols>; this project's put it before the devices,
    # because the scaffold already contains it and the devices are removed and appended
    # after. Nothing has been shown to depend on the order, but "differs from every real
    # config in a way nobody chose" is exactly the shape of the last several faults, and
    # this project's own rule is not to reorder what it does not model.
    protocols_el = root.find("Protocols")
    if protocols_el is not None:
        root.remove(protocols_el)
        root.append(protocols_el)

    new_uc = '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")
    actionlists_xml = '<?xml version="1.0" encoding="UTF-8"?><Root>' + "".join(actionlists) + "</Root>"

    if os.path.exists(work): shutil.rmtree(work)
    # Documentation dropped next to a scaffold must not end up inside the flashed
    # configuration. A config tree never contains markdown, so ignoring it is safe - and
    # a stray CONTENTS.md silently riding along has already happened once.
    shutil.copytree(base, work, ignore=shutil.ignore_patterns("*.md"))
    _repair_scaffold_line_endings(work)
    # Do not swap platformconfig/ from another dump. A donor's own platformconfig
    # flashes unmodified, but mixing trees silently replaces help.db,
    # system_statetracker.dat and the timeformat/childlock/backlight state files - a
    # change with no accepted sample. Keep `base`'s platformconfig and touch only the RF
    # map below.
    #
    # A donor base tree ships an RF map pointing at the donor's wireless blaster;
    # settings["rf"]="front" rewrites it so every device emits from this remote's front
    # IR LED (see rf.apply_rf_setting). Stale assignments are pruned so the map can never
    # reference a device this config does not have.
    rf = (settings or {}).get("rf")
    if isinstance(rf, dict) and rf.get("assign"):
        ids = {str(s.get("id")) for s in specs}
        rf = {**rf, "assign": {d: t for d, t in rf["assign"].items() if str(d) in ids}}
    apply_rf_setting(work, rf)
    # The remote's own preferences live in platformconfig/system_*.dat. The time format
    # is ALSO an XML property below; both have to be written or the config disagrees with
    # itself and the remote follows the file, not the XML.
    apply_preferences(work, settings)
    # The scaffold's <Protocols> holds only a <Hash>; put the carried per-protocol
    # entries back in front of it, where real configs keep them.
    if protocol_entries:
        new_uc = new_uc.replace("<Protocols>", f"<Protocols>{protocol_entries}", 1)
    # Both files declare UTF-8 in their XML header, so both have to be written as UTF-8.
    # Without the encoding this one took the platform default, which is the ANSI code page
    # on Windows: a command name outside it stops the build with a UnicodeEncodeError, and
    # one inside it is written as cp1252 bytes in a file that says it is UTF-8. `esc()`
    # escapes only & < >, so any non-ASCII command name reaches here as itself.
    with open(f"{work}/userconfig/UserConfiguration.xml", "w", encoding="utf-8") as file:
        file.write(new_uc)
    with open(os.path.join(work, "userconfig", "ActionLists.xml"),
              "w", encoding="utf-8") as f:
        f.write(actionlists_xml)

    # Assemble the final IrProto.bin from the ordered library blocks the devices actually use
    # (each generated at the position it lands in, so there is no relocation step).
    total = sum(len(s["commands"]) for s in specs)
    definitions = {}
    for spec in specs:
        for block_id, definition in (spec.get("protocol_definitions") or {}).items():
            existing = definitions.get(block_id)
            if existing is not None and existing != definition:
                raise ValueError(
                    f"Devices carry conflicting definitions for protocol block {block_id}")
            definitions[block_id] = definition
    irproto.write_payload(os.path.join(work, "userconfig", "IrProto.bin"),
                          irproto.assemble(block_order, definitions))
    ssir.write(os.path.join(work, "userconfig", "SsIr.bin"), raw_entries)
    print(f"built {len(specs)} device(s), {total} commands, {len(block_order)} protocol block(s) "
          f"[{', '.join(block_order)}] -> {work}/")
