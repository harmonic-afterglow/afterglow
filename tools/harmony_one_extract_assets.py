#!/usr/bin/env python3
"""Extract a Harmony One's artwork from a configuration into an editable scaffold.

    python3 tools/harmony_one_extract_assets.py donor.EZHex src/afterglow/scaffolds/harmony-one

## Why this exists

The Harmony One keeps no artwork in firmware: every frame, icon and glyph it draws is
stored in the configuration. A generated configuration therefore has to supply them, and
the ones Logitech shipped are the ones the remote was designed around - drawn for a
176x220 RGB565 panel, hinted at 11 to 16 pixels, and legible in a way a scaled desktop
font is not.

So this reads them out of a real configuration and writes them as PNG files anyone can
open. Only artwork is taken: pictures the interface draws and font glyphs. Nothing that
identifies a remote or its owner - no device names, activities, favourites, or account
data - is read, let alone written.

Every picture and glyph round-trips byte for byte through this project's codecs, so what
lands in the scaffold is exactly what the donor drew.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from afterglow import ezhex, imaging  # noqa: E402
from afterglow.backends.harmony_one import command_index  # noqa: E402
from afterglow.backends.harmony_one import (  # noqa: E402
    bitmap, drawing, font_index, glyph_codec, gspm, resources,
    scaffold, ui_index)


# Which overlay a section-12 program is, recognised by the selectors it switches on.
# The four kinds are identical in shape in every image measured; only their order in the
# table and how many copies of each an image carries differ.
OVERLAY_NAMES = {9: "battery", 0: "charge", 15: "power", 17: "indicator", 4: "progress"}


def payload_of(path: Path) -> bytes:
    """Read a configuration's GSPM payload, unpacking a container if given one."""
    data = path.read_bytes()
    if data[:4] == b"GSPM":
        return data
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(str(path), tmp)
        blob = Path(tmp, "payload.bin")
        if not blob.is_file():
            raise SystemExit(f"{path} unpacked to no payload.bin")
        return blob.read_bytes()


def picture_roles(payload: bytes) -> dict[str, int]:
    """Name the pictures the interface draws, by the role the catalogue gives them."""
    catalogue = resources.catalogue(payload)
    roles: dict[str, int] = {}
    if catalogue["background"]:
        roles["backdrop"] = catalogue["background"][2]
    order = sorted(catalogue["button_frames"], key=lambda xy: (xy[1], xy[0]))
    for index, position in enumerate(order):
        roles[f"button-frame/{index}"] = catalogue["button_frames"][position]
    seen_frames: dict[int, str] = {}
    # Only the frames: a build composes each row's icon from the frame and a type icon
    # (backends/harmony_one/row_icons.py), so the donor's own icons are not taken.
    for icon in catalogue["menu"]["row_icons"]:
        for x, _y, target in icon:
            if x < 10:
                seen_frames.setdefault(target, "row-frame")
    for number, target in enumerate(sorted(seen_frames)):
        roles["row-frame" if number == 0 else f"row-frame/{number}"] = target
    return roles


def _distances(blocks: dict[int, list[dict]], start: int) -> dict[int, int]:
    """How far each picture is from ``start``, in blocks walked to reach it.

    An arm of a switch is not always the block that draws - the progress overlay nests
    two more switches below its own - so the walk has to be transitive. But a picture
    reached through three nested switches belongs to the innermost one, which is why the
    distance is kept rather than only the fact that it was reachable.
    """
    out: dict[int, int] = {}
    seen, frontier, depth = set(), [start], 0
    while frontier:
        following = []
        for offset in frontier:
            if offset in seen or offset not in blocks:
                continue
            seen.add(offset)
            for item in blocks[offset]:
                if item["opcode"] == "bitmap":
                    out.setdefault(item["target"], depth)
                elif item["opcode"] in ("call", "jump"):
                    following.append(item["target"])
                elif item["opcode"] == "switch":
                    following.extend(target for _value, target in item["cases"])
                    following.extend(
                        target for _low, _high, target in item["ranges"])
        frontier, depth = following, depth + 1
    return out


def overlay_roles(payload: bytes) -> dict[str, int]:
    """Name the status pictures section 12 draws, by the state each one stands for.

    A picture is named after the nearest switch that selects it. Naming it after any
    switch that merely reaches it would hand every battery level to the outermost one,
    which selects between power modes and says nothing about the level.
    """
    claims: dict[int, tuple] = {}
    for index, root in enumerate(ui_index.overlay_roots(payload)):
        blocks = drawing.program_blocks(payload, [root])
        for block in blocks.values():
            for item in block:
                if item["opcode"] != "switch":
                    continue
                name = OVERLAY_NAMES.get(item["selector"])
                if name is None:
                    continue
                arms = [(value, target) for value, target in item["cases"]]
                arms += [(low, target) for low, _high, target in item["ranges"]]
                for value, target in sorted(arms):
                    for picture, distance in _distances(blocks, target).items():
                        best = claims.get(picture)
                        if best is None or distance < best[0]:
                            claims[picture] = (distance, name, value)
        # Whatever no switch selects - the progress bar is drawn by the root block
        # itself - still has to reach the scaffold.
        selectors = [
            item["selector"] for block in blocks.values() for item in block
            if item["opcode"] == "switch"
        ]
        fallback = next(
            (OVERLAY_NAMES[selector] for selector in selectors
             if selector in OVERLAY_NAMES), f"overlay-{index:02d}")
        for picture in _distances(blocks, root):
            claims.setdefault(picture, (1 << 30, fallback, None))

    roles: dict[str, int] = {}
    for picture, (_distance, name, value) in sorted(
            claims.items(), key=lambda pair: (pair[1][1], pair[1][2] or 0, pair[0])):
        role = f"status/{name}" if value is None else f"status/{name}-{value}"
        suffix = 2
        while role in roles:
            role = f"status/{name}-{value}-{suffix}"
            suffix += 1
        roles[role] = picture
    return roles


