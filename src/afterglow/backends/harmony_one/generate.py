"""Build a Harmony One configuration from nothing.

Every other writer in this backend starts from an image somebody's remote produced and
changes part of it. This one starts from an empty buffer: it lays out a header, every
section, and the bodies they point at, and the only thing it reads from an existing
configuration is nothing at all. Artwork comes from the scaffold, which is a directory of
files rather than a donor.

What a generated image is obliged to contain was settled by the configuration a Harmony
One ships with, `Region_3.EZHex` in firmware 54.2.5: a virgin remote has no devices, no
status overlays, an empty name chain, and zero entries in sections 13 and 15, so the two
sections nobody has decoded never have to be understood.

Layout is chosen so that every section's range covers its own table and nothing else.
`gspm.section_ranges` ends a section where the next one begins, so bodies are placed
first, then the nineteen tables contiguously in ascending order, then the checksum and
`PTYY`. Section 9 is the exception that proves the order matters: it is not a table but
the key registers themselves, back to back between 7 and 10, as in every donor. A section
pointer must also be unique, which is why no section may be empty.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from . import activity_index, authoring, drawing, font_index, gspm, records, scaffold
from . import idle as idle_machine
from . import activities as activity_plan
from . import catalogue, keys, platform_text


HEADER_SIZE = 0x68
# The factory image counts 2 buttons where every household one counts 55.
HOUSEHOLD_BUTTONS = 55

# What follows the count is mode 0's own list - mode 0 is the "battery level is low"
# screen - and the firmware reads it at that fixed place. Every Harmony One user
# configuration carries these same 55 entries: an event code, then instruction 0x7F
# calling the object numbered by the entry's position. 52 are key presses; the entries
# at 7, 9 and 46 (codes 06, 07 and 2D) are mode events, not keys. Writing the count
# without the entries had the firmware read whatever came next as this list.
MODE_ZERO_EVENTS = bytes.fromhex(
    "89 88 8b 8a 8d 8c 8f 06 8e 07 81 83 82 85 84 87 86 98 99 9a 9b 9c 9d 9e 9f 90 91 92 "
    "93 94 95 96 97 ab a8 af ae ad ac a3 a2 a1 a0 a7 a6 a5 2d a4 b2 b3 b0 b1 b7 b4 b5")
# So objects 0 to 54 are mode 0's handlers, and the image's own objects start after
# them. In the user configurations they do nothing - three empty atoms, a deliberate
# swallow - except event 2D, which draws the status overlays as the platform screens do.
MODE_ZERO_REDRAW = 46

# second, minute, hour, day, month, year - the day and month counting from zero.
DEFAULT_STAMP = (0, 0, 0, 0, 0, 2024)

# Section 14 opens with the same clock section 3 holds: seven properties whose limits are
# 59, 59, 23, 30, 6, 11 and a year, and whose initial values are the timestamp's fields.
# All five images measured agree on all seven, so a generated image keeps them in step.
CLOCK_LIMITS = (59, 59, 23, 30, 6, 11)


def _wrap(operand, category: int = 0x1F) -> dict:
    """A transition taken whenever a property wraps back to zero, from any state."""
    return {"flags": 0, "from": activity_index.ANY_STATE, "to": 0,
            "operand": operand, "category": category}


# The clock carries: a minute wrapping runs `0xf202`, an hour wrapping runs an object of
# `0xf203` and `0xf204`, a day `0xf205` and a month `0xf206`. The factory image and both
# donors carry exactly these four, so they are the firmware's and not a configuration's.
# An operand given as atoms is an object the build places and replaces with its index.
CLOCK_CARRIES = {
    1: [_wrap(0xF202)],
    2: [_wrap({"atoms": [(0xF203, 0x1F), (0xF204, 0x1F)]}, 0x7F)],
    3: [_wrap(0xF205)],
    5: [_wrap(0xF206)],
}

# Section 14's properties 7 to 17, as `(initial, limit)`: identical in the factory image
# and both donors except property 14, which is (0, 1) in the factory image and (2, 4) in
# both donors. The donors' value is taken, since the platform screens are theirs too.
PLATFORM_RECORDS = ((0, 2), (0, 3), (5, 7), (0, 7), (0, 32), (0, 1), (1, 1), (2, 4),
                    (0, 3), (0, 1), (0, 3))


def clock_records(second: int, minute: int, hour: int, day: int, month: int,
                  year: int) -> list[dict]:
    """Section 14's first seven properties, holding the same time section 3 does."""
    weekday = authoring.stamp_weekday(day, month, year)
    values = (second, minute, hour, day, weekday, month)
    records = [
        {"initial": value, "limit": limit, "padding": 0,
         "transitions": [dict(row) for row in CLOCK_CARRIES.get(index, ())]}
        for index, (value, limit) in enumerate(zip(values, CLOCK_LIMITS))
    ]
    # The year's limit is one past the year it holds in every image measured.
    records.append({"initial": year - 2000, "limit": year - 2000 + 1,
                    "padding": 0, "transitions": []})
    return records


def engine_records(*stamp_fields) -> list[dict]:
    """The whole of section 14 a configuration without activities has.

    The clock, the platform's own properties, then the terminator - nineteen records,
    which is what the factory image holds. Property ids are positions, so a firmware
    reading a platform property by id reads past the table if any of them is missing.
    """
    records = clock_records(*stamp_fields)
    records += [{"initial": initial, "limit": limit, "padding": 0, "transitions": []}
                for initial, limit in PLATFORM_RECORDS]
    records.append({"initial": 0, "limit": activity_index.TERMINATOR_LIMIT,
                    "padding": 0, "transitions": []})
    return records


# Section 14's header, measured in the factory image and both donors: a count, one less
# than the count, a one, and one less than the count again, then a pointer per record.
def engine_index(records: list[int]) -> bytes:
    count = len(records)
    if count > 0xFFFF:
        raise ValueError("section 14 indexes at most 65535 engine records")
    trailing = max(0, count - 1)
    return (struct.pack("<HHHH", count, trailing, 1, trailing)
            + b"".join((gspm.BASE + offset).to_bytes(3, "little") for offset in records))


def name_chain(records: list[bytes] = ()) -> bytes:
    """Section 0. An empty chain declares zero, which is what the factory image writes."""
    body = b"".join(records)
    if not body:
        return b"\xed\xfe\x00\x00\x00\xef\xbe"
    return (b"\xed\xfe" + (3 + len(body) + 2).to_bytes(3, "little") + body + b"\xef\xbe")


def platform_table(entries: list[int], tail: bytes) -> bytes:
    """Section 15: a count of pointers, then the platform table section 16 indexes."""
    if len(entries) > 0xFF:
        raise ValueError("section 15 counts at most 255 entries")
    return (bytes([len(entries)])
            + b"".join((gspm.BASE + offset).to_bytes(3, "little") for offset in entries)
            + tail)


def platform_index(tail_offset: int) -> bytes:
    """Section 16: eleven pointers into section 15's tail, at the measured offsets."""
    return (bytes([len(scaffold.SECTION_16_OFFSETS)])
            + b"".join((gspm.BASE + tail_offset + offset).to_bytes(3, "little")
                       for offset in scaffold.SECTION_16_OFFSETS))


def counted_index(offsets: list[int], *, width: int, label: str) -> bytes:
    """A count of the given width, then one 24-bit pointer per entry."""
    limit = 0xFF if width == 1 else 0xFFFF
    if len(offsets) > limit:
        raise ValueError(f"{label} indexes at most {limit} entries")
    return (len(offsets).to_bytes(width, "little")
            + b"".join((gspm.BASE + offset).to_bytes(3, "little") for offset in offsets))


PLATFORM_TAIL = "platform/section15-tail.bin"
PLATFORM_TAIL_SIZE = 151


def platform_tail(directory=None) -> bytes:
    """The 151 bytes section 16 indexes, which are measured rather than derivable."""
    from ... import paths
    directory = paths.scaffolds("harmony-one") if directory is None else directory
    tail = (Path(directory) / PLATFORM_TAIL).read_bytes()
    if len(tail) != PLATFORM_TAIL_SIZE:
        raise ValueError(
            f"{PLATFORM_TAIL} is {len(tail)} bytes; section 15's table is "
            f"{PLATFORM_TAIL_SIZE}")
    return tail


def _place(out: bytearray, body: bytes) -> int:
    """Put a structure where a sequential native read stays inside one 64 KiB window."""
    offset = authoring._align_window(out, len(body))
    out += body
    return offset


def _place_picture(out: bytearray, body: bytes) -> int:
    """Pictures do not obey the window: a 176x220 backdrop is 77,445 bytes on its own."""
    offset = len(out)
    out += body
    return offset


