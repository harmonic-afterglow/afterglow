"""Read-only Harmony One backend with lossless native preservation.

The first increment recognizes and validates the arch-12 GSPM image without claiming
to understand its household devices or author safe mutations. Unknown native data is
accounted for and retained by the selected carrier.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile

from ... import ezhex, payloads
from ..contracts import BuildResult, ImportResult
from . import baseline, build, command_index, gspm, inventory


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
    settings = {
        "remote": profile.id,
        "baseline": baseline.descriptor(source, payload, profile),
    }
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
            "with native device-menu names when the image uses a proved glyph repertoire. Screen "
            "key bindings and raw glyph lines were retained as evidence. Activity contexts and "
            "state transitions were also indexed, but portable key names and unresolved native "
            "behavior remain opaque; "
            "the native payload was preserved unchanged.",
        ),
        rejected={
            "native_objects": max(
                0, native["objects"]["objects"] - ownership["counts"]["command_objects"]),
            "native_commands": sum(ownership["rejected"].values()),
            "native_payload_bytes": len(payload),
        },
    )


def build_project(project, profile, context) -> BuildResult:
    """Rebuild the project's own baseline image and emit it through its carrier.

    The safety gate comes first: a read-only profile cannot produce an artifact, so the
    plan is still described but nothing is written. That keeps the machinery testable
    while the Harmony One remains unwritten to.
    """
    profile.require_buildable()
    payload, baseline_state = baseline.load(project, profile)
    steps = build.plan(project, payload)
    result, report = build.apply(payload, project, steps, library=context.get("library"))

    carrier = payloads.get(profile.payload)
    work = Path(tempfile.mkdtemp(prefix="harmony_one_build_"))
    output = Path((project.get("settings") or {}).get("out_file") or "home.ezhex")
    if not output.is_absolute():
        output = Path(context.root) / output
    try:
        carrier.unpack(result, str(work))
        ezhex.pack_standalone(str(work), str(output), profile=profile)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return BuildResult(
        artifact=output,
        validation=report["validation"],
        changes=report,
        metadata={
            "backend": "harmony-one",
            "baseline": baseline_state,
            "plan": steps,
        },
    )
