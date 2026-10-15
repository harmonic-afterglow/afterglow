#!/usr/bin/env python3
"""Draw the Harmony 800's own look as vector artwork, and export it into its scaffold.

    python3 tools/harmony_800_art.py
    python3 tools/harmony_800_art.py --remote-showing SCREEN.png OUT.svg

The 800's scaffold began as the One's pictures, widened (harmony_800_fit_artwork.py). The
800 looks different: the Getting Started Guide and the product photographs show a grey
title bar - a lighter band behind the title, a darker one behind the page counter - rows
and buttons coloured above a horizon and black below it, inside a thin edge - blue for the
activities, green for Options and orange for the devices, as their softkeys are -
and a grey softkey bar at the foot of the display, split in two. This draws that look as
SVG (scaffolds/harmony-800/art/), one file per picture, and renders each at the size the
remote draws it (backends/harmony_800/pages.py) into images/.

The status bar's pictures - battery, charge, the IR indicator and the patch the clock is
drawn on - sit on the title bar, and the display has no blending, so each one carries the
slice of the title bar it covers: its SVG draws the whole bar, shifted, and the icon on it.

`--remote-showing` writes the remote drawing alone, self-contained, with a 240 x 320
capture of the 800's screen in its display.

Rendering needs `rsvg-convert` (librsvg). Colours are reduced to the display's RGB565
here, so the loader reports nothing to change; every picture is opaque.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import imaging  # noqa: E402
from afterglow.backends.harmony_800 import bitmap, pages  # noqa: E402

SCAFFOLD = ROOT / "src/afterglow/scaffolds/harmony-800"
ART = SCAFFOLD / "art"

SCREEN_WIDTH = pages.SCREEN_WIDTH
HEADER_HEIGHT = pages.HEADER_HEIGHT
BAR_TOP = pages.SOFTKEY_BAR_TOP
BUTTON = (pages.FRAME_WIDTH, pages.FRAME_HEIGHT)
ROW = (pages.ROW_FRAME_WIDTH, pages.FRAME_HEIGHT)
# Where the status bar draws each of its pictures on the 800 (the One's places, moved to
# the display's top right: geometry.STATUS_ORIGIN), and their sizes.
STATUS_X = SCREEN_WIDTH - 176
BATTERY_AT, BATTERY_SIZE = (STATUS_X + 153, 4), (20, 11)
INDICATOR_AT, INDICATOR_SIZE = (STATUS_X + 128, 0), (22, 18)
# The clock drops onto the page counter's line (firmware_screens.CLOCK_DROP).
CLOCK_AT, CLOCK_SIZE = (STATUS_X + 88, 19 + pages.PAGE_COUNTER_Y - 18), (88, 10)


# --- the title bar --------------------------------------------------------------------

def header_defs() -> str:
    """The title bar's gradients, in screen pixels: the light band behind the title, the
    dark band behind the page counter, as the guide's screens shade them."""
    return f"""
  <linearGradient id="band" gradientUnits="userSpaceOnUse"
                  x1="0" y1="0" x2="0" y2="{pages.TITLE_BAND}">
    <stop offset="0" stop-color="#363a38"/>
    <stop offset="0.55" stop-color="#3f403e"/>
    <stop offset="1" stop-color="#4a4743"/>
  </linearGradient>
  <linearGradient id="under" gradientUnits="userSpaceOnUse"
                  x1="0" y1="{pages.TITLE_BAND}" x2="0" y2="{HEADER_HEIGHT}">
    <stop offset="0" stop-color="#1c1b1b"/>
    <stop offset="0.8" stop-color="#141413"/>
    <stop offset="1" stop-color="#000000"/>
  </linearGradient>"""


def header_body() -> str:
    band = pages.TITLE_BAND
    return f"""
  <rect width="{SCREEN_WIDTH}" height="{HEADER_HEIGHT}" fill="url(#under)"/>
  <rect width="{SCREEN_WIDTH}" height="{band}" fill="url(#band)"/>
  <rect y="{band - 1}" width="{SCREEN_WIDTH}" height="1" fill="#57534f"/>
  <rect y="{band}" width="{SCREEN_WIDTH}" height="1" fill="#0e0d0d"/>"""


def svg(width: int, height: int, defs: str, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" shape-rendering="geometricPrecision">\n'
            f'<defs>{defs}\n</defs>{body}\n</svg>\n')


def header() -> str:
    return svg(SCREEN_WIDTH, HEADER_HEIGHT, header_defs(), header_body())


