#!/usr/bin/env python3
"""Extract an arch-14 remote's artwork and platform layer from a configuration into a scaffold.

    python3 tools/arch14_extract_assets.py --remote harmony-700 donor.EZHex \
        src/afterglow/scaffolds/harmony-700

## Why this exists

A Harmony 650 or 700 keeps no artwork in firmware: every backdrop, bar and icon it draws is stored
in the configuration, and so are the firmware's own screens - the charging animation, the
battery and USB notices and the diagnostics. A generated configuration has to supply all
of it, so this reads it out of a real configuration as PNG files and a model of those
screens, the way `harmony_one_extract_assets.py` does for the One.

Only artwork and platform state are taken. Nothing that identifies a remote or its owner -
no device names, activities, favourites, account data - is read, let alone written. The
fonts are not taken either: a build draws text from Galmuri, and only each font slot's
height and two colours are read from the donor. The firmware screens' words are not taken:
each is a label naming an entry in the remote's backend's `catalogue.py`.

Format reference: docs/harmony_650_700/gspm.md
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from collections import Counter
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from afterglow import ezhex, imaging, paths, remotes  # noqa: E402

# The remote's own backend modules, set by use() from the profile --remote names: the
# 650's and the 700's are copies of each other, so this tool serves both.
activity_index = bitmap = command_index = drawing = font_index = gspm = scaffold = None
ui_index = importing = labels = None
REMOTE = None
# How many screens the remote's firmware owns before a configuration's own (44 on the 650,
# 49 on the 700): the length of its scaffold's model of them.
SYSTEM_SCREENS = None


def use(remote: str) -> None:
    """Read and write through ``remote``'s backend."""
    import importlib

    global activity_index, bitmap, command_index, drawing, font_index, gspm, scaffold
    global ui_index, importing, labels, REMOTE, SYSTEM_SCREENS
    package = "afterglow.backends." + remotes.get(remote).backend.replace("-", "_")
    (activity_index, bitmap, command_index, drawing, font_index, gspm, scaffold, ui_index,
     importing, labels) = (importlib.import_module(f"{package}.{name}") for name in (
        "activity_index", "bitmap", "command_index", "drawing", "font_index", "gspm",
        "scaffold", "ui_index", "importing", "labels"))
    REMOTE = remote
    SYSTEM_SCREENS = len(json.loads((paths.scaffolds(remote) / "platform" / "system-screens.json")
                                    .read_text("utf-8"))["screens"])

SCREEN = 128
PICTURES = ("bitmap", "sized_bitmap")
# The softkey's label sits on the softkey picture, at the bottom of the screen.
SOFTKEY_TOP = 108


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


class Image:
    """A configuration's screens and what each one draws, read once."""

    def __init__(self, payload: bytes):
        self.p = payload
        self.ranges = gspm.section_ranges(payload)
        self.screens = ui_index.screen_slots(payload)
        self.objects = command_index.objects(payload)
        self.drawn = []
        for screen in self.screens:
            roots = [slot["program_offset"] for slot in screen["slots"]]
            self.drawn.append([item for block in drawing.program_blocks(payload, roots).values()
                               for item in block if item["opcode"] in PICTURES])

    def size(self, target: int) -> tuple[int, int]:
        picture = bitmap.decode(self.p, target)
        return picture["width"], picture["height"]

    def u24(self, at: int) -> int:
        return int.from_bytes(self.p[at:at + 3], "little") - gspm.BASE

    def rows(self, mode: int) -> list[tuple[int, int, int]]:
        """The mode's header rows, ``(key, operand, opcode)``."""
        p = self.p
        at = self.u24(self.screens[mode]["trailer_offset"] + 1)
        return [(p[at + 1 + 4 * k], int.from_bytes(p[at + 2 + 4 * k:at + 4 + 4 * k], "little"),
                 p[at + 4 + 4 * k]) for k in range(p[at])]


def charging_picture_roles(image: Image) -> dict[str, int]:
    """Name the charging animation, `charging/0` onwards: the firmware's first screens, each
    one whole-screen picture and nothing else. Nothing in the configuration chains them -
    their handlers start no timer - so the order is the screens' own."""
    roles = {}
    for mode in range(SYSTEM_SCREENS):
        drawn = image.drawn[mode]
        programs = [ui_index.drawing_program(image.p, slot["program_offset"])["instructions"]
                    for slot in image.screens[mode]["slots"]]
        only_picture = all(item["opcode"] in PICTURES + ("end",)
                           for program in programs for item in program)
        if (len(drawn) != 1 or not only_picture
                or image.size(drawn[0]["target"]) != (SCREEN, SCREEN)):
            break
        roles[f"charging/{mode}"] = drawn[0]["target"]
    return roles if len(roles) > 1 else {}


