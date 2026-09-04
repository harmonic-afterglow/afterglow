#!/usr/bin/env python3
"""Lazy device lookup and safe materialization from an external Harmony archive.

The optional Logitech archive contains 276,236 devices.  The GUI's shipped library is
small enough to load eagerly; the archive is not.  This provider reads only its compact
manufacturer index, one selected manufacturer's model index, and finally the one shared
code set chosen by the user.  Nothing is copied into Afterglow's shipped library.

Archive conversion and remote reproduction are deliberately separate questions.  A
command appears in the resulting device only when the selected remote profile can lower
its reviewed semantic signal natively or encode its fixed waveform without flattening a
toggle, intro/repeat lifecycle, or an SsIr hardware limit.  The returned report retains
one verdict per source command so the GUI can show exactly what was accepted or refused.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re

from . import backends, device_json, logitech_archive, paths, remotes


# The archive is read at a **pinned commit**, not from a moving branch.
#
# It is a third-party repository that the application reads device and protocol records
# from at run time. Following `main` means a change there can alter what a build produces
# without anything here changing, which makes a report from a user impossible to
# reproduce: the same version of Afterglow, the same device, a different answer next
# week. Pinning also means an upstream mistake cannot reach anyone until this constant is
# deliberately moved.
#
# `AFTERGLOW_LOGITECH_ARCHIVE_REVISION` overrides it with any branch, tag or commit -
# `main` to follow the tip, a different SHA to test one. That is the escape hatch for
# checking a fix before the pin is updated, and it is why the pin is not a hardcoded URL.
LOGITECH_ARCHIVE_REVISION = "1dbdb5904ab6d3d15418abd1718047b96083a54c"
LOGITECH_ARCHIVE_REPOSITORY = (
    "https://raw.githubusercontent.com/pickysysadmin/logitech-harmony-ir-archive"
)


def logitech_archive_revision() -> str:
    """The archive commit to read, honouring the override."""
    return (os.environ.get("AFTERGLOW_LOGITECH_ARCHIVE_REVISION")
            or LOGITECH_ARCHIVE_REVISION)


def logitech_archive_url() -> str:
    """Base URL for the pinned - or overridden - archive revision."""
    return f"{LOGITECH_ARCHIVE_REPOSITORY}/{logitech_archive_revision()}"


# Kept as a module attribute because callers and tests refer to it by name; it follows
# the override, so importing this module after setting the variable gets the right base.
LOGITECH_ARCHIVE_URL = logitech_archive_url()


@dataclass(frozen=True)
class Manufacturer:
    name: str
    slug: str
    devices: int


@dataclass(frozen=True)
class Model:
    manufacturer: str
    manufacturer_slug: str
    name: str
    filename: str
    global_device_id: int

    @property
    def relative_path(self) -> str:
        return f"devices/{self.manufacturer_slug}/{self.filename}"

    @property
    def display(self) -> str:
        return self.name


# The archive documents only numeric ids. These are the stable, common categories needed
# for initial authoring; an unknown category stays editable on the wizard's Identity page.
DEVICE_TYPES = {
    1: "Television",
    2: "Vcr",
    3: "Cd",
    4: "DvdCd",
    5: "Receiver",
    6: "Amplifier",
    8: "Laserdisc",
    9: "Minidisc",
    12: "Pvr",
    13: "Computer",
    14: "GameConsole",
    18: "MediaCenterPC",
    35: "MediaCenterPC",
    # 10,644 catalogue devices are air conditioners and heat pumps, and the remote has a
    # `ClimateControl` type for exactly that. They were arriving as `HomeAppliance`, the
    # fallback for a type nobody had mapped, which is what the remote uses to decide how
    # the device is presented.
    45: "ClimateControl",
}


class LogitechCatalog:
    """Read the source archive indexes lazily and materialize one selected device."""

    def __init__(self, source, *, remote_id: str = "harmony-900"):
        self.archive = (source if isinstance(source, logitech_archive.Archive)
                        else logitech_archive.Archive(source))
        self.profile = remotes.get(remote_id)
        self._manufacturers: list[Manufacturer] | None = None
        self._models: dict[str, list[Model]] = {}

    @property
    def root(self) -> Path:
        return self.archive.root

    def manufacturers(self, query: str = "", *, limit: int = 200) -> list[Manufacturer]:
        if self._manufacturers is None:
            records = self.archive.read_json("index.json")
            if not isinstance(records, list):
                raise logitech_archive.ArchiveError("index.json must contain a list")
            found = []
            for record in records:
                if not isinstance(record, dict):
                    raise logitech_archive.ArchiveError(
                        "index.json contains a non-object manufacturer")
                name, slug = record.get("n"), record.get("s")
                count = record.get("c", 0)
                if not isinstance(name, str) or not isinstance(slug, str):
                    raise logitech_archive.ArchiveError(
                        "index.json contains an incomplete manufacturer")
                found.append(Manufacturer(name.strip(), slug, int(count)))
            self._manufacturers = found
        needle = query.strip().casefold()
        matches = [entry for entry in self._manufacturers
                   if not needle or needle in entry.name.casefold()]
        return matches[:limit]

    def manufacturer(self, name: str) -> Manufacturer:
        wanted = name.strip().casefold()
        try:
            return next(entry for entry in self.manufacturers(limit=100_000)
                        if entry.name.casefold() == wanted)
        except StopIteration:
            raise LookupError(f"manufacturer {name!r} is not in the archive") from None

    def models(self, manufacturer: str, query: str = "", *, limit: int = 300) -> list[Model]:
        maker = self.manufacturer(manufacturer)
        if maker.slug not in self._models:
            relative = f"devices/{maker.slug}/index.json"
            records = self.archive.read_json(relative)
            if not isinstance(records, list):
                raise logitech_archive.ArchiveError(f"{relative} must contain a list")
            found = []
            for record in records:
                if not isinstance(record, dict):
                    raise logitech_archive.ArchiveError(
                        f"{relative} contains a non-object device")
                filename, model, global_id = (
                    record.get("f"), record.get("m"), record.get("id"))
                # Three of the 276,236 catalogue devices publish a null model and carry
                # no code set. They name nothing and can send nothing, so there is
                # nothing to list - but raising for one of them made the whole
                # manufacturer unreachable, which hid all 20,006 Sony devices. Skip the
                # entry; anything malformed in another way is still refused.
                if model is None:
                    continue
                if (not isinstance(filename, str) or not isinstance(model, str)
                        or not isinstance(global_id, int)):
                    raise logitech_archive.ArchiveError(
                        f"{relative} contains an incomplete device")
                # The archive filename is an address, but it must still be one filename.
                if PurePosixPath(filename).name != filename:
                    raise logitech_archive.ArchiveError(
                        f"device filename escapes its manufacturer: {filename!r}")
                found.append(Model(
                    maker.name, maker.slug, model.strip(), filename, global_id))
            self._models[maker.slug] = found
        needle = query.strip().casefold()
        matches = [entry for entry in self._models[maker.slug]
                   if not needle or needle in entry.name.casefold()]
        return matches[:limit]

    def materialize(self, model: Model) -> dict:
        """Return `{template, commands, counts}` for one archive catalogue device."""
        device, codeset, protocols = logitech_archive.transform_device(
            self.archive, model.relative_path)
        if codeset is None:
            raise ValueError(f"{model.manufacturer} {model.name} has no commands")

        # The definitions this device's commands refer to. A protocol record carries a
        # reviewed `portable` definition, a `generic_portable` one generated from the
        # archive's own field layout, or both; a signal names whichever it uses. They are
        # collected here because the application installs no protocol library, so these
        # are the only description of the device's protocols that exists.
        definitions = {}
        for record in (protocols or {}).values():
            if not isinstance(record, dict):
                continue
            for key in ("portable", "generic_portable"):
                spec = record.get(key)
                if isinstance(spec, dict) and spec.get("id"):
                    definitions.setdefault(spec["id"], spec)

        commands = []
        report = []
        for command in codeset["commands"]:
            verdict = self._command_capability(command, protocols, definitions)
            report.append(verdict)
            if not verdict["supported"]:
                continue
            entry = {
                "name": command["name"],
                "label": command["name"],
                "signal": deepcopy(command["signal"]),
            }
            hard_key = _hard_key(command["name"], self.profile.hard_keys)
            if hard_key:
                entry["hard_key"] = hard_key
            commands.append(entry)

        if not commands:
            reasons = sorted({entry["reason"] for entry in report})
            raise ValueError(
                f"{model.manufacturer} {model.name} has no command {self.profile.model} "
                f"can reproduce faithfully: {'; '.join(reasons)}")

        names = _Commands({entry["name"] for entry in commands})
        template = {
            "schema": device_json.PORTABLE_SCHEMA,
            "manufacturer": device["manufacturer"],
            "model": device["model"],
            "names": [device["model"]],
            "type": DEVICE_TYPES.get(device["device_type"], "HomeAppliance"),
            "source": device["source"],
            "commands": commands,
        }
        control = device.get("control") or {}
        # A published power block is authoritative even where its actions are too long to
        # express here: a device can carry a command named `PowerOn` and still only
        # toggle, so falling back to the name heuristic would invent discrete power.
        power = _archive_power(control.get("power"), names)
        if power is None:
            power = _power(names)
        if power:
            # How long the device needs after being powered before it will accept the
            # next command. The remote already models this as the power state's delay,
            # and an activity that jumps straight to an input switch without it arrives
            # while the set is still waking.
            delay = (control.get("timing") or {}).get("powerOnDelay")
            if isinstance(delay, int) and not isinstance(delay, bool) and delay > 0:
                power["delay_ms"] = delay
            template["power"] = power
        inputs = _archive_inputs(control.get("inputs"), names)
        if inputs is None:
            inputs = _inputs(names)
        if inputs:
            template["inputs"] = inputs
        cycle = _archive_input_cycle(control.get("inputs"), names)
        if cycle:
            template["input_cycle"] = cycle
        declared = _archive_states(control.get("states"), names)
        if declared:
            template["control_states"] = declared
        timing = _archive_timing(control.get("timing"))
        if timing:
            template["timing"] = timing
        if all(str(number) in names for number in range(10)):
            template["numeric"] = _archive_numeric(control.get("channelTuning"), names)
        used = {entry["signal"].get("protocol") for entry in commands
                if isinstance(entry.get("signal"), dict)}
        carried = {key: value for key, value in definitions.items() if key in used}
        if carried:
            template["portable_protocol_definitions"] = carried

        supported = sum(1 for entry in report if entry["supported"])
        return {
            "template": template,
            "commands": report,
            "counts": {"source": len(report), "supported": supported,
                       "excluded": len(report) - supported},
            "catalogue_id": device["id"],
            "codeset": device["codeset"],
        }

    def _command_capability(self, command: dict, protocols: dict,
                            definitions: dict | None = None) -> dict:
        name = command.get("name", "?")
        signal = command.get("signal")
        base = {
            "name": name,
            "classification": command.get("classification", "unknown"),
            "supported": False,
            "strategy": "unavailable",
            "reason": command.get("reason", "no portable signal"),
        }
        if not isinstance(signal, dict):
            return base

        # A derived Pronto with a fixed toggle state is not a faithful replacement for
        # the source protocol. Reviewed semantic signals retain toggle state explicitly.
        wrapper = protocols.get(command.get("protocol")) or {}
        source_protocol = ((wrapper.get("source") or {}).get("record") or {})
        fields = source_protocol.get("keycodeFields") or {}
        has_toggle = any(isinstance(field, dict) and field.get("toggleBit") is not None
                         for field in fields.values())
        if signal.get("kind") == "waveform" and has_toggle:
            base["reason"] = "source protocol has sender toggle state"
            return base

        # Ask the profile's own backend whether it can lower this signal. Shared code must
        # not reach into one - it used to call `ir_compile`, `ssir` and `portable_code`
        # from `harmony_pk` directly, which pins the catalogue to a single remote and is
        # what `backends.capability` exists to replace.
        try:
            from . import ir_protocol
            library = dict(ir_protocol.catalog())
            library.update(definitions or {})
            verdict = backends.for_profile(self.profile).capability(
                signal, self.profile, library=library)
            base.update({
                "supported": bool(verdict.get("supported")),
                "strategy": verdict.get("strategy", "unavailable"),
                "reason": verdict.get("reason", "no reason given"),
            })
            if verdict.get("validation"):
                base["validation"] = verdict["validation"]
        except (KeyError, LookupError, ValueError) as exc:
            base["reason"] = str(exc)
        return base


def online_logitech_catalog(*, cache: Path | None = None,
                            remote_id: str = "harmony-900",
                            follow_latest: bool = False) -> LogitechCatalog:
    """Open the live Logitech database and read only records the user selects.

    `follow_latest` reads the tip instead of the pinned revision. Its cache is kept
    separate, because a record fetched from one revision must not be served as if it came
    from the other - that would make the pin meaningless the moment anyone toggled it.
    """
    revision = "main" if follow_latest else logitech_archive_revision()
    cache_root = (cache or paths.cache_dir() / "sources"
                  / f"logitech-harmony-ir-archive@{revision[:12]}")
    base = f"{LOGITECH_ARCHIVE_REPOSITORY}/{revision}"
    archive = logitech_archive.LiveHttpArchive(base, cache_root)
    return LogitechCatalog(archive, remote_id=remote_id)


def _hard_key(name: str, available: list[str]) -> str | None:
    direct = name if name in available else None
    aliases = {
        "Mute": "VolumeMute",
        "OK": "Select",
        "Enter": "InputAV",
        "Return": "Back",
        "ChannelPrev": "PrevChannel",
        "PreviousChannel": "PrevChannel",
        "SkipForward": "Skip",
        "SkipBack": "Replay",
    }
    candidate = direct or aliases.get(name)
    if candidate in available:
        return candidate
    if re.fullmatch(r"[0-9]", name):
        candidate = f"Number{name}"
        if candidate in available:
            return candidate
    return None


def _archive_numeric(tuning, names) -> bool | dict:
    """How a channel number must be dialled on this device.

    `fixedDigits` is on 57,940 devices - 2 digits on 41,339, 3 on 16,594 - and on those
    channel 7 must be sent as `07` or `007`, or the tuner sits waiting for a digit that
    never arrives. `finish` is on 28,996: send the digits, then `Enter`. Both map onto the
    number block the builder already writes.

    `greaterTen` and `greaterHundred` are the old `-/--` key: a prefix pressed *before*
    the digits. The firmware has somewhere to put one:
    `share/lua/5.1/ethanol/objects/Numeric.lua`, shipped as readable Lua inside the
    firmware image, reads `<GreaterTen>` and `<GreaterHundred>`
    elements of the `<Numeric>` block, each holding an `<Action>` list, and emits them in
    `generateActions`:

        Start actions, then zero-padding to `FixedDigits`, then GreaterTen for a
        two-digit number or GreaterHundred for three to six, then the digits, then Finish.

    Over six digits it refuses outright, so `fixed` is bounded here at six rather than the
    ten this once allowed.

    Returns True - meaning "an ordinary number pad" - when the archive says nothing.
    """
    if not isinstance(tuning, dict):
        return True
    out = {}
    digits = tuning.get("fixedDigits")
    if isinstance(digits, int) and not isinstance(digits, bool) and 0 < digits <= 6:
        out["fixed"] = digits
    finish = _one_command(tuning.get("finish"), names)
    if finish:
        out["finish"] = finish
    for source, target in (("start", "start"), ("greaterTen", "greater_ten"),
                           ("greaterHundred", "greater_hundred")):
        steps = _steps(tuning.get(source), names)
        if steps:
            out[target] = steps
    return out or True


def _archive_input_cycle(inputs, names) -> dict:
    """Stepping actions for a device whose inputs cannot be selected directly.

    The archive names 1,089,512 inputs across 209,010 devices, but only 680,091 of those
    name a command that selects them; the rest belong to devices that can only cycle. For
    those, a list of input names with no way to reach any of them is not useful, and
    `next`/`previous` are the whole of the device's input control.
    """
    if not isinstance(inputs, dict):
        return {}
    out = {}
    for key in ("next", "previous"):
        steps = _steps(inputs.get(key), names)
        if steps:
            out[key] = steps
    return out


def _archive_states(states, names) -> list[dict]:
    """Logitech's declared device states, in a remote-neutral shape.

    15,689 devices declare these - 39,854 states, most often `InputType`, `TVInput`,
    `Screen` and `VideoInput`. They are what an `{"set": …, "to": …}` step refers to, and
    without them such a step names something the configuration never declares.

    The shape is taken from a ground-truth pair rather than guessed: `Panasonic
    TX-P42VT20E` publishes `AV2Input` in the archive *and* appears in a donor
    configuration Logitech itself flashed, and the correspondence there is exact -
    `values[].name` to the state's values, `start`/`finish` to bracketing actions,
    `next`/`previous` to relative actions, and `values[].select` to a discrete action per
    value. This carries the same fields under names that mean nothing to any one remote.

    A value with no route is still declared: knowing a state *has* a value matters even
    when Logitech gives no way to reach it directly, because a `{"to": …}` step elsewhere
    may name it.
    """
    if not isinstance(states, dict):
        return []
    out = []
    for state_id, body in sorted(states.items()):
        if not isinstance(state_id, str) or not isinstance(body, dict):
            continue
        values, select = [], {}
        for value in body.get("values") or []:
            if not isinstance(value, dict) or not isinstance(value.get("name"), str):
                continue
            values.append(value["name"])
            routes = value.get("select") or []
            # More than one route means genuinely different ways to reach the same value,
            # told apart by an undecoded `setType`. Take the first rather than merge them:
            # merging would silently pick one anyway, and pretend it had not.
            for route in routes:
                steps = _steps((route or {}).get("commands"), names)
                if steps:
                    # `setType` is documented upstream as an undecoded enum. Against the
                    # `Panasonic TX-P42VT20E` ground-truth pair it decodes exactly, 11 of
                    # 11 values with no exception: 1 is a plain set, 2 is a *change*. The
                    # firmware keeps them in separate containers, so the distinction is
                    # carried rather than flattened.
                    kind = (route or {}).get("setType")
                    select[value["name"]] = (
                        {"steps": steps, "set_type": kind}
                        if isinstance(kind, int) and not isinstance(kind, bool)
                        else {"steps": steps})
                    break
        if not values:
            continue
        entry = {"id": state_id, "values": values}
        if select:
            entry["select"] = select
        for source, target in (("start", "start"), ("finish", "finish"),
                               ("next", "next"), ("previous", "previous")):
            steps = _steps(body.get(source), names)
            if steps:
                entry[target] = steps
        delay = body.get("valueDelay")
        if isinstance(delay, int) and not isinstance(delay, bool) and delay > 0:
            entry["delay_ms"] = delay
        out.append(entry)
    return out


def _archive_timing(timing) -> dict:
    """Logitech's per-device pacing, in the two fields this project already models.

    Archive schema 2 publishes nine timing fields. Only these two have an existing
    meaning here, so only these two are taken; inventing homes for the rest would be
    modelling by coincidence of name. The others stay on the catalogue device's
    ``control`` block for whoever needs them.

    Deliberately *not* mapped: `pressMinRepeats`. It plausibly explains the native
    minimum-repeat byte, agreeing with 13 of 16 measured donor devices, but three
    disagree - and changing how many times every command transmits deserves better than
    a correlation on decade-old configs.
    """
    if not isinstance(timing, dict):
        return {}
    out = {}
    for source, target in (("interKeyDelay", "press_interkey"),):
        value = timing.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            out[target] = value
    return out


class _Commands:
    """Resolve a control block's command reference to the code set's own spelling.

    Logitech's control data and its code sets disagree about capitalisation: the archive's
    worked example publishes an input selected by `InputAux` while the code set calls it
    `InputAUX`, and matching exactly drops that input silently. Across a 3,000-device
    sample, 14,906 references matched exactly, 255 differed only in case, and **no code
    set contained two commands differing only in case** - so folding is unambiguous. The
    ambiguity guard is kept anyway, because "no counterexample today" is not "never".

    A reference genuinely absent from the code set (3,917 in that sample) still resolves
    to None. Logitech's control data outlives the commands it names.
    """

    def __init__(self, names):
        self.names = set(names)
        folded = {}
        for name in self.names:
            folded.setdefault(name.casefold(), []).append(name)
        self.folded = {key: found[0] for key, found in folded.items()
                       if len(found) == 1}

    def __iter__(self):
        return iter(self.names)

    def __contains__(self, name) -> bool:
        return self.resolve(name) is not None

    def resolve(self, name) -> str | None:
        if not isinstance(name, str):
            return None
        if name in self.names:
            return name
        return self.folded.get(name.casefold())


def _one_command(action, names) -> str | None:
    """A single named command, or None if this action is anything more."""
    if isinstance(action, str):
        return names.resolve(action)
    if isinstance(action, list) and len(action) == 1 and isinstance(action[0], str):
        return names.resolve(action[0])
    return None


def _steps(actions, names: set[str]) -> list | None:
    """One archive action list as device-local steps, or None if it cannot be followed.

    The archive's vocabulary is five kinds of step; four of them have a meaning that does
    not depend on any remote, and those are translated to this project's own device-local
    form - no device ids, because the owning device supplies that:

        "Cmd"                            ->  "Cmd"
        {"command": X, "durationMs": N}  ->  {"command": X, "hold_ms": N}
        {"hold": X}                      ->  {"command": X, "hold_ms": None}
        {"delayMs": N}                   ->  {"delay_ms": N}
        {"set": S, "to": V}              ->  {"set": S, "to": V}

    Returns None rather than a partial list when a step names a command the code set does
    not have, or is a shape not listed above. A sequence with a step missing is not a
    shorter sequence - it selects the wrong input, or half-powers the device - so the
    caller must be able to tell "cannot follow this" from "nothing to do".
    """
    if not isinstance(actions, list):
        return None
    out = []
    for step in actions:
        if isinstance(step, str):
            resolved = names.resolve(step)
            if resolved is None:
                return None
            out.append(resolved)
        elif isinstance(step, dict) and "delayMs" in step:
            delay = step["delayMs"]
            if not isinstance(delay, int) or isinstance(delay, bool) or delay < 0:
                return None
            out.append({"delay_ms": delay})
        elif isinstance(step, dict) and ("command" in step or "hold" in step):
            command = names.resolve(step.get("command") or step.get("hold"))
            if command is None:
                return None
            duration = step.get("durationMs")
            if duration is not None and (not isinstance(duration, int)
                                         or isinstance(duration, bool) or duration < 0):
                return None
            out.append({"command": command, "hold_ms": duration})
        elif isinstance(step, dict) and "set" in step and "to" in step:
            state, value = step["set"], step["to"]
            if not isinstance(state, str) or not isinstance(value, str):
                return None
            out.append({"set": state, "to": value})
        else:
            return None
    return out


def _archive_power(power, names: set[str]) -> dict | None:
    """Logitech's own power control, for the shapes this project can express.

    Returns None only when the archive publishes nothing, so the caller can fall back to
    guessing from command names. **When the archive does publish a power block its
    `type` is authoritative, even where the actions themselves are not expressible here.**

    That distinction is the whole point. The archive's own documentation calls `type` the
    most important field it has after the codes: a device can carry a command named
    `PowerOn` and still be toggle-behaviour, and sending it to turn the set on turns it
    off half the time. Roughly one published power block in sixty is a multi-step sequence
    this model cannot hold; falling back to the name heuristic for those would read
    `PowerOn`/`PowerOff` out of the code set and declare discrete power on a device that
    only toggles. On a sample of 8,000 devices, 90 toggle devices sat in exactly that gap.

    So a block with no expressible action yields a mode and no commands - the caller
    learns "this device toggles, and I do not know how", which is true and safe, rather
    than a confident wrong answer.
    """
    if not isinstance(power, dict):
        return None
    out = {}
    mode = power.get("type")
    if isinstance(mode, str) and mode in ("discrete", "toggle", "none", "unknown"):
        out["mode"] = mode
    for key in ("on", "off", "toggle"):
        command = _one_command(power.get(key), names)
        if command:
            out[key] = command
    # A toggle device has no discrete on/off however the code set names its commands.
    if out.get("mode") == "toggle":
        out.pop("on", None)
        out.pop("off", None)
    return out


def _archive_inputs(inputs, names: set[str]) -> list[list[str]] | None:
    """Logitech's own input list, for the entries this project can express.

    Returns None when the archive publishes nothing, so the caller can fall back to the
    name heuristic; returns a (possibly empty) list when it does, because Logitech saying
    an appliance has no selectable inputs is information and the heuristic's guess is not.

    The heuristic reads every command starting "Input" as an input, which is wrong in
    both directions. `Magnavox RJ5540` is the archive's own worked example: it publishes
    two inputs, "VCR/AUX" and "TV", each selected by `InputNext`, a 500 ms wait, then
    `InputAux`/`InputTuner`. The heuristic invents a third input called "Next" out of the
    stepping command and claims all three are directly selectable.

    A multi-step entry keeps its whole sequence, as a list of device-local steps; a
    single-command one stays a bare command name so existing readers are unaffected. An
    entry is dropped only when it has no commands at all (Logitech publishes many that
    name an input without saying how to reach it) or names a command the code set lacks -
    never flattened to its first step, which would select whatever input is adjacent.
    """
    if not isinstance(inputs, dict):
        return None
    out = []
    for entry in inputs.get("list") or []:
        if not isinstance(entry, dict):
            continue
        label = entry.get("name")
        if not isinstance(label, str) or not label:
            continue
        steps = _steps(entry.get("commands"), names)
        if not steps:
            continue
        command = _one_command(entry.get("commands"), names)
        # The common case stays a bare command name, so every existing reader of
        # `inputs` keeps working unchanged; only a real sequence becomes a list.
        out.append([label, command] if command else [label, steps])
    return out


def _power(names: set[str]) -> dict:
    power = {}
    for command, field in (("PowerOn", "on"), ("PowerOff", "off"),
                           ("PowerToggle", "toggle")):
        if command in names:
            power[field] = command
    return power


def _inputs(names: set[str]) -> list[list[str]]:
    out = []
    for name in sorted(names):
        if not name.casefold().startswith("input"):
            continue
        label = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", name[5:]).strip() or name
        out.append([label, name])
    return out