def system_picture_roles(payload: bytes, taken: set[int]) -> dict[str, int]:
    """Name the pictures the firmware's own screens draw that no other role claimed.

    The first forty screens are the platform's - notices and diagnostics every
    configuration carries - and a generated one has to draw them too. Most of what they
    draw is already here as a backdrop or a status icon; the rest is named after the
    first screen that uses it.
    """
    roles: dict[str, int] = {}
    screens = ui_index.screen_slots(payload)[:scaffold.SYSTEM_SCREENS]
    for ordinal, screen in enumerate(screens):
        roots = [slot["program_offset"] for slot in screen["slots"]]
        count = 0
        for block in drawing.program_blocks(payload, roots).values():
            for item in block:
                target = item.get("target")
                if item["opcode"] != "bitmap" or target in taken:
                    continue
                roles[f"platform/screen-{ordinal:02d}-{count}"] = target
                taken.add(target)
                count += 1
    return roles


def activity_picture_roles(payload: bytes, taken: set[int]) -> dict[str, int]:
    """Name the picture every activity's starting screen draws: the infrared waves above
    its icon, which the Help screens draw too.

    An activity's enter handler opens by entering its starting screen, so the screens are
    found from the activities rather than by number; what all of them draw besides the
    backdrop and their own icon is the one picture they share. Activity icons are not
    taken - a build draws each from its type (backends/harmony_one/row_icons.py).
    """
    from afterglow.backends.harmony_one import activity_index

    p = payload
    objects_at = gspm.section_ranges(p)[11][0]

    def atoms(index):
        at = int.from_bytes(p[objects_at + 2 + 3 * index:objects_at + 5 + 3 * index],
                            "little") - gspm.BASE
        return [(int.from_bytes(p[at + 1 + 3 * k:at + 3 + 3 * k], "little"),
                 p[at + 3 + 3 * k]) for k in range(p[at])]

    screens = ui_index.screen_slots(p)
    shared = None
    for context in activity_index.contexts(p):
        enter = [row for row in context["rows"] if row["key_code"] == activity_index.ENTER]
        if not enter or enter[0]["category"] != 0x7F:
            continue
        first = [operand for operand, opcode in atoms(enter[0]["operand"]) if opcode == 0x7E]
        if not first:
            continue
        roots = [slot["program_offset"] for slot in screens[first[0]]["slots"]]
        drawn = {item["target"] for block in drawing.program_blocks(p, roots).values()
                 for item in block if item["opcode"] == "bitmap"} - taken
        shared = drawn if shared is None else shared & drawn
    roles = {}
    if shared and len(shared) == 1:
        roles["activity/sending"] = shared.pop()
    roles.update(activity_frame_roles(payload))
    return roles


class _Modes:
    """A configuration's screens as the remote runs them: each one's list rows, the atoms
    of an object, a timer's record, and the pictures and words its pages draw."""

    def __init__(self, payload: bytes):
        self.p = payload
        self.ranges = gspm.section_ranges(payload)
        self.screens = ui_index.screen_slots(payload)
        self.count = min(len(self.screens), int.from_bytes(
            payload[self.ranges[6][0]:self.ranges[6][0] + 2], "little"))

    def u24(self, at):
        return int.from_bytes(self.p[at:at + 3], "little") - gspm.BASE

    def atoms(self, index):
        p, at = self.p, self.u24(self.ranges[11][0] + 2 + 3 * index)
        return [(int.from_bytes(p[at + 1 + 3 * k:at + 3 + 3 * k], "little"), p[at + 3 + 3 * k])
                for k in range(p[at])]

    def timer(self, index):
        p, at = self.p, self.u24(self.ranges[13][0] + 1 + 3 * index)
        return (int.from_bytes(p[at + 1:at + 4], "little"),
                int.from_bytes(p[at + 4:at + 6], "little"), p[at + 6])

    def rows(self, mode):
        """The mode's list rows, ``(key, operand, opcode)``."""
        p = self.p
        at = self.u24(self.u24(self.ranges[6][0] + 3 + 3 * mode) + 1)
        if p[at]:
            return [(p[at + 1 + 4 * k], int.from_bytes(p[at + 2 + 4 * k:at + 4 + 4 * k],
                                                        "little"), p[at + 4 + 4 * k])
                    for k in range(p[at])]
        return [(p[at + 3 + 5 * k], int.from_bytes(p[at + 4 + 5 * k:at + 6 + 5 * k], "little"),
                 p[at + 6 + 5 * k]) for k in range(p[at + 1])]

    def entered(self, mode, key):
        """The screen ``key`` opens from ``mode``, directly or through an object."""
        for row_key, operand, opcode in self.rows(mode):
            if row_key != key:
                continue
            if opcode == 0x7E:
                return operand
            if opcode == 0x7F:
                for value, code in self.atoms(operand):
                    if code == 0x7E:
                        return value
        return None

    def page(self, mode, *, prologue=False):
        """What the screen's first page draws, in order; with ``prologue``, what the
        fragment it calls draws too."""
        roots = [self.screens[mode]["slots"][0]["program_offset"]]
        listing = ui_index.drawing_program(self.p, roots[0])["instructions"]
        if prologue:
            return [item for block in drawing.program_blocks(self.p, roots).values()
                    for item in block]
        return listing


