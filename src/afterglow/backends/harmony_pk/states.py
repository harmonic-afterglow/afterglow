#!/usr/bin/env python3
"""Harmony PK device state machines and number entry: `<States>` and `<Numeric>`.

Format reference: docs/harmony_pk/configuration.md
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

# The action kinds, and which group each belongs to.
DISCRETE = ("SetAction", "ChangeAction")
RELATIVE = ("NextAction", "PrevAction")
DIGIT_SETS = ("FirstDigit", "MiddleDigit", "LastDigit")

_MISSING = object()      # "no container seen yet", distinct from a bare (None) group


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# reading
def _parse_action(element) -> dict:
    """One <Action> -> {"target":..., "operation":..., "params":[(name, value), ...]}.

    Parameters are kept as an ordered list rather than a dict: the remote reads them
    positionally in places, and rewriting them in a different order produces a config
    that differs from every real one for no reason.
    """
    operation = element.find("Operation")
    return {
        "target": element.findtext("Target") or "Device",
        "operation": operation.findtext("Name") if operation is not None else None,
        "params": [(p.attrib.get("name"), p.text or "")
                   for p in (operation.findall("Parameter") if operation is not None else [])],
    }


def _parse_action_element(element, group) -> dict:
    """One SetAction / ChangeAction / NextAction / PrevAction / StartAction.

    `group` is the container it came from, or None when it hangs directly off the
    state. One such element may hold SEVERAL <Action>s - switching a television to
    "Component" can mean sending a code *and* setting a second state - so they are
    kept as a list. Reading only the first silently halved those.
    """
    children = [c.tag for c in element]
    entry = {
        "group": group,
        "kind": element.tag,
        "name": element.findtext("Name"),
        "actions": [_parse_action(a) for a in element.findall("Action")],
    }
    # Logitech writes <Action> then <Name>; Afterglow itself once wrote <Name> first.
    # Both configs exist and both run, so the order seen is the order written back -
    # a carrier that "corrects" what it reads is not a carrier.
    if "Name" in children and "Action" in children:
        entry["name_first"] = children.index("Name") < children.index("Action")
    return entry


def parse_states(device) -> list[dict]:
    """Every <State> of a <Device>, in document order."""
    states = []
    for state in device.findall("States/State"):
        entry = {
            "id": state.findtext("Id"),
            "values": [v.text or "" for v in state.findall("Value")],
            "actions": [],
        }
        delay = state.findtext("Delay")
        if delay is not None and delay.strip().lstrip("-").isdigit():
            entry["delay"] = int(delay)
        # Anything that is not Id/Value/Delay carries behaviour. Most of it sits in a
        # DiscreteActions or RelativeActions container, but not all: `StartAction`
        # hangs directly off <State>. Rather than assume the set of containers, keep
        # whatever is there, in the order it is there.
        for child in state:
            if child.tag in ("Id", "Value", "Delay"):
                continue
            if child.find(".//Action") is None:
                # Carries no behaviour we model - a numeric range (`MinValue`,
                # `MaxValue`) or a starting value (`InitialValue`), both of which the
                # firmware reads (State.lua). Kept verbatim rather than dropped.
                entry.setdefault("extra", []).append(
                    ET.tostring(child, encoding="unicode"))
            elif child.find("Action") is not None:        # a bare action element
                entry["actions"].append(_parse_action_element(child, group=None))
            else:                                        # a container of them
                for action in child:
                    entry["actions"].append(_parse_action_element(action, group=child.tag))
        states.append(entry)
    return states


def parse_numeric(device) -> dict | None:
    """The <Numeric> block: fixed-digit padding, the three digit sets, and Finish."""
    numeric = device.find("Numeric")
    if numeric is None:
        return None
    out: dict = {"digits": {}}
    fixed = numeric.findtext("FixedDigits")
    if fixed and fixed.strip().isdigit():
        out["fixed"] = int(fixed)
    for name in DIGIT_SETS:
        container = numeric.find(name)
        if container is None:
            continue
        out["digits"][name] = [
            # Real configs write <Digit value="N">; Afterglow briefly wrote
            # <Digit><value>N</value>. The firmware reads both - ParseTable.lua maps an
            # attribute and a child element to the same shape - so the odd form was not
            # itself the bug. Both are accepted, and the form real configs use is the
            # one written back.
            {"value": digit.attrib.get("value", digit.findtext("value")),
             "action": _parse_action(digit.find("Action"))}
            for digit in container.findall("Digit") if digit.find("Action") is not None
        ]
    finish = numeric.find("Finish/Action")
    if finish is not None:
        out["finish"] = _parse_action(finish)
    # `Start`, `GreaterTen` and `GreaterHundred` are real parts of the format
    # (Numeric.lua): actions run before dialling, and the prefix a receiver needs for a
    # two- or three-digit channel. Nothing here models them, so they are carried whole
    # instead of being quietly discarded.
    for child in numeric:
        if child.tag not in DIGIT_SETS and child.tag not in ("FixedDigits", "Finish"):
            out.setdefault("extra", {})[child.tag] = ET.tostring(child, encoding="unicode")
    # Real configs disagree on where <Finish> sits: some put it after the digit sets,
    # some before them. Keep the order seen rather than imposing one.
    out["order"] = [child.tag for child in numeric if child.tag != "FixedDigits"]
    return out


# writing
def _build_action(spec: dict) -> str:
    params = "".join(f'<Parameter name="{_esc(n)}">{_esc(v)}</Parameter>'
                     for n, v in spec.get("params", []))
    return (f"<Action><Target>{_esc(spec.get('target', 'Device'))}</Target>"
            f"<Operation><Name>{_esc(spec.get('operation'))}</Name>{params}</Operation>"
            f"</Action>")


def build_control_states(control: list[dict], device_id: str) -> list[dict]:
    """Neutral declared states -> the parsed shape `build_states` already writes.

    Validated against a pair Logitech itself produced: `Panasonic TX-P42VT20E` publishes
    `AV2Input` in the archive and appears in a donor configuration, and the flashed block
    is exactly this - `values[].name` as the state's values, `start` as a bare
    `StartAction`, `next`/`previous` inside `RelativeActions`, and a `SetAction` per value
    that names a route.

    Going through the parsed shape rather than emitting XML here means the one writer
    stays `build_states`, which round-trips a real configuration byte for byte.
    """
    def steps(sequence) -> list[dict]:
        out = []
        for step in sequence or []:
            if isinstance(step, str):
                out.append({"target": "Device", "operation": "SendCommand",
                            "params": [["DeviceId", device_id], ["Command", step],
                                       ["Modifier", "Press"]]})
            elif "delay_ms" in step:
                out.append({"target": "Device", "operation": "SendDelay",
                            "params": [["Delay", str(int(step["delay_ms"]))],
                                       ["DeviceId", device_id]]})
            elif "command" in step:
                params = [["DeviceId", device_id], ["Command", step["command"]],
                          ["Modifier", "Press"]]
                if step.get("hold_ms"):
                    params.append(["Duration", str(int(step["hold_ms"]))])
                out.append({"target": "Device", "operation": "SendCommand",
                            "params": params})
            elif "set" in step:
                out.append({"target": "Device", "operation": "SetValue",
                            "params": [["DeviceId", device_id],
                                       ["State", step["set"]], ["Value", step["to"]]]})
        return out

    built = []
    for state in control or []:
        actions = []
        for key, kind in (("start", "StartAction"), ("finish", "FinishAction")):
            body = steps(state.get(key))
            if body:
                actions.append({"group": None, "kind": kind, "name": None,
                                "actions": body})
        # `RelativeActions` and `DiscreteActions` are mutually exclusive - `State.lua`
        # reads the first and only falls to the second in an `elseif` - so a state
        # carrying both would have its discrete routes ignored entirely.
        select = state.get("select") or {}
        if select:
            for value in state.get("values") or []:
                route = select.get(value) or {}
                body = steps(route.get("steps"))
                if not body:
                    continue
                # Logitech's `setType`: 1 is a plain set, 2 is a change. Decoded from the
                # `Panasonic TX-P42VT20E` pair, where all 11 routed values agree, and the
                # firmware reads the two from different containers.
                kind = "ChangeAction" if route.get("set_type") == 2 else "SetAction"
                actions.append({"group": "DiscreteActions", "kind": kind,
                                "name": value, "name_first": False,
                                "actions": body})
        else:
            for key, kind in (("next", "NextAction"), ("previous", "PrevAction")):
                body = steps(state.get(key))
                if body:
                    actions.append({"group": "RelativeActions", "kind": kind,
                                    "name": None, "actions": body})
        if not actions:
            continue
        entry = {"id": state["id"], "values": list(state.get("values") or []),
                 "actions": actions}
        if state.get("delay_ms"):
            entry["delay"] = int(state["delay_ms"])
        built.append(entry)
    return built


def build_states(states: list[dict]) -> str:
    """Regenerate the <States> block. `parse_states` -> `build_states` is byte-exact."""
    if not states:
        return ""
    out = []
    for state in states:
        body = [f"<Id>{_esc(state.get('id'))}</Id>"]
        body += [f"<Value>{_esc(v)}</Value>" for v in state.get("values", [])]
        if "delay" in state:
            body.append(f"<Delay>{int(state['delay'])}</Delay>")
        body += list(state.get("extra", []))
        # Actions go back into the container they came from, consecutive ones sharing
        # a container as they did originally; a group of None is written bare.
        def _one(action):
            name = (f"<Name>{_esc(action['name'])}</Name>"
                    if action.get("name") is not None else "")
            steps = "".join(_build_action(a) for a in action["actions"])
            body = name + steps if action.get("name_first") else steps + name
            return f"<{action['kind']}>{body}</{action['kind']}>"

        current, inner = _MISSING, ""
        for action in state.get("actions", []):
            group = action.get("group")
            if group != current:
                if current is not _MISSING and inner:
                    body.append(f"<{current}>{inner}</{current}>" if current else inner)
                current, inner = group, ""
            inner += _one(action)
        if current is not _MISSING and inner:
            body.append(f"<{current}>{inner}</{current}>" if current else inner)
        out.append(f"<State>{''.join(body)}</State>")
    return f"<States>{''.join(out)}</States>"


def build_numeric(numeric: dict) -> str:
    """Regenerate the <Numeric> block from a parsed one."""
    if not numeric:
        return ""
    body = f"<FixedDigits>{int(numeric.get('fixed', 0))}</FixedDigits>"
    order = numeric.get("order") or (
        [n for n in DIGIT_SETS if numeric.get("digits", {}).get(n)]
        + (["Finish"] if numeric.get("finish") else [])
        + list(numeric.get("extra", {})))
    for tag in order:
        if tag == "Finish" and numeric.get("finish"):
            body += f"<Finish>{_build_action(numeric['finish'])}</Finish>"
            continue
        carried = numeric.get("extra", {}).get(tag)
        if carried:
            body += carried
            continue
        digits = numeric.get("digits", {}).get(tag)
        if not digits:
            continue
        inner = "".join(f'<Digit value="{_esc(d["value"])}">'
                        f'{_build_action(d["action"])}</Digit>' for d in digits)
        body += f"<{tag}>{inner}</{tag}>"
    return f"<Numeric>{body}</Numeric>"


# the convenience view the interface uses
def _command_of(action: dict) -> str | None:
    if action.get("operation") != "SendCommand":
        return None
    return dict(action.get("params", [])).get("Command")


def power_commands(states: list[dict]) -> dict:
    """`{"on": cmd, "off": cmd, "toggle": cmd, "delay": ms}` as far as they exist.

    Reads every action kind, not just `SetAction`: a television whose power-on is a
    `ChangeAction` is completely ordinary and used to import as having no power at all.
    """
    out: dict = {}
    for state in states:
        if state.get("id") != "Power":
            continue
        if "delay" in state:
            out["delay"] = state["delay"]
        for action in state.get("actions", []):
            command = next((c for c in map(_command_of, action["actions"]) if c), None)
            if command is None:
                continue
            if action["kind"] in RELATIVE:
                out.setdefault("toggle", command)
            elif (action.get("name") or "").lower() == "on":
                out.setdefault("on", command)
            elif (action.get("name") or "").lower() == "off":
                out.setdefault("off", command)
    return out


def input_list(states: list[dict]) -> list[list]:
    """`[[name, command], ...]` for the interface - command is None when indirect.

    The action behind an input may send a code, or it may `SetValue` on a second state
    that holds the code. Flattening the indirect ones to a command is what dropped
    every input on a real television; they are reported with a command of None so the
    interface can show them and the builder knows not to synthesise from them.
    """
    for state in states:
        if state.get("id") != "Input":
            continue
        found = [[a["name"], next((c for c in map(_command_of, a["actions"]) if c), None)]
                 for a in state.get("actions", []) if a.get("name")]
        return found or [[v, None] for v in state.get("values", [])]
    return []


def set_power(states: list[dict], device_id: str, on: str | None,
              off: str | None, toggle: str | None, delay: int | None) -> list[dict]:
    """Rewrite the Power state to match what the interface was given.

    Every other state is left exactly as it was, so editing a television's power
    command cannot quietly discard its input tree.
    """
    def send(command):
        return {"target": "Device", "operation": "SendCommand",
                "params": [("DeviceId", str(device_id)), ("Command", command),
                           ("Modifier", "Press")]}

    actions = []
    if on and off:
        actions = [{"group": "DiscreteActions", "kind": "SetAction", "name": "On",
                    "actions": [send(on)]},
                   {"group": "DiscreteActions", "kind": "SetAction", "name": "Off",
                    "actions": [send(off)]}]
    elif toggle:
        actions = [{"group": "RelativeActions", "kind": "NextAction", "name": None,
                    "actions": [send(toggle)]}]
    if not actions:
        return [s for s in states if s.get("id") != "Power"]

    entry = {"id": "Power", "values": ["Off", "On"], "actions": actions}
    if delay is not None:
        entry["delay"] = int(delay)
    out = [dict(entry) if s.get("id") == "Power" else s for s in states]
    if not any(s.get("id") == "Power" for s in states):
        out.insert(0, entry)
    return out
