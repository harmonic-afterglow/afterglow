"""The hub every Logitech configuration has, devices or not: the Activities screen it boots
into, the device menu behind Devices, and each device's pages of command buttons.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from collections.abc import Mapping

from . import drawing, structures
from .devices import device_key_rows
from .pages import (
    BUTTON_POSITIONS, FIRST_BUTTON_KEY, HOME_DEVICES_TAG, HOME_OPTIONS_TAG,
    MENU_ACTIVITIES_KEY, MENU_ROW_KEYS, MENU_ROWS_PER_PAGE, PAGE_ACTIVITIES_KEY,
    PAGE_DEVICES_KEY, SIDE_NEXT_KEY, SIDE_PREV_KEY, SOFTKEY_LEFT_ZONE, SOFTKEY_RIGHT_KEY,
    SOFTKEY_RIGHT_ZONE, button_page, menu_page)
from .scaffold import menu_template
from .structures import OBJECT_ATOM


class _Button(Mapping):
    """A button on a device's page: its command, seen through, under a label of its own.
    A view rather than a copy, since the command's wrapper is numbered after the pages
    are planned - and one command can sit on a page twice, under two labels."""

    def __init__(self, command: dict, label: str):
        self._command, self._label = command, label

    def __getitem__(self, key):
        return self._label if key == "label" else self._command[key]

    def __iter__(self):
        return iter({**self._command, "label": self._label})

    def __len__(self):
        return len({**self._command, "label": self._label})


def device_pages(devices: list[dict], frames, roles, font) -> dict[int, list]:
    """Each device's command pages, six commands a page, by device index - when there is a
    font to label them with and a frame to draw them on. A device given a page of its own
    (``screen``) shows those buttons, in that order and under those labels. Otherwise a
    command on one of the device's keys, one with no label and a held code an activity
    sends have a record but no button, as on Logitech's pages. A device with no button
    left still has its one page, which is where its keys are bound. A None on a page given
    to it is a gap: that place stays empty."""
    out = {}
    if not (all(role in roles for role in frames.buttons) and font is not None):
        return out
    for device in devices:
        if "screen" in device:
            # The page the device was given: its buttons in order, each under its label.
            by_name = {command["name"]: command for command in device["commands"]}
            commands = [None if entry is None else _Button(by_name[entry[0]], entry[1])
                        for entry in device["screen"]
                        if entry is None or entry[0] in by_name]
        else:
            commands = [command for command in device["commands"]
                        if not command.get("hidden")]
        out[device["index"]] = [commands[first:first + len(BUTTON_POSITIONS)]
                                for first in range(0, len(commands), len(BUTTON_POSITIONS))
                                ] or [[]]
    return out


class Hub:
    """The hub's screens in ``screens``, at the ``ordinals`` planned for them.
    ``flow`` is the activities' (activity_screens.Flow), or None when the image has
    none; ``hub`` is whether the image has the hub's softkeys at all."""

    def __init__(self, screens, ordinals, devices, pages, *, frames, geometry, hub,
                 flow=None, options=False):
        self.screens = screens
        self.layout = screens.layout
        self.ordinals = ordinals
        self.devices = devices
        self.pages = pages
        self.frames = frames
        self.geometry = geometry
        self.hub = hub
        self.flow = flow
        self.options = options

    def _to_activities(self) -> int:
        """What the Activities softkey runs: back to what is running, or the menu."""
        if self.flow is not None and self.flow.acts:
            return self.flow.back_to_current()
        return self.layout.navigation(self.ordinals.home)

    def home(self):
        """Activities with none yet: the list says so, and Devices opens the device list."""
        screens, layout, ordinals = self.screens, self.layout, self.ordinals
        rows = [(SOFTKEY_RIGHT_KEY, layout.navigation(ordinals.menu[0]), OBJECT_ATOM)]
        zones = [dict(SOFTKEY_RIGHT_ZONE, tag=HOME_DEVICES_TAG)]
        names = ["devices"]
        if self.options:
            rows.append((0x80 | HOME_OPTIONS_TAG, layout.navigation(ordinals.options),
                         OBJECT_ATOM))
            zones.append(dict(SOFTKEY_LEFT_ZONE, tag=HOME_OPTIONS_TAG))
            names.insert(0, "options")

        def program(_picture, prologue):
            out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            out += screens.message(screens.words("hub.no-activities")) + [{"opcode": "end"}]
            return screens.softkeys(out, names)
        screens.owned(rows, zones, program, "activities", screens.words("hub.activities-title"))

    def device_menu(self):
        """The device menu: a page of up to three rows, and where there are more devices
        the side strips move between menu pages in a cycle."""
        screens, layout, ordinals = self.screens, self.layout, self.ordinals
        menu = ordinals.menu
        devices = list(self.pages)
        icon_roles = sorted(role for role in screens.roles if role.startswith("row-icon/"))
        running = self.flow is not None and bool(self.flow.acts)
        for page_index in range(len(menu)):
            on_page = devices[page_index * MENU_ROWS_PER_PAGE:
                              (page_index + 1) * MENU_ROWS_PER_PAGE]
            # a row is a navigation to the device's first page
            rows = [(MENU_ROW_KEYS[slot], layout.navigation(ordinals.commands[index][0]),
                     OBJECT_ATOM) for slot, index in enumerate(on_page)]
            if len(menu) > 1:
                rows.append((SIDE_PREV_KEY, layout.navigation(menu[(page_index - 1) % len(menu)]),
                             OBJECT_ATOM))
                rows.append((SIDE_NEXT_KEY, layout.navigation(menu[(page_index + 1) % len(menu)]),
                             OBJECT_ATOM))
            if self.hub:
                # The menu template's own bottom-left zone is the Activities softkey,
                # which goes back to a running activity when there is one.
                rows.append((MENU_ACTIVITIES_KEY, self._to_activities(), OBJECT_ATOM))
            labels = [self.devices[index]["label"] for index in on_page]
            # A configured device carries the icon composed for its type; a bare
            # skeleton takes the scaffold's row icons in turn.
            icons = [self.devices[index].get("icon")
                     or (icon_roles[number % len(icon_roles)] if icon_roles else None)
                     for number, index in enumerate(on_page)]

            def program(picture, prologue, labels=labels, icons=icons):
                # A page with no rows names no frame, so an empty list places none.
                frame = picture("row-frame") if labels else 0
                out = menu_page(labels, frame, [role and picture(role) for role in icons],
                                screens.font, prologue=prologue, attribute=screens.label,
                                label_room=self.frames.row_label_room)
                if not labels:
                    out[-1:] = (screens.message(screens.words("hub.no-devices"))
                                + [{"opcode": "end"}])
                if self.hub and running:
                    return screens.softkeys_with_current(out, [])
                return screens.softkeys(out, ["activities"]) if self.hub else out
            screens.owned(rows, menu_template(), program, "devices",
                          screens.words("hub.devices-title"), (page_index, len(menu)))

    def command_pages(self):
        """Command pages, device by device. A device with more than six commands spans
        several pages; the side strips move between them and wrap round - past the last
        page to the first, before the first to the last - as Logitech's own do. Leading
        back to the device list from either end, as they once did here, is what three
        testers reported as broken; Devices is the way back."""
        screens, layout, ordinals = self.screens, self.layout, self.ordinals
        running = self.flow is not None and bool(self.flow.acts)
        frames = self.frames
        for device_index, chunks in self.pages.items():
            pages = ordinals.commands[device_index]
            home = ordinals.menu_of_device.get(device_index, pages[0])
            for page_index, chunk in enumerate(chunks):
                rows = [(FIRST_BUTTON_KEY + index, command["wrapper_index"], OBJECT_ATOM)
                        for index, command in enumerate(chunk) if command is not None]
                if len(chunks) > 1:
                    previous = pages[(page_index - 1) % len(chunks)]
                    following = pages[(page_index + 1) % len(chunks)]
                    rows.append((SIDE_PREV_KEY, layout.navigation(previous), OBJECT_ATOM))
                    rows.append((SIDE_NEXT_KEY, layout.navigation(following), OBJECT_ATOM))
                elif ordinals.menu_of_device:
                    rows.append((SIDE_NEXT_KEY, layout.navigation(home), OBJECT_ATOM))
                zones = without_gaps(page_zones(self.geometry, len(chunk)), chunk)
                # The softkeys upstairs' device pages carry: Activities bottom left,
                # Devices bottom right, in the screen's bottom strip. Whatever a donor
                # template had in the strip gives way to them.
                if self.hub:
                    zones = [zone for zone in zones if zone["y"] != SOFTKEY_LEFT_ZONE["y"]]
                    zones += [dict(SOFTKEY_LEFT_ZONE, tag=PAGE_ACTIVITIES_KEY & 0x7F),
                              dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F)]
                    rows.append((PAGE_ACTIVITIES_KEY, self._to_activities(), OBJECT_ATOM))
                    rows.append((PAGE_DEVICES_KEY, layout.navigation(home), OBJECT_ATOM))
                labels = [None if command is None else command.get("label") or command["name"]
                          for command in chunk]
                gaps = [command is None for command in chunk]
                keys = device_key_rows(self.devices[device_index]["commands"])

                def program(picture, prologue, labels=labels, gaps=gaps):
                    out = button_page(
                        labels, [None if gap else picture(role)
                                 for role, gap in zip(frames.buttons, gaps)],
                        screens.font, prologue=prologue, attribute=screens.label,
                        frame_width=frames.width)
                    if self.hub and running:
                        return screens.softkeys_with_current(out, ["devices"])
                    return screens.softkeys(out, ["activities", "devices"]) if self.hub else out
                screens.owned(rows, zones, program,
                              "commands-paged" if len(chunks) > 1 else "commands",
                              self.devices[device_index]["label"], (page_index, len(chunks)),
                              keys=keys)


