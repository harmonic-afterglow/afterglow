"""Say how a Harmony One configuration would be generated rather than edited.

A build should start from the remote's platform layer and generate everything else from
the project, so a new configuration is never a copy of an old one. Four independent
images share almost nothing - different glyph repertoires, fonts, chrome strings, button
frames and selectors, 7 to 19 per cent of bytes matching at the same offset - but that
describes how they were produced, not what the format requires. They were emitted from
an asset library, a subset at a time. A remote fresh out of its box had no previous
configuration either.

So this module holds two things. `SECTION_PLAN` says, section by section, how a generated
image would produce one and what evidence stands behind that, because the sections still
marked unknown are the whole distance left to go. `classify_screens` and `audit` say who
owns what inside an existing image, which is what a generated configuration has to be
able to supply.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from collections import Counter

from . import activity_index, command_index, drawing, ui_index


# Every image measured opens section 10 with the same number of contexts before its
# activities begin, whatever else differs between them.
BASE_CONTEXTS = 7

# A screen's ordinal is not free: the firmware selects its own screens by index, and the
# first forty belong to it. Both household donors draw the same text with the same
# instruction shape in all forty - 40 of 40 - and nothing an owner owns appears before
# ordinal 40 in one or 44 in the other. They are notices and diagnostics: the battery
# warning and the charging-problem screen with their OK buttons, "Learning...", "Update
# in progress", and then the thirty messages the factory configuration also carries,
# among them "Invalid Configuration" and "Configuration Corrupted" - the two the remote
# would use to say it had rejected a configuration.
#
# A generated image that starts its own screens at ordinal 0 is therefore not merely
# missing them; its first command page stands where the low-battery notice belongs.
#
# They are the vendor's own work and delivered rather than dumped: both donor containers
# carry `TRANSFERTYPE Winsock`, post to members.harmonyremote.com, hold one payload
# member and match their own checksum. And they are structurally constant without being
# byte-constant - the same text and instruction shape in all forty, at the same addresses,
# but only 2 of the 40 programs identical, because each points at pictures and glyph
# strings that sit elsewhere in each configuration. Carrying them means carrying a model
# and linking it, which is what `compose` does, not copying a blob.
#
# `generate.configuration` does exactly that: it emits them at ordinals 0 to 39 from the
# scaffold's `platform/system-screens.json`, and a project's own screens start at 40.
SYSTEM_SCREENS = 40

DEVICE_COMMANDS = "device-commands"
DEVICE_MENU = "device-menu"
ACTIVITY_MENU = "activity-menu"
UNCLASSIFIED = "unclassified"


def classify_screens(payload: bytes, ownership: dict | None = None) -> dict[int, str]:
    """Say who owns each screen, and leave the ones nobody has claimed unclassified."""
    ownership = command_index.inspect(payload) if ownership is None else ownership
    menus = ui_index.device_menus(payload, ownership)
    activities = ui_index.activity_rows(payload, ownership)
    out = {
        ordinal: UNCLASSIFIED
        for ordinal in range(len(ui_index.screen_slots(payload)))
    }
    for row in (row for menu in menus["menus"] for row in menu["rows"]):
        if row["target_screen"] is not None and row["target_screen"] in out:
            out[row["target_screen"]] = DEVICE_COMMANDS
    for menu in menus["menus"]:
        out[menu["screen"]] = DEVICE_MENU
    for ordinal in activities["screens"]:
        out[ordinal] = ACTIVITY_MENU
    return out


def _program_bytes(payload: bytes, screens: list[dict], ordinals) -> tuple[int, int]:
    roots = [
        slot["program_offset"] for ordinal in ordinals
        for slot in screens[ordinal]["slots"]
    ]
    if not roots:
        return 0, 0
    blocks = drawing.program_blocks(payload, roots)
    return len(blocks), sum(
        len(drawing.encode_program(block)) for block in blocks.values())


def audit(payload: bytes, ownership: dict | None = None) -> dict:
    """Report what a scaffold would keep, and what still stands in the way of cutting one.

    A screen nobody claims is not evidence of platform ownership. The count of them
    tracks how many activities an image has - 149 screens for three activities, 319 for
    nine - so activity-owned screens are still in there, and until they can be named the
    remainder cannot be called a platform layer.
    """
    ownership = command_index.inspect(payload) if ownership is None else ownership
    screens = ui_index.screen_slots(payload)
    classes = classify_screens(payload, ownership)
    counts = Counter(classes.values())
    contexts = activity_index.contexts(payload)
    by_class = {}
    for label in (DEVICE_COMMANDS, DEVICE_MENU, ACTIVITY_MENU, UNCLASSIFIED):
        ordinals = [key for key, value in classes.items() if value == label]
        blocks, size = _program_bytes(payload, screens, ordinals)
        by_class[label] = {
            "screens": len(ordinals), "blocks": blocks, "program_bytes": size,
        }
    blocking = []
    if counts[UNCLASSIFIED]:
        blocking.append(
            f"{counts[UNCLASSIFIED]} screens are owned by nobody this backend can name")
    if len(contexts) > BASE_CONTEXTS:
        blocking.append(
            f"{len(contexts) - BASE_CONTEXTS} activity contexts have no portable model, "
            "so they can be kept or dropped but not rebuilt")
    return {
        "screens": dict(counts),
        "by_class": by_class,
        "devices": ownership["counts"]["devices"],
        "contexts": {
            "base": min(BASE_CONTEXTS, len(contexts)),
            "activity": max(0, len(contexts) - BASE_CONTEXTS),
        },
        # A scaffold may only be cut when nothing household is left in what it keeps.
        "can_cut": not blocking,
        "blocking": blocking,
    }


# What a section is made of, and therefore how a generated image would produce one.
#
#   constant  the same bytes in all four images measured; carried
#   emitted   this backend writes it, and the writer reproduces every donor's bytes
#   modelled  this backend reads and writes the structure, but supplies the content
#   unknown   neither the bytes nor a model; nothing can be generated for it yet
CONSTANT = "constant"
EMITTED = "emitted"
MODELLED = "modelled"
UNKNOWN = "unknown"

# Sections whose bytes are identical in all four images measured.
# Section 16 indexes section 15's tail at these offsets, in every image measured
# including the factory configuration in firmware 54.2.5.
SECTION_16_OFFSETS = (0, 3, 16, 19, 22, 35, 68, 101, 104, 109, 134)

CONSTANT_SECTIONS = {
    1: bytes.fromhex("0c0c360d000000"),
    2: bytes.fromhex("100000f0ff3f000040"),
    17: bytes.fromhex("00"),
    18: bytes.fromhex("0000"),
}

SECTION_PLAN = {
    0: (MODELLED, "named property records, read by named_index"),
    1: (CONSTANT, "7 bytes, identical in all four"),
    2: (CONSTANT, "9 bytes, identical in all four"),
    3: (EMITTED, "two markers around a timestamp of second, minute, hour, day, "
                 "weekday, month and year. The day and month count from zero and the "
                 "weekday counts Sunday as zero, which all five images agree with"),
    4: (EMITTED, "a constant 126-byte head, then every command record again, counted "
                 "and grouped by device; reproduces all four byte for byte"),
    5: (EMITTED, "device and command index"),
    6: (EMITTED, "screen index, trailers and slots"),
    7: (MODELLED, "font index; glyphs can be authored"),
    9: (EMITTED, "key registers"),
    10: (MODELLED, "context table and bodies; what an activity context means is not "
                   "established"),
    11: (EMITTED, "object table and bodies"),
    12: (MODELLED, "the overlay table: status-bar, battery and charge programs that "
                   "switch on firmware state, then per-activity stubs of unknown "
                   "meaning. No screen calls it, so it is a drawing root of its own"),
    13: (EMITTED, "a u8-counted table of 7-byte records whose meaning is not "
                  "established, and does not need to be: the factory configuration in "
                  "firmware 54.2.5 counts zero of them, so a generated image emits the "
                  "count alone"),
    14: (EMITTED, "a state machine per property: an initial value, a limit, and "
                  "transitions carrying an object index. Every field is a state "
                  "number or an index, so a record holds no address and moves as "
                  "it is. What the properties mean is still not established"),
    15: (EMITTED, "a u8-counted table of pointers, which the factory configuration "
                  "counts zero of, followed by a 151-byte platform table. Only 3 of "
                  "those 151 bytes differ between the factory and a household image"),
    16: (EMITTED, "11 pointers into section 15's own 151-byte tail, at the same 11 "
                  "offsets in every image measured including the factory one, so the "
                  "index is derived from the table rather than stored beside it"),
    17: (CONSTANT, "1 byte, identical in all four"),
    18: (CONSTANT, "2 bytes, identical in all four"),
    19: (MODELLED, "touch templates and the bitmaps they draw; bitmaps can be authored"),
}


def plan() -> dict:
    """Report how each section of a generated image would be produced, and what blocks it.

    Generating a configuration from nothing needs every section to be constant, emitted
    or modelled. The ones that are neither are the whole distance left to go, and naming
    them is more useful than a summary that averages them away.
    """
    by_state: dict[str, list[int]] = {}
    for section, (state, _why) in sorted(SECTION_PLAN.items()):
        by_state.setdefault(state, []).append(section)
    return {
        "sections": {
            section: {"state": state, "evidence": why}
            for section, (state, why) in sorted(SECTION_PLAN.items())
        },
        "by_state": by_state,
        "blocking": [
            f"section {section}: {SECTION_PLAN[section][1]}"
            for section in by_state.get(UNKNOWN, ())
        ],
        "can_generate": not by_state.get(UNKNOWN),
    }
