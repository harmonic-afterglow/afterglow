"""Build an arch-14 image - a Harmony 650's - from a project and the scaffold, and nothing
else.

The scaffold carries the platform as models: the firmware's own screens
(platform/system-screens.json), the wiring that connects the firmware's events to a
configuration (platform/wiring.json), the model's constants (platform/platform.json), the
pictures and the fonts' looks. A build numbers everything itself - screens, objects,
contexts, variables, switch tables - fills the models' holes from the project, draws the
project's own screens, and lays the whole out with link.py.

What a build adds for the household, in screen order after the firmware's: the
Activities menu and the Devices list, which open each other through the centre key, each
device's pages, then each activity's. An activity is a context, as on the One: entering it
sets the devices' power and input variables, whose transitions send; picking it again
re-sends its inputs; Off is the context that turns them off. The activity keys start the
first three activities in menu order, as the 700 measured binds its two; a key with no
activity shows the "add an Activity" notice, as Logitech's configurations do.

Format reference: docs/harmony_650_700/gspm.md
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import activities, activity_index, catalogue, drawing, keys, platform_text, scaffold, \
    structures
from .actions import Actions
from .devices import device_state_records, waits
from .link import Pieces
from .structures import (
    COMPARE, DRAW_OVERLAY, ENTER_MODE, OBJECT_ATOM, engine_record, name_chain,
    name_record, object_body, timer_record)

SCREEN = 128
CORNERS = 4                         # a page's labels, one beside each key at the screen
LABEL_ROOM = 59                     # a corner label's width: the widest Logitech's draw
# A corner label as Logitech's pages place it, on all three configurations measured: one
# line low in its corner, beside its key - y 40 above the middle, 90 below - and two lines
# from 25 or 75, a font's height apart; 3 px in from the left, ending at 125 on the right.
LABEL_ONE_Y = (40, 90)
LABEL_TWO_Y = (25, 75)
LABEL_LEFT, LABEL_RIGHT = 3, SCREEN - 3
COUNTER_RIGHT = SCREEN - 3
INTER_DEVICE_CASES = 21             # the delay before the next device: 0 to 2 s, in tenths
WAIT_TENTHS = 0x67                  # `67 01nn`: wait nn tenths of a second
LOAD_ONE = (0xFB01, 0x1F)           # `1F FB01`: the byte register := 1
DEVICE_ATOM = 0x7C                  # `7C dd01`: the device a command is sent to
WIRING_FILE = "platform/wiring.json"
PLATFORM_FILE = "platform/platform.json"
WIRING_SCHEMA = "afterglow-harmony-650-wiring/1"
# The status screens - "Go to Website", the diagnostics - the firmware's event map names
# by position: the last thirty of its own (docs/harmony_650_700/gspm.md, "Firmware-owned
# screens"); section 4's head maps them.
STATUS_SCREENS = 30
POP_MODE = (0xFFFD, 0x07)          # `07 FFFD`: leave the screen for the one before
SELECT_CONTEXT = 0xFF00            # `1F FFnn`: select context nn
STORE = 0xED00                     # `1F EDvv`: write the accumulator into variable vv
# The platform's properties after the clock, `(initial, limit)`: identical in the 700's
# and both 650s' configurations and in the factory configurations of both.
PLATFORM_RECORDS = ((0, 2), (0, 3), (5, 7), (0, 7), (0, 32), (0, 1), (0, 32), (1, 1),
                    (0, 3), (0, 1), (0, 3))
WIDE = 0xFF                         # a variable whose limit passes this takes two bytes
# Page layout, as the 700's own pages draw: the title strip, the counter at its right,
# the softkey's label on the bar at the bottom.
TITLE_XY = (0, 2)
SOFTKEY_Y = 114
# The Activities menu: two rows a page, each spanning the screen - both keys of its side
# start it - its label centred on the row (the 700 measured: rows at 35 and 79).
MENU_ROWS = 2
MENU_ROW_Y = (35, 79)
MENU_ROOM = SCREEN - 6
ACTIVITY_SCREEN_ROOM = 100
# A start-up screen, as Logitech's draw "Starting <activity>" and "Turning system off": the
# title centred from y 5, at most 123 px a line; three fixed lines centred from y 82, 14 px
# apart; every key - codes 0x81 to 0xB6, 54 of them - bound to nothing while its codes go
# out (harmony-explorations' config-format.md, "The enter list in full").
NOTICE_TITLE_Y = 5
NOTICE_ROOM = 123
# MyHarmony's remote settings in the wiring: the screen's lit time is the first timer whose
# list opens `1F E910`, in seconds; the tilt sensor is armed by `3F F101`
GLOW_START, TILT_ON = (0xE910, 0x1F), (0xF101, 0x3F)
BACKLIGHT_RANGE = (2, 120)
# The Remote Assistant after an activity starts, as a 700 of Logitech's has it (screens 100
# and 119): its note over the activity until "Turn off Assistant" sets its variable. Its
# words, as every word drawn, are the catalogue's (catalogue.py).
ASSISTANT_FIRST_Y = 21              # the note's first line, the rest 14 px apart
ASSISTANT_TEST = 0x8000             # `71 80vv`: vv against the byte register, two arms
# The welcome tour after a write, Logitech's words and keys (650-a, the one dump that
# shows it; gspm.md, "The welcome tour"): for each page, the keys that go on and its
# softkey word's message; its text and the line saying what to press are the catalogue's
# `tour.<n>` and `tour.<n>.prompt`. The right arrow goes on where it is named, the left
# one back on every page but the first.
TOUR_RIGHT, TOUR_LEFT = 0xA3, 0x8B
TOUR = [
    ((TOUR_RIGHT,), None), ((TOUR_RIGHT,), None), ((TOUR_RIGHT,), None), ((0x85,), None),
    ((0x88, 0x82, 0x89, 0xA2), None), ((0x99,), "tour.center-button"), ((0x83,), None),
    ((0x84,), None), ((0x86,), None), ((), "softkey.exit"),
]
TOUR_TOP, TOUR_PROMPT_Y, TOUR_ROOM = 1, 90, SCREEN - 4
# A remote sold under this one's firmware with a look of its own names the scaffold whose
# look.json gives its pictures and light levels - the Harmony 600's grey artwork - in its
# profile ("looks": {skin: scaffold}); the backend passes it to build()
LOOK_FILE = "look.json"
NOTICE_LINES_Y = 82
NOTICE_KEYS = range(0x81, 0xB7)
# `3F D000`: run the next instruction once what is queued ahead of it - the start's codes
# and waits - has gone, so the start-up screen stays until then (harmony-explorations'
# findings.md, 287).
DEFER = (0xD000, 0x3F)
# Help, as Logitech's 650 and 700 run it (650-b screens 180, 75, 111, 131): Help released
# in an activity's context (0x43) enters its "Attempting to fix" screen, which sends the
# activity's own power-on and input commands again when it is entered (0x06), then asks
# "Did that fix the problem?". No (0x89) goes on to a question per device - is it on, is it
# on the right input - Yes (0xA2), the centre key and Help again (0x83) back to the
# activity; 0x2D redraws the corner.
HELP = 0x43
HELP_EXIT = 0x83
ENTERED = 0x06
REDRAW = 0x2D
ANSWER_NO, ANSWER_YES = 0x89, 0xA2
# where "Attempting to fix" and "Please keep your remote pointed" start, lines 14 apart
ATTEMPTING = (("help.attempting", 5), ("help.keep-pointed", 82))
ATTEMPTING_PITCH = 14
QUESTION_LAST_Y = 47                # a question's last line; those above it 14 px apart
QUESTION_PITCH = 14
QUESTION_LINES = 4
ANSWER_Y = 82                       # "No" from x 5, "Yes" to x 123
ANSWER_NO_X, ANSWER_YES_RIGHT = 5, 123
# Help held (0xC3), as Logitech's 650 and 700 run it (650-b screens 49, 115, 128, 127, 62,
# 106, 126): "Delay Fixing" asks whether to go on, then a device is picked; its menu sets
# its delays to the default or changes one - the power-on delay, 0 to 45 s, or the delay
# before the next device, 0 to 2 s, both in tenths. A delay screen edits a copy, which a
# section-12 program draws as "( 1.5 sec )"; - and + step it to the next whole second (half
# second), Done copies it back and saves it in the remote's own store under the device's
# key, from which the start restores it.
POWER_ON_CASES = 451
POWER_STEP, INTER_STEP = 10, 5
DELAY_KEY_LIMIT = 0xFEFD            # `7A FEFD`: what the store gives for a key never saved
SAVE_DELAY = 0x6C                   # `7A key, 6C value`: save under key; inter-device | 8000
INTER_SAVED = 0x8000
RESTORE = 0x0F                      # `0F FF40`/`FF41`: the accumulator := the saved delay
RESTORE_POWER, RESTORE_INTER = 0xFF40, 0xFF41
LOAD_ACC = 0x7A                     # `7A n`: the accumulator := n
ADD = 0x79                          # `79 n`: the accumulator += n
MODULO = 0x6E                       # `6E n`: the accumulator %= n
COMPARE_ACC = 0x70                  # `70 0cvv`: test variable vv against the accumulator
LOAD_VARIABLE = 0xEF00              # `1F EFvv`: the accumulator := variable vv
LOAD_BYTE_REGISTER = 0xFB00         # `1F FBnn`: the byte register := nn
NOT_EQUAL, LESS, GREATER, SUBTRACT = 1, 2, 3, 7
EXIT_DELAYS = (0xFFFC, 0x07)        # `07 FFFC`: back to where Help was held
SWALLOW = (0xFFF5, 0x07)            # `07 FFF5`: a key that does nothing here
REDRAW_SCREEN = (0xFFF7, 0x07)
HELP_HELD = 0xC3
OFF_KEY = 0x86
DELAY_WARNING_Y = 21
DELAY_TEXT_X = 3
DELAY_TEXT_Y = 21
RESET_TEXT_Y = 5
COUNTDOWN_Y = 80
OK_Y = 90
# The sending mark: section 12's corner programs, which a page queues (`73 n`) after its
# backdrop - a switch on the firmware's sending flag, variable 17, drawing the page's own
# patch at 114, 112 while it is 0 and the mark while it is 1 to 3, then `07 FFFA`. Numbered
# as Logitech's are: 0 the delay countdown's place, 1 the device pages', 2 the activity
# pages' and the menu's, 3 the rest's (harmony-explorations' config-format.md,
# "Base slot 11").
SENDING_FLAG = 17
SECTION1_SKIN = 2                  # section 1's byte that is the remote's skin
CORNER_XY = (114, 112)
CORNER_TAIL = (0xFFFA, 0x07)
CORNER_PROGRAMS = ("device", "activity", "idle")


def load_json(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text("utf-8"))


@dataclass
class Fonts:
    """The image's font slots, by attribute, and how to set text in them."""
    records: list[dict]
    roles: dict[str, int]

    def step_down(self, attribute: int) -> list[int]:
        """``attribute``, then the smaller fonts of its look, largest first: what a label
        too wide for its font is set in next, as Logitech's pages go down a size (15, 14,
        13, 11 and 10 pixels on the configurations measured) before cutting it short."""
        font = self.records[attribute]

        def colours(record):
            # the same colours, whatever the face: a large bold label steps down to the
            # 9-pixel bold, as Logitech's 15-pixel labels go to its 13 and 11
            look = json.loads(record["look"]) if record["look"] else {}
            return look.get("colour"), look.get("shadow")
        smaller = [index for index, other in enumerate(self.records)
                   if colours(other) == colours(font) and other["height"] < font["height"]]
        # one of each height, the first slot of it
        seen, out = set(), [attribute]
        for index in sorted(smaller, key=lambda index: (-self.records[index]["height"], index)):
            if self.records[index]["height"] not in seen:
                seen.add(self.records[index]["height"])
                out.append(index)
        return out

    def width(self, text: str, attribute: int) -> int:
        return self.label(text, attribute, 10_000)[1]

    def label(self, text: str, attribute: int, room: int = SCREEN) -> tuple[str, int]:
        font = self.records[attribute]
        codes = font["codes"]
        missing = sorted({char for char in text if char not in codes})
        if missing:
            raise ValueError(f"{text!r} has letters this remote cannot show: "
                             f"{''.join(missing)!r}. Rename it without them.")
        width = sum(font["widths"][codes[char]] for char in text)
        # past its room - a translation's word longer than the English it stands for - it
        # is cut, "..", as a name too long is
        while width > room and len(text) > 2:
            text = text[:-3].rstrip() + ".." if not text.endswith("..") else text[:-3] + ".."
            width = sum(font["widths"][codes[char]] for char in text)
        if width > room:
            raise ValueError(f"{text!r} is {width} pixels, past its {room}")
        glyphs = drawing.GlyphCodes.of(codes[char] for char in text)
        return bytes(glyphs).hex(), width


