"""A project's devices as a generated 5xx holds them: each command lowered to a record's
waveforms, its keys, and whether a page shows it.

A command's identifier carries its device in the high byte and its ordinal in the low
one, as on every GSPM remote, so a device holds at most 255 commands.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

import re

from . import ir_lowering, keys
from .structures import OBJECT_ATOM

# the name an import gives a command nothing else names: its ordinal (command_index.py)
NUMBERED = re.compile(r"Command ([0-9A-F]{2})")
# What a device that does not say waits after switching on - what the device editor shows
# for one (gui/device_wizard.py), so a build never does other than what the editor showed.
POWER_DELAY_DEFAULT = 1500
# "From any value": it runs on every write, the same value included, which is how picking
# the running activity again re-sends its inputs.
TRANSITION_FROM_ANY = 0xFFFE
WAIT = 0x7C                    # (device << 8 | tenths): wait before that device's next send


def waits(device_index: int, milliseconds: int) -> list[tuple[int, int]]:
    """A wait in tenths of a second, a hundred at a time, as Logitech writes long ones."""
    tenths = round(milliseconds / 100)
    out = []
    while tenths > 0:
        chunk = min(100, tenths)
        out.append(((device_index << 8) | chunk, WAIT))
        tenths -= chunk
    return out


def transition(source: int, target: int, operand: int, category: int) -> dict:
    return {"flags": 0, "from": source, "to": target, "operand": operand,
            "category": category}


def device_state_records(device: dict, place_object, states: dict[str, int] | None = None
                         ) -> list[tuple[str, dict]]:
    """A device's `<Label>_Power_2` and `<Label>_Input_<n>` variables, with transitions.

    As downstairs and upstairs build them: power going 1 to 0 sends the off command, 0 to
    1 sends the on command and then waits the power-on delay; an input chosen directly
    is a transition from any value to it sending that input's command, and inputs reached
    by stepping get one transition per ordered pair, sending "next" as many times as it
    takes with the input delay after each. ``place_object`` numbers an object body.

    ``states`` numbers the device's other states' variables, by id, which an input's
    sequence may set; ``place_object`` numbers an object's atoms.
    """
    label = device["label"].replace(" ", "_")
    index = device["index"]
    objects = {command["command_id"]: command["object_index"]
               for command in device["commands"]}
    states = states or {}

    def atoms_of(steps):
        """Steps as instructions: a send its command's object, a wait `7C`, another state
        set a write of its variable (``states``, by id), the atoms given as they are."""
        out_atoms = []
        for step in steps:
            if step[0] == "send":
                out_atoms.append((objects[step[1]], OBJECT_ATOM))
            elif step[0] == "wait":
                out_atoms += waits(index, step[1])
            elif step[0] == "set":
                out_atoms.append((step[2], 0x80 | states[step[1]]))
            else:
                out_atoms += step[1]
        return out_atoms
    out = []
    power = device.get("power")
    if power:
        on = [(objects[power["on"]], OBJECT_ATOM)] + waits(index, power["delay_ms"])
        on_operand = place_object(on) if len(on) > 1 else objects[power["on"]]
        off_operand = (place_object(atoms_of(
            [("send", command) for command in power["off_steps"]]))
            if power.get("off_steps") else objects[power["off"]])
        # a device kept on (`always_on`) keeps the variable, as Logitech's do, but
        # changing it sends nothing: only Help sends its power (a Dutch 650's fan)
        out.append((f"{label}_Power_2", {
            "initial": 0, "limit": 1, "padding": 0, "transitions": [] if device.get(
                "always_on") else [
                transition(1, 0, off_operand, OBJECT_ATOM),
                transition(0, 1, on_operand, OBJECT_ATOM)]}))
    inputs = device.get("inputs")
    if inputs and len(inputs["values"]) > 0:
        count = len(inputs["values"])
        transitions = []
        if "direct" in inputs:
            for value, chosen in enumerate(inputs["direct"]):
                if chosen is None:
                    transitions.append(transition(TRANSITION_FROM_ANY, value, 0, 0))
                elif isinstance(chosen, list):
                    # a sequence: its sends, its waits before this device's next send, and
                    # the device's other states it sets
                    atoms = atoms_of(chosen)
                    transitions.append(transition(TRANSITION_FROM_ANY, value,
                                                   place_object((atoms)),
                                                   OBJECT_ATOM)
                                       if len(atoms) != 1 or atoms[0][1] == OBJECT_ATOM
                                       or not atoms[0][1] & 0x80 else
                                       # one state set alone is that write, as Logitech's is
                                       transition(TRANSITION_FROM_ANY, value, *atoms[0]))
                else:
                    transitions.append(transition(TRANSITION_FROM_ANY, value,
                                                   objects[chosen], OBJECT_ATOM))
        elif count > 1:
            # Stepping: "next" as many times as it takes - or "previous", where it is the
            # shorter way round - between the device's "start" and "finish", as Logitech's
            # menu inputs go (`InputType` 4): a Soniq's Source, Up or Down, then OK. Each
            # code is followed by the input delay, which Logitech holds every one of them.
            delay = waits(index, inputs["delay_ms"])

            def spaced(sequence):
                out_atoms = []
                for item in sequence:
                    out_atoms += atoms_of([item])
                    if item[0] == "send":
                        out_atoms += delay
                return out_atoms
            step = [(objects[inputs["next"]], OBJECT_ATOM)] + delay
            back = ([(objects[inputs["previous"]], OBJECT_ATOM)] + delay
                    if inputs.get("previous") is not None else None)
            start = spaced(inputs.get("start") or [])
            finish = spaced(inputs.get("finish") or [])
            for source in range(count):
                for target in range(count):
                    if source == target:
                        continue
                    ahead, behind = (target - source) % count, (source - target) % count
                    body = start + (back * behind if back and behind < ahead
                                    else step * ahead) + finish
                    if len(body) > 0xFF:
                        raise ValueError(f"{device['label']!r} steps too far between inputs")
                    transitions.append(transition(source, target,
                                                   place_object((body)),
                                                   OBJECT_ATOM))
        out.append((f"{label}_Input_{count}", {
            "initial": 0, "limit": count - 1, "padding": 0, "transitions": transitions}))
    # the device's other states, after its power and input: a route to each
    # value from any other, or the steps to the next value, each pair that many
    for state in device.get("states") or []:
        count = state["count"]
        transitions = []
        if state.get("select"):
            for value, steps in sorted(state["select"].items()):
                atoms = atoms_of(steps)
                transitions.append(transition(
                    TRANSITION_FROM_ANY, value,
                    *((place_object((atoms)), OBJECT_ATOM)
                      if len(atoms) != 1 else atoms[0])))
        elif state.get("next"):
            step = atoms_of(state["next"])
            for source in range(count):
                for target in range(count):
                    if source != target:
                        body = step * ((target - source) % count)
                        transitions.append(transition(source, target,
                                                       place_object((body)),
                                                       OBJECT_ATOM))
        out.append((f"{label}_{state['id']}_{count}", {
            "initial": 0, "limit": count - 1, "padding": 0, "transitions": transitions}))
    return out



def _in_place(signals: dict) -> list[tuple[str, dict]]:
    """A device's commands in ordinal order: one named by its place - "Command 17" -
    back at that place, so it reads back with that name; the rest in name order."""
    count = len(signals)
    placed, rest = {}, []
    for name, signal in sorted(signals.items()):
        match = NUMBERED.fullmatch(name)
        at = int(match.group(1), 16) if match else None
        if at is not None and at < count and at not in placed:
            placed[at] = (name, signal)
        else:
            rest.append((name, signal))
    out, others = [], iter(rest)
    for ordinal in range(count):
        out.append(placed[ordinal] if ordinal in placed else next(others))
    return out


def protocol_library(project: dict, library=None):
    """The protocols a project's devices are lowered with: whatever is installed, and
    each catalogue device's own definitions (`portable_protocol_definitions`), as the
    other remotes' builds read them."""
    from ... import ir_protocol

    inline = {}
    for device in project.get("devices") or []:
        for protocol_id, definition in (device.get("portable_protocol_definitions")
                                        or {}).items():
            if inline.get(protocol_id, definition) != definition:
                raise ValueError(f"two devices define protocol {protocol_id!r} differently")
            inline[protocol_id] = definition
    if inline:
        installed = (dict(library) if isinstance(library, dict)
                     else ir_protocol.catalog(library))
        for protocol_id, definition in inline.items():
            if installed.get(protocol_id, definition) != definition:
                raise ValueError(f"a device's protocol {protocol_id!r} conflicts with the "
                                 "installed definition")
        library = {**installed, **inline}
    return library