def on_header(at, size, icon: str, defs: str = "") -> str:
    """A status picture: the slice of the title bar at ``at``, and ``icon`` over it,
    drawn in the picture's own pixels."""
    x, y = at
    return svg(*size, header_defs() + defs,
               f'\n  <g transform="translate({-x} {-y})">{header_body()}\n  </g>{icon}')


# --- the softkey bar ------------------------------------------------------------------

def softkey_bar() -> str:
    height = 320 - BAR_TOP
    middle = SCREEN_WIDTH // 2
    return svg(SCREEN_WIDTH, height, """
  <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#121314"/>
    <stop offset="0.35" stop-color="#1d1f1e"/>
    <stop offset="1" stop-color="#383a37"/>
  </linearGradient>""", f"""
  <rect width="{SCREEN_WIDTH}" height="{height}" fill="url(#bar)"/>
  <rect width="{SCREEN_WIDTH}" height="1" fill="#050607"/>
  <rect x="{middle - 1}" y="2" width="1" height="{height - 2}" fill="#070707"/>
  <rect x="{middle}" y="2" width="1" height="{height - 2}" fill="#4b4c4a"/>""")


# --- frames ---------------------------------------------------------------------------

# Each screen's colour, as the 800 colours them: blue for the activities', and for the rest
# their softkey label's colour - green for Options, orange for the devices. Per palette:
# the sky's five stops from the top down to the horizon, the faint tint just under it, the
# line along the top, the horizon's line, the edge and the foot.
PALETTES = {
    "blue": (("#0c2236", "#0b3352", "#0c4068", "#135284", "#1d6a9e"), "#03080e", "#1a3142",
             "#3a78a0", "#1d2e3d", "#23262e"),
    "green": (("#142608", "#1e380b", "#29500f", "#3a6c14", "#55921c"), "#060b02", "#25381a",
              "#7ab43a", "#2a3a1e", "#262b22"),
    "orange": (("#2c1405", "#432008", "#5c2d0b", "#82410f", "#b25e18"), "#0e0602", "#3e2716",
               "#e08a40", "#3d2a1d", "#2e2622"),
}


def frame(width: int, height: int, palette: str = "blue") -> str:
    """A button or row: deep colour brightening down to a horizon halfway, black below it,
    in a thin dark edge with rounded corners - opaque, black outside the corners, which is
    what the backdrop is."""
    horizon = height // 2
    sky, tint, top, line, edge, foot = PALETTES[palette]
    stops = "".join(f'\n    <stop offset="{offset}" stop-color="{colour}"/>'
                    for offset, colour in zip((0, 0.3, 0.6, 0.85, 1), sky))
    return svg(width, height, f"""
  <linearGradient id="sky" gradientUnits="userSpaceOnUse"
                  x1="0" y1="1" x2="0" y2="{horizon}">{stops}
  </linearGradient>
  <linearGradient id="ground" gradientUnits="userSpaceOnUse"
                  x1="0" y1="{horizon}" x2="0" y2="{height}">
    <stop offset="0" stop-color="{tint}"/>
    <stop offset="0.25" stop-color="#010101"/>
    <stop offset="1" stop-color="#000000"/>
  </linearGradient>
  <clipPath id="inside">
    <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="3"/>
  </clipPath>""",
               f"""
  <rect width="{width}" height="{height}" fill="#000000"/>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="4"
        fill="#000000" stroke="{edge}"/>
  <g clip-path="url(#inside)">
    <rect y="0" width="{width}" height="{horizon}" fill="url(#sky)"/>
    <rect y="{horizon}" width="{width}" height="{height - horizon}" fill="url(#ground)"/>
    <rect y="1" width="{width}" height="1" fill="{top}"/>
    <rect y="{horizon - 1}" width="{width}" height="1" fill="{line}"/>
  </g>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="4"
        fill="none" stroke="{edge}"/>
  <rect x="4" y="{height - 1}" width="{width - 8}" height="1" fill="{foot}"/>""")


# --- the status bar -------------------------------------------------------------------

GREEN, AMBER, RED, GREY = "#3ccf3c", "#f0a020", "#e83030", "#8c8c8c"


