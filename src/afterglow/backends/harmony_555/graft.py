"""A model's platform as another's with some of its parts replaced, measured from that
model's own configurations.

The 515 and 510 run another firmware build than the 555's: their configurations reach the
firmware through other system calls and wire every key of the global key set to an object
of its own, where the 555's share one. Their households hold the 555's empty platform in
every other part. No empty configuration of theirs survives, so their platform is the
555's with those parts grafted in from a household of theirs (`graft`), and what a
household changes in any platform - the idle key set, the menu, the battery screens, the
switch tables answering by the activity - is never taken from one (`HOUSEHOLD_FILE`).

Both sides are walked from the platform's roots and paired part by part; a part is taken
from the household when, its references translated into the platform's numbers, it is
not the platform's. Timers are paired by what they do, since their order changes from
one configuration to the next, and `1F EAnn` / `1F EBnn` start and stop timer nn.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import gspm, importing, ui_index

HOUSEHOLD_FILE = "platform/household.json"
HOUSEHOLD_SCHEMA = "afterglow-arch9-household/1"
FIRMWARE_SCREENS = 41
FIRMWARE_VARIABLES = 13
OBJECT, SCREEN, SWITCH, SYSTEM = 0x7F, 0x7E, 0x72, 0x1F
TESTS = (0x70, 0x71)
TIMER_CALLS = (0xEA, 0xEB)
SELECT_CONTEXT = 0xFF


@dataclass
class View:
    """A configuration's wiring, as numbers: objects' atoms, contexts' rows, switch tables'
    cases (value, atoms), screens' key lists, timers, the start-up list."""
    objects: list
    contexts: list
    tables: list
    screens: list           # (header rows, [page rows])
    timers: list            # (flags, seconds, operand, category)
    lead: list
    variables: int
    idle: int = field(default=-1)

    def __post_init__(self):
        for key, operand, category in self.contexts[1]:
            if key == 0xB6 and category == SYSTEM and operand >> 8 == SELECT_CONTEXT:
                self.idle = operand & 0xFF
        if self.idle < 0:
            raise ValueError("no idle context: Off selects none")


def model_view(wiring: dict, screens: dict) -> View:
    """A scaffold's platform model (wiring.json, screens.json) as a View."""
    programs = [[tuple(atom) for atom in atoms] for atoms in wiring["programs"]]
    return View(
        objects=[[tuple(atom) for atom in atoms] for atoms in wiring["objects"]],
        contexts=[[(row[1], row[2], row[3]) for row in context["rows"]]
                  for context in wiring["contexts"]],
        tables=[[(value, programs[program]) for value, program in table["cases"]]
                for table in wiring["tables"]],
        screens=[([tuple(row) for row in screen["keys"]],
                  [[tuple(row) for row in page["keys"]] for page in screen["pages"]])
                 for screen in screens["screens"]],
        timers=[tuple(timer) for timer in wiring["timers"]],
        lead=[tuple(atom) for atom in wiring["lead"]],
        variables=len(wiring["variables"]))


def image_view(payload: bytes) -> View:
    """A configuration as a View."""
    image = importing.Image(payload)
    tables = []
    for group in image.groups:
        cases = []
        for value, block in group["cases"]:
            atoms = [(item["operand"], item["category"])
                     for item in ui_index.drawing_program(payload, block)["instructions"]
                     if item["opcode"] == "atom"]
            cases.append((value, atoms))
        tables.append(cases)
    ranges = gspm.section_ranges(payload)
    s13 = ranges[13][0]
    timers = []
    for index in range(payload[s13]):
        at = int.from_bytes(payload[s13 + 1 + 3 * index:s13 + 4 + 3 * index], "little") \
            - gspm.BASE
        timers.append((payload[at], int.from_bytes(payload[at + 1:at + 4], "little"),
                       *struct.unpack_from("<HB", payload, at + 4)))
    s9 = ranges[9][0]
    lead = [struct.unpack_from("<HB", payload, s9 + 1 + 3 * index)
            for index in range(payload[s9])]
    return View(
        objects=[list(item["atoms"]) for item in image.objects],
        contexts=[[(row["key_code"], row["operand"], row["category"]) for row in c["rows"]]
                  for c in image.contexts],
        tables=tables,
        screens=[([(e["key_code"], e["operand"], e["category"])
                   for e in screen["header_entries"]],
                  [[(e["key_code"], e["operand"], e["category"]) for e in slot["entries"]]
                   for slot in screen["slots"]])
                 for screen in image.screens],
        timers=timers, lead=lead, variables=len(image.engine))


def _found(atoms, wanted) -> bool:
    return any(atom == wanted for atom in atoms)