def skeleton(*, buttons: int = HOUSEHOLD_BUTTONS, stamp: bytes | None = None,
             tail: bytes | None = None, fonts=(), pictures=(), engine=(),
             devices=(), templates=None, label_font: int | None = None,
             softkey_fonts: dict | None = None, options: dict | None = None,
             system: dict | None = None, words=None, activities: dict | None = None) -> bytes:
    """Emit the smallest configuration this backend can build without reading one.

    No devices, no activities and no status overlays, which is what the factory image
    has. Sections whose contents nobody has decoded are emitted with a count of zero,
    which is also what it has.
    """
    tail = platform_tail() if tail is None else tail
    # Every word this image draws comes from the catalogue, in the project's language.
    words = catalogue.ENGLISH if words is None else words
    if system:
        # The firmware's screens name their words; they are drawn in this image's fonts
        # (platform_text.py), or left out of an image built without fonts.
        used = {item["font"] for block in system["blocks"] for item in block
                if item.get("opcode") == "label"}
        fonts_ok = bool(fonts) and all(font < len(fonts) for font in used)
        system = platform_text.render(system, labeller(list(fonts)) if fonts_ok else None,
                                      words)
    # Section 16 indexes fixed offsets into this table, the last at 134, so a table of
    # the wrong length would point past the end of section 15 rather than into it.
    if len(tail) != PLATFORM_TAIL_SIZE:
        raise ValueError(
            f"the platform table is {len(tail)} bytes; section 15's table is "
            f"{PLATFORM_TAIL_SIZE}")
    out = bytearray(HEADER_SIZE)
    out[0:4] = gspm.MAGIC
    struct.pack_into("<I", out, 8, gspm.HEADER_CONSTANT)
    out[gspm.BUTTON_MAP_OFFSET:gspm.BUTTON_MAP_OFFSET + 4] = gspm.BUTTON_MAP_MAGIC
    out[gspm.BUTTON_MAP_OFFSET + 4] = buttons
    if buttons == HOUSEHOLD_BUTTONS:
        out += mode_zero_list()

    # Objects are numbered before anything is placed, since key rows and handlers name
    # them by index, and their bodies are placed after the modes, as in every donor.
    object_bodies = []

    def _object(body):
        object_bodies.append(body)
        return len(object_bodies) - 1

    first_platform_object = HOUSEHOLD_BUTTONS if buttons == HOUSEHOLD_BUTTONS else 0
    if buttons == HOUSEHOLD_BUTTONS:
        mode_zero = _handlers(system["screens"][0]["header"], first_platform_object) \
            if system else {}
        for index in range(HOUSEHOLD_BUTTONS):
            _object(mode_zero_handler(index, mode_zero))
    # The firmware's screens queue objects of their own by index, so those go first,
    # followed by the object their OK buttons use to open the first screen a project
    # owns. Everything a project adds is numbered after them.
    platform_count = len(system["screens"]) if system else 0
    navigate = None
    if system:
        for atoms in system["objects"]:
            _object(object_body(
                [(_platform_object(value, first_platform_object), category)
                 for value, category in atoms]))
        navigate = _object(authoring.navigation_object(
            platform_count, authoring.IR_OBJECT_KIND_FALLBACK))
    owned_handlers = _owned_handlers(system, first_platform_object)

    label = label_font if label_font is not None else 0
    font = fonts[label] if fonts else None
    # The hub every Logitech configuration has, devices or not: the Activities screen is
    # the first one the image owns - what it boots into and what every OK opens - with
    # Options and Devices softkeys, and the device list behind Devices, empty or not.
    hub = system is not None and font is not None and softkey_fonts is not None
    home_ordinal = platform_count if hub else None
    # Options, and the screens carried behind it, come straight after Activities; the
    # idle machine - key lights, events, start-up - is built into the same namespace.
    carried = idle_machine.attach(options, system) if hub and options else None
    options_ordinal = platform_count + 1 if carried else None
    carried_first = platform_count + 2 if carried else None
    first_menu = (platform_count + (1 if hub else 0)
                  + (1 + len(carried["modes"]) if carried else 0))

    carried_fixed, extra_blocks = {}, {}
    carried_timers, carried_groups = [], []
    carried_object_base = None

    def _carried_variable(value):
        return value if isinstance(value, int) else len(engine) - 1 + value["variable"]

    def _carried_operand(value):
        """A carried model's operand as this image numbers it."""
        if isinstance(value, int):
            return value
        if "object" in value:
            return carried_object_base + value["object"]
        if "mode" in value:
            return carried_first + value["mode"]
        if "platform" in value:
            return _platform_object(value["platform"], first_platform_object)
        if "exit" in value:
            return {"options": options_ordinal, "home": home_ordinal,
                    "devices": first_menu}[value["exit"]]
        if "timer" in value:
            return (value["band"] << 8) | (len(system.get("timers", ())) + value["timer"])
        if "group" in value:
            return (value["group"] << 8) | _carried_variable(value["variable"])
        if "test" in value:
            return (value["test"] << 8) | _carried_variable(value["variable"])
        if "register" in value:
            return (value["register"] << 8) | _carried_variable(value["variable"])
        if "charge" in value:
            return (value["band"] << 8) | CHARGE_CONTEXTS[value["charge"]]
        raise ValueError(f"a carried screen names {value!r}")

    def _carried_category(value):
        return value if isinstance(value, int) else 0x80 | _carried_variable(value["write"])

    def _carried_rows(rows):
        return [(key, _carried_operand(operand), _carried_category(category))
                for key, operand, category in rows]

    def _carried_block(block, picture):
        out = []
        for item in block:
            item = dict(item)
            if item["opcode"] in ("call", "jump"):
                item["target"] = CARRIED_BLOCK + item["target"]["block"]
            elif item["opcode"] == "switch":
                item["selector"] = _carried_variable(item["selector"])
                item["cases"] = [(value, CARRIED_BLOCK + at) for value, at in item["cases"]]
                item["ranges"] = [(low, high, CARRIED_BLOCK + at)
                                  for low, high, at in item["ranges"]]
            elif item["opcode"] == "bitmap":
                item["target"] = picture(item["target"]["picture"])
            elif item["opcode"] == "atom":
                item["operand"] = _carried_operand(item["operand"])
                item["category"] = _carried_category(item["category"])
            out.append(item)
        return out

    # The carried model's objects are numbered now, so the firmware's own screens - whose
    # enter, leave and redraw handlers the idle layer's flags depend on - can name them.
    if carried:
        carried_object_base = len(object_bodies)
        object_bodies.extend([None] * len(carried["objects"]))
        for index, atoms in enumerate(carried["objects"]):
            object_bodies[carried_object_base + index] = object_body(
                [(_carried_operand(value), _carried_category(category))
                 for value, category in atoms])
    platform_handlers = {}
    if carried and "idle" in carried:
        for key, (operand, category) in carried["idle"]["handlers"].items():
            ordinal, tag = key.split(":")
            platform_handlers[(int(ordinal), int(tag, 16))] = (
                _carried_operand(operand), _carried_category(category))
        # mode 0's list calls its handlers through objects 0 to 54
        zero = {tag: operand for (ordinal, tag), (operand, category)
                in platform_handlers.items() if ordinal == 0 and category == OBJECT_ATOM}
        if zero and buttons == HOUSEHOLD_BUTTONS:
            for index in range(HOUSEHOLD_BUTTONS):
                object_bodies[index] = mode_zero_handler(index, {**mode_zero, **zero})

    for device in devices:
        # Each command gets the object naming it and the wrapper a key binds to, laid out
        # the way every donor lays them out: command object, then its wrapper, command by
        # command. `device_objects` is the measured builder for exactly that, and the kind
        # is the fallback a donor-less build uses - `0x0fca`, which every command binding
        # in the donors carries.
        bodies, wrappers = authoring.device_objects(
            device["index"], len(device["commands"]), len(object_bodies),
            authoring.IR_OBJECT_KIND_FALLBACK)
        for body in bodies:
            _object(body)
        for command, wrapper in zip(device["commands"], wrappers):
            command["wrapper_index"] = wrapper
            # the command object a wrapper calls, which is what a state change sends
            command["object_index"] = wrapper - 1

    # Each device's power and input as state variables, as every donor has them: a
    # transition sends what changing the state takes. They follow the platform's and
    # the Options screens' variables in section 14, before the terminator, and the
    # activity counter follows them.
    engine_records_base = list(engine)
    device_variables = []
    device_slots = []          # per device: the variable index of its power and input
    first_device_variable = (len(engine) - 1 + (len(carried["variables"]) if carried else 0)
                             if engine else None)
    if engine:
        for device in devices:
            records_ = device_state_records(device, _object)
            kinds = ["power"] * bool(device.get("power"))
            kinds += ["input"] * (len(records_) - len(kinds))
            slots = {}
            for kind, (name, record) in zip(kinds, records_):
                slots[kind] = first_device_variable + len(device_variables)
                device_variables.append((name, record))
            device_slots.append(slots)
    # Activities need the idle layer's contexts and somewhere to count them.
    acts = list((activities or {}).get("activities") or []) if (
        hub and carried and "idle" in carried and engine) else []
    state_variable = None
    if hub and carried and "idle" in carried and engine and activities is not None:
        # `CurrentActivityState`: each activity is a value, and the one past them is
        # nothing running, the value it starts at - section 0 names it, as the donors do.
        state_variable = first_device_variable + len(device_variables)
        device_variables.append((f"CurrentActivityState_0_{len(acts) + 1}", {
            "initial": len(acts), "limit": len(acts), "padding": 0, "transitions": []}))
    assistant_variable = None
    if acts:
        # Whether the Remote Assistant asks after each start: on until Options turns it off.
        assistant_variable = first_device_variable + len(device_variables)
        device_variables.append(("RemoteAssistant_2", {
            "initial": 1, "limit": 1, "padding": 0, "transitions": []}))

    # The object every owned page's fragment queues to draw status overlays 3 and 0.
    status_object = (_object(object_body([(3, DRAW_OVERLAY), (0, DRAW_OVERLAY)]))
                     if system and len(system["overlays"]) >= 4 else None)

    def _navigation(ordinal):
        """Number a go-to-screen object and return its section-11 index."""
        return _object(authoring.navigation_object(
            ordinal, authoring.IR_OBJECT_KIND_FALLBACK))

    # A page per six commands, when there is a font to label them with and a frame to
    # draw them on. Section 6 has no zero-screen form, so a configuration with nothing
    # to show still gets one screen whose slot draws a program that ends immediately.
    # The donors carry a frame per button position, not one frame reused, so the
    # scaffold names them that way and a page draws the frame belonging to each slot.
    roles = set(pictures) if isinstance(pictures, dict) else set()
    # Only the pictures some program draws are placed, as Logitech's builder places them:
    # every donor's pictures are all reached, and an unreachable one is bytes the remote
    # stores and never shows. Each program records the roles it names as it is measured.
    drawn = set()

    def _draws(role):
        drawn.add(role)
        return 0
    frame_roles = [f"button-frame/{index}" for index in range(len(BUTTON_POSITIONS))]
    # Pictures may be redrawn at another size, but not moved: labels are fitted to the
    # frames as drawn, and a frame too big for its place is refused.
    frame_width = FRAME_WIDTH
    if all(role in roles for role in frame_roles):
        sizes = {picture_size(pictures[role]) for role in frame_roles}
        frame_width = max(width for width, _height in sizes)
        room = (BUTTON_POSITIONS[1][0] - BUTTON_POSITIONS[0][0],
                BUTTON_POSITIONS[2][1] - BUTTON_POSITIONS[0][1])
        for width, height in sizes:
            if width > room[0] or height > room[1]:
                raise ValueError(f"a button frame is {width}x{height}; a button has "
                                 f"{room[0]}x{room[1]} before it reaches the next one")
    row_label_room = MENU_LABEL_MAX
    if "row-frame" in roles:
        width, height = picture_size(pictures["row-frame"])
        if MENU_FRAME_XY[0][0] + width > SCREEN_WIDTH or \
                height > MENU_FRAME_XY[1][1] - MENU_FRAME_XY[0][1]:
            raise ValueError(f"the menu row frame is {width}x{height}, which does not fit "
                             "its row")
        row_label_room = min(MENU_LABEL_MAX,
                             MENU_FRAME_XY[0][0] + width - MENU_LABEL_XY[0][0])
    pages = []
    if all(role in roles for role in frame_roles) and frame_roles and font is not None:
        geometry = touch_templates() if templates is None else templates
        for device in devices:
            # a held code an activity sends has a record but no button
            commands = [command for command in device["commands"]
                        if not command.get("hidden")]
            for first in range(0, len(commands), len(BUTTON_POSITIONS)):
                pages.append((device, commands[first:first + len(BUTTON_POSITIONS)],
                              geometry))

    # Every mode is laid out the way every donor lays one out, contiguously:
    #
    #     [handler list] then, per page, [fragment] [page program] [7-byte page record]
    #     then [entry: flag, list, page count, pages]
    #
    # where the page program opens by calling the fragment just after the list. Readers
    # find a page's program at the end of its mode's list, so nothing else may sit there.
    # The programs draw pictures that are placed later, and a program's size does not
    # depend on its addresses, so each mode is reserved whole now and its programs are
    # written once everything they point at has an address.
    trailers, template_zones = [], []
    pending_slots, pending_programs, fixed_blocks, fragments = [], [], {}, set()
    # Section 9 is every slot's key register laid back to back, between sections 7 and 10,
    # and nothing else: walking it register by register ends exactly at section 10 in
    # every donor. So a page record is reserved with its register pointer left open, and
    # the registers are written out together when the tables are.

    def _mode(header, flag, mode_pages):
        """Reserve one mode. ``header`` is its list's bytes, or the address of a list
        placed elsewhere; each page is ``(template, rows, program sizes)``, and its record
        draws the last program. Returns each page's program addresses."""
        own = header if isinstance(header, (bytes, bytearray)) else b""
        size = len(own) + sum(sum(sizes) + 7 for _t, _r, sizes in mode_pages)
        size += len(authoring.screen_trailer(flag, 0, [0] * len(mode_pages)))
        start = _place(out, bytes(size))
        out[start:start + len(own)] = own
        list_at = start if own else header
        cursor = start + len(own)
        addresses, slots = [], []
        for template, rows, sizes in mode_pages:
            placed = []
            for program_size in sizes:
                placed.append(cursor)
                cursor += program_size
            pending_slots.append((cursor, template, list(rows), placed[-1]))
            slots.append(cursor)
            cursor += 7
            addresses.append(placed)
        trailer = authoring.screen_trailer(flag, list_at, slots)
        out[cursor:cursor + len(trailer)] = trailer
        trailers.append(cursor)
        return addresses

    def _template(zones):
        # pages with the same zones share a template, as the donors' do: section 19
        # indexes at most 255
        zones = list(zones)
        if zones in template_zones[fixed_templates:]:
            return fixed_templates + template_zones[fixed_templates:].index(zones)
        template_zones.append(zones)
        return len(template_zones) - 1

    # The firmware's own screens come first, at the ordinals and template indices it looks
    # for. Their OK buttons open the first screen the project owns; the object bindings of
    # their physical keys lead into the donor's help flow and are not carried. Each one's
    # page program opens by calling a fragment no other program calls, which is the
    # fragment its mode carries after its list.
    fixed_templates = 0
    if system:
        # the firmware's screens name their templates by index, so these are all kept
        for zones in system["templates"]:
            template_zones.append(list(zones))
        fixed_templates = len(template_zones)
        measured = system_blocks(system, {role: 0 for role in roles}, first_platform_object)
        drawn.update(item["target"]["picture"] for block in system["blocks"] for item in block
                     if isinstance(item.get("target"), dict) and "picture" in item["target"])
        callers = {}
        for at, block in measured.items():
            for item in block:
                targets = [item.get("target")] if item["opcode"] in ("call", "jump") else []
                if item["opcode"] == "switch":
                    targets = [t for _v, t in item["cases"]] + [t for *_r, t in item["ranges"]]
                for target in targets:
                    callers.setdefault(target, set()).add(at)
        shared = {MODEL_BLOCK + index for index in system["overlays"]}
        for screen in system["screens"]:
            shared.update(MODEL_BLOCK + slot["program"] for slot in screen["slots"])
        for ordinal, screen in enumerate(system["screens"]):
            if ordinal == 0 and buttons == HOUSEHOLD_BUTTONS:
                # Mode 0's list is the one the firmware reads after LWJL.
                header = gspm.BUTTON_MAP_OFFSET + len(gspm.BUTTON_MAP_MAGIC)
            else:
                rows = [(key, _platform_object(operand, first_platform_object), category)
                        for key, operand, category in screen["header"]
                        if (ordinal, key) not in platform_handlers]
                rows += [(tag, *platform_handlers[(ordinal, tag)])
                         for tag in (ENTER, LEAVE, REDRAW)
                         if (ordinal, tag) in platform_handlers]
                header = authoring.key_register(rows)
            mode_pages, owned = [], []
            for slot in screen["slots"]:
                program = MODEL_BLOCK + slot["program"]
                first = measured[program][0]
                blocks = [program]
                if (first["opcode"] == "call" and first["target"] not in shared
                        and callers.get(first["target"]) == {program}):
                    blocks.insert(0, first["target"])
                    shared.add(first["target"])
                    fragments.add(first["target"])
                rows = [(key["key"], navigate, OBJECT_ATOM) for key in slot["keys"]]
                # A fragment ends at its return, and every donor follows that with an end.
                sizes = [len(drawing.encode_program(measured[at])) + (at in fragments)
                         for at in blocks]
                mode_pages.append((slot["template"], rows, sizes))
                owned.append(blocks)
            for blocks, placed in zip(owned, _mode(header, screen["flag"], mode_pages)):
                fixed_blocks.update(zip(blocks, placed))

    # A screen's ordinal is its position in section 6, not its emission order, so every
    # page's ordinal can be assigned before any page is written and a navigation can name
    # a page that has not been emitted yet. The menu comes first among the owned screens,
    # then the command pages, device by device.
    device_pages, device_geometry = {}, {}
    for device, chunk, geometry in pages:
        device_pages.setdefault(device["index"], []).append(chunk)
        device_geometry[device["index"]] = geometry
    menu_devices = list(device_pages)
    menu_page_count = (len(menu_devices) + MENU_ROWS_PER_PAGE - 1) // MENU_ROWS_PER_PAGE
    if hub:
        menu_page_count = max(1, menu_page_count)
    elif system is None:
        menu_page_count = 0
    menu_ordinals = list(range(first_menu, first_menu + menu_page_count))
    cursor = first_menu + menu_page_count
    command_ordinals = {}
    for device_index in menu_devices:
        command_ordinals[device_index] = list(
            range(cursor, cursor + len(device_pages[device_index])))
        cursor += len(device_pages[device_index])
    menu_of_device = {
        device_index: menu_ordinals[position // MENU_ROWS_PER_PAGE]
        for position, device_index in enumerate(menu_devices)
    } if menu_page_count else {}
    # Then the activities' screens, in the order they are emitted: the Activities menu's
    # pages after its first (which is the home screen), then each activity's starting
    # screen, its pages of buttons and its Help screen, then Help with nothing running.
    activity_menu_pages = max(1, -(-len(acts) // MENU_ROWS_PER_PAGE))
    activity_menu_ordinals = ([home_ordinal]
                              + list(range(cursor, cursor + activity_menu_pages - 1)))
    cursor += activity_menu_pages - 1
    # Each activity: starting, its favourites' pages, its buttons' pages, Help, the
    # Remote Assistant's question and then one per device and input it asks about.
    act_screens = []

    def _take(count):
        nonlocal cursor
        cursor += count
        return list(range(cursor - count, cursor))
    for act in acts:
        favourite_pages = -(-len(act["favourites"]) // len(BUTTON_POSITIONS))
        command_pages = -(-len(act["buttons"]) // len(BUTTON_POSITIONS))
        if not favourite_pages:
            command_pages = max(1, command_pages)
        asked = ([("power", index) for index in act["on"] if "power" in device_slots[index]]
                 + [("input", index, value) for index, value in act["inputs"]
                    if "input" in device_slots[index]])
        screens = {"start": _take(1)[0], "favourites": _take(favourite_pages),
                   "pages": _take(command_pages), "help": _take(1)[0],
                   "prompt": _take(1)[0], "questions": _take(len(asked)), "asked": asked}
        screens["home"] = (screens["favourites"] or screens["pages"])[0]
        act_screens.append(screens)
    off_help_ordinal = _take(1)[0] if acts else None
    # Options' second page, with the Remote Assistant's switch.
    options_more_ordinal = _take(1)[0] if acts else None
    tutorial_ordinals = _take(len(TUTORIAL)) if acts else []
    # The idle layer's contexts are 1 and 2, then its charge contexts; each activity's
    # follows, then Off's.
    activity_context = CHARGE_CONTEXTS["low"] + 1
    off_context = activity_context + len(acts)

    def _screen_handlers(kind):
        """The platform's enter, leave and redraw for a screen of ``kind``, its enter and
        leave also lighting and darkening the zones such a screen lights."""
        screens = carried["idle"]["screens"] if carried and "idle" in carried else {}
        if kind not in screens:
            return owned_handlers
        return [(tag, _carried_operand(screens[kind][f"{tag:#04x}"][0]),
                 _carried_category(screens[kind][f"{tag:#04x}"][1]))
                if f"{tag:#04x}" in screens[kind] else (tag, operand, category)
                for tag, operand, category in owned_handlers]

    def _owned_mode(rows, zones, build, kind=None, title=None, page=None, keys=(),
                    on_enter=None):
        """Reserve a mode this image owns: the platform's handlers, then a fragment
        drawing the backdrop, then the page program, which calls it and draws the rest.
        ``build(picture, prologue)`` returns the page program's instructions, and
        ``kind`` names which keypad zones the screen lights (idle.SCREEN_ZONES) and the
        fonts its ``title`` is drawn in. ``page`` is `(index, total)` for one page of a
        screen that has several, which are numbered as the donors number theirs.
        ``keys`` are rows for the physical keys, bound in the mode's own list, and
        ``on_enter`` is `(before, after)`, instructions run either side of the
        platform's own enter handler when the screen is entered."""
        backdrop = "backdrop" in roles
        title_font, counter_font = TITLE_FONTS.get(kind, (None, None))
        titled = (title is not None and title_font is not None and fonts is not None
                  and max(title_font, counter_font) < len(fonts))
        numbered = titled and page is not None and page[1] > 1

        def heading():
            [glyphs] = fit_label(title, fonts[title_font], TITLE_ROOM, lines=1)
            return [{"opcode": "attribute", "value": title_font},
                    {"opcode": "inline_text", "x": TITLE_XY[0], "y": TITLE_XY[1],
                     "glyphs": glyphs.hex()}]

        def counter_text(text, x, right=False):
            [glyphs] = fit_label(text, fonts[counter_font], SCREEN_WIDTH, lines=1)
            widths, _codes = _measure(fonts[counter_font])
            if right:
                x = max(0, x - sum(widths[code] for code in glyphs))
            return {"opcode": "inline_text", "x": x, "y": PAGE_COUNTER_Y,
                    "glyphs": glyphs.hex()}

        def fragment(picture, _prologue):
            # The donors' prologue: the title, the backdrop, the status bar - an atom
            # queues `(2, 0x73)`, overlay 2, and another the object drawing overlays 3
            # and 0, without which the clock and battery waited for the refresh timer -
            # then a paged screen's total, and the title again over everything.
            status = [] if status_object is None else [
                {"opcode": "atom", "operand": 2, "category": DRAW_OVERLAY},
                {"opcode": "atom", "operand": status_object, "category": OBJECT_ATOM}]
            total = []
            if numbered:
                widths, _codes = _measure(fonts[counter_font])
                [digits] = fit_label(str(page[1]), fonts[counter_font], SCREEN_WIDTH, 1)
                after = PAGE_TOTAL_XY[0] + sum(widths[code] for code in digits) + PAGES_GAP
                total = [{"opcode": "attribute", "value": counter_font},
                         counter_text(str(page[1]), PAGE_TOTAL_XY[0]),
                         counter_text(words.plural("pages", page[1]), after)]
            return ((heading() if titled else [])
                    + [{"opcode": "bitmap", "x": 0, "y": 0, "target": picture("backdrop")}]
                    + status[:1] + total + status[1:] + (heading() if titled else [])
                    + [{"opcode": "return"}, {"opcode": "end"}])

        page_build = build
        if numbered:
            def page_build(picture, prologue):
                # each page ends with its own number, right-aligned to the slash
                program = build(picture, prologue)
                return program[:-1] + [
                    {"opcode": "attribute", "value": counter_font},
                    counter_text(str(page[0] + 1), PAGE_SLASH_XY[0], right=True),
                    counter_text("/", PAGE_SLASH_XY[0])] + program[-1:]

        builds = ([fragment] if backdrop else []) + [page_build]
        template = zones if isinstance(zones, int) else _template(zones)
        # A program's size does not depend on its addresses, so it is measured with every
        # address standing at zero.
        sizes = [len(drawing.encode_program(item(_draws, 0 if backdrop else None)))
                 for item in builds]
        handlers = _screen_handlers(kind)
        if on_enter is not None:
            before, after = on_enter
            handlers = [(tag, _atoms_object(list(before) + [(operand, category)]
                                            + list(after)), OBJECT_ATOM)
                        if tag == ENTER else (tag, operand, category)
                        for tag, operand, category in handlers]
        [placed] = _mode(authoring.key_register(handlers + list(keys)), 0,
                         [(template, rows, sizes)])
        prologue = placed[0] if backdrop else None
        for at, item in zip(placed, builds):
            pending_programs.append((at, item, prologue))

    def _softkeys(program, keys):
        """End a page program with its softkey labels, each in its own font."""
        labels = []
        for name in keys:
            xy = SOFTKEYS[name]
            text = words(f"softkey.{name}")
            attribute = softkey_fonts[name]
            labels += softkey_label(text, fonts[attribute], attribute, xy)
        return program[:-1] + labels + [{"opcode": "end"}]

    def _message(text):
        """A line in the label font, centred on the screen: what an empty list shows."""
        widths, _codes = _measure(font)
        out = [{"opcode": "attribute", "value": label}]
        lines = fit_label(text, font, EMPTY_MESSAGE_WIDTH)
        for glyphs, y in zip(lines, _line_ys(EMPTY_MESSAGE_Y, len(lines), MENU_LINE_OFFSETS)):
            width = sum(widths[code] for code in glyphs)
            out.append({"opcode": "inline_text", "x": (SCREEN_WIDTH - width) // 2,
                        "y": y, "glyphs": glyphs.hex()})
        return out

    def _carry_options():
        """Options, and the Date and Time and Screen Sensitivity screens behind it."""
        for item in carried["timers"]:
            carried_timers.append(item)
        carried_groups.extend(carried["groups"])
        for block in carried["blocks"]:
            for item in block:
                if item["opcode"] == "bitmap":
                    drawn.add(item["target"]["picture"])
        drawn.update(carried["row_frames"])

        # The Options screen: the working entries on the rows upstairs draws them on,
        # labelled in its row font, a switch's label read off its own flag. With
        # activities it has Logitech's two pages: the Remote Assistant, the Tutorial and
        # Date and Time, then Screen Sounds and Screen Sensitivity.
        sounds = carried["sounds"]["switch"]
        sounds_row = ("switch", _carried_variable(sounds["variable"]),
                      {0: words("options.sounds-off"), 1: words("options.sounds-on")},
                      _object(object_body([(_carried_operand(sounds), 0x72)])))
        date_row = ("open", words("options.date-and-time"),
                    _navigation(carried_first + carried["entries"]["date-and-time"]))
        sensitivity_row = ("open", words("options.screen-sensitivity"),
                           _navigation(carried_first
                                       + carried["entries"]["screen-sensitivity"]))
        if options_more_ordinal is None:
            options_pages.append([date_row, sounds_row, sensitivity_row])
        else:
            redraw = {"opcode": "atom", "operand": options_ordinal, "category": ENTER_MODE}
            toggle = _act_group([
                (value, _act_block([{"opcode": "atom", "operand": 1 - value,
                                     "category": 0x80 | assistant_variable}, redraw,
                                    {"opcode": "end"}])) for value in (0, 1)])
            assistant_row = ("switch", assistant_variable,
                             {0: words("options.assistant-on"),
                              1: words("options.assistant-off")},
                             _object(object_body([(authoring.IR_OBJECT_KIND_FALLBACK, 0x75),
                                                  ((toggle << 8) | assistant_variable,
                                                   0x72)])))
            tutorial_row = ("open", words("options.tutorial"),
                            _navigation(tutorial_ordinals[0]))
            options_pages.extend([[assistant_row, tutorial_row, date_row],
                                  [sounds_row, sensitivity_row]])
        _options_page(0)

        templates_base = len(template_zones)
        for zones in carried["templates"]:      # named by position: kept as they are
            template_zones.append(list(zones))
        for index, mode in enumerate(carried["modes"]):
            pages, blocks = [], []
            for page in mode["pages"]:
                size = len(drawing.encode_program(
                    _carried_block(carried["blocks"][page["program"]], lambda _r: 0)))
                pages.append((templates_base + page["template"], _carried_rows(page["rows"]),
                              [size]))
                blocks.append(page["program"])
            placed = _mode(authoring.key_register(_carried_rows(mode["header"])),
                           mode["flag"], pages)
            for block, [at] in zip(blocks, placed):
                carried_fixed.setdefault(CARRIED_BLOCK + block, at)
                if carried_fixed[CARRIED_BLOCK + block] != at:
                    extra_copies.append((CARRIED_BLOCK + block, at))

    extra_copies = []
    activity_groups, activity_blocks = [], []

    def _act_block(block):
        """A drawing block a switch runs, placed with the carried screens' blocks."""
        at = ACTIVITY_BLOCK + len(activity_blocks)
        activity_blocks.append(at)
        extra_blocks[at] = block
        return at

    def _act_group(cases, ranges=()):
        """A section-15 switch table, numbered after the carried screens' tables."""
        activity_groups.append({"lead": 2, "cases": list(cases), "ranges": list(ranges)})
        return len(carried["groups"]) + len(activity_groups) - 1

    def _atoms_object(atoms):
        """An object running ``atoms``; one holds 255, so a longer list is split into
        objects run one after another."""
        atoms = list(atoms)
        if len(atoms) <= 0xFF:
            return _object(object_body(atoms))
        parts = [_atoms_object(atoms[at:at + 0xFF]) for at in range(0, len(atoms), 0xFF)]
        return _atoms_object([(part, OBJECT_ATOM) for part in parts])

    command_objects = {(device["index"], command["command_id"]): command
                       for device in devices for command in device["commands"]}

    def _step_atoms(steps):
        """A plan's steps (activities.py) as instructions: a send runs the command's
        object, a wait holds that device's next send, an input writes its variable."""
        out = []
        for step in steps:
            if step[0] == "send":
                out.append((command_objects[(step[1], step[2])]["object_index"],
                            OBJECT_ATOM))
            elif step[0] == "wait":
                out += _waits(step[1], step[2])
            elif step[0] == "input" and "input" in device_slots[step[1]]:
                out.append((step[2], 0x80 | device_slots[step[1]]["input"]))
        return out

    def _key_target(steps):
        """What a key bound to ``steps`` runs: one send is the command's own object,
        as a device page binds it; anything else an object of its own."""
        if len(steps) == 1 and steps[0][0] == "send":
            return command_objects[(steps[0][1], steps[0][2])]["object_index"]
        return _atoms_object(_step_atoms(steps))

    def _power_writes(indices, value):
        return [(value, 0x80 | device_slots[index]["power"]) for index in indices
                if "power" in device_slots[index]]

    def _input_writes(inputs):
        return [(value, 0x80 | device_slots[index]["input"]) for index, value in inputs
                if "input" in device_slots[index]]

    def _direct_power(indices, on, toggles=False):
        """Help's sends: each device's own power command, straight, for the devices
        that have one for each way - a toggle sent again would undo what it fixes. With
        ``toggles``, a toggle too: the Remote Assistant has been told the device is off."""
        out = []
        for index in indices:
            power = devices[index].get("power")
            if not power or (power["on"] == power["off"] and not toggles):
                continue
            command = power["on"] if on else power["off"]
            out.append((command_objects[(index, command)]["object_index"], OBJECT_ATOM))
            if on:
                out += _waits(index, power["delay_ms"])
        return out

    # Back to what is running: an activity's first page, or the Activities menu.
    current_group = resume_group = None
    if state_variable is not None:
        current_group = _act_group(
            [(value, _act_block([{"opcode": "atom", "operand": screens["home"],
                                  "category": ENTER_MODE}, {"opcode": "end"}]))
             for value, screens in enumerate(act_screens)]
            + [(len(acts), _act_block([{"opcode": "atom", "operand": home_ordinal,
                                        "category": ENTER_MODE}, {"opcode": "end"}]))])
        # From the Activities menu, its key goes back to a running activity only.
        resume_group = _act_group(
            [(value, _act_block([{"opcode": "atom", "operand": screens["home"],
                                  "category": ENTER_MODE}, {"opcode": "end"}]))
             for value, screens in enumerate(act_screens)]) if acts else None

    def _back_to_current():
        return _object(object_body([(authoring.IR_OBJECT_KIND_FALLBACK, 0x75),
                                    ((current_group << 8) | state_variable, 0x72)]))

    current_labels = {}

    def _softkeys_with_current(program, others):
        """Softkeys whose left one reads "Current Activity" while an activity runs and
        "Activities" when none does: a switch on the counter, drawn last so each case
        can end the program."""
        program = _softkeys(program, others)[:-1]
        attribute = softkey_fonts["activities"]
        # Made once: a page program is built again after the blocks are laid out, and a
        # block made then would never be given an address.
        blocks = current_labels
        for name in ("activities", "current-activity"):
            if name not in blocks:
                blocks[name] = _act_block(
                    softkey_label(words(f"softkey.{name}"), fonts[attribute], attribute,
                                  SOFTKEYS["activities"]) + [{"opcode": "end"}])
        return program + [{"opcode": "switch", "selector": state_variable,
                           "cases": [(len(acts), blocks["activities"])],
                           "ranges": ([(0, len(acts) - 1, blocks["current-activity"])]
                                      if acts else [])},
                          {"opcode": "end"}]

    options_pages = []

    def _options_page(page_index):
        """One page of Options: up to three rows on its row frames, each opening a
        screen or flipping a switch whose label is read off its variable - drawn last,
        since each case ends the program. The side strips turn the pages."""
        entries = options_pages[page_index]
        total = len(options_pages)
        ordinals = [options_ordinal, options_more_ordinal][:total]
        rows = [(MENU_ROW_KEYS[row], entry[-1], OBJECT_ATOM)
                for row, entry in enumerate(entries)]
        rows.append((MENU_ACTIVITIES_KEY, _navigation(home_ordinal), OBJECT_ATOM))
        if total > 1:
            other = _navigation(ordinals[(page_index + 1) % total])
            rows += [(SIDE_PREV_KEY, other, OBJECT_ATOM), (SIDE_NEXT_KEY, other, OBJECT_ATOM)]
        row_font = fonts[OPTIONS_FONT]
        widths, _codes = _measure(row_font)

        def centred(text, row):
            [glyphs] = fit_label(text, row_font, OPTIONS_LABEL_ROOM, lines=1)
            width = sum(widths[code] for code in glyphs)
            return {"opcode": "inline_text",
                    "x": MENU_FRAME_XY[row][0] + (OPTIONS_FRAME_WIDTH - width) // 2,
                    "y": MENU_LABEL_XY[row][1], "glyphs": glyphs.hex()}
        switch = None
        for row, entry in enumerate(entries):
            if entry[0] == "switch":
                switch = {"opcode": "switch", "selector": entry[1], "ranges": [],
                          "cases": [(value, _act_block([
                              {"opcode": "attribute", "value": OPTIONS_FONT},
                              centred(text, row), {"opcode": "end"}]))
                              for value, text in sorted(entry[2].items())]}

        def program(picture, prologue):
            out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            for row, _entry in enumerate(entries):
                out.append({"opcode": "bitmap", "x": MENU_FRAME_XY[row][0],
                            "y": MENU_FRAME_XY[row][1],
                            "target": picture(carried["row_frames"][row])})
            out.append({"opcode": "attribute", "value": OPTIONS_FONT})
            out += [centred(entry[1], row) for row, entry in enumerate(entries)
                    if entry[0] == "open"]
            out = _softkeys(out + [{"opcode": "end"}], ["activities"])[:-1]
            return out + ([switch] if switch else []) + [{"opcode": "end"}]
        _owned_mode(rows, menu_template(), program, "options", words("options.title"),
                    (page_index, total) if total > 1 else None)

    def _tutorial():
        """The Tutorial, in its own words: a page per thing to learn, each moved on by
        the key it teaches - bound in the page's own list, so pressing Help or Off here
        teaches rather than does - the left arrow back, Exit back to what is running."""
        exit_row = (PAGE_DEVICES_KEY, _back_to_current(), OBJECT_ATOM)
        zones = [zone for zone in menu_template() if zone["tag"] in (0x2E, 0x2F, 0x32)]
        zones.append(dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F))
        first = acts[0]
        row_frame = "activity/row-frame" if "activity/row-frame" in roles else "row-frame"
        widths, _codes = _measure(fonts[HELP_FONT])

        def paragraphs(text):
            out, y = [{"opcode": "attribute", "value": HELP_FONT}], TUTORIAL_TOP
            for paragraph in text.split("\n"):
                for glyphs in fit_label(paragraph, fonts[HELP_FONT], EMPTY_MESSAGE_WIDTH,
                                        TUTORIAL_LINES):
                    width = sum(widths[code] for code in glyphs)
                    out.append({"opcode": "inline_text", "x": (SCREEN_WIDTH - width) // 2,
                                "y": y, "glyphs": glyphs.hex()})
                    y += LINE_SPACING
                y += LINE_SPACING // 2
            return out

        for number, ((key, advance), ordinal) in enumerate(zip(TUTORIAL, tutorial_ordinals)):
            following = tutorial_ordinals[number + 1] if number + 1 < len(TUTORIAL) else None
            onward = _navigation(following) if following is not None else None
            text = (words(key, activity=first["label"]) if key == "tutorial.activities"
                    else words(key))
            rows, mode_keys = [exit_row], []
            if number:
                rows.append((SIDE_PREV_KEY, _navigation(tutorial_ordinals[number - 1]),
                             OBJECT_ATOM))
            if advance == "next":
                rows.append((SIDE_NEXT_KEY, onward, OBJECT_ATOM))
            elif advance == "touch":
                rows.append((MENU_ROW_KEYS[2], onward, OBJECT_ATOM))
            elif advance in ("activities", "help", "off"):
                scan = {"activities": keys.ACTIVITIES, "help": keys.HELP, "off": keys.OFF}
                mode_keys.append((keys.code(scan[advance]), onward, OBJECT_ATOM))
            # the keys the flow owns do nothing else while the Tutorial is shown
            mode_keys += [(keys.code(scan), 0, 0) for scan in (keys.ACTIVITIES, keys.HELP,
                                                                keys.OFF)
                          if keys.code(scan) not in {row[0] for row in mode_keys}]

            def program(picture, prologue, text=text, advance=advance):
                out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
                if advance == "touch":
                    # the first activity's own row, to touch
                    out += menu_page([first["label"]], picture(row_frame),
                                     [first.get("icon") and picture(first["icon"])], font,
                                     attribute=label, label_room=row_label_room,
                                     rows=(2,))[:-1]
                out += paragraphs(text)
                return _softkeys(out + [{"opcode": "end"}], ["exit"])
            _owned_mode(rows, zones, program, "tutorial", words("tutorial.title"),
                        (number, len(TUTORIAL)), keys=mode_keys)

    def _activity_menu_page(page_index):
        """One page of the Activities menu: up to three activities, each row starting
        its activity by selecting its context, on the activities' own row frame."""
        total = len(activity_menu_ordinals)
        on_page = list(range(page_index * MENU_ROWS_PER_PAGE,
                             min(len(acts), (page_index + 1) * MENU_ROWS_PER_PAGE)))
        rows = [(MENU_ROW_KEYS[slot], _object(object_body([
                    (authoring.IR_OBJECT_KIND_FALLBACK, 0x75),
                    (0xFF00 | (activity_context + index), 0x1F)])), OBJECT_ATOM)
                for slot, index in enumerate(on_page)]
        rows.append((MENU_OPTIONS_KEY, _navigation(options_ordinal), OBJECT_ATOM))
        rows.append((MENU_DEVICES_KEY, _navigation(menu_ordinals[0]), OBJECT_ATOM))
        if total > 1:
            rows.append((SIDE_PREV_KEY, _navigation(
                activity_menu_ordinals[(page_index - 1) % total]), OBJECT_ATOM))
            rows.append((SIDE_NEXT_KEY, _navigation(
                activity_menu_ordinals[(page_index + 1) % total]), OBJECT_ATOM))
        zones = menu_template() + [dict(SOFTKEY_RIGHT_ZONE, tag=MENU_DEVICES_KEY & 0x7F)]
        frame_role = "activity/row-frame" if "activity/row-frame" in roles else "row-frame"
        labels = [acts[index]["label"] for index in on_page]
        icons = [acts[index].get("icon") for index in on_page]

        def program(picture, prologue, labels=labels, icons=icons):
            built = menu_page(labels, picture(frame_role),
                              [role and picture(role) for role in icons], font,
                              prologue=prologue, attribute=label,
                              label_room=row_label_room)
            return _softkeys(built, ["options", "devices"])
        # On the menu the Activities key goes back to what is running.
        menu_keys = [(keys.code(keys.ACTIVITIES), (resume_group << 8) | state_variable,
                      0x72)]
        _owned_mode(rows, zones, program, "activities", words("hub.activities-title"),
                    (page_index, total), keys=menu_keys)

    if hub and acts:
        _activity_menu_page(0)
    elif hub:
        # Activities: none yet, so the list says so, and Devices opens the device list.
        home_rows = [(SOFTKEY_RIGHT_KEY, _navigation(menu_ordinals[0]), OBJECT_ATOM)]

        home_zones = [dict(SOFTKEY_RIGHT_ZONE, tag=HOME_DEVICES_TAG)]
        home_keys = ["devices"]
        if carried:
            home_rows.append((0x80 | HOME_OPTIONS_TAG, _navigation(options_ordinal),
                              OBJECT_ATOM))
            home_zones.append(dict(SOFTKEY_LEFT_ZONE, tag=HOME_OPTIONS_TAG))
            home_keys.insert(0, "options")

        def home_program(_picture, prologue):
            program = [] if prologue is None else [{"opcode": "call", "target": prologue}]
            program += _message(words("hub.no-activities")) + [{"opcode": "end"}]
            return _softkeys(program, home_keys)
        _owned_mode(home_rows, home_zones, home_program, "activities",
                    words("hub.activities-title"))

    if carried:
        _carry_options()

    # The device menu: a page of up to three rows, and where there are more devices the
    # side strips move between menu pages in a cycle.
    if menu_page_count:
        icon_roles = sorted(role for role in roles if role.startswith("row-icon/"))
        for page_index, menu_ordinal in enumerate(menu_ordinals):
            on_page = menu_devices[
                page_index * MENU_ROWS_PER_PAGE:(page_index + 1) * MENU_ROWS_PER_PAGE]
            rows = []
            for slot_index, device_index in enumerate(on_page):
                target = command_ordinals[device_index][0]
                # A row is a navigation to the device's first page.
                row = _object(authoring.navigation_object(
                    target, authoring.IR_OBJECT_KIND_FALLBACK))
                rows.append((MENU_ROW_KEYS[slot_index], row, OBJECT_ATOM))
            if menu_page_count > 1:
                rows.append((SIDE_PREV_KEY, _navigation(
                    menu_ordinals[(page_index - 1) % menu_page_count]), OBJECT_ATOM))
                rows.append((SIDE_NEXT_KEY, _navigation(
                    menu_ordinals[(page_index + 1) % menu_page_count]), OBJECT_ATOM))
            if hub:
                # The menu template's own bottom-left zone is the Activities softkey,
                # which goes back to a running activity when there is one.
                rows.append((MENU_ACTIVITIES_KEY, _back_to_current() if acts
                             else _navigation(home_ordinal), OBJECT_ATOM))
            labels = [devices[index]["label"] for index in on_page]
            # A configured device carries the icon composed for its type; a bare
            # skeleton takes the scaffold's row icons in turn.
            icons = [
                devices[device_index].get("icon")
                or (icon_roles[index % len(icon_roles)] if icon_roles else None)
                for index, device_index in enumerate(on_page)
            ]

            def menu_program(picture, prologue, labels=labels, icons=icons):
                # A page with no rows names no frame, so an empty list places none.
                frame = picture("row-frame") if labels else 0
                program = menu_page(
                    labels, frame, [role and picture(role) for role in icons], font,
                    prologue=prologue, attribute=label, label_room=row_label_room)
                if not labels:
                    program[-1:] = _message(words("hub.no-devices")) + [{"opcode": "end"}]
                if hub and acts:
                    return _softkeys_with_current(program, [])
                return _softkeys(program, ["activities"]) if hub else program
            _owned_mode(rows, menu_template(), menu_program, "devices",
                        words("hub.devices-title"),
                        (page_index, menu_page_count))

    # Command pages, device by device. A device with more than six commands spans several
    # pages; the side strips move between them, and the last one leads back to the menu
    # (or, when there is no menu, wraps to the device's first page).
    for device_index in menu_devices:
        chunks = device_pages[device_index]
        ordinals = command_ordinals[device_index]
        geometry = device_geometry[device_index]
        home = menu_of_device.get(device_index, ordinals[0])
        for page_index, chunk in enumerate(chunks):
            rows = [
                (FIRST_BUTTON_KEY + index, command["wrapper_index"], OBJECT_ATOM)
                for index, command in enumerate(chunk)
            ]
            if len(chunks) > 1:
                previous = ordinals[page_index - 1] if page_index else home
                following = (ordinals[page_index + 1]
                             if page_index + 1 < len(chunks) else home)
                rows.append((SIDE_PREV_KEY, _navigation(previous), OBJECT_ATOM))
                rows.append((SIDE_NEXT_KEY, _navigation(following), OBJECT_ATOM))
            elif menu_of_device:
                rows.append((SIDE_NEXT_KEY, _navigation(home), OBJECT_ATOM))
            # The donors carry geometry for 1, 2, 3, 5 and 6 button pages. A page of a size
            # they never drew takes the smallest template that still covers its buttons, so
            # no zone is left pointing at a button the page does not draw.
            fitting = sorted(size for size in geometry if size >= len(chunk))
            if not fitting:
                raise ValueError(
                    f"no touch template covers a page of {len(chunk)} buttons; "
                    f"the scaffold has {sorted(geometry)}")
            zones = [
                zone for zone in geometry[fitting[0]]
                if (zone["tag"] | 0x80) < FIRST_BUTTON_KEY + len(chunk)
                or (zone["tag"] | 0x80) >= FIRST_BUTTON_KEY + len(BUTTON_POSITIONS)
            ]
            # The softkeys upstairs' device pages carry: Activities bottom left, Devices
            # bottom right, in the screen's bottom strip. Whatever a donor template had in
            # the strip gives way to them.
            if hub:
                zones = [zone for zone in zones if zone["y"] != SOFTKEY_LEFT_ZONE["y"]]
                zones += [dict(SOFTKEY_LEFT_ZONE, tag=PAGE_ACTIVITIES_KEY & 0x7F),
                          dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F)]
                rows.append((PAGE_ACTIVITIES_KEY, _back_to_current() if acts
                             else _navigation(home_ordinal), OBJECT_ATOM))
                rows.append((PAGE_DEVICES_KEY, _navigation(home), OBJECT_ATOM))
            labels = [command["name"] for command in chunk]
            device_keys = device_key_rows(devices[device_index]["commands"])

            def command_program(picture, prologue, labels=labels):
                program = button_page(
                    labels, [picture(role) for role in frame_roles[:len(labels)]], font,
                    prologue=prologue, attribute=label, frame_width=frame_width)
                if hub and acts:
                    return _softkeys_with_current(program, ["devices"])
                return _softkeys(program, ["activities", "devices"]) if hub else program
            _owned_mode(rows, zones, command_program,
                        "commands-paged" if len(chunks) > 1 else "commands",
                        devices[device_index]["label"], (page_index, len(chunks)),
                        keys=device_keys)
    # The activities' screens, in the ordinals given them above.
    activity_rows = {}
    if hub and acts:
        for page_index in range(1, len(activity_menu_ordinals)):
            _activity_menu_page(page_index)
        frames = [f"activity/button-frame/{index}" for index in range(len(BUTTON_POSITIONS))]
        if not all(role in roles for role in frames):
            frames = frame_roles
        swallow = [(keys.code(scan), 0, 0) for scan in keys.SCANS.values()]
        geometry = touch_templates() if templates is None else templates

        def _lines(text, attribute, top, room=EMPTY_MESSAGE_WIDTH, lines=2):
            """``text`` centred on the screen in ``attribute``, its lines 12 apart from
            ``top`` down."""
            widths, _codes = _measure(fonts[attribute])
            out = [{"opcode": "attribute", "value": attribute}]
            for number, glyphs in enumerate(fit_label(text, fonts[attribute], room, lines)):
                width = sum(widths[code] for code in glyphs)
                out.append({"opcode": "inline_text", "x": (SCREEN_WIDTH - width) // 2,
                            "y": top + LINE_SPACING * number, "glyphs": glyphs.hex()})
            return out

        def _sending(picture):
            return ([{"opcode": "bitmap", "x": SENDING_XY[0], "y": SENDING_XY[1],
                      "target": picture("activity/sending")}]
                    if "activity/sending" in roles else [])

        def _help_screen(title, before):
            """Help: the activity's name, what it is doing, and the remote's waves, while
            ``before`` re-sends what the activity needs."""
            def program(picture, prologue):
                out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
                out += _lines(words("activity.fixing"), HELP_FONT, HELP_TOP)
                out += [{"opcode": "bitmap", "x": HELP_SENDING_XY[0],
                         "y": HELP_SENDING_XY[1], "target": picture("activity/sending")}
                        ] if "activity/sending" in roles else []
                out += _lines(words("activity.keep-pointed"), HELP_FONT, HELP_KEEP_TOP)
                return out + [{"opcode": "end"}]
            _owned_mode([], [], program, "help", title, keys=swallow, on_enter=before)

        answer_zones = [zone for zone in geometry[len(BUTTON_POSITIONS)]
                        if (zone["tag"] | 0x80) in (FIRST_BUTTON_KEY + 4, FIRST_BUTTON_KEY + 5)]

        def _yes_no(title, question, yes, no, fix_object=False):
            """A question with Yes and No on the bottom row: Yes opens ``yes``, No runs
            ``no`` - a screen to open, or with ``fix_object`` an object to run."""
            rows = [(FIRST_BUTTON_KEY + 4, _navigation(yes), OBJECT_ATOM),
                    (FIRST_BUTTON_KEY + 5, no if fix_object else _navigation(no),
                     OBJECT_ATOM)]

            def program(picture, prologue):
                out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
                out += _lines(question, HELP_FONT, QUESTION_TOP, lines=3)
                widths, _codes = _measure(font)
                out.append({"opcode": "attribute", "value": label})
                for slot, text in ((4, words("assistant.yes")), (5, words("assistant.no"))):
                    left, top = BUTTON_POSITIONS[slot]
                    out.append({"opcode": "bitmap", "x": left, "y": top,
                                "target": picture(frames[slot])})
                    [glyphs] = fit_label(text, font, frame_width, lines=1)
                    width = sum(widths[code] for code in glyphs)
                    out.append({"opcode": "inline_text",
                                "x": (2 * left + frame_width - width) // 2,
                                "y": top + LABEL_BASELINE, "glyphs": glyphs.hex()})
                return out + [{"opcode": "end"}]
            _owned_mode(rows, answer_zones, program, "question", title)

        def _input_fix(index, value):
            """What answering No about an input sends: its own command again, or for
            inputs reached by stepping, one step."""
            inputs = devices[index]["inputs"]
            if "direct" in inputs:
                command = inputs["direct"][value]
                return [] if command is None else [
                    (command_objects[(index, command)]["object_index"], OBJECT_ATOM)]
            return [(command_objects[(index, inputs["next"])]["object_index"], OBJECT_ATOM)]

        for index, (act, screens) in enumerate(zip(acts, act_screens)):
            # Starting: its icon under the waves, "Starting ...", and every key held off
            # until the activity is running.
            def start_program(picture, prologue, act=act):
                out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
                out += _sending(picture)
                if act.get("start_icon"):
                    out.append({"opcode": "bitmap", "x": START_ICON_XY[0],
                                "y": START_ICON_XY[1], "target": picture(act["start_icon"])})
                out += _lines(words("activity.starting", activity=act["label"]),
                              START_FONT, START_TEXT_Y, room=SCREEN_WIDTH - 12, lines=1)
                out += _lines(words("activity.keep-pointed"), HELP_FONT, START_KEEP_TOP)
                return out + [{"opcode": "end"}]
            _owned_mode([], [], start_program, keys=swallow)

            # Its favourites, then its buttons, six a page; the side strips turn each set
            # of pages, the left softkey goes between the two, and Devices opens the
            # device list.
            def _pages(entries, ordinals, other, other_key, kind_name, frames_for):
                chunks = [entries[at:at + len(BUTTON_POSITIONS)]
                          for at in range(0, len(entries), len(BUTTON_POSITIONS))] or [[]]
                for page_index, chunk in enumerate(chunks):
                    rows = []
                    for slot, (_label, steps, _picture) in enumerate(chunk):
                        if len(steps) == 1 and steps[0][0] == "send":
                            target = command_objects[(steps[0][1], steps[0][2])][
                                "wrapper_index"]
                        else:
                            target = _atoms_object(
                                [(authoring.IR_OBJECT_KIND_FALLBACK, 0x75)]
                                + _step_atoms(steps))
                        rows.append((FIRST_BUTTON_KEY + slot, target, OBJECT_ATOM))
                    if len(chunks) > 1:
                        rows.append((SIDE_PREV_KEY, _navigation(ordinals[page_index - 1]),
                                     OBJECT_ATOM))
                        rows.append((SIDE_NEXT_KEY, _navigation(
                            ordinals[(page_index + 1) % len(ordinals)]), OBJECT_ATOM))
                    rows.append((PAGE_DEVICES_KEY, _navigation(menu_ordinals[0]),
                                 OBJECT_ATOM))
                    size = sorted(size for size in geometry if size >= max(1, len(chunk)))
                    if not size:
                        raise ValueError(f"no touch template covers a page of {len(chunk)} "
                                         f"buttons; the scaffold has {sorted(geometry)}")
                    zones = [zone for zone in geometry[size[0]]
                             if (zone["tag"] | 0x80) < FIRST_BUTTON_KEY + len(chunk)
                             or (zone["tag"] | 0x80) >= FIRST_BUTTON_KEY
                             + len(BUTTON_POSITIONS)]
                    zones = [zone for zone in zones if zone["y"] != SOFTKEY_LEFT_ZONE["y"]]
                    zones.append(dict(SOFTKEY_RIGHT_ZONE, tag=PAGE_DEVICES_KEY & 0x7F))
                    softkeys = ["devices"]
                    if other is not None:
                        zones.append(dict(SOFTKEY_LEFT_ZONE, tag=PAGE_ACTIVITIES_KEY & 0x7F))
                        rows.append((PAGE_ACTIVITIES_KEY, _navigation(other), OBJECT_ATOM))
                        softkeys.insert(0, other_key)
                    labels = [text if picture is None else None
                              for text, _steps, picture in chunk]
                    pictured = [picture for _text, _steps, picture in chunk]

                    def program(picture, prologue, labels=labels, pictured=pictured):
                        built = button_page(
                            labels, [picture(role or frames_for[slot])
                                     for slot, role in enumerate(pictured)], font,
                            prologue=prologue, attribute=label, frame_width=frame_width)
                        return _softkeys(built, softkeys)
                    kind = kind_name + ("-paged" if len(chunks) > 1 else "")
                    _owned_mode(rows, zones, program, kind, act["label"],
                                (page_index, len(chunks)))

            both = bool(screens["favourites"]) and bool(screens["pages"])
            kind_name = "activity-both" if both else "activity"
            if screens["favourites"]:
                _pages([(item["label"], item["steps"], item.get("picture"))
                        for item in act["favourites"]], screens["favourites"],
                       screens["pages"][0] if both else None, "commands", kind_name, frames)
            if screens["pages"]:
                _pages([(text, steps, None) for text, steps in act["buttons"]],
                       screens["pages"], screens["favourites"][0] if both else None,
                       "favourites", kind_name, frames)

            # Where a start ends: the Remote Assistant's question while it is on, else
            # the activity's own first page.
            after = _act_group([
                (0, _act_block([{"opcode": "atom", "operand": screens["home"],
                                 "category": ENTER_MODE}, {"opcode": "end"}])),
                (1, _act_block([{"opcode": "atom", "operand": screens["prompt"],
                                 "category": ENTER_MODE}, {"opcode": "end"}]))])
            finish = ((after << 8) | assistant_variable, 0x72)

            # Help: re-send the power and inputs the activity set, then the question.
            _help_screen(act["label"], (
                [(0xFFFB, idle_machine.MODE_STACK)] + _direct_power(act["on"], True)
                + _input_writes(act["inputs"]), [finish]))

            # The Remote Assistant: did everything turn on? No asks about each device
            # and input in turn, and fixes the one that is not.
            questions = screens["questions"]
            _yes_no(act["label"], words("assistant.question"), screens["home"],
                    questions[0] if questions else screens["help"])
            for number, (asked, ordinal) in enumerate(zip(screens["asked"], questions)):
                following = questions[number + 1] if number + 1 < len(questions) \
                    else screens["home"]
                device = devices[asked[1]]
                if asked[0] == "power":
                    text = words("assistant.is-on", device=device["label"])
                    fix = _direct_power([asked[1]], True, toggles=True)
                else:
                    value = asked[2]
                    text = words("assistant.input", device=device["label"],
                                 input=device["inputs"]["values"][value])
                    fix = _input_fix(asked[1], value)
                _yes_no(act["label"], text, following,
                        _atoms_object(fix + [(ordinal, ENTER_MODE)]), fix_object=True)

            context_rows = [
                (activity_index.ENTER, _atoms_object(
                    [(screens["start"], ENTER_MODE), (0xFFFB, idle_machine.MODE_STACK)]
                    + _power_writes(act["on"], 1) + _input_writes(act["inputs"])
                    + _power_writes(act["off"], 0) + [(index, 0x80 | state_variable)]
                    + _step_atoms(act["enter"]) + [finish])),
                (activity_index.LEAVE, _atoms_object(
                    [(0xFFFB, idle_machine.MODE_STACK)] + _step_atoms(act["leave"]))),
                # picked again while running: its inputs again, and back to its screen
                (activity_index.REFRESH, _atoms_object(
                    [(0xFFFB, idle_machine.MODE_STACK)] + _input_writes(act["inputs"])
                    + [(screens["home"], ENTER_MODE)])),
                (keys.code(keys.HELP), _navigation(screens["help"])),
            ] + [(code, _key_target(steps)) for code, steps in sorted(act["keys"].items())]
            activity_rows[activity_context + index] = context_rows
    if hub and state_variable is not None:
        # Off: nothing running, the Activities menu, and every device off behind it; its
        # Help turns them off again. It has no leave, as no donor's has.
        off = (activities or {}).get("all_off") or {"off": []}
        activity_rows[off_context] = [
            (activity_index.ENTER, _atoms_object(
                [(len(acts), 0x80 | state_variable), (0xFFFB, idle_machine.MODE_STACK),
                 (home_ordinal, ENTER_MODE)] + _power_writes(off["off"], 0))),
            (activity_index.REFRESH, _object(object_body([(home_ordinal, ENTER_MODE)]))),
        ]
        if acts:
            activity_rows[off_context].append(
                (keys.code(keys.HELP), _navigation(off_help_ordinal)))
            _help_screen(off.get("label") or words("activity.power-off"), (
                [(0xFFFB, idle_machine.MODE_STACK)] + _direct_power(off["off"], False),
                [(home_ordinal, ENTER_MODE)]))

    if options_more_ordinal is not None:
        _options_page(1)
        _tutorial()

    # Nothing the project owns to show still needs a screen at the first owned ordinal,
    # since section 6 has no zero-screen form and the OK buttons open that ordinal. It is
    # also the screen such an image boots into, and nothing clears the display, so it
    # draws the backdrop and says so: a screen that draws nothing leaves the boot logo up,
    # which looks exactly like a remote that never started.
    if len(trailers) == platform_count:
        if font is not None:
            def empty_program(_picture, prologue):
                out = [] if prologue is None else [{"opcode": "call", "target": prologue}]
                return out + _message(words("hub.no-devices")) + [{"opcode": "end"}]
            _owned_mode([], 0, empty_program)
        else:
            [[program]] = _mode(authoring.key_register(owned_handlers), 0,
                                [(0, [], [len(drawing.encode_program([{"opcode": "end"}]))])])
            pending_programs.append(
                (program, lambda _picture, _prologue: [{"opcode": "end"}], None))

    # The image starts on the first screen it owns, the one every OK button opens.
    startup = len(object_bodies)
    idle = None
    if carried and "idle" in carried:
        idle = {part: [(_carried_operand(operand), _carried_category(category))
                       for operand, category in steps]
                for part, steps in carried["idle"]["startup"].items()}
    for body in startup_objects(platform_count, USB_SCREEN if system else None, startup,
                                idle, off_context if state_variable is not None else None):
        _object(body)
    global_keys = []
    if hub and state_variable is not None:
        global_keys = [
            (keys.code(keys.ACTIVITIES), _object(object_body([(home_ordinal, ENTER_MODE)]))),
            (keys.code(keys.OFF), _object(object_body([(0xFF00 | off_context, 0x1F)]))),
        ]

    # Then the objects, in the order they were numbered, none longer than the donors'.
    object_bodies = bounded_objects(object_bodies)
    objects = [_place(out, body) for body in object_bodies]

    # A command record points at its own waveforms, so those are placed before it.
    device_records, names = [], []
    for device in devices:
        placed = []
        for command in device["commands"]:
            phases = {
                phase: _place(out, body)
                for phase, body in sorted(command["phases"].items())
            }
            record = _place(out, bytes(records.PREFIX_SIZE + 20))
            out[record:record + 25] = records.command_record(
                record, phases["press"], phases.get("hold"),
                command["carrier_period_ns"], command["carrier_half_period_ns"],
                release_offset=phases.get("release"))
            placed.append(record)
        device_records.append(placed)
    # Section 0 names the state variables, by index, under `Root` and `State`, as every
    # donor does; commands are not named.
    leaves = [(first_device_variable + index, name)
              for index, (name, _record) in enumerate(device_variables)]
    if carried:
        sounds = carried["sounds"]["switch"]["variable"]
        if isinstance(sounds, dict):
            leaves.append((len(engine_records_base) - 1 + sounds["variable"],
                           "ButtonSoundVolume_2"))
    if leaves:
        names = [name_record(0, "Root", leaf=False), name_record(1, "State", leaf=False)]
        names += [name_record(index, name) for index, name in sorted(leaves)]

    font_records = []
    for font_item in fonts:
        placed = {code: _place(out, body) for code, body in sorted(font_item["glyphs"].items())}
        font_records.append(_place(out, _font_record(font_item, placed)))
    picture_offsets = {role: _place_picture(out, pictures[role]) for role in sorted(drawn)}

    template_offsets = []
    for zones in template_zones:
        placed_zones = []
        for zone in zones:
            at = len(out)
            out += touch_zone(zone, at)
            placed_zones.append(at)
        template_offsets.append(_place(out, counted_index(
            placed_zones, width=1, label="a touch template")))

    # The firmware's blocks are laid out once the pictures they draw have addresses: the
    # fragments and page programs into the modes reserved for them, the rest together.
    overlay_offsets = []
    if system:
        if not isinstance(pictures, dict):
            raise ValueError("the firmware's screens draw pictures by name, so name them")
        model_blocks = system_blocks(system, picture_offsets, first_platform_object)
        if carried:
            for index, block in enumerate(carried["blocks"]):
                model_blocks[CARRIED_BLOCK + index] = _carried_block(
                    block, picture_offsets.__getitem__)
            model_blocks.update(extra_blocks)
        fixed = {**fixed_blocks, **carried_fixed}
        rest = {at: block for at, block in model_blocks.items() if at not in fixed}
        size = sum(len(drawing.encode_program(block)) for block in rest.values())
        body, mapping = drawing.lay_out(
            rest, authoring._align_window(out, min(size, authoring.ADDRESS_WINDOW)),
            mapping=fixed)
        out += body
        for at, offset in list(fixed.items()) + extra_copies:
            block = drawing.relocated(model_blocks[at], mapping)
            if at in fragments:
                block.append({"opcode": "end"})
            encoded = drawing.encode_program(block)
            out[offset:offset + len(encoded)] = encoded
        overlay_offsets = [mapping[MODEL_BLOCK + index] for index in system["overlays"]]
    else:
        mapping = {}
    for at, build, prologue in pending_programs:
        encoded = drawing.encode_program(drawing.relocated(
            build(picture_offsets.__getitem__, prologue), mapping))
        out[at:at + len(encoded)] = encoded
    # Section 15's switch tables, now their programs have addresses: a lead byte, the
    # exact cases `{u16 value, u24 program}`, then the ranges `{u16 low, u16 high, u24}`.
    groups = []
    for group in carried_groups:
        record = bytearray([group["lead"], len(group["cases"])])
        for value, at in group["cases"]:
            record += struct.pack("<H", value) + (gspm.BASE + mapping[CARRIED_BLOCK + at]
                                                  ).to_bytes(3, "little")
        record.append(len(group["ranges"]))
        for low, high, at in group["ranges"]:
            record += struct.pack("<HH", low, high) + (
                gspm.BASE + mapping[CARRIED_BLOCK + at]).to_bytes(3, "little")
        groups.append(_place(out, bytes(record)))
    for group in activity_groups:
        record = bytearray([group["lead"], len(group["cases"])])
        for value, at in group["cases"]:
            record += struct.pack("<H", value) + (gspm.BASE + mapping[at]).to_bytes(3, "little")
        record.append(len(group["ranges"]))
        for low, high, at in group["ranges"]:
            record += struct.pack("<HH", low, high) + (gspm.BASE + mapping[at]).to_bytes(
                3, "little")
        groups.append(_place(out, bytes(record)))
    # A context needs a row, and no context in any image binds key 0. The factory image
    # leaves keys it does not use as category 0 with operand 0, so the one row this
    # context holds is the factory's own unbound row rather than a binding to object 0.
    def _charge_rows(name):
        return [{"flags": 1, "key_code": int(code, 16), "operand": _carried_operand(operand),
                 "category": _carried_category(category)}
                for code, (operand, category) in carried["idle"]["charge"][name].items()]
    if idle is not None:
        context = _place(out, authoring.context_record({"form": "long",
                                                        "rows": _charge_rows("normal")}))
    else:
        context = _place(out, authoring.context_record({
            "form": "short",
            "rows": [{"flags": None, "key_code": 0x10, "operand": 0, "category": 0x00}],
        }))
    contexts = [context]
    if idle is not None:
        # The events the firmware posts - USB, charging, redraws, the side strips' paging -
        # and the key light every physical key runs and then passes on (flags bit 0 set,
        # so the search goes on down the stack), as upstairs' contexts 1 and 4 are.
        events = carried["idle"]["events"]
        event_rows = [
            {"flags": None, "key_code": int(code, 16),
             "operand": _carried_operand(operand), "category": _carried_category(category)}
            for code, (operand, category) in events.items()]
        # The keys the flow owns, under everything else on the stack: Activities opens
        # the Activities menu, Off selects Off's context.
        event_rows += [{"flags": None, "key_code": code, "operand": operand,
                        "category": OBJECT_ATOM} for code, operand in global_keys]
        contexts.append(_place(out, authoring.context_record({"form": "short",
                                                              "rows": event_rows})))
        operand, category = carried["idle"]["key_light"]
        rows = [{"flags": 1, "key_code": key, "operand": _carried_operand(operand),
                 "category": _carried_category(category)}
                for key in MODE_ZERO_EVENTS if key >= 0x80]
        # and the two codes below the keys that wake it too: picking it up, and 0x30
        rows += [{"flags": 1, "key_code": int(code, 16), "operand": _carried_operand(value),
                  "category": _carried_category(cat)}
                 for code, (value, cat) in carried["idle"].get("key_rows", {}).items()]
        contexts.append(_place(out, authoring.context_record({"form": "long", "rows": rows})))
        for name in ("usb", "low"):
            if len(contexts) != CHARGE_CONTEXTS[name]:
                raise ValueError(f"the {name} charge context is not where 0xFC finds it")
            contexts.append(_place(out, authoring.context_record({
                "form": "long", "rows": _charge_rows(name)})))
        # Each activity's context, then Off's: enter, leave and picked again, Help, and
        # the keys it routes.
        for index in sorted(activity_rows):
            if index != len(contexts):
                raise ValueError("an activity's context is not where its rows select it")
            contexts.append(_place(out, authoring.context_record({"form": "short", "rows": [
                {"flags": None, "key_code": code, "operand": operand,
                 "category": OBJECT_ATOM} for code, operand in activity_rows[index]]})))
    if not objects:
        objects.append(_place(out, b"\x00"))
    # Section 13 is the timer table. The platform screens start timer by index while they
    # are shown - the status bar's refresh - so the image carries the platform's timers;
    # an empty table left every one of those starts reading past its end.
    timers = [
        _place(out, timer_record(item["flags"], item["duration"],
                                 _platform_object(item["action"][0], first_platform_object),
                                 item["action"][1]))
        for item in (system or {}).get("timers", ())
    ] + [
        _place(out, timer_record(item["flags"], item["duration"],
                                 _carried_operand(item["action"][0]),
                                 _carried_category(item["action"][1])))
        for item in carried_timers
    ]
    # Section 14's records hold no addresses, so they are placed as they are given, once
    # any object a transition names by its atoms has been placed and given an index.
    engine_offsets = []
    if carried or device_variables:
        engine = list(engine[:-1]) + [
            {"initial": item["initial"], "limit": item["limit"], "padding": 0,
             "transitions": [
                 _transition(t["from"], t["to"], _carried_operand(t["action"][0]),
                             _carried_category(t["action"][1]))
                 | {"flags": t["flags"]} for t in item.get("transitions", ())]}
            for item in (carried or {}).get("variables", ())] + [
            record for _name, record in device_variables] + list(engine[-1:])
    for item in engine:
        rows = []
        for row in item["transitions"]:
            if isinstance(row["operand"], dict):
                objects.append(_place(out, object_body(row["operand"]["atoms"])))
                row = {**row, "operand": len(objects) - 1}
            rows.append(row)
        engine_offsets.append(_place(out, _engine_record({**item, "transitions": rows})))

    # Then the nineteen tables, contiguously and in ascending order, so that each
    # section's derived range covers its own table and nothing else.
    bodies = {}
    order = [
        (0, name_chain(names)),
        (1, scaffold.CONSTANT_SECTIONS[1]),
        (2, scaffold.CONSTANT_SECTIONS[2]),
        (3, authoring.stamp(*DEFAULT_STAMP) if stamp is None else stamp),
        (4, authoring.command_flat_index(device_records)),
        (5, None),
        (6, authoring.screen_index(trailers)),
        (7, counted_index(font_records, width=2, label="section 7")),
        (9, None),   # section 9 must hold every key register
        (10, counted_index(contexts, width=1, label="section 10")),
        (11, counted_index(objects, width=2, label="section 11")),
        (12, counted_index(overlay_offsets, width=2, label="section 12")),
        (13, counted_index(timers, width=1, label="section 13")),
        (14, engine_index(engine_offsets)),
        (15, None),
        (16, None),
        (17, scaffold.CONSTANT_SECTIONS[17]),
        (18, scaffold.CONSTANT_SECTIONS[18]),
        (19, counted_index(template_offsets, width=1, label="section 19")),
    ]
    placed = {}
    for index, body in order:
        if index == 9:
            # The start-up list, then every slot's register, in slot order, with nothing
            # between them. A pad zero is not an empty register: a leading zero selects
            # the wide form, so it would take the next byte as a count and put a walk of
            # the section out of step. The section is placed whole, so any window padding
            # comes before it.
            registers = [authoring.key_register(rows) for _slot, _t, rows, _p in pending_slots]
            lead = object_body([(startup, OBJECT_ATOM)])
            offset = _place(out, lead + b"".join(registers))
            register = offset + len(lead)
            for (slot, template, _rows, program), body in zip(pending_slots, registers):
                out[slot:slot + 7] = authoring.screen_slot(template, register, program)
                register += len(body)
        elif index == 5:
            # Section 5's sub-tables are section 4's device runs, so it points into
            # section 4 rather than holding copies of them.
            offset = len(out)
            run = placed[4] + authoring.COMMAND_INDEX_HEAD_SIZE
            subtables = []
            for commands in device_records:
                subtables.append(run)
                run += len(authoring.command_subtable(commands))
            out += (bytes([len(subtables)])
                    + b"".join((gspm.BASE + item).to_bytes(3, "little")
                               for item in subtables))
        elif index == 15:
            offset = len(out)
            out += platform_table(groups, tail)
            bodies["tail"] = offset + 1 + 3 * len(groups)
        elif index == 16:
            offset = len(out)
            out += platform_index(bodies["tail"])
        else:
            offset = len(out)
            out += body
        placed[index] = offset
    for index, offset in placed.items():
        struct.pack_into("<I", out, 0x0C + 4 * index, gspm.BASE + offset)

    out += b"\x00\x00PTYY"
    struct.pack_into("<I", out, 4, gspm.BASE + len(out) - 4)
    marker = len(out) - 4
    out[marker - 2:marker] = bytes(gspm.checksum(bytes(out), marker - 2))
    result = bytes(out)
    gspm.validate(result)
    return result


def _font_record(font: dict, placed: dict[int, int]) -> bytes:
    from . import compose
    return compose._font_record(font, placed)


def _engine_record(record: dict) -> bytes:
    from . import compose
    return compose._engine_record(record)


def font_from_scaffold(font: dict) -> dict:
    """Turn a loaded scaffold font into the shape a font record is written from.

    A scaffold font indexes its glyphs by the code the manifest gives them, and those run
    past the largest repertoire any donor uses, so the slot count is the highest code
    rather than a number read out of somebody's image.
    """
    glyphs = {code: item["body"] for code, item in font["glyphs"].items()}
    slots = max(glyphs, default=0)
    return {
        "height": font["height"],
        "slots": slots,
        # The wide header counts glyphs in a u16, which is the only one that reaches 95.
        "layout": font_index.WIDE_COUNT,
        "glyphs": glyphs,
        # A font record is written from bytes, but laying a label out needs each glyph's
        # width and the character it stands for. Both are carried so that a caller does
        # not have to hold the scaffold's own shape as well as this one.
        "metrics": {
            code: {"width": item["width"], "char": item["char"]}
            for code, item in font["glyphs"].items()
        },
    }


# "From any value", as upstairs' and Kāt's direct inputs all have it: it runs on every
# write, the same value included, which is how picking the running activity again
# re-sends its inputs. (Downstairs has one television with `0xFFFD` instead.)
TRANSITION_FROM_ANY = 0xFFFE
WAIT = 0x7C                    # (device << 8 | tenths): wait before that device's next send


def _waits(device_index: int, milliseconds: int) -> list[tuple[int, int]]:
    """A wait in tenths of a second, a hundred at a time, as the donors write long ones."""
    tenths = round(milliseconds / 100)
    out = []
    while tenths > 0:
        chunk = min(100, tenths)
        out.append(((device_index << 8) | chunk, WAIT))
        tenths -= chunk
    return out


def _transition(source: int, target: int, operand: int, category: int) -> dict:
    return {"flags": 0, "from": source, "to": target, "operand": operand,
            "category": category}


def device_state_records(device: dict, place_object) -> list[tuple[str, dict]]:
    """A device's `<Label>_Power_2` and `<Label>_Input_<n>` variables, with transitions.

    As downstairs and upstairs build them: power going 1 to 0 sends the off command, 0 to
    1 sends the on command and then waits the power-on delay; an input chosen directly
    is a transition from any value to it sending that input's command, and inputs reached
    by stepping get one transition per ordered pair, sending "next" as many times as it
    takes with the input delay after each. ``place_object`` numbers an object body.
    """
    label = device["label"].replace(" ", "_")
    index = device["index"]
    objects = {command["command_id"]: command["object_index"]
               for command in device["commands"]}
    out = []
    power = device.get("power")
    if power:
        on = [(objects[power["on"]], OBJECT_ATOM)] + _waits(index, power["delay_ms"])
        on_operand = (place_object(object_body(on)) if len(on) > 1
                      else objects[power["on"]])
        out.append((f"{label}_Power_2", {
            "initial": 0, "limit": 1, "padding": 0, "transitions": [
                _transition(1, 0, objects[power["off"]], OBJECT_ATOM),
                _transition(0, 1, on_operand, OBJECT_ATOM)]}))
    inputs = device.get("inputs")
    if inputs and len(inputs["values"]) > 0:
        count = len(inputs["values"])
        transitions = []
        if "direct" in inputs:
            for value, command_id in enumerate(inputs["direct"]):
                if command_id is None:
                    transitions.append(_transition(TRANSITION_FROM_ANY, value, 0, 0))
                else:
                    transitions.append(_transition(TRANSITION_FROM_ANY, value,
                                                   objects[command_id], OBJECT_ATOM))
        elif count > 1:
            step = [(objects[inputs["next"]], OBJECT_ATOM)] + _waits(index,
                                                                     inputs["delay_ms"])
            for source in range(count):
                for target in range(count):
                    if source == target:
                        continue
                    steps = (target - source) % count
                    body = step * steps
                    if len(body) > 0xFF:
                        raise ValueError(f"{device['label']!r} steps too far between inputs")
                    transitions.append(_transition(source, target,
                                                   place_object(object_body(body)),
                                                   OBJECT_ATOM))
        out.append((f"{label}_Input_{count}", {
            "initial": 0, "limit": count - 1, "padding": 0, "transitions": transitions}))
    return out


def device_key_rows(commands: list[dict]) -> list[tuple[int, int, int]]:
    """A device page's physical keys: each key one of its commands is bound to sends
    that command, without the click a touch makes, and every other command key does
    nothing - so device mode never falls through to the running activity's keys. The
    Activities, Off and Help keys are left to the flow above it."""
    bound = {}
    for command in commands:
        for name in command.get("keys") or ():
            code = keys.by_name(name)
            if code is not None:
                bound.setdefault(code, command["object_index"])
    return [(keys.by_name(name), bound.get(keys.by_name(name), 0),
             OBJECT_ATOM if keys.by_name(name) in bound else 0)
            for name in keys.COMMAND_KEYS]


def name_record(identifier: int, name: str, *, leaf: bool = True) -> bytes:
    """One section-0 named record: `a7`, a length, a type, an id, then the name."""
    encoded = name.encode("utf-8")
    if not encoded:
        raise ValueError("a named record needs a name")
    length = 4 + len(encoded)
    if length > 0xFFFF:
        raise ValueError("a named record is too long to declare its own length")
    return (b"\xa7" + length.to_bytes(2, "little")
            + (1 if leaf else 0).to_bytes(2, "little")
            + identifier.to_bytes(2, "little") + encoded)


def protocol_library(project: dict, library=None):
    """The protocols a project's devices are lowered with: whatever is installed, and
    each catalogue device's own definitions (`portable_protocol_definitions`), as the
    other remotes' builds read them."""
    from ... import ir_protocol

    inline = {}
    for device in project.get("devices") or []:
        for protocol_id, definition in (device.get("portable_protocol_definitions")
                                        or {}).items():
            if inline.get(protocol_id, definition) != definition:
                raise ValueError(f"two devices define protocol {protocol_id!r} differently")
            inline[protocol_id] = definition
    if inline:
        installed = (dict(library) if isinstance(library, dict)
                     else ir_protocol.catalog(library))
        for protocol_id, definition in inline.items():
            if installed.get(protocol_id, definition) != definition:
                raise ValueError(f"a device's protocol {protocol_id!r} conflicts with the "
                                 "installed definition")
        library = {**installed, **inline}
    return library


def held_commands(project: dict, devices: list[dict], planned: dict, *, library=None):
    """Give each held send in a plan a record of its own - the code held that long -
    and point the step at it. The records join their device's commands but no screen,
    and a step that names the same command held as long shares one."""
    from . import ir_lowering

    library = protocol_library(project, library)
    made = {}

    def resolve(steps):
        out = []
        for step in steps:
            if step[0] != "send" or len(step) < 4:
                out.append(step)
                continue
            _send, index, command_id, held_ms = step
            if (index, command_id, held_ms) not in made:
                device = devices[index]
                source = next(command for command in device["commands"]
                              if command["command_id"] == command_id)
                ordinal = len(device["commands"])
                if ordinal > 0xFF:
                    raise ValueError(f"device {device['label']!r} has no room for "
                                     f"{source['name']!r} held {held_ms} ms")
                signal = project["devices"][index]["signals"][source["name"]]
                lowered = ir_lowering.lower(signal, library=library, held_ms=held_ms)
                device["commands"].append({
                    "name": f"{source['name']} ({held_ms} ms)", "keys": [], "hidden": True,
                    "command_id": (index << 8) | ordinal,
                    "carrier_period_ns": lowered.carrier_period_ns,
                    "carrier_half_period_ns": lowered.carrier_half_period_ns,
                    "phases": {"press": lowered.press_waveform}})
                made[(index, command_id, held_ms)] = (index << 8) | ordinal
            out.append(("send", index, made[(index, command_id, held_ms)]))
        return out

    for activity in planned["activities"]:
        for key in ("enter", "leave"):
            activity[key] = resolve(activity[key])
        activity["keys"] = {code: resolve(steps) for code, steps in activity["keys"].items()}
        activity["buttons"] = [(label, resolve(steps)) for label, steps in activity["buttons"]]
        activity["favourites"] = [dict(item, steps=resolve(item["steps"]))
                                  for item in activity.get("favourites") or []]


def lowered_devices(project: dict, *, library=None) -> list[dict]:
    """Lower a project's devices into the pieces a command record is written from.

    A command's identifier carries its device in the high byte and its ordinal in the
    low one, which is how the whole format refers to commands, so a device may hold 255
    of them and no more.
    """
    from . import ir_lowering

    library = protocol_library(project, library)
    out = []
    for index, device in enumerate(project.get("devices") or []):
        label = device.get("label") or f"Device {index}"
        signals = device.get("signals") or {}
        if len(signals) > 0xFF:
            raise ValueError(
                f"device {label!r} has {len(signals)} commands; an ordinal is one byte")
        # The keys each command is bound to, from the project's own hard slots.
        slots = {}
        for entry in device.get("commands") or []:
            if len(entry) > 4 and entry[4]:
                slots[entry[0]] = entry[4] if isinstance(entry[4], list) else [entry[4]]
        commands = []
        for ordinal, (name, signal) in enumerate(sorted(signals.items())):
            lowered = ir_lowering.lower(signal, library=library)
            commands.append({
                "name": name,
                "keys": slots.get(name, []),
                "command_id": (index << 8) | ordinal,
                "carrier_period_ns": lowered.carrier_period_ns,
                "carrier_half_period_ns": lowered.carrier_half_period_ns,
                "phases": {
                    phase: body for phase, body in (
                        ("press", lowered.press_waveform),
                        ("hold", lowered.hold_waveform),
                        ("release", lowered.release_waveform),
                    ) if body
                },
            })
        ids = {command["name"]: command["command_id"] for command in commands}
        out.append({"index": index, "label": label, "commands": commands,
                    **device_states(device, ids)})
    return out


def device_states(device: dict, ids: dict[str, int]) -> dict:
    """A project device's power and inputs, with every command named by its id.

    The project's own fields, as the other remotes' builders read them: `power_on_cmd`
    and `power_off_cmd` or a toggle `power_cmd`, `power_delay` in milliseconds, `inputs`
    as `[name, command]` pairs, and `input_cycle` for inputs reached by stepping.
    """
    def command(name):
        if name is None:
            return None
        if name not in ids:
            raise ValueError(f"device {device.get('label')!r} names {name!r}, "
                             "which is not one of its commands")
        return ids[name]

    out = {}
    on, off = device.get("power_on_cmd"), device.get("power_off_cmd")
    toggle = device.get("power_cmd")
    if (on or toggle) and (off or toggle):
        out["power"] = {"on": command(on or toggle), "off": command(off or toggle),
                        "delay_ms": device.get("power_delay") or 0}
    inputs = [(entry[0], command(entry[1]) if len(entry) > 1 else None)
              for entry in device.get("inputs") or []]
    cycle = device.get("input_cycle") or {}
    if inputs:
        out["inputs"] = {"values": [name for name, _id in inputs],
                         "direct": [command_id for _name, command_id in inputs]}
    elif cycle.get("next") and cycle.get("values"):
        step = cycle["next"]
        step = step[0] if isinstance(step, list) else step
        out["inputs"] = {"values": list(cycle["values"]), "next": command(step),
                         "delay_ms": cycle.get("delay_ms") or 0}
    return out


TOUCH_TEMPLATES = "platform/touch-templates.json"

# Where the six command buttons sit, in reading order, and how far below a button's top
# its label's baseline falls. Both measured across every command page in the donors.
BUTTON_POSITIONS = ((6, 38), (89, 38), (6, 92), (89, 92), (6, 146), (89, 146))
LABEL_BASELINE = 20
# The first of the six touch keys; a page's buttons take consecutive codes from here.
FIRST_BUTTON_KEY = 0xB0
OBJECT_ATOM = 0x7F
DRAW_OVERLAY = 0x73   # run section-12 program n: the status bar's clock, battery and signal


def mode_zero_list() -> bytes:
    """Mode 0's 55 entries: each event calls the object numbered by its position."""
    return b"".join(struct.pack("<BHB", code, index, OBJECT_ATOM)
                    for index, code in enumerate(MODE_ZERO_EVENTS))


# Section 9 opens with the image's own action list, `u8 count; {u16 operand; u8 opcode}`,
# and only then the page registers. The firmware runs it to start the image: in the factory
# image it is `[0x7F 0]`, and object 0 pushes context 0 onto the key stack, enters the
# "update settings" home screen, and shows USB CONNECTED when variable 0x10 is set. All
# four household images name an object of the same shape, ending in the same USB check.
# Without it the firmware read the first page register as this list.
PUSH_CONTEXT = 0xFE00    # `0x1F` band FE: push a section-10 context; FD names the mode
PUSH_CURRENT_MODE = 0xFEFD
# `3F F0xx` writes the firmware's setting 0 (10 at reset), which the 800's handbook reads
# as the timers' unit; the factory image and every donor set it to 100 first thing.
TIMER_UNIT = (0xF064, 0x3F)
LOAD_ONE = 0xFB01        # `0x1F` band FB: load the byte register
USB_CONNECTED = 0x10     # the state variable the USB check compares
COMPARE = 0x71
ENTER_MODE = 0x7E
# The platform screen that says USB CONNECTED: mode 1 in both donors, whose screens the
# scaffold carries, and mode 28 in the factory image.
USB_SCREEN = 1


def startup_objects(home: int, usb_screen: int | None, first: int,
                    idle: dict | None = None, select: int | None = None) -> list[bytes]:
    """The objects the image's start-up list runs, numbered from ``first``.

    The factory image's three, in its own shape: push the image's context and then the
    current mode, so a key is looked up in the mode before the context, enter ``home``,
    and then, in a list of its own because a failed comparison ends the list it is in,
    enter ``usb_screen`` if the remote is on USB.

    With the idle layer, as upstairs starts: the screen timer, the flag resets, then the
    event context, the current mode and the key light on top - so every key lights the
    keypad on its way down - then the light and sound set-up, and only then ``home``:
    the set-up clears the zone flags, which entering a screen sets.
    ``idle`` gives those as `{"resets": [...], "setup": [...]}`, instructions. The
    stack is every donor's: the events, `0xFE`, the current mode, `0xFC`, the key light.
    ``select`` is a context to select last - Off's, so the remote starts with nothing
    running, as every donor starts.
    """
    head = [(PUSH_CONTEXT, 0x1F), (PUSH_CURRENT_MODE, 0x1F), (home, ENTER_MODE), TIMER_UNIT]
    if idle is not None:
        head = ([TIMER_UNIT] + list(idle["resets"])
                + [(PUSH_CONTEXT | EVENT_CONTEXT, 0x1F), (PUSH_CONTEXT | 0xFE, 0x1F),
                   (PUSH_CURRENT_MODE, 0x1F), (PUSH_CONTEXT | 0xFC, 0x1F),
                   (PUSH_CONTEXT | KEY_LIGHT_CONTEXT, 0x1F)]
                + list(idle["setup"]) + [(home, ENTER_MODE)])
        if select is not None:
            head.append((0xFF00 | select, 0x1F))
    if usb_screen is None:
        return [object_body(head)]
    return [
        object_body(head + [(first + 1, OBJECT_ATOM)]),
        object_body([(LOAD_ONE, 0x1F), (first + 2, OBJECT_ATOM)]),
        object_body([(USB_CONNECTED, COMPARE), (usb_screen, ENTER_MODE)]),
    ]


# The idle layer's contexts, after the image's own (0): events, then the key light. The
# charge contexts the firmware looks up under 0xFC are 0 - the image's own, as in every
# donor - and the two after the key light.
EVENT_CONTEXT, KEY_LIGHT_CONTEXT = 1, 2
CHARGE_CONTEXTS = {"normal": 0, "usb": 3, "low": 4}


# Mode 0's three events, by their position in its list.
MODE_ZERO_EVENT_AT = {0x06: 7, 0x07: 9, 0x2D: MODE_ZERO_REDRAW}
ENTER, LEAVE, REDRAW = 0x06, 0x07, 0x2D


def _platform_object(value, first: int):
    """A platform model's operand: an object it names, a timer, or a literal.

    The platform's timers are the image's section 13 in model order, so a timer's index
    is its model index and the operand is the band that starts or stops it.
    """
    if isinstance(value, dict) and "timer" in value:
        return (value["band"] << 8) | value["timer"]
    if isinstance(value, dict) and "charge" in value:
        return (value["band"] << 8) | CHARGE_CONTEXTS[value["charge"]]
    return first + value["object"] if isinstance(value, dict) else value


def timer_record(flags: int, duration: int, operand: int, opcode: int) -> bytes:
    """A section-13 timer: flags, a 24-bit duration, then the instruction it runs."""
    return (bytes([flags]) + duration.to_bytes(3, "little")
            + struct.pack("<HB", operand, opcode))


def _handlers(header, first: int) -> dict[int, int]:
    """A platform screen's event handlers, ``tag -> image object index``."""
    return {key: _platform_object(operand, first)
            for key, operand, category in header
            if category == OBJECT_ATOM and key in (ENTER, LEAVE, REDRAW)}


def _owned_handlers(system, first: int) -> list[tuple[int, int, int]]:
    """Enter, leave and redraw for a screen the image owns, as platform screens have them.

    Every mode on a Harmony One carries an enter and a leave handler, and the firmware's
    own screens also redraw their status overlays on event 2D. A screen this backend adds
    uses the same three: the platform's enter and leave actions and its redraw object.
    """
    if not system:
        return []
    for screen in system["screens"]:
        rows = {key: (operand, category) for key, operand, category in screen["header"]}
        if ENTER in rows and LEAVE in rows and REDRAW in rows \
                and rows[ENTER][1] != OBJECT_ATOM and rows[LEAVE][1] != OBJECT_ATOM:
            return [(tag, _platform_object(rows[tag][0], first), rows[tag][1])
                    for tag in (ENTER, LEAVE, REDRAW)]
    return []


def mode_zero_handler(index: int, platform: dict[int, int] | None = None) -> bytes:
    """What mode 0 does for its entry ``index``, as the user configurations have it.

    The three events call the platform's own mode 0 handlers when a build carries them;
    every key entry does nothing, three empty atoms, a deliberate swallow.
    """
    for tag, at in MODE_ZERO_EVENT_AT.items():
        if index == at and platform and tag in platform:
            return object_body([(platform[tag], OBJECT_ATOM)])
    if index == MODE_ZERO_REDRAW:
        return object_body([(1, 0x73), (3, 0x73), (2, 0x73)])
    return object_body([(0, 0), (0, 0), (0, 0)])


# The firmware's instruction queue holds 40 and drops what does not fit, and running an
# object puts all of its atoms at the head of the queue at once (the Harmony 800's
# section-11 runner, gspm.md). No handler in any donor queues more than 16 deep; a build
# keeps every object to this many atoms, so its handlers stay as shallow.
OBJECT_ATOMS = 8
# Atoms that must stay next to the one after them: a test drops the next instruction, and
# `07 FFFF` silences the next write.
_TIES = {0x70, 0x71}


def _tied(atom) -> bool:
    return atom[1] in _TIES or atom == (0xFFFF, 0x07)


def bounded_objects(bodies: list[bytes]) -> list[bytes]:
    """``bodies`` with every object longer than OBJECT_ATOMS made a chain: its atoms in
    objects of their own, run one after another from the original, which keeps its index.
    A cut never falls after a test or a silent mark."""
    bodies = list(bodies)
    index = 0
    while index < len(bodies):
        body = bodies[index]
        atoms = [struct.unpack_from("<HB", body, 1 + 3 * k) for k in range(body[0])]
        if len(atoms) > OBJECT_ATOMS:
            parts, part = [], []
            for atom in atoms:
                part.append(atom)
                if len(part) >= OBJECT_ATOMS and not _tied(atom):
                    parts.append(part)
                    part = []
            if part:
                parts.append(part)
            calls = []
            for part in parts:
                bodies.append(object_body(part))
                calls.append((len(bodies) - 1, OBJECT_ATOM))
            bodies[index] = object_body(calls)
            continue                      # the chain itself may be too long: look again
        index += 1
    return bodies


def object_body(atoms) -> bytes:
    """A section-11 object: a count, then one `(u16 operand, u8 category)` per atom."""
    return bytes([len(atoms)]) + b"".join(
        struct.pack("<HB", operand, category) for operand, category in atoms)


def touch_templates(directory=None) -> dict[int, list[dict]]:
    """The panel geometry a page of a given button count uses."""
    from ... import paths

    directory = paths.scaffolds("harmony-one") if directory is None else directory
    text = (Path(directory) / TOUCH_TEMPLATES).read_text("utf-8")
    return {int(key): value for key, value in json.loads(text).items()}


def touch_zone(zone: dict, offset: int) -> bytes:
    """One twelve-byte zone: its rectangle, its tag, and a pointer back to itself."""
    return (struct.pack("<HHHH", zone["x"], zone["width"], zone["y"], zone["height"])
            + bytes([zone["tag"]])
            + (gspm.BASE + offset).to_bytes(3, "little"))


# A label too wide for its place is wrapped onto two lines, as the donors draw one: the
# lines sit 6 pixels either side of a menu row's baseline (51 and 63 for 57) and at 5 above
# and 6 below a button's (53 and 64 for 58).
MENU_LINE_OFFSETS = (-6, 6)
BUTTON_LINE_OFFSETS = (-5, 6)
ELLIPSIS = ".."


def _measure(font: dict):
    metrics = font.get("metrics") or font["glyphs"]
    widths = {code: item["width"] for code, item in metrics.items()}
    codes = {item["char"]: code for code, item in metrics.items() if item["char"]}
    return widths, codes


def fit_label(label: str, font: dict, room: int, lines: int = 2) -> list[bytes]:
    """A label as the glyph lines that fit ``room`` pixels, at most ``lines`` of them.

    Words wrap at spaces; a word wider than a line on its own is split where it stops
    fitting. What still does not fit after the last line is cut, and the cut is marked
    with two full stops when the font has them, so a long name is shortened rather than
    refused or drawn past its frame, which nothing in the format clips.
    """
    widths, codes = _measure(font)
    missing = sorted(set(label) - set(codes))
    if missing:
        raise ValueError(
            f"this font cannot draw {', '.join(repr(item) for item in missing)}")

    def width(text):
        return sum(widths[codes[character]] for character in text)

    # Each line remembers how it joins the one before: a space, or nothing where a word
    # was split, so what is cut after the last line reads as the label did.
    out, line, joins = [], "", []
    words = [(word, " ") for word in label.split()]
    while words:
        word, join = words.pop(0)
        candidate = f"{line} {word}" if line else word
        if width(candidate) <= room:
            if not line:
                joins.append(join)
            line = candidate
            continue
        if line:
            out.append(line)
            line = ""
            words.insert(0, (word, join))
            continue
        # One word wider than a whole line: take as much of it as fits.
        cut = 1
        while cut < len(word) and width(word[:cut + 1]) <= room:
            cut += 1
        out.append(word[:cut])
        joins.append(join)
        if word[cut:]:
            words.insert(0, (word[cut:], ""))
    if line:
        out.append(line)
    if len(out) > lines:
        rest = out[lines - 1] + "".join(
            join + text for join, text in zip(joins[lines:], out[lines:]))
        mark = ELLIPSIS if all(character in codes for character in ELLIPSIS) else ""
        while rest and width(rest.rstrip() + mark) > room:
            rest = rest[:-1]
        out = out[:lines - 1] + [rest.rstrip() + mark]
    # what the font was asked to draw - the whole label, since its characters are checked
    # before it is cut, and the cut's mark - so a build can carry exactly those glyphs
    font.setdefault("drawn", set()).update(label, *out)
    return [drawing.GlyphCodes.of(codes[character] for character in text) for text in out]


def _line_ys(baseline: int, count: int, offsets: tuple[int, int]) -> list[int]:
    return [baseline] if count == 1 else [baseline + offset for offset in offsets[:count]]


def button_page(labels: list[str], frames: list[int], font: dict, *,
                prologue: int | None = None, backdrop: int | None = None,
                attribute: int = 0, frame_width: int | None = None) -> list[dict]:
    """The drawing program for a page of command buttons.

    Each button is its frame and then its label, centred over the frame the way every
    donor page centres one: the label's x is the midpoint of the frame less half the
    text's width. A label wider than its button wraps onto a second line.
    """
    if len(labels) != len(frames):
        raise ValueError("a page needs one frame per label")
    if len(labels) > len(BUTTON_POSITIONS):
        raise ValueError(
            f"a page holds at most {len(BUTTON_POSITIONS)} buttons, not {len(labels)}")
    widths, _codes = _measure(font)
    out = []
    if prologue is not None:
        out.append({"opcode": "call", "target": prologue})
    # Nothing in the format clears the screen, so a page that draws no backdrop leaves
    # whatever the last one drew underneath its buttons.
    if backdrop is not None:
        out.append({"opcode": "bitmap", "x": 0, "y": 0, "target": backdrop})
    # A label is measured in one font, so it has to be drawn in that font: the drawing
    # VM draws text in whichever attribute was set last, and a page that sets none draws
    # in whatever the previous program left behind. Every donor page sets it explicitly.
    out.append({"opcode": "attribute", "value": attribute})
    for index, (label, frame) in enumerate(zip(labels, frames)):
        left, top = BUTTON_POSITIONS[index]
        out.append({"opcode": "bitmap", "x": left, "y": top, "target": frame})
        frame_width = FRAME_WIDTH if frame_width is None else frame_width
        if label is None:          # a picture that says it all: a favourite's logo
            continue
        lines = fit_label(label, font, frame_width)
        for glyphs, y in zip(lines, _line_ys(top + LABEL_BASELINE, len(lines),
                                             BUTTON_LINE_OFFSETS)):
            width = sum(widths[code] for code in glyphs)
            out.append({
                "opcode": "inline_text",
                "x": (2 * left + frame_width - width) // 2,
                "y": y,
                "glyphs": glyphs.hex(),
            })
    out.append({"opcode": "end"})
    return out


FRAME_WIDTH = 81

# The softkeys, as upstairs draws them in the bottom strip of the screen (raw touch
# coordinates, y measured upwards): Options or Activities on the left, Devices on the
# right, each label in its own font - the attribute numbers are upstairs', which the
# scaffold's fonts keep.
SOFTKEY_LEFT_ZONE = {"x": 1257, "width": 1395, "y": 271, "height": 1001}
SOFTKEY_RIGHT_ZONE = {"x": 2406, "width": 1150, "y": 271, "height": 1001}
SOFTKEYS = {"options": (22, 202), "activities": (16, 202), "devices": (110, 202),
            "commands": (16, 202), "favourites": (16, 202), "exit": (110, 202)}
SOFTKEY_FONTS = {"options": 13, "activities": 6, "devices": 9, "commands": 6,
                 "favourites": 6, "exit": 9}

# The Tutorial: each page's words, and what moves on from it - the key it teaches.
TUTORIAL = (("tutorial.welcome", "next"), ("tutorial.activities", "touch"),
            ("tutorial.switching", "activities"), ("tutorial.pages", "next"),
            ("tutorial.help", "help"), ("tutorial.assistant", "next"),
            ("tutorial.off", "off"), ("tutorial.done", "exit"))
TUTORIAL_TOP, TUTORIAL_LINES = 40, 9
# The keys each screen binds them to, as upstairs does: the Activities screen's softkeys
# are its 0x30 and 0x31 zones, the device list's Activities is its template's 0x33, and a
# command page's are 0x2B and 0x2C.
HOME_OPTIONS_TAG, HOME_DEVICES_TAG = 0x30, 0x31
SOFTKEY_RIGHT_KEY = 0x80 | HOME_DEVICES_TAG
MENU_ACTIVITIES_KEY = 0xB3
# The Activities menu, which has both softkeys besides its rows, as upstairs' has.
MENU_OPTIONS_KEY, MENU_DEVICES_KEY = 0xB3, 0xB4
PAGE_ACTIVITIES_KEY, PAGE_DEVICES_KEY = 0xAB, 0xAC
# The Options screen, as upstairs draws it: its row frames at the menu rows, labels centred
# on them in its row font (attribute 5). Screen Sounds' label reads its flag: 0 offers to
# turn the sounds off, 1 to turn them on.
OPTIONS_FONT = 5
OPTIONS_FRAME_WIDTH = 164
OPTIONS_LABEL_ROOM = OPTIONS_FRAME_WIDTH - 8


def picture_size(body: bytes) -> tuple[int, int]:
    """A stored picture's width and height, from its header."""
    return struct.unpack_from("<HH", body, 1)


def softkey_label(text: str, font: dict, attribute: int, xy) -> list[dict]:
    """A softkey's label: one line in its own font, cut to the half-strip it sits in."""
    lines = fit_label(text, font, SCREEN_WIDTH - xy[0], lines=1)
    return [{"opcode": "attribute", "value": attribute},
            {"opcode": "inline_text", "x": xy[0], "y": xy[1], "glyphs": lines[0].hex()}]

# A screen's title and page counter, as every donor draws them: the title at (6,4) in a
# title font, a paged screen's total at (23,18) followed by the word, and each page's
# number right-aligned against the slash at (18,18), in a smaller font of the same colour.
# Which fonts follow the screen: cyan for Activities, green for Options, orange for the
# device screens.
TITLE_XY = (6, 4)
TITLE_ROOM = 96          # what the status bar's clock and battery leave of the top line
PAGE_COUNTER_Y = 18
PAGE_TOTAL_XY = (23, 18)
PAGE_SLASH_XY = (18, 18)
PAGES_GAP = 5
TITLE_FONTS = {"activities": (10, 12), "options": (2, 7), "devices": (3, 4),
               "commands": (3, 4), "commands-paged": (3, 4),
               "activity": (10, 12), "activity-paged": (10, 12), "help": (2, 7),
               "activity-both": (10, 12), "activity-both-paged": (10, 12),
               "question": (2, 7), "tutorial": (2, 7)}

# The device menu: three rows a page, each a full-width frame, a device icon and a label,
# with the row's touch key opening that device's first command page. Geometry measured on
# every donor and identical across them.
MENU_ROWS_PER_PAGE = 3
MENU_FRAME_XY = ((6, 38), (6, 92), (6, 146))
MENU_ICON_XY = ((11, 39), (11, 93), (11, 147))
MENU_LABEL_XY = ((63, 57), (63, 111), (63, 165))
MENU_ROW_KEYS = (0xB0, 0xB1, 0xB2)
# Donor menu rows end with `(1, 0x99)`, which looked like a constant marker. Opcodes from
# 0x80 write variable `opcode & 0x7f`, so it sets the donor's own variable 25, whose
# meaning and range differ from donor to donor; a generated image has no variable 25.
MENU_TEMPLATE_FILE = "platform/menu-template.json"

# The two side-strip touch zones every screen template carries, used here to move between
# a device's command pages and between menu pages. Their tags are 0x2e and 0x2f.
SIDE_PREV_KEY = 0xAE
SIDE_NEXT_KEY = 0xAF


def menu_template(directory=None) -> list[dict]:
    """The device-menu touch geometry the scaffold carries."""
    from ... import paths

    directory = Path(paths.scaffolds("harmony-one") if directory is None else directory)
    return json.loads((directory / MENU_TEMPLATE_FILE).read_text("utf-8"))


def menu_page(labels: list[str], frame: int, icons: list[int], font: dict, *,
              prologue: int | None = None, backdrop: int | None = None,
              attribute: int = 0, label_room: int | None = None,
              rows=None) -> list[dict]:
    """The drawing program for a page of device-menu rows.

    Each row is the full-width frame, the device's icon, and its name on the frame's
    baseline. A name too wide for the row wraps onto a second line. ``rows`` are the
    row places to draw in, the first ones when not given.
    """
    if len(labels) > MENU_ROWS_PER_PAGE:
        raise ValueError(
            f"a menu page holds {MENU_ROWS_PER_PAGE} rows, not {len(labels)}")
    out = []
    if prologue is not None:
        out.append({"opcode": "call", "target": prologue})
    if backdrop is not None:
        out.append({"opcode": "bitmap", "x": 0, "y": 0, "target": backdrop})
    out.append({"opcode": "attribute", "value": attribute})
    places = range(len(labels)) if rows is None else rows
    for index, label, icon in zip(places, labels, icons):
        out.append({"opcode": "bitmap", "x": MENU_FRAME_XY[index][0],
                    "y": MENU_FRAME_XY[index][1], "target": frame})
        if icon is not None:
            out.append({"opcode": "bitmap", "x": MENU_ICON_XY[index][0],
                        "y": MENU_ICON_XY[index][1], "target": icon})
        lines = fit_label(label, font, MENU_LABEL_MAX if label_room is None else label_room)
        x, baseline = MENU_LABEL_XY[index]
        for glyphs, y in zip(lines, _line_ys(baseline, len(lines), MENU_LINE_OFFSETS)):
            out.append({"opcode": "inline_text", "x": x, "y": y, "glyphs": glyphs.hex()})
    out.append({"opcode": "end"})
    return out


# What an image with no devices shows on the screen it boots into.
SCREEN_WIDTH = 176
EMPTY_MESSAGE_WIDTH = SCREEN_WIDTH - 12
EMPTY_MESSAGE_Y = 111

# A device row's label starts at x=63 on a 176-wide screen, so it has this much room.
MENU_LABEL_MAX = 176 - 63



SYSTEM_SCREENS_FILE = "platform/system-screens.json"
SYSTEM_TEMPLATES_FILE = "platform/system-templates.json"
SYSTEM_SCHEMA = "afterglow-harmony-one-system-screens/1"
# Addresses for blocks built from a model rather than read out of an image. A pointer is
# 24 bits past the mapping base, so these sit inside that range but far above anything
# an image this backend will write can reach.
MODEL_BLOCK = 0xF00000
# Carried screens' blocks and the Options screen's own label blocks, in the same space.
CARRIED_BLOCK = 0xF80000
ACTIVITY_BLOCK = 0xFA0000

# What the starting and Help screens draw, and where, as every donor's draw them: the
# starting screen's name in attribute 11, the rest in attribute 0, lines 12 apart.
START_FONT, HELP_FONT = 11, 0
START_TEXT_Y, START_KEEP_TOP = 124, 179
HELP_TOP, HELP_KEEP_TOP, HELP_SENDING_XY = 43, 162, (57, 95)
QUESTION_TOP = 70
LINE_SPACING = 12


def load_system(directory=None) -> dict:
    """The firmware's own screens, as the scaffold carries them."""
    from ... import paths

    directory = Path(paths.scaffolds("harmony-one") if directory is None else directory)
    model = json.loads((directory / SYSTEM_SCREENS_FILE).read_text("utf-8"))
    if model.get("schema") != SYSTEM_SCHEMA:
        raise ValueError(
            f"{SYSTEM_SCREENS_FILE} declares {model.get('schema')!r}, not {SYSTEM_SCHEMA!r}")
    model["templates"] = json.loads((directory / SYSTEM_TEMPLATES_FILE).read_text("utf-8"))
    return model


def system_blocks(model: dict, pictures: dict[str, int], first_object: int) -> dict:
    """The platform's blocks with every name resolved, keyed by a model address.

    Block references become model addresses the layout maps to where each block lands;
    pictures resolve to where they were placed; an object reference becomes the index the
    platform's objects were given in this image. Nothing refers to a donor any more.
    """
    blocks = {}
    for index, block in enumerate(model["blocks"]):
        instructions = []
        for item in block:
            item = dict(item)
            target = item.get("target")
            if isinstance(target, dict) and "block" in target:
                item["target"] = MODEL_BLOCK + target["block"]
            elif isinstance(target, dict) and "picture" in target:
                role = target["picture"]
                if role not in pictures:
                    raise ValueError(
                        f"the platform screens draw {role!r}, which the scaffold lacks")
                item["target"] = pictures[role]
            if item["opcode"] == "switch":
                item["cases"] = [(value, MODEL_BLOCK + at) for value, at in item["cases"]]
                item["ranges"] = [(low, high, MODEL_BLOCK + at)
                                  for low, high, at in item["ranges"]]
            if item["opcode"] == "atom" and isinstance(item.get("operand"), dict):
                item["operand"] = first_object + item["operand"]["object"]
            instructions.append(item)
        blocks[MODEL_BLOCK + index] = instructions
    return blocks


def configuration(project: dict, **options) -> bytes:
    """Build a whole configuration for a project from the scaffold (see ``build``)."""
    return build(project, **options)["image"]


def build(project: dict, *, directory=None, library=None,
          stamp_fields=None, buttons: int = HOUSEHOLD_BUTTONS) -> dict:
    """Build a whole configuration for a project from the scaffold, and nothing else.

    Fonts are emitted in the donor's attribute order, because the firmware's own screens
    name fonts by attribute; the one labelling a button is found by the role the scaffold
    records for it rather than assumed.
    """
    from ... import paths
    from . import assets

    directory = Path(paths.scaffolds("harmony-one") if directory is None else directory)
    if stamp_fields is None:
        stamp_fields = build_stamp()
    words = catalogue.for_project(project)
    manifest = assets.read_manifest(directory)
    # Each font carries only the characters it draws, as Logitech's builder did: a build
    # with every character the words could need records what each slot drew, and the
    # image is then built with exactly those, numbered from 1 in each slot.
    candidates = catalogue.characters(words) | {
        character for device in project.get("devices") or []
        for text in [device.get("label") or ""] + list(device.get("signals") or {})
        for character in text} | {
        character for activity in project.get("activities") or []
        for text in [activity.get("label") or ""] + [
            button.get("label") or "" if isinstance(button, dict) else button[0]
            for button in (activity.get("soft_buttons") or []) + [
                entry for _name, entries in activity.get("screen_groups") or []
                for entry in entries]]
        for character in text} | set(project.get("power_off_label") or "")
    first = _configuration(project, directory, manifest, assets.load(directory, candidates),
                           stamp_fields, buttons, library, words)
    drawn = {role: font.get("drawn", set()) for role, font in first["fonts"].items()}
    built = _configuration(project, directory, manifest, assets.load(directory, drawn),
                           stamp_fields, buttons, library, words)
    # what each font attribute's codes stand for, since every image numbers its own
    built["characters"] = [{code: item["char"] for code, item in font["metrics"].items()}
                           for _role, font in sorted(built["fonts"].items())]
    return built


def _configuration(project, directory, manifest, loaded, stamp_fields, buttons, library,
                   words) -> dict:
    """One build of ``project`` with the fonts ``loaded``: the image, and the fonts as
    laid out, each knowing what it drew."""
    order = sorted(loaded["fonts"])
    button = manifest.get("font_roles", {}).get("button")
    if button not in loaded["fonts"]:
        raise ValueError("the scaffold names no font for labelling a button")
    pictures = {role: item["body"] for role, item in loaded["pictures"].items()}
    devices = lowered_devices(project, library=library)
    for device, spec in zip(devices, project.get("devices") or []):
        device["icon"] = row_icon(directory, manifest, pictures, "devices", spec.get("type"))
    planned = activity_plan.plan(project, devices)
    held_commands(project, devices, planned, library=library)
    frame = "activity/row-frame" if "activity/row-frame" in pictures else "row-frame"
    for activity in planned["activities"]:
        activity["icon"] = row_icon(directory, manifest, pictures, "activities",
                                    activity["type"], frame)
        activity["start_icon"] = start_icon(directory, manifest, pictures, activity["type"])
        for number, favourite in enumerate(activity["favourites"]):
            favourite["picture"] = favourite_picture(
                directory, manifest, pictures, favourite["image"],
                number % len(BUTTON_POSITIONS), planned["skipped"],
                f"activity {activity['label']!r} favourite {favourite['label']!r}")
    # one set of fonts for everything this build draws, so each records all it drew
    fonts = [font_from_scaffold(loaded["fonts"][role]) for role in order]
    image = skeleton(
        buttons=buttons, stamp=authoring.stamp(*stamp_fields),
        tail=platform_tail(directory),
        fonts=fonts,
        label_font=order.index(button),
        softkey_fonts=dict(SOFTKEY_FONTS) if len(order) > max(SOFTKEY_FONTS.values())
        else None,
        pictures=pictures,
        engine=engine_records(*stamp_fields),
        devices=devices,
        templates=touch_templates(directory), system=load_system(directory),
        options=options_model(fonts, stamp_fields[-1], words),
        words=words, activities=planned)
    return {"image": image, "fonts": dict(zip(order, fonts)), "skipped": planned["skipped"]}


# A device row's icon sits over the row frame's left end: this patch of the frame.
ROW_ICON_SIZE = (51, 48)


def row_icon(directory, manifest: dict, pictures: dict, kind: str,
             name: str | None, frame: str = "row-frame") -> str | None:
    """Compose the row icon for a ``kind`` of type ``name`` into ``pictures``, once per
    icon and frame, and return its role (row_icons.py); None when the scaffold has no
    type icons. Activities' rows are drawn on their own frame (``activity/row-frame``),
    so their icons carry that frame's patch rather than a device row's."""
    role = row_icons_role(kind, name, directory, frame)
    if role is not None and role not in pictures:
        at = (MENU_ICON_XY[0][0] - MENU_FRAME_XY[0][0], MENU_ICON_XY[0][1] - MENU_FRAME_XY[0][1])
        pictures[role] = _composed(directory, manifest, frame, at, ROW_ICON_SIZE, kind, name)
    return role


def row_icons_role(kind, name, directory, frame="row-frame"):
    from . import row_icons

    role = row_icons.role(kind, name, directory)
    if role is None or frame == "row-frame":
        return role
    return f"{frame.rsplit('/', 1)[0]}/{role}"


# Where an activity's icon sits on the screen it starts on, and the box it is fitted to.
START_ICON_XY, START_ICON_SIZE = (57, 67), (62, 42)
SENDING_XY = (57, 33)


def start_icon(directory, manifest: dict, pictures: dict, name: str | None) -> str | None:
    """Compose the icon an activity of type ``name`` shows while it starts: its type
    icon on the patch of the backdrop it is drawn over, so it needs no transparency."""
    from . import row_icons

    path = row_icons.source(directory, "activities", name)
    if path is None or "backdrop" not in manifest["pictures"]:
        return None
    role = f"activity/start-icon/{path.stem}"
    if role not in pictures:
        pictures[role] = _composed(directory, manifest, "backdrop", START_ICON_XY,
                                   START_ICON_SIZE, "activities", name, box=START_ICON_SIZE)
    return role


# A favourite's logo sits inside its button's frame, clear of the bevel.
LOGO_BOX = (73, 42)


def logo_file(name) -> Path | None:
    """A favourite's logo: a path, or a name in the owner's logos folder (paths.py)."""
    from ... import paths

    if not name:
        return None
    for path in (Path(name), paths.logos_dir() / str(name)):
        if path.is_file():
            return path
    return None


def favourite_picture(directory, manifest, pictures, image, position, skipped,
                      where) -> str | None:
    """Compose a favourite's logo onto the frame of the button place it is drawn in, so
    it needs no transparency; None, and a note, when the logo cannot be found."""
    from ... import imaging
    from . import assets, bitmap, row_icons

    path = logo_file(image)
    if path is None:
        if image:
            skipped.append(f"{where}: no logo {image!r}; its name is drawn instead")
        return None
    frame = f"activity/button-frame/{position}"
    if frame not in manifest["pictures"]:
        frame = f"button-frame/{position}"
    role = f"favourite/{path.stem}/{position}"
    if role not in pictures:
        under = imaging.decode((Path(directory) / manifest["pictures"][frame]["file"])
                               .read_bytes())["rows"]
        logo = imaging.decode(path.read_bytes())["rows"]
        size = (len(under[0]), len(under))
        rows = row_icons.compose(under, (0, 0), size, logo, LOGO_BOX)
        image_ = {"width": size[0], "height": size[1], "rows": rows}
        pictures[role] = bitmap.encode(assets.to_rows(image_)[0], mode=assets.MODES["shorter"])
    return role


def _composed(directory, manifest, frame, at, size, kind, name, box=None) -> bytes:
    from ... import imaging
    from . import assets, bitmap, row_icons

    under = imaging.decode((Path(directory) / manifest["pictures"][frame]["file"])
                           .read_bytes())["rows"]
    icon = imaging.decode(row_icons.source(directory, kind, name).read_bytes())["rows"]
    rows = row_icons.compose(under, at, size, icon, box or row_icons.FIT)
    image = {"width": size[0], "height": size[1], "rows": rows}
    return bitmap.encode(assets.to_rows(image)[0], mode=assets.MODES["shorter"])


def build_stamp(now=None) -> tuple:
    """The clock a configuration starts with: when it was built, as section 3 and the
    clock variables hold it (day and month counted from 0)."""
    import datetime

    now = datetime.datetime.now() if now is None else now
    return (now.second, now.minute, now.hour, now.day - 1, now.month - 1, now.year)


def labeller(fonts: list[dict]):
    """``label(text, attribute, room)``: one line of text in the image's font of that
    attribute, as glyph codes (hex) and its width, cut to ``room`` pixels."""
    def label(text, attribute, room):
        [glyphs] = fit_label(text, fonts[attribute], room, lines=1)
        widths, _codes = _measure(fonts[attribute])
        return glyphs.hex(), sum(widths[code] for code in glyphs)
    return label


def options_model(fonts: list[dict], year: int, words=None) -> dict | None:
    """The Options screens (options.py), their text set in the image's own fonts."""
    from . import options

    if not fonts or len(fonts) <= max(options.TITLE_FONT, options.COUNTER_FONT,
                                      options.LABEL_FONT, options.BACK_FONT):
        return None
    return options.build(labeller(fonts), year, words)
