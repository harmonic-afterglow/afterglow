"""Payload types: what lives inside the container, per remote architecture.

The `.ezhex` container is the same everywhere - an XML header and a payload - but the
payload differs by architecture. A remote profile names the type it needs, so adding an
architecture means adding a module here and referencing it from a profile.

**Nothing outside this package may name a concrete payload module.** This registry
resolves one by name, or identifies it from the bytes; it never falls back to a
particular format. That is not style - this package previously did
``from . import blob, pk`` and set ``DEFAULT = pk.NAME``, which meant deleting `pk.py`
stopped `afterglow.ezhex` from importing at all, and an unidentifiable header was
silently treated as a Harmony 900. Both are the coupling this project refuses: removing
a remote or a payload type must be a deletion, not a refactor.

A module here must define ``NAME``, ``unpack(payload, out_dir)``, ``build(src_dir)`` and
``describe(payload)``. It may also define:

``ALIASES``      - former names to keep reading (private files outlive renames).
``sniff(bytes)`` - True when the payload's own magic identifies this format.
``claims(dir)``  - True when an unpacked directory is one of these.
``rehash(dir)``  - re-sync internal digests before building; must no-op when there is
                   nothing to do, since the caller cannot know what this format hashes.
``LAST_RESORT``  - this type accepts anything; only consulted when nothing else claims.
"""
from __future__ import annotations

from importlib import import_module
from pkgutil import iter_modules
from types import ModuleType

REQUIRED = ("NAME", "unpack", "build", "describe")


class UnknownPayload(LookupError):
    """No payload type claims these bytes, and none was named."""


def names() -> list[str]:
    """Every payload module present, discovered rather than listed."""
    return sorted(info.name for info in iter_modules(__path__)
                  if not info.name.startswith("_"))


def _verify(module: ModuleType, name: str) -> ModuleType:
    missing = [attribute for attribute in REQUIRED if not hasattr(module, attribute)]
    if missing:
        raise TypeError(
            f"payload type {name!r} is incomplete; missing {', '.join(missing)}")
    return module


def _load(module_name: str) -> ModuleType:
    return _verify(import_module(f"{__name__}.{module_name}"), module_name)


def loaded() -> list[ModuleType]:
    """Import every installed payload type. Order is not significant."""
    return [_load(name) for name in names()]


def get(name: str) -> ModuleType:
    """Resolve one payload type by ``NAME`` or by a declared alias."""
    if not isinstance(name, str) or not name.strip():
        raise UnknownPayload("no payload type was named")
    wanted = name.strip()
    for module in loaded():
        if wanted == module.NAME or wanted in getattr(module, "ALIASES", ()):
            return module
    raise UnknownPayload(
        f"unknown payload type {wanted!r}; available: {', '.join(names())}")


def _decide(test, *, subject: str) -> ModuleType:
    modules = loaded()
    claimed = [module for module in modules
               if not getattr(module, "LAST_RESORT", False) and test(module)]
    if len(claimed) > 1:
        raise UnknownPayload(
            f"{subject} is claimed by more than one payload type: "
            f"{', '.join(sorted(module.NAME for module in claimed))}")
    if claimed:
        return claimed[0]
    fallback = [module for module in modules if getattr(module, "LAST_RESORT", False)]
    if len(fallback) == 1:
        return fallback[0]
    raise UnknownPayload(
        f"no payload type recognises {subject}"
        + (f"; {len(fallback)} claim to accept anything" if fallback else ""))


def identify(payload: bytes) -> ModuleType:
    """The payload type whose own magic matches these bytes."""
    return _decide(lambda module: bool(getattr(module, "sniff", None))
                   and module.sniff(payload), subject="this payload")


def identify_tree(src_dir: str) -> ModuleType:
    """The payload type an unpacked directory belongs to."""
    return _decide(lambda module: bool(getattr(module, "claims", None))
                   and module.claims(src_dir), subject=f"{src_dir}")
