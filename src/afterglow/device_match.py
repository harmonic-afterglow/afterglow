"""Which models in the IR archive a device is, from what its commands send and its name.

A configuration read off a Harmony One keeps a device's commands and its name - "Sony AV
Receiver", "Vizio" - but no manufacturer or model, and names only the commands a button
shows. The archive's code index (build_index.py there) says which command sets send a
code; the sets most of a device's codes are in are what it may be. Its name breaks the
ties a common code leaves: many Sony receivers share a power code, few are called
"Receiver" and made by Sony. A suggestion is only that: someone picks it, or not.

Format reference: docs/ir-recognition.md, "The code index"
"""
from __future__ import annotations

import re
from collections import Counter

from . import ir_protocol, ir_recognise

# How many of a device's codes are looked up: each is a shard of the index to fetch.
SAMPLE = 12
# How many of the best-voted sets are ranked by name, and how many are read in full.
SHORTLIST, CONFIRMED = 40, 5


def _keys(device: dict) -> dict[str, str]:
    """Each command's key, by name, for those whose first frame has one."""
    library = None
    out = {}
    for name, signal in (device.get("signals") or {}).items():
        pulses = None
        if signal.get("kind") == "waveform":
            pulses = signal["pulses_us"]
        elif signal.get("kind") == "protocol":
            if library is None:
                library = {**ir_protocol.catalog(),
                           **(device.get("portable_protocol_definitions") or {})}
            try:
                rendered = ir_protocol.render_transmission(signal, library=library)[0]
            except (KeyError, LookupError, ValueError):
                rendered = None
            pulses = rendered["pulses_us"] if rendered else None
        key = ir_recognise.fingerprint(pulses) if pulses else None
        if key:
            out[name] = key
    return out


def _words(text) -> set[str]:
    return {word for word in re.split(r"[^0-9a-z]+", str(text or "").casefold()) if word}


def _named(device: dict, user: dict) -> int:
    """How much a model's name agrees with the device's: its manufacturer named counts
    most, then its model's words, then its type."""
    said = _words(device.get("label")) | _words(device.get("mfr") or device.get("manufacturer"))
    score = 4 * bool(_words(user.get("manufacturer")) & said)
    score += 2 * len(_words(user.get("model")) & said)
    kind = _words(re.sub(r"(?<!^)(?=[A-Z])", " ", str(user.get("type") or "")))
    return score + bool(kind & (said | _words(device.get("type"))))


def suggest(device: dict, archive, *, limit: int = 3) -> list[dict]:
    """The models ``device`` may be, best first, each ``{"codeset", "matched", "keyed",
    "models": [{id, manufacturer, model, type}], "names": {command: the set's name}}``:
    how many of its keyed commands the set sends, and what the set calls them. Empty
    when the archive has no code index or no set sends its codes."""
    if not getattr(archive, "has_code_index", False):
        return []
    keys = _keys(device)
    if not keys:
        return []
    # the commands a button names first: a numbered one may be anything
    sample = sorted(set(keys.values()), key=lambda key: (
        not any(not name[:1].isdigit() for name, k in keys.items() if k == key), key))[:SAMPLE]
    votes = Counter()
    for key in sample:
        votes.update({codeset for codeset, _name in archive.code_sets_sending(key)})
    if not votes:
        return []
    ranked = []
    for codeset, count in votes.most_common(SHORTLIST):
        users = archive.code_set_users(codeset)
        named = max((_named(device, user) for user in users), default=0)
        ranked.append((count, named, codeset, users))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    out = []
    for _count, named, codeset, users in ranked[:CONFIRMED]:
        theirs = {}
        for command in archive.code_set(codeset):
            pulses = _pronto(command.get("pronto"))
            key = ir_recognise.fingerprint(pulses) if pulses else None
            if key:
                theirs.setdefault(key, command.get("Name"))
        names = {name: theirs[key] for name, key in keys.items() if key in theirs}
        users.sort(key=lambda user: -_named(device, user))
        out.append({"codeset": codeset, "matched": len(names), "keyed": len(keys),
                    "named": named, "models": users, "names": names})
    out.sort(key=lambda item: (-item["matched"], -item["named"], item["codeset"]))
    return out[:limit]