def timer_role(view: View, timer: tuple, depth: int = 4) -> str:
    """What a timer does, by the calls its object makes: the backlight's (E900 first),
    the sleep's (F101), the screen watch's (71 810C), the poll's (07 FFFC), and the one
    that stops another (E910 first)."""
    def calls(operand, category, level):
        if category == OBJECT and level >= 0 and 0 <= operand < len(view.objects):
            out = []
            for atom in view.objects[operand]:
                out += calls(*atom, level - 1)
            return out
        return [(operand, category)]
    atoms = calls(timer[2], timer[3], depth)
    if (0xF101, 0x3F) in atoms:
        return "sleep"
    if (0x810C, 0x71) in atoms:
        return "watch"
    if (0xFFFC, 0x07) in atoms:
        return "poll"
    if atoms[:1] == [(0xE910, SYSTEM)]:
        return "stop"
    if (0xE900, SYSTEM) in atoms:
        return "backlight"
    return "unknown"


class Pairing:
    """The parts of two configurations that stand in the same place, walked from the
    platform's roots: the first pairing of a part is kept."""

    def __init__(self, a: View, b: View):
        self.a, self.b = a, b
        self.map = {kind: {} for kind in ("object", "screen", "table", "context",
                                          "variable")}
        self.todo: list = []
        for context in range(4):
            self.pair("context", context, context)
        self.pair("context", a.idle, b.idle)
        for screen in range(FIRMWARE_SCREENS):
            self.pair("screen", screen, screen)
        self.atoms(a.lead, b.lead)
        self.timers = self._timers()
        for x, y in self.timers.items():
            self.atoms([a.timers[x][2:]], [b.timers[y][2:]])
        while self.todo:
            kind, x, y = self.todo.pop()
            getattr(self, "walk_" + kind)(x, y)

    def _timers(self) -> dict[int, int]:
        roles = {}
        for index, timer in enumerate(self.b.timers):
            roles.setdefault(timer_role(self.b, timer), index)
        out = {}
        for index, timer in enumerate(self.a.timers):
            role = timer_role(self.a, timer)
            if role in roles and roles[role] not in out.values():
                out[index] = roles[role]
        return out

    def pair(self, kind, x, y):
        if kind == "variable" and (x < FIRMWARE_VARIABLES or y < FIRMWARE_VARIABLES):
            return
        if x in self.map[kind] or y in self.map[kind].values():
            return
        self.map[kind][x] = y
        if kind in ("object", "screen", "table", "context"):
            self.todo.append((kind, x, y))

    def atoms(self, xs, ys):
        for (xo, xc), (yo, yc) in zip(xs, ys):
            if xc != yc and not (xc >= 0x80 and yc >= 0x80):
                continue
            if xc == OBJECT:
                self.pair("object", xo, yo)
            elif xc == SCREEN:
                self.pair("screen", xo, yo)
            elif xc == SWITCH:
                self.pair("table", xo >> 8, yo >> 8)
                self.pair("variable", xo & 0xFF, yo & 0xFF)
            elif xc in TESTS:
                self.pair("variable", xo & 0xFF, yo & 0xFF)
            elif xc >= 0x80:
                self.pair("variable", xc & 0x7F, yc & 0x7F)
            elif xc == SYSTEM and xo >> 8 == SELECT_CONTEXT and xo & 0xFF < 0xF0:
                self.pair("context", xo & 0xFF, yo & 0xFF)

    def rows(self, xs, ys):
        by_key = {row[0]: row[1:] for row in ys}
        for row in xs:
            if row[0] in by_key:
                self.atoms([row[1:]], [by_key[row[0]]])

    def walk_object(self, x, y):
        self.atoms(self.a.objects[x], self.b.objects[y])

    def walk_context(self, x, y):
        self.rows(self.a.contexts[x], self.b.contexts[y])

    def walk_screen(self, x, y):
        (ha, pa), (hb, pb) = self.a.screens[x], self.b.screens[y]
        self.rows(ha, hb)
        for page_a, page_b in zip(pa, pb):
            self.rows(page_a, page_b)

    def walk_table(self, x, y):
        cases_b = dict(self.b.tables[y])
        for value, atoms in self.a.tables[x]:
            if value in cases_b:
                self.atoms(atoms, cases_b[value])


