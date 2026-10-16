"""What each of a project's activities does on a Harmony 800, before any of it is laid out.

A project describes an activity the way every Harmony remote's software does: the devices
it switches on, in order, and the ones it switches off; the input each device is set to;
the devices that play its roles, from which the keypad is routed; any key or on-screen
button that runs something else; and steps to run as it starts and stops. This turns that
into the One's terms - which power and input variables to write, which command each key
and button sends - with every device and command named by the lowered devices' indices,
so the layout (activity_screens.py) only has to place it.

Nothing is dropped quietly: a step this remote cannot carry out is recorded in the plan's
``skipped`` list with the reason, and a step naming a device or command the project does
not have is refused, since the activity would start differently from how it was written.

Format reference: docs/harmony_one/gspm.md
"""
from __future__ import annotations

from . import keypad, keys
from .devices import PRESS_INTERKEY_DEFAULT

VOLUME_KEYS = ("VolumeUp", "VolumeDown", "VolumeMute")
DIGITS = {str(n): f"Number{n}" for n in range(10)}


def plan(project: dict, devices: list[dict]) -> dict:
    """``{"activities": [...], "all_off": {...}, "skipped": [...]}`` for ``project``,
    whose devices were lowered as ``devices`` (generate.lowered_devices), in order."""
    specs = project.get("devices") or []
    index_of = {spec.get("id"): position for position, spec in enumerate(specs)
                if spec.get("id") is not None}
    skipped = []
    out = []
    for activity in project.get("activities") or []:
        out.append(_activity(activity, specs, devices, index_of, skipped))
    # Off turns off every device that has a power command, or the project's own list.
    chosen = project.get("power_off_all")
    if chosen is not None:
        off = [_device(index_of, did, "Off") for did in chosen]
    else:
        off = list(range(len(devices)))
    return {"activities": out,
            "all_off": {"off": [index for index in dict.fromkeys(off)
                                if devices[index].get("power")
                                and not specs[index].get("always_on")],
                        "label": project.get("power_off_label")},
            "skipped": skipped}


def _device(index_of: dict, did, where: str) -> int:
    if did not in index_of:
        raise ValueError(f"{where} names device {did!r}, which the project does not have")
    return index_of[did]


def _activity(activity: dict, specs, devices, index_of, skipped) -> dict:
    label = activity.get("label") or "Activity"
    where = f"activity {label!r}"

    def device(did):
        return _device(index_of, did, where)

    display, control = activity.get("display"), activity.get("control")
    volume = activity.get("volume", display)
    roles = [display, volume, control] + list((activity.get("roles") or {}).values())
    # An explicit plan wins even when it switches nothing on; only an activity without
    # one follows its roles. Every other device is switched off, as every Logitech
    # configuration partitions them.
    if activity.get("power_on_devices") is not None:
        on = [device(did) for did in activity["power_on_devices"]]
    else:
        on = [device(did) for did in roles if did is not None]
    # a device marked Always on is never switched by the remote, either way
    steady = {index for index, spec in enumerate(specs) if spec.get("always_on")}
    on = [index for index in dict.fromkeys(on) if index not in steady]
    off = [index for index in range(len(devices)) if index not in on and index not in steady]

    inputs, enter = [], []
    steps = list(activity.get("enter") or [])
    if activity.get("input"):
        steps.append(["input", *activity["input"]])
    for step in steps:
        if step and step[0] == "input":
            target = device(step[1])
            value = _input_value(devices[target], step[2], where, skipped)
            if value is not None:
                inputs.append((target, value))
        else:
            enter += _steps([step], specs, devices, index_of, where, skipped)
    leave = _steps(activity.get("leave") or [], specs, devices, index_of, where, skipped)

    bound = {}
    for name, (target, command) in _routed_keys(activity, devices, index_of).items():
        bound[name] = [("send", target, command)]
    if activity.get("bound_keys") is not None:
        bound = {name: value for name, value in bound.items()
                 if name in activity["bound_keys"]}
    for name, macro in (activity.get("hard_macros") or {}).items():
        bound[name] = _steps(macro, specs, devices, index_of, f"{where} key {name}",
                             skipped)
    hard = {}
    for name, value in bound.items():
        code = keys.by_name(name)
        if code is None or keys.SCANS[name] in keys.FLOW:
            # a key routed from a device's own slots simply is not on this remote; one
            # the project bound on purpose is worth saying so about
            if name in (activity.get("hard_macros") or {}):
                skipped.append(f"{where}: the 800 has no key {name!r} to bind")
            continue
        hard[code] = value

    buttons = []
    for button in _buttons(activity):
        if button is None:
            buttons.append(None)
            continue
        label_, macro = button
        buttons.append((label_, _steps(macro, specs, devices, index_of,
                                       f"{where} button {label_!r}", skipped)))
    favourites = _favourites(activity, specs, devices, index_of, where, skipped)
    return {"label": label, "type": activity.get("type"), "on": on, "off": off,
            "inputs": inputs, "enter": enter, "leave": leave, "keys": hard,
            "buttons": buttons, "favourites": favourites,
            "numbers": _numbers(activity, devices, index_of)}


