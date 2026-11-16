"""The Harmony 700 backend: build a configuration from a project, and read one back.

A build generates the whole arch-14 image from the project's devices, activities and
settings and the scaffold's platform models (compose.py) - nothing is carried from a
previous configuration. Reading an
image validates it and recovers what is proven of its devices, keeping the native payload
unchanged.

Format reference: docs/harmony_650_700/gspm.md, docs/harmony_one/README.md
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
import shutil
import struct
import tempfile

from ... import ezhex, payloads
from ..contracts import BuildResult, ImportResult
from . import command_index, font_index, gspm, importing, inventory, labels


# The types a device and an activity get when none is recognised: "Home appliance" and
# "Custom / Other".
GENERIC_DEVICE = "HomeAppliance"
GENERIC_ACTIVITY = "VirtualGeneric"


def afterglow_built(payload: bytes) -> bool | None:
    """Whether ``payload`` is one of Afterglow's builds, for the app's "first flash"
    decision before a write (settings.welcome): True for ours, False for Logitech's or
    nothing readable, None when it cannot tell. Logitech's compiles draw Logitech's
    letters, and every build of ours draws its own font or a theme's (labels.Text.logitech),
    as the Harmony One's backend tells them apart."""
    try:
        gspm.validate(payload)
        drawn = sum(len(font["glyphs"]) for font in font_index.fonts(payload))
        text = labels.Text(payload)
    except (ValueError, IndexError, KeyError, struct.error):
        return False
    if not drawn:                       # no letters at all: nothing to tell it by
        return None
    return not text.logitech


def validate_payload(payload: bytes, _profile=None) -> dict:
    return gspm.validate(payload)


def compare_payloads(recovery: bytes, candidate: bytes, _profile) -> dict:
    """What a write changes, section by section, for review before Test write writes it
    (first_write.py)."""
    def sections(payload):
        return {f"section {index}": hashlib.sha256(payload[start:end]).hexdigest()
                for index, (start, end) in gspm.section_ranges(payload).items()}

    before, after = sections(recovery), sections(candidate)
    return {
        "kind": "gspm-section-sha256",
        "size before": len(recovery),
        "size after": len(candidate),
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": sorted(name for name in before.keys() & after.keys()
                          if before[name] != after[name]),
        "unchanged": sum(before[name] == after[name] for name in before.keys() & after.keys()),
    }


def import_project(source, profile, context) -> ImportResult:
    """Read an image back as a project (importing.py): its devices with their commands,
    names, power, inputs and keys, and its activities. The image itself is kept as
    evidence, unchanged."""
    carrier = payloads.get(profile.payload)
    payload = carrier.build(source)
    validation = validate_payload(payload, profile)
    native = inventory.inspect(payload)
    ownership = native["ownership"]
    notes: list[str] = []
    naming: dict = {}
    image = importing.Image(payload)
    devices = importing.project_devices(image, command_index.portable_devices(
        ownership, native["keys"], native["ui"]["device_menus"]), notes, naming)
    # each type from the icon its menu row draws, before the activities, whose display
    # is the device among theirs that shows a picture
    types = importing.read_types(image)
    for index, device in enumerate(devices):
        device["type"] = types.get(("device", index)) or device.get("type")
    # favourites' logos go to the owner's logos folder, by the configuration's name
    from ... import paths
    name = (context.get("name") or Path(str(source)).name.removesuffix("_extracted")
            or "imported")
    logos = paths.logos_dir() / "Imported" / name
    activities, off = importing.Activities(image, devices, naming, notes, logos).read()
    # A 700's menu rows draw no icon, so no row says a type: a device is a Home appliance
    # and an activity "Custom / Other", as an editor would otherwise open them as types they
    # are not. On a 700 a type names nothing it draws.
    for index, device in enumerate(devices):
        device["type"] = types.get(("device", index)) or GENERIC_DEVICE
    for activity in activities:
        activity["type"] = types.get(("activity", int(activity["id"]))) or GENERIC_ACTIVITY
    # the devices as the Devices list shows them - activities name them by id, so this
    # comes after them
    rank = {index: at for at, index in enumerate(importing.device_list_order(image)[0])}
    devices = [device for _key, device in sorted(
        enumerate(devices), key=lambda pair: (rank.get(pair[0], len(rank)), pair[0]))]
    # a name with a character the text reader does not know is said, to be put right
    unread = [label for label in (
        [device["label"] for device in devices]
        + [name for device in devices for name in device["signals"]]
        + [activity["label"] for activity in activities]) if labels.UNKNOWN in label]
    if unread:
        notes.append("these names have characters that could not be read (shown as "
                     f"{labels.UNKNOWN}): " + ", ".join(repr(name) for name in unread))
    notes += [f"could not read the image's {item}" for item in image.unreadable]
    settings = {"remote": profile.id, **importing.remote_settings(image)}
    if not activities:
        settings.pop("remote_assistant", None)      # its note follows a start: nothing to say
    if context.get("out_file"):
        settings["out_file"] = str(context["out_file"])
    return ImportResult(
        project={"devices": devices, "activities": activities, "assets": [],
                 "settings": settings, **off},
        preservation={
            "mode": "opaque-native-payload",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "validation": validation,
            "inventory": native,
        },
        warnings=tuple(notes),
        rejected={
            "native_objects": max(
                0, native["objects"]["objects"] - ownership["counts"]["command_objects"]),
            "native_commands": sum(ownership["rejected"].values()),
            "native_payload_bytes": len(payload),
        },
    )