def charging_picture_roles(payload: bytes, taken: set[int]) -> dict[str, int]:
    """Name the pictures the remote shows while it charges: a battery, then photographs.

    Each is a screen of one full-screen picture whose enter handler starts a timer that
    enters the next, round in a ring; the battery is the one shown longest. The ring is
    followed from the screens' own handlers, so the pictures are named in the order the
    remote shows them - `charging/battery`, then `charging/photo-1` onwards.
    """
    modes = _Modes(payload)
    pictures, following = {}, {}
    for mode in range(modes.count):
        drawn = [item for item in modes.page(mode, prologue=True)
                 if item["opcode"] in ("bitmap", "text", "inline_text")]
        if len(drawn) != 1 or drawn[0]["opcode"] != "bitmap" \
                or (drawn[0]["x"], drawn[0]["y"]) != (0, 0):
            continue
        shape = bitmap.decode(payload, drawn[0]["target"])
        if (shape["width"], shape["height"]) != (176, 220):
            continue
        pictures[mode] = drawn[0]["target"]
        for key, operand, opcode in modes.rows(mode):
            if key != scaffold.ENTER or opcode != 0x7F:
                continue
            for value, code in modes.atoms(operand):
                if code == 0x1F and value >> 8 == 0xEB:
                    duration, target, kind = modes.timer(value & 0xFF)
                    if kind == 0x7E:
                        following[mode] = (target, duration)
    rings = []
    for start in following:
        ring, mode = [], start
        while mode in following and mode in pictures and mode not in ring:
            ring.append(mode)
            mode = following[mode][0]
        if mode == start and len(ring) > 1:
            rings.append(ring)
    if not rings:
        return {}
    # the ring with the longest-shown picture, started there: the battery
    ring = max(rings, key=lambda ring: max(following[mode][1] for mode in ring))
    first = max(ring, key=lambda mode: following[mode][1])
    ring = ring[ring.index(first):] + ring[:ring.index(first)]
    names = ["charging/battery"] + [f"charging/photo-{n}" for n in range(1, len(ring))]
    return {name: pictures[mode] for name, mode in zip(names, ring)
            if pictures[mode] not in taken}


# The keys a Tutorial page is turned with: the side strips.
_PREVIOUS, _NEXT = 0xAE, 0xAF


def tutorial_picture_roles(payload: bytes, taken: set[int]) -> dict[str, int]:
    """Name the Tutorial's pictures, page by page: `tutorial/1` onwards.

    A Tutorial page is the one kind of screen drawn on a blank black screen - its fragment
    fills the screen with black rather than drawing the backdrop - with one picture of the
    remote. The pages are put in order by their own left strips, each going back to the
    page before; the first goes back to none.
    """
    modes = _Modes(payload)
    pages = {}
    for mode in range(modes.count):
        listing = modes.page(mode)
        if not listing or listing[0]["opcode"] != "call":
            continue
        fragment = ui_index.drawing_program(payload, listing[0]["target"])["instructions"]
        if not fragment or fragment[0]["opcode"] != "rectangle" or (
                fragment[0]["width"], fragment[0]["height"], fragment[0]["color"]) != (
                176, 220, 0):
            continue
        drawn = [item["target"] for item in listing if item["opcode"] == "bitmap"]
        if len(drawn) == 1:
            pages[mode] = drawn[0]
    back = {mode: modes.entered(mode, _PREVIOUS) for mode in pages}
    firsts = [mode for mode in pages if back[mode] not in pages]
    if len(firsts) != 1:
        return {}
    order, mode = [], firsts[0]
    while mode is not None and mode not in order:
        order.append(mode)
        mode = next((other for other in pages if back[other] == mode), None)
    return {f"tutorial/{number}": pages[mode] for number, mode in enumerate(order, 1)
            if pages[mode] not in taken}


