"""The arch-9 backend (the Harmony 510, 515, 520, 525, 550, 555 and the Harmony for
Xbox 360): read a configuration back as a project, and build one from a project.

Reading an image validates it and recovers what is proven of its devices and activities,
keeping the native payload unchanged. A build generates every byte from the project and
the model's scaffold (generate.py); only a model whose platform has been read into a
scaffold builds, and only once its profile's gate allows it (docs/harmony_5xx/ahcm.md).

Format reference: docs/harmony_5xx/ahcm.md
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
import shutil
import struct
import tempfile

from ... import activity_layouts, ezhex, payloads, themes
from ..contracts import BuildResult, ImportResult
from . import command_index, font_index, gspm, importing, inventory, keys, labels
from .generate import LAYOUTS


# The types a device and an activity get when none is recognised: "Home appliance" and
# "Custom / Other".
GENERIC_DEVICE = "HomeAppliance"
GENERIC_ACTIVITY = "VirtualGeneric"

# A page's buttons sit in its four corners, and Logitech's 5xx images leave a corner
# empty where the owner left one, a whole page too: a gap is a corner drawn and bound
# with nothing.
SCREEN_GAPS = True


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
    image = importing.Image(payload, keys.Keypad.of(profile))
    devices = importing.project_devices(image, command_index.portable_devices(
        ownership, native["keys"], native["ui"]["device_menus"]), notes, naming)
    layout_codes = {keys.code(scan): kind for kind, (name, _title) in LAYOUTS.items()
                    for key, scan in ((profile.vocabulary or {}).get("layout_key_scans")
                                      or {}).items() if key == name}
    activities, off = importing.Activities(image, devices, naming, notes,
                                           layout_codes).read()
    # A 5xx's menu rows draw no icon, so no row says a type: a device is a Home appliance
    # and an activity "Custom / Other", as an editor would otherwise open them as types they
    # are not. On a 5xx a type names nothing it draws.
    for device in devices:
        device["type"] = GENERIC_DEVICE
    # which Sound and Picture layouts each device's own screen has, as no type says
    if layout_codes:
        for index, kinds in importing.device_layout_kinds(image, layout_codes).items():
            device = devices[index]
            if tuple(kinds) != activity_layouts.device_kinds(device):
                device["layouts"] = list(kinds)
    for activity in activities:
        activity["type"] = GENERIC_ACTIVITY
    # the devices as the Devices list shows them - activities name them by id, so this
    # comes after them
    rank = {index: at for at, index in enumerate(importing.device_list_order(image)[0])}
    devices = [device for _key, device in sorted(
        enumerate(devices), key=lambda pair: (rank.get(pair[0], len(rank)), pair[0]))]
    # a name with a character the text reader does not know is said, to be put right: it
    # reads as "?", which builds, and a name is one when a line it was read from had one
    unread = [label for label in (
        [device["label"] for device in devices]
        + [name for device in devices for name in device["signals"]]
        + [activity["label"] for activity in activities])
        if any(line and line in label for line in image.text.unread)]
    if unread:
        notes.append("these names have characters that could not be read (shown as "
                     f"{labels.UNKNOWN!r}): " + ", ".join(repr(name) for name in unread)
                     + ". They build and can be renamed; please open an Issue in the "
                     "Afterglow repository with this configuration so its letters can be "
                     "learned")
    notes += [f"could not read the image's {item}" for item in image.unreadable]
    settings = {"remote": profile.id, **importing.remote_settings(image)}
    # a remote sold under another of the profile's numbers keeps its own (a 510's 68)
    from .generate import SKIN_AT
    skin = payload[gspm.section_ranges(payload)[1][0] + SKIN_AT]
    if skin in profile.other_skins:
        settings["skin"] = skin
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

    The safety gate comes first: a read-only profile produces nothing. Then the model's
    scaffold: a model whose platform has not been read into one (platform/wiring.json)
    is refused rather than given another model's. Its pictures and typeface are the
    theme's the project's settings name (`theme_folder`: a theme's name in the owner's
    Themes folder, themes.py, or a folder of its own), where the theme has them.
    """
    from . import generate

    profile.require_buildable()
    directory = context.find_scaffold(profile.id, context.root)
    if directory is None or not any((Path(directory) / name).is_file()
                                    for name in (generate.WIRING_FILE, generate.DERIVED_FILE)):
        raise ValueError(f"Afterglow cannot build for the {profile.model} yet: its platform "
                         "has not been read from an empty configuration of its own")
    settings = dict(project.get("settings") or {}, remote=profile.id)
    folder = themes.build_folder(settings, profile.id, context)
    theme = settings.get("theme_folder") if folder else None
    context.log(f"Building for {profile.model}"
                + (f" with the theme {theme!r}" if theme else ""))
    image, payload = generate.build_fitting(dict(project, settings=settings), Path(directory),
                                            generate.build_stamp(), None, folder)
    validation = validate_payload(payload, profile)
    carrier = payloads.get(profile.payload)
    work = Path(tempfile.mkdtemp(prefix="arch9_build_"))
    output = Path(settings.get("out_file") or "home.EZHex")
    if not output.is_absolute():
        output = Path(context.root) / output
    if output.suffix.lower() != ".ezhex":
        output = output.with_suffix(".EZHex")
    try:
        carrier.unpack(payload, str(work))
        # the header names the remote as the configuration does: a 510 as a 510
        skin = generate.own_skin(project, profile)
        ezhex.pack_standalone(str(work), str(output), profile=profile if skin is None
                              else dataclasses.replace(profile, skin=skin))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for note in image.skipped:
        context.log(f"WARNING: {note}")
    context.log(f"Wrote {output} ({output.stat().st_size:,} bytes)")
    return BuildResult(
        artifact=output,
        validation=validation,
        changes={"skipped": list(image.skipped)},
        metadata={"backend": "harmony-555", "generator": "from-project",
                  "scaffold": str(directory), "size": len(payload)},
    )


def translations() -> list[str]:
    """The languages this remote's words are translated into (catalogue.translations)."""
    from . import catalogue
    return catalogue.translations()


def capability(signal: dict, profile, *, library=None) -> dict:
    """Whether a 5xx can send a portable signal: its lowering takes it or says why."""
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
            "reason": "lowered to the remote's own class-5 records"}