def corner_kinds(image: Image) -> dict[str, int]:
    """The sending mark and the patches it is drawn over: section 12's corner programs,
    each a switch on variable 17 - the sending flag - whose case 0 draws the page's own
    12 by 10 patch at 114, 112 and whose range 1 to 3 draws the mark there. `corner/device`
    is the one a device's pages and the Devices list queue, `corner/activity` an
    activity's pages' and the Activities menu's, `corner/idle` the rest's; `corner/mark`
    the mark (harmony-explorations, `docs/config-format.md`, "Base slot 11")."""
    reader = importing.Image(image.p)
    start = image.ranges[12][0]
    count = int.from_bytes(image.p[start:start + 2], "little")
    programs = {}
    for entry in range(min(count, 256)):
        at = image.u24(start + 2 + 3 * entry)
        program = ui_index.drawing_program(image.p, at)["instructions"]
        first = program[0] if program else {}
        if (first.get("opcode") == "switch" and not first.get("wide")
                and first.get("selector") == SENDING_FLAG and first["cases"]
                and first["ranges"]):
            draw = lambda block: next(  # noqa: E731
                item["target"] for item in ui_index.drawing_program(image.p, block)["instructions"]
                if item["opcode"] in PICTURES)
            programs[entry] = (draw(first["cases"][0][1]), draw(first["ranges"][0][2]))
    if not programs:
        return {}
    pages = {ordinal for ordinals in importing.command_pages(reader).values()
             for ordinal in ordinals}
    acts = importing.Activities(reader, [], {}, [])
    labels = set(acts.menu_rows().values())
    queued: dict[str, Counter] = {}
    for ordinal, screen in enumerate(reader.screens):
        for slot in screen["slots"]:
            program = ui_index.drawing_program(image.p, slot["program_offset"])["instructions"]
            entries = [item["operand"] & 0xFF for item in program
                       if item["opcode"] == "atom" and item["category"] == 0x73]
            title = next((item["text"] for item in reader.page_text(slot["program_offset"])
                          if (item["x"], item["y"]) == importing.TITLE_XY), "")
            kind = ("device" if ordinal in pages or title == "Devices"
                    else "activity" if title == "Activities" or any(
                        importing._same_title(title, label) for label in labels)
                    else "idle")
            for entry in entries:
                if entry in programs:
                    queued.setdefault(kind, Counter())[entry] += 1
    out = {}
    for kind, counts in sorted(queued.items()):
        out[f"corner/{kind}"] = programs[counts.most_common(1)[0][0]][0]
    out["corner/mark"] = Counter(mark for _patch, mark in programs.values()).most_common(1)[0][0]
    return out


# The rows of Help held's delay menus (650-b screens 128 and 127), which draw on their own
# backdrop in their own font
DELAY_MENU_ROWS = {"Set to default", "Change Delay", "Power On Delay"}


def page_kinds(image: Image) -> dict[str, int]:
    """The household's backdrops by what a page is: `page/device` for a device's pages and
    the Devices list, `page/activity` for an activity's, `page/menu` for the Activities
    menu, each with `-one` for a page of one button or menu row - which draws no lines
    between them; `page/select` and `page/delays` for Help held's device list and menus.
    Each is the picture most such pages draw first; a kind the donor has no page of is not
    named, and a build draws the backdrop there."""
    reader = importing.Image(image.p)
    acts = importing.Activities(reader, [], {}, [])
    starts = set(acts.starts())
    labels = set(acts.menu_rows().values())
    devices = {ordinal for ordinals in importing.command_pages(reader).values()
               for ordinal in ordinals}
    found: dict[str, Counter] = {}
    for ordinal, screen in enumerate(reader.screens):
        for slot in screen["slots"]:
            program = ui_index.drawing_program(image.p, slot["program_offset"])["instructions"]
            first = next((item for item in program if item["opcode"] in PICTURES), None)
            if first is None:
                continue
            rows = [entry for entry in slot["entries"]
                    if entry["key_code"] in importing.CORNER_KEYS]
            title = next((item["text"] for item in reader.page_text(slot["program_offset"])
                          if (item["x"], item["y"]) == importing.TITLE_XY), None)
            if (not slot["entries"] and [entry["key_code"] for entry in
                                         screen["header_entries"]] == [ENTERED]):
                # "Attempting to fix the problem...": it binds only being entered, which
                # sends the codes again
                found.setdefault("page/working", Counter())[first["target"]] += 1
                continue
            texts = {item["text"] for item in reader.page_text(slot["program_offset"])}
            if title == "Select device" or texts & DELAY_MENU_ROWS:
                # Help held's device list and its delay menus, on their own backdrops
                kind = "select" if title == "Select device" else "delays"
                found.setdefault(f"page/{kind}", Counter())[first["target"]] += 1
                continue
            started = {step[1] for entry in rows for step in reader.row(entry)
                       if step[0] == importing.CONTEXT and step[1] in starts}
            if started:
                # a menu row is both keys of a side: count the activities it starts
                rows = rows[:len(started)]
                kind = "menu"
            # an activity's page of one device's buttons is the activity's, by its title
            elif title and any(importing._same_title(title, label) for label in labels):
                kind = "activity"
            elif ordinal in devices:
                kind = "device"
            else:
                continue
            if len(rows) <= 1:
                kind += "-one"
            found.setdefault(f"page/{kind}", Counter())[first["target"]] += 1
    return {role: counts.most_common(1)[0][0] for role, counts in sorted(found.items())}


