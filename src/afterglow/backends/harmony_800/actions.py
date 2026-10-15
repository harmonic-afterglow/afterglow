"""What an activity's planned steps (activities.py) become in a generated Harmony 800: the
instructions that send a device's command, wait before its next send, or write its power
and input variables, whose transitions send what changing them takes.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from .devices import waits
from .structures import OBJECT_ATOM


class Actions:
    """Steps as instructions, for ``devices`` (devices.lowered_devices, their command
    objects numbered) whose variables are ``slots``: per device, the variable index of
    its power and input."""

    def __init__(self, layout, devices: list[dict], slots: list[dict]):
        self.layout = layout
        self.devices = devices
        self.slots = slots
        self.commands = {(device["index"], command["command_id"]): command
                         for device in devices for command in device["commands"]}

    def command(self, device: int, command_id: int) -> int:
        """The object that sends a command."""
        return self.commands[(device, command_id)]["object_index"]

    def wrapper(self, device: int, command_id: int) -> int:
        """The object a touch key binds for a command: it clicks, then sends."""
        return self.commands[(device, command_id)]["wrapper_index"]

    def atoms(self, steps) -> list[tuple[int, int]]:
        """A send runs the command's object, a wait holds that device's next send, an
        input writes its variable."""
        out = []
        for step in steps:
            if step[0] == "send":
                out.append((self.command(step[1], step[2]), OBJECT_ATOM))
            elif step[0] == "wait":
                out += waits(step[1], step[2])
            elif step[0] == "input" and "input" in self.slots[step[1]]:
                out.append((step[2], 0x80 | self.slots[step[1]]["input"]))
        return out

    def key_target(self, steps) -> int:
        """What a key bound to ``steps`` runs: one send is the command's own object,
        as a device page binds it; anything else an object of its own."""
        if len(steps) == 1 and steps[0][0] == "send":
            return self.command(steps[0][1], steps[0][2])
        return self.layout.atoms_object(self.atoms(steps))

    def power_writes(self, indices, value: int) -> list[tuple[int, int]]:
        return [(value, 0x80 | self.slots[index]["power"]) for index in indices
                if "power" in self.slots[index]]

    def input_writes(self, inputs) -> list[tuple[int, int]]:
        return [(value, 0x80 | self.slots[index]["input"]) for index, value in inputs
                if "input" in self.slots[index]]

    def direct_power(self, indices, on: bool, toggles: bool = False) -> list[tuple[int, int]]:
        """Help's sends: each device's own power command, straight, for the devices
        that have one for each way - a toggle sent again would undo what it fixes. With
        ``toggles``, a toggle too: the Remote Assistant has been told the device is off."""
        out = []
        for index in indices:
            power = self.devices[index].get("power")
            if not power or (power["on"] == power["off"] and not toggles):
                continue
            out.append((self.command(index, power["on"] if on else power["off"]),
                        OBJECT_ATOM))
            if on:
                out += waits(index, power["delay_ms"])
        return out

    def input_fix(self, index: int, value: int) -> list[tuple[int, int]]:
        """What answering No about an input sends: its own command again, or for
        inputs reached by stepping, one step."""
        inputs = self.devices[index]["inputs"]
        if "direct" in inputs:
            chosen = inputs["direct"][value]
            if chosen is None:
                return []
            if isinstance(chosen, list):
                out = []
                for kind, item in chosen:
                    out += ([(self.command(index, item), OBJECT_ATOM)] if kind == "send"
                            else waits(index, item))
                return out
            return [(self.command(index, chosen), OBJECT_ATOM)]
        return [(self.command(index, inputs["next"]), OBJECT_ATOM)]
