"""The welcome a remote shows after a write, and whether this write is its first.

A project's `settings.welcome` is "first" (the default), "always" or "never". Each backend
builds its own welcome - the Harmony 650 and 700's ten page tour, the One's and 800's
Tutorial, the 900's first-time setup - when a build is handed "always", and none with
"never". "first" is this module's to decide before a write, as MyHarmony decided it for
an account's first sync: the welcome goes on a remote whose configuration is not one of
Afterglow's - Logitech's, a factory image, or nothing readable.

A backend says which configurations are Afterglow's through `afterglow_built(payload)`:
True for ours, False for any other, None when it cannot tell, which counts as not ours.
"""
from __future__ import annotations

from . import backends, ezhex, remotes

CHOICES = (("First flash only", "first"), ("Every flash", "always"), ("Never", "never"))
DEFAULT = "first"


def setting(project: dict) -> str:
    """The project's welcome setting, "first" when it names none it understands."""
    value = str((project.get("settings") or {}).get("welcome") or DEFAULT)
    return value if value in dict((v, k) for k, v in CHOICES) else DEFAULT


def afterglow_built(profile, raw: bytes | None) -> bool | None:
    """Whether a configuration file's bytes are one of Afterglow's builds for ``profile``'s
    remote; None when the backend cannot tell or has no way to."""
    if not raw:
        return False
    try:
        backend = backends.for_profile(profile)
    except (LookupError, TypeError):
        return None
    check = getattr(backend, "afterglow_built", None)
    if check is None:
        return None
    try:
        payload = ezhex.read(raw).payload
    except (ValueError, IndexError):
        payload = raw
    try:
        return check(payload)
    except Exception:            # a reader's surprise is no reason to stop a write
        return None


def decide(project: dict, raw: bytes | None) -> str:
    """"always" or "never" for this write: the project's own choice, or with "first" the
    welcome unless what is on the remote now (``raw``, its configuration file) is ours."""
    chosen = setting(project)
    if chosen != "first":
        return chosen
    try:
        profile = remotes.get((project.get("settings") or {}).get("remote") or "")
    except remotes.UnknownRemote:
        return "always"
    return "never" if afterglow_built(profile, raw) is True else "always"


def resolved(project: dict, choice: str) -> dict:
    """A copy of ``project`` whose build is handed ``choice``."""
    out = dict(project)
    out["settings"] = dict(project.get("settings") or {}, welcome=choice)
    return out