def picture_roles(image: Image) -> dict[str, int]:
    """Name every picture the configuration's screens draw.

    The backdrop is the whole-screen picture most screens draw first; the softkey and the
    title bar are the two pictures drawn at a declared size, the softkey a whole screen with
    only its button drawn and the title bar a strip. Whatever only the firmware's screens draw
    is named after the first of them that draws it. The rest are the pages' own backdrops,
    named by what a page is (page_kinds), then `page/<n>` in the order screens first draw
    them, and the small marks in a page's corner,
    `corner/<n>`.
    """
    uses: Counter = Counter()
    first_owned: dict[int, int] = {}
    platform: dict[int, tuple[int, int]] = {}
    sized: Counter = Counter()
    for mode, drawn in enumerate(image.drawn):
        for count, item in enumerate(drawn):
            target = item["target"]
            uses[target] += 1
            if item["opcode"] == "sized_bitmap":
                sized[target] += 1
            if mode < SYSTEM_SCREENS:
                platform.setdefault(target, (mode, count))
            else:
                first_owned.setdefault(target, mode)
    roles = charging_picture_roles(image)
    taken = set(roles.values())

    whole = [target for target in uses if image.size(target) == (SCREEN, SCREEN)
             and target not in sized and target not in taken]
    if whole:
        roles["backdrop"] = max(whole, key=lambda target: uses[target])
    for target in sorted(sized, key=lambda target: -sized[target]):
        width, height = image.size(target)
        role = "softkey" if (width, height) == (SCREEN, SCREEN) else "title-bar"
        if width == SCREEN and role not in roles:
            roles[role] = target
    taken = set(roles.values())

    numbers: Counter = Counter()
    for target, (mode, _count) in sorted(platform.items(), key=lambda pair: pair[1]):
        if target in taken or target in first_owned:
            continue
        roles[f"platform/screen-{mode:02d}-{numbers[mode]}"] = target
        numbers[mode] += 1
        taken.add(target)
    for role, target in {**page_kinds(image), **corner_kinds(image)}.items():
        roles[role] = target
        taken.add(target)
    pages = corners = 0
    for target, _mode in sorted(first_owned.items(), key=lambda pair: (pair[1], pair[0])):
        if target in taken:
            continue
        if image.size(target) == (SCREEN, SCREEN):
            roles[f"page/{pages}"] = target
            pages += 1
        else:
            roles[f"corner/{corners}"] = target
            corners += 1
        taken.add(target)
    return roles


# Header rows of the platform screens, by category: null bindings, `0x1f` actions and the
# `07` instructions (an Exit's `07 FFFC`) as they are; every object a row runs, with the
# objects it reaches; and writes of the platform's own variables (below).
CARRIED_HEADER_CATEGORIES = (0x00, 0x07, 0x1F)
CARRIED_HANDLER_TAGS = (0x06, 0x07, 0x2D)
MODE_SWITCH = 0x7E
TIMER_BANDS = (0xEA, 0xEB)
CHARGE_BAND = 0xE8
PLATFORM_VARIABLES = 18
WRITE_MODIFIER = (0xFFFF, 0x07)


def platform_variables(image: Image) -> list[int]:
    """The variables the firmware's screens keep for themselves, though the donor numbers
    them among its own: those a screen's header writes - the battery notice flag - and
    those an object a screen's key runs writes directly - the USB screen's state
    (docs/harmony_650_700/gspm.md, "The battery notice flag"). A build gives them numbers
    of its own."""
    found = []
    for mode in range(SYSTEM_SCREENS):
        for key, operand, category in image.rows(mode):
            writes = []
            if category >= 0x80:
                writes = [category & 0x7F]
            elif category == 0x7F and key not in CARRIED_HANDLER_TAGS:
                writes = [atom & 0x7F for _value, atom in image.objects[operand]["atoms"]
                          if atom >= 0x80]
            found += [variable for variable in writes
                      if variable >= PLATFORM_VARIABLES and variable not in found]
    return found


def donor_bookkeeping(atoms: list, platform: list[int] = ()) -> tuple[list, int]:
    """Drop the donor's own variables and contexts from a platform object's atoms; the
    platform's variables are kept, by their index in ``platform``."""
    kept, dropped, skip = [], 0, False
    for value, category in atoms:
        if skip:
            skip, dropped = False, dropped + 1
            continue
        if category >= 0x80 and category & 0x7F in platform:
            kept.append([value, {"write": platform.index(category & 0x7F)}])
            continue
        if category in (0x70, 0x71, 0x72) and value & 0xFF in platform:
            kept.append([{"variable": platform.index(value & 0xFF), "high": value >> 8},
                         category])
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


def charge_contexts(payload: bytes) -> dict[int, str]:
    """The donor's charge contexts - the ones `1F E8` puts under 0xFC on the key stack -
    by number, named by the battery events each answers."""
    events = {frozenset((0x1A, 0x1B, 0x1C, 0x1D)): "normal", frozenset((0x1E,)): "usb",
              frozenset((0x18, 0x19)): "low"}
    out = {}
    for context in activity_index.contexts(payload):
        codes = frozenset(row["key_code"] for row in context["rows"])
        if codes in events:
            out[context["ordinal"]] = events[codes]
    return out


