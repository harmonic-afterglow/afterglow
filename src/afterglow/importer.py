"""Dispatch an extracted configuration to its remote architecture backend."""
from pathlib import Path

from . import backends, project_devices, remotes


def build_project(extracted_dir, out_file=None):
    """Read an extracted configuration into the portable project model."""
    header_path = Path(extracted_dir) / ".ezhex_header"
    profile = (remotes.identify(header_path.read_bytes()) if header_path.is_file()
               else remotes.default())
    result = backends.for_profile(profile).import_project(
        extracted_dir, profile, {"out_file": out_file})
    # The remote it came off is the remote it is for, until somebody migrates it.
    result.project.setdefault("settings", {})["remote"] = profile.id
    # Its keys are bound as the configuration had them; none is free to fill.
    for device in result.project.get("devices") or []:
        device[project_devices.KEYS_FILLED] = True
    return result.project