def _favourites(activity, specs, devices, index_of, where, skipped) -> list[dict]:
    """An activity's favourite channels: each a logo (or its name) and what tuning to it
    sends - the control device's digits, each held off by its key delay, then the key
    that confirms them, as Logitech's software dials them."""
    entries = list(activity.get("image_buttons") or [])
    entries += [[station, "channel", number, image]
                for station, number, image in activity.get("channels") or []]
    control = activity.get("control")
    confirm = activity.get("channel_confirm")
    out = []
    for label, kind, payload, image in entries:
        here = f"{where} favourite {label!r}"
        if kind == "channel":
            target = _device(index_of, control, here)
            interkey = int(PRESS_INTERKEY_DEFAULT if specs[target].get("press_interkey") is None
                           else specs[target]["press_interkey"])
            steps = []
            for digit in str(payload):
                name = _digit_command(specs[target], digit)
                if name is None:
                    raise ValueError(f"{here} dials {payload} on "
                                     f"{devices[target]['label']!r}, which has no {digit} key")
                steps.append(("send", target, _command(devices, target, name, here)))
                if interkey:
                    steps.append(("wait", target, interkey))
            if confirm:
                steps.append(("send", target, _command(devices, target, confirm, here)))
        elif kind == "command":
            steps = _steps([["command", *payload]], specs, devices, index_of, here, skipped)
        elif kind == "macro":
            steps = _steps(payload, specs, devices, index_of, here, skipped)
        else:
            skipped.append(f"{here}: a {kind!r} favourite is not one the One can send")
            continue
        out.append({"label": label, "image": image, "steps": steps})
    return out


def _input_value(device: dict, name, where, skipped) -> int | None:
    values = (device.get("inputs") or {}).get("values") or []
    if name in values:
        return values.index(name)
    folded = [str(value).casefold() for value in values]
    if str(name).casefold() in folded:
        return folded.index(str(name).casefold())
    skipped.append(f"{where}: {device['label']!r} has no input {name!r}")
    return None


def _command(devices, target: int, name: str, where: str) -> int:
    for command in devices[target]["commands"]:
        if command["name"] == name:
            return command["command_id"]
    raise ValueError(f"{where} sends {name!r} to {devices[target]['label']!r}, "
                     "which has no such command")


