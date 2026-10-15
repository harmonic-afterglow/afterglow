"""Options as a generated Harmony 800 shows it, and the Tutorial behind it.

With activities Options has Logitech's two pages - the Remote Assistant, the Tutorial and
Date and Time, then Screen Sounds and Screen Sensitivity - and without them the one page
of the last three. The screens it opens are carried (options.py, carried.py).

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from . import keys, structures
from . import geometry
from .pages import (
    COLUMN_XS, EDGE, FRAME_HEIGHT, FRAME_WIDTH, HEADER_HEIGHT, LABEL_BASELINE, LABEL_INSET,
    MENU_ACTIVITIES_KEY, MENU_FRAME_XY, MENU_LABEL_LEFT, MENU_LABEL_MAX, MENU_LABEL_XY,
    MENU_ROW_KEYS, OPTIONS_FONT, OPTIONS_FRAME_WIDTH, OPTIONS_LABEL_ROOM, PAGE_DEVICES_KEY,
    ROW_FRAME_WIDTH, ROW_ICON_AT, SCREEN_WIDTH, SIDE_NEXT_KEY, SIDE_PREV_KEY,
    SOFTKEY_BAR_TOP, SOFTKEY_RIGHT_ZONE, TEXT_HEIGHT, fit_label, measure)
from .scaffold import menu_template
from .structures import ENTER_MODE, OBJECT_ATOM, object_body

# The Tutorial, page by page, as Logitech's has it, laid out on the 800's display: under
# the title bar, the page's words, and at the foot, above the softkey bar, what it shows -
# the scaffold's `tutorial/<n>` picture of the remote (art/tutorial/), and for some pages
# the remote's own activity row or buttons with their labels: (key, attribute). What
# moves on: the keys it teaches, and touching the page - or, on the page that asks for
# it, the activity row. Exit, bottom right, is on every page.
TUTORIAL = (
    {"picture": 1, "keys": ("next",), "touch": "page"},
    {"picture": 2, "keys": ("next",), "touch": "page"},
    {"picture": 3, "keys": ("activities",), "touch": "page"},
    {"picture": None, "keys": (), "touch": "row", "row": ("tutorial.watch-tv", 5)},
    {"picture": 5, "keys": ("next",), "touch": "page"},
    {"picture": None, "keys": ("next",), "touch": "page",
     "buttons": (("tutorial.display", 8), ("tutorial.aspect", 8))},
    {"picture": 3, "keys": ("next", "activities"), "touch": "page"},
    {"picture": 8, "keys": ("help",), "touch": "page"},
    {"picture": 9, "keys": ("next",), "touch": "page", "question": ("tutorial.is-tv-on", 14),
     "buttons": (("tutorial.yes", 8), ("tutorial.no", 8))},
    {"picture": 10, "keys": ("off",), "touch": "page"},
    {"picture": 11, "keys": (), "touch": None},
)
TUTORIAL_FONT, TUTORIAL_LEFT, TUTORIAL_LINE, TUTORIAL_PARAGRAPH = 14, 8, 16, 4
TUTORIAL_TOP = HEADER_HEIGHT + 6
TUTORIAL_BOTTOM = SOFTKEY_BAR_TOP - 4         # the foot of what a page shows
TUTORIAL_GAP = 6                              # between the parts of what it shows
# The activity row page 4 teaches: the activities' row frame and the Watch TV icon on it,
# composed by the build (generate.py).
TUTORIAL_ROW_FRAME, TUTORIAL_ROW_ICON = "activity/row-frame", "tutorial/row-icon"


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
            block[:] = [item for item in block if item["opcode"] != "bitmap"
                        or not item["target"]["picture"].startswith("chrome/")
                        or item["target"]["picture"] in screens.roles]
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
        """The Tutorial, as Logitech's: each page's words and its picture of the remote,
        moved on by the key it teaches - bound in the page's own list, so pressing Help or
        Off there teaches rather than does - or by touching the page; the left arrow back,
        Exit back to what is running."""
        screens, layout, ordinals = self.screens, self.layout, self.ordinals
        pages = ordinals.tutorial
        exit_row = (PAGE_DEVICES_KEY, self.flow.back_to_current(), OBJECT_ATOM)
        sides = [zone for zone in menu_template() if zone["tag"] in (0x2E, 0x2F)]
        exit_zone = dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F)
        taught = {"next": SIDE_NEXT_KEY, "activities": keys.code(keys.ACTIVITIES),
                  "help": keys.code(keys.HELP), "off": keys.code(keys.OFF)}

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
            shown = self._tutorial_figure(page)
            zones = list(sides) + [exit_zone]
            if page["touch"] == "page":
                zones.append(geometry.pixels(0, HEADER_HEIGHT, SCREEN_WIDTH,
                                             SOFTKEY_BAR_TOP - HEADER_HEIGHT, 0x30))
            elif page["touch"] == "row":
                zones.append(geometry.pixels(EDGE, shown["row"], ROW_FRAME_WIDTH,
                                             FRAME_HEIGHT, 0x30))
            if page["touch"]:
                rows.append((0xB0, onward, OBJECT_ATOM))
            text = screens.words(f"tutorial.{number + 1}")

            def program(picture, prologue, page=page, text=text, shown=shown):
                out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
                out += self._tutorial_words(page, text, shown["top"])
                out += self._tutorial_shown(page, shown, picture)
                return screens.softkeys(out + [{"opcode": "end"}], ["exit"])
            screens.owned(rows, zones, program, "tutorial", screens.words("tutorial.title"),
                          (number, len(TUTORIAL)), keys=mode_keys)

    def _tutorial_figure(self, page) -> dict:
        """Where what a page shows goes, stacked up from the foot of the page: the
        picture, the question, and the row or the buttons. ``top`` is the top of it all."""
        sizes = self.screens.sizes
        parts = []
        role = None if page["picture"] is None else f"tutorial/{page['picture']}"
        if role is not None:
            parts.append(("picture", sizes.get(role, (0, 0))[1]))
        if page.get("question"):
            parts.append(("question", TEXT_HEIGHT))
        if page.get("buttons"):
            parts.append(("buttons", FRAME_HEIGHT))
        if page.get("row"):
            parts.append(("row", FRAME_HEIGHT))
        out, y = {"role": role}, TUTORIAL_BOTTOM
        for name, height in reversed(parts):
            y -= height
            out[name] = y
            y -= TUTORIAL_GAP
        out["top"] = y
        return out

    def _tutorial_words(self, page, text, bottom) -> list[dict]:
        """A page's words from under the title bar; lines that would reach what the page
        shows are left out. The first page's words welcome on their own: the One's
        "Welcome!" above them said it twice."""
        screens = self.screens
        out, y = [], TUTORIAL_TOP
        font = screens.fonts[TUTORIAL_FONT]
        out.append({"opcode": "attribute", "value": TUTORIAL_FONT})
        for paragraph in text.split("\n"):
            for glyphs in fit_label(paragraph, font, SCREEN_WIDTH - 2 * TUTORIAL_LEFT, 12):
                if y + TUTORIAL_LINE > bottom:
                    return out
                out.append({"opcode": "inline_text", "x": TUTORIAL_LEFT, "y": y,
                            "glyphs": glyphs.hex()})
                y += TUTORIAL_LINE
            y += TUTORIAL_PARAGRAPH
        return out

    def _tutorial_shown(self, page, shown, picture) -> list[dict]:
        """What a page shows: its picture centred, the question centred under it, and the
        remote's own row or buttons with their labels."""
        screens = self.screens
        out = []

        def centred(key, attribute, left, width, y):
            label_font = screens.fonts[attribute]
            [glyphs] = fit_label(screens.words(key), label_font, width - LABEL_INSET, 1)
            widths, _codes = measure(label_font)
            text_width = sum(widths[code] for code in glyphs)
            return [{"opcode": "attribute", "value": attribute},
                    {"opcode": "inline_text", "x": left + (width - text_width) // 2, "y": y,
                     "glyphs": glyphs.hex()}]
        if shown["role"] is not None and "picture" in shown:
            width = screens.sizes.get(shown["role"], (0, 0))[0]
            out.append({"opcode": "bitmap", "x": (SCREEN_WIDTH - width) // 2,
                        "y": shown["picture"], "target": picture(shown["role"])})
        if page.get("question"):
            out += centred(*page["question"], 0, SCREEN_WIDTH, shown["question"])
        for (key, attribute), x in zip(page.get("buttons", ()), COLUMN_XS):
            out.append({"opcode": "bitmap", "x": x, "y": shown["buttons"],
                        "target": picture("activity/button-frame/0")})
            out += centred(key, attribute, x, FRAME_WIDTH, shown["buttons"] + LABEL_BASELINE)
        if page.get("row"):
            y = shown["row"]
            out.append({"opcode": "bitmap", "x": EDGE, "y": y,
                        "target": picture(TUTORIAL_ROW_FRAME)})
            if TUTORIAL_ROW_ICON in screens.roles:
                out.append({"opcode": "bitmap", "x": EDGE + ROW_ICON_AT[0],
                            "y": y + ROW_ICON_AT[1], "target": picture(TUTORIAL_ROW_ICON)})
            out += centred(*page["row"], MENU_LABEL_LEFT, MENU_LABEL_MAX, y + LABEL_BASELINE)
        return out