def load_fonts(directory: Path, manifest: dict, extra: str = "") -> Fonts:
    """The scaffold's font slots, each carrying printable ASCII and ``extra``: the
    characters a household's own names add - a Polish 600's "Słuchanie radia"."""
    from . import assets, faces

    loaded = assets.load(directory, set(faces.REPERTOIRE) | set(extra))
    records = []
    for role in sorted(loaded["fonts"]):
        font = loaded["fonts"][role]
        records.append({
            "height": font["height"],
            "look": json.dumps(manifest["fonts"][role].get("look"), sort_keys=True),
            "glyphs": {code: item["body"] for code, item in font["glyphs"].items()},
            "codes": {item["char"]: code for code, item in font["glyphs"].items()},
            "widths": {code: item["width"] for code, item in font["glyphs"].items()},
        })
    order = sorted(loaded["fonts"])
    roles = {part: order.index(role) for part, role in manifest["font_roles"].items()}
    return Fonts(records, roles)


@dataclass
class Numbers:
    """Every number the image hands out, in the order it hands them out."""
    screens: int = 0
    objects: list = field(default_factory=list)          # bodies, by index
    groups: list = field(default_factory=list)           # switch tables
    contexts: list = field(default_factory=list)         # context records
    narrow: list = field(default_factory=list)           # (name, record)
    wide: list = field(default_factory=list)

    def object(self, atoms) -> int:
        self.objects.append(object_body(atoms))
        return len(self.objects) - 1


