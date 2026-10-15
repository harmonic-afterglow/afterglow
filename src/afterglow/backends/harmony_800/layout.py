"""The image a build is laying out: its objects, its modes and their pages, the touch
templates, and the drawing blocks and switch tables made along the way.

A screen's ordinal, an object's index and a switch table's number are positions, so each
is handed out in the order things are asked for and never changes; that order is what
makes a build reproducible. What a mode's programs point at is placed later, so each mode
is reserved whole when it is numbered and its programs are written once everything has an
address (assemble.py).

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import struct

from . import drawing, structures
from .structures import OBJECT_ATOM, object_body

# Addresses for the drawing blocks a build makes for its own switches - the Options
# screen's labels, the activities' screens - in the space model blocks use (scaffold.py).
ACTIVITY_BLOCK = 0xFA0000

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


def place(out: bytearray, body: bytes) -> int:
    """Put a structure where a sequential native read stays inside one 64 KiB window."""
    offset = structures._align_window(out, len(body))
    out += body
    return offset


def place_picture(out: bytearray, body: bytes) -> int:
    """Pictures do not obey the window: a 176x220 backdrop is 77,445 bytes on its own."""
    offset = len(out)
    out += body
    return offset


class Layout:
    """One image being laid out. ``out`` is its bytes so far, the header first."""

    def __init__(self, out: bytearray):
        self.out = out
        # Objects are numbered before anything is placed, since key rows and handlers
        # name them by index; their bodies are placed after the modes, as in every donor.
        self.objects: list[bytes | None] = []
        # Section 6's trailers, and the slots whose key registers section 9 will hold.
        self.trailers: list[int] = []
        self.pending_slots: list[tuple] = []
        # Page programs to write once what they point at has an address:
        # ``(address, build(picture, prologue), prologue)``.
        self.pending_programs: list[tuple] = []
        self.template_zones: list[list[dict]] = []
        self.fixed_templates = 0
        # Model blocks that live inside a reserved mode, by their model address; the
        # carried screens' ones; and copies of a carried block another mode reuses.
        self.fixed_blocks: dict[int, int] = {}
        self.carried_fixed: dict[int, int] = {}
        self.extra_copies: list[tuple[int, int]] = []
        # Fragments a firmware screen's page calls, which carry an end after their return.
        self.fragments: set[int] = set()
        # The build's own blocks and switch tables (section 15), numbered after the
        # carried screens' tables.
        self.blocks: dict[int, list[dict]] = {}
        self.groups: list[dict] = []
        self.group_base = 0
        # Only the pictures some program draws are placed, as Logitech's builder placed
        # them: every donor's pictures are all reached.
        self.drawn: set[str] = set()

    # -- objects

    def object(self, body: bytes) -> int:
        """Number an object; its index."""
        self.objects.append(body)
        return len(self.objects) - 1

    def reserve_objects(self, count: int) -> int:
        """Number ``count`` objects whose bodies are given later; the first index."""
        base = len(self.objects)
        self.objects.extend([None] * count)
        return base

    def navigation(self, ordinal: int) -> int:
        """A go-to-screen object."""
        return self.object(structures.navigation_object(
            ordinal, structures.IR_OBJECT_KIND_FALLBACK))

    def atoms_object(self, atoms) -> int:
        """An object running ``atoms``; one holds 255, so a longer list is split into
        objects run one after another."""
        atoms = list(atoms)
        if len(atoms) <= 0xFF:
            return self.object(object_body(atoms))
        parts = [self.atoms_object(atoms[at:at + 0xFF]) for at in range(0, len(atoms), 0xFF)]
        return self.atoms_object([(part, OBJECT_ATOM) for part in parts])

    # -- modes and templates

    def mode(self, header, flag: int, mode_pages) -> list[list[int]]:
        """Reserve one mode, laid out as every donor lays one out, contiguously:

            [handler list] then, per page, [fragment] [page program] [7-byte page record]
            then [entry: flag, list, page count, pages]

        ``header`` is its list's bytes, or the address of a list placed elsewhere; each
        page is ``(template, rows, program sizes)``, and its record draws the last program.
        Readers find a page's program at the end of its mode's list, so nothing else may
        sit there. Section 9 holds every register back to back, so a page record is
        reserved with its register pointer left open. Returns each page's program
        addresses."""
        out = self.out
        own = header if isinstance(header, (bytes, bytearray)) else b""
        size = len(own) + sum(sum(sizes) + 7 for _t, _r, sizes in mode_pages)
        size += len(structures.screen_trailer(flag, 0, [0] * len(mode_pages)))
        start = place(out, bytes(size))
        out[start:start + len(own)] = own
        list_at = start if own else header
        cursor = start + len(own)
        addresses, slots = [], []
        for template, rows, sizes in mode_pages:
            placed = []
            for program_size in sizes:
                placed.append(cursor)
                cursor += program_size
            self.pending_slots.append((cursor, template, list(rows), placed[-1]))
            slots.append(cursor)
            cursor += 7
            addresses.append(placed)
        trailer = structures.screen_trailer(flag, list_at, slots)
        out[cursor:cursor + len(trailer)] = trailer
        self.trailers.append(cursor)
        return addresses

    def keep_templates(self, templates) -> int:
        """Add templates named by position - the firmware's screens', the carried
        screens' - as they are; the index of the first."""
        base = len(self.template_zones)
        self.template_zones.extend(list(zones) for zones in templates)
        return base

    def fix_templates(self):
        """Templates so far are named by index and never shared with a page's own."""
        self.fixed_templates = len(self.template_zones)

    def template(self, zones) -> int:
        """A page's template: pages with the same zones share one, as the donors' do,
        since section 19 indexes at most 255."""
        zones = list(zones)
        shared = self.template_zones[self.fixed_templates:]
        if zones in shared:
            return self.fixed_templates + shared.index(zones)
        self.template_zones.append(zones)
        return len(self.template_zones) - 1

    # -- the build's own blocks and switches

    def block(self, block: list[dict]) -> int:
        """A drawing block a switch runs, placed with the carried screens' blocks. It is the
        build's own, so drawn on the 800's display as it is (geometry.place): a case drawing
        at the One's origin put a switch row's label a row low and to the right."""
        at = ACTIVITY_BLOCK + len(self.blocks)
        self.blocks[at] = [dict(item, native=True) for item in block]
        return at

    def group(self, cases, ranges=()) -> int:
        """A section-15 switch table, numbered after the carried screens' tables."""
        self.groups.append({"lead": 2, "cases": list(cases), "ranges": list(ranges)})
        return self.group_base + len(self.groups) - 1

    def draws(self, role: str) -> int:
        """Measure a program: note the picture it draws, at a stand-in address."""
        self.drawn.add(role)
        return 0

    def program_sizes(self, builds, prologue) -> list[int]:
        """Each program's size, measured with every address standing at zero - a
        program's size does not depend on its addresses."""
        return [len(drawing.encode_program(build(self.draws, prologue))) for build in builds]
