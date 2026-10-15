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
      "backend": "harmony-pk",
      "status": "verified",
      "capabilities": {"rf_blaster": true, "touchscreen": true},
      "infrared": {"native_protocols": ["nec1"]}
    }

## `status` is a safety gate, not a label

    read-only    identity is known; importing and inspection only
    experimental configs may be built for controlled first-write testing
    verified     configs have been built AND flashed to this remote successfully

Only `verified` profiles are writable through the normal application flow. Getting a
config wrong can strand hardware that cannot be re-flashed from a vendor server any
more, so a new profile defaults to `read-only` and promotion is explicit.

The skin id identifies the model (`library/remotes/models.json`, indexed by skin,
from Concordance's table). Identity is read straight out of a config's
`<INTENDEDVERSION>`, which is exactly what libconcord's `get_identity` returns.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import paths

SCHEMA = "afterglow-remote/1"
LIBRARY = paths.library("remotes")

VERIFIED = "verified"
EXPERIMENTAL = "experimental"
READ_ONLY = "read-only"
UNTESTED = "untested"  # legacy profile value; loaded as READ_ONLY
STATUSES = frozenset({READ_ONLY, EXPERIMENTAL, VERIFIED})


class UnknownRemote(LookupError):
    """No profile matches this configuration's identity."""


class NotWritable(PermissionError):
    """Refusing to write a config for a remote nobody has verified."""


class NotBuildable(PermissionError):
    """Refusing to build for a profile that has not entered controlled testing."""


# What the interface can offer, and the order it offers it in. Every profile's
# `interface` section has to name the subset its remote has - there is no default, since
# a default is a guess about a remote nobody described.
TABS = ("devices", "activities", "settings", "flash")
DEVICE_PAGES = ("search", "identity", "commands", "screen", "inputs", "timing", "advanced")
ACTIVITY_PAGES = ("identity", "roles", "favourites", "screen_buttons", "hard_buttons",
                  "startup", "power", "advanced")
SETTINGS_FIELDS = ("output_file", "owner", "language", "rf_blasters", "theme", "preferences")
# The device Timing page's fields, by the project key each one sets.
TIMING_FIELDS = ("always_on", "power_delay", "press_presilence", "press_interkey",
                 "hold_presilence", "hold_interkey", "input_delay", "app_power_delay")
# What each list may contain, and what it must: a device is its commands, and so on.
INTERFACE = {
    "tabs": (TABS, ("devices", "flash")),
    "device_pages": (DEVICE_PAGES, ("identity", "commands")),
    "activity_pages": (ACTIVITY_PAGES, ("identity", "roles")),
    "settings": (SETTINGS_FIELDS, ("output_file",)),
    "timing": (TIMING_FIELDS, ()),
}


def _check_interface(profile_id: str, interface, preferences) -> None:
    """Refuse a profile whose interface section is missing, incomplete or unknown."""
    if not isinstance(interface, dict):
        raise ValueError(f"{profile_id}: no interface section - a profile must name the "
                         "tabs, editor pages, settings and languages its remote has")
    for key, (known, required) in INTERFACE.items():
        listed = interface.get(key)
        if not isinstance(listed, list):
            raise ValueError(f"{profile_id}: interface.{key} must be a list")
        unknown = [name for name in listed if name not in known]
        if unknown:
            raise ValueError(f"{profile_id}: unknown interface.{key} {unknown}; "
                             f"known: {list(known)}")
        missing = [name for name in required if name not in listed]
        if missing:
            raise ValueError(f"{profile_id}: interface.{key} must include {missing}")
    grid = interface.get("screen_grid")
    if grid is not None and not (
            isinstance(grid, dict) and set(grid) <= {"device", "activity"} and all(
                isinstance(size, list) and len(size) == 2
                and all(isinstance(n, int) and n > 0 for n in size)
                for size in grid.values())):
        raise ValueError(f"{profile_id}: interface.screen_grid gives a device's and an "
                         "activity's page as [columns, rows]")
    screens = interface.get("activity_screens")
    if screens is not None and not (
            isinstance(screens, dict) and isinstance(screens.get("tabs"), list)
            and all(isinstance(tab, dict) and tab.get("group") and tab.get("flag")
                    for tab in screens["tabs"])):
        raise ValueError(f"{profile_id}: interface.activity_screens lists its tabs, each "
                         "with the group it shows and the property that turns it on")
    languages = interface.get("languages")
    if not isinstance(languages, list) or not languages or not all(
            isinstance(pair, list) and len(pair) == 2 for pair in languages):
        raise ValueError(f"{profile_id}: interface.languages must list [label, LocaleId]")
    offered = {k for k in (preferences or {}) if not k.startswith("_")}
    if "preferences" in interface["settings"] and not offered:
        raise ValueError(f"{profile_id}: interface.settings offers preferences but the "
                         "profile defines none")
    if offered and "preferences" not in interface["settings"]:
        raise ValueError(f"{profile_id}: preferences are defined but interface.settings "
                         "does not offer them")
    for key, spec in (preferences or {}).items():
        if key.startswith("_"):
            continue
        for required in ("file", "label", "default"):
            if required not in spec:
                raise ValueError(f"{profile_id}: preference {key} has no {required}")
        if ("choices" in spec) == ("range" in spec):
            raise ValueError(f"{profile_id}: preference {key} needs choices or a range")


def comparable(field: str, value):
    """An identity value in the form a configuration file and a live remote share.

    The board is major.minor.micro, and only the first two are recorded anywhere but
    the live remote: Concordance writes every dump's header as `%i.%i.0`, and Logitech's
    own Harmony 900 files all say 0.1.0, while a live 900 reports its real micro
    revision (0.1.15 on one). Comparing all three refused remotes that are the same
    model, so the micro revision is left out of every comparison.
    """
    if field == "board" and isinstance(value, str):
        return ".".join(value.split(".")[:2])
    # The flash chip as manufacturer:device numbers, however the hex is cased or written:
    # a live One reported `0x1f:0xc8` against the profile's `0x1F:0xC8`, and the same chip
    # was refused.
    if field == "flash" and isinstance(value, str):
        try:
            return tuple(int(part, 16) for part in value.split(":"))
        except ValueError:
            return value
    return value


@dataclass(frozen=True)
class RemoteProfile:
    id: str
    model: str
    arch: int | None = None
    skin: int | None = None
    flash: str | None = None
    board: str | None = None
    software_type: int | None = None
    # What the remote reports as its software type while in Safe Mode - the Harmony
    # 900 says 4 there, 0 otherwise. The same remote, running its recovery image: it
    # can still be read and written, and writing it is how it gets out.
    safe_mode_software_type: int | None = None
    firmware_min: str | None = None
    firmware_max: str | None = None
    payload: str = ""          # required in the JSON; see load()
    backend: str = ""          # implementation selector, separate from capabilities
    status: str = READ_ONLY
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
    # What the interface shows for this model - tabs, editor pages, settings rows, the
    # languages its firmware has - and the remote's own settings files. Both are the
    # profile's to say: models differ in all of them.
    interface: dict = field(default_factory=dict)
    preference_definitions: dict = field(default_factory=dict)
    # Other skin numbers for the same remote: the same firmware sold under another
    # model number (the Harmony 1100 is skin 63 and 62). Matched like `skin`.
    other_skins: tuple = ()
    # Other board revisions of the same remote (the Harmony 1100 is board 0.3 and 0.5).
    # Matched like `board`.
    other_boards: tuple = ()
    notes: str = ""
    # The remote's own folder (`<id>/profile.json`), which holds what belongs to this
    # remote alone - its drawing. None for a profile that is a bare JSON file.
    folder: Path | None = None
    # The folder's `art.json`: the drawing, where each key sits on it, and how it was cut
    # from the user guide (tools/remote_art.py). Kept out of the profile, which says what
    # the remote is rather than how it looks.
    art: dict | None = None

    @property
    def skins(self) -> tuple:
        return tuple(s for s in (self.skin, *self.other_skins) if s is not None)

    @property
    def boards(self) -> tuple:
        return tuple(b for b in (self.board, *self.other_boards) if b is not None)

    def same_board(self, a, b) -> bool:
        """Whether two board revisions are this remote's, or simply equal."""
        known = {comparable("board", board) for board in self.boards}
        a, b = comparable("board", a), comparable("board", b)
        return a == b or {a, b} <= known

    def _offered(self, key: str) -> tuple:
        """The listed names, in the interface's own order (checked when loaded)."""
        known, _required = INTERFACE[key]
        listed = self.interface[key]
        return tuple(name for name in known if name in listed)

    @property
    def tabs(self) -> tuple:
        """The main window's tabs this model has, in window order."""
        return self._offered("tabs")

    @property
    def device_pages(self) -> tuple:
        return self._offered("device_pages")

    @property
    def activity_pages(self) -> tuple:
        return self._offered("activity_pages")

    @property
    def settings_fields(self) -> tuple:
        return self._offered("settings")

    @property
    def timing_fields(self) -> tuple:
        """The device Timing page's fields this remote's builder uses."""
        return self._offered("timing")

    @property
    def activity_screens(self) -> dict | None:
        """An activity's screen as a set of tabs, for a remote that has one (the 1100):
        each tab's group, the property that turns it on, and its named slots - or None
        where an activity's screen is one page of buttons."""
        return self.interface.get("activity_screens")

    def activity_tabs(self, act: dict) -> dict:
        """{property: "True"} for the tabs a new activity's screen has, on a remote whose
        activity screen is a set of tabs (the 1100) - each turned on by a property, and
        with none on, the remote shows no screen at all. As Logitech gives them for the
        activity's type (the `applies_to` of each tab's property), or as it gives a
        generic activity for a type it never used; and any tab the activity has buttons
        on. An activity's own property says otherwise."""
        screens = self.activity_screens
        if not screens:
            return {}
        declared = (self.properties or {}).get("activity") or {}

        def given(kind):
            out = set()
            for tab in screens["tabs"]:
                applies = (declared.get(tab["flag"]) or {}).get("applies_to")
                if applies == "all" or kind in (applies or ()):
                    out.add(tab["flag"])
            return out

        flags = given(act.get("type") or "VirtualGeneric") or given("VirtualGeneric")
        groups = {name for name, _buttons in act.get("screen_groups") or []}
        if act.get("soft_buttons") and not act.get("screen_groups"):
            groups.add("Misc")
        # an activity with favourites shows them: the screen of channels takes its
        # corner from whatever its type would have put there
        if act.get("image_buttons") or act.get("channels"):
            for tab in screens["tabs"]:
                if tab.get("channels"):
                    groups.add(tab["group"])
                    flags -= {other["flag"] for other in screens["tabs"]
                              if other is not tab and other.get("corner") is not None
                              and other.get("corner") == tab.get("corner")}
        flags |= {tab["flag"] for tab in screens["tabs"] if tab["group"] in groups}
        return {flag: "True" for flag in sorted(flags)}

    def start_screen(self, shown: list[str]) -> str | None:
        """The screen a new activity opens on, of the groups it shows: the first the
        profile's `start_prefers` lists, as Logitech set them."""
        prefers = (self.activity_screens or {}).get("start_prefers") or []
        return next((group for group in prefers if group in shown), None)

    def shown_tabs(self, act: dict) -> list[dict]:
        """The tabs an activity's screen shows: its own properties, else what a new
        activity of its type gets (`activity_tabs`). An imported activity's properties
        are all it has."""
        screens = self.activity_screens
        if not screens:
            return []
        given = {} if act.get("properties_complete") else self.activity_tabs(act)
        flags = {**given, **(act.get("properties") or {})}
        return [tab for tab in screens["tabs"] if flags.get(tab["flag"]) == "True"]

    @staticmethod
    def tab_layout(tab: dict, model: str | None) -> list | None:
        """A tab's fixed places, row by row - for the game controller, the pad the
        remote draws for the main device's `model`, or None for a model it draws none
        for. None too for a tab without fixed places."""
        if "layouts" not in tab:
            return tab.get("layout")
        for name, models in (tab.get("layout_by_model") or {}).items():
            if (model or "") in models:
                return tab["layouts"][name]
        return None

    def place_defaults(self, act: dict, devices: dict) -> dict:
        """{group: {place: {device, command, label?}}} - what a fixed place the activity
        does not set sends, on the tabs it shows: the command of the main device (its
        `control`) that goes by the place's name, or by one of the names `fill` lists for
        it; with the tab's `labels` entry, on a tab that draws a label. `devices` is
        {id: device}, each with its `commands` ([name, ...] rows) and `model`. Nothing
        for an imported activity: it has what Logitech gave it."""
        if act.get("properties_complete"):
            return {}
        device = devices.get(act.get("control"))
        if not device:
            return {}
        have = {row[0] for row in device.get("commands") or []}
        out = {}
        for tab in self.shown_tabs(act):
            places = {}
            for row in self.tab_layout(tab, device.get("model")) or []:
                for place in row:
                    if not place:
                        continue
                    names = [place, *(tab.get("fill") or {}).get(place, [])]
                    command = next((name for name in names if name in have), None)
                    if command:
                        places[place] = {"device": device["id"], "command": command}
                        label = (tab.get("labels") or {}).get(place)
                        if label and "label" in tab.get("draws", ()):
                            places[place]["label"] = label
            if places:
                out[tab["group"]] = places
        return out

    def screen_grid(self, kind: str) -> tuple[int, int] | None:
        """(columns, rows) of a device's or an activity's page of buttons on this
        remote's screen, filled row by row - None for a remote with no such page."""
        size = (self.interface.get("screen_grid") or {}).get(kind)
        return tuple(size) if size else None

    @property
    def languages(self) -> tuple:
        """(label, LocaleId) pairs this model's firmware has, in menu order."""
        return tuple(tuple(pair) for pair in self.interface["languages"])

    @property
    def preferences(self) -> dict:
        """{key: definition} for the remote's own settings files, in display order."""
        return {k: v for k, v in (self.preference_definitions or {}).items()
                if not k.startswith("_")}

    @property
    def verified(self) -> bool:
        return self.status == VERIFIED

    @property
    def buildable(self) -> bool:
        return self.status in (EXPERIMENTAL, VERIFIED)

    def can(self, capability: str) -> bool:
        return bool(self.capabilities.get(capability))

    def ir_strategy(self, signal: dict) -> str:
        """How this remote can reproduce a portable signal, without guessing.

        `unsupported` still means the signal is valid and describable; it means only
        that this backend has no proven lowering for it.
        """
        from . import ir_signal

        ir_signal.validate(signal)
        backend = self.backend or self.infrared.get("backend")
        native = signal.get("native") or {}
        evidence_names = (backend,) if backend else ()
        if backend:
            # Backend aliases are migration knowledge, not portable signal semantics.
            # Resolve them through the generic registry so a renamed backend can still
            # reproduce native evidence stored by an older private project.
            from . import backends
            implementation = backends.get(backend)
            evidence_names = getattr(
                implementation, "NATIVE_EVIDENCE_NAMES",
                getattr(implementation, "BACKEND_NAMES", evidence_names),
            )
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

    @property
    def hard_key_aliases(self) -> dict:
        """{a name this model's keys were once called: the key's real name}."""
        return dict(self.vocabulary.get("hard_key_aliases") or {})

    @property
    def hard_key_layout(self) -> list[dict]:
        """Where each physical button sits on the case, for drawing a picture of it.

        One cell per button: grid row and column, spans, the key's configuration name
        (None for a button the configuration cannot bind) and the label printed on it.
        """
        return [
            {"row": row, "column": column, "rows": rows, "columns": columns,
             "key": key, "label": label}
            for row, column, rows, columns, key, label
            in self.vocabulary.get("hard_key_layout") or []
        ]

    @property
    def hard_key_art(self) -> dict | None:
        """The remote's own picture and where each key sits on it, for the keys view:
        {"svg": path, "view": (x, y, w, h) shown, "keys": {key: (x, y, w, h)},
        "unassignable": {name: (x, y, w, h)}} in the drawing's units - a key cut from a
        ring is the corners of its wedge instead - or None for a remote nobody has drawn
        yet (the grid of `hard_key_layout` then)."""
        art = self.art
        if not art or self.folder is None:
            return None
        return {"svg": self.folder / art["svg"],
                "view": tuple(art["view"]) if art.get("view") else None,
                "keys": {key: tuple(box) for key, box in art["keys"].items()},
                "unassignable": {name: tuple(box) for name, box
                                 in (art.get("unassignable") or {}).items()}}

    def key_label(self, key: str) -> str:
        """A key as people call it - "Volume +", "OK" - rather than as a configuration
        does: the profile's `hard_key_labels`, else the label its grid prints, else the
        name with its words apart."""
        labels = self.vocabulary.get("hard_key_labels") or {}
        if key in labels:
            return labels[key]
        for cell in self.hard_key_layout:
            if cell["key"] == key and cell["label"]:
                return cell["label"]
        return re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", key)

    def require_writable(self) -> None:
        """Whatever can be built can be written. An experimental remote is written the
        same way as a verified one, after a warning and a backup the interface takes
        first (UpdateTab.flash): a separate test-write flow with typed phrases and
        byte-exact read-back checks only failed good writes, and stopped no one."""
        if not self.buildable:
            raise NotWritable(
                f"{self.model} (skin {self.skin}) is {self.status}: its configurations "
                "can be read and inspected, but Afterglow does not build or write them."
            )

    def require_buildable(self) -> None:
        if not self.buildable:
            raise NotBuildable(
                f"{self.model} (skin {self.skin}) is {self.status}: its identity may be "
                "read and inspected, but configs cannot be built until the profile is "
                "explicitly promoted to \"experimental\" for controlled testing."
            )

    def identity_mismatches(self, identity: dict, *, require_all: bool = False,
                            stated=None) -> list[str]:
        """Describe conflicts with the identity constraints declared by this profile.

        Import may identify an older header that omits a field, but a destructive write
        must pass ``require_all=True`` and prove every declared constraint - every one the
        file can state, ``stated`` (ezhex.stated): an MH configuration's description names
        only its skin, and the remote it goes to is checked on every field regardless.
        """
        mismatches = []
        identity = self.normal_identity(identity)
        skin = identity.get("skin")
        if self.other_skins and skin in self.other_skins:
            identity = {**identity, "skin": self.skin}      # the same remote
        board = identity.get("board")
        if self.other_boards and isinstance(board, str) and self.same_board(board, self.board):
            identity = {**identity, "board": self.board}    # another revision of it
        for name, expected in (
            ("arch", self.arch),
            ("skin", self.skin),
            ("flash", self.flash),
            ("board", self.board),
            ("software_type", self.software_type),
        ):
            if expected is None:
                continue
            actual = identity.get(name)
            if actual is None or actual == -1:
                if require_all and (stated is None or name in stated):
                    mismatches.append(f"{name} is unavailable (expected {expected})")
            elif comparable(name, actual) != comparable(name, expected):
                mismatches.append(f"{name} is {actual} (expected {expected})")

        firmware = identity.get("firmware")
        if self.firmware_min or self.firmware_max:
            if not firmware:
                if require_all:
                    mismatches.append("firmware is unavailable")
            else:
                actual = _version(firmware)
                if self.firmware_min and actual < _version(self.firmware_min):
                    mismatches.append(
                        f"firmware is {firmware} (minimum {self.firmware_min})")
                if self.firmware_max and actual > _version(self.firmware_max):
                    mismatches.append(
                        f"firmware is {firmware} (maximum {self.firmware_max})")
        return mismatches

    def in_safe_mode(self, identity: dict) -> bool:
        """Whether this identity is this remote's Safe Mode (see
        `safe_mode_software_type`)."""
        return (self.safe_mode_software_type is not None
                and identity.get("software_type") == self.safe_mode_software_type)

    def normal_identity(self, identity: dict) -> dict:
        """The identity as the remote reports it outside Safe Mode."""
        if self.in_safe_mode(identity) and self.software_type is not None:
            return {**identity, "software_type": self.software_type}
        return identity

    def matches(self, identity: dict) -> bool:
        """Whether every identity field present agrees with this profile."""
        return not self.identity_mismatches(identity)

    def to_json(self) -> dict:
        return {
            "schema": SCHEMA, "id": self.id, "model": self.model,
            "identity": {
                **{k: v for k, v in (("arch", self.arch), ("skin", self.skin),
                                     ("flash", self.flash), ("board", self.board),
                                     ("software_type", self.software_type))
                   if v is not None},
                **({"firmware": {k: v for k, v in (("min", self.firmware_min),
                                                    ("max", self.firmware_max)) if v}}
                   if self.firmware_min or self.firmware_max else {}),
                **({"other_skins": list(self.other_skins)} if self.other_skins else {}),
                **({"other_boards": list(self.other_boards)} if self.other_boards else {}),
                **({"safe_mode_software_type": self.safe_mode_software_type}
                   if self.safe_mode_software_type is not None else {}),
            },
            "payload": self.payload, "backend": self.backend, "status": self.status,
            "capabilities": self.capabilities,
            "infrared": {k: v for k, v in self.infrared.items() if k != "backend"},
            "vocabulary": self.vocabulary,
            "properties": self.vocabulary_properties, "interface": self.interface,
            "preferences": self.preference_definitions, "notes": self.notes,
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


def _required_backend(data: dict) -> str:
    """Read the top-level selector, accepting the old infrared location on import."""
    infrared = data.get("infrared") or {}
    backend = data.get("backend") or infrared.get("backend")
    if not isinstance(backend, str) or not backend.strip():
        raise ValueError(
            f"remote profile {data.get('id', '?')!r} does not name a backend; "
            "add a top-level \"backend\"")
    if data.get("backend") and infrared.get("backend") \
            and data["backend"].strip() != infrared["backend"].strip():
        raise ValueError(
            f"remote profile {data.get('id', '?')!r} names conflicting backends")
    return backend.strip()


def _status(data: dict) -> str:
    status = data.get("status", READ_ONLY)
    if status == UNTESTED:
        return READ_ONLY
    if status not in STATUSES:
        raise ValueError(
            f"remote profile {data.get('id', '?')!r} has unknown status {status!r}")
    return status


def _version(value: str) -> tuple[int, ...]:
    try:
        parts = tuple(int(part) for part in str(value).split("."))
    except ValueError as exc:
        raise ValueError(f"invalid dotted firmware version {value!r}") from exc
    return parts + (0,) * (4 - len(parts))


def _from_json(data: dict) -> RemoteProfile:
    if data.get("schema") != SCHEMA:
        raise ValueError(f"expected schema {SCHEMA!r}, got {data.get('schema')!r}")
    ident = data.get("identity", {})
    firmware = ident.get("firmware") or {}
    if not isinstance(firmware, dict):
        raise ValueError("identity.firmware must contain optional min/max versions")
    for bound in (firmware.get("min"), firmware.get("max")):
        if bound:
            _version(bound)
    if firmware.get("min") and firmware.get("max") \
            and _version(firmware["min"]) > _version(firmware["max"]):
        raise ValueError("identity.firmware min is newer than max")
    payload, backend = _required_payload(data), _required_backend(data)
    _check_interface(data.get("id"), data.get("interface"), data.get("preferences"))
    return RemoteProfile(
        id=data["id"], model=data["model"],
        arch=ident.get("arch"), skin=ident.get("skin"), flash=ident.get("flash"),
        board=ident.get("board"), software_type=ident.get("software_type"),
        safe_mode_software_type=ident.get("safe_mode_software_type"),
        firmware_min=firmware.get("min"), firmware_max=firmware.get("max"),
        payload=payload, backend=backend,
        status=_status(data),
        capabilities=data.get("capabilities", {}),
        infrared=data.get("infrared", {}),
        vocabulary=data.get("vocabulary", {}),
        vocabulary_properties=data.get("properties", {}),
        interface=data["interface"],
        preference_definitions=data.get("preferences", {}),
        other_skins=tuple(ident.get("other_skins") or ()),
        other_boards=tuple(ident.get("other_boards") or ()),
        notes=data.get("notes", ""),
    )


PROFILE = "profile.json"
ART = "art.json"


def load_all(library: Path | str = LIBRARY) -> list[RemoteProfile]:
    """Every profile in the library, verified ones first.

    A remote is a folder - `<id>/profile.json`, with whatever else is the remote's own
    beside it, so removing the folder removes all of it. A bare `<id>.json` is read too,
    for a profile that has nothing else."""
    library = Path(library)
    found = [(path / PROFILE, path) for path in sorted(library.iterdir())
             if (path / PROFILE).is_file()] if library.is_dir() else []
    found += [(path, None) for path in sorted(library.glob("*.json"))
              if path.name != "models.json"]
    profiles = []
    for path, folder in found:
        try:
            profile = _from_json(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"[warn] ignoring remote profile {path}: {exc}")
            continue
        art = folder / ART if folder is not None else None
        try:
            drawn = json.loads(art.read_text(encoding="utf-8")) if art and art.is_file() \
                else None
        except json.JSONDecodeError as exc:            # the keys then show as a grid
            print(f"[warn] ignoring remote drawing {art}: {exc}")
            drawn = None
        profiles.append(replace(profile, folder=folder, art=drawn))
    return sorted(profiles, key=lambda p: (not p.verified, p.model))


def profile_path(profile_id: str, library: Path | str = LIBRARY) -> Path:
    """Where a profile's JSON is."""
    folder = Path(library) / profile_id / PROFILE
    return folder if folder.is_file() else Path(library) / f"{profile_id}.json"


def get(profile_id: str, library: Path | str = LIBRARY) -> RemoteProfile:
    for profile in load_all(library):
        if profile.id == profile_id:
            return profile
    raise UnknownRemote(f"no remote profile with id {profile_id!r}")


def default(library: Path | str = LIBRARY) -> RemoteProfile:
    """The remote a project targets when it names none.

    Only ever the single verified model. With none, or with several, there is no honest
    answer, so this raises rather than picking one - the bug this replaces was every
    module quietly assuming a Harmony 900 on its own.
    """
    verified = [profile for profile in load_all(library) if profile.verified]
    if len(verified) != 1:
        raise UnknownRemote(
            f"{len(verified)} remote models are verified, so a project has to name the "
            "one it is for in settings.remote")
    return verified[0]


def for_project(project: dict, library: Path | str = LIBRARY) -> RemoteProfile:
    """The profile a project is built for: the one it names, else `default()`."""
    remote_id = (project.get("settings") or {}).get("remote")
    return get(remote_id, library) if remote_id else default(library)


def models(library: Path | str = LIBRARY) -> dict:
    """skin id -> {model, manufacturer} for every remote the format knows about."""
    path = Path(library) / "models.json"
    return json.loads(path.read_text(encoding="utf-8"))["models"] if path.is_file() else {}


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
    have = ", ".join(sorted({profile.model for profile in load_all(library)}))
    raise UnknownRemote(
        f"no profile for identity {identity}"
        + (f" (skin {identity.get('skin')} is a {known})" if known else "")
        + f". Afterglow has profiles for: {have} - see "
          "docs/harmony_pk/remote-identities.md for what is known about the others."
    )


def describe(profile: RemoteProfile) -> str:
    caps = ", ".join(sorted(k for k, v in profile.capabilities.items() if v)) or "none declared"
    return (f"{profile.model}  [{profile.status}]\n"
            f"  identity     : arch {profile.arch}, skin {profile.skin}, "
            f"flash {profile.flash}, board {profile.board}\n"
            f"  payload      : {profile.payload}\n"
            f"  capabilities : {caps}\n"
            f"  backend      : {profile.backend or 'none declared'}")


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
        header = ezhex.read(Path(args.config).read_bytes()).header
        print(describe(identify(header)))


if __name__ == "__main__":
    main()
