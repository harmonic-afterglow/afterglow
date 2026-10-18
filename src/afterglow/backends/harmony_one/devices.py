"""A project's devices as a generated Harmony One holds them: commands lowered to records,
power and inputs as state variables, and the keys a device page binds.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ... import project_devices
from . import keys
from .structures import OBJECT_ATOM, object_body


# What a device that does not say waits after switching on, and between the digits of a
# channel - what the device editor shows for one (gui/device_wizard.py), so a build never
# does other than what the editor showed.
POWER_DELAY_DEFAULT, PRESS_INTERKEY_DEFAULT = 1500, 500

# "From any value", as upstairs' and Kāt's direct inputs all have it: it runs on every
# write, the same value included, which is how picking the running activity again
# re-sends its inputs. (Downstairs has one television with `0xFFFD` instead.)
TRANSITION_FROM_ANY = 0xFFFE
WAIT = 0x7C                    # (device << 8 | tenths): wait before that device's next send
LOAD_BYTE = (0xFB00, 0x1F)     # the byte register, 0: what a test compares with
EQUALS = 0x71                  # (0 << 8 | variable): the next instruction runs if it is equal


def waits(device_index: int, milliseconds: int) -> list[tuple[int, int]]:
    """A wait in tenths of a second, a hundred at a time, as the donors write long ones."""
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


def device_state_records(device: dict, place_object, online: int | None = None,
                         states: dict[str, int] | None = None) -> list[tuple[str, dict]]:
    """A device's `<Label>_Power_2` and `<Label>_Input_<n>` variables, with transitions.

    As downstairs and upstairs build them: power going 1 to 0 sends the off command, 0 to
    1 sends the on command and then waits the power-on delay; an input chosen directly
    is a transition from any value to it sending that input's command, and inputs reached
    by stepping get one transition per ordered pair, sending "next" as many times as it
    takes with the input delay after each. ``place_object`` numbers an object body.

    A device with online inputs (`device["online"]`) also has `<Label>_Online_2`,
    variable ``online``, which says its apps are up: power-on clears it, and choosing an
    online input while it is clear first waits out the rest of the apps' delay, then
    sets it - so only the first app after power-on waits. Logitech's One configurations
    gate an input on the same delay (Kāt's: a 45-second timer from the TV's power-on).
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
    gate = device.get("online") if online is not None else None
    if power:
        on = [(objects[power["on"]], OBJECT_ATOM)] + waits(index, power["delay_ms"])
        if gate:
            on.append((0, 0x80 | online))
        on_operand = (place_object(object_body(on)) if len(on) > 1
                      else objects[power["on"]])
        off_operand = (place_object(object_body(atoms_of(
            [("send", command) for command in power["off_steps"]])))
            if power.get("off_steps") else objects[power["off"]])
        out.append((f"{label}_Power_2", {
            "initial": 0, "limit": 1, "padding": 0, "transitions": [
                transition(1, 0, off_operand, OBJECT_ATOM),
                transition(0, 1, on_operand, OBJECT_ATOM)]}))
    inputs = device.get("inputs")
    if inputs and len(inputs["values"]) > 0:
        count = len(inputs["values"])
        transitions = []
        if "direct" in inputs:
            for value, chosen in enumerate(inputs["direct"]):
                if gate and value in gate["values"] and chosen is not None:
                    # the apps' delay counts from power-on, whose own wait is part of it
                    rest = waits(index, max(0, gate["delay_ms"] - power["delay_ms"]))
                    first = [LOAD_BYTE, (online, EQUALS)]
                    first += ([(place_object(object_body(rest)), OBJECT_ATOM)
                               if len(rest) > 1 else rest[0]] if rest else [])
                    first.append((1, 0x80 | online))
                    chosen = [("atoms", first)] + (
                        chosen if isinstance(chosen, list) else [("send", chosen)])
                if chosen is None:
                    transitions.append(transition(TRANSITION_FROM_ANY, value, 0, 0))
                elif isinstance(chosen, list):
                    # a sequence: its sends, its waits before this device's next send, and
                    # the device's other states it sets
                    atoms = atoms_of(chosen)
                    transitions.append(transition(TRANSITION_FROM_ANY, value,
                                                   place_object(object_body(atoms)),
                                                   OBJECT_ATOM)
                                       if len(atoms) != 1 or atoms[0][1] == OBJECT_ATOM
                                       or not atoms[0][1] & 0x80 else
                                       # one state set alone is that write, as Logitech's is
                                       transition(TRANSITION_FROM_ANY, value, *atoms[0]))
                else:
                    transitions.append(transition(TRANSITION_FROM_ANY, value,
                                                   objects[chosen], OBJECT_ATOM))
        elif count > 1:
            step = [(objects[inputs["next"]], OBJECT_ATOM)] + waits(index,
                                                                     inputs["delay_ms"])
            for source in range(count):
                for target in range(count):
                    if source == target:
                        continue
                    steps = (target - source) % count
                    body = step * steps
                    if len(body) > 0xFF:
                        raise ValueError(f"{device['label']!r} steps too far between inputs")
                    transitions.append(transition(source, target,
                                                   place_object(object_body(body)),
                                                   OBJECT_ATOM))
        out.append((f"{label}_Input_{count}", {
            "initial": 0, "limit": count - 1, "padding": 0, "transitions": transitions}))
    if gate:
        out.append((f"{label}_Online_2", {
            "initial": 0, "limit": 1, "padding": 0, "transitions": []}))
    # the device's other states, after its power, input and apps' gate: a route to each
    # value from any other, or the steps to the next value, each pair that many
    for state in device.get("states") or []:
        count = state["count"]
        transitions = []
        if state.get("select"):
            for value, steps in sorted(state["select"].items()):
                atoms = atoms_of(steps)
                transitions.append(transition(
                    TRANSITION_FROM_ANY, value,
                    *((place_object(object_body(atoms)), OBJECT_ATOM)
                      if len(atoms) != 1 else atoms[0])))
        elif state.get("next"):
            step = atoms_of(state["next"])
            for source in range(count):
                for target in range(count):
                    if source != target:
                        body = step * ((target - source) % count)
                        transitions.append(transition(source, target,
                                                       place_object(object_body(body)),
                                                       OBJECT_ATOM))
        out.append((f"{label}_{state['id']}_{count}", {
            "initial": 0, "limit": count - 1, "padding": 0, "transitions": transitions}))
    return out


