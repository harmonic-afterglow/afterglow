"""Where every screen a generated Harmony One owns sits in section 6, and every activity's
context in section 10, decided before any of them is drawn.

A screen's ordinal is its position in section 6, not its emission order, so every page's
ordinal can be assigned first and a navigation can name a page that has not been emitted
yet. The order is the hub's: Activities (the home screen), Options and the screens
carried behind it, the charging screens, the device menu, each device's command pages,
the rest of the Activities menu, each activity's screens, then Help with nothing running,
Options' second page and the Tutorial.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .pages import BUTTON_POSITIONS, MENU_ROWS_PER_PAGE
from .scaffold import CHARGE_CONTEXTS


@dataclass
class Ordinals:
    platform: int                       # the firmware's screens: 0 to platform - 1
    home: int | None = None             # Activities, the first screen the image owns
    options: int | None = None
    carried: int | None = None          # the first carried screen behind Options
    charging: list[int] = field(default_factory=list)   # the battery, then its photos
    first_menu: int = 0                 # the device menu's first page
    menu: list[int] = field(default_factory=list)
    commands: dict[int, list[int]] = field(default_factory=dict)   # by device index
    menu_of_device: dict[int, int] = field(default_factory=dict)
    activity_menu: list[int] = field(default_factory=list)
    activities: list[dict] = field(default_factory=list)          # per activity
    off_help: int | None = None
    off: dict = field(default_factory=dict)        # Off's Help and Remote Assistant
    options_more: int | None = None
    tutorial: list[int] = field(default_factory=list)
    # section 10: each activity's context, then Off's
    activity_context: int = CHARGE_CONTEXTS["low"] + 1
    off_context: int = CHARGE_CONTEXTS["low"] + 1


def hub(*, platform: int, hub: bool, carried_modes: int | None, charging: int = 0) -> Ordinals:
    """The hub's own screens, which the carried screens name before anything else is
    numbered. ``carried_modes`` is how many screens Options carries, None without Options;
    ``charging`` how many charging screens the idle layer shows, which it names too."""
    carried = carried_modes is not None
    out = Ordinals(platform=platform)
    out.home = platform if hub else None
    # Options, and the screens carried behind it, come straight after Activities; then
    # the charging screens, which only an image with the idle layer has.
    out.options = platform + 1 if carried else None
    out.carried = platform + 2 if carried else None
    first_charging = platform + 2 + carried_modes if carried else None
    out.charging = list(range(first_charging, first_charging + charging)) if carried else []
    out.first_menu = (platform + (1 if hub else 0) + (1 + carried_modes if carried else 0)
                      + len(out.charging))
    return out


# The Remote Assistant's notes each activity has, and Off's, in the order they are made.
ASSISTANT = ("first", "set-up", "again", "hide", "how-to-hide")
OFF_ASSISTANT = ("welcome", "first", "again", "hide", "how-to-hide")
# Help's screens for each thing it asks about: the question, the question again after a
# fix, the question asked once more, and whether that fixed it.
QUESTION = ("ask", "now", "again", "fixed")


def screens(out: Ordinals, *, hub: bool, system: bool, device_pages: dict[int, list],
            acts: list[dict], device_slots: list[dict], tutorial_pages: int,
            off_devices: list[int] = ()) -> Ordinals:
    """Number every other owned screen, after the hub's. ``device_pages`` is each
    device's command pages, in menu order; ``device_slots`` which of power and input each
    device has a variable for; ``system`` whether the image has the firmware's screens;
    ``off_devices`` the devices Off turns off."""
    menu_devices = list(device_pages)
    menu_count = (len(menu_devices) + MENU_ROWS_PER_PAGE - 1) // MENU_ROWS_PER_PAGE
    if hub:
        menu_count = max(1, menu_count)
    elif not system:
        menu_count = 0
    out.menu = list(range(out.first_menu, out.first_menu + menu_count))
    cursor = out.first_menu + menu_count
    for device_index in menu_devices:
        out.commands[device_index] = list(range(cursor, cursor + len(device_pages[device_index])))
        cursor += len(device_pages[device_index])
    if menu_count:
        out.menu_of_device = {device_index: out.menu[position // MENU_ROWS_PER_PAGE]
                              for position, device_index in enumerate(menu_devices)}

    # Then the activities' screens, in the order they are emitted: the Activities menu's
    # pages after its first (which is the home screen), then each activity's screens.
    menu_pages = max(1, -(-len(acts) // MENU_ROWS_PER_PAGE))
    out.activity_menu = [out.home] + list(range(cursor, cursor + menu_pages - 1))
    cursor += menu_pages - 1

    def take(count):
        nonlocal cursor
        cursor += count
        return list(range(cursor - count, cursor))

    def questions(asked):
        return [dict(zip(QUESTION, take(len(QUESTION)))) for _ in asked]

    # Each activity: starting, its favourites' pages, its buttons' pages, Help, Help's
    # first question and then four screens per device and input it asks about, and the
    # Remote Assistant's notes.
    for act in acts:
        favourite_pages = -(-len(act["favourites"]) // len(BUTTON_POSITIONS))
        command_pages = -(-len(act["buttons"]) // len(BUTTON_POSITIONS))
        if not favourite_pages:
            command_pages = max(1, command_pages)
        asked = ([("power", index) for index in act["on"] if "power" in device_slots[index]]
                 + [("input", index, value) for index, value in act["inputs"]
                    if "input" in device_slots[index]])
        screens_ = {"start": take(1)[0], "favourites": take(favourite_pages),
                    "pages": take(command_pages), "help": take(1)[0],
                    "prompt": take(1)[0], "questions": questions(asked), "asked": asked,
                    "assistant": dict(zip(ASSISTANT, take(len(ASSISTANT))))}
        screens_["home"] = (screens_["favourites"] or screens_["pages"])[0]
        out.activities.append(screens_)
    if acts:
        out.off_help = take(1)[0]
        asked = [("off", index) for index in off_devices if "power" in device_slots[index]]
        out.off = {"prompt": take(1)[0], "questions": questions(asked), "asked": asked,
                   "assistant": dict(zip(OFF_ASSISTANT, take(len(OFF_ASSISTANT))))}
        # Options' second page, with the Remote Assistant's switch.
        out.options_more = take(1)[0]
        out.tutorial = take(tutorial_pages)
    # The idle layer's contexts are 1 and 2, then its charge contexts; each activity's
    # follows, then Off's.
    out.off_context = out.activity_context + len(acts)
    return out
