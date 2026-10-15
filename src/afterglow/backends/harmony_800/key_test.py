"""The key test: a screen that names the code of whatever is pressed on the remote.

The 800's hard keys, keyboard and touch areas beyond the display all arrive as list tags
(gsgd.md, "Lists"), and which code each key sends has not been read anywhere. This screen
answers every code a list can hold besides its handlers, each by a screen showing that
code, so a remote's owner can press every key and say what each one is. Touching the
display goes back to Activities; the strips beside it and the panel below it, where the
softkey bars are, show their own codes.

Before it comes the light test: a page for each of the 800's seven LEDs, each lighting
only its own LED (every other dark) and saying which it is, so the owner can say which
light each channel is (gsgd.md, "Lights"). Touching the display moves on; after the last
LED the key test begins. Waking the remote lights them all again, as it always does.

It is reached from the device list: its right strip, on the last page, opens it.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

from . import geometry, gspm, structures
from .screens import backdrop, native
from .structures import OBJECT_ATOM

# A list holds 255 rows. Every code a hard key or touch zone can send, 0x00-0x7E, and as
# much of the keyboard's (0x4xx) as is left after the platform's handlers and the way out.
EXIT_CODE = 0x7F
HARD = tuple(range(0x00, EXIT_CODE))
KEYBOARD_ROOM = 255 - len(HARD) - 1 - 24
KEYBOARD = tuple(0xC400 + code for code in range(KEYBOARD_ROOM))
CODES = HARD + KEYBOARD
TITLE_ATTRIBUTE = 2


LEDS = tuple(range(7))
LED_LEVEL = 4


def screen_count() -> int:
    return len(LEDS) + 1 + len(CODES)


def page_lines(screens, lines, title="keytest.title"):
    """A test page: the backdrop, its title, and its lines of text."""
    def build(picture, _prologue):
        out = [backdrop(picture)]
        out += screens.lines(screens.words(title), TITLE_ATTRIBUTE, 8)
        top = 70
        for text in lines:
            out += screens.lines(text, screens.label, top)
            top += 28
        return out + [{"opcode": "end"}]
    return native(build)


def _shown(code: int) -> str:
    return f"{structures.tag(0x80 | code if code < 0x80 else code):04X}"


def place(screens, layout, ordinals, home: int) -> None:
    """The light test's pages, the prompt, then a screen per code, at the ordinals planned
    for them."""
    from .idle import light
    light_pages = ordinals.key_test[:len(LEDS)]
    first = ordinals.key_test[len(LEDS)]
    results = dict(zip(CODES, ordinals.key_test[len(LEDS) + 1:]))
    handlers = screens.handlers("devices")
    rows = [(0x80 | EXIT_CODE, layout.navigation(home), OBJECT_ATOM)]
    rows += [(0x80 | code if code < 0x80 else code, layout.navigation(ordinal), OBJECT_ATOM)
             for code, ordinal in results.items()]
    if len(handlers) + len(rows) > 0xFF:
        raise ValueError(f"the key test's list would hold {len(handlers) + len(rows)} rows")
    zones = [dict(geometry.DISPLAY, tag=EXIT_CODE, native=True)]
    zones += [dict(strip, tag=tag, native=True) for tag, strip in geometry.STRIPS.items()]
    zones += [dict(geometry.BELOW_LEFT, tag=0x2B, native=True),
              dict(geometry.BELOW_RIGHT, tag=0x2C, native=True)]
    template = layout.template(zones)

    def page(lines):
        def build(picture, _prologue):
            out = [backdrop(picture)]
            out += screens.lines(screens.words("keytest.title"), TITLE_ATTRIBUTE, 8)
            top = 70
            for text in lines:
                out += screens.lines(text, screens.label, top)
                top += 28
            return out + [{"opcode": "end"}]
        return native(build)

    def reserve(header, build):
        sizes = layout.program_sizes([build], None)
        [placed] = layout.mode(header, 0, [(template, [], sizes)])
        layout.pending_programs.append((placed[0], build, None))

    # The light test: each page's enter handler runs the platform's, then lights its LED
    # alone; touching the display opens the next page, and the last one the prompt.
    if len(layout.trailers) != light_pages[0]:
        raise AssertionError("the light test is not where its screens were numbered")
    light_template = layout.template([dict(geometry.DISPLAY, tag=EXIT_CODE, native=True)])
    for index, led in enumerate(LEDS):
        enter = [row for row in handlers if row[0] == 0x06]
        others = [row for row in handlers if row[0] != 0x06]
        atoms = [(enter[0][1], enter[0][2])] if enter else []
        atoms += [tuple(light(c, LED_LEVEL if c == led else 0)) for c in LEDS]
        following = light_pages[index + 1] if index + 1 < len(LEDS) else first
        rows_ = [(0x06, layout.object(structures.object_body(atoms)), OBJECT_ATOM)] + others
        rows_ += [(0x80 | EXIT_CODE, layout.navigation(following), OBJECT_ATOM)]
        sizes = layout.program_sizes([page_lines(screens, [
            screens.words("lighttest.lit", led=str(led)), screens.words("lighttest.next")],
            "lighttest.title")], None)
        build = page_lines(screens, [screens.words("lighttest.lit", led=str(led)),
                                     screens.words("lighttest.next")], "lighttest.title")
        [placed] = layout.mode(structures.key_register(rows_), 0, [(light_template, [], sizes)])
        layout.pending_programs.append((placed[0], build, None))
    if len(layout.trailers) != first:
        raise AssertionError("the key test is not where its screens were numbered")
    reserve(structures.key_register(handlers + rows),
            page([screens.words("keytest.prompt"), screens.words("keytest.back")]))
    trailer = layout.trailers[-1]
    shared = int.from_bytes(layout.out[trailer + 1:trailer + 4], "little") - gspm.BASE
    for code in CODES:
        reserve(shared, page([screens.words("keytest.pressed", code=_shown(code)),
                              screens.words("keytest.again"), screens.words("keytest.back")]))