def device_key_rows(commands: list[dict]) -> list[tuple[int, int, int]]:
    """A device page's physical keys: each key one of its commands is bound to sends
    that command, without the click a touch makes, and every other command key does
    nothing - so device mode never falls through to the running activity's keys. The
    Activities, Off and Help keys are left to the flow above it."""
    bound = {}
    for command in commands:
        for name in command.get("keys") or ():
            code = keys.by_name(name)
            if code is not None:
                bound.setdefault(code, command["object_index"])
    return [(keys.by_name(name), bound.get(keys.by_name(name), 0),
             OBJECT_ATOM if keys.by_name(name) in bound else 0)
            for name in keys.COMMAND_KEYS]


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


def held_commands(project: dict, devices: list[dict], planned: dict, *, library=None):
    """Give each held send in a plan a record of its own - the code held that long -
    and point the step at it. The records join their device's commands but no screen,
    and a step that names the same command held as long shares one."""
    from . import ir_lowering

    library = protocol_library(project, library)
    made = {}

    def resolve(steps):
        out = []
        for step in steps:
            if step[0] != "send" or len(step) < 4:
                out.append(step)
                continue
            _send, index, command_id, held_ms = step
            if (index, command_id, held_ms) not in made:
                device = devices[index]
                source = next(command for command in device["commands"]
                              if command["command_id"] == command_id)
                ordinal = len(device["commands"])
                if ordinal > 0xFF:
                    raise ValueError(f"device {device['label']!r} has no room for "
                                     f"{source['name']!r} held {held_ms} ms")
                signal = project["devices"][index]["signals"][source["name"]]
                lowered = ir_lowering.lower(signal, library=library, held_ms=held_ms)
                device["commands"].append({
                    "name": f"{source['name']} ({held_ms} ms)", "keys": [], "hidden": True,
                    "command_id": (index << 8) | ordinal,
                    "carrier_period_ns": lowered.carrier_period_ns,
                    "carrier_half_period_ns": lowered.carrier_half_period_ns,
                    "phases": {"press": lowered.press_waveform},
                    **({"alternate_phases": _phases(lowered.alternate)}
                       if lowered.alternate else {})})
                made[(index, command_id, held_ms)] = (index << 8) | ordinal
            out.append(("send", index, made[(index, command_id, held_ms)]))
        return out

    for activity in planned["activities"]:
        for key in ("enter", "leave"):
            activity[key] = resolve(activity[key])
        activity["keys"] = {code: resolve(steps) for code, steps in activity["keys"].items()}
        activity["buttons"] = [None if button is None else (button[0], resolve(button[1]))
                               for button in activity["buttons"]]
        activity["favourites"] = [dict(item, steps=resolve(item["steps"]))
                                  for item in activity.get("favourites") or []]