def activity_frame_roles(payload: bytes) -> dict[str, int]:
    """Name the frames activities are drawn in - blue where a device's are orange and
    Options' green: the Activities menu's row frame, and the frame at each of the six
    button places on an activity's own screens.

    An activity's screen is whatever a switch on `CurrentActivityState` enters for its
    value, so the screens are found from the variable section 0 names; at each button
    place the frame is the first picture drawn there, and the one most of them draw.
    """
    from collections import Counter

    from afterglow.backends.harmony_one import activity_index, named_index

    p = payload
    roles = {}
    menu = activity_index.activity_menu(p)
    screens = ui_index.screen_slots(p)
    if menu is not None:
        frames = Counter()
        for slot in screens[menu["screen"]]["slots"]:
            for block in drawing.program_blocks(p, [slot["program_offset"]]).values():
                for item in block:
                    if item["opcode"] == "bitmap" and item["x"] < 10:
                        size = bitmap.decode(p, item["target"])
                        if size["width"] > 100:
                            frames[item["target"]] += 1
        if frames:
            roles["activity/row-frame"] = frames.most_common(1)[0][0]
    names = named_index.leaf_names(named_index.inspect(p))
    state = [index for index, name in names.items()
             if name.startswith("CurrentActivityState")]
    if not state:
        return roles
    groups_at = gspm.section_ranges(p)[15][0]
    modes = set()
    # every switch on the variable, wherever it is queued: an object or another switch
    def group_programs(group):
        at = int.from_bytes(p[groups_at + 1 + 3 * group:groups_at + 4 + 3 * group],
                            "little") - gspm.BASE + 1
        return [int.from_bytes(p[at + 3 + 5 * k:at + 6 + 5 * k], "little") - gspm.BASE
                for k in range(p[at])]
    switches = [operand for item in command_index.objects(p)
                for operand, opcode in item["atoms"] if opcode == 0x72]
    seen_groups, on_state = set(), set()
    while switches:
        operand = switches.pop()
        group = operand >> 8
        if operand & 0xFF == state[0]:
            on_state.add(group)
        if group in seen_groups:
            continue
        seen_groups.add(group)
        for block in drawing.program_blocks(p, group_programs(group)).values():
            switches += [item["operand"] for item in block
                         if item["opcode"] == "atom" and item["category"] == 0x72]
    for group in on_state:
        for block in drawing.program_blocks(p, group_programs(group)).values():
            modes.update(item["operand"] for item in block
                         if item["opcode"] == "atom" and item["category"] == 0x7E)
    places = [Counter() for _ in compose_positions()]
    for mode in modes:
        if menu is not None and mode == menu["screen"]:
            continue
        for slot in screens[mode]["slots"]:
            seen = set()
            for item in ui_index.drawing_program(p, slot["program_offset"])["instructions"]:
                if item["opcode"] != "bitmap" or (item["x"], item["y"]) in seen:
                    continue
                if (item["x"], item["y"]) in compose_positions():
                    seen.add((item["x"], item["y"]))
                    if bitmap.decode(p, item["target"])["width"] != BUTTON_FRAME_WIDTH:
                        continue
                    places[compose_positions().index((item["x"], item["y"]))][
                        item["target"]] += 1
    for index, counts in enumerate(places):
        if counts:
            roles[f"activity/button-frame/{index}"] = counts.most_common(1)[0][0]
    return roles


BUTTON_FRAME_WIDTH = 81   # a device list's rows start at the first button's place too


def compose_positions() -> list[tuple[int, int]]:
    """Where the six buttons of a page sit, in reading order."""
    from afterglow.backends.harmony_one import pages
    return list(pages.BUTTON_POSITIONS)


def system_templates(payload: bytes) -> list[list[dict]]:
    """The touch templates the platform screens use, in index order from zero.

    A platform screen names its template by index, so these have to be emitted at the
    indices it expects, ahead of any page a project adds. They are not the same as the
    button-count templates a command page chooses from.
    """
    screens = ui_index.screen_slots(payload)[:scaffold.SYSTEM_SCREENS]
    used = sorted({slot["template"] for screen in screens for slot in screen["slots"]})
    if used != list(range(len(used))):
        raise SystemExit(f"the platform screens use templates {used}, not a run from zero")
    zones = ui_index.touch_templates(payload)
    return [
        [{"tag": zone["tag"], "x": zone["x"], "width": zone["width"],
          "y": zone["y"], "height": zone["height"]} for zone in zones[index]]
        for index in used
    ]