class Image:
    """One image being built."""

    def __init__(self, project: dict, directory: Path, stamp_fields: tuple, words,
                 look: str | None = None, model: str | None = None):
        from ... import paths
        from . import assets, firmware_screens

        self.project, self.directory, self.words = project, directory, words
        self.manifest = assets.read_manifest(directory)
        self.pictures = {role: item["body"]
                         for role, item in assets.load(directory)["pictures"].items()}
        # the characters past ASCII the household's names and the remote's words use
        extra = {char for char in json.dumps(project, ensure_ascii=False)
                 if ord(char) > 0x7E and char.isprintable()}
        extra |= {char for char in catalogue.characters(words)
                  if ord(char) > 0x7E and char.isprintable()}
        self.fonts = load_fonts(directory, self.manifest, "".join(sorted(extra)))
        self.system = firmware_screens.load_system(directory)
        self.wiring = load_json(directory, WIRING_FILE)
        self.constants = load_json(directory, PLATFORM_FILE)
        # a remote sold under this one's firmware with a look of its own - the Harmony
        # 600, skins 71 and 73: its pictures and light levels over the scaffold's
        self.model = model
        if look is not None:
            folder = Path(paths.scaffolds(look))
            manifest = load_json(folder, LOOK_FILE)
            loaded, _notes = assets.load_pictures(folder, manifest["pictures"])
            self.pictures.update({role: item["body"] for role, item in loaded.items()})
            self.constants = dict(self.constants, tail=manifest["tail"])
        self.stamp_fields = stamp_fields
        self.fw = len(self.system["screens"])
        self.n = Numbers(screens=self.fw)
        self.drawn: set[str] = set()
        self.blocks: dict[str, list[dict]] = {}      # drawing blocks, by piece name
        self.screens: list[dict] = []                # every screen: header, flag, slots
        self.timers: list[tuple] = []
        from .devices import lowered_devices
        self.devices = lowered_devices(project)
        for device in self.devices:
            for command in device["commands"]:
                _press_alone(command)
        self.plan = activities.plan(project, self.devices)
        self.acts = self.plan["activities"]

    # -- variables

    def variables(self):
        """The engine's records: the clock and the platform's properties, the household's
        narrow variables, the platform's own, then every wide one."""
        records = scaffold.clock_records(*self.stamp_fields)
        # a carry given as atoms is an object of the image's
        for record in records:
            record["transitions"] = [
                {**row, "operand": self.n.object(row["operand"]["atoms"])}
                if isinstance(row["operand"], dict) else row
                for row in record["transitions"]]
        records += [{"initial": i, "limit": limit, "padding": 0, "transitions": []}
                    for i, limit in PLATFORM_RECORDS]
        self.firmware_count = len(records)
        acts = len(self.acts)
        self.state = {"initial": acts, "limit": acts}
        self.n.narrow.append((f"CurrentActivityState_0_{acts + 1}", self.state))
        # where More Activities and the start go: as Logitech's, only ever 0 - the
        # Activities menu - so More Activities opens the menu from a running activity
        self.location = {"initial": 0, "limit": 0}
        self.n.narrow.append(("CurrentLocation_1", self.location))
        # set while an activity or Off sends to several devices, when each device's
        # commands first wait its delay before the next (gspm.md, "Delays")
        self.sequence = {"initial": 0, "limit": 1}
        self.n.narrow.append((None, self.sequence))
        # whether the Remote Assistant was turned off on the remote: 0 shows its note after
        # a start, 1 - written by "Turn off Assistant" - no more until the next write
        self.assistant = None
        if (self.project.get("settings") or {}).get("remote_assistant", True) is not False \
                and self.acts:
            self.assistant = {"initial": 0, "limit": 1}
            self.n.narrow.append((None, self.assistant))
        # each device's power and input, as the One names them; their transitions are
        # filled once the commands' objects are numbered (place_devices)
        self.state_records = []
        for device in self.devices:
            label = device["label"].replace(" ", "_")
            inputs = device.get("inputs") or {}
            kinds = {}
            if device.get("power"):
                kinds["power"] = f"{label}_Power_2"
            if inputs.get("values"):
                kinds["input"] = f"{label}_Input_{len(inputs['values'])}"
            if device.get("online") and device.get("power") and "direct" in inputs:
                kinds["online"] = f"{label}_Online_2"
            # its other states - `Screen`, `TVInput` - which its inputs set
            for state in device.get("states") or []:
                kinds[f"state:{state['id']}"] = f"{label}_{state['id']}_{state['count']}"
            slots = {}
            for kind, name in kinds.items():
                slots[kind] = {"initial": 0, "limit": 0, "transitions": []}
                self.n.narrow.append((name, slots[kind]))
            self.state_records.append(slots)
        self.platform_variable = {}
        for index, variable in enumerate(self.wiring["variables"]):
            record = {"initial": variable["initial"], "limit": variable["limit"]}
            (self.n.wide if variable["limit"] > WIDE else self.n.narrow).append((None, record))
            self.platform_variable[index] = record
        self.records = records
        self.inter_device = []
        for device, spec in zip(self.devices, self.project.get("devices") or []):
            delay = spec.get("inter_device_delay")
            tenths = min(INTER_DEVICE_CASES - 1, round((500 if delay is None else delay) / 100))
            record = {"initial": tenths, "limit": 0xFEFD}
            self.n.wide.append((f"InterDeviceDelay_{device['index'] + 1}_65278", record))
            self.inter_device.append(record)
        # the power-on delay a device waits after its on command, as Logitech keeps it - a
        # variable Help's delay screens change (gspm.md, "Delays")
        self.power_on = []
        for device in self.devices:
            power = device.get("power")
            tenths = min(POWER_ON_CASES - 1, round(power["delay_ms"] / 100)) if power else 0
            record = {"initial": tenths, "limit": 0xFEFD}
            self.n.wide.append((f"PowerOnDelay_{device['index'] + 1}_65278", record))
            self.power_on.append(record)
        # what a delay screen edits - a copy of the power-on delay, of the inter-device one
        # - and where a step rounds through
        self.power_edit = {"initial": 0, "limit": POWER_ON_CASES - 1}
        self.inter_edit = {"initial": 0, "limit": INTER_DEVICE_CASES - 1}
        self.delay_scratch = {"initial": 0, "limit": 0xFEFD}
        if self.devices:
            self.n.narrow.append((None, self.inter_edit))
            self.n.wide += [(None, self.power_edit), (None, self.delay_scratch)]

    def variable_index(self, record) -> int:
        """A variable's number: firmware's first, then the narrow, then the wide."""
        for number, (_name, item) in enumerate(self.n.narrow):
            if item is record:
                return self.firmware_count + number
        for number, (_name, item) in enumerate(self.n.wide):
            if item is record:
                return self.firmware_count + len(self.n.narrow) + number
        raise KeyError("not a variable of this image")

    def platform(self, index: int) -> int:
        return self.variable_index(self.platform_variable[index])

    def var(self, record) -> int:
        return self.variable_index(record)

    def write(self, value: int, record) -> tuple[int, int]:
        return value, 0x80 | self.variable_index(record)

    def atoms_object(self, atoms) -> int:
        """An object of ``atoms``, as actions.py asks a layout for one."""
        return self.n.object(atoms)

    def named(self, prefix: str) -> int:
        for number, (name, _item) in enumerate(self.n.narrow):
            if name and name.startswith(prefix):
                return self.firmware_count + number
        raise KeyError(prefix)

    # -- the models' atoms

    def resolve(self, atom, objects: dict, holes) -> tuple[int, int]:
        """One model atom as an instruction: objects by the model's numbering, variables
        by the platform's, holes from ``holes``."""
        operand, category = atom
        if isinstance(category, dict):                      # a write
            target = category["write"]
            if isinstance(target, dict):
                if "variable" in target:
                    target = self.platform(target["variable"])
                else:
                    filled = holes(target)
                    if isinstance(filled, tuple):                # nothing to write: an atom
                        return filled
                    target = filled
            elif objects is self.system_objects:            # the screens name the platform's
                target = self.platform(target)
            return operand, 0x80 | target
        if isinstance(operand, dict):
            if "object" in operand:
                return objects[operand["object"]], category
            if "test" in operand:
                variable = operand["test"]
                if isinstance(variable, dict):
                    variable = (self.platform(variable["variable"]) if "variable" in variable
                                else holes(variable))
                return operand["high"] << 8 | variable, category
            if "store" in operand:                           # `1F EDvv`: into a variable
                variable = operand["store"]
                if isinstance(variable, dict):
                    variable = self.platform(variable["variable"])
                return STORE | variable, category
            if "variable" in operand:                        # the screens' tests
                return operand["high"] << 8 | self.platform(operand["variable"]), category
            if operand.get("context") == "off":
                return SELECT_CONTEXT | self.off_context, category
            if "context" in operand:
                return SELECT_CONTEXT | operand["context"], category
            if operand.get("screen") == "activity-menu":
                return self.activity_menu, category
            if "group" in operand:
                variable = operand["variable"]
                if isinstance(variable, dict):
                    variable = (self.platform(variable["variable"]) if "variable" in variable
                                else holes(variable))
                return self.wiring_groups[operand["group"]] << 8 | variable, category
            if "hole" in operand:
                return holes(operand)
            raise ValueError(f"a model names {operand!r}, which no build knows")
        return operand, category

    # -- the household's screens

    def page(self, *, backdrop: str, title: str, softkey: str | None,
             corners: list[tuple[int, int, list[str]]], counter: str | None = None,
             rows: list[tuple[int, int, list[str]]] = (), corner: str | None = None,
             title_x: int = TITLE_XY[0]) -> list[dict]:
        """A page as the 700 draws one: backdrop, title strip, the corner labels, the
        softkey and its word. A corner or a menu row is ``(place, font, lines)``."""
        fonts = self.fonts
        out = [{"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": backdrop}}]
        if corner is not None and corner in self.corners:
            out.append({"opcode": "atom", "operand": self.corners[corner], "category": 0x73})
        out += [{"opcode": "sized_bitmap", "x": 0, "y": 0, "reserved": "0000",
                "width": SCREEN, "height": 16, "target": {"picture": "title-bar"}},
               {"opcode": "attribute", "value": fonts.roles["title"]}]
        glyphs, _width = fonts.label(title, fonts.roles["title"], 100)
        out.append({"opcode": "inline_text", "x": title_x, "y": TITLE_XY[1],
                    "glyphs": glyphs})
        if counter:
            attribute = fonts.roles["indicator"]
            glyphs, width = fonts.label(counter, attribute)
            out += [{"opcode": "attribute", "value": attribute},
                    {"opcode": "inline_text", "x": COUNTER_RIGHT - width, "y": TITLE_XY[1],
                     "glyphs": glyphs}]
        current = None
        for corner, attribute, lines in corners:
            if attribute != current:
                out.append({"opcode": "attribute", "value": attribute})
                current = attribute
            right, bottom = corner % 2, corner // 2
            top = (LABEL_ONE_Y if len(lines) == 1 else LABEL_TWO_Y)[bottom]
            for number, line in enumerate(lines):
                glyphs, width = fonts.label(line, attribute, LABEL_ROOM)
                x = LABEL_RIGHT - width if right else LABEL_LEFT
                out.append({"opcode": "inline_text", "x": x,
                            "y": top + fonts.records[attribute]["height"] * number,
                            "glyphs": glyphs})
        for row, attribute, lines in rows:
            if attribute != current:
                out.append({"opcode": "attribute", "value": attribute})
                current = attribute
            height = fonts.records[attribute]["height"]
            top = MENU_ROW_Y[row] - height // 2 * (len(lines) - 1)
            for number, line in enumerate(lines):
                glyphs, width = fonts.label(line, attribute, MENU_ROOM)
                out.append({"opcode": "inline_text", "x": (SCREEN - width) // 2,
                            "y": top + height * number, "glyphs": glyphs})
        if softkey:
            out += [{"opcode": "sized_bitmap", "x": 0, "y": 0, "reserved": "0000",
                     "width": SCREEN, "height": SCREEN, "target": {"picture": "softkey"}},
                    {"opcode": "attribute", "value": fonts.roles["softkey"]}]
            glyphs, width = fonts.label(softkey, fonts.roles["softkey"], 60)
            out.append({"opcode": "inline_text", "x": (SCREEN - width) // 2, "y": SOFTKEY_Y,
                        "glyphs": glyphs})
        out.append({"opcode": "end"})
        return out

    def place_corners(self) -> None:
        """Section 12: the corner programs a page queues to draw the sending mark, from the
        scaffold's patches and mark; none when the scaffold has no mark."""
        self.corners: dict[str, int] = {}
        self.section12 = [self._block("corner:none", [{"opcode": "end"}])]
        if "corner/mark" not in self.pictures:
            return
        tail = {"opcode": "atom", "operand": CORNER_TAIL[0], "category": CORNER_TAIL[1]}
        for kind in CORNER_PROGRAMS:
            if f"corner/{kind}" not in self.pictures:
                continue
            drawn = {}
            for part, picture in (("patch", f"corner/{kind}"), ("mark", "corner/mark")):
                drawn[part] = self._block(f"corner:{kind}:{part}", [
                    {"opcode": "bitmap", "x": CORNER_XY[0], "y": CORNER_XY[1],
                     "target": {"picture": picture}}, tail, {"opcode": "end"}])
            self.corners[kind] = len(self.section12)
            self.section12.append(self._block(f"corner:{kind}", [
                {"opcode": "switch", "selector": SENDING_FLAG,
                 "cases": [(0, {"piece": drawn["patch"]})],
                 "ranges": [(1, 3, {"piece": drawn["mark"]})]},
                tail, {"opcode": "end"}]))

    def _block(self, name: str, block: list[dict]) -> str:
        self.blocks[name] = block
        return f"block:{name}"

    def backdrop(self, kind: str, count: int) -> str:
        """The picture a page of ``count`` buttons draws first: Logitech's for that kind
        of page - lines between the buttons, or none for one - as the scaffold names them
        (page/device, page/activity, page/menu and their `-one`), else the backdrop."""
        roles = [f"page/{kind}-one", f"page/{kind}"]
        for role in roles if count <= 1 else roles[::-1]:
            if role in self.pictures:
                return role
        return "backdrop"

    def screen(self, header, pages) -> int:
        """Number a screen: its header rows and ``(rows, program)`` per page. A screen
        whose pages queue a corner program binds `2D` - the firmware's sending flag
        changing - to it, as every page of Logitech's does, so the mark comes and goes
        while the page stays (650-b screens 105, 132, 78 and 47)."""
        corners = set(self.corners.values())
        queued = [item["operand"] for _rows, name in pages[:1]
                  for item in self.blocks.get(name, ())
                  if item["opcode"] == "atom" and item["category"] == DRAW_OVERLAY
                  and item["operand"] in corners]
        if queued and not any(row[0] == REDRAW for row in header):
            header = list(header) + [(REDRAW, queued[0], DRAW_OVERLAY)]
        self.screens.append({"header": header, "flag": 0, "pages": pages})
        return len(self.screens) - 1

    # -- building

    def build(self) -> bytes:
        self.place_corners()
        self.variables()
        self.place_countdowns()
        self.place_system()
        self.place_wiring()
        self.place_devices()
        self.place_hub()
        self.place_activities()
        return self.lay_out()

    # -- devices

    def place_devices(self):
        """Each device's commands, as arch 14 sends one: an object that first waits the
        device's delay when a sequence is being sent, then the command and its device."""
        self.device_screen = {}
        self.command_gate = {}          # each device's wait before its next, which every send
        for device, record in zip(self.devices, self.inter_device):
            group = len(self.n.groups)
            self.n.groups.append([(value, [(0x100 | value, WAIT_TENTHS)])
                                  for value in range(INTER_DEVICE_CASES)])
            wait = self.n.object([(group << 8 | self.variable_index(record), 0x72)])
            test = self.n.object([(self.variable_index(self.sequence), COMPARE),
                                  (wait, OBJECT_ATOM)])
            first = self.n.object([LOAD_ONE, (test, OBJECT_ATOM)])
            self.command_gate[device["index"]] = first
            for command in device["commands"]:
                command["object"] = self.n.object([
                    (first, OBJECT_ATOM), (command["command_id"], 0x7D),
                    (device["index"] << 8 | 1, DEVICE_ATOM)])
                command["object_index"] = command["object"]
        # each device's power-on wait, a case per tenth its delay can be, and the tables
        # that save its delays as they are set (Help's delay screens)
        self.power_waits, self.delay_saves = {}, []
        for device, power, inter in zip(self.devices, self.power_on, self.inter_device):
            index = device["index"]
            if device.get("power"):
                self.power_waits[index] = [self.switch(
                    [(value, waits(index, value * 100)) for value in range(POWER_ON_CASES)],
                    power)]
            key = self.delay_keys[index]
            self.delay_saves.append({
                "power": self.switch([(value, [(key, LOAD_ACC), (value, SAVE_DELAY)])
                                      for value in range(POWER_ON_CASES)], power),
                "inter": self.switch([(value, [(key, LOAD_ACC),
                                               (INTER_SAVED | value, SAVE_DELAY)])
                                      for value in range(INTER_DEVICE_CASES)], inter)})
        # power and inputs: the One's transitions, which arch 14 runs the same - a send is
        # the command's object, a wait `7C` in tenths (devices.device_state_records)
        for device, slots in zip(self.devices, self.state_records):
            online = self.var(slots["online"]) if "online" in slots else None
            states = {kind.split(":", 1)[1]: self.var(record) for kind, record in slots.items()
                      if kind.startswith("state:")}
            made = device_state_records(device, self._place_body, online, states,
                                        self.power_waits.get(device["index"]))
            if [name for name, _record in made] != [
                    name for name, item in self.n.narrow
                    if any(item is record for record in slots.values())]:
                raise ValueError(f"device {device['label']!r}: its variables are not the "
                                 "ones reserved for it")
            for (name, record), kind in zip(made, slots):
                slots[kind].update({key: record[key]
                                    for key in ("initial", "limit", "transitions")})
        self.slots = [{kind: self.var(record) for kind, record in slots.items()}
                      for slots in self.state_records]
        self.actions = Actions(self, self.devices, self.slots, self.power_waits,
                               held=self.held_command)

    def held_command(self, device: int, command_id: int, tenths: int) -> int:
        """A command's object held ``tenths`` - as Logitech writes the codes Help sends to
        fix a device, its inter-key delay: the same object but for its hold."""
        return self.n.object([(self.command_gate[device], OBJECT_ATOM), (command_id, 0x7D),
                              (device << 8 | tenths, DEVICE_ATOM)])

    def switch(self, cases, record) -> tuple[int, int]:
        """A switch on ``record`` over a table of its own: `72 ggvv`, both a byte."""
        group, variable = len(self.n.groups), self.variable_index(record)
        if group > 0xFF or variable > 0xFF:
            raise ValueError("a switch past the 256 tables or variables a `72` names")
        self.n.groups.append(cases)
        return group << 8 | variable, 0x72

    def byte_var(self, record) -> int:
        """A variable an instruction names in a byte: `1F EDvv`, `70 0cvv`."""
        variable = self.variable_index(record)
        if variable > 0xFF:
            raise ValueError("a delay variable past the 256 an instruction can name")
        return variable

    @property
    def delay_keys(self) -> list[int]:
        """Each device's key in the remote's store: from its id and its project delays, so
        a delay saved on the remote outlives a rebuild of the same household and one the
        project changes starts from the project's (Logitech's are its device ids)."""
        if not hasattr(self, "_delay_keys"):
            specs = self.project.get("devices") or []
            keys_, taken = [], set()
            for device, power, inter in zip(self.devices, self.power_on, self.inter_device):
                spec = specs[device["index"]] if device["index"] < len(specs) else {}
                seed = f"{spec.get('id') or device['label']}|{power['initial']}|" \
                       f"{inter['initial']}".encode()
                key = zlib.crc32(seed) % (DELAY_KEY_LIMIT - 1) + 1
                while key in taken:
                    key = key % (DELAY_KEY_LIMIT - 1) + 1
                taken.add(key)
                keys_.append(key)
            self._delay_keys = keys_
        return self._delay_keys

    def delay_restore(self) -> int:
        """The start's restore of each device's saved delays, as Logitech's: the saved
        value into the scratch, and when one was saved, into the device's variable."""
        scratch = self.byte_var(self.delay_scratch)
        out = []
        for key, power, inter in zip(self.delay_keys, self.power_on, self.inter_device):
            for which, record in ((RESTORE_POWER, power), (RESTORE_INTER, inter)):
                store = self.n.object([(key, LOAD_ACC), (which, RESTORE),
                                       (STORE | self.byte_var(record), 0x1F)])
                saved = self.n.object([(NOT_EQUAL << 8 | scratch, COMPARE_ACC),
                                       (store, OBJECT_ATOM)])
                out.append((self.n.object([
                    (key, LOAD_ACC), (which, RESTORE), (STORE | scratch, 0x1F),
                    (self.n.object([(DELAY_KEY_LIMIT, LOAD_ACC), (saved, OBJECT_ATOM)]),
                     OBJECT_ATOM)]), OBJECT_ATOM))
        return self.n.object(out)

    def _place_body(self, body: bytes) -> int:
        self.n.objects.append(body)
        return len(self.n.objects) - 1

    def label_lines(self, text: str, attribute: int,
                    room: int = LABEL_ROOM) -> tuple[int, list[str]]:
        """A label in at most two lines that fit a corner, and the font it is set in: the
        page's, or as Logitech's pages do with one too wide for it, the next size down
        (Fonts.step_down); cut with ".." in the page's font when none holds it."""
        for font in self.fonts.step_down(attribute):
            lines = self._lines(text, font, room)
            if all(self.fonts.width(line, font) <= room for line in lines):
                return font, lines
        return attribute, [self._fit(line, attribute, room)
                           for line in self._lines(text, attribute, room)]

    def _lines(self, text: str, attribute: int, room: int) -> list[str]:
        """A label's lines: whole if it fits, else broken in two. A command's name is
        broken where its words meet, as Logitech's 700 pages draw `PowerToggle` - "Power"
        over "Toggle" - and nothing is added, so an import joins it back; a label with
        spaces is wrapped between its words. `AddDlt`, which fits, stays whole."""
        if self.fonts.width(text, attribute) <= room:
            return [text]
        if " " in text:
            parts, glue = text.split(), " "
        else:
            parts, glue = _words(text).split(), ""
        if len(parts) <= 1:
            return [text]
        # the break that leaves the longer line shortest
        best = min(range(1, len(parts)), key=lambda at: max(
            self.fonts.width(glue.join(parts[:at]), attribute),
            self.fonts.width(glue.join(parts[at:]), attribute)))
        return [glue.join(parts[:best]), glue.join(parts[best:])]

    def _fit(self, text: str, attribute: int, room: int) -> str:
        while self.fonts.label(text, attribute, 10_000)[1] > room and len(text) > 1:
            text = text[:-3].rstrip() + ".." if not text.endswith("..") else text[:-3] + ".."
        return text

    def device_list_pages(self, softkey: str, tag: str, title: str | None = None,
                          opens=None, corner: str | None = "device",
                          backdrop: str | None = None) -> list[tuple[list, str]]:
        """A Devices list, four devices a page, its softkey ``softkey``: "Activities" for
        the one shown with nothing running, "Activity" for a running activity's own, as
        Logitech's configurations have one each. Help's "Select device" is one too, each
        device opening what ``opens`` gives for it."""
        title = self.words("devices.title") if title is None else title
        attribute = self.fonts.roles["button"]
        corner_keys = [keys.code(keys.SCREEN_KEYS[corner]) for corner in (
            "top-left", "top-right", "bottom-left", "bottom-right")]
        marker = self.menu_marker()
        devices = list(self.devices)
        groups = [devices[at:at + CORNERS] for at in range(0, len(devices), CORNERS)] or [[]]
        pages = []
        for number, group in enumerate(groups):
            rows, corners = [], []
            for corner, device in enumerate(group):
                if opens is None:
                    target = self.n.object(
                        [(self.device_screen[device["index"]], ENTER_MODE)]
                        + ([(1, 0x80 | marker)] if marker is not None else []))
                    rows.append((corner_keys[corner], target, OBJECT_ATOM))
                else:
                    rows.append((corner_keys[corner], *opens(device)))
                corners.append((corner, *self.label_lines(device["label"], attribute)))
            name = f"hub:devices:{tag}:{number}"
            self.blocks[name] = self.page(
                backdrop=backdrop or self.backdrop("device", len(group)), title=title,
                softkey=softkey, corners=corners, corner=corner,
                counter=f"{number + 1}/{len(groups)}" if len(groups) > 1 else None)
            pages.append((rows, name))
        return pages

    def place_device_screens(self, to_list: int):
        """Each device's own screen, four of its commands a page, its keys bound in the
        screen's list; its Back goes to the Devices list it came from."""
        attribute = self.fonts.roles["button"]
        centre = keys.code(keys.CENTRE)
        corner_keys = [keys.code(keys.SCREEN_KEYS[corner]) for corner in (
            "top-left", "top-right", "bottom-left", "bottom-right")]
        title_room = 100
        specs = self.project.get("devices") or []
        for device in self.devices:
            # in the order the project lists them, as the pages it was read from showed them
            listed = [entry[0] for entry in specs[device["index"]].get("commands") or []]
            rank = {name: at for at, name in enumerate(listed)}
            shown = sorted((command for command in device["commands"]
                            if not command.get("hidden")),
                           key=lambda command: rank.get(command["name"], len(rank)))
            chunks = [shown[at:at + CORNERS] for at in range(0, len(shown), CORNERS)] or [[]]
            title = self._fit(device["label"], self.fonts.roles["title"], title_room)
            names = {command["name"] for command in device["commands"]}
            device_pages = []
            for number, chunk in enumerate(chunks):
                rows = [(corner_keys[corner], command["object"], OBJECT_ATOM)
                        for corner, command in enumerate(chunk)]
                corners = [(corner, *self.label_lines(_drawn_name(command["name"], names),
                                                      attribute))
                           for corner, command in enumerate(chunk)]
                name = f"device:{device['index']}:{number}"
                self.blocks[name] = self.page(
                    backdrop=self.backdrop("device", len(chunk)), title=title,
                    softkey=self.words("softkey.back"), corners=corners, corner="device",
                    counter=f"{number + 1}/{len(chunks)}" if len(chunks) > 1 else None)
                device_pages.append((rows, name))
            header = [(centre, to_list, OBJECT_ATOM)]
            for command in device["commands"]:
                for key in command["keys"]:
                    code = keys.by_name(key)
                    if code is not None and all(code != row[0] for row in header):
                        header.append((code, command["object"], OBJECT_ATOM))
            self.screen(header, device_pages)

    def menu_marker(self) -> int | None:
        """The platform's variable More Activities sets to 0 - which a device list row sets
        to 1 - read off the wiring's More Activities row."""
        for context in self.wiring["contexts"]:
            for row in context["rows"]:
                if row["key"] != keys.code(keys.ACTIVITIES):
                    continue
                operand = row["action"][0]
                if isinstance(operand, dict) and "object" in operand:
                    for _value, category in self.wiring["objects"][operand["object"]]:
                        if isinstance(category, dict) and isinstance(category["write"], dict) \
                                and "variable" in category["write"]:
                            return self.platform(category["write"]["variable"])
        return None

    def place_system(self):
        """The firmware's own screens, at the ordinals it knows them by, their objects
        first."""
        system = platform_text.render(self.system, self.fonts.label, self.words)
        base = len(self.n.objects)
        self.system_objects = {index: base + index for index in range(len(system["objects"]))}
        for atoms in system["objects"]:
            self.n.objects.append(None)
        for index, atoms in enumerate(system["objects"]):
            self.n.objects[base + index] = object_body(
                [self.resolve(atom, self.system_objects, self._no_hole) for atom in atoms])
        for index, block in enumerate(system["blocks"]):
            self.blocks[f"sys:{index}"] = block
        for ordinal, model in enumerate(system["screens"]):
            header = [(key, *self.resolve([operand, category], self.system_objects,
                                          self._no_hole))
                      for key, operand, category in model["header"]]
            pages = [([], f"sys:{slot['program']}") for slot in model["slots"]]
            self.screens.append({"header": "mode-zero" if ordinal == 0 else header,
                                 "flag": model["flag"], "pages": pages})

    @staticmethod
    def _no_hole(hole):
        raise ValueError(f"the firmware screens' model has a hole: {hole!r}")

    def place_wiring(self):
        """The wiring: its objects, its switch tables, its timers, its contexts, the
        start-up list and mode 0's list, every hole filled."""
        wiring = self.wiring
        # numbers the wiring's holes need, handed out now so its atoms can name them
        self.activity_menu = self.fw
        self.device_list = self.fw + 1
        self.off_context = len(wiring["contexts"])
        self.empty = self.n.object([])
        base = len(self.n.objects)
        self.wiring_objects = {index: base + index for index in range(len(wiring["objects"]))}
        self.n.objects.extend([None] * len(wiring["objects"]))
        self.wiring_groups = {}
        for index in range(len(wiring["groups"])):
            self.wiring_groups[index] = len(self.n.groups)
            self.n.groups.append(None)
        self.location_group = len(self.n.groups)
        self.n.groups.append(None)
        resolve = lambda atom: self.resolve(atom, self.wiring_objects, self.hole)  # noqa: E731
        # MyHarmony's remote settings (gspm.md, "Remote settings"): with the tilt sensor
        # off, nothing arms it
        settings = self.project.get("settings") or {}
        tilt = str(settings.get("tilt", "on")) != "off"
        for index, atoms in enumerate(wiring["objects"]):
            self.n.objects[base + index] = object_body([
                resolve(atom) for atom in atoms if tilt or list(atom) != list(TILT_ON)])
        for index, group in enumerate(wiring["groups"]):
            self.n.groups[self.wiring_groups[index]] = [
                (value, [resolve(atom) for atom in atoms]) for value, atoms in group["cases"]]
        # the household's screens, in order after the firmware's: the menu, the Devices
        # list, each device's, each activity's, each activity's own Devices list, each
        # activity's start-up screen, then All Off's
        acts, first = len(self.acts), self.fw + 2 + len(self.devices)
        self.activity_screens = [first + index for index in range(acts)]
        self.activity_device_lists = [first + acts + index for index in range(acts)]
        self.starting_screens = [first + 2 * acts + index for index in range(acts)]
        self.off_screen = first + 3 * acts
        # then Help's: per activity and for Off, "Attempting to fix", "Did that fix the
        # problem?", and three per question (Is it..?, Now is it..?, Did that fix it?);
        # none for one with nothing to ask about
        self.help_chains, at = [], self.off_screen + 1
        # a device kept on is asked about too, in every activity and Off, as Logitech's
        # Help asks after a Dutch 650's fan that no activity switches
        steady = [index for index, device in enumerate(self.devices)
                  if device.get("always_on") and device.get("power")]

        def asked(powered):
            return list(powered) + [index for index in steady if index not in powered]
        chains = [(self.activity_screens[index], asked(act["on"]), act["inputs"], True)
                  for index, act in enumerate(self.acts)]
        chains.append((self.activity_menu, asked(self.plan["all_off"]["off"]), [], False))
        for home, powered, inputs, on in chains:
            questions = self.help_questions(powered, inputs, on)
            if not questions:
                self.help_chains.append(None)
                continue
            self.help_chains.append({"home": home, "attempt": at, "check": at + 1, "on": on,
                                     "powered": powered, "inputs": inputs,
                                     "questions": questions})
            at += 2 + 3 * len(questions)
        # then Help held's: "Delay Fixing", "Select device", and five a device - its menu,
        # Change Delay, the two delay screens and "set to default"
        self.delay_warning = self.delay_select = None
        if self.devices:
            self.delay_warning, self.delay_select = at, at + 1
            self.delay_screens = [
                dict(zip(("menu", "change", "power", "inter", "reset"),
                         range(at + 2 + 5 * number, at + 7 + 5 * number)))
                for number in range(len(self.devices))]
            at += 2 + 5 * len(self.devices)
        # then each activity's favourite channels, which its first page's first button
        # opens, as Logitech's "Favorite Channels" (a tester's 650)
        self.favourite_screens = {}
        for index, act in enumerate(self.acts):
            if act.get("favourites"):
                self.favourite_screens[index] = at
                at += 1
        # then each activity's Remote Assistant note
        self.assistant_screens = {}
        if self.assistant is not None:
            for index in range(len(self.acts)):
                self.assistant_screens[index] = at
                at += 1
        # then the welcome tour's ten pages, when this build shows it
        self.place_tour_start(resolve, at)
        at += len(self.tour_screens)
        # CurrentLocation's one value: the Activities menu (Logitech's 650 and 700 the same)
        self.n.groups[self.location_group] = [(0, [(self.activity_menu, ENTER_MODE)])]
        self.timers = [(item["flags"], item["duration"], *resolve(item["action"]))
                       for item in wiring["timers"]]
        # how long the screen stays lit: the first timer whose list opens `1F E910`
        lit = str(settings.get("backlight_timeout") or "").strip()
        for number, item in enumerate(wiring["timers"]):
            action = item["action"][0]
            if lit.isdigit() and isinstance(action, dict) and "object" in action \
                    and list(wiring["objects"][action["object"]][0]) == list(GLOW_START):
                seconds = max(BACKLIGHT_RANGE[0], min(BACKLIGHT_RANGE[1], int(lit)))
                self.timers[number] = (item["flags"], seconds, *self.timers[number][2:])
                break
        self.lead = [resolve(atom) for atom in wiring["lead"]]
        self.mode_zero = [(entry[0], *resolve(entry[1:])) for entry in wiring["mode_zero"]]
        self.activity_key = self.n.object([POP_MODE, (self.add_activity_screen(), ENTER_MODE)])
        on_keys = self.activity_keys()
        for context in wiring["contexts"]:
            rows = []
            for row in context["rows"]:
                action = row["action"]
                if isinstance(action[0], dict) and action[0].get("hole") == "activity-key":
                    order = on_keys.get(row["key"] & 0x7F)
                    if order is not None:
                        operand, category = SELECT_CONTEXT | self.activity_context(order), \
                            0x1F
                    else:
                        operand, category = self.activity_key, OBJECT_ATOM
                else:
                    operand, category = resolve(action)
                rows.append({"flags": row["flags"], "key_code": row["key"],
                             "operand": operand, "category": category})
            self.n.contexts.append({"form": context["form"], "rows": rows})
        # Off: "Turning system off", every device it turns off off, nothing running, and
        # once the codes have gone back to the menu
        menu = (self.activity_menu, ENTER_MODE)
        self.n.contexts.append(self.context([
            (activity_index.ENTER, self.n.object(
                [(self.off_screen, ENTER_MODE), self.write(1, self.sequence)]
                + self.actions_power_writes(self.plan["all_off"]["off"], 0)
                + [self.write(len(self.acts), self.state),
                   (self.n.object([DEFER, menu]), OBJECT_ATOM),
                   self.write(0, self.sequence)])),
            (activity_index.REFRESH, self.n.object([menu]))]
            + [(HELP, chain["attempt"], ENTER_MODE) for chain in self.help_chains[-1:] if chain]
            + self.held_help()))

    def activity_keys(self) -> dict[int, int]:
        """Which activity each activity key starts, by scan code: the one that names it
        (`activity_button`: "Movie", "TV" or "Music"), as Logitech's configurations say;
        in a project that names none, the first three in key order. A key no activity
        has says to add one."""
        named = {}
        for index, act in enumerate(self.acts):
            if act.get("activity_button") in keys.ACTIVITY_BUTTONS:
                named.setdefault(keys.ACTIVITY_BUTTONS[act["activity_button"]], index)
        if any(act.get("activity_button") for act in self.acts):
            return named
        return {scan: order for order, scan in enumerate(keys.ACTIVITY_KEYS)
                if order < len(self.acts)}

    def actions_power_writes(self, indices, value: int) -> list[tuple[int, int]]:
        """Power writes, before the commands are numbered: by the variables alone."""
        return [self.write(value, self.state_records[index]["power"]) for index in indices
                if "power" in self.state_records[index]]

    def activity_context(self, index: int) -> int:
        """Activity ``index``'s context: after the platform's and Off."""
        return self.off_context + 1 + index

    @staticmethod
    def context(rows) -> dict:
        """A context of ``(key code, object)`` rows - or ``(key code, operand, category)``
        - in key order as the One writes them."""
        return {"form": "short", "rows": [
            {"flags": None, "key_code": row[0], "operand": row[1],
             "category": row[2] if len(row) > 2 else OBJECT_ATOM}
            for row in sorted(rows)]}

    def hole(self, hole: dict) -> tuple[int, int]:
        """What a build puts in a hole the project has nothing for: a call to an empty
        object, which runs nothing - the Help flow's switches with no device to help
        with, the Remote Assistant's screen, a device's own variable."""
        kind = hole.get("hole")
        if kind == "delay-restore":
            # the delays Help's delay screens saved on the remote, each device's restored
            return (self.delay_restore() if self.devices else self.empty), OBJECT_ATOM
        if kind == "location-map":
            return self.location_group << 8 | self.named("CurrentLocation"), 0x72
        if kind == "screen":
            return self.activity_menu, ENTER_MODE
        if kind == "location":
            return self.named("CurrentLocation")
        return self.empty, OBJECT_ATOM

    def add_activity_screen(self) -> int:
        """The firmware screen that asks for an Activity on this button."""
        for number, words in catalogue.NOTICES.items():
            if "add an Activity on" in words.replace("\n", " "):
                return number
        raise ValueError("the catalogue has no 'add an Activity' notice")

    def place_hub(self):
        """The Activities menu and the Devices list, each opening the other with the centre
        key below the screen. "Devices" goes through a switch on the running activity, as
        Logitech's does (the 700 measured: the menu's and an activity's centre key both
        switch on `CurrentActivityState`): to that activity's own Devices list, whose
        softkey returns to it, or with nothing running to the list that returns to the
        menu. A device's Back goes the same way."""
        centre = keys.code(keys.CENTRE)
        for device in self.devices:
            self.device_screen[device["index"]] = self.fw + 2 + device["index"]
        group = len(self.n.groups)
        self.n.groups.append([(index, [(ordinal, ENTER_MODE)])
                              for index, ordinal in enumerate(self.activity_device_lists)]
                             + [(len(self.acts), [(self.device_list, ENTER_MODE)])])
        self.to_devices = self.n.object([(group << 8 | self.var(self.state), 0x72)])
        to_activities = self.n.object([(self.activity_menu, ENTER_MODE)])
        self.screen([(centre, self.to_devices, OBJECT_ATOM)], self.menu_pages())
        self.screen([(centre, to_activities, OBJECT_ATOM)],
                    self.device_list_pages(self.words("softkey.activities"), "idle"))
        self.place_device_screens(self.to_devices)

    def menu_pages(self) -> list[tuple[list, str]]:
        """The Activities menu: two activities a page, each row started by both keys
        of its side."""
        # the button font, as Logitech's menus set their rows
        attribute = self.fonts.roles["button"]
        sides = (("top-left", "top-right"), ("bottom-left", "bottom-right"))
        indices = list(range(len(self.acts)))
        groups = [indices[at:at + MENU_ROWS]
                  for at in range(0, len(indices), MENU_ROWS)] or [[]]
        pages = []
        for number, group in enumerate(groups):
            rows, drawn = [], []
            for row, index in enumerate(group):
                start = SELECT_CONTEXT | self.activity_context(index)
                rows += [(keys.code(keys.SCREEN_KEYS[corner]), start, 0x1F)
                         for corner in sides[row]]
                font, lines = self.label_lines(self.acts[index]["label"], attribute, MENU_ROOM)
                drawn.append((row, font, lines))
            name = f"hub:activities:{number}"
            self.blocks[name] = self.page(
                backdrop=self.backdrop("menu", len(group)), title=self.words("menu.title"),
                softkey=self.words("softkey.devices"), corners=[], corner="activity",
                rows=drawn, counter=f"{number + 1}/{len(groups)}" if len(groups) > 1 else None)
            pages.append((rows, name))
        return pages

    # -- activities

    def place_activities(self):
        """Each activity's screen - its buttons, four a page - and its context."""
        centre = keys.code(keys.CENTRE)
        to_devices = self.to_devices
        attribute = self.fonts.roles["button"]
        corner_keys = [keys.code(keys.SCREEN_KEYS[corner]) for corner in (
            "top-left", "top-right", "bottom-left", "bottom-right")]
        actions = self.actions

        def button_pages(title: str, buttons: list, tag: str) -> list[tuple[list, str]]:
            # four buttons a page; a button whose steps are a screen's number opens it
            chunks = [buttons[at:at + CORNERS]
                      for at in range(0, len(buttons), CORNERS)] or [[]]
            pages = []
            for number, chunk in enumerate(chunks):
                rows = [(corner_keys[corner], steps, ENTER_MODE) if isinstance(steps, int)
                        else (corner_keys[corner], actions.key_target(steps), OBJECT_ATOM)
                        for corner, (_label, steps) in enumerate(chunk)]
                corners = [(corner, *self.label_lines(label, attribute))
                           for corner, (label, _steps) in enumerate(chunk)]
                name = f"{tag}:{number}"
                self.blocks[name] = self.page(
                    backdrop=self.backdrop("activity", len(chunk)), title=title,
                    softkey=self.words("softkey.devices"), corners=corners,
                    corner="activity",
                    counter=f"{number + 1}/{len(chunks)}" if len(chunks) > 1 else None)
                pages.append((rows, name))
            return pages
        titles = []
        for index, act in enumerate(self.acts):
            screen = self.activity_screens[index]
            if len(self.screens) != screen:
                raise ValueError("an activity's screen is not where its start goes")
            title = self._fit(act["label"], self.fonts.roles["title"], ACTIVITY_SCREEN_ROOM)
            titles.append(title)
            buttons = list(act["buttons"])
            if index in self.favourite_screens:
                buttons.insert(0, (self.words("activity.favourites"),
                                   self.favourite_screens[index]))
            self.screen([(centre, to_devices, OBJECT_ATOM)],
                        button_pages(title, buttons, f"activity:{index}"))
            shown = (screen, ENTER_MODE)
            # as Logitech's enter lists: the start-up screen, the devices' writes, the
            # activity's number, its steps, and once their codes have gone its own screen
            rows = [
                (activity_index.ENTER, self.n.object(
                    [(self.starting_screens[index], ENTER_MODE), self.write(1, self.sequence)]
                    + actions.power_writes(act["on"], 1) + actions.input_writes(act["inputs"])
                    + actions.power_writes(act["off"], 0)
                    + [self.write(index, self.state)]
                    + actions.atoms(act["enter"])
                    + [(self.n.object([DEFER, self.after_start(index, shown)]),
                        OBJECT_ATOM),
                       self.write(0, self.sequence)])),
                # picked again while running: its inputs again, and back to its screen
                (activity_index.REFRESH, self.n.object(
                    [self.write(1, self.sequence)] + actions.input_writes(act["inputs"])
                    + [self.write(0, self.sequence), shown])),
            ]
            if self.help_chains[index]:
                rows.append((HELP, self.help_chains[index]["attempt"], ENTER_MODE))
            rows += self.held_help()
            if act["leave"]:
                rows.append((activity_index.LEAVE, self.n.object(actions.atoms(act["leave"]))))
            rows += [(code, actions.key_target(steps)) for code, steps in act["keys"].items()]
            self.n.contexts.append(self.context(rows))
        # each activity's own Devices list, whose softkey goes back to the activity
        for index, ordinal in enumerate(self.activity_device_lists):
            if len(self.screens) != ordinal:
                raise ValueError("an activity's Devices list is not where its switch goes")
            back = self.n.object([(self.activity_screens[index], ENTER_MODE)])
            self.screen([(centre, back, OBJECT_ATOM)],
                        self.device_list_pages(self.words("softkey.activity"),
                                               f"activity{index}"))
        for index, act in enumerate(self.acts):
            self.notice_screen(self.starting_screens[index], f"starting:{index}",
                               self.words("activity.starting", activity=act["label"]))
        self.notice_screen(self.off_screen, "off", self.words("off.turning-off"))
        for number, chain in enumerate(self.help_chains):
            if chain:
                self.place_help(number, chain)
        if self.devices:
            self.place_delays()
        # each activity's favourites, "Commands" first going back to its buttons
        for index, ordinal in self.favourite_screens.items():
            if len(self.screens) != ordinal:
                raise ValueError("an activity's favourites are not where its button goes")
            favourites = [(item["label"] or self.words("favourites.unnamed", number=number),
                           item["steps"])
                          for number, item in enumerate(self.acts[index]["favourites"], 1)]
            self.screen([(centre, to_devices, OBJECT_ATOM)], button_pages(
                titles[index],
                [(self.words("favourites.commands"), self.activity_screens[index])]
                + favourites,
                f"favourites:{index}"))
        for index, ordinal in self.assistant_screens.items():
            if len(self.screens) != ordinal:
                raise ValueError("an activity's Remote Assistant is not where its start goes")
            self.assistant_screen(index)
        self.place_tour()

    # -- Help

    def help_questions(self, powered, inputs, on: bool) -> list[dict]:
        """What Help asks about, in order: each device with a power command whether it is
        on (off, for Off), then each input that can be set again whether it is set."""
        questions = [{"device": index} for index in powered
                     if self.devices[index].get("power")]
        for index, value in inputs:
            choices = self.devices[index].get("inputs") or {}
            if "next" in choices or (choices.get("direct") or [None] * (value + 1))[value]:
                questions.append({"device": index, "input": value})
        return questions

    def help_text(self, question: dict, on: bool, again: bool = False) -> str:
        """A Help question, or ``again`` the one it asks after fixing what it asked."""
        device = self.devices[question["device"]]
        now = "now-" if again else "is-"
        if "input" in question:
            name = device["inputs"]["values"][question["input"]]
            return self.words("help." + ("now-input" if again else "input"),
                              device=device["label"], input=name)
        return self.words(f"help.{now}{'on' if on else 'off'}", device=device["label"])

    def help_atoms(self, question: dict, on: bool, fix: bool) -> list[tuple[int, int]]:
        """What an answer runs: No (``fix``) sends the device's power - a toggle too -
        or its input again; either way the variable is set to what was asked."""
        actions, index = self.actions, question["device"]
        if "input" in question:
            sends = actions.input_fix(index, question["input"]) if fix else []
            return sends + actions.input_writes([(index, question["input"])])
        sends = actions.direct_power([index], on, toggles=True) if fix else []
        return sends + actions.power_writes([index], int(on))

    def help_answer(self, atoms, target: int | None) -> tuple[int, int]:
        """An answer's binding: ``atoms`` then screen ``target`` (None stays)."""
        shown = [(target, ENTER_MODE)] if target is not None else []
        if not atoms and shown:
            return shown[0]
        return self.n.object(list(atoms) + shown), OBJECT_ATOM

    def place_help(self, number: int, chain: dict) -> None:
        """One activity's Help (or Off's): "Attempting to fix", which sends its commands
        again, then its questions; every Yes that fixed it goes home."""
        if len(self.screens) != chain["attempt"]:
            raise ValueError("a Help screen is not where its activity's Help goes")
        actions, home, on = self.actions, chain["home"], chain["on"]
        resend = actions.direct_power(chain["powered"], on)
        for index, value in chain["inputs"]:
            if "direct" in (self.devices[index].get("inputs") or {}):
                resend += actions.input_fix(index, value)
        check = (self.n.object([DEFER, (chain["check"], ENTER_MODE)]), OBJECT_ATOM)
        entered = self.n.object([self.write(1, self.sequence)] + resend
                                + [check, self.write(0, self.sequence)])
        self.attempting_screen(f"help:{number}", entered)
        questions = chain["questions"]
        firsts = [chain["check"] + 1 + 3 * at for at in range(len(questions))] + [home]
        self.question_screen(f"help:{number}:check", self.words("help.fixed"), home,
                             self.help_answer([], firsts[0]), self.help_answer([], home))
        for at, question in enumerate(questions):
            again, fixed = firsts[at] + 1, firsts[at] + 2
            text = self.help_text(question, on)
            self.question_screen(
                f"help:{number}:{at}", text, home,
                self.help_answer(self.help_atoms(question, on, True), again),
                self.help_answer(self.help_atoms(question, on, False), firsts[at + 1]))
            self.question_screen(
                f"help:{number}:{at}:again", self.help_text(question, on, again=True), home,
                self.help_answer(self.help_atoms(question, on, True), None),
                self.help_answer(self.help_atoms(question, on, False), fixed))
            self.question_screen(f"help:{number}:{at}:fixed", self.words("help.fixed"), home,
                                 self.help_answer([], firsts[at + 1]),
                                 self.help_answer([], home))

    def attempting_screen(self, name: str, entered: int) -> None:
        """Help's first screen: Logitech's working picture, its lines in the notice font,
        and what it sends when it is entered."""
        fonts, attribute = self.fonts, self.fonts.roles["notice"]
        out = [{"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": self.pictures_or(
            "page/working")}}, {"opcode": "attribute", "value": attribute}]
        placed = []
        for key, top in ATTEMPTING:
            lines = self.paragraph(self.words(key).split("\n"), attribute)
            placed += [(line, top + ATTEMPTING_PITCH * row) for row, line in enumerate(lines)]
        for line, y in placed:
            glyphs, width = fonts.label(line, attribute, SCREEN)
            out.append({"opcode": "inline_text", "x": (SCREEN - width) // 2, "y": y,
                        "glyphs": glyphs})
        out.append({"opcode": "end"})
        self.blocks[name] = out
        self.screen([(ENTERED, entered, OBJECT_ATOM)], [([], name)])

    def paragraph(self, lines, attribute: int, room: int = NOTICE_ROOM) -> list[str]:
        """A text as Logitech breaks it into lines, kept where each fits ``room`` in the
        face drawing it; where one does not - Galmuri Afterglow's bold runs wider than
        Logitech's - wrapped anew between its words into as many lines, the last cut to
        fit."""
        if all(self.fonts.width(line, attribute) <= room for line in lines):
            return list(lines)
        wrapped = self.question_lines(" ".join(lines), attribute, room)
        if len(wrapped) > len(lines):
            rest = " ".join(wrapped[len(lines) - 1:])
            wrapped = wrapped[:len(lines) - 1] + [self._fit(rest, attribute, room)]
        return wrapped

    def pictures_or(self, role: str) -> str:
        return role if role in self.pictures else "backdrop"

    def question_lines(self, text: str, attribute: int, room: int = NOTICE_ROOM) -> list[str]:
        """A question wrapped between its words to the screen, at most four lines."""
        lines = []
        for word in text.split():
            if lines and self.fonts.width(f"{lines[-1]} {word}", attribute) <= room:
                lines[-1] += f" {word}"
            else:
                lines.append(word)
        if len(lines) > QUESTION_LINES:
            lines[QUESTION_LINES - 1:] = [" ".join(lines[QUESTION_LINES - 1:])]
        return [self._fit(line, attribute, room) for line in lines]

    def question_screen(self, name: str, text: str, home: int, no, yes) -> None:
        """A Help question: the backdrop and the idle corner, the question centred so
        its last line is at y 47, "No" and "Yes" over their keys, and "Exit Help"."""
        fonts = self.fonts
        message, answer, softkey = (fonts.roles[role]
                                    for role in ("message", "answer", "softkey"))
        out = [{"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": "backdrop"}}]
        if "idle" in self.corners:
            out.append({"opcode": "atom", "operand": self.corners["idle"],
                        "category": DRAW_OVERLAY})
        out.append({"opcode": "attribute", "value": message})
        lines = self.question_lines(text, message)
        for number, line in enumerate(lines):
            glyphs, width = fonts.label(line, message, SCREEN)
            out.append({"opcode": "inline_text", "x": (SCREEN - width) // 2,
                        "y": QUESTION_LAST_Y - QUESTION_PITCH * (len(lines) - 1 - number),
                        "glyphs": glyphs})
        out.append({"opcode": "attribute", "value": answer})
        glyphs, _width = fonts.label(self.words("answer.no"), answer, SCREEN)
        out.append({"opcode": "inline_text", "x": ANSWER_NO_X, "y": ANSWER_Y,
                    "glyphs": glyphs})
        glyphs, width = fonts.label(self.words("answer.yes"), answer, SCREEN)
        out.append({"opcode": "inline_text", "x": ANSWER_YES_RIGHT - width, "y": ANSWER_Y,
                    "glyphs": glyphs})
        out += [{"opcode": "sized_bitmap", "x": 0, "y": 0, "reserved": "0000",
                 "width": SCREEN, "height": SCREEN, "target": {"picture": "softkey"}},
                {"opcode": "attribute", "value": softkey}]
        glyphs, width = fonts.label(self.words("softkey.exit-help"), softkey, 60)
        out.append({"opcode": "inline_text", "x": (SCREEN - width) // 2, "y": SOFTKEY_Y,
                    "glyphs": glyphs})
        out.append({"opcode": "end"})
        self.blocks[name] = out
        header = [(keys.code(keys.CENTRE), home, ENTER_MODE),
                  (HELP_EXIT, home, ENTER_MODE)]
        if "idle" in self.corners:
            header.append((REDRAW, self.corners["idle"], DRAW_OVERLAY))
        self.screen(header, [([(ANSWER_NO, *no), (ANSWER_YES, *yes)], name)])

    def after_start(self, index: int, shown: tuple[int, int]) -> tuple[int, int]:
        """Where a start ends: the activity's screen, or with the Remote Assistant on its
        note first - Logitech's `1F FB00` then `[71 80vv, 7E note, 7E screen]`."""
        if self.assistant is None:
            return shown
        choose = self.n.object([(ASSISTANT_TEST | self.var(self.assistant), COMPARE),
                                (self.assistant_screens[index], ENTER_MODE), shown])
        return self.n.object([(LOAD_BYTE_REGISTER, 0x1F), (choose, OBJECT_ATOM)]), OBJECT_ATOM

    def place_tour_start(self, resolve, at: int) -> None:
        """The welcome tour's start: the wiring's third entry list runs `[mark := 1, call
        the tour's exit]`, the form MyHarmony compiles after a first sync. Shown - unless
        the project's settings say `welcome: never` - it enters the tour's first page
        instead, as a first sync's does; the mark, seeded 0 by every write, stops it
        running twice (Danny Bloemendaal's harmony-explorations, finding 286)."""
        self.tour_screens, self.tour_exit = [], None
        settings = self.project.get("settings") or {}
        wiring = self.wiring
        try:
            entry = wiring["objects"][wiring["lead"][3][0]["object"]]
            start = entry[-1][0]["object"]
            mark, exit_ = wiring["objects"][start]
            exit_[0]["object"]                              # noqa: B018 - an object call
        except (IndexError, KeyError, TypeError, ValueError):
            return
        if str(settings.get("welcome", "first")) == "never":
            return
        self.tour_screens = list(range(at, at + len(TOUR)))
        self.tour_exit = resolve(exit_)
        self.n.objects[self.wiring_objects[start]] = object_body(
            [resolve(mark), (self.tour_screens[0], ENTER_MODE)])

    def place_tour(self) -> None:
        """The welcome tour's pages, as Logitech's: the text from the top left, what to
        press below it, each page going on with the key it names and back with the left
        arrow; the last one's Exit goes where a skipped tour would have."""
        if not self.tour_screens:
            return
        fonts = self.fonts
        message, softkey = fonts.roles["message"], fonts.roles["softkey"]
        height = fonts.records[message]["height"]
        model = self.model or ("Harmony 700" if "700" in WIRING_SCHEMA else "Harmony 650")
        for number, (onward, word) in enumerate(TOUR):
            ordinal = self.tour_screens[number]
            if len(self.screens) != ordinal:
                raise ValueError("a page of the welcome tour is not where the tour goes")
            body = self.tour_lines(self.words(f"tour.{number + 1}", model=model), message)
            prompt = self.words(f"tour.{number + 1}.prompt") \
                if catalogue.has(f"tour.{number + 1}.prompt") else None
            word = self.words(word) if word else None
            placed = [(line, TOUR_TOP + height * row) for row, line in enumerate(body)]
            if prompt:
                lines = self.tour_lines(prompt, message)
                # over a softkey the prompt follows the text after a blank line
                top = TOUR_TOP + height * (len(body) + 1) if word else min(
                    TOUR_PROMPT_Y, SCREEN - height * len(lines))
                placed += [(line, top + height * row) for row, line in enumerate(lines)]
            out = [{"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": "backdrop"}},
                   {"opcode": "attribute", "value": message}]
            for line, y in placed:
                glyphs, _width = fonts.label(line, message, SCREEN)
                out.append({"opcode": "inline_text", "x": 3, "y": y, "glyphs": glyphs})
            if word:
                out += [{"opcode": "sized_bitmap", "x": 0, "y": 0, "reserved": "0000",
                         "width": SCREEN, "height": SCREEN,
                         "target": {"picture": "softkey"}},
                        {"opcode": "attribute", "value": softkey}]
                glyphs, width = fonts.label(word, softkey, 100)
                out.append({"opcode": "inline_text", "x": (SCREEN - width) // 2,
                            "y": SOFTKEY_Y, "glyphs": glyphs})
            out.append({"opcode": "end"})
            name = f"tour:{number}"
            self.blocks[name] = out
            header = []
            if number:
                header.append((TOUR_LEFT, self.tour_screens[number - 1], ENTER_MODE))
            if number + 1 < len(TOUR):
                header += [(key, self.tour_screens[number + 1], ENTER_MODE) for key in onward]
            else:
                header.append((keys.code(keys.CENTRE), *self.tour_exit))
            self.screen(header, [([], name)])

    def tour_lines(self, text: str, attribute: int) -> list[str]:
        """A tour page's text wrapped between its words across the screen, from x 3."""
        lines = []
        for word in text.split():
            if lines and self.fonts.width(f"{lines[-1]} {word}", attribute) <= TOUR_ROOM:
                lines[-1] += f" {word}"
            else:
                lines.append(word)
        return lines

    def assistant_screen(self, index: int) -> None:
        """The Remote Assistant's note after activity ``index`` starts, as a 700 of
        Logitech's draws it: titled, the note centred below, "Turn off Assistant" over
        the left side key, which turns it off and goes on to the activity as Exit does."""
        fonts = self.fonts
        title, message, answer, softkey = (fonts.roles[role] for role in (
            "title", "message", "answer", "softkey"))
        home = self.activity_screens[index]
        out = [{"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": "backdrop"}},
               {"opcode": "sized_bitmap", "x": 0, "y": 0, "reserved": "0000",
                "width": SCREEN, "height": 16, "target": {"picture": "title-bar"}},
               {"opcode": "attribute", "value": title}]
        glyphs, _width = fonts.label(self.words("assistant.title"), title, SCREEN)
        out += [{"opcode": "inline_text", "x": 3, "y": TITLE_XY[1], "glyphs": glyphs},
                {"opcode": "attribute", "value": message}]
        note = self.words("assistant.note")
        for number, line in enumerate(self.question_lines(note, message, SCREEN - 4)):
            glyphs, width = fonts.label(line, message, SCREEN)
            out.append({"opcode": "inline_text", "x": (SCREEN - width) // 2,
                        "y": ASSISTANT_FIRST_Y + QUESTION_PITCH * number, "glyphs": glyphs})
        out.append({"opcode": "attribute", "value": answer})
        for number, line in enumerate(self.words("assistant.turn-off").split("\n")):
            glyphs, _width = fonts.label(line, answer, SCREEN)
            out.append({"opcode": "inline_text", "x": ANSWER_NO_X,
                        "y": ANSWER_Y + fonts.records[answer]["height"] * number,
                        "glyphs": glyphs})
        out += [{"opcode": "sized_bitmap", "x": 0, "y": 0, "reserved": "0000",
                 "width": SCREEN, "height": SCREEN, "target": {"picture": "softkey"}},
                {"opcode": "attribute", "value": softkey}]
        glyphs, width = fonts.label(self.words("softkey.exit"), softkey, 60)
        out += [{"opcode": "inline_text", "x": (SCREEN - width) // 2, "y": SOFTKEY_Y,
                 "glyphs": glyphs}, {"opcode": "end"}]
        name = f"assistant:{index}"
        self.blocks[name] = out
        turn_off = self.n.object([self.write(1, self.assistant), (home, ENTER_MODE)])
        self.screen([(keys.code(keys.CENTRE), home, ENTER_MODE)],
                    [([(ANSWER_NO, turn_off, OBJECT_ATOM)], name)])

    def notice_screen(self, ordinal: int, name: str, title: str) -> None:
        """A start-up screen: Logitech's working picture - the one "Attempting to fix"
        draws (650-b screens 89 and 107) - ``title`` centred at the top in the
        firmware's message font, "Please keep the remote pointed at your system" below,
        and every key bound to nothing."""
        if len(self.screens) != ordinal:
            raise ValueError(f"start-up screen {name!r} is not where its start goes")
        fonts, attribute = self.fonts, self.fonts.roles["notice"]
        _font, lines = self.label_lines(title, attribute, NOTICE_ROOM)
        lines = [self._fit(line, attribute, NOTICE_ROOM) for line in lines]
        height = fonts.records[attribute]["height"]
        out = [{"opcode": "bitmap", "x": 0, "y": 0,
                "target": {"picture": self.pictures_or("page/working")}},
               {"opcode": "attribute", "value": attribute}]
        placed = [(line, NOTICE_TITLE_Y + height * number) for number, line in enumerate(lines)]
        placed += [(line, NOTICE_LINES_Y + height * number)
                   for number, line in enumerate(self.paragraph(
                       self.words("notice.keep-pointed").split("\n"), attribute))]
        for line, y in placed:
            glyphs, width = fonts.label(line, attribute, SCREEN)
            out.append({"opcode": "inline_text", "x": (SCREEN - width) // 2, "y": y,
                        "glyphs": glyphs})
        out.append({"opcode": "end"})
        self.blocks[f"notice:{name}"] = out
        self.screen([(code, 0, 0) for code in NOTICE_KEYS], [([], f"notice:{name}")])

    # -- Help held: the delays

    def held_help(self) -> list[tuple[int, int]]:
        """Help held in an activity or Off: "Delay Fixing", over the screen it was held on."""
        if self.delay_warning is None:
            return []
        return [(HELP_HELD, self.n.object([POP_MODE, (self.delay_warning, ENTER_MODE)]))]

    def place_countdowns(self) -> None:
        """Section 12's delay programs, as Logitech numbers them: entry 0 the power-on
        delay being edited, "( 4.5 sec )" - a wide switch, a case a tenth to 45 s - and
        after the corners the inter-device delay's, to 2 s."""
        self.countdowns = {}
        if not self.devices:
            return
        answer = self.fonts.roles["answer"]

        def countdown(name: str, record: dict, cases: int) -> str:
            drawn = []
            for value in range(cases):
                tenths = f".{value % 10}" if value % 10 else ""
                glyphs, width = self.fonts.label(
                    self.words("delays.seconds", seconds=f"{value // 10}{tenths}"), answer)
                drawn.append((value, {"piece": self._block(f"{name}:{value}", [
                    {"opcode": "attribute", "value": answer},
                    {"opcode": "inline_text", "x": (SCREEN - width) // 2, "y": COUNTDOWN_Y,
                     "glyphs": glyphs}, {"opcode": "end"}])}))
            switch = {"opcode": "switch", "selector": self.byte_var(record), "cases": drawn,
                      "ranges": []}
            if cases > 0x100:
                switch["wide"] = True
            return self._block(name, [switch, {"opcode": "end"}])
        self.section12[0] = countdown("countdown:power", self.power_edit, POWER_ON_CASES)
        self.countdowns = {"power": 0, "inter": len(self.section12)}
        self.section12.append(countdown("countdown:inter", self.inter_edit,
                                        INTER_DEVICE_CASES))

    def delay_header(self, *rows, off: bool = True) -> list[tuple]:
        """A delay screen's header: ``rows``, then Help and the activity keys doing
        nothing, and Off - but on "Select device" - going to Off, as Logitech's."""
        out = list(rows) + [(code, *SWALLOW) for code in (HELP, 0x81, 0x85, 0x84)]
        out += [(HELP_HELD, 0, 0), (0x87, *SWALLOW)]
        if off:
            out.append((OFF_KEY, self.n.object([(SELECT_CONTEXT | self.off_context, 0x1F)]),
                        OBJECT_ATOM))
        else:
            out.append((OFF_KEY, *SWALLOW))
        return out

    def titled(self, backdrop: str, title: str) -> list[dict]:
        """A Help screen's backdrop and title strip, its title from x 3."""
        attribute = self.fonts.roles["title"]
        glyphs, _width = self.fonts.label(self._fit(title, attribute, ACTIVITY_SCREEN_ROOM),
                                          attribute, SCREEN)
        return [{"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": backdrop}},
                {"opcode": "sized_bitmap", "x": 0, "y": 0, "reserved": "0000",
                 "width": SCREEN, "height": 16, "target": {"picture": "title-bar"}},
                {"opcode": "attribute", "value": attribute},
                {"opcode": "inline_text", "x": DELAY_TEXT_X, "y": TITLE_XY[1],
                 "glyphs": glyphs}]

    def lines_at(self, lines, attribute: int, top: int, centred: bool) -> list[dict]:
        out = [{"opcode": "attribute", "value": attribute}]
        height = QUESTION_PITCH
        for number, line in enumerate(lines):
            glyphs, width = self.fonts.label(line, attribute, SCREEN)
            out.append({"opcode": "inline_text",
                        "x": (SCREEN - width) // 2 if centred else DELAY_TEXT_X,
                        "y": top + height * number, "glyphs": glyphs})
        return out

    def answers(self, left: str, right: str, y: int = ANSWER_Y) -> list[dict]:
        """Words over the two bottom keys in the answer font: "No"/"Yes", "-"/"+"."""
        attribute = self.fonts.roles["answer"]
        out = [{"opcode": "attribute", "value": attribute}]
        if left:
            glyphs, _width = self.fonts.label(left, attribute, SCREEN)
            out.append({"opcode": "inline_text", "x": ANSWER_NO_X, "y": y, "glyphs": glyphs})
        glyphs, width = self.fonts.label(right, attribute, SCREEN)
        out.append({"opcode": "inline_text", "x": ANSWER_YES_RIGHT - width, "y": y,
                    "glyphs": glyphs})
        return out

    def softkey_word(self, word: str) -> list[dict]:
        attribute = self.fonts.roles["softkey"]
        glyphs, width = self.fonts.label(word, attribute, 60)
        return [{"opcode": "sized_bitmap", "x": 0, "y": 0, "reserved": "0000",
                 "width": SCREEN, "height": SCREEN, "target": {"picture": "softkey"}},
                {"opcode": "attribute", "value": attribute},
                {"opcode": "inline_text", "x": (SCREEN - width) // 2, "y": SOFTKEY_Y,
                 "glyphs": glyphs}]

    def delay_step(self, record: dict, step: int, up: bool) -> int:
        """- or + on a delay screen, as Logitech's: within its bounds (more than a step
        for the power-on delay's -, more than 0 for the inter-device one's, less than the
        last case for +), round the edited delay down to a step, then step it - down only
        if that left it above the first step - and redraw."""
        edit, scratch = self.byte_var(record), self.byte_var(self.delay_scratch)
        power = record is self.power_edit
        rounded = self.n.object([
            (LOAD_VARIABLE | edit, 0x1F), (STORE | scratch, 0x1F),
            (LOAD_VARIABLE | edit, 0x1F), (step, MODULO),
            (self.n.object([(SUBTRACT << 8 | scratch, COMPARE_ACC), (0, 0)]), OBJECT_ATOM),
            (0, LOAD_ACC), (LOAD_VARIABLE | scratch, 0x1F), (STORE | edit, 0x1F)])
        moved = self.n.object([(LOAD_VARIABLE | edit, 0x1F),
                               ((step if up else -step) & 0xFFFF, ADD),
                               (STORE | edit, 0x1F)])
        if power:
            bound, test = (record["limit"], LESS) if up else (step, GREATER)
            load, compare = (bound, LOAD_ACC), COMPARE_ACC
        else:
            bound, test = (record["limit"], LESS) if up else (0, GREATER)
            load, compare = (LOAD_BYTE_REGISTER | bound, 0x1F), COMPARE
        if up:
            change = (moved, OBJECT_ATOM)
        else:
            floor = (step, LOAD_ACC) if power else (LOAD_BYTE_REGISTER, 0x1F)
            change = (self.n.object([floor, (self.n.object(
                [(NOT_EQUAL << 8 | edit, compare), (moved, OBJECT_ATOM)]), OBJECT_ATOM)]),
                OBJECT_ATOM)
        body = self.n.object([(rounded, OBJECT_ATOM), change, REDRAW_SCREEN])
        return self.n.object([load, (self.n.object(
            [(test << 8 | edit, compare), (body, OBJECT_ATOM)]), OBJECT_ATOM)])

    def place_delays(self) -> None:
        """Help held's screens, in the order place_wiring numbered them."""
        if len(self.screens) != self.delay_warning:
            raise ValueError("Delay Fixing is not where Help held goes")
        centre = keys.code(keys.CENTRE)
        top = [keys.code(keys.SCREEN_KEYS[corner]) for corner in ("top-left", "top-right")]
        bottom = [ANSWER_NO, ANSWER_YES]
        message = self.fonts.roles["message"]
        # "Delay Fixing": go on, or back where Help was held
        self.blocks["delays:warning"] = (
            self.titled("backdrop", self.words("delays.title"))
            + self.lines_at(self.paragraph(self.words("delays.warning").split("\n"), message),
                            message, DELAY_WARNING_Y, centred=True)
            + self.answers(self.words("answer.no"), self.words("answer.yes"))
            + self.softkey_word(self.words("softkey.exit")) + [{"opcode": "end"}])
        self.screen(self.delay_header((centre, *EXIT_DELAYS)),
                    [([(ANSWER_NO, *EXIT_DELAYS), (ANSWER_YES, self.delay_select, ENTER_MODE)],
                      "delays:warning")])
        screens = {device["index"]: screen
                   for device, screen in zip(self.devices, self.delay_screens)}
        self.screen(self.delay_header((centre, *EXIT_DELAYS), off=False),
                    self.device_list_pages(
                        self.words("softkey.exit"), "delays",
                        title=self.words("delays.select-title"), corner=None,
                        backdrop=self.pictures_or("page/select"),
                        opens=lambda device: (screens[device["index"]]["menu"], ENTER_MODE)))
        row = self.fonts.roles.get("delay_row", self.fonts.roles["menu_row"])
        for number, device in enumerate(self.devices):
            ordinals, saves = self.delay_screens[number], self.delay_saves[number]
            power, inter = self.power_on[number], self.inter_device[number]
            label = device["label"]
            if len(self.screens) != ordinals["menu"]:
                raise ValueError("a device's delay screens are not where its row goes")
            # its menu: set to default, or change a delay
            reset = self.n.object([
                (power["initial"], LOAD_ACC), (STORE | self.byte_var(power), 0x1F),
                (inter["initial"], LOAD_ACC), (STORE | self.byte_var(inter), 0x1F),
                saves["power"], saves["inter"], (ordinals["reset"], ENTER_MODE)])
            for name, lines, back, keyed in (
                    ("menu", (self.words("delays.set-default"), self.words("delays.change")),
                     self.delay_select,
                     ((reset, OBJECT_ATOM), (ordinals["change"], ENTER_MODE))),
                    ("change", (self.words("delays.power-on"),
                                self.words("delays.inter-device")), ordinals["menu"],
                     tuple((self.n.object([
                         (LOAD_VARIABLE | self.byte_var(source), 0x1F),
                         (STORE | self.byte_var(edit), 0x1F),
                         (ordinals[kind], ENTER_MODE)]), OBJECT_ATOM)
                         for kind, source, edit in (("power", power, self.power_edit),
                                                    ("inter", inter, self.inter_edit))))):
                block = f"delays:{number}:{name}"
                self.blocks[block] = self.page(
                    backdrop=self.pictures_or("page/delays"),
                    softkey=self.words("softkey.back"),
                    title=self._fit(label, self.fonts.roles["title"], ACTIVITY_SCREEN_ROOM),
                    corners=[], title_x=DELAY_TEXT_X,
                    rows=[(at, *self.label_lines(line, row, MENU_ROOM))
                          for at, line in enumerate(lines)])
                rows = [(code, *keyed[0]) for code in top] + [
                    (code, *keyed[1]) for code in bottom]
                self.screen(self.delay_header((centre, back, ENTER_MODE)), [(rows, block)])
            # the two delay screens: - and +, Done copies the edit back and saves it
            for kind, which, record, edit, step in (
                    ("power", "power-on", power, self.power_edit, POWER_STEP),
                    ("inter", "inter-device", inter, self.inter_edit, INTER_STEP)):
                block = f"delays:{number}:{kind}"
                lines = self.question_lines(
                    self.words(f"delays.set-{which}", device=label), message,
                    NOTICE_ROOM - DELAY_TEXT_X)[:QUESTION_LINES - 1]
                self.blocks[block] = (
                    self.titled("backdrop", self.words(f"delays.{which}-title"))
                    + [{"opcode": "atom", "operand": self.countdowns[kind],
                        "category": DRAW_OVERLAY}]
                    + self.lines_at(lines, message, DELAY_TEXT_Y, centred=False)
                    + self.answers("-", "+") + self.softkey_word(self.words("softkey.done"))
                    + [{"opcode": "end"}])
                done = self.n.object([
                    (LOAD_VARIABLE | self.byte_var(edit), 0x1F),
                    (STORE | self.byte_var(record), 0x1F), saves[kind],
                    (ordinals["change"], ENTER_MODE)])
                self.screen(self.delay_header((centre, done, OBJECT_ATOM)), [(
                    [(ANSWER_NO, self.delay_step(edit, step, False), OBJECT_ATOM),
                     (ANSWER_YES, self.delay_step(edit, step, True), OBJECT_ATOM)], block)])
            # "Delay settings for ... are now set to default"
            block = f"delays:{number}:reset"
            idle = ([{"opcode": "atom", "operand": self.corners["idle"],
                      "category": DRAW_OVERLAY}] if "idle" in self.corners else [])
            lines = self.question_lines(self.words("delays.reset", device=label),
                                        message, NOTICE_ROOM - DELAY_TEXT_X)
            self.blocks[block] = (
                [{"opcode": "bitmap", "x": 0, "y": 0, "target": {"picture": "backdrop"}}]
                + idle + self.lines_at(lines, message, RESET_TEXT_Y, centred=False)
                + self.answers("", self.words("answer.ok"), OK_Y) + [{"opcode": "end"}])
            redraw = ([(REDRAW, self.corners["idle"], DRAW_OVERLAY)]
                      if "idle" in self.corners else [])
            self.screen(self.delay_header(*redraw),
                        [([(ANSWER_YES, ordinals["menu"], ENTER_MODE)], block)])

    # -- laying out

    def lay_out(self) -> bytes:
        from . import gspm

        pieces = Pieces(self.header)
        self.pieces = pieces
        self._plan_section9()
        # drawing blocks, each a piece: page programs and the firmware screens' blocks
        for name, block in self.blocks.items():
            pieces.add(f"block:{name}", self._program(block))
        # mode lists, key registers come with section 9
        for ordinal, screen in enumerate(self.screens):
            if screen["header"] != "mode-zero":
                pieces.add(f"header:{ordinal}", self._header_list(screen["header"]))
            pieces.add(f"trailer:{ordinal}", self._trailer(ordinal, screen))
        for device in self.devices:
            for command in device["commands"]:
                for phase, body in sorted(command["phases"].items()):
                    pieces.add(f"wave:{command['command_id']}:{phase}", _constant(body))
                # a toggling (RC5/RC6) command's other state, sent on every other press
                for phase, body in sorted((command.get("alternate_phases") or {}).items()):
                    pieces.add(f"wave:{command['command_id']}:other:{phase}", _constant(body))
                pieces.add(f"command:{command['command_id']}", self._record(command))
        for index, body in enumerate(self.n.objects):
            pieces.add(f"object:{index}", _constant(body))
        for index, context in enumerate(self.n.contexts):
            pieces.add(f"context:{index}", _constant(structures.context_record(context)))
        for index, group in enumerate(self.n.groups):
            for value, atoms in group:
                pieces.add(f"case:{index}:{value}", _constant(_atoms_program(atoms)))
            pieces.add(f"group:{index}", self._group(index, group))
        for index, timer in enumerate(self.timers):
            pieces.add(f"timer:{index}", _constant(timer_record(*timer)))
        # section 17: a number sender per device favourites dial, as Logitech's
        senders = self.number_senders()
        for index, objects in enumerate(senders):
            pieces.add(f"sender-table:{index}", _constant(b"".join(
                struct.pack("<HB", item, OBJECT_ATOM) for item in objects)))
            pieces.add(f"sender:{index}", lambda p, index=index: (
                bytes(14) + p.pointer(f"sender-table:{index}") * 3))
        records = (self.records + [record for _name, record in self.n.narrow]
                   + [record for _name, record in self.n.wide])
        for index, record in enumerate(records):
            pieces.add(f"record:{index}", _constant(engine_record(
                {**record, "padding": 0, "transitions": record.get("transitions", [])})))
        for attribute, font in enumerate(self.fonts.records):
            for code, body in sorted(font["glyphs"].items()):
                pieces.add(f"glyph:{attribute}:{code}", _constant(body))
            pieces.add(f"font:{attribute}", self._font(attribute, font))
        # the tables, in ascending order, then the pictures after section 19's count
        names = self._names()
        sections = {
            0: _constant(name_chain(names)),
            1: _constant(self._section1()),
            2: _constant(bytes.fromhex(self.constants["section2"])),
            3: _constant(structures.stamp(*self.stamp_fields)),
            4: self._section4,
            5: self._section5,
            6: lambda p: self._index("trailer", len(self.screens), 2, reserved=True)(p),
            7: self._index("font", len(self.fonts.records), 2),
            9: self._section9,
            10: self._index("context", len(self.n.contexts), 1),
            11: self._index("object", len(self.n.objects), 2),
            12: self._section12,
            13: self._index("timer", len(self.timers), 1),
            14: self._engine(len(records)),
            15: self._section15,
            16: self._section16,
            17: (lambda p: bytes([len(senders)]) + b"".join(
                p.pointer(f"sender:{index}") for index in range(len(senders))))
            if senders else _constant(bytes.fromhex(self.constants["section17"])),
            19: _constant(b"\x00\x00"),
        }
        for index in sorted(sections):
            pieces.add(f"section:{index}", sections[index], window=False)
        for role in sorted(self.drawn):
            pieces.add(f"picture:{role}", _constant(self.pictures[role]), window=False)
        out = pieces.lay_out()
        image = gspm.seal(bytes(out))
        gspm.validate(image)
        return image

    def number_senders(self) -> list[list[int]]:
        """Each device that an activity's favourite channels dial, as section 17's number
        sender has it (gspm.md, "Favourites"): its 0 to 9 commands' objects. A build
        dials the digits itself; the table says which command is which digit, as
        Logitech's does, so an import names them so (Number0 to Number9)."""
        from .activities import _digit_command

        specs = self.project.get("devices") or []
        ids = [spec.get("id") for spec in specs]
        out, seen = [], set()
        for act in self.project.get("activities") or []:
            dials = any(entry[1] == "channel" for entry in act.get("image_buttons") or [])
            dials = dials or bool(act.get("channels"))
            control = act.get("control")
            if not dials or control not in ids or control in seen:
                continue
            index = ids.index(control)
            commands = {command["name"]: command for command in self.devices[index]["commands"]}
            names = [_digit_command(specs[index], str(digit)) for digit in range(10)]
            if all(name in commands for name in names):
                seen.add(control)
                out.append([commands[name]["object"] for name in names])
        return out

    def header(self, p: Pieces) -> bytes:
        from . import gspm

        out = bytearray(b"GSPM" + bytes(4) + struct.pack("<I", gspm.HEADER_CONSTANT))
        for slot, section in enumerate(gspm.SLOT_SECTIONS):
            out += struct.pack("<I", p.address(f"section:{section}") if p.final else 0)
        out += bytes(gspm.BUTTON_MAP_OFFSET - len(out)) + gspm.BUTTON_MAP_MAGIC
        out.append(len(self.mode_zero))
        for code, operand, category in self.mode_zero:
            out += struct.pack("<BHB", code, operand, category)
        return bytes(out)

    def _program(self, block):
        def produce(p: Pieces) -> bytes:
            items = []
            for item in block:
                item = dict(item)
                target = item.get("target")
                if isinstance(target, dict) and "picture" in target:
                    self.drawn.add(target["picture"])
                    item["target"] = p.offset(f"picture:{target['picture']}")
                elif isinstance(target, dict) and "block" in target:
                    item["target"] = p.offset(f"block:sys:{target['block']}")
                if item["opcode"] == "switch":
                    where = lambda at: (p.offset(at["piece"]) if isinstance(at, dict)  # noqa: E731
                                        else p.offset(f"block:sys:{at}"))
                    item["cases"] = [(value, where(at)) for value, at in item["cases"]]
                    item["ranges"] = [(low, high, where(at))
                                      for low, high, at in item["ranges"]]
                items.append(item)
            return drawing.encode_program(items)
        # every picture a program draws has to be placed: note them now
        for item in block:
            target = item.get("target")
            if isinstance(target, dict) and "picture" in target:
                self.drawn.add(target["picture"])
        return produce

    def _section1(self) -> bytes:
        """Section 1 as the scaffold's donor has it, its skin byte the remote's: a build
        for the skin a project names says that skin (a Harmony 665 is a 650 that says 75)."""
        out = bytearray.fromhex(self.constants["section1"])
        skin = (self.project.get("settings") or {}).get("skin")
        if skin is not None:
            out[SECTION1_SKIN] = skin
        return bytes(out)

    def _section12(self, p: Pieces) -> bytes:
        """The screen program table, `u16` count then a pointer each: the corner programs."""
        return (struct.pack("<H", len(self.section12))
                + b"".join(p.pointer(name) for name in self.section12))

    def _header_list(self, rows):
        return _constant(structures.key_register(list(rows)))

    def _trailer(self, ordinal, screen):
        def produce(p: Pieces) -> bytes:
            if screen["header"] == "mode-zero":
                from . import gspm
                header = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC)
            else:
                header = p.offset(f"header:{ordinal}")
            slots = [p.offset("section:9") + self.slot_at[(ordinal, page)]
                     for page in range(len(screen["pages"]))]
            return structures.screen_trailer(screen["flag"], header, slots)
        return produce

    def _record(self, command):
        from . import records

        def produce(p: Pieces) -> bytes:
            phases = {phase: p.offset(f"wave:{command['command_id']}:{phase}")
                      for phase in command["phases"]}
            others = {phase: p.offset(f"wave:{command['command_id']}:other:{phase}")
                      for phase in command.get("alternate_phases") or {}}
            return records.command_record(
                p.offset(f"command:{command['command_id']}"), phases["press"],
                phases.get("hold"), command["carrier_period_ns"],
                command["carrier_half_period_ns"], release_offset=phases.get("release"),
                alternate=((others["press"], others.get("hold"), others.get("release"))
                           if others else None))
        return produce

    def _device_records(self, p: Pieces) -> list[list[int]]:
        return [[p.offset(f"command:{command['command_id']}") for command in device["commands"]]
                for device in self.devices]

    def _section4(self, p: Pieces) -> bytes:
        return structures.command_flat_index(self._device_records(p),
                                             first_key=self.fw - STATUS_SCREENS)

    def _section5(self, p: Pieces) -> bytes:
        """A device count, then each device's run in section 4, which its sub-table is."""
        from . import gspm

        run = p.offset("section:4") + structures.COMMAND_INDEX_HEAD_SIZE
        out = bytearray([len(self.devices)])
        for records in self._device_records(p):
            out += (gspm.BASE + run).to_bytes(3, "little")
            run += len(structures.command_subtable(records))
        return bytes(out)

    def _plan_section9(self):
        """Where each page's slot record sits in section 9: after the start-up list, all
        the slot records, then the key registers they point at."""
        self.slot_at, cursor = {}, len(object_body(self.lead))
        for ordinal, screen in enumerate(self.screens):
            for page in range(len(screen["pages"])):
                self.slot_at[(ordinal, page)] = cursor
                cursor += 6

    def _section9(self, p: Pieces) -> bytes:
        """The start-up list, every page's six-byte slot record, then its key register."""
        out = bytearray(object_body(self.lead))
        layout = []
        for ordinal, screen in enumerate(self.screens):
            for page, (rows, program) in enumerate(screen["pages"]):
                if self.slot_at[(ordinal, page)] != len(out):
                    raise ValueError("section 9's slot records moved")
                out += bytes(6)
                layout.append((len(out) - 6, rows, program))
        for slot, rows, program in layout:
            register = len(out)
            out += structures.key_register(list(rows))
            out[slot:slot + 6] = ((p.address("section:9") + register).to_bytes(3, "little")
                                  + p.pointer(f"block:{program}"))
        return bytes(out)

    def _index(self, kind: str, count: int, width: int, reserved: bool = False):
        def produce(p: Pieces) -> bytes:
            head = count.to_bytes(width, "little") + (b"\x00" if reserved else b"")
            return head + b"".join(p.pointer(f"{kind}:{index}") for index in range(count))
        return produce

    def _engine(self, count: int):
        narrow = self.firmware_count + len(self.n.narrow)
        wide = len(self.n.wide)

        def produce(p: Pieces) -> bytes:
            return (struct.pack("<HHHH", count, narrow, wide, narrow)
                    + b"".join(p.pointer(f"record:{index}") for index in range(count)))
        return produce

    def _group(self, index, group):
        def produce(p: Pieces) -> bytes:
            out = bytearray([2]) + struct.pack("<H", len(group))
            for value, _atoms in group:
                out += struct.pack("<H", value) + p.pointer(f"case:{index}:{value}")
            return bytes(out + b"\x00")
        return produce

    def _section15(self, p: Pieces) -> bytes:
        tail = bytes.fromhex(self.constants["tail"])
        return (bytes([len(self.n.groups)])
                + b"".join(p.pointer(f"group:{index}") for index in range(len(self.n.groups)))
                + tail)

    def _section16(self, p: Pieces) -> bytes:
        from . import gspm

        tail = p.offset("section:15") + 1 + 3 * len(self.n.groups)
        offsets = self.constants["tail_offsets"]
        return bytes([len(offsets)]) + b"".join(
            (gspm.BASE + tail + offset).to_bytes(3, "little") for offset in offsets)

    def _font(self, attribute, font):
        def produce(p: Pieces) -> bytes:
            count = max(font["glyphs"])
            out = bytearray([font["height"], 1, count])
            for code in range(1, count + 1):
                out += (p.pointer(f"glyph:{attribute}:{code}") if code in font["glyphs"]
                        else bytes(3))
            return bytes(out)
        return produce

    def _names(self) -> list[bytes]:
        named = self.n.narrow + self.n.wide
        leaves = [(self.firmware_count + number, name)
                  for number, (name, _record) in enumerate(named) if name]
        return ([name_record(0, "Root", leaf=False), name_record(1, "State", leaf=False)]
                + [name_record(index, name) for index, name in leaves])


