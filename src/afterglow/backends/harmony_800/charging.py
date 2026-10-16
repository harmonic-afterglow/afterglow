"""The screens a Harmony 800 shows while it charges, as its factory image shows them.

The battery - and after it any photographs a theme adds - each a whole screen of one picture
with nothing over it, no title, no status bar: the idle layer (idle.py) opens them a moment
after charging starts and goes back to what was shown when charging stops; each screen
enters the next when its timer runs out, and after the last the screen rests dark and the
battery shows again. Every key starts again from the battery, so a key pressed on the cradle
does nothing else. The pictures are the scaffold's `charging/*`, so a theme can replace them.

Format reference: docs/harmony_one/gspm.md, "Charging"
"""

from __future__ import annotations

from . import keys
from .structures import OBJECT_ATOM

BATTERY = "charging/battery"


def roles(pictures) -> list[str]:
    """The charging pictures an image has, in the order they are shown: the battery, then
    ``charging/photo-1`` onwards for as long as they run; none without the battery."""
    if BATTERY not in pictures:
        return []
    out, number = [BATTERY], 1
    while f"charging/photo-{number}" in pictures:
        out.append(f"charging/photo-{number}")
        number += 1
    return out


def place(screens, numbers, chosen: list[str]):
    """The charging screens, at ``numbers.charging``, one per picture in ``chosen``."""
    if not chosen:
        return
    layout = screens.layout
    again = layout.navigation(numbers.charging[0])
    every_key = [(keys.code(scan), again, OBJECT_ATOM) for scan in keys.SCANS.values()]
    for index, role in enumerate(chosen):
        def program(picture, _prologue, role=role):
            return [{"opcode": "bitmap", "x": 0, "y": 0, "target": picture(role)},
                    {"opcode": "end"}]
        screens.owned([], [], program, f"charging-{index}", keys=every_key, bare=True)
