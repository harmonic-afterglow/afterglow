"""Adapter for the original five-operation Harmony PK backend contract."""

from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import tempfile

from .contracts import BuildResult, ImportResult


REQUIRED = (
    "build_tree",
    "capability",
    "import_project",
    "lower_devices",
    "migrate_legacy_device",
)


class Backend:
    """Present a v2 two-operation boundary around an unchanged v1 implementation."""

    def __init__(self, module):
        self.module = module

    def __getattr__(self, name):
        # Optional capabilities remain available during migration. Shared build/import
        # orchestration no longer depends on them individually.
        return getattr(self.module, name)

    def import_project(self, source, profile, context) -> ImportResult:
        project = self.module.import_project(source, out_file=context.get("out_file"))
        return ImportResult(project=project)

    def build_project(self, project: dict, profile, context) -> BuildResult:
        """Run the old lowering/tree-builder sequence entirely inside the adapter."""
        from .. import ezhex, ir_protocol, project_devices

        settings = project["settings"]
        context.log(f"Building for {profile.model} (payload: {profile.payload})")
        output = settings.get("out_file", "home.ezhex")
        if not project.get("devices"):
            raise ValueError("No devices configured.")

        portable_devices = []
        for device in project["devices"]:
            source = copy.deepcopy(device)
            if project_devices.is_portable(source):
                portable_devices.append(project_devices.clean(source))
            else:
                portable_devices.append(self.module.migrate_legacy_device(source))

        context.log(
            f"Building {len(portable_devices)} device(s), "
            f"{len(project.get('activities', []))} activity/ies...")
        work = tempfile.mkdtemp(prefix="harmony_build_")
        original_cwd = Path.cwd()
        try:
            os.chdir(context.root)
            scaffold = context.find_scaffold(profile.id, context.root)
            if scaffold is None:
                raise FileNotFoundError(
                    f"No scaffold for {profile.model} ({profile.id}).\n"
                    "A scaffold is that model's own platform state - its calibration and "
                    "persisted settings - and cannot be borrowed from another remote.")
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
            specs = self.module.lower_devices(
                portable_devices, profile, library=portable_protocols)
            self.module.build_tree(
                specs, work, activities=project.get("activities") or None,
                settings=settings, base_dir=str(scaffold),
                protocol_meta_by_id=project.get("protocol_meta"),
                power_off_all=project.get("power_off_all"),
                power_off_label=project.get("power_off_label"))

            for asset in project.get("assets", []):
                source = context.root / asset["source"]
                target = Path(work) / "userconfig" / "image" / asset["name"]
                if not source.is_file():
                    raise FileNotFoundError(f"Project image asset missing: {source}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            context.log("Re-hashing IrProto.bin...")
            ezhex.rehash(work)
            context.log(f"Packing -> {output}...")
            ezhex.pack_standalone(work, output, profile=profile)
        finally:
            os.chdir(original_cwd)
            shutil.rmtree(work, ignore_errors=True)
        return BuildResult(
            artifact=context.root / output,
            metadata={"contract": "v1-adapter", "backend": profile.backend},
        )