def battery(level: int | None, colour: str = GREEN, mark: str = "", bolt: bool = False) -> str:
    """The guide's battery: a light outline and its tip, filled from the left in
    ``level`` sevenths; ``mark`` a character over it, ``bolt`` the charge sign."""
    x, y = BATTERY_AT
    w, h = BATTERY_SIZE
    body = f"""
  <rect x="0.5" y="1.5" width="{w - 3}" height="{h - 3}" rx="1.5"
        fill="#101010" stroke="#d6d6d2"/>
  <rect x="{w - 2}" y="{h // 2 - 2}" width="2" height="4" fill="#d6d6d2"/>"""
    if level:
        inner = (w - 6) * level / 7
        body += f'\n  <rect x="2" y="3" width="{inner:.2f}" height="{h - 6}" fill="{colour}"/>'
    if mark:
        body += (f'\n  <text x="{(w - 2) / 2}" y="{h - 2.5}" text-anchor="middle" '
                 f'font-family="DejaVu Sans" font-weight="bold" font-size="8" '
                 f'fill="{colour}">{mark}</text>')
    if bolt:
        body += ('\n  <path d="M10 1 L6 6 L9 6 L7 10 L12 4.5 L9 4.5 Z" fill="#ffe14a" '
                 'stroke="#101010" stroke-width="0.6"/>')
    return on_header((x, y), (w, h), body)


def indicator(sending: bool) -> str:
    """The IR indicator: three arcs spreading from a point while the remote sends."""
    w, h = INDICATOR_SIZE
    if not sending:
        return on_header(INDICATOR_AT, INDICATOR_SIZE, "")
    cx, cy = w / 2, h - 3
    arcs = "".join(
        f'\n  <path d="M{cx - r:.2f} {cy - r * 0.15:.2f} A{r} {r} 0 0 1 {cx + r:.2f} '
        f'{cy - r * 0.15:.2f}" fill="none" stroke="#e8e8e8" stroke-width="1.5" '
        f'stroke-linecap="round"/>' for r in (3.5, 7, 10.5))
    return on_header(INDICATOR_AT, INDICATOR_SIZE,
                     f'\n  <circle cx="{cx}" cy="{cy}" r="1.6" fill="#e8e8e8"/>{arcs}')


def sending() -> str:
    """The waves over a starting activity's icon: four arcs spreading up from the remote's
    window, brightest nearest it, on the black backdrop."""
    w, h = pages.SENDING_SIZE
    cx, cy = w / 2, h - 2
    arcs = "".join(
        f'\n  <path d="M{cx - r:.2f} {cy - r * 0.2:.2f} A{r} {r * 0.95:.2f} 0 0 1 '
        f'{cx + r:.2f} {cy - r * 0.2:.2f}" fill="none" stroke="{colour}" '
        f'stroke-width="3" stroke-linecap="round"/>'
        for r, colour in ((8, "#f4f4f4"), (15, "#c9d8e4"), (22, "#8fb3cf"), (29, "#5a88ad")))
    return svg(w, h, "", f"""
  <rect width="{w}" height="{h}" fill="#000000"/>
  <circle cx="{cx}" cy="{cy}" r="3" fill="#ffffff"/>{arcs}""")


# Each status picture the scaffold draws, as the One's status bar uses them: the battery's
# eight levels (0 unknown), the charge animation, on external power, and the indicator.
STATUS = {
    "status/battery-0-2": lambda: battery(None, GREY, "?"),
    "status/battery-0": lambda: battery(None, GREY),
    "status/battery-1": lambda: battery(1, RED, "!"),
    "status/battery-2": lambda: battery(1, RED),
    "status/battery-3": lambda: battery(2, AMBER),
    "status/battery-4": lambda: battery(3),
    "status/battery-5": lambda: battery(4),
    "status/battery-6": lambda: battery(6),
    "status/battery-7": lambda: battery(7),
    "status/charge-0": lambda: battery(7, bolt=True),
    "status/charge-1": lambda: battery(None, bolt=True),
    "status/charge-1-2": lambda: battery(3, bolt=True),
    "status/power-3": lambda: battery(7, bolt=True),
    "status/indicator-0": lambda: indicator(False),
    "status/indicator-1": lambda: indicator(True),
    "status/progress": lambda: on_header(CLOCK_AT, CLOCK_SIZE, ""),
}


# --- the Tutorial ---------------------------------------------------------------------
#
# The Tutorial's pictures, redrawn in the 800's look: the 800 itself, from the vector
# drawing made from its guide's line art (art/tutorial/harmony-800-front.svg, referenced,
# not copied into each picture), with the key a page teaches circled and magnified in a
# frame its own shape, as Logitech's Tutorial pictures its remote; the 800's own screen on
# the remote's display; the scaffold's own icons for the devices. The hand and the thumb (pages 1
# and 11) are Logitech's, the One's own pictures, kept.

