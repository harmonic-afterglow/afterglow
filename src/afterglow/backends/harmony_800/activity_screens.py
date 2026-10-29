"""The activities a generated Harmony 800 runs, as Logitech's remotes run them: the
Activities menu, each activity's starting screen, favourites and command pages, its Help
and the Remote Assistant's questions, and the section-10 context that starts it - and Off.

What each activity does was planned already (activities.py); this lays it out.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from ...project_devices import input_label

from . import activity_index, keypad, keys, structures
from .hub import page_zones, without_gaps
from .idle import MODE_STACK
from .pages import (
    ASSISTANT_Y, BUTTON_POSITIONS, FIRST_BUTTON_KEY, HELP_FONT, HELP_KEEP_TOP,
    HELP_PROMPT_Y, HELP_QUESTION_Y, HELP_SENDING_XY, HELP_TOP, LINE_SPACING,
    MENU_DEVICES_KEY, MENU_OPTIONS_KEY, MENU_ROW_KEYS, MENU_ROWS_PER_PAGE,
    PAGE_ACTIVITIES_KEY, PAGE_DEVICES_KEY, SCREEN_WIDTH, SENDING_XY, SIDE_NEXT_KEY,
    SIDE_PREV_KEY, SOFTKEY_LEFT_ZONE, SOFTKEY_RIGHT_ZONE, START_FONT, START_ICON_XY,
    START_KEEP_TOP, START_TEXT_Y, button_page, menu_page)
from .scaffold import menu_template
from .structures import ENTER_MODE, OBJECT_ATOM, object_body

# `07 FFFB`: stop every running timer, as each donor's activity does first.
STOP_TIMERS = (0xFFFB, MODE_STACK)
# The touch keys an answer softkey binds, as upstairs binds them: 0xB1 for Yes - or OK,
# alone at the right - and 0xB2 for No.
ANSWER_KEYS = (0xB1, 0xB2)


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
            out += screens.lines(screens.words("help.keep-pointed"), HELP_FONT,
                                 HELP_KEEP_TOP)
            return out + [{"opcode": "end"}]
        screens.owned([], [], program, "help", title, keys=self._swallow(), on_enter=before)

    def _paragraphs(self, text, top, lines=3) -> list[dict]:
        """``text`` centred, a paragraph per line break with a blank line between."""
        screens, out = self.screens, []
        for paragraph in text.split("\n"):
            drawn = screens.lines(paragraph, HELP_FONT, top, lines=lines)
            out += drawn
            top += LINE_SPACING * (len(drawn) - 1) + LINE_SPACING
        return out

    def _answered(self, title, draw, answers, *, icon=None, on_enter=None, home=None):
        """A screen of Help or the Remote Assistant, as upstairs draws one: its title,
        ``draw``'s words (with the activity's ``icon`` above them, for Help), and its
        answers as softkeys - Yes bottom left, No or OK bottom right. ``answers`` is
        {"yes"|"no"|"ok": object}; with ``home``, Help goes back to the activity."""
        screens, layout = self.screens, self.layout
        zone = {"yes": (SOFTKEY_LEFT_ZONE, ANSWER_KEYS[0]),
                "no": (SOFTKEY_RIGHT_ZONE, ANSWER_KEYS[1]),
                "ok": (SOFTKEY_RIGHT_ZONE, ANSWER_KEYS[0])}
        rows = [(zone[name][1], target, OBJECT_ATOM) for name, target in answers.items()]
        zones = [dict(zone[name][0], tag=zone[name][1] & 0x7F) for name in answers]
        mode_keys = ([(keys.code(keys.HELP), layout.navigation(home), OBJECT_ATOM)]
                     if home is not None else [])

        def program(picture, prologue):
            out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            if icon:
                out.append({"opcode": "bitmap", "x": START_ICON_XY[0], "y": START_ICON_XY[1],
                            "target": picture(icon)})
            out += draw()
            return screens.softkeys(out + [{"opcode": "end"}], list(answers))
        screens.owned(rows, zones, program, "question", title, keys=mode_keys,
                      on_enter=on_enter)

    def _help(self, title, ordinals, before, home, icon=None):
        """Help as upstairs runs it: re-send everything and ask whether that fixed it;
        if not, ask after each device and input in turn - No sends it again and asks
        whether it is now right, and once it is, whether that fixed the problem."""
        words, layout = self.screens.words, self.layout
        self.help_screen(title, (before, [(ordinals["prompt"], ENTER_MODE)]))
        nav = layout.navigation
        items = list(zip(ordinals["asked"], ordinals["questions"]))
        first = items[0][1]["ask"] if items else home
        self._answered(title, lambda: self._paragraphs(words("help.fixed-first"),
                                                       HELP_PROMPT_Y),
                       {"yes": nav(home), "no": nav(first)}, icon=icon, home=home)
        for number, (asked, screens_) in enumerate(items):
            following = items[number + 1][1]["ask"] if number + 1 < len(items) else home
            ask, now, fix = self._question(asked)

            def fixing(ordinal, fix=fix):
                return layout.atoms_object(fix + [(ordinal, ENTER_MODE)])

            def question(text):
                return lambda: self._paragraphs(text, HELP_QUESTION_Y)
            self._answered(title, question(ask), {"yes": nav(following),
                                                  "no": fixing(screens_["now"])},
                           icon=icon, home=home)
            self._answered(title, question(now), {"yes": nav(screens_["fixed"]),
                                                  "no": fixing(screens_["again"])},
                           icon=icon, home=home)
            self._answered(title, question(ask), {"yes": nav(screens_["fixed"]),
                                                  "no": fixing(screens_["now"])},
                           icon=icon, home=home)
            self._answered(title, question(words("help.fixed")),
                           {"yes": nav(home), "no": nav(following)}, icon=icon, home=home)

    def _question(self, asked) -> tuple[str, str, list]:
        """What Help asks about one thing - the question, and again once fixed - and
        what answering No sends."""
        words, actions = self.screens.words, self.actions
        device = self.devices[asked[1]]
        if asked[0] == "power":
            return (words("assistant.is-on", device=device["label"]),
                    words("assistant.now-on", device=device["label"]),
                    actions.direct_power([asked[1]], True, toggles=True))
        if asked[0] == "off":
            return (words("assistant.is-off", device=device["label"]),
                    words("assistant.now-off", device=device["label"]),
                    actions.direct_power([asked[1]], False, toggles=True))
        name = input_label(device["inputs"]["values"][asked[2]])
        return (words("assistant.input", device=device["label"], input=name),
                words("assistant.now-input", device=device["label"], input=name),
                actions.input_fix(asked[1], asked[2]))

    def _notes(self, name, notes, home, *, off=False):
        """The Remote Assistant's notes, as upstairs shows them (its state: 0 never
        shown, 1 shown its welcome, 2 shown before, 3 hidden). After an activity starts:
        the first time, a note to press Help if anything is wrong; back from hidden,
        that the remote has set the system up, then that note; after that, the note and
        whether to hide it. After Off: a welcome the first time, then that every device
        should be off; after that, the same and whether to hide it."""
        words, layout = self.screens.words, self.layout
        state = 0x80 | self.variables.assistant
        title = words("assistant.title", name=name)
        nav = layout.navigation

        def note(text):
            return lambda: (self._paragraphs(words("assistant.heading"), ASSISTANT_Y, 1)
                            + self._paragraphs(text, ASSISTANT_Y + LINE_SPACING, 4))

        def setting(value, ordinal):
            return layout.atoms_object([(value, state), (ordinal, ENTER_MODE)])
        hide = (words("assistant.hide"), {"yes": setting(3, notes["how-to-hide"]),
                                          "no": nav(home)})
        if off:
            alert = words("assistant.all-off")
            sequence = [
                ("welcome", words("assistant.welcome"), {"ok": setting(1, notes["first"])},
                 None),
                ("first", alert, {"ok": nav(home)}, None),
                ("again", alert, {"ok": nav(notes["hide"])}, None)]
        else:
            alert = words("assistant.press-help")
            sequence = [
                ("first", alert, {"ok": nav(home)}, ([(2, state)], [])),
                ("set-up", words("assistant.set-up"), {"ok": nav(notes["first"])},
                 ([(2, state)], [])),
                ("again", alert, {"ok": nav(notes["hide"])}, None)]
        sequence += [("hide",) + hide + (None,),
                     ("how-to-hide", words("assistant.how-to-hide"), {"ok": nav(home)}, None)]
        for _key, text, answers, on_enter in sequence:
            self._answered(title, note(text), answers, on_enter=on_enter)

    def _assistant_after(self, notes, home, *, off=False) -> tuple[int, int]:
        """Which note follows, by the Remote Assistant's state: after an activity, the
        first, set-up or again note, or the activity itself once it is hidden; after
        Off, the welcome or again note, or nothing."""
        layout = self.layout
        if off:
            cases = [(0, notes["welcome"]), (1, notes["welcome"]), (2, notes["again"])]
        else:
            cases = [(0, notes["first"]), (1, notes["set-up"]), (2, notes["again"]),
                     (3, home)]
        group = layout.group([(value, layout.block(_enter(ordinal))) for value, ordinal in cases])
        return ((group << 8) | self.variables.assistant, 0x72)

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
        screens.owned([], [], program, "activity", act["label"], keys=self._swallow())

    def _button_pages(self, act, entries, ordinals, other, other_key, numbers=None):
        """An activity's favourites or its buttons, eight a page; the side strips turn the
        pages, the left softkey goes to ``other`` (the other set's first page) - or, with
        no other set, to the ``numbers`` keypad - and Devices opens the device list. Each
        entry is ``(label, steps, picture)``, or None for a gap: a place left empty, with
        no key and nothing drawn."""
        screens, layout, actions = self.screens, self.layout, self.actions
        frames, frame_width = self._frames(), self.frames.width
        chunks = [entries[at:at + len(BUTTON_POSITIONS)]
                  for at in range(0, len(entries), len(BUTTON_POSITIONS))] or [[]]
        for page_index, chunk in enumerate(chunks):
            rows = []
            for slot, entry in enumerate(chunk):
                if entry is None:
                    continue
                steps = entry[1]
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
            zones = [zone for zone in without_gaps(page_zones(self.geometry, len(chunk)), chunk)
                     if zone["y"] != SOFTKEY_LEFT_ZONE["y"]]
            zones.append(dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F))
            softkeys = ["devices"]
            left = (other, other_key) if other is not None else (
                (numbers, "numbers") if numbers is not None else None)
            if left is not None:
                zones.append(dict(SOFTKEY_LEFT_ZONE, tag=PAGE_ACTIVITIES_KEY & 0x7F))
                rows.append((PAGE_ACTIVITIES_KEY, layout.navigation(left[0]), OBJECT_ATOM))
                softkeys.insert(0, left[1])
            # A favourite's picture says it all; a button's icon has its label over it
            iconed = [bool(entry is not None and len(entry) > 3 and entry[3])
                      for entry in chunk]
            labels = [None if entry is None or (entry[2] is not None and not icon)
                      else entry[0] for entry, icon in zip(chunk, iconed)]
            pictured = [None if entry is None else entry[2] for entry in chunk]
            gaps = [entry is None for entry in chunk]

            def program(picture, prologue, labels=labels, pictured=pictured,
                        softkeys=softkeys, gaps=gaps):
                built = button_page(
                    labels, [None if gap else picture(role or frames[slot])
                             for slot, (role, gap) in enumerate(zip(pictured, gaps))],
                    screens.font,
                    prologue=prologue, attribute=screens.label, frame_width=frame_width)
                return screens.softkeys(built, softkeys)
            # the softkeys it lights: the left one too wherever it has one - Favorites or
            # Commands, or 123
            kind = ("activity-both" if left is not None else "activity") + (
                "-paged" if len(chunks) > 1 else "")
            screens.owned(rows, zones, program, kind, act["label"], (page_index, len(chunks)))

    def _numbers_screen(self, act, ordinals):
        """The activity's number keypad (keypad.py), back to its first page."""
        layout, actions = self.layout, self.actions
        places = []
        for label, steps in act["numbers"]:
            if steps is None:
                places.append((label, None))
            elif len(steps) == 1 and steps[0][0] == "send":
                places.append((label, actions.wrapper(steps[0][1], steps[0][2])))
            else:
                places.append((label, layout.atoms_object(
                    [(structures.IR_OBJECT_KIND_FALLBACK, 0x75)] + actions.atoms(steps))))
        keypad.screen(self.screens, places, title=act["label"], kind="activity",
                      back=ordinals["home"], device_list=self.ordinals.menu[0])

    def activity(self, index: int) -> list[tuple[int, int]]:
        """One activity's screens; the rows of the context that runs it."""
        act, ordinals = self.acts[index], self.ordinals.activities[index]
        layout, actions, variables = self.layout, self.actions, self.variables
        self._start_screen(act)
        both = bool(ordinals["favourites"]) and bool(ordinals["pages"])
        if ordinals["favourites"]:
            self._button_pages(act, [(item["label"], item["steps"], item.get("picture"))
                                     for item in act["favourites"]], ordinals["favourites"],
                               ordinals["pages"][0] if both else None, "commands")
        if ordinals["pages"]:
            drawn = act.get("button_pictures") or []
            self._button_pages(act, [
                None if button is None else
                (*button, drawn[number] if number < len(drawn) else None,
                 bool(number < len(drawn) and drawn[number]))
                for number, button in enumerate(act["buttons"])],
                               ordinals["pages"], ordinals["favourites"][0] if both else None,
                               "favourites", numbers=ordinals["numbers"])

        # Where a start ends: the Remote Assistant's note, by its state.
        finish = self._assistant_after(ordinals["assistant"], ordinals["home"])

        # Help: re-send the power and inputs the activity set, then ask.
        self._help(act["label"], ordinals,
                   [STOP_TIMERS] + actions.direct_power(act["on"], True)
                   + actions.input_writes(act["inputs"]), ordinals["home"],
                   icon=act.get("start_icon"))
        self._notes(act["label"], ordinals["assistant"], ordinals["home"])
        if ordinals["numbers"] is not None:
            self._numbers_screen(act, ordinals)
        numbers = ([row[:2] for row in keypad.opener(layout, ordinals["numbers"])]
                   if ordinals["numbers"] is not None else [])
        opened = {code for code, _target in numbers}

        return [
            (activity_index.ENTER, layout.atoms_object(
                [(ordinals["start"], ENTER_MODE), STOP_TIMERS]
                + actions.power_writes(act["on"], 1) + actions.input_writes(act["inputs"])
                + actions.power_writes(act["off"], 0) + [(index, 0x80 | variables.state)]
                + actions.atoms(act["enter"]) + [finish])),
            (activity_index.LEAVE, layout.atoms_object(
                [STOP_TIMERS] + actions.atoms(act["leave"]))),
            # picked again while running: its inputs again, and back to its screen - by
            # way of the Remote Assistant's note, as upstairs' refresh goes
            (activity_index.REFRESH, layout.atoms_object(
                [STOP_TIMERS] + actions.input_writes(act["inputs"])
                + [(ordinals["home"], ENTER_MODE), finish])),
            (keys.code(keys.HELP), layout.navigation(ordinals["help"])),
        ] + numbers + [(code, actions.key_target(steps))
                       for code, steps in sorted(act["keys"].items()) if code not in opened]

    def activities(self) -> dict[int, list[tuple[int, int]]]:
        """The rest of the Activities menu, then every activity's screens; each
        activity's context rows, by context."""
        for page_index in range(1, len(self.ordinals.activity_menu)):
            self.menu_page(page_index)
        return {self.ordinals.activity_context + index: self.activity(index)
                for index in range(len(self.acts))}

    def off(self) -> list[tuple[int, int]]:
        """Off: nothing running, the Activities menu, and every device off behind it,
        then the Remote Assistant's note; its Help turns them off again and asks after
        each. It has no leave, as no donor's has."""
        layout, ordinals, off = self.layout, self.ordinals, self.all_off
        home = ordinals.home
        after = ([self._assistant_after(ordinals.off["assistant"], home, off=True)]
                 if self.acts else [])
        rows = [
            (activity_index.ENTER, layout.atoms_object(
                [(len(self.acts), 0x80 | self.variables.state), STOP_TIMERS,
                 (home, ENTER_MODE)] + self.actions.power_writes(off["off"], 0) + after)),
            (activity_index.REFRESH, layout.atoms_object([(home, ENTER_MODE)] + after)),
        ]
        if self.acts:
            name = off.get("label") or self.screens.words("activity.power-off")
            rows.append((keys.code(keys.HELP), layout.navigation(ordinals.off_help)))
            self._help(name, ordinals.off,
                       [STOP_TIMERS] + self.actions.direct_power(off["off"], False), home)
            self._notes(name, ordinals.off["assistant"], home, off=True)
        return rows
