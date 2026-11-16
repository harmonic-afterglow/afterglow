"""The Harmony 650's and 700's words come from their catalogues, so they can be translated:
every word a build draws is a message of `catalogue.py`, the templates and English
catalogues are in step with it, and a translated build reads back as one of Afterglow's."""
from __future__ import annotations

import importlib
import re

import pytest

from afterglow import payloads, remotes

REMOTES = ("harmony-650", "harmony-700")
MARK = "ø"


def _backend(remote, name):
    return importlib.import_module(f"afterglow.backends.{remote.replace('-', '_')}.{name}")


@pytest.mark.parametrize("remote", REMOTES)
def test_the_template_and_english_catalogue_are_in_step(remote):
    """Run tools/arch14_pot.py after changing a word."""
    catalogue = _backend(remote, "catalogue")
    pot = catalogue.LOCALE_DIR / f"{catalogue.DOMAIN}.pot"
    assert catalogue.DOMAIN == remote
    assert pot.read_text("utf-8") == catalogue.template()
    shipped = (catalogue.LOCALE_DIR / "en.po").read_text("utf-8")
    assert catalogue.english_catalogue(shipped) == shipped


def _marked(text: str) -> str:
    """Every word of ``text`` marked, its {fields} and line breaks kept."""
    return "".join(MARK + token if re.match(r"[^\s{}]", token) else token
                   for token in re.findall(r"\{[^}]*\}|[^\s{}]+|\s+", text))


def _translated(remote, tmp_path, monkeypatch):
    """The remote's catalogue with a language, "xx", whose every word is marked."""
    from afterglow import po
    catalogue = _backend(remote, "catalogue")

    def answers(message):
        return ([_marked(message.text)] if message.plural is None
                else [_marked(message.text), _marked(message.plural)])
    (tmp_path / "xx.po").write_text(
        po.template(catalogue.MESSAGES, catalogue.DOMAIN, answers, "xx"), "utf-8")
    monkeypatch.setattr(catalogue, "LOCALE_DIR", tmp_path)
    return catalogue


def _read_as(word: str) -> str:
    """A word as reading it back can tell it: our own face draws I and l alike."""
    return word.casefold().replace("l", "i")


def _household(remote):
    module = importlib.import_module(f"test_{remote.replace('-', '_')}")
    project = module._household()
    tv = project["devices"][0]
    for digit in range(10):
        tv["signals"][f"Number{digit}"] = module._nec(4, 40 + digit)
        tv["commands"].append([f"Number{digit}", "", "", "", f"Number{digit}"])
    project["activities"][0]["image_buttons"] = [
        ["BBC One", "channel", "101", None], ["", "channel", "7", None]]
    project["settings"] = {"locale": "xx", "welcome": "always", "remote_assistant": True}
    return project


@pytest.mark.parametrize("remote", REMOTES)
def test_every_word_a_build_draws_is_the_catalogues(remote, tmp_path, monkeypatch):
    """Built in a language whose every word is marked, the image draws no unmarked word
    but the household's own names - nothing is drawn around the catalogue."""
    _translated(remote, tmp_path, monkeypatch)
    compose, importing = _backend(remote, "compose"), _backend(remote, "importing")
    project = _household(remote)
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    # the household's own words: every name it gives, its commands' split at their capitals
    names = set()

    def gather(value):
        if isinstance(value, str):
            for word in value.split():
                names.add(word)
                names.update(re.findall(r"[A-Z]?[a-z]+\d*|[A-Z]+(?![a-z])|\d+", word))
        elif isinstance(value, dict):
            for item in value.values():
                gather(item)
        elif isinstance(value, list):
            for item in value:
                gather(item)
    gather([project["devices"], project["activities"]])
    names.update(("Harmony", remote.split("-")[1]))
    known = {_read_as(name) for name in names}
    reader = importing.Image(image)
    unmarked = set()
    for screen in reader.screens:
        for slot in screen["slots"]:
            carried = False         # a mark a label broke off its word, onto a line alone
            for item in reader.page_text(slot["program_offset"]):
                for word in item["text"].split():
                    if word == MARK:
                        carried = True
                        continue
                    marked, carried = carried or MARK in word, False
                    cut = word.endswith("..")
                    word = word.rstrip(".?:")
                    if marked or not re.search(r"[A-Za-z]", word) or _read_as(word) in known \
                            or cut and any(name.startswith(_read_as(word)) for name in known):
                        continue
                    unmarked.add(word)
    assert unmarked == set()


@pytest.mark.parametrize("remote", REMOTES)
def test_a_translated_build_reads_back_as_afterglows(remote, tmp_path, monkeypatch):
    """Its Remote Assistant is found by its title in any language there is a catalogue
    for, and it is still one of Afterglow's builds."""
    _translated(remote, tmp_path, monkeypatch)
    compose, backend = _backend(remote, "compose"), _backend(remote, "backend")
    image = compose.build(_household(remote), stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    folder = tmp_path / "built"
    payloads.get("blob").unpack(image, str(folder))
    read = backend.import_project(str(folder), remotes.get(remote), {"name": "t"}).project
    assert read["settings"]["remote_assistant"] is True
    assert backend.afterglow_built(image) is True


@pytest.mark.parametrize("remote", REMOTES)
def test_a_translation_with_a_misspelt_field_falls_back_to_english(remote, tmp_path,
                                                                    monkeypatch):
    """A translator's {feild} used to stop the build with a bare KeyError."""
    from afterglow import po
    catalogue = _backend(remote, "catalogue")
    message = next(m for m in catalogue.MESSAGES if m.brace_format and m.plural is None
                   and re.search(r"\{(\w+)\}", m.text))
    field = re.search(r"\{(\w+)\}", message.text).group(1)

    def answers(m):
        if m is message:
            return [message.text.replace("{" + field + "}", "{misspelt}")]
        return [m.text] if m.plural is None else [m.text, m.plural]
    (tmp_path / "xx.po").write_text(
        po.template(catalogue.MESSAGES, catalogue.DOMAIN, answers, "xx"), "utf-8")
    monkeypatch.setattr(catalogue, "LOCALE_DIR", tmp_path)
    words = catalogue.load("xx")
    values = {name: "X" for name in re.findall(r"\{(\w+)\}", message.text)}
    assert words(message.context, **values) == message.text.format(**values)


@pytest.mark.parametrize("remote", REMOTES)
def test_a_notice_longer_than_the_english_stays_on_the_screen(remote):
    platform_text = _backend(remote, "platform_text")
    height, spacing = platform_text.SCREEN_HEIGHT, 12
    texts, top = platform_text._on_screen(["word"] * 4, 120, spacing)
    assert top >= 0 and top + spacing * len(texts) <= height
    texts, top = platform_text._on_screen(["word"] * 30, 64, spacing)
    assert len(texts) == height // spacing and texts[-1].endswith("..")
    assert top >= 0 and top + spacing * len(texts) <= height
    assert platform_text._on_screen(["a", "b"], 64, spacing) == (["a", "b"], 58)