def _words(name: str) -> str:
    """A command's name with its words apart, as a label shows it: `PowerToggle` is
    "Power Toggle", `InputHdmi1` "Input Hdmi1", and `TVProgrammas` "TV Programmas", as a
    Dutch 650 draws it - an initialism ends where a capitalised word begins."""
    out = ""
    for index, char in enumerate(name):
        if index and char.isupper() and (
                name[index - 1].islower()
                or (name[index - 1].isupper() and index + 1 < len(name)
                    and name[index + 1].islower())):
            out += " "
        out += char
    return out


def _drawn_name(name: str, names: set[str]) -> str:
    """The label a command's page draws: its name, less the ` (2)` an import gives the
    second of two commands a page drew alike - Logitech's cut names, `VolumeFrontRight..`
    for two - so the page draws them alike again, and an import names them the same."""
    match = re.match(r"^(?P<base>.+) \((?P<number>\d+)\)$", name)
    if match and match["base"] in names:
        return match["base"]
    return name


def _press_alone(command: dict) -> None:
    """A press with no hold after it starts at its first mark on arch 14: its lead-in
    space comes only with a hold (docs/harmony_650_700/gspm.md, "IR waveforms")."""
    phases = command["phases"]
    if "hold" in phases:
        return
    body = phases["press"]
    at = 0
    while at + 2 <= len(body) and not struct.unpack_from("<H", body, at)[0] & 0x8000:
        at += 2
    phases["press"] = body[at:]