def _phases(waveforms) -> dict:
    return {phase: body for phase, body in zip(("press", "hold", "release"), waveforms)
            if body}


def lowered_devices(project: dict, keypad: keys.Keypad, *, library=None) -> list[dict]:
    """Each device: its label and its commands, each with its keys, its waveforms and
    whether a page shows it - not when the project gives it no label, nor when it is the
    key's own command (VolumeUp on VolumeUp), which Logitech's pages leave to the key."""
    library = protocol_library(project, library)
    out = []
    for index, device in enumerate(project.get("devices") or []):
        label = device.get("label") or f"Device {index}"
        signals = device.get("signals") or {}
        if len(signals) > 0xFF:
            raise ValueError(f"device {label!r} has {len(signals)} commands; a 5xx keeps "
                             "at most 255 for a device")
        slots, unlabelled, labels, order = {}, set(), {}, []
        for entry in device.get("commands") or []:
            order.append(entry[0])
            if len(entry) > 4 and entry[4]:
                slots[entry[0]] = entry[4] if isinstance(entry[4], list) else [entry[4]]
            if len(entry) > 1:
                if entry[1] == "":
                    unlabelled.add(entry[0])
                else:
                    labels[entry[0]] = entry[1]
        rank = {name: at for at, name in enumerate(order)}
        commands = []
        for ordinal, (name, signal) in enumerate(_in_place(signals)):
            lowered = ir_lowering.lower(signal, library=library)
            bound = [key for key in slots.get(name, []) if keypad.by_name(key) is not None]
            commands.append({
                "name": name,
                "label": labels.get(name) or name,
                "keys": bound,
                "hidden": name in unlabelled or any(
                    keys.is_own_command(key, name) for key in bound),
                "rank": rank.get(name, len(rank) + ordinal),
                "command_id": (index << 8) | ordinal,
                # the count its sends carry: 1, or what an imported 5xx image gave it
                "sends": int(((signal.get("native") or {}).get("harmony-555") or {})
                             .get("sends", 1)),
                "carrier_period_ns": lowered.carrier_period_ns,
                "carrier_half_period_ns": lowered.carrier_half_period_ns,
                "phases": _phases((lowered.press_waveform, lowered.hold_waveform,
                                   lowered.release_waveform)),
                **({"alternate_phases": _phases(lowered.alternate)}
                   if lowered.alternate else {}),
            })
        ids = {command["name"]: command["command_id"] for command in commands}
        out.append({"index": index, "id": device.get("id"), "label": label,
                    "commands": commands,
                    **({"always_on": True} if device.get("always_on") else {}),
                    **device_states(device, ids)})
    return out


