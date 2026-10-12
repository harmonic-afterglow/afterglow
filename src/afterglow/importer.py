"""Dispatch an extracted configuration to its remote architecture backend."""
import contextlib
import io
import shutil
import tempfile
from pathlib import Path

from . import backends, project_devices, remotes


def import_result(extracted_dir, out_file=None, name=None):
    """Read an extracted configuration without discarding backend evidence. ``name`` is
    the configuration's, for what the import keeps of it (its pictures); by default the
    folder's."""
    header_path = Path(extracted_dir) / ".ezhex_header"
    profile = (remotes.identify(header_path.read_bytes()) if header_path.is_file()
               else remotes.default())
    result = backends.for_profile(profile).import_project(
        extracted_dir, profile, {"out_file": out_file, "name": name})
    # The remote it came off is the remote it is for, until somebody migrates it.
    result.project.setdefault("settings", {})["remote"] = profile.id
    # Its keys are bound as the configuration had them; none is free to fill.
    for device in result.project.get("devices") or []:
        device[project_devices.KEYS_FILLED] = True
    return result


def build_project(extracted_dir, out_file=None):
    """Compatibility entry point returning only the portable project model."""
    return import_result(extracted_dir, out_file=out_file).project


def import_file(path, name=None):
    """Import a configuration file. It is unpacked into a temporary folder that is gone
    afterwards, so nothing is left beside the file; the pictures the project uses are
    copied to `Logos/Imported/<name>` first, where the project then finds them."""
    from . import ezhex, paths

    name = name or Path(path).stem
    with tempfile.TemporaryDirectory(prefix="afterglow-import-") as work:
        tree = Path(work) / "tree"
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(str(path), str(tree))
        result = import_result(str(tree), name=name)
        kept = paths.logos_dir() / "Imported" / name
        for asset in result.project.get("assets") or []:
            source = Path(asset.get("source") or "")
            if not source.is_absolute() or not source.is_relative_to(work):
                continue
            kept.mkdir(parents=True, exist_ok=True)
            target = kept / Path(asset["name"]).name
            shutil.copy2(source, target)
            asset["source"] = str(target)
    return result