REMOTE = "harmony-800-front.svg"
REMOTE_VIEW = (530, 212, 104, 216)          # the drawing's viewBox, in the guide's points
REMOTE_BODY = (531, 597)                    # the remote alone, without its keyboard
DISPLAY = (547.218, 236.86, 35.982, 47.976)  # its display, 3:4 as the screen, in the same points
RING = "#f5b800"
TUTORIAL_SIZE = (200, 116)


# What the remote's display shows in the pictures: the 800's own Activities screen, as a
# build of this scaffold draws it - captured from one (art/tutorial/screen.png, 240 x 320).
SCREEN = "screen.png"


def mini_defs() -> str:
    """The captured screen, once, as ``#mini-screen``, in display pixels (240 x 320)."""
    data = base64.b64encode((ART / "tutorial" / SCREEN).read_bytes()).decode()
    return f"""
  <g id="mini-screen">
    <image href="data:image/png;base64,{data}" width="240" height="320"
           preserveAspectRatio="none" image-rendering="optimizeQuality"/>
  </g>"""


def remote(k: float, at, target, clip_id: str) -> str:
    """The remote drawn ``k`` pixels to the guide's point, ``target`` (points) at ``at``,
    with its own screen on its display, clipped to ``clip_id``."""
    vx, vy, vw, vh = REMOTE_VIEW
    ox, oy = at[0] - (target[0] - vx) * k, at[1] - (target[1] - vy) * k
    dx, dy, dw, dh = DISPLAY
    return f"""
  <g clip-path="url(#{clip_id})">
    <image href="{REMOTE}" x="{ox:.2f}" y="{oy:.2f}" width="{vw * k:.2f}" height="{vh * k:.2f}"/>
    <g transform="translate({ox - vx * k:.2f} {oy - vy * k:.2f}) scale({k})">
      <rect x="{dx}" y="{dy}" width="{dw}" height="{dh}" rx="1.1" fill="#000"/>
      <g transform="translate({dx + (dw - dh * 0.75) / 2:.3f} {dy}) scale({dh / 320:.5f})">
        <use href="#mini-screen"/>
      </g>
    </g>
  </g>"""


# Each key the Tutorial teaches: its centre and its size on the drawing, in points.
KEYS = {"arrow": ((587.4, 268.2), (3.6, 8.0)), "activities": ((563.3, 300.6), (22.4, 4.8)),
        "help": ((564.8, 309.4), (18.4, 5.0)), "power": ((547.2, 225.6), (7.2, 7.2))}
LINK = "#c9c9c9"


def callout(key: str, remote_at, frame_at, *, zoom: float, k: float = 1.9) -> str:
    """A Tutorial picture as Logitech's: the remote, the key ``key`` framed on it by a
    rounded rectangle its own shape, and the key magnified ``zoom`` pixels to the point in
    a larger frame of the same shape at ``frame_at`` (its top left), joined by two thin
    lines."""
    w, h = TUTORIAL_SIZE
    target, (key_w, key_h) = KEYS[key]
    left = remote_at[0] - (target[0] - REMOTE_BODY[0]) * k
    right = remote_at[0] + (REMOTE_BODY[1] - target[0]) * k
    # the small frame round the key on the remote, and the large one round its picture
    sw, sh = key_w * k + 7, key_h * k + 7
    sx, sy = remote_at[0] - sw / 2, remote_at[1] - sh / 2
    bw, bh = key_w * zoom + 26, key_h * zoom + 22
    bx, by = frame_at
    centre = (bx + bw / 2, by + bh / 2)
    # the lines join the sides that face each other: a frame above the key from its foot
    # down to the key's frame, one beside it from its near side across
    if by + bh < sy:
        ends = [((bx + bw * 0.3, by + bh), (sx + 2, sy + sh / 2)),
                ((bx + bw * 0.85, by + bh), (sx + sw - 2, sy + sh / 2))]
    else:
        near, far = (bx + bw, sx) if bx + bw / 2 < remote_at[0] else (bx, sx + sw)
        ends = [((near, by + bh * part), (far, sy + sh * part)) for part in (0.25, 0.75)]
    lines = "".join(
        f'\n  <line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" '
        f'stroke="{LINK}" stroke-width="1"/>' for a, b in ends)

    def rounded(x, y, width, height, stroke, fill="none"):
        radius = min(width, height) * 0.42
        return (f'\n  <rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height:.2f}" '
                f'rx="{radius:.2f}" fill="{fill}" stroke="{RING}" stroke-width="{stroke}"/>')
    clip_radius = min(bw, bh) * 0.42
    return svg(w, h, mini_defs() + f"""
  <clipPath id="body">
    <rect x="{left:.2f}" y="0" width="{right - left:.2f}" height="{h}"/>
  </clipPath>
  <clipPath id="frame"><rect x="{bx}" y="{by}" width="{bw:.2f}" height="{bh:.2f}"
                             rx="{clip_radius:.2f}"/></clipPath>""", f"""
  <rect width="{w}" height="{h}" fill="#000000"/>{remote(k, remote_at, target, "body")}{lines}"""
               + rounded(sx, sy, sw, sh, 2) + rounded(bx, by, bw, bh, 0, "#000000")
               + remote(zoom, centre, target, "frame") + rounded(bx, by, bw, bh, 3))