def system_screens(image: Image, roles: dict[str, int], platform: list[int]) -> dict:
    """The firmware's screens as a model a build links afresh: blocks whose targets are
    names - a block index, a picture role, an object index - rather than addresses."""
    payload = image.p
    role_of = {target: role for role, target in roles.items()}
    screens = image.screens[:SYSTEM_SCREENS]
    roots = [slot["program_offset"] for screen in screens for slot in screen["slots"]]
    blocks = drawing.program_blocks(payload, roots)
    order, queue = {}, list(roots)
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
    objects = image.objects
    object_index: dict[int, int] = {}
    carried_objects: list = []
    timers_start = image.ranges[13][0]
    timer_index: dict[int, int] = {}
    carried_timers: list = []
    dropped_atoms = [0]
    charges = charge_contexts(payload)

    def literal(value: int, category: int):
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
        at = image.u24(timers_start + 1 + 3 * referenced)
        flags, duration = payload[at], int.from_bytes(payload[at + 1:at + 4], "little")
        operand = int.from_bytes(payload[at + 4:at + 6], "little")
        opcode = payload[at + 6]
        if opcode == 0x7F:
            action = [{"object": carry(operand)}, opcode]
        elif opcode == MODE_SWITCH and operand >= SYSTEM_SCREENS:
            raise SystemExit(f"platform timer {referenced} switches to the donor's mode {operand}")
        else:
            action = [literal(operand, opcode), opcode]
        carried_timers[timer_index[referenced]] = {
            "flags": flags, "duration": duration, "action": action}
        return timer_index[referenced]

    def carry(referenced: int) -> int:
        if referenced in object_index:
            return object_index[referenced]
        object_index[referenced] = len(carried_objects)
        carried_objects.append(None)
        atoms = []
        source, dropped = donor_bookkeeping(objects[referenced]["atoms"], platform)
        dropped_atoms[0] += dropped
        for value, category in source:
            if category == 0x7F:
                atoms.append([{"object": carry(value)}, category])
            else:
                if category == MODE_SWITCH and value >= SYSTEM_SCREENS:
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
        elif kind in PICTURES:
            if item["target"] not in role_of:
                raise SystemExit(f"a platform screen draws {item['target']:#x}, which has no role")
            out["target"] = {"picture": role_of[item["target"]]}
        elif kind == "text":
            out = {"opcode": "inline_text", "x": item["x"], "y": item["y"],
                   "glyphs": item["glyphs"]}
        elif kind == "atom":
            raise SystemExit("a platform screen's drawing runs an atom; arch 14's carry no "
                             "overlays, so it cannot be linked")
        return out

    model_blocks = [None] * len(order)
    for at, position in order.items():
        model_blocks[position] = [instruction(item) for item in blocks[at]]
    dropped = 0
    model_screens = []
    for mode, screen in enumerate(screens):
        header = []
        for key, operand, category in image.rows(mode):
            if category in CARRIED_HEADER_CATEGORIES:
                header.append([key, literal(operand, category), category])
            elif category == 0x7F:
                header.append([key, {"object": carry(operand)}, category])
            elif category >= 0x80 and category & 0x7F in platform:
                header.append([key, operand, {"write": platform.index(category & 0x7F)}])
            else:
                dropped += 1
        slots = []
        for slot in screen["slots"]:
            if slot["entries"]:
                raise SystemExit(f"platform screen {mode} binds keys; none measured does")
            slots.append({"program": order[slot["program_offset"]], "keys": []})
        model_screens.append({"flag": payload[screen["trailer_offset"]], "header": header,
                              "slots": slots})
    return {
        "schema": "afterglow-arch14-system-screens/1",
        "blocks": model_blocks,
        "objects": carried_objects,
        "timers": carried_timers,
        # the platform's own variables, which a build numbers among its own (main fills
        # them in, shared with the wiring)
        "variables": [],
        "screens": model_screens,
        "dropped_header_rows": dropped,
        "dropped_donor_atoms": dropped_atoms[0],
    }


def platform_constants(image: Image) -> dict:
    """What a build writes as the donor holds it, being the model's and not the household's:
    sections 1 and 2, the key table's first key (section 4's head), section 15's platform
    table, and the offsets into it section 16 names (docs/harmony_650_700/gspm.md,
    "The wiring")."""
    p, ranges = image.p, image.ranges
    start, end = ranges[15]
    tail_at = start + 1 + 3 * p[start]
    index_start, _index_end = ranges[16]
    offsets = [image.u24(index_start + 1 + 3 * k) - tail_at for k in range(p[index_start])]
    head = ranges[4][0]
    return {
        "section1": p[ranges[1][0]:ranges[1][1]].hex(),
        "section2": p[ranges[2][0]:ranges[2][1]].hex(),
        "key_table_first": int.from_bytes(p[head:head + 3], "little"),
        "key_table_count": int.from_bytes(p[head + 3:head + 6], "little"),
        "tail": p[tail_at:end].hex(),
        "tail_offsets": offsets,
        "section17": p[ranges[17][0]:ranges[17][1]].hex(),
        "screens": SYSTEM_SCREENS,
    }


STORE = 0xED00       # `1F EDvv`: write the accumulator into variable vv
SENDING_FLAG = 17    # the firmware's variable 1 to 3 while codes go out
ENTERED = 0x06       # the event a screen's list binds for being entered


