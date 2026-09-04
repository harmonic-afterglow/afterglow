#!/usr/bin/env python3
"""Remote profiles: which remote we are talking to, and what it can do.

Nothing in Afterglow should assume a particular remote. A profile says how to
recognise one, which payload format its configuration uses, what it can do, and -
crucially - **whether writing to it has ever actually been verified**.

A profile is a JSON file in `library/remotes/`, so supporting another remote of an
already-implemented architecture is adding a file, not editing code:

    {
      "schema": "afterglow-remote/1",
      "id": "harmony-900",
      "model": "Harmony 900",
      "identity": {"arch": 15, "skin": 61, "flash": "0x01:0x49", "board": "0.1.0"},
      "payload": "pk",
      "status": "verified",
      "capabilities": {"rf_blaster": true, "touchscreen": true},
      "infrared": {"backend": "harmony-pk", "native_protocols": ["nec1"]}
    }

## `status` is a safety gate, not a label

    verified   configs have been built AND flashed to this remote successfully
    untested   the identity is known but nothing has ever been written to one

`untested` profiles can read and inspect; `require_writable()` refuses to write to
them. Getting a config wrong on a remote nobody has tested means bricking hardware
that cannot be re-flashed from a vendor server any more, so the default is no.

The skin id identifies the model (`library/remotes/models.json`, indexed by skin,
from Concordance's table). Identity is read straight out of a config's
`<INTENDEDVERSION>`, which is exactly what libconcord's `get_identity` returns.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

SCHEMA = "afterglow-remote/1"
LIBRARY = paths.library("remotes")

VERIFIED = "verified"
UNTESTED = "untested"


class UnknownRemote(LookupError):
    """No profile matches this configuration's identity."""


class NotWritable(PermissionError):
    """Refusing to write a config for a remote nobody has verified."""


@dataclass(frozen=True)
class RemoteProfile:
    id: str
    model: str
    arch: int | None = None
    skin: int | None = None
    flash: str | None = None
    board: str | None = None
    software_type: int | None = None
    payload: str = ""          # required in the JSON; see load()
    status: str = UNTESTED
    capabilities: dict = field(default_factory=dict)
    # IR meaning is portable; reproduction is not. This records which semantic
    # protocols the backend can lower and what kind of waveform evidence it requires.
    infrared: dict = field(default_factory=dict)
    # What this model can be told: its device and activity types, and the physical keys
    # its case has. Read out of the remote's own firmware, and different per model - a
    # remote without a touchscreen has no screen buttons, one with fewer keys has fewer
    # slots. Empty for a profile that has not been worked out yet.
    vocabulary: dict = field(default_factory=dict)
    # The <Property> entries this model has. Same reasoning as `vocabulary`: the sets
    # differ between models, so this is not something to keep in the code.
    vocabulary_properties: dict = field(default_factory=dict)
    notes: str = ""

    @property
    def verified(self) -> bool:
        return self.status == VERIFIED

    def can(self, capability: str) -> bool:
        return bool(self.capabilities.get(capability))

    def ir_strategy(self, signal: dict) -> str:
        """How this remote can reproduce a portable signal, without guessing.

        `unsupported` still means the signal is valid and describable; it means only
        that this backend has no proven lowering for it.
        """
        from . import ir_signal

        ir_signal.validate(signal)
        backend = self.infrared.get("backend")
        native = signal.get("native") or {}
        evidence_names = (backend,) if backend else ()
        if backend:
            # Backend aliases are migration knowledge, not portable signal semantics.
            # Resolve them through the generic registry so a renamed backend can still
            # reproduce native evidence stored by an older private project.
            from . import backends
            implementation = backends.get(backend)
            evidence_names = getattr(implementation, "BACKEND_NAMES", evidence_names)
        has_native_evidence = any(native.get(name) for name in evidence_names)
        if signal["kind"] == "protocol":
            if signal["protocol"] in self.infrared.get("native_protocols", []):
                return "native-protocol"
            if self.infrared.get("waveform") == "carrier-period" and backend:
                return "render-waveform"
            return "unsupported"
        if signal["kind"] == "waveform":
            waveform = self.infrared.get("waveform")
            if waveform == "native-evidence-only" and backend:
                if has_native_evidence:
                    return "native-waveform"
            if waveform == "carrier-period" and backend:
                if has_native_evidence or signal.get("carrier_hz"):
                    return "native-waveform"
            return "unsupported"
        return "unsupported"

    @property
    def properties(self) -> dict:
        """Which <Property> entries this model has, and what its firmware does with
        each. Merged with the shared descriptions by `properties.catalog`."""
        return {k: v for k, v in (self.vocabulary_properties or {}).items()
                if not k.startswith("_")}

    @property
    def device_types(self) -> dict:
        """{identifier: readable label}, in the order the interface should offer them."""
        return dict(self.vocabulary.get("device_types") or {})

    @property
    def activity_types(self) -> list:
        """[(label, identifier)], in menu order - which is not alphabetical and not the
        order the identifiers sort in."""
        return [tuple(pair) for pair in self.vocabulary.get("activity_types") or []]

    @property
    def hard_keys(self) -> list:
        """The physical buttons this case has, by the name a config calls them."""
        return list(self.vocabulary.get("hard_keys") or [])

    def require_writable(self) -> None:
        if not self.verified:
            raise NotWritable(
                f"{self.model} (skin {self.skin}) is {self.status}: no config has ever been "
                f"flashed to one, so Afterglow will not write for it. Reading and inspecting "
                f"work. To change this, flash a config built for it by hand, confirm the "
                f"remote boots, then set \"status\": \"verified\" in its profile."
            )

    def matches(self, identity: dict) -> bool:
        """Identity from a config header vs this profile. Skin alone identifies the
        model; arch is checked too when the profile declares it."""
        if self.skin is not None and identity.get("skin") != self.skin:
            return False
        if self.arch is not None and identity.get("arch") not in (None, self.arch):
            return False
        return True

    def to_json(self) -> dict:
        return {
            "schema": SCHEMA, "id": self.id, "model": self.model,
            "identity": {k: v for k, v in (("arch", self.arch), ("skin", self.skin),
                                           ("flash", self.flash), ("board", self.board),
                                           ("software_type", self.software_type))
                         if v is not None},
            "payload": self.payload, "status": self.status,
            "capabilities": self.capabilities, "infrared": self.infrared,
            "vocabulary": self.vocabulary,
            "properties": self.vocabulary_properties, "notes": self.notes,
        }


