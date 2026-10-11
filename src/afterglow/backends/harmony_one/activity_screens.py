"""The activities a generated Harmony One runs, as Logitech's remotes run them: the
Activities menu, each activity's starting screen, favourites and command pages, its Help
and the Remote Assistant's questions, and the section-10 context that starts it - and Off.

What each activity does was planned already (activities.py); this lays it out.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from . import activity_index, keys, structures
from .hub import page_zones
from .idle import MODE_STACK
from .pages import (
    BUTTON_POSITIONS, FIRST_BUTTON_KEY, HELP_FONT, HELP_KEEP_TOP, HELP_SENDING_XY, HELP_TOP,
    LABEL_BASELINE, MENU_DEVICES_KEY, MENU_OPTIONS_KEY, MENU_ROW_KEYS, MENU_ROWS_PER_PAGE,
    PAGE_ACTIVITIES_KEY, PAGE_DEVICES_KEY, QUESTION_TOP, SCREEN_WIDTH, SIDE_NEXT_KEY,
    SIDE_PREV_KEY, SOFTKEY_LEFT_ZONE, SOFTKEY_RIGHT_ZONE, START_FONT, START_KEEP_TOP,
    START_TEXT_Y, button_page, fit_label, measure, menu_page)
from .pictures import SENDING_XY, START_ICON_XY
from .scaffold import menu_template
from .structures import ENTER_MODE, OBJECT_ATOM, object_body

# `07 FFFB`: stop every running timer, as each donor's activity does first.
STOP_TIMERS = (0xFFFB, MODE_STACK)


def _enter(ordinal: int) -> list[dict]:
    """A block that opens screen ``ordinal``."""
    return [{"opcode": "atom", "operand": ordinal, "category": ENTER_MODE}, {"opcode": "end"}]


class Flow:
    """The activities' screens and contexts in ``screens``, at the ``ordinals`` planned
    for them. ``acts`` is the plan's activities, ``variables`` the build's own
    (devices.Variables): ``state`` counts which activity runs, ``assistant`` is whether
    the Remote Assistant asks. ``all_off`` is the plan's Off."""

    def __init__(self, screens, ordinals, variables, devices, acts, actions, *, frames,
                 geometry, all_off=None):
        self.screens = screens
        self.layout = screens.layout
        self.ordinals = ordinals
        self.variables = variables
        self.devices = devices
        self.acts = acts
        self.actions = actions
        self.frames = frames
        self.geometry = geometry
        self.all_off = all_off or {"off": []}
        # Back to what is running: an activity's first page, or the Activities menu.
        layout = self.layout
        self.current_group = self.resume_group = None
        if variables.state is not None:
            self.current_group = layout.group(
                [(value, layout.block(_enter(item["home"])))
                 for value, item in enumerate(ordinals.activities)]
                + [(len(acts), layout.block(_enter(ordinals.home)))])
            # From the Activities menu, its key goes back to a running activity only.
            self.resume_group = layout.group(
                [(value, layout.block(_enter(item["home"])))
                 for value, item in enumerate(ordinals.activities)]) if acts else None

    def back_to_current(self) -> int:
        """An object that opens what is running: an activity's first page, or the menu."""
        return self.layout.object(object_body([
            (structures.IR_OBJECT_KIND_FALLBACK, 0x75),
            ((self.current_group << 8) | self.variables.state, 0x72)]))

    def _row_frame(self) -> str:
        return ("activity/row-frame" if "activity/row-frame" in self.screens.roles
                else "row-frame")

    def menu_page(self, page_index: int):
        """One page of the Activities menu: up to three activities, each row starting
        its activity by selecting its context, on the activities' own row frame."""
        screens, layout, ordinals, acts = self.screens, self.layout, self.ordinals, self.acts
        total = len(ordinals.activity_menu)
        on_page = list(range(page_index * MENU_ROWS_PER_PAGE,
                             min(len(acts), (page_index + 1) * MENU_ROWS_PER_PAGE)))
        rows = [(MENU_ROW_KEYS[slot], layout.object(object_body([
                    (structures.IR_OBJECT_KIND_FALLBACK, 0x75),
                    (0xFF00 | (ordinals.activity_context + index), 0x1F)])), OBJECT_ATOM)
                for slot, index in enumerate(on_page)]
        rows.append((MENU_OPTIONS_KEY, layout.navigation(ordinals.options), OBJECT_ATOM))
        rows.append((MENU_DEVICES_KEY, layout.navigation(ordinals.menu[0]), OBJECT_ATOM))
        if total > 1:
            rows.append((SIDE_PREV_KEY, layout.navigation(
                ordinals.activity_menu[(page_index - 1) % total]), OBJECT_ATOM))
            rows.append((SIDE_NEXT_KEY, layout.navigation(
                ordinals.activity_menu[(page_index + 1) % total]), OBJECT_ATOM))
        zones = menu_template() + [dict(SOFTKEY_RIGHT_ZONE, tag=MENU_DEVICES_KEY & 0x7F)]
        frame_role = self._row_frame()
        labels = [acts[index]["label"] for index in on_page]
        icons = [acts[index].get("icon") for index in on_page]

        def program(picture, prologue, labels=labels, icons=icons):
            built = menu_page(labels, picture(frame_role),
                              [role and picture(role) for role in icons], screens.font,
                              prologue=prologue, attribute=screens.label,
                              label_room=self.frames.row_label_room)
            return screens.softkeys(built, ["options", "devices"])
        # On the menu the Activities key goes back to what is running.
        menu_keys = [(keys.code(keys.ACTIVITIES),
                      (self.resume_group << 8) | self.variables.state, 0x72)]
        screens.owned(rows, zones, program, "activities", screens.words("hub.activities-title"),
                      (page_index, total), keys=menu_keys)

    # -- the activities' own screens

    def _frames(self) -> list[str]:
        frames = [f"activity/button-frame/{index}" for index in range(len(BUTTON_POSITIONS))]
        if not all(role in self.screens.roles for role in frames):
            frames = self.frames.buttons
        return frames

    def _sending(self, picture) -> list[dict]:
        return ([{"opcode": "bitmap", "x": SENDING_XY[0], "y": SENDING_XY[1],
                  "target": picture("activity/sending")}]
                if "activity/sending" in self.screens.roles else [])

    def _swallow(self) -> list[tuple[int, int, int]]:
        """Every key held off, as a screen that waits does."""
        return [(keys.code(scan), 0, 0) for scan in keys.SCANS.values()]

    def help_screen(self, title, before):
        """Help: the activity's name, what it is doing, and the remote's waves, while
        ``before`` re-sends what the activity needs."""
        screens = self.screens

        def program(picture, prologue):
            out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            out += screens.lines(screens.words("activity.fixing"), HELP_FONT, HELP_TOP)
            out += [{"opcode": "bitmap", "x": HELP_SENDING_XY[0],
                     "y": HELP_SENDING_XY[1], "target": picture("activity/sending")}
                    ] if "activity/sending" in screens.roles else []
            out += screens.lines(screens.words("activity.keep-pointed"), HELP_FONT,
                                 HELP_KEEP_TOP)
            return out + [{"opcode": "end"}]
        screens.owned([], [], program, "help", title, keys=self._swallow(), on_enter=before)

    def _yes_no(self, title, question, yes, no, fix_object=False):
        """A question with Yes and No on the bottom row: Yes opens ``yes``, No runs
        ``no`` - a screen to open, or with ``fix_object`` an object to run."""
        screens, layout = self.screens, self.layout
        frames, frame_width = self._frames(), self.frames.width
        rows = [(FIRST_BUTTON_KEY + 4, layout.navigation(yes), OBJECT_ATOM),
                (FIRST_BUTTON_KEY + 5, no if fix_object else layout.navigation(no),
                 OBJECT_ATOM)]
        zones = [zone for zone in self.geometry[len(BUTTON_POSITIONS)]
                 if (zone["tag"] | 0x80) in (FIRST_BUTTON_KEY + 4, FIRST_BUTTON_KEY + 5)]

        def program(picture, prologue):
            out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            out += screens.lines(question, HELP_FONT, QUESTION_TOP, lines=3)
            widths, _codes = measure(screens.font)
            out.append({"opcode": "attribute", "value": screens.label})
            for slot, text in ((4, screens.words("assistant.yes")),
                               (5, screens.words("assistant.no"))):
                left, top = BUTTON_POSITIONS[slot]
                out.append({"opcode": "bitmap", "x": left, "y": top,
                            "target": picture(frames[slot])})
                [glyphs] = fit_label(text, screens.font, frame_width, lines=1)
                width = sum(widths[code] for code in glyphs)
                out.append({"opcode": "inline_text", "x": (2 * left + frame_width - width) // 2,
                            "y": top + LABEL_BASELINE, "glyphs": glyphs.hex()})
            return out + [{"opcode": "end"}]
        screens.owned(rows, zones, program, "question", title)

    def _start_screen(self, act):
        """Starting: its icon under the waves, "Starting ...", and every key held off
        until the activity is running."""
        screens = self.screens

        def program(picture, prologue):
            out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            out += self._sending(picture)
            if act.get("start_icon"):
                out.append({"opcode": "bitmap", "x": START_ICON_XY[0],
                            "y": START_ICON_XY[1], "target": picture(act["start_icon"])})
            out += screens.lines(screens.words("activity.starting", activity=act["label"]),
                                 START_FONT, START_TEXT_Y, room=SCREEN_WIDTH - 12, lines=1)
            out += screens.lines(screens.words("activity.keep-pointed"), HELP_FONT,
                                 START_KEEP_TOP)
            return out + [{"opcode": "end"}]
        screens.owned([], [], program, keys=self._swallow())

    def _button_pages(self, act, entries, ordinals, other, other_key, kind_name):
        """An activity's favourites or its buttons, six a page; the side strips turn the
        pages, the left softkey goes to ``other`` (the other set's first page), and
        Devices opens the device list. Each entry is ``(label, steps, picture)``."""
        screens, layout, actions = self.screens, self.layout, self.actions
        frames, frame_width = self._frames(), self.frames.width
        chunks = [entries[at:at + len(BUTTON_POSITIONS)]
                  for at in range(0, len(entries), len(BUTTON_POSITIONS))] or [[]]
        for page_index, chunk in enumerate(chunks):
            rows = []
            for slot, (_label, steps, _picture) in enumerate(chunk):
                if len(steps) == 1 and steps[0][0] == "send":
                    target = actions.wrapper(steps[0][1], steps[0][2])
                else:
                    target = layout.atoms_object(
                        [(structures.IR_OBJECT_KIND_FALLBACK, 0x75)] + actions.atoms(steps))
                rows.append((FIRST_BUTTON_KEY + slot, target, OBJECT_ATOM))
            if len(chunks) > 1:
                rows.append((SIDE_PREV_KEY, layout.navigation(ordinals[page_index - 1]),
                             OBJECT_ATOM))
                rows.append((SIDE_NEXT_KEY, layout.navigation(
                    ordinals[(page_index + 1) % len(ordinals)]), OBJECT_ATOM))
            rows.append((PAGE_DEVICES_KEY, layout.navigation(self.ordinals.menu[0]),
                         OBJECT_ATOM))
            zones = [zone for zone in page_zones(self.geometry, len(chunk))
                     if zone["y"] != SOFTKEY_LEFT_ZONE["y"]]
            zones.append(dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F))
            softkeys = ["devices"]
            if other is not None:
                zones.append(dict(SOFTKEY_LEFT_ZONE, tag=PAGE_ACTIVITIES_KEY & 0x7F))
                rows.append((PAGE_ACTIVITIES_KEY, layout.navigation(other), OBJECT_ATOM))
                softkeys.insert(0, other_key)
            labels = [text if picture is None else None for text, _steps, picture in chunk]
            pictured = [picture for _text, _steps, picture in chunk]

            def program(picture, prologue, labels=labels, pictured=pictured,
                        softkeys=softkeys):
                built = button_page(
                    labels, [picture(role or frames[slot])
                             for slot, role in enumerate(pictured)], screens.font,
                    prologue=prologue, attribute=screens.label, frame_width=frame_width)
                return screens.softkeys(built, softkeys)
            kind = kind_name + ("-paged" if len(chunks) > 1 else "")
            screens.owned(rows, zones, program, kind, act["label"], (page_index, len(chunks)))

    def _assistant(self, act, ordinals):
        """The Remote Assistant: did everything turn on? No asks about each device and
        input in turn, and fixes the one that is not."""
        words, actions, layout = self.screens.words, self.actions, self.layout
        questions = ordinals["questions"]
        self._yes_no(act["label"], words("assistant.question"), ordinals["home"],
                     questions[0] if questions else ordinals["help"])
        for number, (asked, ordinal) in enumerate(zip(ordinals["asked"], questions)):
            following = questions[number + 1] if number + 1 < len(questions) \
                else ordinals["home"]
            device = self.devices[asked[1]]
            if asked[0] == "power":
                text = words("assistant.is-on", device=device["label"])
                fix = actions.direct_power([asked[1]], True, toggles=True)
            else:
                value = asked[2]
                text = words("assistant.input", device=device["label"],
                             input=device["inputs"]["values"][value])
                fix = actions.input_fix(asked[1], value)
            self._yes_no(act["label"], text, following,
                         layout.atoms_object(fix + [(ordinal, ENTER_MODE)]), fix_object=True)

    def activity(self, index: int) -> list[tuple[int, int]]:
        """One activity's screens; the rows of the context that runs it."""
        act, ordinals = self.acts[index], self.ordinals.activities[index]
        layout, actions, variables = self.layout, self.actions, self.variables
        self._start_screen(act)
        both = bool(ordinals["favourites"]) and bool(ordinals["pages"])
        kind_name = "activity-both" if both else "activity"
        if ordinals["favourites"]:
            self._button_pages(act, [(item["label"], item["steps"], item.get("picture"))
                                     for item in act["favourites"]], ordinals["favourites"],
                               ordinals["pages"][0] if both else None, "commands", kind_name)
        if ordinals["pages"]:
            self._button_pages(act, [(text, steps, None) for text, steps in act["buttons"]],
                               ordinals["pages"], ordinals["favourites"][0] if both else None,
                               "favourites", kind_name)

        # Where a start ends: the Remote Assistant's question while it is on, else the
        # activity's own first page.
        after = layout.group([(0, layout.block(_enter(ordinals["home"]))),
                              (1, layout.block(_enter(ordinals["prompt"])))])
        finish = ((after << 8) | variables.assistant, 0x72)

        # Help: re-send the power and inputs the activity set, then the question.
        self.help_screen(act["label"], (
            [STOP_TIMERS] + actions.direct_power(act["on"], True)
            + actions.input_writes(act["inputs"]), [finish]))
        self._assistant(act, ordinals)

        return [
            (activity_index.ENTER, layout.atoms_object(
                [(ordinals["start"], ENTER_MODE), STOP_TIMERS]
                + actions.power_writes(act["on"], 1) + actions.input_writes(act["inputs"])
                + actions.power_writes(act["off"], 0) + [(index, 0x80 | variables.state)]
                + actions.atoms(act["enter"]) + [finish])),
            (activity_index.LEAVE, layout.atoms_object(
                [STOP_TIMERS] + actions.atoms(act["leave"]))),
            # picked again while running: its inputs again, and back to its screen
            (activity_index.REFRESH, layout.atoms_object(
                [STOP_TIMERS] + actions.input_writes(act["inputs"])
                + [(ordinals["home"], ENTER_MODE)])),
            (keys.code(keys.HELP), layout.navigation(ordinals["help"])),
        ] + [(code, actions.key_target(steps)) for code, steps in sorted(act["keys"].items())]

    def activities(self) -> dict[int, list[tuple[int, int]]]:
        """The rest of the Activities menu, then every activity's screens; each
        activity's context rows, by context."""
        for page_index in range(1, len(self.ordinals.activity_menu)):
            self.menu_page(page_index)
        return {self.ordinals.activity_context + index: self.activity(index)
                for index in range(len(self.acts))}

    def off(self) -> list[tuple[int, int]]:
        """Off: nothing running, the Activities menu, and every device off behind it;
        its Help turns them off again. It has no leave, as no donor's has."""
        layout, ordinals, off = self.layout, self.ordinals, self.all_off
        home = ordinals.home
        rows = [
            (activity_index.ENTER, layout.atoms_object(
                [(len(self.acts), 0x80 | self.variables.state), STOP_TIMERS,
                 (home, ENTER_MODE)] + self.actions.power_writes(off["off"], 0))),
            (activity_index.REFRESH, layout.object(object_body([(home, ENTER_MODE)]))),
        ]
        if self.acts:
            rows.append((keys.code(keys.HELP), layout.navigation(ordinals.off_help)))
            self.help_screen(off.get("label") or self.screens.words("activity.power-off"), (
                [STOP_TIMERS] + self.actions.direct_power(off["off"], False),
                [(home, ENTER_MODE)]))
        return rows
