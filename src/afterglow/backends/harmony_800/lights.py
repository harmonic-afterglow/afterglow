"""The One's light instructions on the 800's light channels.

A light is opcode `3F` with band `C0`-`CF`: the One reads the channel from five bits,
`(operand >> 4) & 0x1F` (harmony_one/gspm.md), and has the screen's backlight on channel
`0x11`, its keypad on `0x08`-`0x0C` and `0x10`, and eight zones on 0-7. The 800 reads only
the operand's low byte, `channel = low >> 4`, `level = (low >> 1) & 7`, `flag = low & 1`
(`FUN_0800b61a`), and has LEDs on channels 0-6 and the display's backlight on channel 7, a
driver of its own (`FUN_0800b274`); Logitech's image sets channel 7 only with the flag.

So the One's backlight goes to channel 7 and any channel above 7 becomes `3F 0000`, a band
the 800's interpreter does nothing with. The idle layer (idle.py) lights the 800's own
channels: the keys, the keyboard and the power key while awake, as Logitech's image does,
and the touch areas - the arrows beside the display and the areas below it - per screen,
each of the One's zones on the 800 LED in its place (idle.zone_light). A light instruction
still in the One's numbering, from a carried One model, lights nothing on zone 7, which
would be the 800's backlight (`one`). Instructions can pass the encoders twice, so
`instruction` leaves channels 0-7 alone.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

SETTING = 0x3F
ONE_BACKLIGHT, BACKLIGHT = 0x11, 7
LEDS = range(7)
NOTHING = (0x0000, SETTING)


def instruction(operand: int, opcode: int) -> tuple[int, int]:
    """``(operand, opcode)`` as the 800 must be given it: a One light renumbered. Channels
    0-7 are the 800's own already, so a second pass changes nothing."""
    if opcode != SETTING or not 0xC000 <= operand <= 0xCFFF:
        return operand, opcode
    channel, low = (operand >> 4) & 0x1F, operand & 0x0F
    if channel == ONE_BACKLIGHT:
        return 0xC000 | BACKLIGHT << 4 | low, opcode
    if channel in LEDS or channel == BACKLIGHT:
        return operand, opcode
    return NOTHING


def one(operand: int, opcode: int) -> tuple[int, int]:
    """An instruction still in the One's numbering - read from a carried One model - as the
    800 must be given it: the One's zone 7 lights nothing, and the rest as `instruction`."""
    if opcode == SETTING and 0xC000 <= operand <= 0xCFFF and (operand >> 4) & 0x1F == BACKLIGHT:
        return NOTHING
    return instruction(operand, opcode)


