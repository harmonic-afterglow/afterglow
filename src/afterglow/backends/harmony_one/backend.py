"""Read-only Harmony One backend with lossless native preservation.

The first increment recognizes and validates the arch-12 GSPM image without claiming
to understand its household devices or author safe mutations. Unknown native data is
accounted for and retained by the selected carrier.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import hashlib

from ... import payloads
from ..contracts import ImportResult
from . import command_index, gspm, inventory


def validate_payload(payload: bytes, _profile=None) -> dict:
    return gspm.validate(payload)


def import_project(source, profile, context) -> ImportResult:
    """Validate a preserved image while portable record decoding remains unavailable."""
    carrier = payloads.get(profile.payload)
    payload = carrier.build(source)
    validation = validate_payload(payload, profile)
    native = inventory.inspect(payload)
    ownership = native["ownership"]
    devices = command_index.portable_devices(
        ownership, native["keys"], native["ui"]["device_menus"])
    settings = {"remote": profile.id}
    if context.get("out_file"):
        settings["out_file"] = str(context["out_file"])
    return ImportResult(
        project={"devices": devices, "activities": [], "assets": [], "settings": settings},
        preservation={
            "mode": "opaque-native-payload",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "validation": validation,
            "inventory": native,
        },
        warnings=(
            "Harmony One command ownership and proven press/hold/release waveforms were imported "
            "with generated native names. Screen key bindings and owned device-menu glyph lines "
            "were retained as evidence. Activity contexts and state transitions were also indexed, "
            "but portable key names, decoded labels, and unresolved native behavior remain opaque; "
            "the native payload was preserved unchanged.",
        ),
        rejected={
            "native_objects": max(
                0, native["objects"]["objects"] - ownership["counts"]["command_objects"]),
            "native_commands": sum(ownership["rejected"].values()),
            "native_payload_bytes": len(payload),
        },
    )


def build_project(_project, profile, _context):
    raise NotImplementedError(
        f"{profile.model} authoring is not implemented; import and backup are read-only")
