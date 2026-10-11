"""The screens a generated Harmony One owns, as every donor draws one: a fragment with the
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
    PAGE_SLASH_XY, PAGE_TOTAL_XY, PAGES_GAP, SCREEN_WIDTH, SOFTKEYS, TITLE_FONTS, TITLE_ROOM,
    TITLE_XY, fit_label, line_ys, measure, softkey_label)
from .scaffold import ENTER
from .structures import DRAW_OVERLAY, OBJECT_ATOM


class Screens:
    """Reserve and draw owned screens in ``layout``.

    ``fonts`` are the image's fonts by attribute, ``label`` the attribute labels are drawn
    in, ``handlers(kind)`` the enter, leave and redraw rows a screen of that kind gets, and
    ``status_object`` the object that draws status overlays 3 and 0, when the image has
    them. ``current`` is ``(state variable, activity count)`` when activities run, so the
    left softkey can read "Current Activity"."""

    def __init__(self, layout, *, fonts, words, roles, label, softkey_fonts, handlers,
                 status_object=None, current=None):
        self.layout = layout
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
              on_enter=None):
        """Reserve a mode this image owns: the platform's handlers, then a fragment
        drawing the backdrop, then the page program, which calls it and draws the rest.
        ``build(picture, prologue)`` returns the page program's instructions, and
        ``kind`` names which keypad zones the screen lights (idle.SCREEN_ZONES) and the
        fonts its ``title`` is drawn in. ``page`` is `(index, total)` for one page of a
        screen that has several, which are numbered as the donors number theirs.
        ``keys`` are rows for the physical keys, bound in the mode's own list, and
        ``on_enter`` is `(before, after)`, instructions run either side of the
        platform's own enter handler when the screen is entered."""
        fonts = self.fonts
        backdrop = "backdrop" in self.roles
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
            return ((heading() if titled else [])
                    + [{"opcode": "bitmap", "x": 0, "y": 0, "target": picture("backdrop")}]
                    + status[:1] + total + status[1:] + (heading() if titled else [])
                    + [{"opcode": "return"}, {"opcode": "end"}])

        page_build = build
        if numbered:
            def page_build(picture, prologue):
                # each page ends with its own number, right-aligned to the slash
                program = build(picture, prologue)
                return program[:-1] + [
                    {"opcode": "attribute", "value": counter_font},
                    counter_text(str(page[0] + 1), PAGE_SLASH_XY[0], right=True),
                    counter_text("/", PAGE_SLASH_XY[0])] + program[-1:]

        builds = ([fragment] if backdrop else []) + [page_build]
        layout = self.layout
        template = zones if isinstance(zones, int) else layout.template(zones)
        sizes = layout.program_sizes(builds, 0 if backdrop else None)
        handlers = self.handlers(kind)
        if on_enter is not None:
            before, after = on_enter
            handlers = [(tag, layout.atoms_object(list(before) + [(operand, category)]
                                                  + list(after)), OBJECT_ATOM)
                        if tag == ENTER else (tag, operand, category)
                        for tag, operand, category in handlers]
        [placed] = layout.mode(structures.key_register(handlers + list(keys)), 0,
                               [(template, rows, sizes)])
        prologue = placed[0] if backdrop else None
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
