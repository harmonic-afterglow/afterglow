"""Options as a generated Harmony One shows it, and the Tutorial behind it.

With activities Options has Logitech's two pages - the Remote Assistant, the Tutorial and
Date and Time, then Screen Sounds and Screen Sensitivity - and without them the one page
of the last three. The screens it opens are carried (options.py, carried.py).

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from . import keys, structures
from .pages import (
    EMPTY_MESSAGE_WIDTH, HELP_FONT, LINE_SPACING, MENU_ACTIVITIES_KEY, MENU_FRAME_XY,
    MENU_LABEL_XY, MENU_ROW_KEYS, OPTIONS_FONT, OPTIONS_FRAME_WIDTH, OPTIONS_LABEL_ROOM,
    PAGE_DEVICES_KEY, SCREEN_WIDTH, SIDE_NEXT_KEY, SIDE_PREV_KEY, SOFTKEY_RIGHT_ZONE,
    fit_label, measure, menu_page)
from .scaffold import menu_template
from .structures import ENTER_MODE, OBJECT_ATOM, object_body

# The Tutorial: each page's words, and what moves on from it - the key it teaches.
TUTORIAL = (("tutorial.welcome", "next"), ("tutorial.activities", "touch"),
            ("tutorial.switching", "activities"), ("tutorial.pages", "next"),
            ("tutorial.help", "help"), ("tutorial.assistant", "next"),
            ("tutorial.off", "off"), ("tutorial.done", "exit"))
TUTORIAL_TOP, TUTORIAL_LINES = 40, 9


class Options:
    """Options in ``screens``, its entries opening the ``carried`` screens
    (carried.Carried). ``flow`` is the activities' (activity_screens.Flow), or None when
    the image has none, in which case Options has its one page."""

    def __init__(self, screens, ordinals, carried, *, frames, flow=None, assistant=None):
        self.screens = screens
        self.layout = screens.layout
        self.ordinals = ordinals
        self.carried = carried
        self.frames = frames
        self.flow = flow
        self.assistant = assistant
        self.pages: list[list[tuple]] = []

    def carry(self):
        """Options' first page, then the screens carried behind it - Date and Time and
        Screen Sensitivity - whose pictures it draws."""
        screens, layout, carried, ordinals = self.screens, self.layout, self.carried, self.ordinals
        words, model = screens.words, carried.model
        for block in model["blocks"]:
            for item in block:
                if item["opcode"] == "bitmap":
                    layout.drawn.add(item["target"]["picture"])
        layout.drawn.update(model["row_frames"])

        # A row opens a screen, or flips a switch whose label is read off its own flag.
        sounds = model["sounds"]["switch"]
        sounds_row = ("switch", carried.variable(sounds["variable"]),
                      {0: words("options.sounds-off"), 1: words("options.sounds-on")},
                      layout.object(object_body([(carried.operand(sounds), 0x72)])))
        date_row = ("open", words("options.date-and-time"),
                    layout.navigation(ordinals.carried + model["entries"]["date-and-time"]))
        sensitivity_row = ("open", words("options.screen-sensitivity"),
                           layout.navigation(ordinals.carried
                                             + model["entries"]["screen-sensitivity"]))
        if ordinals.options_more is None:
            self.pages.append([date_row, sounds_row, sensitivity_row])
        else:
            redraw = {"opcode": "atom", "operand": ordinals.options, "category": ENTER_MODE}
            toggle = layout.group([
                (value, layout.block([{"opcode": "atom", "operand": 1 - value,
                                       "category": 0x80 | self.assistant}, redraw,
                                      {"opcode": "end"}])) for value in (0, 1)])
            assistant_row = ("switch", self.assistant,
                             {0: words("options.assistant-on"),
                              1: words("options.assistant-off")},
                             layout.object(object_body([
                                 (structures.IR_OBJECT_KIND_FALLBACK, 0x75),
                                 ((toggle << 8) | self.assistant, 0x72)])))
            tutorial_row = ("open", words("options.tutorial"),
                            layout.navigation(ordinals.tutorial[0]))
            self.pages.extend([[assistant_row, tutorial_row, date_row],
                               [sounds_row, sensitivity_row]])
        self.page(0)
        carried.place_modes(layout)

    def page(self, page_index: int):
        """One page of Options: up to three rows on its row frames, each opening a
        screen or flipping a switch whose label is read off its variable - drawn last,
        since each case ends the program. The side strips turn the pages."""
        screens, layout, ordinals = self.screens, self.layout, self.ordinals
        entries = self.pages[page_index]
        total = len(self.pages)
        pages = [ordinals.options, ordinals.options_more][:total]
        rows = [(MENU_ROW_KEYS[row], entry[-1], OBJECT_ATOM)
                for row, entry in enumerate(entries)]
        rows.append((MENU_ACTIVITIES_KEY, layout.navigation(ordinals.home), OBJECT_ATOM))
        if total > 1:
            other = layout.navigation(pages[(page_index + 1) % total])
            rows += [(SIDE_PREV_KEY, other, OBJECT_ATOM), (SIDE_NEXT_KEY, other, OBJECT_ATOM)]
        row_font = screens.fonts[OPTIONS_FONT]
        widths, _codes = measure(row_font)
        row_frames = self.carried.model["row_frames"]

        def centred(text, row):
            [glyphs] = fit_label(text, row_font, OPTIONS_LABEL_ROOM, lines=1)
            width = sum(widths[code] for code in glyphs)
            return {"opcode": "inline_text",
                    "x": MENU_FRAME_XY[row][0] + (OPTIONS_FRAME_WIDTH - width) // 2,
                    "y": MENU_LABEL_XY[row][1], "glyphs": glyphs.hex()}
        switch = None
        for row, entry in enumerate(entries):
            if entry[0] == "switch":
                switch = {"opcode": "switch", "selector": entry[1], "ranges": [],
                          "cases": [(value, layout.block([
                              {"opcode": "attribute", "value": OPTIONS_FONT},
                              centred(text, row), {"opcode": "end"}]))
                              for value, text in sorted(entry[2].items())]}

        def program(picture, prologue):
            out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            for row, _entry in enumerate(entries):
                out.append({"opcode": "bitmap", "x": MENU_FRAME_XY[row][0],
                            "y": MENU_FRAME_XY[row][1], "target": picture(row_frames[row])})
            out.append({"opcode": "attribute", "value": OPTIONS_FONT})
            out += [centred(entry[1], row) for row, entry in enumerate(entries)
                    if entry[0] == "open"]
            out = screens.softkeys(out + [{"opcode": "end"}], ["activities"])[:-1]
            return out + ([switch] if switch else []) + [{"opcode": "end"}]
        screens.owned(rows, menu_template(), program, "options", screens.words("options.title"),
                      (page_index, total) if total > 1 else None)

    def tutorial(self):
        """The Tutorial, in its own words: a page per thing to learn, each moved on by
        the key it teaches - bound in the page's own list, so pressing Help or Off here
        teaches rather than does - the left arrow back, Exit back to what is running."""
        screens, layout, ordinals = self.screens, self.layout, self.ordinals
        pages = ordinals.tutorial
        exit_row = (PAGE_DEVICES_KEY, self.flow.back_to_current(), OBJECT_ATOM)
        zones = [zone for zone in menu_template() if zone["tag"] in (0x2E, 0x2F, 0x32)]
        zones.append(dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F))
        first = self.flow.acts[0]
        row_frame = ("activity/row-frame" if "activity/row-frame" in screens.roles
                     else "row-frame")
        widths, _codes = measure(screens.fonts[HELP_FONT])
        flow_keys = (keys.ACTIVITIES, keys.HELP, keys.OFF)

        def paragraphs(text):
            out, y = [{"opcode": "attribute", "value": HELP_FONT}], TUTORIAL_TOP
            for paragraph in text.split("\n"):
                for glyphs in fit_label(paragraph, screens.fonts[HELP_FONT],
                                        EMPTY_MESSAGE_WIDTH, TUTORIAL_LINES):
                    width = sum(widths[code] for code in glyphs)
                    out.append({"opcode": "inline_text", "x": (SCREEN_WIDTH - width) // 2,
                                "y": y, "glyphs": glyphs.hex()})
                    y += LINE_SPACING
                y += LINE_SPACING // 2
            return out

        for number, ((key, advance), ordinal) in enumerate(zip(TUTORIAL, pages)):
            following = pages[number + 1] if number + 1 < len(TUTORIAL) else None
            onward = layout.navigation(following) if following is not None else None
            text = (screens.words(key, activity=first["label"])
                    if key == "tutorial.activities" else screens.words(key))
            rows, mode_keys = [exit_row], []
            if number:
                rows.append((SIDE_PREV_KEY, layout.navigation(pages[number - 1]), OBJECT_ATOM))
            if advance == "next":
                rows.append((SIDE_NEXT_KEY, onward, OBJECT_ATOM))
            elif advance == "touch":
                rows.append((MENU_ROW_KEYS[2], onward, OBJECT_ATOM))
            elif advance in ("activities", "help", "off"):
                scan = {"activities": keys.ACTIVITIES, "help": keys.HELP, "off": keys.OFF}
                mode_keys.append((keys.code(scan[advance]), onward, OBJECT_ATOM))
            # the keys the flow owns do nothing else while the Tutorial is shown
            mode_keys += [(keys.code(scan), 0, 0) for scan in flow_keys
                          if keys.code(scan) not in {row[0] for row in mode_keys}]

            def program(picture, prologue, text=text, advance=advance):
                out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
                if advance == "touch":
                    # the first activity's own row, to touch
                    out += menu_page([first["label"]], picture(row_frame),
                                     [first.get("icon") and picture(first["icon"])],
                                     screens.font, attribute=screens.label,
                                     label_room=self.frames.row_label_room, rows=(2,))[:-1]
                out += paragraphs(text)
                return screens.softkeys(out + [{"opcode": "end"}], ["exit"])
            screens.owned(rows, zones, program, "tutorial", screens.words("tutorial.title"),
                          (number, len(TUTORIAL)), keys=mode_keys)
