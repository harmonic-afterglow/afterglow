"""The Harmony 800 backend: build a configuration from a project.

A build generates the whole image from the project's devices, activities and settings
(generate.py, the Harmony One's generator on the 800's format) and wraps it as the 800 takes
a configuration over USB: a zip of `Description.xml` and the image, which Concordance writes
to the remote's `/cfg/usercfg`. Reading an image back gives the project it was built from,
which every image Afterglow builds carries in its mark (mark.py); the 800's own
configurations from Logitech carry none and are not supported.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from ... import payloads
from ..contracts import BuildResult, ImportResult
from . import gsgd, mark

SKIN = 0x56
# A page's buttons take its six places in turn (pages.BUTTON_POSITIONS), and a gap is a
# place drawn and bound with nothing: no frame, no label, no key, no touch zone, as on the
# Harmony One; Afterglow draws the 800's pages itself.
SCREEN_GAPS = True
# What Concordance writes for an MH remote's configuration and reads back
# (libconcord/xml_headers.h, `mh_config_header`): the file, where it goes, its size, and
# the checksum over all but the last six bytes - the image's own, seeded 0x4321.
DESCRIPTION = (
    '<DATA><FILES><FILE NAME="Result.EzHex" SIZE="{size}" PATH="/cfg/usercfg" VERSION="1" '
    'FW_VERSION="9.5" OPERATIONTYPE="userconfiguration"><CHECKSUM SEED="0x4321" '
    'OFFSET="0x0" LENGTH="0x{length:04x}" EXPECTEDVALUE="0x{checksum:04x}" TYPE="XOR"/>'
    '</FILE></FILES><INTENDED><SKIN>{skin}</SKIN></INTENDED><ORDER><ORDER_ELEMENT '
    'NAME="Result.EzHex" RESET="true"/></ORDER></DATA>')


def validate_payload(payload: bytes, _profile=None) -> dict:
    return gsgd.validate(payload)


def compare_payloads(recovery: bytes, candidate: bytes, _profile) -> dict:
    """What a write changes, section by section, for review before it is written
    (first_write.py), as the Harmony One's backend reports it."""
    from . import gspm

    def sections(payload):
        image = gsgd.trimmed(payload)
        return {f"section {index}": hashlib.sha256(image[start:end]).hexdigest()
                for index, (start, end) in gspm.section_ranges(image).items()}

    before, after = sections(recovery), sections(candidate)
    return {
        "kind": "gsgd-section-sha256",
        "size before": len(recovery),
        "size after": len(candidate),
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": sorted(name for name in before.keys() & after.keys()
                          if before[name] != after[name]),
        "unchanged": sum(before[name] == after[name] for name in before.keys() & after.keys()),
    }


def description(image: bytes) -> str:
    low, high = gsgd.checksum(image, len(image) - 6)
    return DESCRIPTION.format(size=len(image), length=len(image) - 6,
                              checksum=(high << 8) | low, skin=SKIN)


def configuration_file(image: bytes, path: Path) -> Path:
    """Write ``image`` as the zip Concordance sends to the 800."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Description.xml", description(image))
        archive.writestr("Result.EzHex", image)
    return path


def read_configuration_file(path) -> bytes:
    """The image inside a configuration zip, or the file itself when it is a bare image."""
    data = Path(path).read_bytes()
    if data[:4] != b"PK\x03\x04":
        return data
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith(".xml")]
        if len(names) != 1:
            raise ValueError(f"{path} holds {len(names)} images, not one")
        return archive.read(names[0])


def import_project(source, profile, context) -> ImportResult:
    """Read a configuration Afterglow built back as the project it was built from (its
    mark, mark.py). One without the mark - Logitech's own - is refused, never guessed at."""
    carrier = payloads.get(profile.payload)
    payload = gsgd.trimmed(carrier.build(source))
    validation = validate_payload(payload, profile)
    project = mark.read(payload)["project"]
    project["settings"] = {**(project.get("settings") or {}), "remote": profile.id}
    if context.get("out_file"):
        project["settings"]["out_file"] = str(context["out_file"])
    return ImportResult(
        project=project,
        preservation={"mode": "afterglow-mark",
                      "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload),
                      "validation": validation},
        warnings=(),
        rejected={},
    )


def build_project(project, profile, context) -> BuildResult:
    """Generate a configuration from the project alone and write it as the 800 takes one.
    The safety gate comes first: a read-only profile produces nothing."""
    from . import generate

    profile.require_buildable()
    settings = project.get("settings") or {}
    directory = context.find_scaffold(profile.id, context.root)
    context.log(f"Building for {profile.model}")
    built = generate.build(project, directory=directory)
    payload = built["image"]
    validation = validate_payload(payload, profile)
    output = Path(settings.get("out_file") or "harmony800.EZHex")
    if not output.is_absolute():
        output = Path(context.root) / output
    configuration_file(payload, output)
    for note in built["skipped"]:
        context.log(f"WARNING: {note}")
    context.log(f"Wrote {output} ({output.stat().st_size:,} bytes)")
    return BuildResult(
        artifact=output,
        validation=validation,
        changes={"skipped": list(built["skipped"])},
        metadata={"backend": "harmony-800", "generator": "from-project",
                  "scaffold": str(directory) if directory else None, "size": len(payload)},
    )


def capability(signal: dict, profile, *, library=None) -> dict:
    """Whether the 800 can send a portable signal: its lowering (the One's) takes it."""
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
            "reason": "lowered to the 800's waveform records (the One's)"}