def build_project(project, profile, context) -> BuildResult:
    """Generate a configuration from the project alone and wrap it for the remote.

    Nothing is read from a previous image: devices, activities and settings in, every
    screen and handler generated (compose.py) onto the scaffold - or onto the
    theme the project's settings name (`theme_folder`): a theme's name in the owner's
    Themes folder (themes.py), or a folder of its own; not `theme`, which the Harmony 900
    already uses for a preference of its own. The safety gate comes first: a read-only
    profile produces nothing.
    """
    from . import compose

    profile.require_buildable()
    settings = project.get("settings") or {}
    theme = settings.get("theme_folder")
    directory = context.find_scaffold(profile.id, context.root)
    if theme:
        directory = context.find_theme(profile.id, theme) or Path(theme)
        if not directory.is_absolute():
            directory = Path(context.root) / directory
        if not (directory / "assets.json").is_file():
            raise ValueError(f"there is no theme {theme!r}: no such theme in the Themes "
                             "folder, and no scaffold folder of that name")
    context.log(f"Building for {profile.model}"
                + (f" with the theme {theme!r}" if theme else ""))
    # One remote sold under several skins builds for the one the project names
    skin = settings.get("skin")
    if skin is not None and skin not in profile.skins:
        raise ValueError(f"skin {skin} is not a {profile.model}'s")
    from ... import remotes
    built = compose.build(project, directory=directory,
                          look=profile.looks.get(skin) if skin is not None else None,
                          model=remotes.model_name(
                              profile, skin if skin is not None else profile.skin))
    payload = built["image"]
    validation = validate_payload(payload, profile)

    carrier = payloads.get(profile.payload)
    work = Path(tempfile.mkdtemp(prefix="harmony_700_build_"))
    output = Path(settings.get("out_file") or "home.ezhex")
    if not output.is_absolute():
        output = Path(context.root) / output
    if output.suffix.lower() != ".ezhex":
        output = output.with_suffix(".EZHex")
    try:
        carrier.unpack(payload, str(work))
        ezhex.pack_standalone(str(work), str(output), profile=(
            dataclasses.replace(profile, skin=skin) if skin is not None else profile))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for note in built["skipped"]:
        context.log(f"WARNING: {note}")
    context.log(f"Wrote {output} ({output.stat().st_size:,} bytes)")
    return BuildResult(
        artifact=output,
        validation=validation,
        changes={"skipped": list(built["skipped"])},
        metadata={"backend": "harmony-700", "generator": "from-project",
                  "scaffold": str(directory) if directory else None, "size": len(payload)},
    )


def name_activity_keys(project) -> int:
    """Write down which activity each activity key starts, in a project that names
    none: the build gives them to the first three activities, Watch a Movie's key first
    (compose.activity_keys), and the editor showed "None" for every one. Returns how many
    were named."""
    from .keys import ACTIVITY_BUTTONS
    activities = project.get("activities") or []
    if any(activity.get("activity_button") for activity in activities):
        return 0
    for name, activity in zip(ACTIVITY_BUTTONS, activities):
        activity["activity_button"] = name
    return min(len(ACTIVITY_BUTTONS), len(activities))


def capability(signal: dict, profile, *, library=None) -> dict:
    """Whether the One can send a portable signal: its lowering takes it or says why."""
    from ... import ir_signal
    from . import ir_lowering

    ir_signal.validate(signal)
    if signal["kind"] == "backend-opaque":
        return {"supported": False, "strategy": "unavailable",
                "reason": "an opaque command from another remote has no meaning to lower"}
    try:
        ir_lowering.lower(signal, library=library)
    except (LookupError, ValueError) as exc:
        return {"supported": False, "strategy": "unavailable", "reason": str(exc)}
    strategy = "waveform" if signal["kind"] == "waveform" else "protocol"
    return {"supported": True, "strategy": strategy,
            "reason": "lowered to the One's own waveform records"}