# Header rows of the platform screens, by category: null bindings are identical in every
# donor and carried; `0x1f` actions carry the donor's own constants, which is coherent
# because everything else here comes from the same donor. Object bindings on physical
# keys lead into the per-device help flow, so they are dropped rather than faked - but a
# mode's own event handlers are object bindings too, and every mode on a Harmony One has
# them: tag 6 when it is entered, 7 when it is left, 2D, which draws the status overlays.
# Those are carried with the objects they reach, which stay within a few objects.
CARRIED_HEADER_CATEGORIES = (0x00, 0x1F)
CARRIED_HANDLER_TAGS = (0x06, 0x07, 0x2D)
# Opcode 0x7E switches mode by number; past the firmware's forty a number names a donor's
# own screen, which a build does not have.
MODE_SWITCH = 0x7E
OVERLAYS_CARRIED = 4
# Opcode 0x1F bands EB and EA start and stop a section-13 timer by index (read on the
# Harmony 800's firmware, which shares the format). The platform's handlers start them -
# every platform screen runs timer 3 while it is shown, the status bar's refresh - so a
# timer they name is carried with the action it runs, and renumbered.
TIMER_BANDS = (0xEA, 0xEB)
# The platform's own state variables are section 14's first 18 - the clock and the
# platform properties - and its contexts are the image's own. A platform handler that
# writes or tests a variable past those, or pushes, pops or selects a context, is doing
# the donor configuration's bookkeeping, so the instruction is not carried: with a write,
# the `07 FFFF` modifier before it; with a test, the instruction the test guards.
PLATFORM_VARIABLES = 18
WRITE_MODIFIER = (0xFFFF, 0x07)


def donor_bookkeeping(atoms: list) -> tuple[list, int]:
    """Drop the donor's own variables and contexts from a platform object's atoms."""
    kept, dropped, skip = [], 0, False
    for value, category in atoms:
        if skip:
            skip, dropped = False, dropped + 1
            continue
        writes = category >= 0x80 and category & 0x7F >= PLATFORM_VARIABLES
        tests = category in (0x70, 0x71, 0x72) and value & 0xFF >= PLATFORM_VARIABLES
        context = (category == 0x1F and value >> 8 in (0xFF, 0xFE, 0xFD)
                   and value & 0xFF < 0xFC)
        if writes and kept and tuple(kept[-1]) == WRITE_MODIFIER:
            kept.pop()
            dropped += 1
        if writes or tests or context:
            dropped += 1
            skip = tests
            continue
        kept.append([value, category])
    return kept, dropped


CHARGE_BAND = 0xE8
# What a charge context is for, by the battery events it answers (gspm.md).
CHARGE_EVENTS = {frozenset((0x1A, 0x1B, 0x1C, 0x1D)): "normal", frozenset((0x1E,)): "usb",
                 frozenset((0x18, 0x19)): "low"}


def charge_contexts(payload: bytes) -> dict[int, str]:
    """The donor's charge contexts - the ones `1F E8` puts under 0xFC on the key stack -
    by number, named for what they are for, so a build can number its own."""
    from afterglow.backends.harmony_one import activity_index

    out = {}
    for context in activity_index.contexts(payload):
        codes = frozenset(row["key_code"] for row in context["rows"])
        if codes in CHARGE_EVENTS:
            out[context["ordinal"]] = CHARGE_EVENTS[codes]
    return out


