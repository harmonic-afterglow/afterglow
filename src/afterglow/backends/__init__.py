"""Load the implementation selected by a remote profile.

The rest of Afterglow deals in portable devices, signals and protocol definitions.  A
backend is the one deliberately narrow place where those meanings become a particular
remote's command bytes, protocol tables and configuration tree.  Backends are loaded by
the name in ``RemoteProfile.infrared.backend``; callers must never import a concrete
backend themselves.

Keeping the registry dynamic matters.  A hard-coded ``harmony_pk`` import in the builder
would make the profile field decorative and a second backend impossible without editing
the supposedly portable layer.  The small runtime contract below turns that declaration
into an actual extension point while keeping the core free of third-party dependencies.
"""
from __future__ import annotations

from importlib import import_module
from types import ModuleType


REQUIRED = (
    "build_tree",
    "capability",
    "import_project",
    "lower_devices",
    "migrate_legacy_device",
)

# This backend is identified by the ``PK\x03\x04`` magic at the start of its ezhex
# payload. ``harmony-z`` and the briefly used structural name ``harmony-ziptree`` were
# never Logitech format names. Keep both as read aliases for private projects/native
# evidence created before the magic-based name was adopted.
ALIASES = {
    "harmony-z": "harmony-pk",
    "harmony-ziptree": "harmony-pk",
}


def get(name: str) -> ModuleType:
    """Return one backend module and verify its public contract."""
    if not isinstance(name, str) or not name.strip():
        raise LookupError("remote profile does not name an infrared backend")
    canonical = ALIASES.get(name.strip(), name.strip())
    module_name = canonical.replace("-", "_")
    try:
        backend = import_module(f"{__name__}.{module_name}.backend")
    except ModuleNotFoundError as exc:
        expected = f"{__name__}.{module_name}"
        if exc.name not in (expected, f"{expected}.backend"):
            raise
        raise LookupError(f"unknown infrared backend {name!r}") from None
    missing = [attribute for attribute in REQUIRED
               if not callable(getattr(backend, attribute, None))]
    if missing:
        raise TypeError(
            f"infrared backend {name!r} is incomplete; missing {', '.join(missing)}")
    return backend


def for_profile(profile) -> ModuleType:
    """Resolve the backend named by a ``RemoteProfile``."""
    return get((profile.infrared or {}).get("backend"))


def installed() -> list[str]:
    """Every backend package present, discovered rather than listed."""
    from pkgutil import iter_modules
    from pathlib import Path

    root = Path(__file__).resolve().parent
    return sorted(info.name.replace("_", "-") for info in iter_modules([str(root)])
                  if info.ispkg and not info.name.startswith("_"))


def for_legacy_device(spec: dict) -> ModuleType:
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
