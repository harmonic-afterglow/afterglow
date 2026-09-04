"""External Afterglow databases distributed as Git repositories.

An external database is a collaboration source, not the user's private local library.
The source settings store only its HTTPS Git URL. When the catalogue is opened we keep
a shallow, refreshable checkout under the application cache and validate the native
``devices/`` layout before exposing it to the device wizard. No revision is pinned:
refreshing follows the repository's advertised default branch.

Git is invoked directly to avoid adding a dependency to the headless build layer.
Cached records are disposable and no repository is ever cloned into the source tree.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit, urlunsplit

from . import paths


@dataclass(frozen=True)
class ExternalRepository:
    """One enabled or disabled remote Afterglow-format Git repository."""

    url: str
    enabled: bool = True

    @property
    def normalized_url(self) -> str:
        value = self.url.strip()
        parts = urlsplit(value)
        path = re.sub(r"/+\Z", "", parts.path)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))

    @property
    def name(self) -> str:
        stem = Path(urlsplit(self.normalized_url).path).name
        return stem.removesuffix(".git") or self.normalized_url

    def validate(self) -> None:
        parts = urlsplit(self.normalized_url)
        if parts.scheme != "https" or not parts.netloc or not parts.path.strip("/"):
            raise ValueError("Enter an HTTPS Git repository URL.")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Repository URLs cannot contain credentials, queries, or fragments.")


def cache_path(repository: ExternalRepository, cache_root: Path | None = None) -> Path:
    repository.validate()
    digest = hashlib.sha256(repository.normalized_url.encode()).hexdigest()[:16]
    root = cache_root or paths.cache_dir() / "sources" / "afterglow"
    return Path(root) / f"{repository.name}-{digest}"


def _git(*args: str, cwd: Path | None = None) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=False)
    except FileNotFoundError as exc:
        raise OSError("Git is required for external Afterglow databases.") from exc
    except subprocess.TimeoutExpired as exc:
        raise OSError("The Git repository request timed out.") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"git exited with status {result.returncode}"
        raise OSError(message)
    return result.stdout.strip()


def sync_repository(repository: ExternalRepository,
                    cache_root: Path | None = None) -> Path:
    """Clone or refresh ``repository`` and return its validated cached root."""
    target = cache_path(repository, cache_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not (target / ".git").is_dir():
            raise OSError(f"External database cache is not a Git checkout: {target}")
        origin = _git("remote", "get-url", "origin", cwd=target)
        if ExternalRepository(origin).normalized_url != repository.normalized_url:
            raise OSError(f"External database cache has the wrong origin: {target}")
        _git("fetch", "--depth", "1", "origin", cwd=target)
        remote_head = _git("symbolic-ref", "refs/remotes/origin/HEAD", cwd=target)
        _git("checkout", "--detach", "--force", remote_head, cwd=target)
    else:
        _git("clone", "--depth", "1", "--single-branch",
             repository.normalized_url, str(target))
    if not (target / "devices").is_dir():
        raise ValueError("External Afterglow database needs a devices/ directory.")
    return target