def _steps(steps, specs, devices, index_of, where, skipped) -> list[tuple]:
    """A macro's steps as `("send", device, command id)` - with a fourth item, the
    milliseconds it is held for - `("wait", device, ms)` and `("input", device, value)`."""
    out = []
    for step in steps:
        kind = step[0] if step else None
        if kind == "command":
            target = _device(index_of, step[1], where)
            command = _command(devices, target, step[2], where)
            if len(step) > 4 and step[4]:
                # held: a record of its own, the code repeated for that long
                out.append(("send", target, command, int(step[4])))
            else:
                out.append(("send", target, command))
        elif kind == "delay":
            target = _device(index_of, step[1], where) if step[1] in index_of else None
            if target is None:
                target = out[-1][1] if out else None
            if target is None:
                skipped.append(f"{where}: a delay of {step[2]} ms names no device")
                continue
            out.append(("wait", target, int(step[2])))
        elif kind == "input":
            target = _device(index_of, step[1], where)
            value = _input_value(devices[target], step[2], where, skipped)
            if value is not None:
                out.append(("input", target, value))
        elif kind == "number":
            target = _device(index_of, step[1], where)
            for digit in str(step[2]):
                name = _digit_command(specs[target], digit)
                if name is None:
                    raise ValueError(f"{where} dials {step[2]} on "
                                     f"{devices[target]['label']!r}, which has no {digit} key")
                out.append(("send", target, _command(devices, target, name, where)))
        else:
            skipped.append(f"{where}: a {kind!r} step is not something the One can do")
    return out


def _digit_command(spec: dict, digit: str) -> str | None:
    """The command a device calls a digit, by its key or by its name."""
    for entry in spec.get("commands") or []:
        slots = entry[4] if len(entry) > 4 else None
        slots = slots if isinstance(slots, list) else [slots]
        if DIGITS[digit] in slots:
            return entry[0]
    names = {entry[0] for entry in spec.get("commands") or []}
    for name in (DIGITS[digit], digit):
        if name in names:
            return name
    return None


def _routed_keys(activity: dict, devices, index_of) -> dict:
    """The keys an activity's roles route: volume and mute to the volume device, every
    other key the control device has a command for to that device."""
    display, control = activity.get("display"), activity.get("control")
    volume = activity.get("volume", display)

    def slots(did):
        if did not in index_of:
            return {}
        target = index_of[did]
        out = {}
        for command in devices[target]["commands"]:
            for name in command.get("keys") or ():
                out.setdefault(name, (target, command["command_id"]))
        return out
    routed = {name: value for name, value in slots(volume).items() if name in VOLUME_KEYS}
    for name, value in slots(control).items():
        routed.setdefault(name, value)
    return routed


def _numbers(activity: dict, devices, index_of) -> list[tuple]:
    """The keypad's twelve places (keypad.NUMPAD), each ``(label, steps)``, the steps None
    for a key the device lacks: the digits of the control device, or the display's when
    the control device has none; no keypad when neither has."""
    for did in (activity.get("control"), activity.get("display")):
        if did not in index_of:
            continue
        target = index_of[did]
        places = keypad.digits(devices[target])
        if places:
            return [(label, None if command is None
                     else [("send", target, command["command_id"])])
                    for label, command in places]
    return []


def _buttons(activity: dict) -> list[tuple[str, list] | None]:
    """An activity's on-screen buttons, in order, each with the steps it runs - None for
    a gap, a place on its page left empty."""
    out = []
    groups = activity.get("screen_groups")
    entries = ([button for _name, buttons in groups for button in buttons] if groups
               else activity.get("soft_buttons") or [])
    for entry in entries:
        if entry is None:            # a gap: that place on the page stays empty
            out.append(None)
            continue
        if isinstance(entry, dict) and entry.get("blank"):   # a place emptied on an 1100
            continue
        if isinstance(entry, dict):
            label = entry.get("label") or ""
            macro = entry.get("macro") or [["command", entry.get("device"),
                                            entry.get("command")]]
        else:
            label, macro = entry[0], [["command", entry[1], entry[2]]]
        out.append((label, macro))
    while out and out[-1] is None:          # nothing after the last button
        out.pop()
    return out
