"""The screens a generated Harmony 800 owns, as every donor draws one: a fragment with the
title, the backdrop and the status bar, then the page program, its softkeys and its page
counter, and the platform's handlers in its list.

The features (hub.py, activity_screens.py, options_screens.py) say what a screen shows and
binds; this says how a screen of theirs is reserved and drawn.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from . import structures
from .pages import (
    EMPTY_MESSAGE_WIDTH, EMPTY_MESSAGE_Y, LINE_SPACING, MENU_LINE_OFFSETS, PAGE_COUNTER_Y,
    PAGE_SLASH_XY, PAGE_TOTAL_XY, PAGES_GAP, SCREEN_WIDTH, SOFTKEY_BAR_TOP, SOFTKEYS,
    TITLE_FONTS, TITLE_ROOM, TITLE_XY, fit_label, line_ys, measure, softkey_label)
from .scaffold import ENTER
from .structures import DRAW_OVERLAY, OBJECT_ATOM


# The 800: a screen this backend builds is drawn on the 800's own display (geometry.py),
# and its backdrop - the One's is black - fills the whole display. It is a picture, as
# every Logitech image's is: the drawing VM's rectangle (opcode 01) writes its pixels
# without selecting the LCD (FUN_08010dc4 toggles only D/C), so after the first picture
# has released the panel's chip select a rectangle draws nothing (gsgd.md, "Drawing").
BACKDROP = "backdrop"

# Over it, a screen of the 800's own draws its title bar and softkey bar, as Logitech's 800
# screens have them (pages.py); a scaffold without them draws the backdrop alone.
CHROME = (("chrome/header", 0, 0), ("chrome/softkeys", 0, SOFTKEY_BAR_TOP))


def backdrop(picture) -> dict:
    """The full-screen backdrop, drawn first: what clears the display."""
    return {"opcode": "bitmap", "x": 0, "y": 0, "target": picture(BACKDROP), "native": True}


def chrome(picture, roles) -> list[dict]:
    """The title and softkey bars, for the ones of them the scaffold has."""
    return [{"opcode": "bitmap", "x": x, "y": y, "target": picture(role), "native": True}
            for role, x, y in CHROME if role in roles]


def native(build):
    """``build`` with everything it draws placed on the 800's display as it is."""
    def drawn(picture, prologue):
        return [dict(item, native=True) for item in build(picture, prologue)]
    return drawn