class Wiring:
    """The firmware's own handling a configuration carries - its events, the contexts every
    key passes through, its timers, the list it starts from, mode 0's list - as a model a
    build links afresh, read the way `system_screens` reads the firmware's screens.

    What in it is the household's is left as a named hole a build fills from its project:
    the Off context and each activity's, the activity keys, the map from where the remote
    is to the screen it goes back to, the Help flow's per-device screens, and a device's
    own variables (docs/harmony_650_700/gspm.md, "The wiring")."""

    def __init__(self, image: Image, platform: list[int]):
        self.image, self.p, self.platform = image, image.p, platform
        self.fw = SYSTEM_SCREENS
        reader = importing.Image(image.p)
        self.names = reader.names
        acts = importing.Activities(reader, [], {}, [])
        self.off = acts.off_context()
        self.activities = set(acts.starts())
        menu = activity_index.activity_menu(image.p)
        self.menu = menu["screen"] if menu else None
        self.location = next((variable for variable, name in self.names.items()
                              if name.startswith("CurrentLocation")), None)
        self.groups = importing.switch_tables(image.p)
        self.objects, self.object_index = [], {}
        self.groups_out, self.group_index = [], {}
        self.holes = Counter()

    def variable(self, variable: int):
        if variable < PLATFORM_VARIABLES:
            return variable
        if variable == self.location:
            return {"hole": "location"}
        if variable in self.names:
            self.holes[f"device variable {self.names[variable]}"] += 1
            return {"hole": "device-variable"}
        if variable not in self.platform:
            self.platform.append(variable)
        return {"variable": self.platform.index(variable)}

    def household_group(self, group: int) -> bool:
        """A switch table some case of which enters a screen of the household's."""
        blocks = [block for _value, block in self.groups[group]["cases"]]
        pending, seen = [], set()
        for block in blocks:
            for item in ui_index.drawing_program(self.p, block)["instructions"]:
                if item["opcode"] == "atom":
                    pending.append((item["operand"], item["category"]))
        while pending:
            operand, category = pending.pop()
            if category == 0x7E and operand >= self.fw:
                return True
            if category == 0x7F and operand not in seen:
                seen.add(operand)
                pending += list(self.image.objects[operand]["atoms"])
        return False

    def atom(self, operand: int, category: int) -> list:
        if category == 0x7F and self.restores_delays(operand):
            # the start's restore of the delays saved on the remote, one list per device of
            # the donor's, keyed by its ids (docs/harmony_650_700/gspm.md, "Delays"): a
            # build restores its own devices', or none
            self.holes["the delay restore"] += 1
            return [{"hole": "delay-restore"}, category]
        if category == 0x7F:
            return [{"object": self.carry(operand)}, category]
        if category == 0x7E:
            if operand < self.fw:
                return [operand, category]
            if operand == self.menu:
                return [{"screen": "activity-menu"}, category]
            self.holes["a household screen"] += 1
            return [{"hole": "screen"}, category]
        if category == 0x1F and operand >> 8 == STORE >> 8:
            # `1F EDvv`: the accumulator into variable vv - a delay restored from the
            # remote's settings store at start, into a device's delay variable
            # (docs/harmony_650_700/gspm.md, "Delays"). A device's is the donor's, and a
            # build has no such variable: a hole, never the donor's number.
            role = self.variable(operand & 0xFF)
            if isinstance(role, dict) and "hole" in role:
                return [{"hole": "device-variable"}, category]
            return [{"store": role}, category]
        if category == 0x1F and operand >> 8 == 0xFF:
            context = operand & 0xFF
            if context == self.off:
                return [{"context": "off"}, category]
            if context in self.activities:
                self.holes["an activity's context"] += 1
                return [{"hole": "activity-context"}, category]
            return [{"context": context}, category]
        if category == 0x72:
            group, variable = operand >> 8, operand & 0xFF
            if variable == self.location:
                return [{"hole": "location-map"}, category]
            if self.household_group(group):
                self.holes["a Help switch"] += 1
                return [{"hole": "help"}, category]
            return [{"group": self.carry_group(group), "variable": self.variable(variable)},
                    category]
        if category in (0x70, 0x71):
            return [{"test": self.variable(operand & 0xFF), "high": operand >> 8}, category]
        if category >= 0x80:
            return [operand, {"write": self.variable(category & 0x7F)}]
        return [operand, category]

    def restores_delays(self, index: int) -> bool:
        """Whether object ``index`` is the sweep that restores saved delays: `07 FFF3`,
        the devices' restore lists, `07 FFF2`."""
        atoms = self.image.objects[index]["atoms"]
        return (len(atoms) >= 2 and tuple(atoms[0]) == (0xFFF3, 0x07)
                and tuple(atoms[-1]) == (0xFFF2, 0x07))

    def carry(self, index: int) -> int:
        if index in self.object_index:
            return self.object_index[index]
        self.object_index[index] = len(self.objects)
        self.objects.append(None)
        self.objects[self.object_index[index]] = [
            self.atom(operand, category) for operand, category in self.image.objects[index]["atoms"]]
        return self.object_index[index]

    def carry_group(self, group: int) -> int:
        if group in self.group_index:
            return self.group_index[group]
        self.group_index[group] = len(self.groups_out)
        self.groups_out.append(None)
        cases = []
        for value, block in self.groups[group]["cases"]:
            atoms = [self.atom(item["operand"], item["category"])
                     for item in ui_index.drawing_program(self.p, block)["instructions"]
                     if item["opcode"] == "atom"]
            cases.append([value, atoms])
        self.groups_out[self.group_index[group]] = {"cases": cases}
        return self.group_index[group]

    def model(self) -> dict:
        p, ranges = self.p, self.image.ranges
        start = ranges[9][0]
        lead = [self.atom(int.from_bytes(p[start + 1 + 3 * k:start + 3 + 3 * k], "little"),
                          p[start + 3 + 3 * k]) for k in range(p[start])]
        timers = []
        start = ranges[13][0]
        for k in range(p[start]):
            at = self.image.u24(start + 1 + 3 * k)
            action = self.atom(int.from_bytes(p[at + 4:at + 6], "little"), p[at + 6])
            timers.append({"flags": p[at], "duration": int.from_bytes(p[at + 1:at + 4], "little"),
                           "action": action})
        contexts = []
        image = importing.Image(p)
        for context in image.contexts:
            if context["ordinal"] == self.off or context["ordinal"] in self.activities:
                continue
            rows = []
            for row in context["rows"]:
                # an activity key is the household's where it starts an activity or says
                # there is none on it; the contexts every key passes down through relight
                # the screen for it as for any other key
                steps = image.row(row) if row["key_code"] in ACTIVITY_KEY_CODES else []
                if any(step[0] in (importing.CONTEXT, importing.MODE) for step in steps):
                    rows.append({"key": row["key_code"], "flags": row["flags"],
                                 "action": [{"hole": "activity-key"}, 0]})
                    continue
                rows.append({"key": row["key_code"], "flags": row["flags"],
                             "action": self.atom(row["operand"], row["category"])})
            contexts.append({"ordinal": context["ordinal"], "form": context["form"],
                             "rows": rows})
        at = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC)
        mode_zero = [[p[at + 1 + 4 * k]] + self.atom(
            int.from_bytes(p[at + 2 + 4 * k:at + 4 + 4 * k], "little"), p[at + 4 + 4 * k])
            for k in range(p[at])]
        return {"schema": "afterglow-arch14-wiring/1", "lead": lead, "timers": timers,
                "contexts": contexts, "mode_zero": mode_zero, "objects": self.objects,
                "groups": self.groups_out, "off_context": self.off,
                "holes": dict(sorted(self.holes.items()))}