def page_zones(geometry: dict[int, list[dict]], buttons: int) -> list[dict]:
    """The touch zones of a page of ``buttons``. The donors carry geometry for 1, 2, 3, 5
    and 6 button pages; a page of a size they never drew takes the smallest template that
    still covers its buttons, so no zone is left pointing at a button it does not draw. A
    page with none yet takes the one-button template, without its button."""
    fitting = sorted(size for size in geometry if size >= max(1, buttons))
    if not fitting:
        raise ValueError(f"no touch template covers a page of {buttons} buttons; "
                         f"the scaffold has {sorted(geometry)}")
    return [zone for zone in geometry[fitting[0]]
            if (zone["tag"] | 0x80) < FIRST_BUTTON_KEY + buttons
            or (zone["tag"] | 0x80) >= FIRST_BUTTON_KEY + len(BUTTON_POSITIONS)]


def without_gaps(zones: list[dict], chunk: list) -> list[dict]:
    """A page's touch zones but those of its gaps (the None places in ``chunk``), so a
    touch where nothing is drawn does nothing."""
    empty = {FIRST_BUTTON_KEY + slot for slot, entry in enumerate(chunk) if entry is None}
    return [zone for zone in zones if (zone["tag"] | 0x80) not in empty]


def empty_screen(screens, owned_handlers):
    """Nothing the project owns to show still needs a screen at the first owned ordinal,
    since section 6 has no zero-screen form and the OK buttons open that ordinal. It is
    also the screen such an image boots into, and nothing clears the display, so it draws
    the backdrop and says so: a screen that draws nothing leaves the boot logo up, which
    looks exactly like a remote that never started."""
    layout = screens.layout
    if screens.font is not None:
        def program(_picture, prologue):
            out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            return out + screens.message(screens.words("hub.no-devices")) + [{"opcode": "end"}]
        screens.owned([], 0, program)
    else:
        [[at]] = layout.mode(structures.key_register(owned_handlers), 0,
                             [(0, [], [len(drawing.encode_program([{"opcode": "end"}]))])])
        layout.pending_programs.append((at, lambda _picture, _prologue: [{"opcode": "end"}],
                                        None))
