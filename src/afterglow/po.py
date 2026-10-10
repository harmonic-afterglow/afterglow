"""Read gettext `.po` catalogues and write `.pot` templates, with the standard library.

Text a remote draws is translated the way most software is: a template (`.pot`) lists
every message with a context and a note for the translator, and a catalogue per language
(`<lang>.po`) answers them, so the usual tools - Poedit, Weblate, Crowdin - work on it.
Python's own `gettext` only reads compiled `.mo` files, and a build must run on a bare
Python with nothing compiled first, so this reads `.po` directly: contexts, plural forms,
multi-line strings and escapes. A fuzzy or obsolete entry is not a translation and is
skipped, so the English stands until someone confirms it.

Nothing here knows about any remote; a backend names its messages and their contexts.
"""
from __future__ import annotations

import gettext
from dataclasses import dataclass, field

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        raise ValueError(f"not a quoted .po string: {text!r}")
    out, body, at = [], text[1:-1], 0
    while at < len(body):
        char = body[at]
        if char == "\\" and at + 1 < len(body):
            out.append(_ESCAPES.get(body[at + 1], body[at + 1]))
            at += 2
            continue
        out.append(char)
        at += 1
    return "".join(out)


def _quote(text: str) -> str:
    escaped = (text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
               .replace("\t", "\\t"))
    return f'"{escaped}"'


@dataclass
class Catalogue:
    """A language's answers: ``(context, message) -> [forms]``, and its plural rule."""
    messages: dict = field(default_factory=dict)
    header: dict = field(default_factory=dict)
    plural: object = None          # n -> index into the forms

    def get(self, context: str | None, message: str, n: int | None = None) -> str | None:
        forms = self.messages.get((context, message))
        if not forms or not any(forms):
            return None
        if n is None or len(forms) == 1:
            return forms[0] or None
        index = self.plural(n) if self.plural else (0 if n == 1 else 1)
        return forms[index] if index < len(forms) and forms[index] else None


def parse(text: str) -> Catalogue:
    """A `.po` file's translations, fuzzy and obsolete entries left out."""
    entries, current, last = [], None, None

    def finish():
        if current is not None:
            entries.append(current)

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            finish()
            current, last = None, None
            continue
        if current is None:
            current = {"flags": set(), "obsolete": False}
        if line.startswith("#~"):
            current["obsolete"] = True
            continue
        if line.startswith("#,"):
            current["flags"].update(flag.strip() for flag in line[2:].split(","))
            continue
        if line.startswith("#"):
            continue
        keyword, _space, rest = line.partition(" ")
        try:
            if line.startswith('"'):
                if last is None:
                    raise ValueError("a continued string with nothing to continue")
                current[last] += _unquote(line)
            elif keyword in ("msgctxt", "msgid", "msgid_plural") or keyword.startswith("msgstr"):
                last = keyword
                current[keyword] = _unquote(rest)
            else:
                raise ValueError(f"unknown keyword {keyword!r}")
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from exc
    finish()

    catalogue = Catalogue()
    for entry in entries:
        if "msgid" not in entry or entry["obsolete"]:
            continue
        if entry["msgid"] == "" and "msgctxt" not in entry:
            for line in entry.get("msgstr", "").splitlines():
                name, _colon, value = line.partition(":")
                catalogue.header[name.strip()] = value.strip()
            continue
        if "fuzzy" in entry["flags"]:
            continue
        if "msgid_plural" in entry:
            forms, index = [], 0
            while f"msgstr[{index}]" in entry:
                forms.append(entry[f"msgstr[{index}]"])
                index += 1
        else:
            forms = [entry.get("msgstr", "")]
        catalogue.messages[(entry.get("msgctxt"), entry["msgid"])] = forms
    rule = catalogue.header.get("Plural-Forms", "")
    if "plural=" in rule:
        expression = rule.split("plural=", 1)[1].strip().rstrip(";")
        try:
            catalogue.plural = gettext.c2py(expression)
        except ValueError:        # a template's placeholder, or a rule not yet written
            catalogue.plural = None
    return catalogue


@dataclass
class Message:
    """One message of a template."""
    context: str
    text: str
    comment: str = ""
    plural: str | None = None
    brace_format: bool = False


def template(messages: list[Message], project: str, answers=None,
             language: str | None = None) -> str:
    """A `.pot` template for ``messages``, in the order given - or, with ``answers``
    (``message -> [forms]``) and a ``language``, that language's `.po` catalogue."""
    plural_rule = ("nplurals=INTEGER; plural=EXPRESSION;" if language is None
                   else "nplurals=2; plural=(n != 1);")
    lines = [
        '# Translations for ' + project + '.',
        'msgid ""',
        'msgstr ""',
        _quote(f"Project-Id-Version: {project}\n"),
        *([_quote(f"Language: {language}\n")] if language else []),
        _quote("Content-Type: text/plain; charset=UTF-8\n"),
        _quote("Content-Transfer-Encoding: 8bit\n"),
        _quote(f"Plural-Forms: {plural_rule}\n"),
        "",
    ]
    for message in messages:
        for line in message.comment.splitlines():
            lines.append(f"#. {line}".rstrip())
        if message.brace_format:
            lines.append("#, python-brace-format")
        lines.append(f"msgctxt {_quote(message.context)}")
        lines.append(f"msgid {_quote(message.text)}")
        forms = answers(message) if answers else None
        if message.plural is not None:
            lines.append(f"msgid_plural {_quote(message.plural)}")
            for index in range(2):
                lines.append(f"msgstr[{index}] {_quote(forms[index] if forms else '')}")
        else:
            lines.append(f"msgstr {_quote(forms[0] if forms else '')}")
        lines.append("")
    return "\n".join(lines)
