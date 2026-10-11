"""The carried screens - Options' Date and Time and Screen Sensitivity (options.py) and the
idle layer (idle.py) - linked into the image being laid out.

Those models name what they use symbolically: an object of their own, a mode, a timer, a
switch table, a variable, the hub's screens. This translates each name into the number
the image gives it, and reserves the carried modes with their programs.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from . import drawing, structures
from .scaffold import CHARGE_CONTEXTS, platform_object
from .structures import object_body

# Carried screens' blocks and the Options screen's own label blocks, in the space model
# blocks use (firmware_screens.MODEL_BLOCK).
CARRIED_BLOCK = 0xF80000


class Carried:
    """``model`` is idle.attach's: the carried modes, objects, blocks, groups, timers and
    variables. ``engine_size`` is how many section-14 records come before the carried
    variables (the terminator included), ``system`` the firmware's screens, and ``exits``
    the ordinals of the hub screens a carried screen leaves to."""

    def __init__(self, model: dict, *, engine_size: int, system: dict, first_platform: int,
                 first_mode: int, exits: dict[str, int]):
        self.model = model
        self.engine_size = engine_size
        self.system = system
        self.first_platform = first_platform
        self.first_mode = first_mode
        self.exits = exits
        self.object_base = None

    def variable(self, value) -> int:
        return value if isinstance(value, int) else self.engine_size - 1 + value["variable"]

    def operand(self, value) -> int:
        """A carried model's operand as this image numbers it."""
        if isinstance(value, int):
            return value
        if "object" in value:
            return self.object_base + value["object"]
        if "mode" in value:
            return self.first_mode + value["mode"]
        if "platform" in value:
            return platform_object(value["platform"], self.first_platform)
        if "exit" in value:
            return self.exits[value["exit"]]
        if "timer" in value:
            return (value["band"] << 8) | (len(self.system.get("timers", ())) + value["timer"])
        if "group" in value:
            return (value["group"] << 8) | self.variable(value["variable"])
        if "test" in value:
            return (value["test"] << 8) | self.variable(value["variable"])
        if "register" in value:
            return (value["register"] << 8) | self.variable(value["variable"])
        if "charge" in value:
            return (value["band"] << 8) | CHARGE_CONTEXTS[value["charge"]]
        raise ValueError(f"a carried screen names {value!r}")

    def category(self, value) -> int:
        return value if isinstance(value, int) else 0x80 | self.variable(value["write"])

    def atoms(self, atoms) -> list[tuple[int, int]]:
        return [(self.operand(value), self.category(category)) for value, category in atoms]

    def rows(self, rows):
        return [(key, self.operand(operand), self.category(category))
                for key, operand, category in rows]

    def block(self, block, picture) -> list[dict]:
        """A carried drawing block with its targets, selectors and pictures resolved."""
        out = []
        for item in block:
            item = dict(item)
            if item["opcode"] in ("call", "jump"):
                item["target"] = CARRIED_BLOCK + item["target"]["block"]
            elif item["opcode"] == "switch":
                item["selector"] = self.variable(item["selector"])
                item["cases"] = [(value, CARRIED_BLOCK + at) for value, at in item["cases"]]
                item["ranges"] = [(low, high, CARRIED_BLOCK + at)
                                  for low, high, at in item["ranges"]]
            elif item["opcode"] == "bitmap":
                item["target"] = picture(item["target"]["picture"])
            elif item["opcode"] == "atom":
                item["operand"] = self.operand(item["operand"])
                item["category"] = self.category(item["category"])
            out.append(item)
        return out

    def number_objects(self, layout):
        """Number the carried objects now, so the firmware's own screens - whose enter,
        leave and redraw handlers the idle layer's flags depend on - can name them."""
        self.object_base = layout.reserve_objects(len(self.model["objects"]))
        for index, atoms in enumerate(self.model["objects"]):
            layout.objects[self.object_base + index] = object_body(self.atoms(atoms))

    @property
    def idle(self) -> dict | None:
        return self.model.get("idle")

    def firmware_handlers(self) -> dict[tuple[int, int], tuple[int, int]]:
        """The idle layer's handlers for the firmware's screens, ``(ordinal, tag)``."""
        out = {}
        for key, (operand, category) in (self.idle or {}).get("handlers", {}).items():
            ordinal, tag = key.split(":")
            out[(int(ordinal), int(tag, 16))] = (self.operand(operand), self.category(category))
        return out

    def screen_handlers(self, kind, owned_handlers):
        """The platform's enter, leave and redraw for a screen of ``kind``, its enter and
        leave also lighting and darkening the zones such a screen lights."""
        screens = self.idle["screens"] if self.idle else {}
        if kind not in screens:
            return owned_handlers
        return [(tag, self.operand(screens[kind][f"{tag:#04x}"][0]),
                 self.category(screens[kind][f"{tag:#04x}"][1]))
                if f"{tag:#04x}" in screens[kind] else (tag, operand, category)
                for tag, operand, category in owned_handlers]

    def place_modes(self, layout):
        """The carried screens' modes, at the ordinals after Options, their templates
        named by position and so kept as they are."""
        templates_base = layout.keep_templates(self.model["templates"])
        for mode in self.model["modes"]:
            pages, blocks = [], []
            for page in mode["pages"]:
                size = len(drawing.encode_program(
                    self.block(self.model["blocks"][page["program"]], lambda _r: 0)))
                pages.append((templates_base + page["template"], self.rows(page["rows"]),
                              [size]))
                blocks.append(page["program"])
            placed = layout.mode(structures.key_register(self.rows(mode["header"])),
                                 mode["flag"], pages)
            for block, [at] in zip(blocks, placed):
                layout.carried_fixed.setdefault(CARRIED_BLOCK + block, at)
                if layout.carried_fixed[CARRIED_BLOCK + block] != at:
                    layout.extra_copies.append((CARRIED_BLOCK + block, at))
