"""The Options screens a generated Harmony One draws: Date and Time, Screen Sensitivity.

Every Logitech configuration carries the same settings behind its Options screen, and they
used to be copied from a donor, which also copied the donor's language and the year it was
built in. They are built here instead, from the reading of upstairs' screens recorded in
docs/harmony_one/gspm.md ("The Options screens"): a chain of pickers - year, month, day,
hour, minute, morning or afternoon - each writing one clock variable and opening the next,
and five sensitivity levels that each write the firmware's setting byte and confirm it.

Its words come from the catalogue (catalogue.py), so they follow the project's language. The years offered are the build
year and the ones either side of it, as Logitech's builder offered them. The model has the
carried-screens form the generator already links (generate.py's `_carry_options`): objects,
blocks, timers, switch tables and variables named by index, keypad zones as
``{"zones": ...}`` for idle.attach, and the way back as ``{"exit": "options"}``.
"""
from __future__ import annotations

import calendar

OBJECT, ENTER, REGISTER, SETTING, MODE_STACK = 0x7F, 0x7E, 0x1F, 0x3F, 0x07
BEEP, OVERLAY = 0x75, 0x73
TEST_ACC, TEST_BYTE = 0x70, 0x71          # compare with the accumulator / byte register
DIVIDE, MULTIPLY, ADD = 0x77, 0x78, 0x79  # on the accumulator
PRESS = (0x0FCA, BEEP)                    # every button's click
SILENT = [0xFFFF, MODE_STACK]             # the next variable write runs no transition
SHOW_PAGE = (0xF776, REGISTER)            # queue (accumulator, 0x76): show that page
CURRENT_PAGE = (0xE700, REGISTER)         # the page shown, into the accumulator
LOAD = 0xFB00
# `0x1F` bands that move a value between a variable and the registers (gspm.md)
TO_ACC, FROM_ACC, FROM_BYTE, TO_BYTE, ADD_BYTE = 0xEF, 0xED, 0xEE, 0xF0, 0xFA
DAY_SET, CLOCK_SET, REFRESH = 0xFFF8, 0xFFF9, 0xFFF7   # `0x07`: after a date, a time, a redraw

# The firmware's clock variables.
MINUTE, HOUR, DAY, MONTH, YEAR = 1, 2, 3, 5, 6
# Screen Sensitivity: the setting byte each level writes, as upstairs writes them.
SENSITIVITY = (("very-low", 0xF508), ("low", 0xF50C), ("medium", 0xF500), ("high", 0xF504),
               ("very-high", 0xF507))
SOUNDS_OFF, SOUNDS_ON = 0xF300, 0xF301

# Every word comes from the catalogue (catalogue.py), English unless the project's
# language has a translation; a picker's title is named by its key there.

# Fonts, by attribute: the title and page counter green, button labels, the Back softkey,
# and the confirmation's message and OK.
TITLE_FONT, COUNTER_FONT, LABEL_FONT, BACK_FONT, MESSAGE_FONT, OK_FONT = 2, 7, 8, 6, 0, 1
HIGHLIGHT = 0xEC07                 # the frame drawn round the value the clock holds now

# Geometry: picture positions on screen, touch zones in the panel's raw units (y upward).
GRID = ((6, 38), (89, 38), (6, 92), (89, 92), (6, 146), (89, 146))
ROWS = ((6, 38), (6, 92), (6, 146))
FRAME, ROW_FRAME = (81, 50), (164, 50)
GRID_FRAMES = [f"options/button-frame/{index}" for index in range(6)]
ROW_FRAMES = [f"options/row-frame/{index}" for index in range(3)]
RAW_COLUMNS = ((1257, 1284), (2422, 1134))
RAW_ROWS = (3016, 2144, 1272)
RAW_ROW_HEIGHT = 807
RAW_FULL_WIDTH = 2600
RAW_MIDDLE = 1772
BACK_ZONE = {"x": 1257, "y": 271, "width": 1395, "height": 1001}
OK_ZONE = {"x": 2406, "y": 271, "width": 1150, "height": 1001}
MESSAGE_ZONE = {"x": 1257, "y": 1240, "width": 2791, "height": 2584}
SIDE_ZONES = ({"tag": 0x2E, "x": 765, "y": 1400, "width": 492, "height": 2000},
              {"tag": 0x2F, "x": 3556, "y": 1400, "width": 492, "height": 2000})
