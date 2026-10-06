"""Load the implementation selected by a remote profile.

The rest of Afterglow deals in portable devices, signals and protocol definitions.  A
backend is the one deliberately narrow place where those meanings become a particular
remote's command bytes, protocol tables and configuration tree.  Backends are loaded by
the name in ``RemoteProfile.backend``; callers must never import a concrete
backend themselves.

Keeping the registry dynamic matters.  A hard-coded ``harmony_pk`` import in the builder
would make the profile field decorative and a second backend impossible without editing
the supposedly portable layer.  The small runtime contract below turns that declaration
into an actual extension point while keeping the core free of third-party dependencies.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from .contracts import BuildContext as BuildContext
from .contracts import BuildResult as BuildResult
from .contracts import ImportResult as ImportResult

REQUIRED = ("build_project", "import_project")

# This backend is identified by the ``PK\x03\x04`` magic at the start of its ezhex
# payload. ``harmony-z`` and the briefly used structural name ``harmony-ziptree`` were
# never Logitech format names. Keep both as read aliases for private projects/native
# evidence created before the magic-based name was adopted.
ALIASES = {
    "harmony-z": "harmony-pk",
    "harmony-ziptree": "harmony-pk",
}


def get(name: str):
    """Return one backend implementation behind the two-operation contract."""
    if not isinstance(name, str) or not name.strip():
        raise LookupError("remote profile does not name an infrared backend")
    canonical = ALIASES.get(name.strip(), name.strip())
    return _get_canonical(canonical)


@lru_cache
def _get_canonical(canonical: str):
    module_name = canonical.replace("-", "_")
    try:
        backend = import_module(f"{__name__}.{module_name}.backend")
    except ModuleNotFoundError as exc:
        expected = f"{__name__}.{module_name}"
        if exc.name not in (expected, f"{expected}.backend"):
            raise
        raise LookupError(f"unknown infrared backend {canonical!r}") from None
    if all(callable(getattr(backend, name, None)) for name in REQUIRED):
        return backend

    from . import v1
    missing = [name for name in v1.REQUIRED if not callable(getattr(backend, name, None))]
    if missing:
        raise TypeError(
            f"infrared backend {canonical!r} is incomplete; missing "
            f"{', '.join(missing)}")
    return v1.Backend(backend)


def for_profile(profile):
    """Resolve the backend named by a ``RemoteProfile``."""
    # The fallback keeps old in-memory profiles readable during the schema migration.
    name = getattr(profile, "backend", "") or (profile.infrared or {}).get("backend")
    return get(name)


def rf_link(profile):
    """The RF blaster pairing for `profile`'s remote, or None if it has no RF.

    None both for a remote whose profile does not offer RF blasters and for a backend
    that has no pairing to offer: either way there is nothing to pair with.
    """
    if "rf_blasters" not in profile.settings_fields:
        return None
    provider = getattr(for_profile(profile), "rf_link", None)
    return provider() if callable(provider) else None


def installed() -> list[str]:
    """Every backend package present, discovered rather than listed."""
    from pkgutil import iter_modules
    from pathlib import Path

    root = Path(__file__).resolve().parent
    return sorted(info.name.replace("_", "-") for info in iter_modules([str(root)])
                  if info.ispkg and not info.name.startswith("_"))


def for_legacy_device(spec: dict):
    """The backend that recognises a pre-portable device record.

    Reading a legacy record needs that architecture's knowledge of block ids and command
    framing, so some backend has to do it - but naming one here would make it
    undeletable. `device_json.to_project_device` used to call
    ``backends.get("harmony-pk")`` directly, which meant removing that backend broke
    loading *any* old device file, including ones another architecture might own.
    Backends declare what they recognise instead, via an optional ``claims_legacy``.
    """
    claimants = []
    for name in installed():
        try:
            backend = get(name)
        except (LookupError, TypeError):
            continue
        claim = getattr(backend, "claims_legacy", None)
        if callable(claim) and claim(spec):
            claimants.append((name, backend))
    if len(claimants) > 1:
        raise LookupError(
            "more than one backend claims this legacy device record: "
            f"{', '.join(name for name, _backend in claimants)}")
    if not claimants:
        raise LookupError(
            f"no installed backend recognises device schema {spec.get('schema')!r}; "
            f"installed: {', '.join(installed()) or 'none'}")
    return claimants[0][1]