class Screens:
    """Reserve and draw owned screens in ``layout``.

    ``fonts`` are the image's fonts by attribute, ``label`` the attribute labels are drawn
    in, ``handlers(kind)`` the enter, leave and redraw rows a screen of that kind gets, and
    ``status_object`` the object that draws status overlays 3 and 0, when the image has
    them. ``current`` is ``(state variable, activity count)`` when activities run, so the
    left softkey can read "Current Activity". ``sizes`` are the pictures' sizes, by role."""

    def __init__(self, layout, *, fonts, words, roles, label, softkey_fonts, handlers,
                 status_object=None, current=None, sizes=None):
        self.layout = layout
        # each picture's width and height, for a screen that places one by its size
        self.sizes = sizes or {}
        self.fonts = fonts
        self.words = words
        self.roles = roles
        self.label = label
        self.font = fonts[label] if fonts else None
        self.softkey_fonts = softkey_fonts
        self.handlers = handlers
        self.status_object = status_object
        self.current = current
        # Made once: a page program is built again after the blocks are laid out, and a
        # block made then would never be given an address.
        self._current_labels: dict[str, int] = {}

    def owned(self, rows, zones, build, kind=None, title=None, page=None, keys=(),
              on_enter=None, bare=False):
        """Reserve a mode this image owns: the platform's handlers, then a fragment
        drawing the backdrop, then the page program, which calls it and draws the rest.
        ``build(picture, prologue)`` returns the page program's instructions, and
        ``kind`` names which keypad zones the screen lights (idle.SCREEN_ZONES) and the
        fonts its ``title`` is drawn in. ``page`` is `(index, total)` for one page of a
        screen that has several, which are numbered as the donors number theirs.
        ``keys`` are rows for the physical keys, bound in the mode's own list, and
        ``on_enter`` is `(before, after)`, instructions run either side of the
        platform's own enter handler when the screen is entered. A ``bare`` screen has no
        fragment: its page program draws everything there is."""
        fonts = self.fonts
        has_backdrop = BACKDROP in self.roles and not bare
        title_font, counter_font = TITLE_FONTS.get(kind, (None, None))
        titled = (title is not None and title_font is not None and fonts is not None
                  and max(title_font, counter_font) < len(fonts))
        numbered = titled and page is not None and page[1] > 1

        def heading():
            [glyphs] = fit_label(title, fonts[title_font], TITLE_ROOM, lines=1)
            return [{"opcode": "attribute", "value": title_font},
                    {"opcode": "inline_text", "x": TITLE_XY[0], "y": TITLE_XY[1],
                     "glyphs": glyphs.hex()}]

        def counter_text(text, x, right=False):
            [glyphs] = fit_label(text, fonts[counter_font], SCREEN_WIDTH, lines=1)
            widths, _codes = measure(fonts[counter_font])
            if right:
                x = max(0, x - sum(widths[code] for code in glyphs))
            return {"opcode": "inline_text", "x": x, "y": PAGE_COUNTER_Y,
                    "glyphs": glyphs.hex()}

        def fragment(picture, _prologue):
            # The donors' prologue: the title, the backdrop, the status bar - an atom
            # queues `(2, 0x73)`, overlay 2, and another the object drawing overlays 3
            # and 0, without which the clock and battery waited for the refresh timer -
            # then a paged screen's total, and the title again over everything.
            status = [] if self.status_object is None else [
                {"opcode": "atom", "operand": 2, "category": DRAW_OVERLAY},
                {"opcode": "atom", "operand": self.status_object, "category": OBJECT_ATOM}]
            total = []
            if numbered:
                widths, _codes = measure(fonts[counter_font])
                [digits] = fit_label(str(page[1]), fonts[counter_font], SCREEN_WIDTH, 1)
                after = PAGE_TOTAL_XY[0] + sum(widths[code] for code in digits) + PAGES_GAP
                total = [{"opcode": "attribute", "value": counter_font},
                         counter_text(str(page[1]), PAGE_TOTAL_XY[0]),
                         counter_text(self.words.plural("pages", page[1]), after)]
            # the One's backdrop is black: on the 800 it covers the whole display
            return ((heading() if titled else [])
                    + [backdrop(picture)] + chrome(picture, self.roles)
                    + status[:1] + total + status[1:] + (heading() if titled else [])
                    + [{"opcode": "return"}, {"opcode": "end"}])

        page_build = build
        if numbered:
            def page_build(picture, prologue):
                # each page ends with its own number, right-aligned to the slash - before
                # a switch drawn last, whose cases end the program, or it is never drawn
                program = build(picture, prologue)
                at = -2 if len(program) > 1 and program[-2]["opcode"] == "switch" else -1
                return program[:at] + [
                    {"opcode": "attribute", "value": counter_font},
                    counter_text(str(page[0] + 1), PAGE_SLASH_XY[0], right=True),
                    counter_text("/", PAGE_SLASH_XY[0])] + program[at:]

        builds = [native(item) for item in ([fragment] if has_backdrop else []) + [page_build]]
        layout = self.layout
        template = zones if isinstance(zones, int) else layout.template(zones)
        sizes = layout.program_sizes(builds, 0 if has_backdrop else None)
        handlers = self.handlers(kind)
        if on_enter is not None:
            before, after = on_enter
            handlers = [(tag, layout.atoms_object(list(before) + [(operand, category)]
                                                  + list(after)), OBJECT_ATOM)
                        if tag == ENTER else (tag, operand, category)
                        for tag, operand, category in handlers]
        [placed] = layout.mode(structures.key_register(handlers + list(keys)), 0,
                               [(template, rows, sizes)])
        prologue = placed[0] if has_backdrop else None
        for at, item in zip(placed, builds):
            layout.pending_programs.append((at, item, prologue))

    def softkeys(self, program, names):
        """End a page program with its softkey labels, each in its own font."""
        labels = []
        for name in names:
            attribute = self.softkey_fonts[name]
            labels += softkey_label(self.words(f"softkey.{name}"), self.fonts[attribute],
                                    attribute, SOFTKEYS[name])
        return program[:-1] + labels + [{"opcode": "end"}]

    def softkeys_with_current(self, program, others):
        """Softkeys whose left one reads "Current Activity" while an activity runs and
        "Activities" when none does: a switch on the counter, drawn last so each case
        can end the program."""
        state_variable, count = self.current
        program = self.softkeys(program, others)[:-1]
        attribute = self.softkey_fonts["activities"]
        blocks = self._current_labels
        for name in ("activities", "current-activity"):
            if name not in blocks:
                blocks[name] = self.layout.block(
                    softkey_label(self.words(f"softkey.{name}"), self.fonts[attribute],
                                  attribute, SOFTKEYS["activities"]) + [{"opcode": "end"}])
        return program + [{"opcode": "switch", "selector": state_variable,
                           "cases": [(count, blocks["activities"])],
                           "ranges": ([(0, count - 1, blocks["current-activity"])]
                                      if count else [])},
                          {"opcode": "end"}]

    def message(self, text):
        """A line in the label font, centred on the screen: what an empty list shows."""
        widths, _codes = measure(self.font)
        out = [{"opcode": "attribute", "value": self.label}]
        lines = fit_label(text, self.font, EMPTY_MESSAGE_WIDTH)
        for glyphs, y in zip(lines, line_ys(EMPTY_MESSAGE_Y, len(lines), MENU_LINE_OFFSETS)):
            width = sum(widths[code] for code in glyphs)
            out.append({"opcode": "inline_text", "x": (SCREEN_WIDTH - width) // 2,
                        "y": y, "glyphs": glyphs.hex()})
        return out

    def lines(self, text, attribute, top, room=EMPTY_MESSAGE_WIDTH, lines=2):
        """``text`` centred on the screen in ``attribute``, its lines 12 apart from
        ``top`` down."""
        widths, _codes = measure(self.fonts[attribute])
        out = [{"opcode": "attribute", "value": attribute}]
        for number, glyphs in enumerate(fit_label(text, self.fonts[attribute], room, lines)):
            width = sum(widths[code] for code in glyphs)
            out.append({"opcode": "inline_text", "x": (SCREEN_WIDTH - width) // 2,
                        "y": top + LINE_SPACING * number, "glyphs": glyphs.hex()})
        return out
