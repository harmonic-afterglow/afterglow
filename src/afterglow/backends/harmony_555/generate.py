"""Build an arch-9 image - a Harmony 5xx's - from a project and the scaffold, and nothing else.

The scaffold carries the platform as a model (tools/arch9_extract_platform.py): the
firmware's own screens and the frame every household is built in (platform/screens.json),
the wiring that connects the firmware's events to them (platform/wiring.json) and the
pictures (images/) - the pictures and typeface a theme's where a theme is given
(artwork.py). A build numbers the household's screens, objects, contexts and
variables after the platform's, draws every page in Logitech's band shape with the
scaffold's typeface, and lays the whole out with link.Pieces, so every pointer is the
build's own.

Format reference: docs/harmony_5xx/ahcm.md
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

from . import activities as activities_module, artwork, catalogue, \
    devices as devices_module, drawing, gspm, infrared, keys, pixels, records, typeface
from ... import activity_layouts
from .link import Pieces
from .structures import (
    context_record, engine_record, name_chain, object_body, stamp, stamp_weekday,
    timer_record)

WIDTH, HEIGHT, BAND = 96, 64, 8
BANDS = HEIGHT // BAND
WIRING_FILE = "platform/wiring.json"
SCREENS_FILE = "platform/screens.json"
WIRING_SCHEMA = "afterglow-arch9-wiring/1"
SCREENS_SCHEMA = "afterglow-arch9-screens/1"
# A model whose platform is another's with its own skin and keys: no empty configuration
# of its own exists, and its households measure the same platform otherwise
# (tools/arch9_derive_platform.py).
DERIVED_FILE = "platform/derived.json"
DERIVED_SCHEMA = "afterglow-arch9-derived/1"
# A key list that names nearly every key - the idle key set, "Stopping Activity", the USB
# screen - names a key a model adds too, and drops one it lacks.
WHOLE_KEYPAD = 40
# The clock: section 14's first seven variables hold section 3's time - second, minute,
# hour, day, weekday, month (the day and month from zero) and the year since 2000, whose
# limit is one past it in every configuration measured.
CLOCK = 7
WIDE = 0xFF                      # a variable whose limit passes this takes two bytes
SKIN_AT = 2                      # section 1: `09 09 <skin> 0d 00 00 00`
OBJECT, SCREEN, COMMAND, DEVICE = 0x7F, 0x7E, 0x7D, 0x7C
WRITE = 0x80                     # `0x80 | n`: write variable n
# The pictures a household's pages draw that the platform's frame does not: the page
# backdrop, its dotted line across the middle between the top corners and the bottom.
HOUSEHOLD_PICTURES = {"page": "images/page.png"}
# the platform's blank backdrop, which a page with no bottom row draws on
PLAIN = "picture-0"
# The fonts, by attribute, as the platform's frame numbers them, and the counter's.
NOTICE, ASSISTANT, TITLE, SOFTKEY, COUNTER = 0, 1, 2, 3, 4
LABEL = NOTICE
# A page as Logitech draws one (docs/harmony_5xx/ahcm.md, "Pages"): the title centred on
# the top row, a label in each corner beside its key - a line from y 13 at the top and 35
# at the bottom, a second 11 rows under it - the right-hand ones ending at the right
# edge, and "n OF m" on the bottom row in a font eight rows high.
CORNERS = 4
CORNER_ROOM = 47
CORNER_Y = {"top": (13, 24), "bottom": (35, 46)}
COUNTER_Y = 56
ELLIPSIS = ".."
# where a translation's long word may break: drawn as "-" only if it breaks there
SOFT_HYPHEN = "\u00ad"
# The events a context's rows answer besides keys: its start when it is selected, its
# leaving when another is, and its being picked again while it runs (docs/harmony_5xx/
# ahcm.md, "Activities").
START, LEAVE, AGAIN = 0x01, 0x02, 0x05
# a command that starts a film: Play or Pause, "Play (press)" too
START_PLAY = re.compile(r"^(Play|Pause)\b")
SWITCH, TEST, SYSTEM, PAUSE = 0x72, 0x71, 0x1F, 0x3F
SELECT_CONTEXT = 0xFF00          # `1F FFnn`: select context nn
# How every chain Logitech's 5xx configurations end a start or a stop on: a pause, the byte
# register cleared, and a test of the battery variable that shows "Replace the batteries"
# before the screen the chain arrives at (harmony-decompiler's FORMAT.md, 5al).
CHAIN_PAUSE = (0xD000, PAUSE)
CHAIN_CLEAR = (0xFB00, SYSTEM)
BATTERY_TEST = (0x8008, TEST)
ANY = 0xFFFE                     # a transition from any value
WAIT_TENTHS = 100                # the longest wait Logitech writes in one `7C`
# Help's questions, as Logitech's 555 asks them (docs/harmony_5xx/ahcm.md, "Help"), by
# their catalogue keys: the question, and the one asked again
IS_ON, NOW_ON = "help.is-on", "help.now-on"
IS_SET, NOW_SET = "help.is-set", "help.now-set"
IS_STATE, NOW_STATE = "help.is-state", "help.now-state"
IS_OFF, NOW_OFF = "help.is-off", "help.now-off"
LINE = typeface.SLOT_HEIGHT      # a line of text below the one above it
SHOWN = 0x06                     # the event a screen raises when it is shown
QUESTION_Y = (1, 12, 23)
YES_KEY, NO_KEY = 0x9F, 0x9E     # the soft keys under "Yes" and "No", bottom left and right
# The layout keys a model has, from its profile (`vocabulary.layout_key_scans`): the 555's
# and the 550's Sound and Picture (docs/harmony_5xx/ahcm.md, "Sound and Picture"), and the
# catalogue's title for each layout's pages
LAYOUTS = {"sound": ("Sound", "layout.sound"), "picture": ("Picture", "layout.picture")}


def load_json(directory: Path, name: str, schema: str) -> dict:
    data = json.loads((directory / name).read_text("utf-8"))
    if data.get("schema") != schema:
        raise ValueError(f"{name} declares {data.get('schema')!r}, not {schema!r}")
    return data


def own_skin(project: dict, profile) -> int | None:
    """The skin a build writes when the remote is sold under another of its profile's
    numbers - the 510 a 515's - as its project says
    (``settings.skin``, which an import keeps); None for the profile's own. A skin the
    profile does not list is ignored: a project moved to another model keeps none."""
    skin = (project.get("settings") or {}).get("skin")
    try:
        skin = int(skin)
    except (TypeError, ValueError):
        return None
    return skin if skin in profile.other_skins else None


def drawn(text: str) -> str:
    """``text`` as drawn: a soft hyphen where it does not break a word is not."""
    return text.replace(SOFT_HYPHEN, "")


class TooLarge(ValueError):
    """A built image too large for the remote's configuration region."""


# What a build that does not fit leaves out, in turn: extras of Afterglow's that the
# remote works without - Help's second asking of a question (a "Now is..." No asks
# again where Logitech's ask it from a copy), then the Sound and Picture layouts of a
# device's own screen. Logitech's own images draw neither, and are smaller for it.
LEAN = ((), ("help retries",), ("help retries", "device layouts"))
LEFT_OUT_NOTES = {
    "help retries": "Help asks a question again from its \"Now is...\" screen, not from "
                    "a copy of its own, so the configuration fits the remote",
    "device layouts": "a device's own screen has no Sound or Picture layouts, so the "
                      "configuration fits the remote",
}

# The backlight times a build takes, in seconds (the GUI offers the same range)
BACKLIGHT_SECONDS = (2, 120)