def system_screens(payload: bytes, roles: dict[str, int]) -> dict:
    """The firmware's forty screens as a model a build can link afresh.

    Every donor draws these the same way, but no two store them the same bytes: each
    points at pictures and glyph strings that sit elsewhere in each configuration. So they
    are written as blocks whose targets are names - a block index, a picture role, an
    object index - and a `text` instruction becomes `inline_text` with the same glyphs,
    since a shared string is only ever another instruction's inline payload anyway.
    """
    role_of = {target: role for role, target in roles.items()}
    screens = ui_index.screen_slots(payload)[:scaffold.SYSTEM_SCREENS]
    overlays = ui_index.overlay_roots(payload)[:OVERLAYS_CARRIED]
    roots = [slot["program_offset"] for screen in screens for slot in screen["slots"]]
    blocks = drawing.program_blocks(payload, roots + overlays)
    order, queue = {}, list(roots) + list(overlays)
    while queue:
        at = queue.pop(0)
        if at in order:
            continue
        order[at] = len(order)
        for item in blocks[at]:
            if item["opcode"] in ("call", "jump"):
                queue.append(item["target"])
            elif item["opcode"] == "switch":
                queue += [target for _v, target in item["cases"]]
                queue += [target for _l, _h, target in item["ranges"]]
    objects = command_index.objects(payload)
    object_index: dict[int, int] = {}
    carried_objects = []
    timers_start = gspm.section_ranges(payload)[13][0]
    timer_index: dict[int, int] = {}
    carried_timers = []
    dropped_atoms = [0]

    charges = charge_contexts(payload)

    def literal(value: int, category: int):
        """An operand as the model holds it: a timer by its model index, a charge context
        by what it is for, else itself."""
        if category == 0x1F and value >> 8 in TIMER_BANDS:
            return {"timer": carry_timer(value & 0xFF), "band": value >> 8}
        if category == 0x1F and value >> 8 == CHARGE_BAND:
            if value & 0xFF not in charges:
                raise SystemExit(f"a platform handler selects context {value & 0xFF} under "
                                 "0xFC, which answers no battery event")
            return {"charge": charges[value & 0xFF], "band": CHARGE_BAND}
        return value

    def carry_timer(referenced: int) -> int:
        if referenced in timer_index:
            return timer_index[referenced]
        if referenced >= payload[timers_start]:
            raise SystemExit(f"a platform handler names timer {referenced}, past the table")
        timer_index[referenced] = len(carried_timers)
        carried_timers.append(None)
        at = int.from_bytes(
            payload[timers_start + 1 + 3 * referenced:timers_start + 4 + 3 * referenced],
            "little") - gspm.BASE
        flags, duration = payload[at], int.from_bytes(payload[at + 1:at + 4], "little")
        operand = int.from_bytes(payload[at + 4:at + 6], "little")
        opcode = payload[at + 6]
        if opcode == 0x7F:
            action = [{"object": carry(operand)}, opcode]
        elif opcode == MODE_SWITCH and operand >= scaffold.SYSTEM_SCREENS:
            raise SystemExit(f"platform timer {referenced} switches to the donor's mode {operand}")
        else:
            action = [literal(operand, opcode), opcode]
        carried_timers[timer_index[referenced]] = {
            "flags": flags, "duration": duration, "action": action}
        return timer_index[referenced]

    def carry(referenced: int) -> int:
        """Carry an object and everything it calls; return its model index."""
        if referenced in object_index:
            return object_index[referenced]
        object_index[referenced] = len(carried_objects)
        carried_objects.append(None)
        atoms = []
        source, dropped = donor_bookkeeping(objects[referenced]["atoms"])
        dropped_atoms[0] += dropped
        for value, category in source:
            if category == 0x7F:
                atoms.append([{"object": carry(value)}, category])
            else:
                if category == MODE_SWITCH and value >= scaffold.SYSTEM_SCREENS:
                    raise SystemExit(f"platform object {referenced} switches to the "
                                     f"donor's own mode {value}")
                atoms.append([literal(value, category), category])
        carried_objects[object_index[referenced]] = atoms
        return object_index[referenced]

    def instruction(item: dict) -> dict:
        kind = item["opcode"]
        out = {key: value for key, value in item.items() if key != "offset"}
        if kind in ("call", "jump"):
            out["target"] = {"block": order[item["target"]]}
        elif kind == "switch":
            out["cases"] = [[value, order[target]] for value, target in item["cases"]]
            out["ranges"] = [[low, high, order[target]]
                             for low, high, target in item["ranges"]]
        elif kind == "bitmap":
            if item["target"] not in role_of:
                raise SystemExit(f"a platform screen draws {item['target']:#x}, which has no role")
            out["target"] = {"picture": role_of[item["target"]]}
        elif kind == "text":
            out = {"opcode": "inline_text", "x": item["x"], "y": item["y"],
                   "glyphs": item["glyphs"]}
        elif kind == "atom" and item["category"] == 0x7F:
            referenced = item["operand"]
            atoms = objects[referenced]["atoms"]
            if any(category == 0x7F for _value, category in atoms):
                raise SystemExit(f"platform object {referenced} is not a leaf")
            if referenced not in object_index:
                object_index[referenced] = len(carried_objects)
                source, dropped = donor_bookkeeping(atoms)
                dropped_atoms[0] += dropped
                carried_objects.append([[literal(value, category), category]
                                        for value, category in source])
            out["operand"] = {"object": object_index[referenced]}
        return out

    model_blocks = [None] * len(order)
    for at, position in order.items():
        model_blocks[position] = [instruction(item) for item in blocks[at]]
    dropped = 0
    model_screens = []
    for screen in screens:
        trailer = screen["trailer_offset"]
        head = int.from_bytes(payload[trailer + 1:trailer + 4], "little") - gspm.BASE
        header = []
        for row in range(payload[head]):
            key = payload[head + 1 + 4 * row]
            operand = int.from_bytes(payload[head + 2 + 4 * row:head + 4 + 4 * row], "little")
            category = payload[head + 4 + 4 * row]
            if category in CARRIED_HEADER_CATEGORIES:
                header.append([key, literal(operand, category), category])
            elif category == 0x7F and key in CARRIED_HANDLER_TAGS:
                header.append([key, {"object": carry(operand)}, category])
            else:
                dropped += 1
        slots = []
        for slot in screen["slots"]:
            keys = []
            for entry in slot["entries"]:
                if entry["category"] != 0x7F:
                    raise SystemExit("a platform key row binds something other than an object")
                # The OK buttons lead into the rest of the donor's interface; a build
                # sends them to its own first screen instead.
                keys.append({"key": entry["key_code"], "navigate": "first-owned-screen"})
            slots.append({"template": slot["template"],
                          "program": order[slot["program_offset"]], "keys": keys})
        model_screens.append({"flag": payload[trailer], "header": header, "slots": slots})
    return {
        "schema": "afterglow-harmony-one-system-screens/1",
        "blocks": model_blocks,
        "overlays": [order[root] for root in overlays],
        "objects": carried_objects,
        "timers": carried_timers,
        "screens": model_screens,
        "dropped_header_rows": dropped,
        "dropped_donor_atoms": dropped_atoms[0],
    }


