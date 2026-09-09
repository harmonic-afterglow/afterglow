"""Persistent same-device baseline contract for Harmony One authoring."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ... import payloads
from . import gspm


MODE = "same-device-native-payload"


def _identity(profile) -> dict:
    return {
        key: getattr(profile, key)
        for key in ("arch", "skin", "flash", "board", "software_type")
    }


def descriptor(source, payload: bytes, profile) -> dict:
    """Describe the immutable native image an imported project must rebuild from."""
    gspm.validate(payload)
    return {
        "mode": MODE,
        "backend": "harmony-one",
        "remote": profile.id,
        "identity": _identity(profile),
        "source": str(Path(source).resolve()),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def load(project: dict, profile) -> tuple[bytes, dict]:
    """Load and authenticate the baseline named by a portable project."""
    record = (project.get("settings") or {}).get("baseline")
    if not isinstance(record, dict) or record.get("mode") != MODE:
        raise ValueError(
            "Harmony One authoring requires an imported same-device native baseline")
    if record.get("backend") != "harmony-one" or record.get("remote") != profile.id:
        raise ValueError("Harmony One baseline belongs to a different backend or remote")
    if record.get("identity") != _identity(profile):
        raise ValueError("Harmony One baseline identity does not match the selected profile")
    source = record.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("Harmony One baseline has no source directory")
    path = Path(source)
    if not path.is_dir():
        raise ValueError(f"Harmony One baseline directory no longer exists: {path}")
    payload = payloads.get(profile.payload).build(str(path))
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != record.get("size") or digest != record.get("sha256"):
        raise ValueError("Harmony One baseline bytes changed since the project was imported")
    validation = gspm.validate(payload)
    return payload, {
        "mode": MODE, "source": str(path), "sha256": digest,
        "size": len(payload), "validation": validation,
    }
