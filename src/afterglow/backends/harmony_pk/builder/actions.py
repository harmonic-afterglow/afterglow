"""Harmony PK action XML: the steps a device state or an activity runs.

An action is one instruction to the remote - send a command, set a state, wait, dial a
channel. Devices and activities both emit them, so they live here rather than in either.
"""
from .codes import esc


def _a_send(dev, cmd, mod="Press", duration=None):
    """One SendCommand. `duration` is milliseconds to keep sending it for.

    Duration is independent of the modifier: real configurations write `Press` with a
    `Duration` of 2000 for a device that needs a long press, rather than switching to
    `Hold`.
    """
    held = (f'<Parameter name="Duration">{int(duration)}</Parameter>'
            if duration else "")
    return ('<Action><Target>Device</Target><Operation><Name>SendCommand</Name>'
            f'<Parameter name="DeviceId">{dev}</Parameter>'
            f'<Parameter name="Command">{esc(cmd)}</Parameter>'
            f'<Parameter name="Modifier">{mod}</Parameter>{held}'
            "</Operation></Action>")

def _a_setvalue(dev, state, value):
    return ('<Action><Target>Device</Target><Operation><Name>SetValue</Name>'
            f'<Parameter name="DeviceId">{dev}</Parameter>'
            f'<Parameter name="State">{esc(state)}</Parameter>'
            f'<Parameter name="Value">{esc(value)}</Parameter></Operation></Action>')

def _a_delay(dev, ms):
    return ('<Action><Target>Device</Target><Operation><Name>SendDelay</Name>'
            f'<Parameter name="DeviceId">{dev}</Parameter>'
            f'<Parameter name="Delay">{int(ms)}</Parameter></Operation></Action>')

def _a_number(dev, number):        # dial a channel via the device's Numeric block
    return ('<Action><Target>Device</Target><Operation><Name>SendNumber</Name>'
            f'<Parameter name="DeviceId">{dev}</Parameter>'
            f'<Parameter name="Value">{esc(str(number))}</Parameter></Operation></Action>')

# The firmware's whole action vocabulary is five operations (HAO.lua `handleAction`):
# SetValue, SendCommand, SendDelay, SendNumber and SendFlush. The first four are used
# by real configurations and are offered here. SendFlush is NOT: it appears in no
# configuration available, so its correct use is unknown, and authoring a guess would
# produce a config that looks right and is not.
def digit_command(spec, digit) -> str | None:
    """What this device calls the key for `digit`, or None if it has no number keys.

    Real configurations name them "0".."9". Afterglow assumed "Number0".."Number9" in
    two separate places - the <Numeric> block and favourite-channel dialling - and both
    emitted commands that no device had, so number entry and favourites did nothing at
    all while the config still built and verified.
    """
    have = {command[0] for command in spec.get("commands", [])}
    return next((name for name in (str(digit), f"Number{digit}") if name in have), None)


def _action(step):
    """Normalize one action step (used by macros, enter and leave):

        ('command', dev, cmd)          send an IR command   (optional 4th: modifier)
        ('command', dev, cmd, 'Hold')  ... held rather than pressed
        ('state',   dev, state, value) set any device state (Power, InputType, ...)
        ('input',   dev, value)        shorthand for ('state', dev, 'Input', value)
        ('delay',   dev, ms)           wait
        ('number',  dev, n)            dial a channel through the device's Numeric block

    or the bare 2-tuple (dev, cmd) as shorthand for a command.
    """
    if len(step) == 2:                              # (dev, cmd) shorthand
        return _a_send(step[0], step[1])
    kind = step[0]
    if kind == "command":
        # Hold is the majority modifier in real configs, not an exotic case, and a
        # trailing duration in milliseconds is optional after it.
        return _a_send(step[1], step[2], step[3] if len(step) > 3 else "Press",
                       step[4] if len(step) > 4 else None)
    if kind == "state":    return _a_setvalue(step[1], step[2], step[3])
    if kind == "input":    return _a_setvalue(step[1], "Input", step[2])
    if kind == "delay":    return _a_delay(step[1], step[2])
    if kind == "number":   return _a_number(step[1], step[2])
    raise ValueError("bad action step: %r" % (step,))