# Where the status bar's clock is anchored, measured on the donors: the weekday ends at
# 141, the hour ends at 158 and the minutes start there.
CLOCK_ANCHORS = {"weekday": ("right", 141), "hour": ("right", 158), "minute": ("left", 158)}
CLOCK_SELECTORS = {4: "weekday", 2: "hour", 1: "minute"}


def words_to_labels(model: dict, payload: bytes) -> dict:
    """The platform model with every word replaced by a label naming platform_text's
    table, so no donor's text or language is carried; a build draws them in its own fonts.

    A screen's lines are centred and keyed by its ordinal and line, its title is the
    numbered system message, OK keeps its place, and the clock's weekday, hour and minutes
    are anchored as every donor anchors them."""
    report = glyph_codec.inspect(payload)
    owner, clock = {}, {}
    for ordinal, screen in enumerate(model["screens"]):
        for slot in screen["slots"]:
            owner[slot["program"]] = ordinal
            for item in model["blocks"][slot["program"]]:
                if item["opcode"] == "call":
                    owner[item["target"]["block"]] = ordinal
    for root in model["overlays"]:
        for item in model["blocks"][root]:
            if item["opcode"] == "switch" and item["selector"] in CLOCK_SELECTORS:
                for value, target in item["cases"]:
                    clock[target] = (CLOCK_SELECTORS[item["selector"]], value)
    blocks = []
    for index, block in enumerate(model["blocks"]):
        out, font, lines = [], None, 0
        for item in block:
            if item["opcode"] == "attribute":
                font = item["value"]
            if item["opcode"] not in ("text", "inline_text"):
                out.append(item)
                continue
            words = glyph_codec.decode(bytes.fromhex(item["glyphs"]), report)
            label = {"opcode": "label", "font": font, "y": item["y"]}
            if index in clock:
                kind, value = clock[index]
                align, x = CLOCK_ANCHORS[kind]
                label.update(key=kind, value=value, align=align, x=x)
            elif (item["x"], item["y"]) == (6, 4):
                label.update(key="system-message", value=int(words.split(":")[1]),
                             align="left", x=6)
            elif words == "OK":
                label.update(key="ok", align="left", x=item["x"])
            else:
                label.update(key=f"screen-{owner[index]}", line=lines, align="centre")
                lines += 1
            out.append(label)
        blocks.append(out)
    return {**model, "blocks": blocks}


