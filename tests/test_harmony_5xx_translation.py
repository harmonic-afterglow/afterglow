"""The Harmony 5xx's words come from one catalogue, so they can be translated: the template
and English catalogue are in step with it, every text on the platform's own screens is one
of its messages, a build in another language draws none of the English, and it reads back
in that language with the names Help asks about kept."""
from __future__ import annotations

import re

import pytest

from afterglow import backends, paths, po, remotes
from afterglow.backends.harmony_555 import catalogue, generate, labels

from test_harmony_5xx import _household, _imported

MARK = "ø"
STAMP = (48, 27, 21, 27, 9, 2020)


def _image(project, remote="harmony-555"):
    project = dict(project, settings=dict(project.get("settings") or {}, remote=remote))
    return generate.Image(project, paths.scaffolds(remote), STAMP)


def _marked(text: str) -> str:
    """Every word of ``text`` marked, its {fields} and line breaks kept."""
    return "".join(MARK + token if re.match(r"[^\s{}]", token) else token
                   for token in re.findall(r"\{[^}]*\}|[^\s{}]+|\s+", text))


@pytest.fixture
def xx(tmp_path, monkeypatch):
    """A language, "xx", whose every word is marked, as the only translation."""
    def write(answers=None):
        (tmp_path / "xx.po").write_text(po.template(
            catalogue.MESSAGES, catalogue.DOMAIN,
            answers or (lambda message: [_marked(message.text)]), "xx"), "utf-8")
        labels.known_shapes.cache_clear()
    monkeypatch.setattr(catalogue, "LOCALE_DIR", tmp_path)
    write()
    yield write
    labels.known_shapes.cache_clear()


def _in_xx(project):
    return dict(project, settings=dict(project.get("settings") or {}, locale="xx"))


def test_the_template_and_english_catalogue_are_in_step():
    """Run tools/harmony_5xx_pot.py after changing a word."""
    pot = catalogue.LOCALE_DIR / f"{catalogue.DOMAIN}.pot"
    assert sorted(catalogue.LOCALE_DIR.glob("*.pot")) == [pot]
    assert pot.read_text("utf-8") == catalogue.template()
    shipped = (catalogue.LOCALE_DIR / "en.po").read_text("utf-8")
    assert catalogue.english_catalogue(shipped) == shipped


def test_every_text_on_the_platforms_screens_is_the_catalogues():
    image = _image({})
    unknown = [line["text"] for blocks in image.blocks.values()
               for key, lines in blocks if key is None for line in lines]
    assert unknown == []
    answers = {line["text"] for screen in image.screens for page in screen["pages"]
               for line in page["lines"] if line["attribute"] == generate.SOFTKEY}
    assert answers <= {catalogue.english(key) for key in catalogue.ANSWERS}


def _names(project) -> set[str]:
    """The household's own words: every name it gives, its commands' split at capitals."""
    out = set()

    def gather(value):
        if isinstance(value, str):
            for word in value.split():
                out.add(word)
                out.update(re.findall(r"[A-Z]?[a-z]+\d*|[A-Z]+(?![a-z])|\d+", word))
        elif isinstance(value, dict):
            for item in value.values():
                gather(item)
        elif isinstance(value, list):
            for item in value:
                gather(item)
    gather([project["devices"], project["activities"]])
    return out


@pytest.mark.parametrize("remote", ["harmony-555", "harmony-525"])
def test_a_build_in_another_language_draws_no_english(remote, xx):
    """Built in a language whose every word is marked, no screen draws an unmarked word
    but the household's own names - nothing is drawn around the catalogue."""
    project = _in_xx(_household())
    image = _image(project, remote)
    image.build()
    names = _names(project)
    unmarked = set()
    for screen in image.screens:
        for page in screen["pages"]:
            for line in page["lines"]:
                for word in image.text_of(line).split():
                    bare = word.removesuffix("..").rstrip(".?:")
                    if MARK in word or not re.search(r"[A-Za-z]", bare) or bare in names \
                            or word.endswith("..") and any(n.startswith(bare) for n in names):
                        continue
                    unmarked.add(word)
    assert unmarked == set()


def test_a_translated_build_reads_back_in_its_language_with_helps_names(xx, tmp_path):
    project = _in_xx(_household())
    tv = project["devices"][0]
    tv["inputs"] = [["HDMI 1", "InputHdmi1"],
                    ["Living room", [{"set": "Screen", "to": "Wide"}]]]
    tv["control_states"] = [{"id": "Screen", "values": ["Normal", "Wide"],
                             "select": {"Normal": {"steps": ["InputHdmi1"]},
                                        "Wide": {"steps": ["InputHdmi2"]}}}]
    project["activities"][0]["enter"] = [["input", tv["id"], "HDMI 1"]]
    project["activities"][1]["enter"] = [["input", tv["id"], "Living room"]]
    back = _imported(_image(project).build(), tmp_path)
    assert back["settings"]["locale"] == "xx"
    assert [device["label"] for device in back["devices"]] == ["Television", "Player"]
    assert [activity["label"] for activity in back["activities"]] == [
        "Watch TV", "Watch a Film"]
    assert [entry[0] for entry in back["devices"][0]["inputs"]][:1] == ["HDMI 1"]
    assert "Wide" in back["devices"][0]["control_states"][0]["values"]


def test_an_english_build_reads_back_with_no_language(tmp_path):
    back = _imported(_image(_household()).build(), tmp_path)
    assert "locale" not in back["settings"]


def test_a_text_longer_than_the_english_stays_on_the_screen(xx):
    """Starting and Stopping Activity's request to keep the remote pointed, in many
    more lines than the English: moved up under its heading and cut, never off the
    screen or over another line."""
    long = " ".join(["word"] * 40)
    xx(lambda message: [long if message.context == "notice.keep-pointed"
                        else _marked(message.text)])
    image = _image(_in_xx(_household()))
    image.build()
    for screen in image.screens:
        for page in screen["pages"]:
            ys = sorted(line["y"] for line in page["lines"]
                        if line["attribute"] == generate.NOTICE
                        and line["align"] == "centre")
            assert all(0 <= y <= generate.HEIGHT - generate.LINE for y in ys)
            assert all(b - a >= generate.LINE for a, b in zip(ys, ys[1:])), ys


def test_a_translation_with_a_misspelt_field_falls_back_to_english(xx):
    xx(lambda message: [message.text.replace("{device}", "{misspelt}")])
    words = catalogue.load("xx")
    assert words("help.is-on", device="TV") == "Is the TV on?"


def test_a_translation_is_offered_because_its_file_is_there(xx):
    profile = remotes.get("harmony-555")
    assert backends.translations(profile) == ("xx",)
    assert "language" in profile.settings_fields
