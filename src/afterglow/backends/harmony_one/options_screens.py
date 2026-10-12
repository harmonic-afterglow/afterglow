"""Options as a generated Harmony One shows it, and the Tutorial behind it.

With activities Options has Logitech's two pages - the Remote Assistant, the Tutorial and
Date and Time, then Screen Sounds and Screen Sensitivity - and without them the one page
of the last three. The screens it opens are carried (options.py, carried.py).

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from . import keys, structures
from .pages import (
    MENU_ACTIVITIES_KEY, MENU_FRAME_XY, MENU_LABEL_XY, MENU_ROW_KEYS, OPTIONS_FONT,
    OPTIONS_FRAME_WIDTH, OPTIONS_LABEL_ROOM, PAGE_DEVICES_KEY, SCREEN_WIDTH, SIDE_NEXT_KEY,
    SIDE_PREV_KEY, SOFTKEY_RIGHT_ZONE, TITLE_FONTS, fit_label, measure)
from .scaffold import menu_template
from .structures import ENTER_MODE, OBJECT_ATOM, object_body

# The Tutorial, page by page, as every donor has it: Logitech's picture of the remote
# (the scaffold's `tutorial/<n>`) and where it is drawn, where the words start, what moves
# on - keys, and the touch zones (raw panel coordinates, as upstairs' templates have
# them) that do the same - and the words drawn over the picture: (key, attribute, x, y,
# whether x is the label's centre). Exit, bottom right, is on every page.
_TEXT = (1257, 2241, 2299, 2018)             # the words' half of the screen, for most pages
TUTORIAL = (
    {"picture": (65, 137), "top": 56, "keys": ("next",),
     "touch": ((2041, 1288, 745, 936), (1257, 3937, 2299, 323), (1257, 2225, 2061, 1695),
               (1257, 1272, 2791, 3165)),
     "labels": (("tutorial.welcome", 16, 10, 13, False),)},
    {"picture": (7, 106), "top": 35, "keys": ("next",), "touch": ((1257, 2548, 2299, 1711),)},
    {"picture": (3, 118), "top": 25, "keys": ("activities",),
     "touch": ((1257, 2354, 2299, 1905),)},
    {"picture": (7, 135), "top": 33, "keys": (),
     "touch": ((1257, 885, 2568, 1372), (1257, 1498, 2600, 807), (1257, 2273, 2299, 1986)),
     "labels": (("tutorial.watch-tv", 5, 69, 151, False),)},
    {"picture": (30, 123), "top": 32, "keys": ("next",), "touch": ((1257, 2290, 2299, 1970),)},
    {"picture": (7, 133), "top": 43, "keys": ("next",), "touch": ((1257, 2128, 2299, 2131),),
     "labels": (("tutorial.display", 8, 47, 149, True), ("tutorial.aspect", 8, 128, 149, True))},
    {"picture": (3, 118), "top": 39, "keys": ("next", "activities"), "touch": (_TEXT,)},
    {"picture": (8, 115), "top": 45, "keys": ("help",), "touch": (_TEXT,)},
    {"picture": (21, 100), "top": 32, "keys": ("next",), "touch": ((1257, 2823, 2299, 1437),),
     "labels": (("tutorial.is-tv-on", 14, 88, 135, True), ("tutorial.yes", 8, 51, 168, True),
                ("tutorial.no", 8, 121, 168, True))},
    {"picture": (7, 15), "top": 107, "keys": ("off",), "touch": ((1257, 1127, 2299, 2051),)},
    {"picture": (68, 148), "top": 34, "keys": (), "touch": ()},
)
TUTORIAL_FONT, TUTORIAL_LEFT, TUTORIAL_LINE = 14, 10, 11
# Where the page counter goes: top right, where no page draws anything.
TUTORIAL_COUNTER_RIGHT, TUTORIAL_COUNTER_Y = 170, 2


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
            # As upstairs' row: shown or not yet shown, it hides the Remote Assistant
            # (state 3); hidden, it brings it back as just set up (state 1).
            redraw = {"opcode": "atom", "operand": ordinals.options, "category": ENTER_MODE}
            toggle = layout.group([
                (value, layout.block([{"opcode": "atom", "operand": 1 if value == 3 else 3,
                                       "category": 0x80 | self.assistant}, redraw,
                                      {"opcode": "end"}])) for value in range(4)])
            assistant_row = ("switch", self.assistant,
                             {value: words("options.assistant-on" if value == 3
                                           else "options.assistant-off")
                              for value in range(4)},
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
        """The Tutorial, as Logitech's: on a black screen, each page's picture of the
        remote and its words, moved on by the key it teaches - bound in the page's own
        list, so pressing Help or Off there teaches rather than does - or by touching the
        page; the left arrow back, Exit back to what is running."""
        screens, layout, ordinals = self.screens, self.layout, self.ordinals
        pages = ordinals.tutorial
        exit_row = (PAGE_DEVICES_KEY, self.flow.back_to_current(), OBJECT_ATOM)
        sides = [zone for zone in menu_template() if zone["tag"] in (0x2E, 0x2F)]
        exit_zone = dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F)
        font = screens.fonts[TUTORIAL_FONT]
        taught = {"next": SIDE_NEXT_KEY, "activities": keys.code(keys.ACTIVITIES),
                  "help": keys.code(keys.HELP), "off": keys.code(keys.OFF)}
        counter_font = TITLE_FONTS["tutorial"][1]

        for number, (page, ordinal) in enumerate(zip(TUTORIAL, pages)):
            following = pages[number + 1] if number + 1 < len(TUTORIAL) else None
            onward = layout.navigation(following) if following is not None else None
            rows = [exit_row]
            if number:
                rows.append((SIDE_PREV_KEY, layout.navigation(pages[number - 1]), OBJECT_ATOM))
            mode_keys = []
            for name in page["keys"]:
                if taught[name] == SIDE_NEXT_KEY:
                    rows.append((SIDE_NEXT_KEY, onward, OBJECT_ATOM))
                else:
                    mode_keys.append((taught[name], onward, OBJECT_ATOM))
            zones = list(sides) + [exit_zone]
            for tag, (x, y, width, height) in enumerate(page["touch"], start=0x30):
                zones.append({"tag": tag, "x": x, "y": y, "width": width, "height": height})
                rows.append((0x80 | tag, onward, OBJECT_ATOM))
            text = screens.words(f"tutorial.{number + 1}")

            def program(picture, _prologue, number=number, page=page, text=text):
                out = [{"opcode": "rectangle", "x": 0, "y": 0, "width": SCREEN_WIDTH,
                        "height": 220, "color": 0},
                       {"opcode": "bitmap", "x": page["picture"][0], "y": page["picture"][1],
                        "target": picture(f"tutorial/{number + 1}")}]
                for key, attribute, x, y, centred in page.get("labels", ()):
                    label_font = screens.fonts[attribute]
                    [glyphs] = fit_label(screens.words(key), label_font, SCREEN_WIDTH - 12, 1)
                    widths, _codes = measure(label_font)
                    width = sum(widths[code] for code in glyphs)
                    out += [{"opcode": "attribute", "value": attribute},
                            {"opcode": "inline_text", "x": max(0, x - width // 2) if centred
                             else x, "y": y, "glyphs": glyphs.hex()}]
                out.append({"opcode": "attribute", "value": TUTORIAL_FONT})
                y = page["top"]
                widths, _codes = measure(font)
                for paragraph in text.split("\n"):
                    for glyphs in fit_label(paragraph, font, SCREEN_WIDTH - 2 * TUTORIAL_LEFT,
                                            12):
                        out.append({"opcode": "inline_text", "x": TUTORIAL_LEFT, "y": y,
                                    "glyphs": glyphs.hex()})
                        y += TUTORIAL_LINE
                    y += TUTORIAL_LINE
                # the page counter, kept from ours: "3/11", top right
                counter = screens.fonts[counter_font]
                [glyphs] = fit_label(f"{number + 1}/{len(TUTORIAL)}", counter, SCREEN_WIDTH, 1)
                widths, _codes = measure(counter)
                out += [{"opcode": "attribute", "value": counter_font},
                        {"opcode": "inline_text",
                         "x": TUTORIAL_COUNTER_RIGHT - sum(widths[code] for code in glyphs),
                         "y": TUTORIAL_COUNTER_Y, "glyphs": glyphs.hex()}]
                return screens.softkeys(out + [{"opcode": "end"}], ["exit"])
            screens.owned(rows, zones, program, "tutorial", keys=mode_keys, bare=True)