def device_states(device: dict, ids: dict[str, int]) -> dict:
    """A project device's power and inputs, with every command named by its id.

    The project's own fields, as the other remotes' builders read them: `power_on_cmd`
    and `power_off_cmd` or a toggle `power_cmd`, `power_delay` in milliseconds, `inputs`
    as `[name, command]` pairs - the command a sequence of steps for an input chosen in
    several - and `input_cycle` for inputs reached by stepping.
    """
    def command(name):
        if name is None:
            return None
        if name not in ids:
            raise ValueError(f"device {device.get('label')!r} names {name!r}, "
                             "which is not one of its commands")
        return ids[name]

    out = {}
    # the device's other states, Logitech's `Screen`, `TVInput` and the like
    # (corpus_provider, `_archive_states`): a value's name to its number, by state
    control = [state for state in device.get("control_states") or []
               if state.get("id") and state.get("values")]
    numbers = {state["id"]: {name: number for number, name in enumerate(state["values"])}
               for state in control}

    def steps_of(sequence, where):
        """Project steps as sends, waits and other states set: `("send", id)`,
        `("wait", ms)`, `("set", state, value number)`."""
        out_steps = []
        for step in sequence or []:
            if isinstance(step, str):
                out_steps.append(("send", command(step)))
            elif "delay_ms" in step:
                out_steps.append(("wait", int(step["delay_ms"])))
            elif "command" in step:
                if step.get("hold_ms"):
                    raise ValueError(f"device {device.get('label')!r} holds "
                                     f"{step['command']!r} in {where}, which these remotes "
                                     "cannot do in a sequence")
                out_steps.append(("send", command(step["command"])))
            elif "set" in step:
                values = numbers.get(step["set"])
                if values is None or step.get("to") not in values:
                    raise ValueError(f"device {device.get('label')!r} sets "
                                     f"{step['set']}={step.get('to')!r} in {where}, which "
                                     "its states do not have")
                out_steps.append(("set", step["set"], values[step["to"]]))
        return out_steps

    on, off = device.get("power_on_cmd"), device.get("power_off_cmd")
    toggle = device.get("power_cmd")
    if (on or toggle) and (off or toggle):
        out["power"] = {"on": command(on or toggle), "off": command(off or toggle),
                        "delay_ms": (POWER_DELAY_DEFAULT if device.get("power_delay") is None
                                     else device["power_delay"])}
        # off in several codes - Exit, then PowerOff, as a Vizio's is
        if len(device.get("power_off_steps") or []) > 1:
            out["power"]["off_steps"] = [command(name) for name in device["power_off_steps"]]
    if control:
        out["states"] = []
        for state in control:
            lowered = {"id": state["id"], "count": len(state["values"]),
                       "values": [str(value) for value in state["values"]]}
            select = {numbers[state["id"]][name]: steps_of(route.get("steps"),
                                                         f"{state['id']}={name}")
                      for name, route in (state.get("select") or {}).items()
                      if name in numbers[state["id"]]}
            if select:
                lowered["select"] = select
            elif state.get("next"):
                lowered["next"] = steps_of(state["next"], f"{state['id']}'s next")
            out["states"].append(lowered)

    def selection(chosen):
        """What choosing an input sends: one command's id, or - when the project gives
        a sequence (`[name, [steps]]`, as the other remotes' builders take it) - its
        sends and waits, `("send", id)` and `("wait", ms)`."""
        if chosen is None or isinstance(chosen, str):
            return command(chosen)
        steps = steps_of(chosen, "an input")
        if len(steps) == 1 and steps[0][0] == "send":
            return steps[0][1]
        return steps or None

    # How long the device needs after switching before its next command: a wait after
    # each input's sends, as the donors have after theirs.
    delay = int(device.get("input_delay") or 0)

    def settled(chosen):
        if not delay or chosen is None:
            return chosen
        steps = chosen if isinstance(chosen, list) else [("send", chosen)]
        return steps + [("wait", delay)]
    inputs = [(entry[0], settled(selection(entry[1])) if len(entry) > 1 else None)
              for entry in device.get("inputs") or []]
    cycle = device.get("input_cycle") or {}
    if inputs:
        out["inputs"] = {"values": [name for name, _id in inputs],
                         "direct": [command_id for _name, command_id in inputs]}
        # A smart TV's online inputs - its apps - answer only `app_power_delay` after it
        # comes on: those values, and the wait.
        online = set(device.get("online_inputs") or [])
        app_delay = int(device.get("app_power_delay") or 0)
        values = [index for index, (name, _id) in enumerate(inputs) if name in online]
        if values and app_delay and out.get("power"):
            out["online"] = {"values": values, "delay_ms": app_delay}
    elif cycle.get("next") and cycle.get("values"):
        def sequence(key):
            field = cycle.get(key)
            return steps_of(field if isinstance(field, list) else [field],
                            f"its input cycle's {key}") if field else []

        def first(key):
            sends = [item[1] for item in sequence(key) if item[0] == "send"]
            return sends[0] if sends else None
        out["inputs"] = {"values": list(cycle["values"]), "next": first("next"),
                         "delay_ms": cycle.get("delay_ms") or 0}
        if first("previous") is not None:
            out["inputs"]["previous"] = first("previous")
        # a menu's way in and out - a Soniq's Source, then OK - around the steps
        for key in ("start", "finish"):
            if sequence(key):
                out["inputs"][key] = sequence(key)
    return out