FIRST_TAG, SIX_BACK_TAG = 0x30, 0x2B
SWALLOW = (0xA6,)                  # a key every Options screen takes and ignores
PREVIOUS_STRIP, NEXT_STRIP = 0xAE, 0xAF
ENTER_TAG, LEAVE_TAG, DRAWN_TAG, REDRAW_TAG = 0x06, 0x07, 0x29, 0x2D
TITLE_XY, BACK_XY, OK_XY = (6, 4), (31, 202), (124, 201)
MESSAGE_Y = (105, 117)
LABEL_DROP, ROW_LABEL_DROP = 20, 19
PAGE_TOTAL_XY, PAGES_X, PAGE_SLASH_X, COUNTER_Y = (23, 18), 35, 18, 18
PAGES_GAP = 3
SCREEN_WIDTH = 176
REFRESH_TICKS = 4


class _Model:
    def __init__(self, label):
        self.label = label             # (text, attribute, room) -> (glyph hex, width)
        self.objects, self.blocks, self.modes = [], [], []
        self.templates, self.groups, self.timers = [], [], []
        self.variables = []

    def object(self, atoms) -> list:
        self.objects.append([list(atom) for atom in atoms])
        return [{"object": len(self.objects) - 1}, OBJECT]

    def block(self, items) -> int:
        self.blocks.append(items)
        return len(self.blocks) - 1

    def variable(self, limit: int) -> dict:
        self.variables.append({"initial": 0, "limit": limit, "transitions": []})
        return {"variable": len(self.variables) - 1}

    def template(self, zones) -> int:
        self.templates.append(zones)
        return len(self.templates) - 1

    def mode(self) -> int:
        self.modes.append(None)
        return len(self.modes) - 1

    def text(self, text, attribute, x, y, room=SCREEN_WIDTH, centre=None) -> list[dict]:
        if centre is None:
            room = min(room, SCREEN_WIDTH - x)    # text placed from x stops at the edge
        glyphs, width = self.label(text, attribute, room)
        if centre is not None:
            x = max(0, centre[0] + (centre[1] - width) // 2)
        return [{"opcode": "attribute", "value": attribute},
                {"opcode": "inline_text", "x": x, "y": y, "glyphs": glyphs}]


def _register(band: int, variable) -> list:
    return [{"register": band, "variable": variable}, REGISTER]


def _test(opcode: int, kind: int, variable) -> list:
    return [{"test": kind, "variable": variable}, opcode]


def _write(variable, value: int) -> list:
    return [value, {"write": variable}]


def _zone_rect(column: int | None, row: int, tag: int, middle: bool = False) -> dict:
    x, width = (RAW_MIDDLE, RAW_COLUMNS[0][1]) if middle else (
        (RAW_COLUMNS[0][0], RAW_FULL_WIDTH) if column is None else RAW_COLUMNS[column])
    return {"tag": tag, "x": x, "y": RAW_ROWS[row], "width": width, "height": RAW_ROW_HEIGHT}


def _highlight(x: int, y: int, width: int) -> list[dict]:
    """The frame round a button: four two-pixel bars just outside it."""
    height = FRAME[1]
    bars = ((x - 2, y - 2, 2, height + 2), (x + width, y - 2, 2, height + 4),
            (x - 2, y - 2, width + 2, 2), (x - 2, y + height, width + 2, 2))
    return [{"opcode": "rectangle", "x": bx, "y": by, "width": bw, "height": bh,
             "color": HIGHLIGHT} for bx, by, bw, bh in bars] + [{"opcode": "end"}]


def build(label, year: int, words=None) -> dict:
    """The Options model for a configuration built in ``year``.

    ``label(text, attribute, room)`` returns a line of text as glyph codes (hex) and its
    width in pixels, in the font the image draws ``attribute`` with; ``words`` is the
    language (catalogue.Words), English when not given.
    """
    from .catalogue import ENGLISH

    words = ENGLISH if words is None else words
    m = _Model(label)
    pm_flag = m.variable(1)
    page_scratch = m.variable(0xFEFD)
    sounds = m.variable(1)

    refresh = len(m.timers)
    m.timers.append({"flags": 1, "duration": REFRESH_TICKS, "action": None})
    status = m.object([(3, OVERLAY), (0, OVERLAY)])
    m.timers[refresh]["action"] = m.object([(3, OVERLAY), (0, OVERLAY),
                                            ({"timer": refresh, "band": 0xEB}, REGISTER)])
    redraw = m.object([(1, OVERLAY), (3, OVERLAY), (2, OVERLAY)])
    start_refresh = [{"timer": refresh, "band": 0xEB}, REGISTER]
    stop_refresh = [{"timer": refresh, "band": 0xEA}, REGISTER]

    grid_group = len(m.groups)
    m.groups.append({"lead": 2, "cases": [[i, m.block(_highlight(x, y, FRAME[0]))]
                                          for i, (x, y) in enumerate(GRID)], "ranges": []})
    row_group = len(m.groups)
    m.groups.append({"lead": 2, "cases": [[i, m.block(_highlight(x, y, ROW_FRAME[0]))]
                                          for i, (x, y) in enumerate(ROWS)], "ranges": []})
    sounds_group = len(m.groups)
    m.groups.append({"lead": 2, "ranges": [], "cases": [
        [0, m.block([{"opcode": "atom", "category": OBJECT, "operand": m.object([
            PRESS, (SOUNDS_OFF, SETTING), _write(sounds, 1), (REFRESH, MODE_STACK)])[0]},
            {"opcode": "end"}])],
        [1, m.block([{"opcode": "atom", "category": OBJECT, "operand": m.object([
            PRESS, (SOUNDS_ON, SETTING), _write(sounds, 0), (REFRESH, MODE_STACK)])[0]},
            {"opcode": "end"}])]]})

    def prologue(title, total):
        items = m.text(words(f"options.{title}"), TITLE_FONT, *TITLE_XY)
        items.append({"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": "backdrop"}})
        items.append({"opcode": "atom", "operand": 2, "category": OVERLAY})
        if total > 1:
            items += m.text(str(total), COUNTER_FONT, *PAGE_TOTAL_XY)
            # after the total, never closer than the donors' own column
            _glyphs, width = m.label(str(total), COUNTER_FONT, SCREEN_WIDTH)
            after = max(PAGES_X, PAGE_TOTAL_XY[0] + width + PAGES_GAP)
            items += m.text(words.plural("pages", total), COUNTER_FONT, after,
                            COUNTER_Y)[1:]
        items.append({"opcode": "atom", "operand": status[0], "category": OBJECT})
        items += m.text(words(f"options.{title}"), TITLE_FONT, *TITLE_XY)
        return m.block(items + [{"opcode": "return"}, {"opcode": "end"}])

    def page_program(head, places, labels, number, total, back=True):
        """A page: its buttons' frames and labels, Back, and its number when paged."""
        items = [{"opcode": "call", "target": {"block": head}}]
        for (x, y, width), (frame, text) in zip(places, labels):
            items.append({"opcode": "bitmap", "x": x, "y": y, "target": {"picture": frame}})
            drop = ROW_LABEL_DROP if width == ROW_FRAME[0] else LABEL_DROP
            items += m.text(text, LABEL_FONT, x, y + drop, width - 8, centre=(x, width))
        if back:
            items += m.text(words("options.back"), BACK_FONT, *BACK_XY)
        if total > 1:
            glyphs, width = m.label(str(number + 1), COUNTER_FONT, SCREEN_WIDTH)
            items += [{"opcode": "attribute", "value": COUNTER_FONT},
                      {"opcode": "inline_text", "x": max(0, PAGE_SLASH_X - width),
                       "y": COUNTER_Y,
                       "glyphs": glyphs}]
            items += m.text("/", COUNTER_FONT, PAGE_SLASH_X, COUNTER_Y)[1:]
        return m.block(items + [{"opcode": "end"}])

    def zones(chosen, on):
        return [{"zones": list(chosen), "on": on}, OBJECT]

    def opens_on_value(variable, offset, per):
        """Show the page holding the value the clock has now."""
        steps = [_register(TO_ACC, variable)]
        if offset:
            steps.append([-offset & 0xFFFF, ADD])
        return steps + [[per, DIVIDE], list(SHOW_PAGE), [REFRESH, MODE_STACK]]

    def highlight(variable, offset, per, group):
        """On each page drawn: when it is the value's page, frame the value's button."""
        def value():
            return [_register(TO_ACC, variable)] + ([[-offset & 0xFFFF, ADD]] if offset else [])
        inner = m.object([[per, DIVIDE], [per, MULTIPLY],
                          m.object([_test(TEST_ACC, 7, page_scratch), [0, 0]]),
                          [LOAD, REGISTER], _register(TO_BYTE, page_scratch),
                          _register(FROM_BYTE, page_scratch),
                          [{"group": group, "variable": page_scratch}, 0x72]])
        middle = m.object(value() + [_register(FROM_ACC, page_scratch)] + value() + [inner])
        return m.object([list(CURRENT_PAGE), _register(FROM_ACC, page_scratch)] + value()
                        + [[per, DIVIDE], m.object([_test(TEST_ACC, 0, page_scratch), middle])])

    def picker(index, title, variable, values, layout, choose, back_to, offset=0,
               prepare=()):
        """A screen of buttons, one per value, ``layout`` "grid" (six a page) or "rows"
        (three). ``choose(value)`` is what a button does."""
        per = 6 if layout == "grid" else 3
        pages = [values[at:at + per] for at in range(0, len(values), per)]
        head = prologue(title, len(pages))
        group = grid_group if layout == "grid" else row_group
        records = []
        for number, chunk in enumerate(pages):
            if layout == "grid":
                places = [(x, y, FRAME[0]) for x, y in GRID[:len(chunk)]]
                frames = GRID_FRAMES
                zones_ = [_zone_rect(i % 2, i // 2, FIRST_TAG + i) for i in range(len(chunk))]
            else:
                places = [(x, y, ROW_FRAME[0]) for x, y in ROWS[:len(chunk)]]
                frames = ROW_FRAMES
                zones_ = [_zone_rect(None, i, FIRST_TAG + i) for i in range(len(chunk))]
            back_tag = SIX_BACK_TAG if len(chunk) == 6 else FIRST_TAG + len(chunk)
            template = m.template(zones_ + [dict(BACK_ZONE, tag=back_tag)] + list(SIDE_ZONES))
            rows = [[0x80 | FIRST_TAG + i, *m.object(choose(value))]
                    for i, (value, _text) in enumerate(chunk)]
            rows.append([0x80 | back_tag, *m.object([PRESS, back_to()])])
            program = page_program(head, places, [(frames[i], text)
                                                  for i, (_v, text) in enumerate(chunk)],
                                   number, len(pages))
            records.append({"template": template, "rows": rows, "program": program})
        paged = len(pages) > 1
        lit = [zones((1, 3), True), zones((5,), True)] if paged else [zones((5,), True)]
        enter = m.object([start_refresh, m.object(list(prepare) + opens_on_value(
            variable, offset, per))] + lit)
        leave = m.object([stop_refresh, zones((1, 3), False), zones((5,), False)])
        header = ([] if paged else [[NEXT_STRIP, 0, 0], [PREVIOUS_STRIP, 0, 0]]) + [
            [ENTER_TAG, *enter], [LEAVE_TAG, *leave],
            [DRAWN_TAG, *highlight(variable, offset, per, group)],
            *[[key, 0, 0] for key in SWALLOW], [REDRAW_TAG, *redraw]]
        m.modes[index] = {"flag": 1, "header": header, "pages": records}

    def go(index):
        return [{"mode": index}, ENTER]

    def silent(variable, value):
        return m.object([SILENT, _write(variable, value)])

    exit_ = [{"exit": "options"}, ENTER]
    years = (year - 1, year, year + 1)
    leap_years = [y for y in years if calendar.isleap(y)]
    year_mode, month_normal, month_leap = m.mode(), m.mode(), m.mode()
    day_modes = {days: m.mode() for days in (31, 30, 29, 28)}
    hour_mode, minute_mode, ampm_mode = m.mode(), m.mode(), m.mode()
    sense_mode = m.mode()
    confirm_modes = {name: m.mode() for name, _value in SENSITIVITY}

    def guarded(test, step):
        return m.object([test, step])

    def back_to_month():
        """The Month screen for the year chosen: the leap one when it is a leap year."""
        if not leap_years:
            return go(month_normal)
        leap = leap_years[0] - 2000
        return m.object([[LOAD | leap, REGISTER], guarded(_test(TEST_BYTE, 0, YEAR),
                                                          go(month_leap)),
                         [LOAD | leap, REGISTER], guarded(_test(TEST_BYTE, 1, YEAR),
                                                          go(month_normal))])

    def back_to_day():
        """The Day screen for the month chosen."""
        steps = []
        for month in range(12):
            if month == 1:
                target = m.object([back_feb()])
            else:
                target = go(day_modes[calendar.monthrange(2001, month + 1)[1]])
            steps += [[LOAD | month, REGISTER], guarded(_test(TEST_BYTE, 0, MONTH), target)]
        return m.object(steps)

    def back_feb():
        if not leap_years:
            return go(day_modes[28])
        leap = leap_years[0] - 2000
        return m.object([[LOAD | leap, REGISTER], guarded(_test(TEST_BYTE, 0, YEAR),
                                                          go(day_modes[29])),
                         [LOAD | leap, REGISTER], guarded(_test(TEST_BYTE, 1, YEAR),
                                                          go(day_modes[28]))])

    picker(year_mode, "year", YEAR, [(y, str(y)) for y in years], "rows",
           lambda y: [PRESS, silent(YEAR, y - 2000),
                      go(month_leap if calendar.isleap(y) else month_normal)],
           lambda: exit_, offset=years[0] - 2000)
    for index, leap in ((month_normal, False), (month_leap, True)):
        def month_choice(month, leap=leap):
            days = calendar.monthrange(2004 if leap else 2001, month + 1)[1]
            return [PRESS, silent(MONTH, month), go(day_modes[days])]
        picker(index, "month", MONTH,
               [(n, words(f"options.month.{n + 1}")) for n in range(12)], "grid",
               month_choice, lambda: go(year_mode))
    for days, index in day_modes.items():
        picker(index, "day", DAY, [(d - 1, str(d)) for d in range(1, days + 1)], "grid",
               lambda d: [PRESS, silent(DAY, d), (DAY_SET, MODE_STACK), go(hour_mode)],
               back_to_month)
    # The clock's hour runs 0-23; the picker shows twelve and the last screen adds the
    # afternoon. Entering it folds an afternoon hour back first, as upstairs does.
    fold = [[LOAD | 12, REGISTER], guarded(_test(TEST_BYTE, 3, HOUR), m.object([
        _register(TO_BYTE, HOUR), [(ADD_BYTE << 8) | (-12 & 0xFF), REGISTER],
        _register(FROM_BYTE, HOUR)]))]
    picker(hour_mode, "hour", HOUR, [(h, f"{h or 12}:00") for h in range(12)], "grid",
           lambda h: [PRESS, silent(HOUR, h), go(minute_mode)], back_to_day, prepare=fold)
    picker(minute_mode, "minute", MINUTE, [(n, f"{n:02d}") for n in range(60)], "grid",
           lambda n: [PRESS, silent(MINUTE, n), go(ampm_mode)], lambda: go(hour_mode))

    # Morning or afternoon: the afternoon adds twelve to the hour; both set the clock.
    head = prologue("time-of-day", 1)
    template = m.template([_zone_rect(0, 0, FIRST_TAG), _zone_rect(1, 0, FIRST_TAG + 1),
                           dict(BACK_ZONE, tag=FIRST_TAG + 2)] + list(SIDE_ZONES))
    am = m.object([PRESS, silent(pm_flag, 0), (CLOCK_SET, MODE_STACK), exit_])
    pm = m.object([PRESS, m.object([[LOAD | 12, REGISTER], guarded(
        _test(TEST_BYTE, 2, HOUR), m.object([_register(TO_BYTE, HOUR),
                                              [(ADD_BYTE << 8) | 12, REGISTER],
                                              _register(FROM_BYTE, HOUR)]))]),
                   silent(pm_flag, 1), (CLOCK_SET, MODE_STACK), exit_])
    back = m.object([PRESS, go(minute_mode)])
    program = page_program(head, [(x, y, FRAME[0]) for x, y in GRID[:2]],
                           [(GRID_FRAMES[0], words("options.am")),
                            (GRID_FRAMES[1], words("options.pm"))],
                           0, 1)
    m.modes[ampm_mode] = {"flag": 0, "header": [
        [NEXT_STRIP, 0, 0], [PREVIOUS_STRIP, 0, 0],
        [ENTER_TAG, *m.object([start_refresh, zones((5,), True)])],
        [LEAVE_TAG, *m.object([stop_refresh, zones((1, 3), False), zones((5,), False)])],
        [REDRAW_TAG, *redraw]],
        "pages": [{"template": template, "program": program, "rows": [
            [0x80 | FIRST_TAG, *am], [0x80 | FIRST_TAG + 1, *pm],
            [0x80 | FIRST_TAG + 2, *back]]}]}

    # Screen Sensitivity: two, one in the middle, two; each level writes the firmware's
    # setting byte and says what it is set to.
    head = prologue("screen-sensitivity", 1)
    places = [GRID[0], GRID[1], (48, 92), GRID[4], GRID[5]]
    frames = [GRID_FRAMES[0], GRID_FRAMES[1], GRID_FRAMES[2], GRID_FRAMES[4], GRID_FRAMES[5]]
    zones_ = [_zone_rect(0, 0, FIRST_TAG), _zone_rect(1, 0, FIRST_TAG + 1),
              _zone_rect(None, 1, FIRST_TAG + 2, middle=True),
              _zone_rect(0, 2, FIRST_TAG + 3), _zone_rect(1, 2, FIRST_TAG + 4)]
    template = m.template(zones_ + [dict(BACK_ZONE, tag=FIRST_TAG + 5)] + list(SIDE_ZONES))
    rows = [[0x80 | FIRST_TAG + i, *m.object([PRESS, (value, SETTING),
                                               go(confirm_modes[name])])]
            for i, (name, value) in enumerate(SENSITIVITY)]
    rows.append([0x80 | FIRST_TAG + 5, *m.object([PRESS, exit_])])
    program = page_program(head, [(x, y, FRAME[0]) for x, y in places],
                           [(frames[i], words(f"options.sensitivity.{name}"))
                            for i, (name, _v) in enumerate(SENSITIVITY)],
                           0, 1)
    m.modes[sense_mode] = {"flag": 0, "header": [
        [NEXT_STRIP, 0, 0], [PREVIOUS_STRIP, 0, 0],
        [ENTER_TAG, *m.object([start_refresh, zones((5,), True)])],
        [LEAVE_TAG, *m.object([stop_refresh, zones((1, 3), False), zones((5,), False)])],
        *[[key, 0, 0] for key in SWALLOW], [REDRAW_TAG, *redraw]],
        "pages": [{"template": template, "program": program, "rows": rows}]}

    confirm_template = m.template([dict(MESSAGE_ZONE, tag=FIRST_TAG),
                                   dict(OK_ZONE, tag=FIRST_TAG + 1)] + list(SIDE_ZONES))
    for name, index in confirm_modes.items():
        items = [{"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": "backdrop"}},
                 {"opcode": "atom", "operand": 2, "category": OVERLAY},
                 {"opcode": "atom", "operand": status[0], "category": OBJECT}]
        items += m.text(words("options.sensitivity-set"), MESSAGE_FONT, 0, MESSAGE_Y[0],
                        centre=(0, SCREEN_WIDTH))
        items += m.text(words(f"options.sensitivity.{name}"), MESSAGE_FONT, 0, MESSAGE_Y[1],
                        centre=(0, SCREEN_WIDTH))
        items += m.text(words("options.ok"), OK_FONT, *OK_XY)
        program = m.block(items + [{"opcode": "end"}])
        m.modes[index] = {"flag": 0, "header": [
            [NEXT_STRIP, 0, 0], [PREVIOUS_STRIP, 0, 0],
            [ENTER_TAG, *m.object([start_refresh, zones((7,), True)])],
            [LEAVE_TAG, *m.object([stop_refresh, zones((7,), False)])],
            *[[key, 0, 0] for key in SWALLOW], [REDRAW_TAG, *redraw]],
            "pages": [{"template": confirm_template, "program": program,
                       "rows": [[0x80 | FIRST_TAG + 1, *m.object([PRESS, exit_])]]}]}

    return {
        "schema": "afterglow-harmony-one-carried-screens/1",
        "entries": {"date-and-time": year_mode, "screen-sensitivity": sense_mode},
        "sounds": {"switch": {"group": sounds_group, "variable": sounds}},
        "modes": m.modes, "templates": m.templates, "blocks": m.blocks,
        "objects": m.objects, "timers": m.timers, "groups": m.groups,
        "variables": m.variables, "row_frames": list(ROW_FRAMES),
    }
