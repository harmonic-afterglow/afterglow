"""Small, backend-neutral request and result objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class BuildContext:
    root: Path
    log: Callable[[str], None]
    find_scaffold: Callable[[str, Path | None], Path | None]


@dataclass(frozen=True)
class BuildResult:
    artifact: Path
    validation: dict = field(default_factory=dict)
    changes: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ImportResult:
    project: dict
    preservation: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    rejected: dict = field(default_factory=dict)
