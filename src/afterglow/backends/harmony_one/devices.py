"""A project's devices as a generated Harmony One holds them: commands lowered to records,
power and inputs as state variables, and the keys a device page binds.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import keys
from .structures import OBJECT_ATOM, object_body


# "From any value", as upstairs' and Kāt's direct inputs all have it: it runs on every
# write, the same value included, which is how picking the running activity again
# re-sends its inputs. (Downstairs has one television with `0xFFFD` instead.)
TRANSITION_FROM_ANY = 0xFFFE
WAIT = 0x7C                    # (device << 8 | tenths): wait before that device's next send


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


def device_state_records(device: dict, place_object) -> list[tuple[str, dict]]:
    """A device's `<Label>_Power_2` and `<Label>_Input_<n>` variables, with transitions.

    As downstairs and upstairs build them: power going 1 to 0 sends the off command, 0 to
    1 sends the on command and then waits the power-on delay; an input chosen directly
    is a transition from any value to it sending that input's command, and inputs reached
    by stepping get one transition per ordered pair, sending "next" as many times as it
    takes with the input delay after each. ``place_object`` numbers an object body.
    """
    label = device["label"].replace(" ", "_")
    index = device["index"]
    objects = {command["command_id"]: command["object_index"]
               for command in device["commands"]}
    out = []
    power = device.get("power")
    if power:
        on = [(objects[power["on"]], OBJECT_ATOM)] + waits(index, power["delay_ms"])
        on_operand = (place_object(object_body(on)) if len(on) > 1
                      else objects[power["on"]])
        out.append((f"{label}_Power_2", {
            "initial": 0, "limit": 1, "padding": 0, "transitions": [
                transition(1, 0, objects[power["off"]], OBJECT_ATOM),
                transition(0, 1, on_operand, OBJECT_ATOM)]}))
    inputs = device.get("inputs")
    if inputs and len(inputs["values"]) > 0:
        count = len(inputs["values"])
        transitions = []
        if "direct" in inputs:
            for value, command_id in enumerate(inputs["direct"]):
                if command_id is None:
                    transitions.append(transition(TRANSITION_FROM_ANY, value, 0, 0))
                else:
                    transitions.append(transition(TRANSITION_FROM_ANY, value,
                                                   objects[command_id], OBJECT_ATOM))
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
                    "phases": {"press": lowered.press_waveform}})
                made[(index, command_id, held_ms)] = (index << 8) | ordinal
            out.append(("send", index, made[(index, command_id, held_ms)]))
        return out

    for activity in planned["activities"]:
        for key in ("enter", "leave"):
            activity[key] = resolve(activity[key])
        activity["keys"] = {code: resolve(steps) for code, steps in activity["keys"].items()}
        activity["buttons"] = [(label, resolve(steps)) for label, steps in activity["buttons"]]
        activity["favourites"] = [dict(item, steps=resolve(item["steps"]))
                                  for item in activity.get("favourites") or []]


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
        # The keys each command is bound to, from the project's own hard slots.
        slots = {}
        for entry in device.get("commands") or []:
            if len(entry) > 4 and entry[4]:
                slots[entry[0]] = entry[4] if isinstance(entry[4], list) else [entry[4]]
        commands = []
        for ordinal, (name, signal) in enumerate(sorted(signals.items())):
            lowered = ir_lowering.lower(signal, library=library)
            commands.append({
                "name": name,
                "keys": slots.get(name, []),
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
            })
        ids = {command["name"]: command["command_id"] for command in commands}
        out.append({"index": index, "label": label, "commands": commands,
                    **device_states(device, ids)})
    return out


def device_states(device: dict, ids: dict[str, int]) -> dict:
    """A project device's power and inputs, with every command named by its id.

    The project's own fields, as the other remotes' builders read them: `power_on_cmd`
    and `power_off_cmd` or a toggle `power_cmd`, `power_delay` in milliseconds, `inputs`
    as `[name, command]` pairs, and `input_cycle` for inputs reached by stepping.
    """
    def command(name):
        if name is None:
            return None
        if name not in ids:
            raise ValueError(f"device {device.get('label')!r} names {name!r}, "
                             "which is not one of its commands")
        return ids[name]

    out = {}
    on, off = device.get("power_on_cmd"), device.get("power_off_cmd")
    toggle = device.get("power_cmd")
    if (on or toggle) and (off or toggle):
        out["power"] = {"on": command(on or toggle), "off": command(off or toggle),
                        "delay_ms": device.get("power_delay") or 0}
    inputs = [(entry[0], command(entry[1]) if len(entry) > 1 else None)
              for entry in device.get("inputs") or []]
    cycle = device.get("input_cycle") or {}
    if inputs:
        out["inputs"] = {"values": [name for name, _id in inputs],
                         "direct": [command_id for _name, command_id in inputs]}
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
    ``first`` is an image without section 14's records, which holds none."""
    out = Variables(first)
    if first is None:
        return out
    for device in devices:
        records = device_state_records(device, place_object)
        kinds = ["power"] * bool(device.get("power"))
        kinds += ["input"] * (len(records) - len(kinds))
        out.slots.append({kind: out.add(name, record)
                          for kind, (name, record) in zip(kinds, records)})
    return out