# The activity keys, whose rows an activity fills or the "add an Activity" screen does.
ACTIVITY_KEY_CODES = (0x81, 0x85, 0x87)


def words_to_labels(model: dict) -> dict:
    """The platform model with every word replaced by a label, so no donor's text or
    language is carried: a screen's lines are keyed by its ordinal and line - left-aligned
    where the donor drew them from the left edge, centred otherwise - and the label on the
    softkey is `exit`, the only word any firmware screen puts there."""
    owner = {}
    for ordinal, screen in enumerate(model["screens"]):
        for slot in screen["slots"]:
            owner[slot["program"]] = ordinal
    blocks = []
    for index, block in enumerate(model["blocks"]):
        out, font, lines = [], None, 0
        for item in block:
            if item["opcode"] == "attribute":
                font = item["value"]
            if item["opcode"] not in ("text", "inline_text"):
                out.append(item)
                continue
            label = {"opcode": "label", "font": font, "y": item["y"]}
            if item["y"] >= SOFTKEY_TOP:
                label.update(key="exit", align="centre")
            else:
                label.update(key=f"screen-{owner[index]}", line=lines,
                             align="left" if item["x"] == 0 else "centre")
                if item["x"] == 0:
                    label["x"] = 0
                lines += 1
            out.append(label)
        blocks.append(out)
    return {**model, "blocks": blocks}