def write_picture(payload: bytes, target: int, path: Path) -> dict:
    picture = bitmap.decode(payload, target)
    rows = [
        [(0, 0, 0, 0) if pixel is None else (*pixel, 255) for pixel in row]
        for row in picture["rows"]
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(imaging.encode(rows))
    return {"size": [picture["width"], picture["height"]],
            "mode": "raw" if picture["mode"] == bitmap.RAW else "runs"}


def _palette(shapes) -> list[tuple[int, int, int]]:
    """A font's own colours, brightest first. Every donor font uses exactly two."""
    seen = {}
    for shape in shapes:
        for row in shape["rows"]:
            for pixel in row:
                if pixel is not None:
                    seen[pixel] = seen.get(pixel, 0) + 1
    return sorted(seen, key=lambda c: (-(c[0] + c[1] + c[2]), c))


def _recoloured(shape: dict, source: list, target: list) -> dict:
    """Redraw a borrowed glyph in the colours of the font borrowing it.

    A font's glyphs are coloured, not masked, so a glyph taken from another font of the
    same typeface arrives in that font's colours. Filling a gap with one unrecoloured
    leaves a word with letters of two different colours in it, which is what completing
    a font in place does and why this does not use it.
    """
    if not source or not target:
        return shape
    mapping = {
        colour: target[min(index, len(target) - 1)]
        for index, colour in enumerate(source)
    }
    return {**shape, "rows": [
        [None if pixel is None else mapping.get(pixel, pixel) for pixel in row]
        for row in shape["rows"]
    ]}


def complete_glyphs(payload: bytes, fonts: list[dict]) -> dict[int, dict]:
    """Fill each font's empty slots from another font of the same typeface, recoloured."""
    shapes = {}
    for font in fonts:
        shapes[font["attribute"]] = {
            code: bitmap.decode_glyph(payload, item["pointer"] - gspm.BASE)
            for code, item in font["glyphs"].items()
        }
    out = {}
    for font in fonts:
        own = dict(shapes[font["attribute"]])
        palette = _palette(own.values())
        for other in fonts:
            if other["attribute"] == font["attribute"] or other["height"] != font["height"]:
                continue
            donor = shapes[other["attribute"]]
            donor_palette = _palette(donor.values())
            for code, shape in donor.items():
                if code not in own:
                    own[code] = _recoloured(shape, donor_palette, palette)
        out[font["attribute"]] = own
    return out


def write_font(payload: bytes, font: dict, path: Path, shapes: dict) -> dict:
    """Write one font as a strip of glyphs in code order, plus where each one sits."""
    table = glyph_codec.REPERTOIRES.get(font["slots"], {})
    glyphs, width = [], 0
    for code in sorted(shapes):
        shape = shapes[code]
        glyphs.append((code, shape))
        width += shape["width"]
    if not glyphs:
        return {}
    height = max(shape["height"] for _code, shape in glyphs)
    sheet = [[(0, 0, 0, 0)] * width for _ in range(height)]
    placed, cursor = [], 0
    for code, shape in glyphs:
        for y, row in enumerate(shape["rows"]):
            for x, pixel in enumerate(row):
                if pixel is not None:
                    sheet[y][cursor + x] = (*pixel, 255)
        placed.append({"code": code, "x": cursor, "width": shape["width"],
                       "char": table.get(code)})
        cursor += shape["width"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(imaging.encode(sheet))
    return {"height": font["height"], "slots": font["slots"],
            "layout": font["layout"], "glyphs": placed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("donor", type=Path, help="an .EZHex backup or a raw GSPM payload")
    parser.add_argument("directory", type=Path, help="the scaffold to write into")
    parser.add_argument("--complete-fonts", action="store_true",
                        help="fill each font's empty slots from another font of the "
                             "same typeface, recoloured to the borrowing font's palette")
    args = parser.parse_args()

    payload = payload_of(args.donor)
    gspm.validate(payload)

    pictures = {}
    roles = {**picture_roles(payload), **overlay_roles(payload)}
    roles.update(system_picture_roles(payload, set(roles.values())))
    roles.update(activity_picture_roles(payload, set(roles.values())))
    roles.update(charging_picture_roles(payload, set(roles.values())))
    roles.update(tutorial_picture_roles(payload, set(roles.values())))
    for role, target in sorted(roles.items()):
        name = f"images/{role}.png"
        pictures[role] = {"file": name, **write_picture(payload, target, args.directory / name)}

    table = font_index.fonts(payload)
    completed = complete_glyphs(payload, table) if args.complete_fonts else {
        font["attribute"]: {
            code: bitmap.decode_glyph(payload, item["pointer"] - gspm.BASE)
            for code, item in font["glyphs"].items()
        }
        for font in table
    }
    fonts = {}
    for font in table:
        role = f"font-{font['attribute']:02d}"
        name = f"fonts/{role}.png"
        described = write_font(payload, font, args.directory / name,
                               completed[font["attribute"]])
        if described:
            fonts[role] = {"file": name, **described}

    # Touch geometry is panel calibration, not artwork: raw resistive coordinates with
    # their own scale per axis and y measured upwards. It is a property of the hardware,
    # so it belongs beside the platform table rather than being derived.
    templates = {}
    for buttons, template in sorted(resources.catalogue(payload)["page_templates"].items()):
        if template is None:
            continue
        zones = ui_index.touch_templates(payload).get(template)
        if not zones:
            continue
        templates[str(buttons)] = [
            {"tag": zone["tag"], "x": zone["x"], "width": zone["width"],
             "y": zone["y"], "height": zone["height"]}
            for zone in zones
        ]
    platform = args.directory / "platform"
    platform.mkdir(parents=True, exist_ok=True)
    (platform / "touch-templates.json").write_text(
        json.dumps(templates, indent=2, sort_keys=True) + "\n", "utf-8")
    system = system_templates(payload)
    (platform / "system-templates.json").write_text(
        json.dumps(system, indent=2, sort_keys=True) + "\n", "utf-8")
    # The device-menu touch template: three device rows, a header strip and two side
    # strips, identical in every donor, so it is carried once and emitted at whatever
    # index a generated menu screen needs.
    menu = resources.catalogue(payload)["menu"]["template"]
    menu_zones = []
    if menu is not None:
        menu_zones = [
            {"tag": zone["tag"], "x": zone["x"], "width": zone["width"],
             "y": zone["y"], "height": zone["height"]}
            for zone in ui_index.touch_templates(payload)[menu]
        ]
    (platform / "menu-template.json").write_text(
        json.dumps(menu_zones, indent=2, sort_keys=True) + "\n", "utf-8")
    print(f"wrote {len(templates)} page templates and {len(system)} platform templates")
    model = words_to_labels(system_screens(payload, roles), payload)
    (platform / "system-screens.json").write_text(json.dumps(model) + "\n", "utf-8")
    print(f"wrote the platform layer: {len(model['screens'])} screens, "
          f"{len(model['blocks'])} blocks, {len(model['objects'])} objects, "
          f"{len(model['overlays'])} overlays, {model['dropped_header_rows']} header rows dropped")

    manifest = {
        "schema": "afterglow-scaffold-assets/1",
        "remote": "harmony-one",
        "source": "extracted from a Harmony One configuration; artwork only",
        "extractor": "tools/harmony_one_extract_assets.py",
        "pictures": pictures,
        "fonts": fonts,
        # Which font draws what, in the donor. Fonts are emitted in attribute order so
        # the platform screens' attribute numbers keep their meaning, and this is how a
        # build still finds the one that labels a button.
        "font_roles": {
            role: f"font-{attribute:02d}"
            for role, attribute in sorted(resources.catalogue(payload)["fonts"].items())
            if attribute is not None
        },
    }
    (args.directory / "assets.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8")
    print(f"wrote {len(pictures)} pictures and {len(fonts)} fonts into {args.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