def _required_payload(data: dict) -> str:
    """A profile must say which payload format its configuration uses.

    This used to default to the Harmony 900's format, which quietly contradicted the
    promise at the top of this module: a new profile that forgot the field was not
    rejected, it was silently declared to be a PK ZIP tree. A wrong payload type is not
    a cosmetic error - it decides how bytes are written to hardware that has no vendor
    recovery left. Make the profile say it.
    """
    payload = data.get("payload")
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError(
            f"remote profile {data.get('id', '?')!r} does not name a payload format; "
            "add a \"payload\" naming one of afterglow.payloads")
    return payload.strip()


def _from_json(data: dict) -> RemoteProfile:
    if data.get("schema") != SCHEMA:
        raise ValueError(f"expected schema {SCHEMA!r}, got {data.get('schema')!r}")
    ident = data.get("identity", {})
    return RemoteProfile(
        id=data["id"], model=data["model"],
        arch=ident.get("arch"), skin=ident.get("skin"), flash=ident.get("flash"),
        board=ident.get("board"), software_type=ident.get("software_type"),
        payload=_required_payload(data), status=data.get("status", UNTESTED),
        capabilities=data.get("capabilities", {}),
        infrared=data.get("infrared", {}),
        vocabulary=data.get("vocabulary", {}),
        vocabulary_properties=data.get("properties", {}),
        notes=data.get("notes", ""),
    )


def load_all(library: Path | str = LIBRARY) -> list[RemoteProfile]:
    """Every profile in the library, verified ones first."""
    library = Path(library)
    profiles = []
    for path in sorted(library.glob("*.json")):
        if path.name == "models.json":
            continue
        try:
            profiles.append(_from_json(json.loads(path.read_text())))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"[warn] ignoring remote profile {path.name}: {exc}")
    return sorted(profiles, key=lambda p: (not p.verified, p.model))


def get(profile_id: str, library: Path | str = LIBRARY) -> RemoteProfile:
    for profile in load_all(library):
        if profile.id == profile_id:
            return profile
    raise UnknownRemote(f"no remote profile with id {profile_id!r}")


def models(library: Path | str = LIBRARY) -> dict:
    """skin id -> {model, manufacturer} for every remote the format knows about."""
    path = Path(library) / "models.json"
    return json.loads(path.read_text())["models"] if path.is_file() else {}


# identifying a remote from a configuration
_FIELDS = {"arch": rb"<PROTOCOL>(\d+)</PROTOCOL>", "skin": rb"<SKIN>(\d+)</SKIN>",
           "software_type": rb"<SOFTWARETYPE>(\d+)</SOFTWARETYPE>"}
_TEXT_FIELDS = {"flash": rb"<FLASH>([^<]*)</FLASH>", "board": rb"<BOARD>([^<]*)</BOARD>"}


def identity_of(header: bytes) -> dict:
    """The five identity fields out of a config's `<INTENDEDVERSION>` header.

    `<PROTOCOL>` is what Concordance calls the architecture; the rest are verbatim.
    """
    intended = header.split(b"<INTENDEDVERSION>", 1)[-1].split(b"</INTENDEDVERSION>", 1)[0]
    out = {}
    for key, pattern in _FIELDS.items():
        match = re.search(pattern, intended)
        if match:
            out[key] = int(match.group(1))
    for key, pattern in _TEXT_FIELDS.items():
        match = re.search(pattern, intended)
        if match:
            out[key] = match.group(1).decode("ascii", "replace")
    return out


def identify(header: bytes, library: Path | str = LIBRARY) -> RemoteProfile:
    """Match a config header against the profile library."""
    identity = identity_of(header)
    for profile in load_all(library):
        if profile.matches(identity):
            return profile
    known = models(library).get(str(identity.get("skin")), {}).get("model")
    raise UnknownRemote(
        f"no profile for identity {identity}"
        + (f" (skin {identity.get('skin')} is a {known})" if known else "")
        + ". Afterglow only has a profile for the Harmony 900 - see "
          "docs/harmony_pk/remote-identities.md for what is known about the others."
    )


def describe(profile: RemoteProfile) -> str:
    caps = ", ".join(sorted(k for k, v in profile.capabilities.items() if v)) or "none declared"
    return (f"{profile.model}  [{profile.status}]\n"
            f"  identity     : arch {profile.arch}, skin {profile.skin}, "
            f"flash {profile.flash}, board {profile.board}\n"
            f"  payload      : {profile.payload}\n"
            f"  capabilities : {caps}\n"
            f"  IR backend   : {profile.infrared.get('backend', 'none declared')}")


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="List or identify remote profiles.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="every profile in the library")
    ident = sub.add_parser("identify", help="which remote is this config for?")
    ident.add_argument("config")
    args = parser.parse_args(argv)

    if args.cmd == "list":
        for profile in load_all():
            print(describe(profile), "\n")
    else:
        from . import ezhex
        header, _, _, _ = ezhex._split(Path(args.config).read_bytes())
        print(describe(identify(header)))


if __name__ == "__main__":
    main()