def _constant(body: bytes):
    return lambda _p: body


def _atoms_program(atoms) -> bytes:
    """A switch case's block: its instructions as atoms, then the end."""
    return drawing.encode_program(
        [{"opcode": "atom", "operand": operand, "category": category}
         for operand, category in atoms] + [{"opcode": "end"}])


def _has(words, key: str) -> bool:
    try:
        words(key)
        return True
    except (KeyError, ValueError):
        return False


def build_stamp(now=None) -> tuple:
    """The clock a configuration starts with: when it was built, as section 3 and the
    clock variables hold it (day and month counted from 0)."""
    import datetime

    now = datetime.datetime.now() if now is None else now
    return (now.second, now.minute, now.hour, now.day - 1, now.month - 1, now.year)


def build(project: dict, *, directory=None, stamp_fields=None, look=None,
          model=None) -> dict:
    """Build an image for ``project`` from the scaffold. ``look`` is the scaffold of the
    model's own look, ``model`` its name for the welcome tour - from its profile."""
    from ... import paths

    directory = Path(paths.scaffolds("harmony-650") if directory is None else directory)
    stamp_fields = build_stamp() if stamp_fields is None else stamp_fields
    words = catalogue.for_project(project)
    image = Image(project, directory, stamp_fields, words, look=look, model=model)
    return {"image": image.build(), "skipped": list(image.plan["skipped"])}