def write_picture(payload: bytes, target: int, path: Path) -> dict:
    picture = bitmap.decode(payload, target)
    rows = [[(0, 0, 0, 0) if pixel is None else (*pixel, 255) for pixel in row]
            for row in picture["rows"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(imaging.encode(rows))
    return {"size": [picture["width"], picture["height"]],
            "mode": "raw" if picture["mode"] == bitmap.RAW else "runs"}


# The faces a slot is drawn in (SIL Open Font License): Galmuri Afterglow, 9 and 11 pixels,
# regular and bold - the One's and the 800's (tools/galmuri_afterglow.py) - by the look
# each slot gets: `bold`, `large` (the 11s), both, or neither.
FACES = {"regular": ("harmony-one", "GalmuriAfterglow9.bdf.gz"),
         # the slots of 11 pixels and less: the 9 needs 12 rows, the 7 ten
         "small": ("harmony-one", "GalmuriAfterglow7.bdf.gz"),
         "bold": ("harmony-one", "GalmuriAfterglow9-Bold.bdf.gz"),
         "large": ("harmony-800", "GalmuriAfterglow11.bdf.gz"),
         "large-bold": ("harmony-800", "GalmuriAfterglow11-Bold.bdf.gz")}
LARGE_SLOT = 14                     # the shortest slot an 11-pixel face fits
LOOKS = {"regular": {}, "bold": {"bold": True}, "large": {"large": True},
         "large-bold": {"large": True, "bold": True}}


def _bdf(path: Path) -> tuple[dict, dict]:
    """A BDF face's advance and inked pixels, by character."""
    import gzip

    widths, ink, char, bits = {}, {}, None, False
    for line in gzip.open(path, "rt", errors="replace"):
        if line.startswith("ENCODING"):
            char = chr(int(line.split()[1]))
            ink[char] = 0
        elif line.startswith("DWIDTH") and char is not None:
            widths[char] = int(line.split()[1])
        elif line.startswith("BITMAP"):
            bits = True
        elif line.startswith("ENDCHAR"):
            bits = False
        elif bits and char is not None:
            ink[char] += bin(int(line.strip(), 16)).count("1")
    return widths, ink


def font_faces(payload: bytes) -> dict[str, str]:
    """The face each font slot is drawn in: the one whose letters are closest to the
    donor's in the strings its screens draw - their widths, and how much of each glyph is
    ink, so that bold is told from regular. A 650's and a 700's button labels, menu rows
    and answers measure as the 11-pixel bold, their titles, messages, notices and softkey
    words as the 9-pixel bold; Galmuri 9 regular, which every slot used before, fits only
    their smallest."""
    import math
    from collections import defaultdict

    faces = {kind: _bdf(paths.scaffolds(scaffold) / "fonts" / "galmuri" / name)
             for kind, (scaffold, name) in FACES.items()}
    image = importing.Image(payload)
    fonts = {font["attribute"]: font for font in font_index.fonts(payload)}
    samples = defaultdict(dict)
    for screen in image.screens:
        for slot in screen["slots"]:
            items = {(item["x"], item["y"]): item["text"]
                     for item in image.page_text(slot["program_offset"])}
            attribute = None
            for item in ui_index.drawing_program(payload, slot["program_offset"])["instructions"]:
                if item["opcode"] == "attribute":
                    attribute = item["value"]
                    continue
                if item["opcode"] not in ("text", "inline_text") or attribute not in fonts:
                    continue
                codes = bytes.fromhex(item["glyphs"]) if item.get("glyphs") else b""
                glyphs = fonts[attribute]["glyphs"]
                text = items.get((item["x"], item["y"]))
                if not text or len(text) != len(codes) or not all(c in glyphs for c in codes):
                    continue
                ink = 0
                for code in codes:
                    rows, _width = ui_index.glyph_mask(payload, glyphs[code]["offset"])
                    ink += sum(sum(1 for value in row if value) if not isinstance(row, (bytes, bytearray))
                               else bin(int.from_bytes(bytes(row), "big")).count("1") for row in rows)
                samples[attribute].setdefault(text, (sum(glyphs[c]["width"] for c in codes), ink))
    out = {}
    for attribute, seen in samples.items():
        scores = {}
        for kind, (widths, inks) in faces.items():
            if kind not in LOOKS:
                continue
            usable = [(text, width, ink) for text, (width, ink) in list(seen.items())[:60]
                      if ink and all(char in widths for char in text)]
            if not usable:
                continue
            error = sum(abs(sum(widths[c] for c in text) - width) / len(text)
                        for text, width, _ink in usable) / len(usable)
            weight = sum(sum(inks[c] for c in text) / ink for text, _width, ink in usable) / len(usable)
            scores[kind] = error + abs(math.log(weight))
        # the 11-pixel faces need 14 rows: in a shorter slot they are clipped, losing
        # accents and running letters together, so the 9-pixel bold stands in
        if fonts[attribute]["height"] < LARGE_SLOT:
            scores = {kind: score for kind, score in scores.items() if not kind.startswith("large")}
        if scores:
            out[f"font-{attribute:02d}"] = min(scores, key=scores.get)
    return out


def font_looks(payload: bytes) -> dict[str, dict]:
    """Each font slot's height and colours: the colour it draws most, and the other one as
    its shadow - or none, for a slot drawn in one colour - and its face (font_faces)."""
    faces = font_faces(payload)
    out = {}
    for font in font_index.fonts(payload):
        seen: Counter = Counter()
        for item in font["glyphs"].values():
            for row in bitmap.decode_glyph(payload, item["pointer"] - gspm.BASE)["rows"]:
                seen.update(pixel for pixel in row if pixel is not None)
        colours = [list(colour) for colour, _count in seen.most_common(2)]
        if not colours:
            continue
        out[f"font-{font['attribute']:02d}"] = {
            "height": font["height"],
            "look": {"colour": colours[0], "shadow": colours[1] if len(colours) > 1 else None,
                     **LOOKS[faces.get(f"font-{font['attribute']:02d}", "regular")]},
        }
    return out


def font_roles(payload: bytes) -> dict[str, str]:
    """Which font slot draws what on the donor's own screens: the page title and its counter
    in the title strip, the softkey's label, a command page's corner labels, a menu's row
    labels, a start-up screen's title (`notice`) and messages - each the slot drawn most
    often in that part."""
    from collections import defaultdict

    image = importing.Image(payload)
    pages = {ordinal for ordinals in importing.command_pages(image).values()
             for ordinal in ordinals}
    seen: dict[str, Counter] = defaultdict(Counter)
    for screen in image.screens[SYSTEM_SCREENS:]:
        # a start-up screen - "Starting ...", "Turning system off" - binds every key to
        # nothing while its codes go out
        blocking = (len(screen["header_entries"]) >= 50
                    and not any(entry["category"] for entry in screen["header_entries"]))
        for slot in screen["slots"]:
            sends = bool(importing._touch_sends(image, slot))
            menu = not sends and any(
                step[0] == importing.CONTEXT
                or (step[0] == importing.MODE and step[1] in pages)
                for entry in slot["entries"] for step in image.row(entry))
            for item in labels.screen_text(payload, slot["program_offset"], image.text):
                if item["attribute"] is None:
                    continue
                if item["text"] in ("No", "Yes") and 76 <= item["y"] < 90:
                    # the Help flow's answers, beside the keys below the screen
                    part = "answer"
                elif item["text"] in DELAY_MENU_ROWS:
                    # Help held's delay menus: "Set to default", "Change Delay"
                    part = "delay_row"
                elif blocking and item["y"] < 40:
                    # a start-up screen's "Starting ..." and All Off's "Turning system off",
                    # at y 5 in the firmware's message font
                    part = "notice"
                elif item["y"] < 8:
                    part = "title" if item["x"] < 60 else "indicator"
                elif item["y"] >= SOFTKEY_TOP:
                    part = "softkey"
                else:
                    part = "button" if sends else "menu_row" if menu else "message"
                seen[part][item["attribute"]] += 1
    return {part: f"font-{counts.most_common(1)[0][0]:02d}"
            for part, counts in sorted(seen.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remote", required=True,
                        help="the profile the scaffold is for: harmony-650 or harmony-700")
    parser.add_argument("donor", type=Path, help="an .EZHex backup or a raw GSPM payload")
    parser.add_argument("directory", type=Path, help="the scaffold to write into")
    args = parser.parse_args()
    use(args.remote)

    payload = payload_of(args.donor)
    gspm.validate(payload)
    image = Image(payload)

    roles = picture_roles(image)
    pictures = {}
    for role, target in sorted(roles.items()):
        name = f"images/{role}.png"
        pictures[role] = {"file": name, **write_picture(payload, target, args.directory / name)}

    # The typeface is Galmuri Afterglow, as the One's and the 800's scaffolds ship it (SIL
    # Open Font License): the four faces the slots are drawn in, and the licence.
    target = args.directory / "fonts" / "galmuri"
    target.mkdir(parents=True, exist_ok=True)
    for scaffold, name in [*FACES.values(), ("harmony-one", "OFL.txt")]:
        shutil.copyfile(paths.scaffolds(scaffold) / "fonts" / "galmuri" / name, target / name)

    platform = args.directory / "platform"
    platform.mkdir(parents=True, exist_ok=True)
    shared = platform_variables(image)
    wiring = Wiring(image, shared).model()
    model = words_to_labels(system_screens(image, roles, shared))
    initial = {record["property_id"]: record
               for record in activity_index.engine_records(payload)}
    variables = [{"initial": initial[variable]["initial"], "limit": initial[variable]["limit"]}
                 for variable in shared]
    model["variables"] = wiring["variables"] = variables
    # which notice each screen with words shows (catalogue.NOTICES, by name) is the
    # scaffold's own record: kept from the one being redrawn, and checked on load
    previous = platform / "system-screens.json"
    if previous.is_file():
        model["notices"] = json.loads(previous.read_text("utf-8")).get("notices", {})
    (platform / "system-screens.json").write_text(json.dumps(model) + "\n", "utf-8")
    (platform / "wiring.json").write_text(json.dumps(wiring) + "\n", "utf-8")
    (platform / "platform.json").write_text(
        json.dumps(platform_constants(image), indent=1) + "\n", "utf-8")
    print(f"wrote the wiring: {len(wiring['objects'])} objects, {len(wiring['groups'])} "
          f"switch tables, {len(wiring['timers'])} timers, {len(wiring['contexts'])} "
          f"contexts, holes {wiring['holes']}")
    print(f"wrote the platform layer: {len(model['screens'])} screens, "
          f"{len(model['blocks'])} blocks, {len(model['objects'])} objects, "
          f"{len(model['timers'])} timers, {model['dropped_header_rows']} header rows dropped, "
          f"{model['dropped_donor_atoms']} donor atoms dropped")

    manifest = {
        "schema": "afterglow-scaffold-assets/1",
        "remote": REMOTE,
        "source": f"extracted from a {remotes.get(REMOTE).model} configuration; artwork only",
        "extractor": "tools/arch14_extract_assets.py",
        "pictures": pictures,
        "fonts": font_looks(payload),
        # Which font draws what in the donor. Fonts are emitted in attribute order so the
        # firmware screens' attribute numbers keep their meaning; this is how a build finds
        # the one for each part.
        "font_roles": font_roles(payload),
        "typeface": {kind: f"fonts/galmuri/{name}" for kind, (_s, name) in FACES.items()},
    }
    (args.directory / "assets.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8")
    print(f"wrote {len(pictures)} pictures and {len(manifest['fonts'])} font slots "
          f"into {args.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