class Translation:
    """Another configuration's parts in the platform's numbers: a part paired with the
    platform's and the same once translated is the platform's; any other is a new part,
    `{"new": n}`, its own references translated in turn."""

    def __init__(self, pairing: Pairing, places: set | None = None):
        self.pairing = pairing
        # grafting: a paired part not in ``places`` is the part it replaces, so the
        # model's sharing is kept; comparing (None): it is the platform's only if the same
        self.places = places
        self.back = {kind: {y: x for x, y in pairs.items()}
                     for kind, pairs in pairing.map.items()}
        self.timers = {y: x for x, y in pairing.timers.items()}
        self.new: list = []
        self.memo: dict[int, object] = {}
        self.missing: list[str] = []

    def _get(self, kind, y):
        x = self.back[kind].get(y)
        if x is None:
            self.missing.append(f"{kind} {y}")
        return y if x is None else x

    def variable(self, y):
        return y if y < FIRMWARE_VARIABLES else self._get("variable", y)

    def atom(self, operand, category):
        if category == OBJECT:
            return (self.object(operand), OBJECT)
        if category == SCREEN:
            return (self._get("screen", operand), SCREEN)
        if category == SWITCH:
            return (self._get("table", operand >> 8) << 8 | self.variable(operand & 0xFF),
                    SWITCH)
        if category in TESTS:
            return (operand & 0xFF00 | self.variable(operand & 0xFF), category)
        if category >= 0x80:
            return (operand, 0x80 | self.variable(category & 0x7F))
        if category == SYSTEM and operand >> 8 == SELECT_CONTEXT and operand & 0xFF < 0xF0:
            return (SELECT_CONTEXT << 8 | self._get("context", operand & 0xFF), SYSTEM)
        if category == SYSTEM and operand >> 8 in TIMER_CALLS:
            timer = self.timers.get(operand & 0xFF)
            if timer is None:
                self.missing.append(f"timer {operand & 0xFF}")
                timer = operand & 0xFF
            return (operand & 0xFF00 | timer, SYSTEM)
        return (operand, category)

    def atoms(self, atoms):
        return [self.atom(*atom) for atom in atoms]

    def object(self, y):
        """Object y as the platform's object, or a new one."""
        if y in self.memo:
            return self.memo[y]
        x = self.back["object"].get(y)
        if x is not None and self.places is not None and ("object", x) not in self.places:
            self.memo[y] = x                # replaced in turn, if it differs (graft)
            return x
        self.memo[y] = x if x is not None else -1           # a cycle meets its pairing
        atoms = self.atoms(self.pairing.b.objects[y])
        if x is not None and same(atoms, self.pairing.a.objects[x]):
            self.memo[y] = x
        else:
            self.memo[y] = {"new": len(self.new)}
            self.new.append(atoms)
        return self.memo[y]


def same(a, b) -> bool:
    return [tuple(atom) for atom in a] == [tuple(atom) for atom in b]


def graft(platform: View, household: View, places: set) -> dict:
    """The parts of ``platform`` to replace with ``household``'s, with the new parts they
    reference; ``places`` are the parts a household changes, `(kind, index)`, never
    taken. Raises when a replaced part references what the platform does not pair."""
    pairing = Pairing(platform, household)
    tr = Translation(pairing, places)
    objects, contexts = {}, {}
    for x, y in sorted(pairing.map["object"].items()):
        if ("object", x) in places:
            continue
        atoms = tr.atoms(household.objects[y])
        if not same(atoms, platform.objects[x]):
            objects[x] = atoms
    for x, y in sorted(pairing.map["context"].items()):
        if ("context", x) in places:
            continue
        rows = [(key, *tr.atom(operand, category))
                for key, operand, category in household.contexts[y]]
        if sorted(map(tuple, rows)) != sorted(map(tuple, platform.contexts[x])):
            contexts[x] = rows
    timers = {}
    for x, y in sorted(pairing.timers.items()):
        flags, seconds, operand, category = household.timers[y]
        atom = tr.atom(operand, category)
        if (flags, seconds, *atom) != tuple(platform.timers[x]):
            timers[x] = [flags, seconds, *atom]
    if tr.missing:
        raise ValueError("the household's parts reference what the platform does not "
                         f"have: {sorted(set(tr.missing))[:10]}")
    unpaired = [index for index in range(len(platform.timers)) if index not in pairing.timers]
    if unpaired:
        raise ValueError(f"the platform's timers {unpaired} have no household counterpart")
    return {"objects": objects, "contexts": contexts, "timers": timers, "new": tr.new}


def changed_places(platform: View, household: View) -> set:
    """The platform's parts a household holds otherwise, references translated: measured
    over a model's households with an empty configuration of their own, these are the
    places a household changes."""
    pairing = Pairing(platform, household)
    tr = Translation(pairing)
    out = set()
    for x, y in pairing.map["object"].items():
        if not same(tr.atoms(household.objects[y]), platform.objects[x]):
            out.add(("object", x))
    for x, y in pairing.map["context"].items():
        rows = [(key, *tr.atom(operand, category))
                for key, operand, category in household.contexts[y]]
        if sorted(rows) != sorted(platform.contexts[x]):
            out.add(("context", x))
    return out
