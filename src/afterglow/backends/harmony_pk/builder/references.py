"""What a build names must be there: every device an activity points at, every command a
step, key, button, favourite or power state sends.

The remote takes what it is given. A role naming a device the file does not have, or a
SendCommand naming a command the device lacks, builds, verifies and flashes, and the key
then does nothing. The other remotes' builders refuse those with a sentence; this one
does the same, before anything is written.
"""
from __future__ import annotations

POWER_FIELDS = ("power_cmd", "power_on_cmd", "power_off_cmd")


def check(specs, activities) -> None:
    """Raise ValueError naming the first thing that points at nothing."""
    by_id = {str(spec.get("id")): spec for spec in specs or []}

    def commands(did) -> set:
        return {command[0] for command in by_id[str(did)].get("commands") or []}

    def label(did) -> str:
        return repr(by_id[str(did)].get("label") or did)

    def device(did, where):
        if str(did) not in by_id:
            raise ValueError(f"{where} names device {did!r}, which the project does not have")

    def send(did, command, where):
        device(did, where)
        if not isinstance(command, str) or not command:
            raise ValueError(f"{where} sends no command to {label(did)}: choose one")
        if command not in commands(did):
            raise ValueError(f"{where} sends {command!r} to {label(did)}, "
                             "which has no such command")

    def step(entry, where):
        if isinstance(entry, dict):                 # a button: {device, command} or macro
            if entry.get("blank"):
                return
            if entry.get("macro"):
                for inner in entry["macro"]:
                    step(inner, where)
            else:
                send(entry.get("device"), entry.get("command"), where)
            return
        if not isinstance(entry, (list, tuple)) or not entry:
            raise ValueError(f"{where} has a step that is not one: {entry!r}")
        if len(entry) == 2:                          # (device, command) shorthand
            send(entry[0], entry[1], where)
        elif entry[0] == "command":
            send(entry[1], entry[2], where)
        elif entry[0] in ("state", "input", "delay", "number"):
            device(entry[1], where)

    for spec in specs or []:
        where = f"device {spec.get('label') or spec.get('id')!r}"
        for field in POWER_FIELDS:
            if spec.get(field):
                send(spec.get("id"), spec[field], f"{where}'s power")
        for pair in spec.get("inputs") or []:
            if len(pair) == 2 and pair[1]:
                # a command, or a sequence of commands and {"delay_ms"} waits
                for entry in [pair[1]] if isinstance(pair[1], str) else pair[1]:
                    if isinstance(entry, dict):
                        entry = entry.get("command")
                    if entry is not None:
                        send(spec.get("id"), entry, f"{where}'s input {pair[0]!r}")

    for act in activities or []:
        where = f"activity {act.get('label') or act.get('id')!r}"
        for role in ("display", "control", "volume"):
            if act.get(role):
                device(act[role], where)
        for did in (act.get("roles") or {}).values():
            if did:
                device(did, where)
        if act.get("input"):
            device(act["input"][0], where)
        for field in ("enter", "leave"):
            for entry in act.get(field) or []:
                step(entry, where)
        for slot, macro in (act.get("hard_macros") or {}).items():
            for entry in macro or []:
                step(entry, f"{where}'s {slot} key")
        for button in act.get("soft_buttons") or []:
            if button is None:
                continue
            if isinstance(button, dict):
                step(button, f"{where}'s button {button.get('label')!r}")
            else:                                    # (label, device, command[, icon])
                send(button[1], button[2], f"{where}'s button {button[0]!r}")
        for _group, buttons in act.get("screen_groups") or []:
            for button in buttons:
                step(button, f"{where}'s button {button.get('label')!r}")
        for favourite in act.get("image_buttons") or []:
            name, kind, payload = favourite[0], favourite[1], favourite[2]
            there = f"{where}'s favourite {name!r}"
            if kind == "channel" and not str(payload or "").strip():
                raise ValueError(f"{there} has no channel number")
            elif kind == "command":
                send(payload[0], payload[1], there)
            elif kind == "macro":
                for entry in payload or []:
                    step(entry, there)
        confirm = act.get("channel_confirm")
        if confirm and (act.get("image_buttons") or act.get("channels")):
            control = act.get("control")
            if isinstance(confirm, (list, tuple)) and len(confirm) >= 2:
                send(confirm[0], confirm[1], f"{where}'s favourites")
            elif isinstance(confirm, str) and control:
                send(control, confirm, f"{where}'s favourites")
