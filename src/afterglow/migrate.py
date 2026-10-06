"""Move a project to another remote, and say exactly what does not come with it.

A project is portable by design: devices are named commands with portable signals,
activities refer to them by role. What is not portable is what each remote can be told -
its device and activity types, the keys on its case, whether it has a touchscreen or RF
blasters, which properties it has, which signals its backend can reproduce. All of that
is in the target's profile, so migrating is reading the project against that profile.

Nothing is dropped quietly. Every rename, substitution and removal is a row in the
report, which the interface shows before anything is written, and the result is a new
project: the one it came from is left as it was.
"""
from __future__ import annotations

from copy import deepcopy

from . import ir_protocol, project_devices, remotes

# A device or activity type the target lacks becomes the most generic one it has.
FALLBACK_DEVICE_TYPE = "HomeAppliance"
FALLBACK_ACTIVITY_TYPE = "VirtualGeneric"
# The all-off activity is the remote's own, not a type a user picks.
BUILT_IN_ACTIVITY_TYPES = {"PowerOff"}


def _row(report, subject, change, detail):
    report.append({"subject": subject, "change": change, "detail": detail})


def migrate(project: dict, target) -> tuple[dict, list[dict]]:
    """The project rebuilt for `target` (a profile or an id), and what changed.

    Each report row is ``{"subject", "change", "detail"}``; `change` is one of
    ``renamed``, ``substituted`` or ``removed``.
    """
    target = target if isinstance(target, remotes.RemoteProfile) else remotes.get(target)
    if not target.buildable:
        raise remotes.NotBuildable(
            f"{target.model} is {target.status}: nothing can be built for it yet")
    try:
        source = remotes.for_project(project)
    except LookupError:
        source = None
    out = deepcopy(project)
    report: list[dict] = []
    settings = out.setdefault("settings", {})
    settings["remote"] = target.id

    _keys(out, target, report)
    _types(out, target, report)
    if not target.can("touchscreen"):
        _touchscreen(out, report)
    if not target.can("rf_blaster"):
        _rf(out, report)
    if source is not None:
        _preferences(out, source, target, report)
    _properties(out, source, target, report)
    _signals(out, target, report)
    return out, report


def _keys(project, target, report):
    renamed = project_devices.rename_hard_keys(project, target.hard_key_aliases)
    if renamed:
        _row(report, "Physical keys", "renamed",
             f"{renamed} binding(s) moved to the name {target.model} uses for that key")
    keys = set(target.hard_keys)
    if not keys:
        return
    # One row per device and per activity, naming every key it loses: a remote with a
    # smaller keypad loses a dozen keys at once, and a row each buried everything else.
    for device in project.get("devices") or []:
        lost = []
        for command in device.get("commands") or []:
            if len(command) < 5 or not command[4]:
                continue
            slots = command[4] if isinstance(command[4], list) else [command[4]]
            missing = [slot for slot in slots if slot not in keys]
            if not missing:
                continue
            kept = [slot for slot in slots if slot in keys]
            command[4] = (kept if isinstance(command[4], list) else
                          (kept[0] if kept else None))
            lost += missing
        if lost:
            _row(report, f"Device {device.get('label')!r}", "removed",
                 f"keys {target.model} does not have: {', '.join(dict.fromkeys(lost))}")
    for activity in project.get("activities") or []:
        macros = activity.get("hard_macros") or {}
        lost = [slot for slot in macros if slot not in keys]
        for slot in lost:
            del macros[slot]
        if lost:
            _row(report, f"Activity {activity.get('label')!r}", "removed",
                 f"what these keys did, which {target.model} does not have: "
                 f"{', '.join(lost)}")
        if activity.get("bound_keys") is not None:
            activity["bound_keys"] = [key for key in activity["bound_keys"] if key in keys]


def _types(project, target, report):
    device_types = target.device_types
    if device_types:
        for device in project.get("devices") or []:
            kind = device.get("type")
            if kind and kind not in device_types:
                new = (FALLBACK_DEVICE_TYPE if FALLBACK_DEVICE_TYPE in device_types
                       else next(iter(device_types)))
                device["type"] = new
                _row(report, f"Device {device.get('label')!r}", "substituted",
                     f"type {kind} is not on {target.model}; it is now {new}")
    activity_types = {identifier for _label, identifier in target.activity_types}
    if activity_types:
        for activity in project.get("activities") or []:
            kind = activity.get("type")
            if kind and kind not in activity_types | BUILT_IN_ACTIVITY_TYPES:
                new = (FALLBACK_ACTIVITY_TYPE if FALLBACK_ACTIVITY_TYPE in activity_types
                       else sorted(activity_types)[0])
                activity["type"] = new
                _row(report, f"Activity {activity.get('label')!r}", "substituted",
                     f"type {kind} is not on {target.model}; it is now {new}")


