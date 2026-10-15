"""Where a page the One's layout draws goes on the 800's screen, and where its touch zones go.

The 800's display is 240 x 320, with the One's arrangement around it - a paging strip beside
each side and a pair of softkey bars below, all off the display. The screens this backend
builds itself are laid out for it (pages.py) and marked ``native``. Everything else - the
firmware's notices, the screens carried behind Options, the charging screens - is the
One's, drawn on the One's 176 x 220: it is placed at ONE_ORIGIN, the middle of the display,
and its touch zones are carried from the One's touch units, through the One's pixels, into
the 800's. The status bar is the One's too, and sits at the display's top right
(STATUS_ORIGIN).

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

SCREEN = (240, 320)
ONE_SCREEN = (176, 220)
ONE_ORIGIN = ((SCREEN[0] - ONE_SCREEN[0]) // 2, (SCREEN[1] - ONE_SCREEN[1]) // 2)
STATUS_ORIGIN = (SCREEN[0] - ONE_SCREEN[0], 0)
PAGE_ORIGIN = ONE_ORIGIN

# The One's touch units against its pixels, fitted to the button and menu zones every One
# image carries (x 1257 at pixel 6, 2422 at 89; y 3823 at pixel 38, rows 872 apart for 54
# pixels), y measured upwards.
ONE_X0, ONE_X_PER_PIXEL = 1173.0, 14.04
ONE_Y_TOP, ONE_Y_PER_PIXEL = 3823.0 + 38 * 16.15, 16.15

# The 800's display in its touch units: the content zone of every factory template
# (x 250-1340, y 230-2020), y measured upwards; the strips lie outside it.
X0, X_PER_PIXEL = 250.0, 1090 / SCREEN[0]
Y_TOP, Y_PER_PIXEL = 2020.0, 1790 / SCREEN[1]

# The top of the One's softkey bars' zones (y 271 to 1272 in every One template).
ONE_SOFTKEY_TOP = 1300

# The paging strips: the One's tags 0x2E and 0x2F, and Logitech's own 800 strips.
STRIPS = {0x2E: {"x": 0, "width": 240, "y": 505, "height": 1011},
          0x2F: {"x": 1356, "width": 240, "y": 505, "height": 1011}}


def place(instruction: dict) -> tuple[int, int]:
    """Where an instruction's ``x`` and ``y`` land on the display."""
    if instruction.get("native"):
        return instruction["x"], instruction["y"]
    origin = instruction.get("origin") or ONE_ORIGIN
    return instruction["x"] + origin[0], instruction["y"] + origin[1]


def pixels(x: int, y: int, width: int, height: int, tag: int) -> dict:
    """A native zone over a rectangle of the display's pixels, in the 800's touch units."""
    left, right = X0 + x * X_PER_PIXEL, X0 + (x + width) * X_PER_PIXEL
    top, bottom = Y_TOP - y * Y_PER_PIXEL, Y_TOP - (y + height) * Y_PER_PIXEL
    return {"x": round(left), "width": round(right - left), "y": max(0, round(bottom)),
            "height": round(top - max(0.0, bottom)), "tag": tag, "native": True}


def touch_zone(zone: dict) -> dict:
    """A One zone ``{x, width, y, height, tag}`` in the 800's touch units; a zone marked
    ``native`` is in them already."""
    if zone.get("native"):
        return {key: zone[key] for key in ("x", "width", "y", "height", "tag")}
    if zone["tag"] in STRIPS:
        return dict(STRIPS[zone["tag"]], tag=zone["tag"])
    if zone["y"] + zone["height"] <= ONE_SOFTKEY_TOP:
        # the One's softkey bars: the 800's, left or right by where the zone's middle is
        from .pages import SOFTKEY_LEFT_ZONE, SOFTKEY_RIGHT_ZONE
        left = zone["x"] + zone["width"] / 2 < ONE_X0 + ONE_SCREEN[0] / 2 * ONE_X_PER_PIXEL
        return {key: value for key, value in (SOFTKEY_LEFT_ZONE if left else
                                              SOFTKEY_RIGHT_ZONE).items()} | {"tag": zone["tag"]}
    left = (zone["x"] - ONE_X0) / ONE_X_PER_PIXEL + PAGE_ORIGIN[0]
    right = (zone["x"] + zone["width"] - ONE_X0) / ONE_X_PER_PIXEL + PAGE_ORIGIN[0]
    top = (ONE_Y_TOP - (zone["y"] + zone["height"])) / ONE_Y_PER_PIXEL + PAGE_ORIGIN[1]
    bottom = (ONE_Y_TOP - zone["y"]) / ONE_Y_PER_PIXEL + PAGE_ORIGIN[1]
    raw_left = max(0, round(X0 + max(0.0, left) * X_PER_PIXEL))
    raw_right = round(X0 + min(SCREEN[0], right) * X_PER_PIXEL)
    raw_top = round(Y_TOP - max(0.0, top) * Y_PER_PIXEL)
    raw_bottom = max(0, round(Y_TOP - bottom * Y_PER_PIXEL))
    return {"x": raw_left, "width": max(1, raw_right - raw_left), "y": raw_bottom,
            "height": max(1, raw_top - raw_bottom), "tag": zone["tag"]}


# The 800's display and the touch panel beyond it, in its own units, for screens that place
# zones there themselves (key_test.py): below the display is where the softkey bars are.
DISPLAY = {"x": 250, "width": 1090, "y": 230, "height": 1790}
BELOW_LEFT = {"x": 250, "width": 540, "y": 0, "height": 225}
BELOW_RIGHT = {"x": 800, "width": 540, "y": 0, "height": 225}