def _phases(waveforms) -> dict:
    """(press, hold, release) waveform bodies as a record's phases, the empty ones left out."""
    return {phase: body for phase, body in zip(("press", "hold", "release"), waveforms)
            if body}


def lowered_devices(project: dict, *, library=None) -> list[dict]:
    """Lower a project's devices into the pieces a command record is written from.

    A command's identifier carries its device in the high byte and its ordinal in the
    low one, which is how the whole format refers to commands, so a device may hold 255
    of them and no more.
    """
    from . import ir_lowering

    library = protocol_library(project, library)
    out = []
    for index, device in enumerate(project.get("devices") or []):
        label = device.get("label") or f"Device {index}"
        signals = device.get("signals") or {}
        if len(signals) > 0xFF:
            raise ValueError(
                f"device {label!r} has {len(signals)} commands; an ordinal is one byte")
        # The keys each command is bound to, from the project's own hard slots, and the
        # commands with no label - ones a device's pages never show.
        slots, unlabelled = {}, set()
        for entry in device.get("commands") or []:
            if len(entry) > 4 and entry[4]:
                slots[entry[0]] = entry[4] if isinstance(entry[4], list) else [entry[4]]
            if len(entry) > 1 and entry[1] == "":
                unlabelled.add(entry[0])
        commands = []
        for ordinal, (name, signal) in enumerate(sorted(signals.items())):
            lowered = ir_lowering.lower(signal, library=library)
            commands.append({
                "name": name,
                "keys": slots.get(name, []),
                # As Logitech's pages: a key's own command is pressed there, not on a page.
                **({"hidden": True} if name in unlabelled or any(
                    keys.is_own_command(key, name) for key in slots.get(name, ())) else {}),
                "command_id": (index << 8) | ordinal,
                "carrier_period_ns": lowered.carrier_period_ns,
                "carrier_half_period_ns": lowered.carrier_half_period_ns,
                "phases": {
                    phase: body for phase, body in (
                        ("press", lowered.press_waveform),
                        ("hold", lowered.hold_waveform),
                        ("release", lowered.release_waveform),
                    ) if body
                },
                **({"alternate_phases": _phases(lowered.alternate)}
                   if lowered.alternate else {}),
            })
        ids = {command["name"]: command["command_id"] for command in commands}
        # A page arranged for this device - read from a configuration or in the editor -
        # replaces the one made from its labels, its gaps (None) left empty on the remote.
        screen = ([entry[:2] if entry else None
                   for entry in project_devices.screen_buttons(device)]
                  if device.get("screen_buttons") is not None else None)
        while screen and screen[-1] is None:        # nothing after the last button
            screen.pop()
        out.append({"index": index, "label": label, "commands": commands,
                    **({"screen": screen} if screen is not None else {}),
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
            lowered = {"id": state["id"], "count": len(state["values"])}
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
        step = cycle["next"]
        step = step[0] if isinstance(step, list) else step
        out["inputs"] = {"values": list(cycle["values"]), "next": command(step),
                         "delay_ms": cycle.get("delay_ms") or 0}
    return out


@dataclass
class Variables:
    """The section-14 variables a build adds after the platform's and the carried
    screens': each device's power and input, then the activity counter and the Remote
    Assistant's switch. ``slots`` is, per device, the index of its power and input."""
    first: int | None
    records: list[tuple[str, dict]] = field(default_factory=list)
    slots: list[dict] = field(default_factory=list)
    state: int | None = None
    assistant: int | None = None

    def add(self, name: str, record: dict) -> int:
        self.records.append((name, record))
        return self.first + len(self.records) - 1


def state_variables(devices: list[dict], place_object, first: int | None) -> Variables:
    """Each device's power and input as state variables, as every donor has them, from
    variable ``first`` on: a transition sends what changing the state takes. None for
    ``first`` is an image without section 14's records, which holds none. A device
    with online inputs has a third, its apps' gate (`device_state_records`)."""
    out = Variables(first)
    if first is None:
        return out
    for device in devices:
        kinds = ["power"] * bool(device.get("power"))
        kinds += ["input"] * bool((device.get("inputs") or {}).get("values"))
        online = None
        if device.get("online") and device.get("power") and "direct" in device["inputs"]:
            online = out.first + len(out.records) + len(kinds)
            kinds.append("online")
        # its other states - `Screen`, `TVInput` - after those, which its inputs set
        states = {}
        for state in device.get("states") or []:
            states[state["id"]] = out.first + len(out.records) + len(kinds)
            kinds.append(f"state:{state['id']}")
        records = device_state_records(device, place_object, online, states)
        out.slots.append({kind: out.add(name, record)
                          for kind, (name, record) in zip(kinds, records)})
    return out