def _touchscreen(project, report):
    for activity in project.get("activities") or []:
        dropped = [key for key in ("soft_buttons", "image_buttons", "channels")
                   if activity.get(key)]
        for key in dropped:
            count = len(activity.pop(key))
            _row(report, f"Activity {activity.get('label')!r}", "removed",
                 f"{count} {key.replace('_', ' ')}: the remote has no touchscreen")


def _rf(project, report):
    rf = project.get("settings", {}).get("rf")
    if isinstance(rf, dict) and (rf.get("receivers") or rf.get("assign")):
        project["settings"]["rf"] = "front"
        _row(report, "RF blasters", "removed",
             f"{len(rf.get('receivers') or [])} paired blaster(s): the remote has no RF; "
             "every device now uses its own infrared")


def _preferences(project, source, target, report):
    """Keep the remote's own settings the target has, as long as their value fits it."""
    from . import preferences
    settings = project.get("settings", {})
    wanted = preferences.definitions(target)
    dropped = []
    for key in preferences.definitions(source):
        if key not in settings:
            continue
        definition = wanted.get(key)
        value = str(settings[key])
        fits = definition is not None and (
            value in {v for _label, v in preferences.choices(definition)}
            if definition.get("choices") else
            value.isdigit() and preferences.bounds(definition)[0] <= int(value)
            <= preferences.bounds(definition)[1])
        if not fits:
            del settings[key]
            dropped.append(key)
    if dropped:
        _row(report, "Remote's own settings", "removed",
             f"{', '.join(dropped)}: the target remote does not keep "
             f"{'it' if len(dropped) == 1 else 'them'} this way")


def _properties(project, source, target, report):
    """Remove what the source remote has and the target does not.

    A property neither profile declares - per-command timing, or something nobody has
    catalogued yet - is carried, as everything unrecognised is: unknown is not absent.
    """
    from . import properties
    if not target.properties or source is None or not source.properties:
        return                       # nothing to compare against: judge nothing
    theirs, ours = properties.catalog(target), properties.catalog(source)
    for scope, items in (("device", project.get("devices") or []),
                         ("activity", project.get("activities") or [])):
        known, had = set(theirs.get(scope, {})), set(ours.get(scope, {}))
        for item in items:
            values = item.get("properties") or {}
            for name in [name for name in values if name in had and name not in known]:
                del values[name]
                _row(report, f"{scope.title()} {item.get('label')!r}", "removed",
                     f"property {name}: {target.model} does not have it")


def _signals(project, target, report):
    """Commands the target's backend cannot reproduce are taken out, each one listed."""
    from . import backends
    try:
        capability = getattr(backends.for_profile(target), "capability", None)
    except (LookupError, TypeError):
        capability = None
    if not callable(capability):
        _row(report, "Infrared", "substituted",
             f"not checked: {target.model}'s backend cannot say what it reproduces")
        return
    shared = ir_protocol.catalog()
    removed: set[tuple[str, str]] = set()
    for device in project.get("devices") or []:
        library = {**shared, **(device.get("portable_protocol_definitions") or {})}
        signals = device.get("signals") or {}
        lost = []
        for name, signal in list(signals.items()):
            verdict = capability(signal, target, library=library)
            if not verdict.get("supported"):
                lost.append((name, verdict.get("reason", "")))
        if not lost:
            continue
        gone = {name for name, _reason in lost}
        removed |= {(str(device.get("id")), name) for name in gone}
        device["signals"] = {k: v for k, v in signals.items() if k not in gone}
        device["commands"] = [c for c in device.get("commands") or [] if c[0] not in gone]
        for name, reason in lost:
            _row(report, f"Device {device.get('label')!r}", "removed",
                 f"command {name}: {target.model} cannot send it ({reason})")
    if removed:
        _references(project, removed, report)


def _mentions(step, removed) -> bool:
    """Whether one activity step or button sends a command that was taken out."""
    if isinstance(step, (list, tuple)):
        if len(step) >= 3 and step[0] == "command":
            return (str(step[1]), step[2]) in removed
        if len(step) >= 3:                             # (label, device, command[, icon])
            return (str(step[1]), step[2]) in removed
        return False
    if isinstance(step, dict):
        if step.get("macro"):
            return any(_mentions(inner, removed) for inner in step["macro"])
        return (str(step.get("device")), step.get("command")) in removed
    return False


def _references(project, removed, report):
    """Take out what still sends a removed command, so the project still builds."""
    for activity in project.get("activities") or []:
        subject = f"Activity {activity.get('label')!r}"
        macros = activity.get("hard_macros") or {}
        for slot in [slot for slot, steps in macros.items()
                     if any(_mentions(step, removed) for step in steps)]:
            del macros[slot]
            _row(report, subject, "removed",
                 f"what {slot} did: it sent a command this remote cannot send")
        buttons = activity.get("soft_buttons") or []
        kept = [button for button in buttons if not _mentions(button, removed)]
        if len(kept) != len(buttons):
            activity["soft_buttons"] = kept
            _row(report, subject, "removed",
                 f"{len(buttons) - len(kept)} touchscreen button(s) that sent a command "
                 "this remote cannot send")
