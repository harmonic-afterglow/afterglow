"""An input's own name, read back from the remote's Help.

A 650's, 700's, One's or 800's image keeps only how many inputs a device has and how each
is chosen, so an import called them "Input 1", "Input 2" - and a tester's remote, built
from it, asked "Is the TV set to the Input 8 input?" where Logitech's had said "HDMI 3".
The names are still in the image: each activity's Help asks about every input the
activity sets, "Is the Soniq TV set to the HDMI 3 input?" (or, on a German One, "Ist
fuer 3D TV der Eingang HDMI 1 gewaehlt?"). Following an activity's Help from its Help key,
along the answers, finds its questions; the input the activity sets on that device is
the one asked about.

Only an input known by its number takes the name: one named after its command
("InputHdmi1") keeps it. A language whose question is not listed, or an input no
activity uses, keeps its number.
"""
from __future__ import annotations

import re

# Logitech's own wordings, where a remote's language words it otherwise than this
# backend's translation: a French and a Dutch One
LOGITECH = (
    "Le/la {device} est-il/elle r\u00e9gl\u00e9(e) sur l'entr\u00e9e {input}?",
    "Le/la {device} est-il/elle maintenant r\u00e9gl\u00e9(e) sur l'entr\u00e9e {input}?",
    "Is uw {device} ingesteld op ingang {input}?",
    "Is uw {device} nu ingesteld op ingang {input}?",
)

# a name an import gives an input it knows only by its number
NUMBERED = re.compile(r"Input \d+")

SEND, WRITE, MODE = "send", "write", "mode"


def _loose(word: str) -> str:
    """A word as an image's text reads it back: a letter its font has no glyph for (an
    accent) as any one character, and "l" as "I" too - the same glyph in Logitech's
    fonts."""
    out = []
    for char in word:
        if not char.isascii():
            out.append(".")
        elif char in "lI":
            out.append("[lI]")
        else:
            out.append(re.escape(char))
    return "".join(out)


def question(template: str) -> re.Pattern:
    """A Help question's wording with ``{device}`` and ``{input}`` as a pattern."""
    parts = re.split(r"(\{device\}|\{input\})", template)
    out = []
    for part in parts:
        if part == "{device}":
            out.append(r"(?P<device>.+?)")
        elif part == "{input}":
            out.append(r"(?P<input>.+?)")
        else:
            out.append(r"\s*".join(_loose(word) for word in part.split()))
            if part[:1].isspace():
                out.insert(-1, r"\s*")
            if part[-1:].isspace():
                out.append(r"\s*")
    return re.compile("".join(out), re.IGNORECASE)


def questions(locale_dir, contexts, english) -> list[re.Pattern]:
    """The Help questions about an input, in English and every language a backend's
    ``locale_dir`` translates them into (``contexts``, the messages' contexts)."""
    from pathlib import Path
    from .. import po
    wordings = list(english) + list(LOGITECH)
    for path in sorted(Path(locale_dir).glob("*.po")):
        catalogue = po.parse(path.read_text(encoding="utf-8"))
        for (context, _message), forms in catalogue.messages.items():
            if context in contexts:
                wordings += [form for form in forms if form]
    return [question(wording) for wording in dict.fromkeys(wordings)]


def _same(label: str, asked: str) -> bool:
    """A device's name as Help wrote it, broken over lines ("AV-Receiver- Wohnzimmer")."""
    return "".join(label.split()).casefold() == "".join(asked.split()).casefold()


def read(reader, *, enter: int, help_key: int, entered: int, answers, questions) -> dict:
    """``{(device index, input value): name}`` from each activity's Help.

    ``reader`` is a backend's Activities reader: ``starts()``, ``hooks(context)``,
    ``contexts``, ``variables`` ({property: (device index, kind)}), ``devices`` and
    ``image`` (``screens``, ``page_text``, ``row``)."""
    image = reader.image
    screens = image.screens

    def bound(ordinal, where):
        screen = screens[ordinal]
        entries = (screen["slots"][0]["entries"] if where == "soft"
                   else screen["header_entries"])
        return {entry["key_code"]: image.row(entry) for entry in entries
                if entry["category"]}

    named: dict[tuple[int, int], str] = {}
    for ordinal in reader.starts():
        hooks = reader.hooks(reader.contexts[ordinal])
        # the input the activity sets on each device
        values = {reader.variables[step[1]][0]: step[2]
                  for step in hooks.get(enter, [])
                  if step[0] == WRITE and step[1] in reader.variables
                  and reader.variables[step[1]][1] == "input"}
        if not values:
            continue
        start = [step[1] for step in hooks.get(help_key, []) if step[0] == MODE]
        queue, seen = list(start), set()
        while queue and len(seen) < 400:
            screen = queue.pop()
            if screen in seen or not 0 <= screen < len(screens) \
                    or not screens[screen]["slots"]:
                continue
            seen.add(screen)
            soft = bound(screen, "soft")
            text = " ".join(" ".join(item["text"] for slot in screens[screen]["slots"]
                                     for item in image.page_text(slot["program_offset"]))
                            .split())
            for pattern in questions:
                for match in pattern.finditer(text):
                    for device, value in values.items():
                        label = reader.devices[device].get("label") or ""
                        if label and _same(label, match["device"]):
                            named.setdefault((device, value), match["input"].strip())
            # on along the answers only: a screen with other keys (the activity's own,
            # where Help ends) is not followed into, but the first ones Help opens are
            if screen in start or set(soft) <= set(answers):
                rows = list(soft.values()) + [bound(screen, "header").get(entered, [])]
                queue += [step[1] for row in rows for step in row if step[0] == MODE]
    return named


def _capital_i(name: str) -> str:
    """"HDMl 2" as "HDMI 2": Logitech's fonts draw "l" and "I" alike, and an "l" after a
    capital, where a word in capitals goes on or ends, is an "I"."""
    return re.sub(r"(?<=[A-Z])l(?=[A-Z0-9]|\b)", "I", name)


def apply(devices: list[dict], named: dict) -> None:
    """Give each input known only by its number the name Help gives it - in the
    device's inputs (and its app inputs) or its input cycle."""
    for (device, value), name in named.items():
        name = _capital_i(name)
        spec = devices[device]
        inputs = spec.get("inputs") or []
        cycle = (spec.get("input_cycle") or {}).get("values") or []
        # a name another of its inputs has already is no name for this one
        if name in [item[0] for item in inputs] + list(cycle):
            continue
        if 0 <= value < len(inputs) and NUMBERED.fullmatch(inputs[value][0]):
            old = inputs[value][0]
            inputs[value][0] = name
            if old in (spec.get("online_inputs") or []):
                spec["online_inputs"] = [name if item == old else item
                                         for item in spec["online_inputs"]]
        elif 0 <= value < len(cycle) and NUMBERED.fullmatch(cycle[value]):
            cycle[value] = name
