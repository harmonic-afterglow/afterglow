"""Reading an arch-14 configuration (600, 650, 665, 700) back: the One's reading fixes,
ported - the language a build was made in, letters two scripts draw alike, and what an
import cannot carry said in its notes rather than dropped unseen."""
from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from afterglow import paths
from afterglow.backends.harmony_650 import compose, importing, labels


def test_a_look_alike_letter_reads_in_the_script_of_its_word():
    # a Cyrillic a is a Latin a's shape: the letters around it say which
    cyrillic = ["П", "аa", "р"]
    latin = ["H", "аa", "t"]
    assert [labels._in_script(c, s) for c, s in zip(cyrillic, labels._scripts(cyrillic))] \
        == ["П", "а", "р"]
    assert [labels._in_script(c, s) for c, s in zip(latin, labels._scripts(latin))] \
        == ["H", "a", "t"]


def test_a_letter_that_could_be_either_script_still_makes_ok_not_0k():
    # the K after it is a Latin or a Cyrillic K, a letter either way
    assert labels._by_neighbours("0O", "", "KК") == "O"


def test_the_language_a_build_was_made_in_comes_back(tmp_path, monkeypatch):
    from test_arch14_translation import _household, _translated

    catalogue = _translated("harmony-650", tmp_path, monkeypatch)
    assert catalogue.translations() == ["xx"]
    image = compose.build(_household("harmony-650"), directory=paths.scaffolds("harmony-650"),
                          stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    read = importing.Image(image)
    assert importing.drawn_language(read) == "xx"
    assert importing.remote_settings(read)["locale"] == "xx"
    # English is no translation: a build in it names no language
    monkeypatch.setattr(catalogue, "LOCALE_DIR", tmp_path / "none")
    assert importing.drawn_language(read) is None


def test_what_a_project_cannot_say_is_counted_not_dropped_unseen():
    """A write to a state of an activity's own is left out and counted; a write to a
    favourite's channel is not, since the digits it dials come along as the favourite."""
    reader = importing.Activities.__new__(importing.Activities)
    reader.variables, reader.naming, reader.left_out = {}, {}, Counter()
    reader.image = SimpleNamespace(names={7: "TV_ChannelMode"}, channel_variables={9})
    reader.macro([(importing.WRITE, 7, 1), (importing.WRITE, 9, 3)])
    assert reader.left_out == Counter({"a write to TV_ChannelMode": 1})


def test_an_unreadable_letter_reads_as_a_question_mark_and_its_line_is_kept():
    """A "?" builds and can be typed over; which lines had a letter no shape reads is
    kept apart, since a "?" may be real."""
    text = labels.Text.empty()
    line = text.decode(bytes([0x21, 0x22]), None)
    assert labels.UNKNOWN == "?" and set(line) == {"?"} and line
    assert text.unread == {line} and text.unknown == len(line)


def test_a_build_of_ours_reads_back_o_as_o_though_its_font_draws_o_like_0(tmp_path):
    """Our fonts draw O and 0 alike. The builder numbers each font's characters in code
    point order, so a shared shape reads as the character between its neighbours'."""
    import importlib

    from afterglow import payloads, remotes
    from afterglow.backends.harmony_650 import backend
    module = importlib.import_module("test_harmony_650")
    project = module._household()
    tv = project["devices"][0]
    for at, name in enumerate(("O", "0")):
        tv["signals"][name] = module._nec(4, 60 + at)
        tv["commands"].append([name, name, "", "", None])
    image = compose.build(project, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    payloads.get("blob").unpack(image, str(tmp_path))
    read = backend.import_project(str(tmp_path), remotes.get("harmony-650"), {}).project
    assert {"O", "0"} <= set(read["devices"][0]["signals"])