# An import looks up only a device with this many commands it can key: the
# testers' two-command IR relays "matched" an LG television.
LOOK_UP_FROM = 8
# How much of a device a set must send for its model to be set without asking, and
# to be offered at all: a Daikin set sending one of ten codes is chance.
CONFIDENT, PLAUSIBLE = 0.9, 0.5


def keyed(device: dict) -> int:
    """How many of the device's commands have a key the code index can look up."""
    return len(_keys(device))


def needs_model(device: dict) -> bool:
    """Whether the device says nothing of what it is: no maker, no model."""
    return not any(str(device.get(field) or "").strip()
                   for field in ("mfr", "manufacturer", "model"))


def worth_looking_up(device: dict) -> bool:
    """A device an import offers to look up: it names no model, and sends enough
    codes that a set sending them all is no chance."""
    return needs_model(device) and keyed(device) >= LOOK_UP_FROM


def plausible(found: list[dict]) -> list[dict]:
    """The suggestions that send at least half of the device's keyed codes."""
    return [item for item in found if item["matched"] >= PLAUSIBLE * item["keyed"]]


def candidates(found: list[dict]) -> list[tuple[dict, dict]]:
    """Every model the suggestions name, once, ``(suggestion, model)`` best first: the
    set that sends most of the device's codes, then the model whose name agrees."""
    out, seen = [], set()
    for suggestion in found:
        for model in suggestion["models"]:
            name = (str(model.get("manufacturer") or "").casefold(),
                    str(model.get("model") or "").casefold())
            if name not in seen:
                seen.add(name)
                out.append((suggestion, model))
    return out


def confident(device: dict, found: list[dict]) -> tuple[dict, dict] | None:
    """The one model ``device`` must be, or None when someone should choose: it sends
    nearly all the device's codes, no other model sends as many, and the device's
    name names its maker - many models share one set, and a set can be anyone's."""
    if not found or found[0]["keyed"] < LOOK_UP_FROM or \
            found[0]["matched"] < CONFIDENT * found[0]["keyed"]:
        return None
    best = [item for item in found if item["matched"] == found[0]["matched"]]
    models = candidates(best)
    if len(models) != 1:
        return None
    suggestion, model = models[0]
    said = _words(device.get("label"))
    if not _words(model.get("manufacturer")) & said:
        return None
    return suggestion, model


def _pronto(text) -> list[int] | None:
    from .logitech_archive import ArchiveError, parse_pronto

    if not text:
        return None
    try:
        return parse_pronto(text)["pulses_us"]
    except ArchiveError:
        return None


# A command an import could not name: "Command 1F", its place in the configuration.
UNNAMED = re.compile(r"^Command [0-9A-F]{2,}$")


def apply(device: dict, suggestion: dict, model: dict, activities=()) -> dict:
    """``device`` as the chosen ``model`` of a ``suggestion``: its manufacturer and model,
    and each command it could not name called what the model's command set calls it -
    unless the device already has a command of that name. What is renamed is followed
    everywhere the device and ``activities`` name it. Returns ``{old: new}``."""
    from . import project_devices

    maker = model.get("manufacturer") or ""
    device["mfr"], device["model"] = maker, model.get("model") or ""
    if "manufacturer" in device:            # an imported One's devices keep it so
        device["manufacturer"] = maker
    taken = set(device.get("signals") or {})
    renames = {}
    for old, new in sorted((suggestion.get("names") or {}).items()):
        if UNNAMED.match(old) and new and new not in taken:
            renames[old] = new
            taken.add(new)
    if not renames:
        return renames
    device["signals"] = {renames.get(name, name): signal
                         for name, signal in (device.get("signals") or {}).items()}
    for signal_name, signal in device["signals"].items():
        if signal.get("name") in renames:
            signal["name"] = signal_name
    device["commands"] = [[renames.get(command[0], command[0]), *command[1:]]
                          for command in device.get("commands") or []]
    project_devices.rename_commands(device, renames, activities)
    return renames