def icon(kind: str, name: str, x: float, y: float, w: float, h: float) -> str:
    """The scaffold's icon for a type, carried in the picture (librsvg reads no file above
    the picture's own folder)."""
    data = base64.b64encode((SCAFFOLD / "images/icons" / kind / f"{name}.png").read_bytes())
    return (f'\n  <image href="data:image/png;base64,{data.decode()}" x="{x}" y="{y}" '
            f'width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet"/>')


def system() -> str:
    """Selecting Watch TV turns on what it needs: the TV, the receiver and the cable box,
    in a ring."""
    w, h = 180, 100
    return svg(w, h, "", f"""
  <rect width="{w}" height="{h}" fill="#000000"/>
  <ellipse cx="90" cy="56" rx="62" ry="32" fill="none" stroke="{RING}" stroke-width="3"/>"""
               + icon("devices", "Television", 52, 2, 76, 37)
               + icon("devices", "Receiver", 0, 62, 70, 34)
               + icon("devices", "CableBox", 110, 62, 70, 34))


def television() -> str:
    """Help asks after the TV: the TV it asks about."""
    w, h = 84, 41
    return svg(w, h, "", f'\n  <rect width="{w}" height="{h}" fill="#000000"/>'
               + icon("devices", "Television", 0, 0, w, h))


# The Tutorial's pictures, by page (options_screens.TUTORIAL). Pages 4 and 6 draw the
# remote's own row and buttons instead, page 7 shows page 3's picture again, and pages 1
# and 11 keep the One's hand and thumb.
TUTORIAL = {
    "tutorial/2": lambda: callout("arrow", (110, 68), (136, 16), zoom=7),
    "tutorial/3": lambda: callout("activities", (160, 98), (4, 10), zoom=4.4),
    "tutorial/5": system,
    "tutorial/8": lambda: callout("help", (160, 98), (4, 10), zoom=4.8),
    "tutorial/9": television,
    "tutorial/10": lambda: callout("power", (140, 22), (8, 24), zoom=6),
}


def pictures() -> dict[str, str]:
    """Every picture this draws, by role, as SVG."""
    out = {"chrome/header": header(), "chrome/softkeys": softkey_bar(),
           pages.NUMPAD_FRAME: frame(pages.NUMPAD_WIDTH, pages.NUMPAD_HEIGHT, "orange"),
           pages.ACTIVITY_NUMPAD_FRAME: frame(pages.NUMPAD_WIDTH, pages.NUMPAD_HEIGHT),
           "activity/sending": sending()}
    # the devices' frames orange, the activities' blue, Options' green
    for group, palette in (("button-frame", "orange"), ("activity/button-frame", "blue"),
                           ("options/button-frame", "green")):
        for index in range(len(pages.BUTTON_POSITIONS)):
            out[f"{group}/{index}"] = frame(*BUTTON, palette)
    for role, palette in (("row-frame", "orange"), ("row-frame/1", "orange"),
                          ("row-frame/2", "orange"), ("activity/row-frame", "blue"),
                          ("options/row-frame/0", "green"), ("options/row-frame/1", "green"),
                          ("options/row-frame/2", "green")):
        out[role] = frame(*ROW, palette)
    out.update({role: draw() for role, draw in STATUS.items()})
    out.update({role: draw() for role, draw in TUTORIAL.items()})
    return out


