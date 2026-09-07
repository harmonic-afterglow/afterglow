"""Build orchestration. Headless on purpose: building a config must not require Qt,
so the CLI, the examples and the tests can all use it.
"""
from __future__ import annotations

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
        from . import backends, remotes

        settings = project["settings"]
        # Which remote is this for, and has its profile entered build testing? This is
        # deliberately weaker than the write gate: experimental profiles can produce
        # artifacts for controlled validation, but the normal flash path still refuses
        # them until a real write and boot has been verified.
        profile = remotes.get(settings.get("remote", "harmony-900"))
        profile.require_buildable()
        backend = backends.for_profile(profile)
        context = backends.BuildContext(
            root=self.root,
            log=self.log,
            find_scaffold=find_scaffold,
        )
        return backend.build_project(project, profile, context).artifact
