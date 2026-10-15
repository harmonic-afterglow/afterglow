#!/usr/bin/env python3
"""Put MyHarmony's type icons in the Harmony 800's scaffold, one per device and activity type.

    python3 tools/harmony_800_myharmony_icons.py MYHARMONY_IMAGES

The 800's own screens, in its Getting Started Guide, show Logitech's glossy icons of that
era - Watch TV the television with a remote beside it, Play Game the white gamepad - and
MyHarmony, the setup software that followed, carries the whole family. MYHARMONY_IMAGES is
a folder of them as Logitech serves them to MyHarmony
(https://files.myharmony.com/Assets/Images/<name>.png, 102 x 102): `DeviceIcon_*` and
`Act_*_Setup`, the newer drawings, and `di_*` and `ai_*`, the older ones the Harmony 900,
1100 and One were given smaller copies of.

Each icon is drawn above a fading reflection of itself. The 800's rows have no floor for it
to stand on, so the reflection is cut away: everything below the last row the icon itself
is opaque in, from where nothing below is more than faint. The icon is then trimmed to
what it draws.

A type MyHarmony has no icon for is made from two that it has (COMPOSITES): watching
something is the television with that thing in front of its lower right, as Watch TV sets
the remote beside it; a combined unit is its two parts, one on the other. Row icons are
scaled at build time (row_icons.py), so the files are written at the size they come out.

The folder is not part of this repository; only the icons written are kept.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import imaging  # noqa: E402
from afterglow.backends.harmony_800.row_icons import scale  # noqa: E402

ICONS = ROOT / "src/afterglow/scaffolds/harmony-800/images/icons"
TV = "DeviceIcon_01_TV"
# MyHarmony's icon for each device type.
DEVICES = {
    "Amplifier": "di_01_amplifier",
    "AudioVideoSwitch": "di_02_av_switch",
    "CableBox": "DeviceIcon_02_CableBox",
    "Cassette": "DeviceIcon_18_TapeDeck",
    "CdJukebox": "di_05_cd_jukebox",
    "Cd": "di_06_cd_player",
    "CdRadioCassette": "DeviceIcon_06_MiniSystem",
    "ClimateControl": "DeviceIcon_98_ClimateControl",
    "Computer": "DeviceIcon_17_Tower",
    "Dat": "DeviceIcon_99_DAT",
    "DvdCdGame": "di_20_game_console_dvd",
    "DvdCd": "DeviceIcon_04_DiscPlayerLight",
    "DvdCdRadio": "di_31_mini_system_dvd_cd_radio",
    "DvdRecorder": "di_16_dvd_recorder",
    "DvdrVcr": "DeviceIcon_20_DvdVcrCombo",
    "DvdVcr": "DeviceIcon_20_DvdVcrCombo",
    "GameConsole": "DeviceIcon_07_GameConsole",
    "HomeAppliance": "DeviceIcon_HomeAppliance",
    "Laptop": "DeviceIcon_08_Computer",
    "Laserdisc": "di_27_laserdisc_player",
    "Light": "DeviceIcon_102_PhilipsHue",
    "MediaCenterPC": "di_29_media_center_pc",
    "Monitor": "di_33_monitor",
    "MusicServer": "di_13_digital_music_server",
    "Projector": "DeviceIcon_16_Projector",
    "Pvr": "di_57_dvr",
    "Receiver": "DeviceIcon_03_Receiver",
    "SetTopBox": "di_14_digital_set_top_box",
    "Television": TV,
    "TvVcr": "DeviceIcon_19_TvVcrCombo",
    "Vcr": "DeviceIcon_15_VCR",
}
# And for each activity type.
ACTIVITIES = {
    "VirtualCdJukebox": "ai_06_listen_cd_jukebox",
    "VirtualCdMulti": "ai_07_listen_to_cd",
    "VirtualDvd": "Act_WatchDVD_Setup",
    "VirtualGameConsole": "DeviceIcon_07_GameConsole",
    "VirtualGeneric": "Act_Custom_Setup",
    "VirtualMediaCenterMusic": "ai_10_listen_to_music_media_cente",
    "VirtualMediaCenterPictures": "di_29_media_center_pc",
    "VirtualMinidisc": "ai_09_listenminidisc",
    "VirtualMusicServer": "ai_03_listendigitalmusic",
    "VirtualRadioSimple": "ai_11_listen_to_radio",
    "VirtualSatelliteMusic": "ai_04_listensatellite",
    "VirtualTape": "ai_12_listen_to_tape",
    "VirtualTeletext": "Act_WatchTV_Setup",
    "VirtualTelevisionN": "Act_WatchTV_Setup",
}
# The types made from two icons: ("front", main, beside) sets ``beside`` in front of the
# lower right of ``main``; ("stack", top, bottom) stands one unit on the other.
COMPOSITES = {
    "devices": {
        "DvdVcrReceiver": ("stack", "DeviceIcon_03_Receiver", "DeviceIcon_20_DvdVcrCombo"),
        "Minidisc": ("front", "DeviceIcon_04_DiscPlayerLight", "ai_09_listenminidisc"),
        "RadioTuner": ("front", "DeviceIcon_03_Receiver", "ai_11_listen_to_radio"),
        "Satellite": ("front", "DeviceIcon_02_CableBox", "di_40_satellite"),
        "TvDvd": ("front", TV, "DeviceIcon_04_DiscPlayerLight"),
        "TvDvdVcr": ("front", TV, "DeviceIcon_20_DvdVcrCombo"),
        "TvHdd": ("front", TV, "di_57_dvr"),
    },
    "activities": {
        "VirtualLaserdisc": ("front", TV, "di_27_laserdisc_player"),
        "VirtualMediaCenterTv": ("front", TV, "di_29_media_center_pc"),
        "VirtualMediaCenterVideos": ("front", "Act_WatchDVD_Setup", "di_29_media_center_pc"),
        "VirtualPresentation": ("front", "DeviceIcon_16_Projector", "DeviceIcon_08_Computer"),
        "VirtualPvr": ("front", TV, "di_57_dvr"),
        "VirtualReplayTV": ("front", TV, "di_16_dvd_recorder"),
        "VirtualTiVo": ("front", TV, "DeviceIcon_HopperOrJoey"),
        "VirtualVcr": ("front", TV, "DeviceIcon_15_VCR"),
        "VirtualVcrRecorder": ("stack", "DeviceIcon_15_VCR", "di_16_dvd_recorder"),
    },
}
# A row at least this opaque somewhere is the icon; below the last such row with nothing
# more opaque under it, what is left is the reflection.
SOLID = 80
# In a "front" composite: the part beside is this high against the main icon, sits this far
# below its foot, and overlaps it by this much of its own width.
BESIDE_HEIGHT, BESIDE_DROP, BESIDE_OVERLAP = 0.55, 0.06, 0.45
# and is no wider than this share of the main icon.
BESIDE_WIDTH = 0.7
# A box wider than this share of its width is tall is flat, and is measured by its width.
FLAT = 0.6
# In a "stack": the gap between the two units, against the lower one's height.
STACK_GAP = 0.04

Rows = list[list[tuple]]


def load(folder: Path, name: str) -> Rows:
    path = folder / f"{name}.png"
    if not path.is_file():
        raise FileNotFoundError(f"MyHarmony's {name}.png is not in {folder}")
    return imaging.decode(path.read_bytes())["rows"]


def without_reflection(rows: Rows) -> Rows:
    """``rows`` cut off below the icon: from the first row under which nothing is solid."""
    solid = [max(pixel[3] for pixel in row) >= SOLID for row in rows]
    if True not in solid:
        return rows
    end = len(solid) - solid[::-1].index(True)
    return rows[:end]


def trimmed(rows: Rows) -> Rows:
    """``rows`` cut to the box of the pixels they draw."""
    ys = [y for y, row in enumerate(rows) if any(pixel[3] for pixel in row)]
    xs = [x for x in range(len(rows[0])) if any(row[x][3] for row in rows)]
    return [row[xs[0]:xs[-1] + 1] for row in rows[ys[0]:ys[-1] + 1]]


def icon(folder: Path, name: str) -> Rows:
    return trimmed(without_reflection(load(folder, name)))


def resized(rows: Rows, height: float) -> Rows:
    factor = height / len(rows)
    return scale(rows, max(1, round(len(rows[0]) * factor)), max(1, round(height)))


def over(canvas: Rows, rows: Rows, x0: int, y0: int) -> None:
    """``rows`` drawn onto ``canvas`` at ``x0``, ``y0``, alpha over what is there."""
    for y, line in enumerate(rows):
        for x, (r, g, b, a) in enumerate(line):
            if not a:
                continue
            under = canvas[y0 + y][x0 + x]
            share, rest = a / 255, under[3] / 255 * (1 - a / 255)
            alpha = share + rest
            canvas[y0 + y][x0 + x] = (
                round((r * share + under[0] * rest) / alpha),
                round((g * share + under[1] * rest) / alpha),
                round((b * share + under[2] * rest) / alpha), round(alpha * 255))


def front(main: Rows, beside: Rows) -> Rows:
    """``beside`` in front of the lower right of ``main``, sized against ``main``'s bulk -
    its height, or a share of its width for a flat box - so it reads beside either, and
    narrow enough to leave ``main`` showing."""
    main_w, main_h = len(main[0]), len(main)
    bulk = max(main_h, main_w * FLAT)
    height = min(bulk * BESIDE_HEIGHT, main_w * BESIDE_WIDTH * len(beside) / len(beside[0]))
    beside = resized(beside, height)
    w, h = len(beside[0]), len(beside)
    x = main_w - round(w * BESIDE_OVERLAP)
    y = main_h + round(bulk * BESIDE_DROP) - h
    lift = max(0, -y)                       # how far the main icon moves down to make room
    canvas = [[(0, 0, 0, 0)] * max(main_w, x + w) for _ in range(max(main_h + lift, y + lift + h))]
    over(canvas, main, 0, lift)
    over(canvas, beside, x, y + lift)
    return canvas


def stack(top: Rows, bottom: Rows) -> Rows:
    """``top`` standing on ``bottom``, both drawn at the width of the wider."""
    width = max(len(top[0]), len(bottom[0]))
    top = resized(top, len(top) * width / len(top[0]))
    bottom = resized(bottom, len(bottom) * width / len(bottom[0]))
    gap = round(len(bottom) * STACK_GAP)
    canvas = [[(0, 0, 0, 0)] * width for _ in range(len(top) + gap + len(bottom))]
    over(canvas, top, (width - len(top[0])) // 2, 0)
    over(canvas, bottom, (width - len(bottom[0])) // 2, len(top) + gap)
    return canvas


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    folder = Path(argv[0])
    for kind, table in (("devices", DEVICES), ("activities", ACTIVITIES)):
        for type_name, name in table.items():
            (ICONS / kind / f"{type_name}.png").write_bytes(imaging.encode(icon(folder, name)))
            print(f"{kind}/{type_name}.png <- {name}")
    for kind, table in COMPOSITES.items():
        for type_name, (how, first, second) in table.items():
            built = {"front": front, "stack": stack}[how](icon(folder, first),
                                                         icon(folder, second))
            (ICONS / kind / f"{type_name}.png").write_bytes(imaging.encode(built))
            print(f"{kind}/{type_name}.png <- {first} {how} {second}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
