"""The Harmony One backend: build a configuration from a project, and read one back.

A build generates the whole GSPM image from the project's devices, activities and
settings (generate.py) - nothing is carried from a previous configuration. Reading an
image validates it and recovers what is proven of its devices, keeping the native payload
unchanged.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile

from ... import ezhex, payloads
from ..contracts import BuildResult, ImportResult
from . import command_index, gspm, importing, inventory


def validate_payload(payload: bytes, _profile=None) -> dict:
    return gspm.validate(payload)


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
    # favourites' logos go to the owner's logos folder, by the configuration's name
    from ... import paths
    name = Path(str(source)).name.removesuffix("_extracted") or "imported"
    logos = paths.logos_dir() / "Imported" / name
    activities, off = importing.Activities(image, devices, naming, notes, logos).read()
    # each type from the icon its menu row draws; a row whose icon is not known keeps none
    types = importing.read_types(image)
    unknown = []
    for index, device in enumerate(devices):
        device["type"] = types.get(("device", index)) or device.get("type")
        if ("device", index) not in types:
            unknown.append(device["label"])
    for activity in activities:
        activity["type"] = types.get(("activity", int(activity["id"])))
        if activity["type"] is None:
            unknown.append(activity["label"])
    if unknown:
        notes.append("no type was recognised for " + ", ".join(repr(name) for name in unknown)
                     + "; their icons are the default ones")
    notes += [f"could not read the image's {item}" for item in image.unreadable]
    settings = {"remote": profile.id}
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
    screen, light and handler generated (generate.py) onto the scaffold - or onto the
    theme the project's settings name (`theme_folder`): a theme's name in the owner's
    Themes folder (themes.py), or a folder of its own; not `theme`, which the Harmony 900
    already uses for a preference of its own. The safety gate comes first: a read-only
    profile produces nothing.
    """
    from . import generate

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
    built = generate.build(project, directory=directory)
    payload = built["image"]
    validation = validate_payload(payload, profile)

    carrier = payloads.get(profile.payload)
    work = Path(tempfile.mkdtemp(prefix="harmony_one_build_"))
    output = Path(settings.get("out_file") or "home.ezhex")
    if not output.is_absolute():
        output = Path(context.root) / output
    if output.suffix.lower() != ".ezhex":
        output = output.with_suffix(".EZHex")
    try:
        carrier.unpack(payload, str(work))
        ezhex.pack_standalone(str(work), str(output), profile=profile)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for note in built["skipped"]:
        context.log(f"WARNING: {note}")
    return BuildResult(
        artifact=output,
        validation=validation,
        changes={"skipped": list(built["skipped"])},
        metadata={"backend": "harmony-one", "generator": "from-project",
                  "scaffold": str(directory) if directory else None, "size": len(payload)},
    )


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