class Image:
    """One image being built."""

    def __init__(self, project: dict, directory: Path, stamp_fields: tuple, words=None,
                 theme=None):
        self.project, self.directory = project, Path(directory)
        self.derived = None
        if (self.directory / DERIVED_FILE).is_file():
            self.derived = load_json(self.directory, DERIVED_FILE, DERIVED_SCHEMA)
            self.directory = self.directory.parent / self.derived["from"]
        # the words drawn, in the project's language (catalogue.Words); and the English a
        # model draws otherwise than the platform it is derived from ("Choose an Activity")
        self.words = catalogue.for_project(project) if words is None else words
        self.english_words = dict((self.derived or {}).get("words") or {})
        self.wiring = load_json(self.directory, WIRING_FILE, WIRING_SCHEMA)
        model = load_json(self.directory, SCREENS_FILE, SCREENS_SCHEMA)
        self.art = artwork.Art(self.directory, theme)
        self.pictures = {role: pixels.encode_picture(self.art.picture(item["file"]))
                         for role, item in model["pictures"].items()}
        self.face = typeface.load(str(self.art.face_directory()))
        if self.art.face_directory() != self.directory:
            self.face.marks = {}
        self.stamp_fields = stamp_fields
        wiring = self.wiring
        self.screens = [_screen(screen) for screen in model["screens"]]
        self.translate_platform()
        self.objects = [[tuple(atom) for atom in atoms] for atoms in wiring["objects"]]
        self.contexts = [{"form": context["form"],
                          "rows": [{"flags": flags, "key_code": key, "operand": operand,
                                    "category": category}
                                   for flags, key, operand, category in context["rows"]]}
                         for context in wiring["contexts"]]
        self.variables = [{"initial": item["initial"], "limit": item["limit"],
                           "transitions": [{"flags": flags, "from": source, "to": target,
                                            "operand": operand, "category": category}
                                           for flags, source, target, operand, category
                                           in item["transitions"]]}
                          for item in wiring["variables"]]
        self.timers = [tuple(timer) for timer in wiring["timers"]]
        self.programs = [[tuple(atom) for atom in atoms] for atoms in wiring["programs"]]
        self.tables = [[tuple(case) for case in table["cases"]] for table in wiring["tables"]]
        self.lead = [tuple(atom) for atom in wiring["lead"]]
        self.names = [tuple(name) for name in wiring["names"]]
        for role, name in HOUSEHOLD_PICTURES.items():
            self.pictures[role] = pixels.encode_picture(self.art.picture(name))
        if self.derived:
            self.derive(self.derived)
        from ... import remotes
        remote = (project.get("settings") or {}).get("remote") or "harmony-555"
        profile = remotes.get(remote)
        self.keypad = keys.Keypad.of(profile)
        self.skin = own_skin(project, profile)
        self.layout_scans = dict((profile.vocabulary or {}).get("layout_key_scans") or {})
        self.devices: list[dict] = []
        self.skipped: list[str] = []
        # what a build leaves out to fit the remote (LEAN): Help's second asking of a
        # question, then the Sound and Picture layouts of a device's own screen
        self.left_out: set[str] = set()

    # -- a model derived from another's platform

    def derive(self, derived: dict) -> None:
        """Another model on this platform: its skin, and the keys it lacks and has besides,
        as its own configurations list them. A key list of the whole keypad drops a key
        the model lacks and gains one it adds, run as the list runs its other keys: by the
        one object they share, or by a copy of a neighbour's own."""
        if derived.get("graft"):
            self.apply_graft(derived["graft"])
        absent = {keys.code(scan) for scan in derived.get("absent_scans") or []}
        added = [keys.code(scan) for scan in derived.get("added_scans") or []]
        section1 = bytearray.fromhex(self.wiring["section1"])
        section1[SKIN_AT] = derived["skin"]
        self.wiring = dict(self.wiring, section1=section1.hex())

        def adjust(rows, make, unmake):
            codes = [unmake(row)[0] for row in rows]
            if sum(1 for code in codes if code & 0x80) < WHOLE_KEYPAD:
                return rows
            kept = [row for row in rows if unmake(row)[0] not in absent]
            presses = [unmake(row) for row in kept if unmake(row)[0] & 0x80]
            handlers = [(operand, category) for _code, operand, category in presses]
            for code in added:
                if code in codes:
                    continue
                shared = max(set(handlers), key=handlers.count)
                if handlers.count(shared) > 1:
                    handler = shared
                else:
                    nearest = min(presses, key=lambda row: abs(row[0] - code))
                    handler = ((self.new_object(self.objects[nearest[1]]), OBJECT)
                               if nearest[2] == OBJECT else nearest[1:])
                kept.append(make(code, *handler))
            return kept
        for context in self.contexts:
            context["rows"] = adjust(
                context["rows"],
                lambda code, operand, category: {"flags": context["rows"][0]["flags"],
                                                 "key_code": code, "operand": operand,
                                                 "category": category},
                lambda row: (row["key_code"], row["operand"], row["category"]))
        for screen in self.screens:
            screen["keys"] = adjust(screen["keys"], lambda *row: tuple(row), tuple)

    def apply_graft(self, graft: dict) -> None:
        """The parts of the platform a model holds otherwise (graft.py): objects and key
        sets replaced, timers replaced, and the new objects they reference appended -
        `{"new": n}` is the n-th of them."""
        base = len(self.objects)

        def atom(operand, category):
            if isinstance(operand, dict):
                operand = base + operand["new"]
            return (operand, category)
        for atoms in graft.get("new") or []:
            self.objects.append([atom(*item) for item in atoms])
        for index, atoms in (graft.get("objects") or {}).items():
            self.objects[int(index)] = [atom(*item) for item in atoms]
        for index, rows in (graft.get("contexts") or {}).items():
            context = self.contexts[int(index)]
            flags = context["rows"][0]["flags"] if context["rows"] else None
            context["rows"] = [{"flags": flags, "key_code": key,
                                "operand": atom(operand, category)[0], "category": category}
                               for key, operand, category in rows]
        for index, (flags, seconds, operand, category) in (graft.get("timers") or {}).items():
            self.timers[int(index)] = (flags, seconds, *atom(operand, category))

    # -- the clock

    def stamp_clock(self) -> None:
        second, minute, hour, day, month, year = self.stamp_fields
        weekday = stamp_weekday(day, month, year)
        for index, value in enumerate((second, minute, hour, day, weekday, month,
                                       year - 2000)):
            self.variables[index]["initial"] = value
        self.variables[CLOCK - 1]["limit"] = year - 2000 + 1

    # -- text

    def text_of(self, line: dict) -> str:
        text = line["text"]
        return self.english_words.get(text, text)

    def translate_platform(self) -> None:
        """The platform's own screens in the project's language: each text of the
        catalogue's found on a page by its English lines and drawn where they were, in as
        many lines as it takes (translated_lines). Its English is left as the platform
        draws it. ``self.blocks`` keeps, by (screen, page), each text's key and lines."""
        self.blocks = {}
        for number, screen in enumerate(self.screens):
            for at, page in enumerate(screen["pages"]):
                page["lines"], self.blocks[(number, at)] = self.translated_lines(
                    page["lines"])

    def translated_lines(self, lines: list[dict]) -> tuple[list[dict], list]:
        """A platform page's lines translated, and its texts: ``(key, lines)`` each, key
        None for a line the catalogue does not have. A text placed from its English
        lines' top, moved up when it needs more lines than there is room for above the
        next text, the answers or the bottom of the screen, wrapped between words and cut
        when even that is not enough. An answer is centred where its English was."""
        body = [line for line in lines if line["attribute"] != SOFTKEY]
        answers = [line for line in lines if line["attribute"] == SOFTKEY]
        blocks, at = [], 0
        while at < len(body):
            for end in range(len(body), at, -1):
                key = catalogue.PLATFORM_KEYS.get("\n".join(line["text"]
                                                             for line in body[at:end]))
                if key:
                    blocks.append((key, body[at:end]))
                    at = end
                    break
            else:
                blocks.append((None, body[at:at + 1]))
                at += 1
        keys = [key for key, _lines in blocks] + [
            catalogue.PLATFORM_KEYS.get(line["text"]) for line in answers]
        if all(key is None or self.words.english(key) for key in keys):
            return lines, blocks
        out, placed, top = [], [], 0
        floor = min((line["y"] for line in answers), default=HEIGHT)
        for index, (key, block) in enumerate(blocks):
            first = block[0]
            limit = blocks[index + 1][1][0]["y"] if index + 1 < len(blocks) else floor
            if key is None or self.words.english(key):
                rows, y = [line["text"] for line in block], first["y"]
            elif first["y"] == 0 and first["attribute"] == TITLE:
                rows, y = [self.words.text(key).replace("\n", " ")], 0
            else:
                rows = [row for part in self.words.text(key).split("\n")
                        for row in self.wrap(part, lines=BANDS)]
                y = max(first["y"], top)
                if y + LINE * len(rows) > limit:
                    y = max(top, limit - LINE * len(rows))
                room = max(1, (limit - y) // LINE)
                if len(rows) > room:
                    rows = rows[:room - 1] + [self.fit(" ".join(rows[room - 1:]), WIDTH)]
            made = [dict(first, y=y + LINE * row, text=text) for row, text in enumerate(rows)]
            out += made
            placed.append((key, made))
            top = made[-1]["y"] + LINE
        for line in answers:
            key = catalogue.PLATFORM_KEYS.get(line["text"])
            if key is None or self.words.english(key):
                out.append(line)
                continue
            text = drawn(self.words.text(key))
            width = self.face.width(text)
            centre = line["x"] + self.face.width(line["text"]) / 2
            out.append(dict(line, text=text,
                            x=min(max(0, round(centre - width / 2)), max(0, WIDTH - width))))
        return out, placed

    def lines(self, page: dict) -> list[dict]:
        """A page's lines placed: each line's text, attribute, x and y."""
        out = []
        for line in page["lines"]:
            text = drawn(self.text_of(line))
            if line["align"] == "left" and line["y"] == 0:
                text = self.fit(text, WIDTH)      # a title, cut as Logitech's are
            width = self.face.width(text)
            if width > WIDTH:
                raise ValueError(f"{text!r} is {width} px, wider than the screen")
            x = ((WIDTH - width) // 2 if line["align"] == "centre"
                 else WIDTH - width if line["align"] == "right" else line["x"])
            out.append({"attribute": line["attribute"], "x": x, "y": line["y"], "text": text})
        return out

    # -- layout

    def build(self) -> bytes:
        self.stamp_clock()
        self.place_backlight()
        self.place_devices()
        self.place_activities()
        return self.lay_out()

    def place_backlight(self) -> None:
        """How long the screen stays lit (``settings.backlight_timeout``, seconds): the
        backlight's timer's duration (importing.remote_settings reads it back). Without
        the setting the platform's own time stays."""
        from types import SimpleNamespace

        from .graft import timer_role

        given = str((self.project.get("settings") or {}).get("backlight_timeout") or "").strip()
        if not given:
            return
        try:
            seconds = int(given)
        except ValueError:
            seconds = None
        if seconds is None or not BACKLIGHT_SECONDS[0] <= seconds <= BACKLIGHT_SECONDS[1]:
            self.skipped.append(f"backlight timeout {given!r}: not a whole number of seconds "
                                f"from {BACKLIGHT_SECONDS[0]} to {BACKLIGHT_SECONDS[1]}; "
                                f"the remote's own time is kept")
            return
        view = SimpleNamespace(objects=self.objects)
        for index, timer in enumerate(self.timers):
            if timer_role(view, timer) == "backlight":
                self.timers[index] = (timer[0], seconds, *timer[2:])

    # -- the household's pages

    def fit(self, text: str, room: int) -> str:
        """``text`` cut to ``room`` pixels, with ".." where it was cut, as Logitech's."""
        text = drawn(text)
        if self.face.width(text) <= room:
            return text
        while text and self.face.width(text + ELLIPSIS) > room:
            text = text[:-1]
        return text.rstrip() + ELLIPSIS

    def corner_lines(self, text: str, words: bool = False) -> list[str]:
        """A corner label in one line, or two: split at a space, after a word's hyphen
        ("AUX-" over "Eingang"), at a soft hyphen, or where a capital starts a word inside
        a name ("ChannelSelect"), but only where an import joins the two lines back into
        the same name (importing.join_lines) - a device's or an activity's name only at a
        space or a hyphen - the first line as long as fits, as Logitech's labels break
        ("Watch a" over "DVD", "InputBlu-" over "ray"). A "\\n" in the label starts the
        second line."""
        from .importing import broken_at_hyphen, join_lines

        if "\n" in text:
            first, second = text.split("\n", 1)
            return [self.fit(first, CORNER_ROOM)] + (
                [self.fit(second.replace("\n", " "), CORNER_ROOM)] if second.strip() else [])
        if self.face.width(drawn(text)) <= CORNER_ROOM:
            return [drawn(text)]
        cuts = {}
        for at in range(1, len(text)):
            if text[at - 1] == " " or broken_at_hyphen(text[:at]) and text[at:].strip():
                cuts[at] = (drawn(text[:at]).rstrip(), drawn(text[at:]).lstrip())
            elif text[at] == SOFT_HYPHEN and at + 1 < len(text):
                cuts[at] = (drawn(text[:at]) + "-", drawn(text[at + 1:]))
            elif not words and text[at].isupper() and text[at - 1].islower():
                cuts[at] = (drawn(text[:at]), drawn(text[at:]))
        fallback = None
        for at in sorted(cuts, reverse=True):
            first, second = cuts[at]
            if not first or self.face.width(first) > CORNER_ROOM:
                continue
            lines = [first, self.fit(second, CORNER_ROOM)]
            if text[at] == SOFT_HYPHEN or join_lines(lines, words) == drawn(text):
                return lines
            fallback = fallback or lines
        return fallback or [self.fit(text, CORNER_ROOM)]

    def page(self, title: str, labels: list[str], number: int, count: int, *,
             title_align: str = "centre", words: bool = False) -> dict:
        """A page of four corners: ``labels`` top left, top right, bottom left, bottom
        right, under ``title``, with "n OF m" when there is more than one page. The
        dotted line between the rows is drawn only when the bottom row has a label, as
        Logitech's pages do: one with two or fewer has the plain backdrop."""
        lines = [{"attribute": TITLE, "x": 0, "y": 0, "align": title_align,
                  "text": self.fit(title, WIDTH)}]
        drawn_as: dict[tuple, list[str]] = {}
        for corner, label in enumerate(labels):
            if label is None:          # a place left empty
                continue
            row = "top" if corner < 2 else "bottom"
            align = "left" if corner % 2 == 0 else "right"
            shown = self.corner_lines(label, words)
            drawn_as.setdefault(tuple(shown), []).append(label)
            for y, text in zip(CORNER_Y[row], shown):
                lines.append({"attribute": LABEL, "x": 0, "y": y, "align": align,
                              "text": text})
        self._say_what_was_cut(title, drawn_as)
        if count > 1:
            lines.append({"attribute": COUNTER, "x": 0, "y": COUNTER_Y, "align": "centre",
                          "text": self.words("page.counter", number=number + 1,
                                             count=count)})
        bottom = any(label is not None for label in labels[2:CORNERS])
        return {"backdrop": "page" if bottom else PLAIN, "overlays": [dict(self.underline)],
                "lines": lines, "keys": []}

    def _say_what_was_cut(self, title: str, drawn_as: dict) -> None:
        """A label cut with ".." to fit its corner, and two that come out the same, are
        said in the build's warnings: "InputComponent1" and "InputComponent2" were both
        drawn "InputComponen.." with nothing said, two buttons no one could tell apart.
        Each page once - a page is built again while a build is fitted to the remote."""
        said = getattr(self, "_cut_said", None)
        if said is None:
            said = self._cut_said = set()
        for shown, names in drawn_as.items():
            cut = [name for name in names if any(line.endswith(ELLIPSIS) for line in shown)
                   and not name.rstrip().endswith(ELLIPSIS)]
            for name in cut:
                if (title, name) not in said:
                    said.add((title, name))
                    self.skipped.append(f"{title!r}: {name!r} is cut short to fit the "
                                        f"screen, as {' '.join(shown)!r}")
            if len(names) > 1 and (title, shown) not in said:
                said.add((title, shown))
                self.skipped.append(
                    f"{title!r}: {', '.join(repr(n) for n in names)} look the same on the "
                    f"screen ({' '.join(shown)!r}); give one a shorter on-screen label")

    def corner_keys(self) -> list[int]:
        return [keys.code(keys.SCREEN_KEYS[corner]) for corner in (
            "top-left", "top-right", "bottom-left", "bottom-right")]

    def new_object(self, atoms) -> int:
        self.objects.append([tuple(atom) for atom in atoms])
        return len(self.objects) - 1

    def place_devices(self) -> None:
        """Each device: an object per command - the command, its device, sent once - a
        screen of its own, its keys bound and four commands a page, and a corner on the
        Devices screen that opens it."""
        self.devices = devices_module.lowered_devices(self.project, self.keypad)
        if not self.devices:
            return
        devices_screen, flag = self._devices_entry()
        list_page = self.screens[devices_screen]["pages"][0]
        self.underline = next(overlay for overlay in list_page["overlays"]
                              if overlay["height"] == 1)
        corner_keys = self.corner_keys()
        command_keys = self._command_keys()
        opens = []
        for device in self.devices:
            for command in device["commands"]:
                command["object"] = self.new_object([
                    (command["command_id"], COMMAND),
                    (device["index"] << 8 | command.get("sends", 1), DEVICE)])
            bound = {}
            for command in device["commands"]:
                for name in command["keys"]:
                    bound.setdefault(self.keypad.by_name(name), command["object"])
            header = [(code, bound[code], OBJECT) if code in bound else (code, 0, 0)
                      for code in command_keys]
            shown = sorted((c for c in device["commands"] if not c["hidden"]),
                           key=lambda c: c["rank"])
            chunks = [shown[at:at + CORNERS] for at in range(0, len(shown), CORNERS)] or [[]]
            pages = []
            for number, chunk in enumerate(chunks):
                page = self.page(device["label"], [c["label"] for c in chunk], number,
                                 len(chunks))
                page["keys"] = [(corner_keys[corner], c["object"], OBJECT)
                                for corner, c in enumerate(chunk)]
                pages.append(page)
            self.screens.append({"flag": 0, "keys": header, "pages": pages})
            device["screen"] = len(self.screens) - 1
            opens.append(self.new_object([(device["screen"], SCREEN), (1, WRITE | flag)]))
        # the Devices screen: its own title, four devices a page
        title = next(line["text"] for line in list_page["lines"] if line["y"] == 0)
        chunks = [list(range(at, min(at + CORNERS, len(self.devices))))
                  for at in range(0, len(self.devices), CORNERS)]
        pages = []
        for number, chunk in enumerate(chunks):
            page = self.page(title, [self.devices[index]["label"] for index in chunk],
                             number, len(chunks), title_align="left", words=True)
            page["keys"] = list(list_page["keys"]) + [
                (corner_keys[corner], opens[index], OBJECT)
                for corner, index in enumerate(chunk)]
            pages.append(page)
        self.screens[devices_screen]["pages"] = pages
        self.place_device_layouts()

    def _devices_entry(self) -> tuple[int, int]:
        """The Devices screen and the variable that says a device was picked from it:
        what the idle activity's Devices key runs - `[0x7E screen, flag := 1]`."""
        devices_key = keys.code(keys.DEVICES)
        for context in self.contexts:
            for row in context["rows"]:
                if row["key_code"] != devices_key or row["category"] != OBJECT:
                    continue
                atoms = self.objects[row["operand"]]
                screens = [operand for operand, category in atoms if category == SCREEN]
                writes = [category & 0x7F for operand, category in atoms
                          if category >= WRITE and operand == 1]
                if len(screens) == 1 and len(writes) == 1:
                    return screens[0], writes[0]
        raise ValueError("the platform's wiring has no Devices key that opens a screen")

    def _command_keys(self) -> list[int]:
        """The keys a device's screen binds, in the order the idle key set lists them:
        every press but the ones the firmware's flow owns."""
        owned = {keys.code(scan) for scan in (keys.PAGE_FORWARD, keys.PAGE_BACK,
                                              *keys.FLOW.values(), *keys.FIRMWARE_ONLY)}
        idle = max(self.contexts, key=lambda context: len(context["rows"]))
        return [row["key_code"] for row in idle["rows"]
                if row["key_code"] & 0x80 and row["key_code"] not in owned]

    # -- the platform's roles

    def _named(self, prefix: str) -> int:
        found = [identifier for level, identifier, name in self.names
                 if level == 1 and name.startswith(prefix)]
        if len(found) != 1:
            raise ValueError(f"the platform names {len(found)} variables {prefix}")
        return found[0]

    def _lookups(self, atoms) -> list[tuple[int, int]]:
        return [(operand >> 8, operand & 0xFF) for operand, category in atoms
                if category == SWITCH]

    def _roles(self) -> dict:
        """Where the platform keeps what an activity extends, found by what it does: the
        idle activity's context and its start, the Activities menu, "Stopping Activity",
        the battery warning, and the switch tables that answer by the activity state - the
        activity's screen, its key set, its Devices screen - and by the location: the menu,
        setting the state to idle, everything off."""
        state, location = self._named("CurrentActivityState"), self._named("CurrentLocation")
        idle = next(index for index, context in enumerate(self.contexts)
                    if {row["key_code"] for row in context["rows"]} >= {
                        START, AGAIN, keys.code(keys.DEVICES)})
        rows = {row["key_code"]: row for row in self.contexts[idle]["rows"]}
        stop = self.objects[rows[START]["operand"]]
        stopping = next(operand for operand, category in stop if category == SCREEN)
        by_state = {table for program in self.programs
                    for table, variable in self._lookups(program) if variable == state}
        by_location = {}
        for atoms in [*self.objects, *self.programs]:
            for table, variable in self._lookups(atoms):
                if variable == location:
                    by_location[table] = self.programs[self.tables[table][0][1]] \
                        if self.tables[table] else []
        menu_table = next(table for table, program in by_location.items()
                          if len(program) == 1 and program[0][1] == SCREEN
                          and program[0][0] != stopping
                          and any(self._lookups(self.programs[self.tables[t][0][1]]) ==
                                  [(table, location)] for t in by_state if self.tables[t]))
        menu = by_location[menu_table][0][0]
        set_idle = next(table for table, program in by_location.items()
                        if program == [(0, WRITE | state)])
        stop_tables = [table for table, variable in self._lookups(stop)
                       if variable == location]
        all_off = next(table for table in stop_tables if table != set_idle)

        def state_table(test) -> int:
            found = [table for table in by_state if test(self.tables[table])]
            if len(found) != 1:
                raise ValueError("the platform's switch tables are not the empty 555's")
            return found[0]
        screen_table = state_table(lambda cases: cases and self._lookups(
            self.programs[cases[0][1]]) == [(menu_table, location)])
        key_sets = state_table(lambda cases: not cases)
        devices_table = state_table(lambda cases: cases and len(
            self.programs[cases[0][1]]) == 1 and self.programs[cases[0][1]][0][1] == SCREEN)
        # the battery warning a stop's chain shows: the chain's test, then its screen
        battery = None
        for atoms in self.objects:
            if atoms and atoms[0] == BATTERY_TEST and len(atoms) > 1 \
                    and atoms[1][1] == SCREEN:
                battery = atoms[1][0]
                break
        if battery is None:
            raise ValueError("the platform has no battery warning")
        return {"state": state, "location": location, "idle": idle, "rows": rows,
                "stopping": stopping, "menu": menu, "menu_table": menu_table,
                "set_idle": set_idle,
                "all_off": all_off, "screen_table": screen_table, "key_sets": key_sets,
                "devices_table": devices_table, "battery": battery,
                "help": rows.get(keys.code(keys.HELP))}

    # -- variables

    def add_variable(self, name: str | None, record: dict) -> int:
        """A narrow variable of the household's, before the terminator that ends section
        14 - the platform's last, the one wide variable - and named in section 0."""
        if self.variables[-1]["limit"] <= WIDE:
            raise ValueError("the platform's variables do not end with the terminator")
        at = len(self.variables) - 1
        self._renumber_variable(at, at + 1)
        self.variables.insert(at, record)
        if name:
            self.names.insert(self._first_name_after_states(), (1, at, name))
        return at

    def _first_name_after_states(self) -> int:
        levels = [level for level, _identifier, _name in self.names]
        last = max(index for index, level in enumerate(levels) if level == 1)
        return last + 1

    def _renumber_variable(self, old: int, new: int) -> None:
        """Nothing the platform runs names the terminator; refuse if something does,
        rather than leave it pointing at a household variable."""
        def names(atoms):
            return any((category & 0x7F) == old and category >= WRITE
                       or category in (TEST, 0x70, SWITCH) and operand & 0xFF == old
                       for operand, category in atoms)
        if any(names(atoms) for atoms in [*self.objects, *self.programs, self.lead]):
            raise ValueError(f"the platform names variable {old}, which has to move")

    def place_device_states(self) -> None:
        """Each device's power, input and other states as variables whose transitions
        send (devices.device_state_records): power on sends the on code and waits the
        device's delay, off its off code; an input chosen directly runs from any value, so
        a re-pick sends it again, one reached by stepping has a transition for every pair;
        a state of its own is set the same ways. Every variable is numbered before any is
        filled, since an input's sequence may set one of the device's states."""
        self.power_var, self.input_var = {}, {}
        # a device an activity switches on keeps a power variable even with no power code
        # to send, as Logitech's do: changing it sends nothing, but it says the device is on
        switched = {did for activity in self.project.get("activities") or []
                    for did in activity.get("power_on_devices") or []}
        for device in self.devices:
            index = device["index"]
            for command in device["commands"]:
                command["object_index"] = command["object"]
            label = device["label"].replace(" ", "_")
            reserved = {}
            if device.get("power"):
                reserved["power"] = self.add_variable(None, {})
            elif device.get("id") in switched and not device.get("always_on"):
                self.power_var[index] = self.add_variable(
                    f"{label}_Power_2", {"initial": 0, "limit": 1, "transitions": []})
            if (device.get("inputs") or {}).get("values"):
                reserved["input"] = self.add_variable(None, {})
            states = {}
            for state in device.get("states") or []:
                states[state["id"]] = reserved[f"state:{state['id']}"] = \
                    self.add_variable(None, {})
            made = devices_module.device_state_records(device, self.new_object, states)
            if len(made) != len(reserved):
                raise ValueError(f"device {device['label']!r}: its variables are not the "
                                 "ones reserved for it")
            for (name, record), (kind, variable) in zip(made, reserved.items()):
                self.variables[variable] = {key: record[key]
                                            for key in ("initial", "limit", "transitions")}
                self.names.insert(self._first_name_after_states(), (1, variable, name))
            if "power" in reserved:
                self.power_var[index] = reserved["power"]
            if "input" in reserved:
                self.input_var[index] = reserved["input"]
            if device.get("online"):
                # said with what it means and what to do: "is not built for this remote"
                # left a tester with neither
                self.skipped.append(f"{device['label']!r}: this remote cannot wait for the "
                                    "TV's apps after switching it on; if an app input is "
                                    "not ready when an activity starts, raise the TV's "
                                    "\"Ready after switching on\" on its Timing page")
            del label

    def command_object(self, device: int, command_id: int) -> int:
        for command in self.devices[device]["commands"]:
            if command["command_id"] == command_id:
                return command["object"]
        raise ValueError(f"device {device} has no command {command_id}")

    def held_command(self, device: int, command_id: int, held_ms: int) -> int:
        """A send held for ``held_ms``, as Logitech's 5xx configurations write one: the
        command's object with a count of sends after its device - the code and its repeat
        frames, as long as the hold - where a plain send's is 1. One object per command
        and count."""
        from .importing import _frame

        held = self.__dict__.setdefault("held", {})
        source = next(command for command in self.devices[device]["commands"]
                      if command["command_id"] == command_id)
        press, frame = _frame(self.project["devices"][device]["signals"][source["name"]])
        press_ms = sum(abs(pulse) for pulse in press) / 1000
        frame_ms = sum(abs(pulse) for pulse in frame) / 1000 or press_ms
        # the count of sends whose length is nearest the hold
        count = min(range(1, 0x100),
                    key=lambda n: abs(press_ms + frame_ms * (n - 1) - held_ms))
        if (command_id, count) not in held:
            held[(command_id, count)] = self.new_object([(command_id, COMMAND),
                                                         (device << 8 | count, DEVICE)])
        return held[(command_id, count)]

    def waits(self, device: int, milliseconds: int) -> list[tuple[int, int]]:
        """A wait before the device's next send, in tenths, at most 100 an instruction."""
        tenths, out = round(milliseconds / 100), []
        while tenths > 0:
            chunk = min(WAIT_TENTHS, tenths)
            out.append(((device << 8) | chunk, DEVICE))
            tenths -= chunk
        return out

    def selection_atoms(self, device: int, selection) -> list[tuple[int, int]]:
        if selection is None:
            return []
        if isinstance(selection, int):
            return [(self.command_object(device, selection), OBJECT)]
        out = []
        for step in selection:
            if step[0] == "send":
                out.append((self.command_object(device, step[1]), OBJECT))
            elif step[0] == "wait":
                out += self.waits(device, step[1])
        return out

    def step_atoms(self, steps) -> list[tuple[int, int]]:
        """A plan's steps: sends, waits and inputs set."""
        out = []
        for step in steps:
            if step[0] == "send":
                if len(step) > 3 and step[3]:
                    out.append((self.held_command(step[1], step[2], step[3]), OBJECT))
                else:
                    out.append((self.command_object(step[1], step[2]), OBJECT))
            elif step[0] == "wait":
                out += self.waits(step[1], step[2])
            elif step[0] == "input" and step[1] in self.input_var:
                out.append((step[2], WRITE | self.input_var[step[1]]))
        return out

    def without_start_play(self, steps: list) -> list:
        """``steps`` without a last Play or Pause and the waits before it: the step that
        starts a film, which Logitech's 5xx configurations leave out when an activity is
        chosen again while it runs (every one of six such activities measured)."""
        out = list(steps)
        while out and out[-1][0] == "send" and START_PLAY.match(
                self.command_name(out[-1][1], out[-1][2])):
            out.pop()
            while out and out[-1][0] == "wait":
                out.pop()
        return out

    def command_name(self, device: int, command_id: int) -> str:
        return next((command["name"] for command in self.devices[device]["commands"]
                     if command["command_id"] == command_id), "")

    # -- activities

    def place_activities(self) -> None:
        """Each activity as Logitech's 555 builds one: a key set (context) the menu
        selects, whose start shows "Starting", switches the devices, sets the inputs and
        the activity state, then - past the battery check - shows the activity's screen;
        picked again, it sets the inputs again. Off is the platform's idle activity, which
        now switches every device off."""
        if not self.devices:
            if self.project.get("activities"):
                raise ValueError("activities need devices to switch")
            return
        self.place_device_states()
        plan = activities_module.plan(self.project, self.devices, self.keypad)
        self.skipped += plan["skipped"]
        roles = self._roles()
        acts = plan["activities"]
        count = len(acts)
        if count:
            # With no activity, the idle key set answers the Activities key itself; with
            # some, Logitech's leaves it to the global one, which opens the menu.
            idle = self.contexts[roles["idle"]]
            idle["rows"] = [row for row in idle["rows"]
                            if row["key_code"] != keys.code(keys.ACTIVITIES)]
            self.place_off_menu(roles)
        state = roles["state"]
        self.variables[state].update({"initial": count, "limit": count})
        self.names = [(level, identifier,
                       f"CurrentActivityState_0_{count + 1}" if identifier == state
                       and level == 1 else name)
                      for level, identifier, name in self.names]
        # every switch table that answers for idle answers for the value idle now is
        for table in (roles["screen_table"], roles["devices_table"]):
            self.tables[table] = [(count if value == 0 else value, program)
                                  for value, program in self.tables[table]]
        set_idle = self.tables[roles["set_idle"]][0][1]
        self.programs[set_idle] = [(count, WRITE | state)]
        all_off = self.tables[roles["all_off"]][0][1]
        self.programs[all_off] = [(0, WRITE | self.power_var[index])
                                  for index in plan["all_off"]["off"]
                                  if index in self.power_var]
        devices_screen, flag = self._devices_entry()
        corner_keys = self.corner_keys()
        menu_opens = []
        self.activity_screens = []
        positions = {device.get("id"): device["index"] for device in self.devices}
        for value, act in enumerate(acts):
            # a device kept on is not switched, but an activity that lists it still writes
            # its variable, which sends nothing, as Logitech's do: it says the device is on
            listed = (self.project["activities"][value].get("power_on_devices") or [])
            steady = [positions[did] for did in listed if did in positions
                      and self.devices[positions[did]].get("always_on")
                      and positions[did] in self.power_var]
            act = dict(act, on=list(act["on"]) + [index for index in steady
                                                   if index not in act["on"]])
            # and an activity that does not list it says it is off, which sends nothing
            act["off"] = list(act["off"]) + [
                index for index in self.power_var if self.devices[index].get("always_on")
                and index not in act["on"] and index not in act["off"]]
            screen = self.place_activity_screen(act)
            self.activity_screens.append(screen)
            battery_start = self.copy_battery(roles["battery"], screen)
            battery_again = self.copy_battery(roles["battery"], screen)
            starting = self.place_starting(roles["stopping"], act["label"])
            # the enter steps in order, the inputs among them: run at the start and again
            # when the activity is chosen while it runs, as Logitech's - all but a last
            # Play or Pause, which starts the film and is not sent again
            inputs = self.new_object(self.step_atoms(act["sequence"]))
            again_steps = self.without_start_play(act["sequence"])
            again_inputs = (inputs if len(again_steps) == len(act["sequence"])
                            else self.new_object(self.step_atoms(again_steps)))
            arrive = self.new_object([BATTERY_TEST, (battery_start, SCREEN), (screen, SCREEN)])
            chain = self.new_object([CHAIN_PAUSE, (self.new_object([CHAIN_CLEAR, (arrive,
                                                                                  OBJECT)]),
                                                  OBJECT)])
            start = self.new_object(
                [(starting, SCREEN),
                 (self.new_object([(1, WRITE | self.power_var[device])
                                   for device in act["on"] if device in self.power_var]),
                  OBJECT),
                 (inputs, OBJECT),
                 *[(0, WRITE | self.power_var[device])
                   for device in act["off"] if device in self.power_var],
                 (value, WRITE | state), (chain, OBJECT)])
            again_arrive = self.new_object([BATTERY_TEST, (battery_again, SCREEN),
                                            (screen, SCREEN)])
            again = self.new_object([(again_inputs, OBJECT),
                                     (self.new_object([CHAIN_CLEAR, (again_arrive, OBJECT)]),
                                      OBJECT)])
            rows = [(START, start, OBJECT), (AGAIN, again, OBJECT)]
            leave = self.step_atoms(act["leave"])
            rows.append((LEAVE, self.new_object(leave), OBJECT) if leave else (LEAVE, 0, 0))
            rows.append((keys.code(keys.DEVICES),
                         self.new_object([(devices_screen, SCREEN), (1, WRITE | flag)]),
                         OBJECT))
            help_screen = self.place_help(act, screen)
            if help_screen is not None:
                rows.append((keys.code(keys.HELP), help_screen, SCREEN))
            elif roles["help"] is not None:
                rows.append((roles["help"]["key_code"], roles["help"]["operand"],
                             roles["help"]["category"]))
            for code, steps in sorted(act["keys"].items()):
                atoms = self.step_atoms(steps)
                if len(atoms) == 1 and atoms[0][1] == OBJECT:
                    rows.append((code, atoms[0][0], OBJECT))
                elif atoms:
                    rows.append((code, self.new_object(atoms), OBJECT))
            self.contexts.append({"form": "short", "rows": [
                {"flags": None, "key_code": code, "operand": operand, "category": category}
                for code, operand, category in rows]})
            context = len(self.contexts) - 1
            menu_opens.append(self.new_object([(SELECT_CONTEXT | context, SYSTEM),
                                               (0, WRITE | flag)]))
            # the switch tables that answer by the activity state
            self.tables[roles["key_sets"]].append(
                (value, self.add_program([(SELECT_CONTEXT | context, SYSTEM)])))
            self.tables[roles["screen_table"]].append(
                (value, self.add_program([(screen, SCREEN)])))
            self.tables[roles["devices_table"]].append(
                (value, self.add_program([(devices_screen, SCREEN)])))
        for table in (roles["key_sets"], roles["screen_table"], roles["devices_table"]):
            self.tables[table].sort()
        self.place_layouts(roles, acts)
        # Help once everything is off: whether each device is off, back to the menu
        off_help = self.place_off_help(
            [index for index in plan["all_off"]["off"] if index in self.power_var],
            (roles["menu_table"] << 8 | roles["location"], SWITCH)) if count else None
        if off_help is not None:
            idle = self.contexts[roles["idle"]]
            idle["rows"] = [dict(row, operand=off_help, category=SCREEN)
                            if row["key_code"] == keys.code(keys.HELP) else row
                            for row in idle["rows"]]
        # the Activities menu: four a page, each corner selecting its activity's key set
        menu = self.screens[roles["menu"]]
        template = menu["pages"][0]
        title = next(line["text"] for line in template["lines"] if line["y"] == 0)
        chunks = [list(range(at, min(at + CORNERS, count)))
                  for at in range(0, count, CORNERS)]
        if chunks:
            pages = []
            for number, chunk in enumerate(chunks):
                page = self.page(title, [acts[index]["label"] for index in chunk], number,
                                 len(chunks), title_align="left", words=True)
                page["keys"] = list(template["keys"]) + [
                    (corner_keys[corner], menu_opens[index], OBJECT)
                    for corner, index in enumerate(chunk)]
                pages.append(page)
            menu["pages"] = pages

    # -- Sound and Picture

    def place_layouts(self, roles: dict, acts: list[dict]) -> None:
        """The Sound and Picture keys, where the profile has them: each activity's layouts
        (activity_layouts), screens of their own as Logitech's are - "Watch TV (Sound)"
        with the layout's buttons, binding the keys the layout rebinds; every other key
        stays the activity's, its key set being underneath. The same key goes back to the
        activity's screen, the other changes layout."""
        layout_keys = self.layout_keys()
        if not layout_keys:
            return
        for value, act in enumerate(acts):
            home = self.activity_screens[value]
            made = {}
            for kind, layout in act["layouts"].items():
                title = self.words(LAYOUTS[kind][1], name=act["label"])
                made[kind] = self.place_activity_screen({"label": title,
                                                        "buttons": layout["buttons"]})
                self.screens[made[kind]]["keys"] = self.key_rows(layout["keys"])
            for kind, screen in made.items():
                self.screens[screen]["keys"] += [
                    (code, home if other == kind else made[other], SCREEN)
                    for other, code in layout_keys.items() if other == kind or other in made]
                self.screens[home]["keys"].append((layout_keys[kind], screen, SCREEN))

    def key_rows(self, bound: dict[int, list]) -> list[tuple[int, int, int]]:
        """Rows binding each key code to the steps it runs, as an activity's key set
        does."""
        rows = []
        for code, steps in sorted(bound.items()):
            atoms = self.step_atoms(steps)
            if len(atoms) == 1 and atoms[0][1] == OBJECT:
                rows.append((code, atoms[0][0], OBJECT))
            elif atoms:
                rows.append((code, self.new_object(atoms), OBJECT))
        return rows

    def layout_keys(self) -> dict[str, int]:
        """The Sound and Picture keys' codes, by layout - none unless the profile names
        both."""
        found = {kind: keys.code(self.layout_scans[name])
                 for kind, (name, _title) in LAYOUTS.items() if name in self.layout_scans}
        return found if set(found) == set(LAYOUTS) else {}

    def place_device_layouts(self) -> None:
        """On a device's own screen, Sound and Picture open that device's layouts, as
        Logitech's do: the same key goes back to the device's screen, the other key to
        its other layout. These are screens of their own, not the ones an activity shows,
        because what their keys go back to differs. Which layouts a device has goes by its
        type, or the project's list (activity_layouts.device_kinds)."""
        layout_keys = self.layout_keys()
        if not layout_keys or "device layouts" in self.left_out:
            return
        specs = self.project.get("devices") or []
        for device in self.devices:
            home = device["screen"]
            kinds = activity_layouts.device_kinds(specs[device["index"]])
            made = {kind: len(self.screens) + offset for offset, kind in enumerate(kinds)}
            for kind in kinds:
                self.layout_screen(kind, device, [
                    (code, home if other == kind else made[other], SCREEN)
                    for other, code in layout_keys.items() if other in made])
            opens = {code: (code, made[kind], SCREEN) for kind, code in layout_keys.items()
                     if kind in made}
            screen = self.screens[home]
            screen["keys"] = [opens.pop(row[0], row) for row in screen["keys"]]
            screen["keys"] += list(opens.values())

    def layout_screen(self, kind: str, lowered: dict, layout_rows: list) -> int:
        """One device's Sound or Picture layout: the device's keys, the layout keys'
        ``layout_rows``, and on the screen only its sound or picture settings
        (activity_layouts.device_layout) - none, often, as Logitech's show none."""
        title = self.words(LAYOUTS[kind][1], name=lowered["label"])
        source = self.screens[lowered["screen"]]
        header = [row for row in source["keys"] if row[2] == OBJECT] + list(layout_rows)
        spec = (self.project.get("devices") or [])[lowered["index"]]
        by_name = {command["name"]: command for command in lowered["commands"]}
        buttons = [(label, by_name[name]) for label, _device, name, *_icon
                   in activity_layouts.device_layout(spec, kind)["soft_buttons"]
                   if name in by_name and not by_name[name]["hidden"]]
        corner_keys = self.corner_keys()
        chunks = [buttons[at:at + CORNERS] for at in range(0, len(buttons), CORNERS)] or [[]]
        pages = []
        for number, chunk in enumerate(chunks):
            page = self.page(title, [label for label, _command in chunk], number,
                             len(chunks))
            page["keys"] = [(corner_keys[corner], command["object"], OBJECT)
                            for corner, (_label, command) in enumerate(chunk)]
            pages.append(page)
        self.screens.append({"flag": 0, "keys": header, "pages": pages})
        return len(self.screens) - 1

    # -- Help

    def wrap(self, text: str, lines: int = len(QUESTION_Y)) -> list[str]:
        """``text`` in lines of the screen's width, broken between words, the last cut to
        fit if there is more than ``lines`` of it; a "\\n" starts a new line. A word that
        does not fit what is left of a line fills it up to its last hyphen that fits, as
        Logitech's Help breaks one ("Is the BD-" over "Panasonic off?"), and a word wider
        than the screen breaks after a hyphen too; a soft hyphen marks where a
        translation's word may break, drawn as "-" only there. A word with neither is
        cut with ".."."""
        from .importing import join_text

        rows: list[str] = []
        for part in text.split("\n"):
            row = None
            for word in part.split():
                if row is not None and self.face.width(drawn(row + " " + word)) <= WIDTH:
                    row += " " + word
                    continue
                if row is not None:
                    head = self.break_word(word, WIDTH - self.face.width(drawn(row + " ")))
                    if head:
                        rows.append(row + " " + head[0])
                        word = head[1]
                    else:
                        rows.append(row)
                while self.face.width(drawn(word)) > WIDTH:
                    head = self.break_word(word, WIDTH)
                    if not head:
                        break
                    rows.append(head[0])
                    word = head[1]
                row = word
            if row is not None:
                rows.append(row)
        out = [self.fit(row, WIDTH) for row in rows]
        if len(out) > lines:
            out = out[:lines - 1] + [self.fit(join_text(out[lines - 1:]), WIDTH)]
        return out

    def break_word(self, word: str, room: int) -> tuple[str, str] | None:
        """``word`` broken at its last hyphen or soft hyphen whose first part fits
        ``room`` pixels: ``(drawn first part, rest)``, None if none does."""
        from .importing import broken_at_hyphen

        for at in range(len(word) - 1, 0, -1):
            if word[at] == SOFT_HYPHEN:
                head = drawn(word[:at]) + "-"
                rest = word[at + 1:]
            elif broken_at_hyphen(word[:at]):
                head, rest = drawn(word[:at]), word[at:]
            else:
                continue
            if drawn(rest) and self.face.width(head) <= room:
                return head, rest
        return None

    def question_template(self) -> dict:
        """The platform's Yes/No page: the Remote Assistant's question, its words left
        behind and its "Yes" and "No" kept."""
        if not hasattr(self, "_question"):
            for screen in self.screens:
                for page in screen["pages"]:
                    answers = [line for line in page["lines"] if line["attribute"] == SOFTKEY]
                    if sorted(line["text"] for line in answers) == sorted(
                            self.words.text(key) for key in ("answer.no", "answer.yes")):
                        self._question = dict(page, lines=answers, keys=[])
                        break
                if hasattr(self, "_question"):
                    break
            else:
                raise ValueError("the platform has no Yes/No page")
        return self._question

    def question(self, text: str, yes, no, home, shown=None) -> int:
        """A Yes/No screen: ``yes`` and ``no`` each a screen, an instruction
        (``(operand, category)``) or atoms to run, Help back to ``home`` (a screen or an
        instruction), ``shown`` run as it appears."""
        template = self.question_template()
        lines = [{"attribute": ASSISTANT, "x": 0, "y": y, "align": "centre", "text": line}
                 for y, line in zip(QUESTION_Y, self.wrap(text))]
        page = dict(template, lines=lines + [dict(line) for line in template["lines"]],
                    keys=[self._answer(YES_KEY, yes), self._answer(NO_KEY, no)])
        header = [self._answer(keys.code(keys.HELP), home)]
        if shown:
            header.append((SHOWN, self.new_object(shown), OBJECT))
        self.screens.append({"flag": 0, "keys": header, "pages": [page]})
        return len(self.screens) - 1

    def _answer(self, code: int, target) -> tuple[int, int, int]:
        if target is None:
            return (code, 0, 0)
        if isinstance(target, int):
            return (code, target, SCREEN)
        if isinstance(target, tuple):
            return (code, *target)
        return (code, self.new_object(target), OBJECT)

    def is_toggle(self, device: int) -> bool:
        power = self.devices[device].get("power") or {}
        return power.get("on") is not None and power.get("on") == power.get("off")

    def help_chain(self, questions: list, home, shown) -> int:
        """Logitech's Remote Assistant over ``questions`` - ``(fill, resend, ask, again)``
        each: "Did that fix the problem?" first, ``shown`` sent as it appears; No walks
        the questions one at a time, Yes going on to the next; No on one sends it again
        and asks ``again`` ("Now is..."), whose Yes asks whether that fixed it and whose
        No sends it once more and asks the question again. The last question's Yes and
        every "fixed" Yes go back to ``home``."""
        after = home
        # built from the last question back, so each knows the one after it
        for fill, resend, ask, again in reversed(questions):
            fixed = self.question(self.words("help.fixed"), home, after, home)
            now = self.question(self.words(again, **fill), fixed, None, home)
            retry = (now if "help retries" in self.left_out else
                     self.question(self.words(ask, **fill), fixed, resend + [(now, SCREEN)],
                                   home))
            self.screens[now]["pages"][0]["keys"][1] = self._answer(
                NO_KEY, resend + [(retry, SCREEN)])
            after = self.question(self.words(ask, **fill), after, resend + [(now, SCREEN)],
                                  home)
        return self.question(self.words("help.fixed"), home, after, home, shown=shown)

    def input_questions(self, device: int, value: int) -> list:
        """What Help asks about a device set to input ``value``: the input itself, when
        choosing it sends codes, and each other state it sets - "Is the TV Screen set
        to HDMI2?" - with what sets that state again."""
        lowered = self.devices[device]
        inputs = lowered.get("inputs") or {}
        if not inputs.get("direct") or device not in self.input_var:
            return []
        selection = inputs["direct"][value]
        out = []
        atoms = self.selection_atoms(device, selection)
        if atoms:
            out.append(({"device": lowered["label"], "input": inputs["values"][value]},
                        atoms, IS_SET, NOW_SET))
        states = {state["id"]: state for state in lowered.get("states") or []}
        for step in selection if isinstance(selection, list) else ():
            if step[0] != "set" or step[1] not in states:
                continue
            state = states[step[1]]
            if "select" in state:
                resend = self.selection_atoms(device, state["select"].get(step[2]))
            else:
                resend = self.selection_atoms(device, state.get("next"))
            names = state.get("values") or []
            if resend:
                out.append(({"device": lowered["label"], "state": state["id"],
                             "value": names[step[2]] if step[2] < len(names)
                             else str(step[2])}, resend, IS_STATE, NOW_STATE))
        return out

    def place_help(self, act: dict, home: int) -> int | None:
        """The activity's Help, as Logitech's 555 asks it: shown, it sends each device's
        power - not a toggle, which would switch it off - and inputs again and asks
        whether that fixed the problem; No walks through them one at a time - is the
        device on, is it set to its input, is its Screen set to HDMI2 - (help_chain).
        Yes anywhere returns to the activity's screen, as Help does."""
        questions, shown = [], []
        for device in act["on"]:
            power = self.devices[device].get("power")
            # a device kept on too: its power is sent here only, as Logitech's
            if power:
                send = [(self.command_object(device, power["on"]), OBJECT)]
                questions.append(({"device": self.devices[device]["label"]}, send,
                                  IS_ON, NOW_ON))
                if not self.is_toggle(device):
                    shown += send
        for device, value in act["inputs"]:
            asked = self.input_questions(device, value)
            questions += asked
            shown += [atom for _fill, resend, _ask, _again in asked for atom in resend]
        if not questions:
            return None
        return self.help_chain(questions, home, shown)

    def place_off_help(self, off: list[int], home) -> int | None:
        """Help once everything is off, as Logitech's households ask it: shown, it sends
        each device's off code again - not a toggle's, which would switch it on - and
        asks whether that fixed the problem; No asks of each device whether it is off
        (help_chain). Yes goes back to ``home``, the Activities menu."""
        questions, shown = [], []
        for device in off:
            power = self.devices[device].get("power")
            if not power:
                continue
            send = ([(self.command_object(device, command), OBJECT)
                     for command in power["off_steps"]] if power.get("off_steps")
                    else [(self.command_object(device, power["off"]), OBJECT)])
            questions.append(({"device": self.devices[device]["label"]}, send,
                              IS_OFF, NOW_OFF))
            if not self.is_toggle(device):
                shown += send
        if not questions:
            return None
        return self.help_chain(questions, home, shown)

    def add_program(self, atoms) -> int:
        self.programs.append([tuple(atom) for atom in atoms])
        return len(self.programs) - 1

    def place_activity_screen(self, act: dict) -> int:
        """The activity's own screen: its buttons four a page under its name, a place
        left empty kept empty."""
        corner_keys = self.corner_keys()
        buttons = act["buttons"]
        chunks = [buttons[at:at + CORNERS] for at in range(0, len(buttons), CORNERS)] or [[]]
        pages = []
        for number, chunk in enumerate(chunks):
            page = self.page(act["label"], [button and button[0] for button in chunk],
                             number, len(chunks))
            for corner, button in enumerate(chunk):
                if button is None:
                    continue
                atoms = self.step_atoms(button[1])
                if len(atoms) == 1 and atoms[0][1] == OBJECT:
                    page["keys"].append((corner_keys[corner], atoms[0][0], OBJECT))
                elif atoms:
                    page["keys"].append((corner_keys[corner], self.new_object(atoms), OBJECT))
            pages.append(page)
        self.screens.append({"flag": 0, "keys": [], "pages": pages})
        return len(self.screens) - 1

    def place_off_menu(self, roles: dict) -> None:
        """Once everything is off, the Activities menu, as Logitech's households have it,
        where the empty platform goes on into its welcome tour ("Welcome to your
        remote."): Off's chains - pressed, and pressed again - end at the battery check,
        its own copy of the warning and then the menu, and the start-up list opens the
        menu where it began the tour (docs/harmony_5xx/ahcm.md, "Activities")."""
        menu_switch = (roles["menu_table"] << 8 | roles["location"], SWITCH)
        tours = set()
        for key in (START, AGAIN):
            row = roles["rows"].get(key)
            if row is None or row["category"] != OBJECT:
                continue
            check = self._battery_check(row["operand"])
            if check is None:
                continue
            tours |= {operand for operand, category in self.objects[check][2:]
                      if category == OBJECT}
            self.objects[check] = [
                BATTERY_TEST, (self.copy_battery(roles["battery"], menu_switch), SCREEN),
                menu_switch]
        for operand, category in self.lead:
            if category == OBJECT:
                self.objects[operand] = [menu_switch if category_ == OBJECT and
                                         operand_ in tours else (operand_, category_)
                                         for operand_, category_ in self.objects[operand]]

    def _battery_check(self, start: int) -> int | None:
        """The object a chain from ``start`` ends its battery check in."""
        seen, todo = set(), [start]
        while todo:
            index = todo.pop(0)
            if index in seen or not 0 <= index < len(self.objects):
                continue
            seen.add(index)
            atoms = self.objects[index]
            if atoms and atoms[0] == BATTERY_TEST:
                return index
            todo += [operand for operand, category in atoms if category == OBJECT]
        return None

    def copy_battery(self, battery: int, then) -> int:
        """A copy of the battery warning whose keys go on to ``then`` - a screen, or an
        atom - one per chain, as Logitech's, since what its keys lead to is where the
        chain was going."""
        source = self.screens[battery]
        then = (then, SCREEN) if isinstance(then, int) else tuple(then)
        rows = [(code, *then) if category == OBJECT else (code, operand, category)
                for code, operand, category in source["keys"]]
        self.screens.append({"flag": source["flag"], "keys": rows,
                             "pages": [dict(page) for page in source["pages"]]})
        return len(self.screens) - 1

    def place_starting(self, stopping: int, label: str) -> int:
        """"Starting" over the activity's name, then the platform's "Stopping Activity"
        screen's request to keep the remote pointed, every key held off as there."""
        source = self.screens[stopping]
        page = source["pages"][0]
        # "Stopping Activity" - in a language that takes two lines for it, both
        stopped = next((block for key, block in self.blocks.get((stopping, 0), ())
                        if key == "off.stopping"), None)
        if stopped is None:
            heading = min(line["y"] for line in page["lines"])
            stopped = [line for line in page["lines"] if line["y"] == heading]
        heading = max(LINE, stopped[0]["y"])
        lines = [{"attribute": NOTICE, "x": 0, "y": heading - LINE, "align": "centre",
                  "text": self.fit(self.words("activity.starting"), WIDTH)},
                 {"attribute": NOTICE, "x": 0, "y": heading, "align": "centre",
                  "text": self.fit(label, WIDTH)}]
        lines += [line for line in page["lines"] if line not in stopped]
        self.screens.append({"flag": source["flag"], "keys": list(source["keys"]),
                             "pages": [dict(page, lines=lines)]})
        return len(self.screens) - 1

    # -- infrared

    def place_infrared(self, pieces: Pieces) -> None:
        """Each device's commands as class-5 records, their bodies spelled from the
        device's own symbol tables, and its sub-table in section 5."""
        self.spelled = {}
        for device in self.devices:
            dictionary = infrared.Dictionary()
            for command in device["commands"]:
                sets = [("", command["phases"])]
                if command.get("alternate_phases"):
                    sets.append(("other:", command["alternate_phases"]))
                for prefix, phases in sets:
                    for phase, waveform in phases.items():
                        self.spelled[(command["command_id"], prefix + phase)] = \
                            dictionary.spell(waveform)
            for table, symbols in enumerate(dictionary.tables):
                for index, words in enumerate(symbols):
                    pieces.add(f"symbol:{device['index']}:{table}:{index}",
                               _constant(infrared.symbol(words)))
                pieces.add(f"symbols:{device['index']}:{table}",
                           self._symbol_table(device["index"], table, len(symbols)))
            for command in device["commands"]:
                for key in [key for key in self.spelled if key[0] == command["command_id"]]:
                    pieces.add(f"body:{key[0]}:{key[1]}", self._body(device["index"], key))
                pieces.add(f"record:{command['command_id']}", self._record(command))
            pieces.add(f"commands:{device['index']}", self._commands(device))

    def _symbol_table(self, device: int, table: int, count: int):
        return lambda p: infrared.table([p.address(f"symbol:{device}:{table}:{index}")
                                         for index in range(count)])

    def _body(self, device: int, key):
        table, indexes = self.spelled[key]
        return lambda p: infrared.body(p.address(f"symbols:{device}:{table}"), indexes)

    def _record(self, command: dict):
        identifier = command["command_id"]

        def produce(p: Pieces) -> bytes:
            def at(phase, prefix=""):
                name = f"body:{identifier}:{prefix}{phase}"
                return p.offset(name) if (identifier, prefix + phase) in self.spelled \
                    else None
            alternate = None
            if command.get("alternate_phases"):
                alternate = (at("press", "other:"), at("hold", "other:"),
                             at("release", "other:"))
            return infrared.classed(records.command_record(
                p.offset(f"record:{identifier}"), at("press"), at("hold"),
                command["carrier_period_ns"], command["carrier_half_period_ns"],
                release_offset=at("release"), alternate=alternate))
        return produce

    def _commands(self, device: dict):
        """A device's sub-table: a zero, the count, each record's address plus eleven."""
        def produce(p: Pieces) -> bytes:
            out = bytearray(b"\x00") + struct.pack("<H", len(device["commands"]))
            for command in device["commands"]:
                out += (p.address(f"record:{command['command_id']}") + 11).to_bytes(3, "little")
            return bytes(out)
        return produce

    def _section5(self, p: Pieces) -> bytes:
        return bytes([len(self.devices)]) + b"".join(
            p.pointer(f"commands:{device['index']}") for device in self.devices)

    def lay_out(self) -> bytes:
        pieces = Pieces(self.header)
        self.pieces = pieces
        self._plan_section9()
        placed = [[self.lines(page) for page in screen["pages"]] for screen in self.screens]
        self.codes = self._codes(placed)
        for grid in sorted({_grid(attribute) for attribute in self.codes}):
            characters = sorted({c for attribute, table in self.codes.items()
                                 if _grid(attribute) == grid for c in table})
            for character in characters:
                pieces.add(f"glyph:{grid[0]}:{ord(character)}",
                           _constant(self.face.body(character, *grid)))
        self.place_infrared(pieces)
        for ordinal, screen in enumerate(self.screens):
            for page, lines in enumerate(placed[ordinal]):
                pieces.add(f"page:{ordinal}:{page}",
                           self._page(screen["pages"][page], lines))
                pieces.add(f"keys:{ordinal}:{page}",
                           _constant(_register(screen["pages"][page]["keys"])))
            pieces.add(f"header:{ordinal}", _constant(_register(screen["keys"])))
            pieces.add(f"trailer:{ordinal}", self._trailer(ordinal, screen))
        for index, atoms in enumerate(self.objects):
            pieces.add(f"object:{index}", _constant(object_body(atoms)))
        for index, context in enumerate(self.contexts):
            pieces.add(f"context:{index}", _constant(context_record(context)))
        for index, atoms in enumerate(self.programs):
            pieces.add(f"program:{index}", _constant(_atoms_program(atoms)))
        for index, cases in enumerate(self.tables):
            pieces.add(f"table:{index}", self._table(cases))
        for index, timer in enumerate(self.timers):
            pieces.add(f"timer:{index}", _constant(timer_record(*timer)))
        for index, record in enumerate(self.variables):
            pieces.add(f"variable:{index}", _constant(engine_record(
                {**record, "padding": 0})))
        for attribute in sorted(self.codes):
            pieces.add(f"font:{attribute}", self._font(attribute))
        sections = {
            0: _constant(self._names()),
            1: _constant(self._section1()),
            2: _constant(bytes.fromhex(self.wiring["section2"])),
            3: _constant(stamp(*self.stamp_fields)),
            4: _constant(bytes.fromhex(self.wiring["section4"])),
            5: self._section5,
            6: lambda p: (struct.pack("<H", len(self.screens)) + b"\x00" + b"".join(
                p.pointer(f"trailer:{ordinal}") for ordinal in range(len(self.screens)))),
            7: self._index("font", len(self.codes), 2),
            9: self._section9,
            10: self._index("context", len(self.contexts), 1),
            11: self._index("object", len(self.objects), 2),
            12: self._index("program", len(self.programs), 2),
            13: self._index("timer", len(self.timers), 1),
            14: self._engine,
            15: self._section15,
            16: self._section16,
            17: _constant(bytes.fromhex(self.wiring["section17"])),
            19: _constant(b"\x00\x00"),
        }
        for index in sorted(sections):
            pieces.add(f"section:{index}", sections[index], window=False)
        for role in sorted(self.drawn_pictures()):
            pieces.add(f"picture:{role}", _constant(self.pictures[role]), window=False)
        out = pieces.lay_out()
        image = gspm.seal(bytes(out))
        if len(image) >= gspm.MAX_SAFE_SIZE:
            raise TooLarge(f"the configuration is {len(image):,} bytes; a 5xx holds "
                           f"{gspm.MAX_SAFE_SIZE - 1:,}")
        gspm.validate(image)
        return image

    def drawn_pictures(self) -> set[str]:
        out = set()
        for screen in self.screens:
            for page in screen["pages"]:
                out.add(page["backdrop"])
                out.update(overlay["picture"] for overlay in page["overlays"])
        return out

    def header(self, p: Pieces) -> bytes:
        out = bytearray(gspm.MAGIC + bytes(4)) + bytes([0, gspm.TABLE_ITEMS, 0])
        for section in gspm.SLOT_SECTIONS:
            out += b"\x00" + (p.pointer(f"section:{section}") if p.final else bytes(3))
        out += bytes(gspm.BUTTON_MAP_OFFSET - len(out)) + gspm.BUTTON_MAP_MAGIC + b"\x00"
        return bytes(out)

    def _codes(self, placed) -> dict[int, dict[str, int]]:
        """Each font attribute's characters and their codes: the characters its lines
        draw, numbered from 1 in code-point order. Four fonts as the scaffold's frame
        draws them, even one with nothing to draw."""
        used: dict[int, set[str]] = {attribute: set() for attribute in range(COUNTER)}
        for screen in placed:
            for lines in screen:
                for line in lines:
                    used.setdefault(line["attribute"], set()).update(line["text"])
        out = {}
        for attribute, characters in sorted(used.items()):
            missing = sorted(c for c in characters if not self.face.has(c))
            if missing:
                raise ValueError(f"the typeface cannot draw {''.join(missing)!r}")
            out[attribute] = {c: code for code, c in enumerate(sorted(characters), 1)}
        return out

    def _font(self, attribute: int):
        table = self.codes[attribute]

        def produce(p: Pieces) -> bytes:
            by_code = {code: character for character, code in table.items()}
            count = len(by_code)
            height = _grid(attribute)[0]
            out = bytearray([height, 1, count])
            for code in range(1, count + 1):
                out += p.pointer(f"glyph:{height}:{ord(by_code[code])}")
            return bytes(out)
        return produce

    def _page(self, page: dict, lines: list[dict]):
        """Logitech's page shape: each band selected, its slice of the backdrop, the text
        that reaches into it, the pictures over it, sent."""
        def produce(p: Pieces) -> bytes:
            items = []
            attribute = None
            for band in range(BANDS):
                top, bottom = band * BAND, band * BAND + BAND
                items.append({"opcode": "row", "value": band})
                items.append({"opcode": "sized_bitmap", "x": 0, "y": top,
                              "reserved": bytes([0, top]).hex(), "width": WIDTH,
                              "height": BAND,
                              "target": p.offset(f"picture:{page['backdrop']}")})
                for line in lines:
                    if line["y"] < bottom and line["y"] + typeface.SLOT_HEIGHT > top:
                        if line["attribute"] != attribute:
                            attribute = line["attribute"]
                            items.append({"opcode": "attribute", "value": attribute})
                        codes = drawing.GlyphCodes.of(
                            self.codes[attribute][c] for c in line["text"])
                        items.append({"opcode": "inline_text", "x": line["x"],
                                      "y": line["y"], "glyphs": codes.hex()})
                for overlay in page["overlays"]:
                    if overlay["y"] < bottom and overlay["y"] + overlay["height"] > top:
                        items.append({"opcode": "sized_bitmap", "x": overlay["x"],
                                      "y": overlay["y"],
                                      "reserved": bytes([overlay["sx"], overlay["sy"]]).hex(),
                                      "width": overlay["width"], "height": overlay["height"],
                                      "target": p.offset(f"picture:{overlay['picture']}")})
                items.append({"opcode": "transfer"})
            items.append({"opcode": "end"})
            return drawing.encode_program(items)
        return produce

    def _plan_section9(self) -> None:
        """Where each page's slot sits in section 9: after the start-up list, six bytes a
        page in screen order."""
        self.slot_at, cursor = {}, len(object_body(self.lead))
        for ordinal, screen in enumerate(self.screens):
            for page in range(len(screen["pages"])):
                self.slot_at[(ordinal, page)] = cursor
                cursor += 6

    def _trailer(self, ordinal: int, screen: dict):
        def produce(p: Pieces) -> bytes:
            out = bytearray([screen["flag"]]) + p.pointer(f"header:{ordinal}")
            out += struct.pack("<H", len(screen["pages"]))
            for page in range(len(screen["pages"])):
                out += (gspm.BASE + p.offset("section:9") + self.slot_at[(ordinal, page)]
                        ).to_bytes(3, "little")
            return bytes(out)
        return produce

    def _section9(self, p: Pieces) -> bytes:
        """The start-up list, then every page's six-byte slot: its key list and its
        program."""
        out = bytearray(object_body(self.lead))
        for ordinal, screen in enumerate(self.screens):
            for page in range(len(screen["pages"])):
                if self.slot_at[(ordinal, page)] != len(out):
                    raise ValueError("section 9's slots moved")
                out += p.pointer(f"keys:{ordinal}:{page}") + p.pointer(f"page:{ordinal}:{page}")
        return bytes(out)

    def _index(self, kind: str, count: int, width: int):
        def produce(p: Pieces) -> bytes:
            return count.to_bytes(width, "little") + b"".join(
                p.pointer(f"{kind}:{index}") for index in range(count))
        return produce

    def _engine(self, p: Pieces) -> bytes:
        count = len(self.variables)
        wide = sum(1 for record in self.variables if record["limit"] > WIDE)
        narrow = count - wide
        if any(record["limit"] > WIDE for record in self.variables[:narrow]):
            raise ValueError("a wide variable stands among the narrow ones")
        return (struct.pack("<HHHH", count, narrow, wide, narrow)
                + b"".join(p.pointer(f"variable:{index}") for index in range(count)))

    def _table(self, cases):
        def produce(p: Pieces) -> bytes:
            out = bytearray([2, len(cases)])
            for value, program in cases:
                out += struct.pack("<H", value) + p.pointer(f"program:{program}")
            return bytes(out + b"\x00")
        return produce

    def _section15(self, p: Pieces) -> bytes:
        return (bytes([len(self.tables)])
                + b"".join(p.pointer(f"table:{index}") for index in range(len(self.tables)))
                + bytes.fromhex(self.wiring["section15_tail"]))

    def _section16(self, p: Pieces) -> bytes:
        tail = p.offset("section:15") + 1 + 3 * len(self.tables)
        offsets = self.wiring["section16"]
        return bytes([len(offsets)]) + b"".join(
            (gspm.BASE + tail + offset).to_bytes(3, "little") for offset in offsets)

    def _section1(self) -> bytes:
        out = bytearray.fromhex(self.wiring["section1"])
        if self.skin is not None:
            out[SKIN_AT] = self.skin
        return bytes(out)

    def _names(self) -> bytes:
        records = []
        for level, identifier, name in self.names:
            encoded = name.encode("utf-8")
            records.append(b"\xa7" + (4 + len(encoded)).to_bytes(2, "little")
                           + level.to_bytes(2, "little") + identifier.to_bytes(2, "little")
                           + encoded)
        return name_chain(records)


def _transition(source: int, target: int, operand: int, category: int) -> dict:
    return {"flags": 0, "from": source, "to": target, "operand": operand,
            "category": category}


def _grid(attribute: int) -> tuple[int, int]:
    """The glyph grid a font attribute draws on: eleven rows, the counter's eight."""
    if attribute == COUNTER:
        return typeface.COUNTER_HEIGHT, typeface.COUNTER_BASELINE
    return typeface.SLOT_HEIGHT, typeface.BASELINE


def _screen(screen: dict) -> dict:
    return {"flag": screen["flag"], "keys": [tuple(row) for row in screen["keys"]],
            "pages": [dict(page, keys=[tuple(row) for row in page["keys"]])
                      for page in screen["pages"]]}


def _register(rows) -> bytes:
    from .structures import key_register
    return key_register(list(rows))


def _constant(body: bytes):
    return lambda _p: body


def _atoms_program(atoms) -> bytes:
    return drawing.encode_program(
        [{"opcode": "atom", "operand": operand, "category": category}
         for operand, category in atoms] + [{"opcode": "end"}])


def build_stamp(now=None) -> tuple:
    """The time a build is made, as section 3 and the clock's variables hold it: second,
    minute, hour, day and month from zero, and the year."""
    import datetime

    now = now or datetime.datetime.now()
    return (now.second, now.minute, now.hour, now.day - 1, now.month - 1, now.year)


def build(project: dict, *, directory=None, stamp_fields=None, words=None,
          theme=None) -> bytes:
    from ... import paths

    directory = Path(directory or paths.scaffolds("harmony-555"))
    stamp_fields = stamp_fields or (0, 0, 0, 0, 0, 2026)
    return build_fitting(project, directory, stamp_fields, words, theme)[1]


def build_fitting(project: dict, directory, stamp_fields, words=None, theme=None) -> tuple:
    """The image, and its bytes, with as much as fits: built whole, then leaving out
    Afterglow's extras in turn (LEAN) - each said in the image's ``skipped`` notes. The
    pictures and typeface are `theme`'s (a folder) where it has them."""
    for left_out in LEAN:
        image = Image(project, Path(directory), stamp_fields, words, theme)
        image.left_out = set(left_out)
        try:
            payload = image.build()
        except TooLarge as error:
            last = error
            continue
        image.skipped += [LEFT_OUT_NOTES[name] for name in left_out]
        return image, payload
    raise last
