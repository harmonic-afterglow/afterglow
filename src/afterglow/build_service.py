"""Build orchestration. Headless on purpose: building a config must not require Qt,
so the CLI, the examples and the tests can all use it.
"""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from . import paths



def find_scaffold(remote_id: str, root: Path | None = None) -> Path | None:
    """Where this remote's scaffold lives, or None.

    Looked for beside the package first, so a packaged application carries its own,
    then next to the caller's root and up the tree for a checkout. The caller used to
    pass a directory two levels below the repository, which sent the search into the
    package and produced a "no scaffold" error for a scaffold that was present.
    """
    here = Path(__file__).resolve().parent
    candidates = [paths.scaffolds(), here / "scaffolds", here.parent / "scaffolds"]
    if root is not None:
        root = Path(root).resolve()
        candidates.append(root / "scaffolds")
        candidates.extend(parent / "scaffolds" for parent in root.parents)
    for folder in candidates:
        scaffold = folder / remote_id
        if scaffold.is_dir():
            return scaffold
    return None


class ConfigBuildService:
    def __init__(self, root: Path, log: Callable[[str], None] | None = None):
        self.root = root
        self.log = log or (lambda _message: None)

    def build(self, project: dict) -> Path:
        from . import ezhex
        from . import backends, ir_protocol, project_devices, remotes

        settings = project["settings"]
        # Which remote is this for, and may we write for it? An untested profile can be
        # read and inspected but not built for: a wrong config on a remote nobody has
        # tried is not recoverable from a vendor server any more.
        profile = remotes.get(settings.get("remote", "harmony-900"))
        profile.require_writable()
        backend = backends.for_profile(profile)
        self.log(f"Building for {profile.model} (payload: {profile.payload})")
        output = settings.get("out_file", "home.ezhex")
        if not project.get("devices"):
            raise ValueError("No devices configured.")

        portable_devices = []
        for device in project["devices"]:
            source = copy.deepcopy(device)
            if project_devices.is_portable(source):
                portable_devices.append(project_devices.clean(source))
            else:
                portable_devices.append(backend.migrate_legacy_device(source))

        self.log(
            f"Building {len(portable_devices)} device(s), "
            f"{len(project.get('activities', []))} activity/ies...")
        work = tempfile.mkdtemp(prefix="harmony_build_")
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            # Every config is built from the bundled scaffold. Using somebody's existing
            # config as a base carries their remote's state along with it - a foreign RF
            # blaster assignment, a stale statetracker, whatever else has not been
            # modelled - and those ride into the new config unnoticed. The scaffold plus
            # the protocol library is enough to build a complete config from nothing.
            # The scaffold is per remote: platformconfig holds that model's persisted
            # settings and hardware calibration (battery curve, PMIC, tilt), which do not
            # transfer between models.
            scaffold = find_scaffold(profile.id, self.root)
            if scaffold is None:
                raise FileNotFoundError(
                    f"No scaffold for {profile.model} ({profile.id}).\n"
                    "A scaffold is that model's own platform state - its calibration and "
                    "persisted settings - and cannot be borrowed from another remote.")
            base_dir = str(scaffold)
            portable_protocols = ir_protocol.catalog()
            for spec in portable_devices:
                for protocol_id, definition in (
                        spec.get("portable_protocol_definitions") or {}).items():
                    existing = portable_protocols.get(protocol_id)
                    if existing is not None and existing != definition:
                        raise ValueError(
                            f"External portable protocol {protocol_id!r} conflicts with "
                            "the built-in definition")
                    portable_protocols[protocol_id] = definition
            specs = backend.lower_devices(
                portable_devices, profile, library=portable_protocols)
            backend.build_tree(
                specs, work, activities=project.get("activities") or None,
                settings=project.get("settings", {}), base_dir=base_dir,
                protocol_meta_by_id=project.get("protocol_meta"),
                power_off_all=project.get("power_off_all"),
                power_off_label=project.get("power_off_label"))
            

            # Project assets are copied explicitly into the config payload; this
            # keeps channel/action art alongside the portable project JSON.
            for asset in project.get("assets", []):
                source = self.root / asset["source"]
                target = Path(work) / "userconfig" / "image" / asset["name"]
                if not source.is_file():
                    raise FileNotFoundError(f"Project image asset missing: {source}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            self.log("Re-hashing IrProto.bin...")
            ezhex.rehash(work)
            self.log(f"Packing -> {output}...")
            ezhex.pack_standalone(work, output, profile=profile)
        finally:
            os.chdir(original_cwd)
            shutil.rmtree(work, ignore_errors=True)
        return self.root / output