def inlined(text: str, folder: Path) -> str:
    """``text`` with each picture of the remote drawing (REMOTE) drawn from its vectors:
    librsvg draws an SVG ``<image>`` at the drawing's own pixel size and scales that, which
    blurs it magnified, where a nested ``<svg>`` is drawn sharp at any size."""
    reference = f'href="{REMOTE}"'
    if reference not in text:
        return text
    drawing = (folder / REMOTE).read_text()
    inner = drawing[drawing.index(">", drawing.index("<svg")) + 1:drawing.rindex("</svg>")]
    vx, vy, vw, vh = REMOTE_VIEW

    def nested(match):
        attributes = dict(re.findall(r'(\w+)="([^"]*)"', match.group(0)))
        return (f'<svg x="{attributes["x"]}" y="{attributes["y"]}" width="{attributes["width"]}" '
                f'height="{attributes["height"]}" viewBox="{vx} {vy} {vw} {vh}">'
                '<use href="#remote-drawing"/></svg>')
    text = re.sub(r'<image href="' + re.escape(REMOTE) + r'"[^>]*/>', nested, text)
    return text.replace("<defs>", f'<defs><g id="remote-drawing">{inner}</g>', 1)


def render(source: Path, target: Path) -> tuple[int, int]:
    """``source`` rendered at its own size, made opaque over black and reduced to RGB565."""
    with tempfile.TemporaryDirectory() as scratch:
        drawn = Path(scratch) / "drawn.png"
        expanded = Path(scratch) / "picture.svg"
        expanded.write_text(inlined(source.read_text(), source.parent))
        subprocess.run(["rsvg-convert", "-o", str(drawn), str(expanded)], check=True)
        image = imaging.decode(drawn.read_bytes())
    rows = []
    for line in image["rows"]:
        row = []
        for red, green, blue, alpha in line:
            share = alpha / 255
            colour = tuple(round(channel * share) for channel in (red, green, blue))
            row.append((*bitmap.from_rgb565(bitmap.to_rgb565(colour)), 255))
        rows.append(row)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(imaging.encode(rows))
    return image["width"], image["height"]


def remote_showing(screen: Path) -> str:
    """The remote drawing, whole and self-contained, with ``screen`` - a 240 x 320 capture
    of what the 800 shows - set into its display, fitted to its height and kept crisp, a
    pixel to a pixel, so it reads as the display it is when the drawing is enlarged. The
    drawing on its own keeps its glare."""
    drawing = (ART / "tutorial" / REMOTE).read_text()
    data = base64.b64encode(screen.read_bytes()).decode()
    dx, dy, dw, dh = DISPLAY
    width = dh * 0.75
    picture = (f'<clipPath id="ui-display"><rect x="{dx}" y="{dy}" width="{dw}" height="{dh}" '
               f'rx="1.1"/></clipPath><g clip-path="url(#ui-display)">'
               f'<rect x="{dx}" y="{dy}" width="{dw}" height="{dh}" fill="#000"/>'
               f'<image href="data:image/png;base64,{data}" x="{dx + (dw - width) / 2:.4f}" '
               f'y="{dy}" width="{width:.4f}" height="{dh}" preserveAspectRatio="none" '
               f'style="image-rendering:pixelated"/></g>')
    # straight after the display's glass, and without the glass's glare over it: a lit
    # display shows its screen, not the reflection drawn on the unlit one
    glare = drawing.index('fill="url(#ag-glare)"')
    start = drawing.rindex("<path", 0, glare)
    drawing = drawing[:start] + drawing[drawing.index("/>", glare) + 2:]
    glass = drawing.index("url(#ag-screen)")
    after = drawing.index("/>", glass) + 2
    return drawing[:after] + picture + drawing[after:]


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--remote-showing":
        Path(argv[2]).write_text(remote_showing(Path(argv[1])))
        return 0
    if shutil.which("rsvg-convert") is None:
        print("needs rsvg-convert (librsvg)", file=sys.stderr)
        return 1
    manifest_path = SCAFFOLD / "assets.json"
    manifest = json.loads(manifest_path.read_text())
    for role, text in pictures().items():
        source = ART / f"{role}.svg"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text)
        file = f"images/{role}.png"
        size = render(source, SCAFFOLD / file)
        # opaque, so stored whole: `raw`, as every frame is
        manifest["pictures"][role] = {"file": file, "mode": "raw", "size": list(size)}
    manifest["pictures"] = dict(sorted(manifest["pictures"].items()))
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"drew {len(pictures())} pictures into {SCAFFOLD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
