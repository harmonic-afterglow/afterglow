"""Themes on the Harmony 5xx: the pictures and the typeface, the rest the platform's."""
from __future__ import annotations

import gzip
import shutil

import pytest

from afterglow import imaging, paths, themes
from afterglow.backends.harmony_555 import artwork, generate, gspm, pixels, typeface

STAMP = (48, 27, 21, 27, 9, 2020)
WHITE, BLACK = (255, 255, 255, 255), (0, 0, 0, 255)


def _png(rows) -> bytes:
    return imaging.encode(rows)


def _built(project, remote="harmony-555", theme=None):
    return generate.build_fitting(dict(project, settings={"remote": remote}),
                                  paths.scaffolds(remote), STAMP, None, theme)


def _example(tmp_path):
    """The 555's example theme, as an owner's copy of it would be."""
    source, files = themes.example_source(paths.scaffolds("harmony-555"))
    theme = tmp_path / "theme"
    for name in files:
        (theme / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, theme / name)
    return theme


def test_any_png_is_drawn_in_its_box_in_black_and_white():
    # black on white at its size comes through pixel for pixel
    drawn = [[BLACK if (x + y) % 3 == 0 else WHITE for x in range(96)] for y in range(64)]
    assert artwork.picture(_png(drawn), 96, 64) == \
        [[1 if (x + y) % 3 == 0 else 0 for x in range(96)] for y in range(64)]
    # a smaller one is centred, transparent is white, and colour is grey
    small = [[(255, 0, 0, 255)] * 4 for _ in range(2)]
    rows = artwork.picture(_png(small), 8, 4)
    assert len(rows) == 4 and len(rows[0]) == 8
    assert sum(map(sum, rows[:1] + rows[3:])) == 0
    assert all(row[:2] == [0, 0] and row[6:] == [0, 0] for row in rows)
    assert artwork.picture(_png([[(0, 0, 0, 0)] * 8] * 8), 8, 8) == [[0] * 8] * 8
    # a bigger one is shrunk to fit, its proportions kept: 192 x 32 is 96 x 16
    rows = artwork.picture(_png([[BLACK] * 192] * 32), 96, 64)
    assert [sum(row) for row in rows] == [0] * 24 + [96] * 16 + [0] * 24
    # and a mid grey is a pattern, half ink
    rows = artwork.picture(_png([[(128, 128, 128, 255)] * 16] * 16), 16, 16)
    assert 100 <= sum(map(sum, rows)) <= 156
    # a box drawn at the top left of a bigger stored picture
    rows = artwork.picture(_png([[BLACK] * 96]), 96, 1, (96, 64))
    assert rows[0] == [1] * 96 and not any(map(any, rows[1:]))


def test_the_example_theme_builds_what_the_scaffold_builds(tmp_path):
    from test_harmony_5xx import _household

    theme = _example(tmp_path)
    for remote in ("harmony-555", "harmony-515"):
        assert _built(_household(), remote, theme)[1] == _built(_household(), remote)[1]


def test_a_themes_pictures_reach_the_build_and_nothing_else_changes(tmp_path):
    from test_harmony_5xx import _household

    theme = tmp_path / "Frames"
    (theme / "images").mkdir(parents=True)
    shutil.copy2(paths.scaffolds("harmony-555") / artwork.MANIFEST, theme)
    # a frame round the screen, drawn twice the size, and a dotted underline
    big = [[BLACK if x < 4 or x >= 188 or y < 4 or y >= 124 else WHITE for x in range(192)]
           for y in range(128)]
    (theme / "images" / "backdrop.png").write_bytes(_png(big))
    (theme / "images" / "underline.png").write_bytes(
        _png([[BLACK if x % 2 == 0 else WHITE for x in range(96)]]))
    default, plain = _built(_household())
    themed, payload = _built(_household(), theme=theme)
    gspm.validate(payload)
    frame = [[1 if x < 2 or x >= 94 or y < 2 or y >= 62 else 0 for x in range(96)]
             for y in range(64)]
    assert themed.pictures["picture-0"] == pixels.encode_picture(frame)
    dotted = [[1 - x % 2 for x in range(96)]] + [[0] * 96] * 63
    assert themed.pictures["picture-2"] == pixels.encode_picture(dotted)
    # every other picture is the scaffold's, and the build is the same size
    assert {role for role in default.pictures
            if default.pictures[role] != themed.pictures[role]} == {"picture-0", "picture-2"}
    assert len(payload) == len(plain)


def test_a_themes_typeface_draws_the_words(tmp_path):
    theme = _example(tmp_path)
    face = theme / typeface.FACE
    # the same face with its capital A drawn as a filled box
    text = gzip.decompress(face.read_bytes()).decode("latin-1")
    start = text.index("STARTCHAR A\n") if "STARTCHAR A\n" in text else text.index("ENCODING 65\n")
    bitmap = text.index("BITMAP\n", start) + len("BITMAP\n")
    end = text.index("ENDCHAR", bitmap)
    rows = text[bitmap:end].split()
    text = text[:bitmap] + "".join("FF\n" for _ in rows) + text[end:]
    face.write_bytes(gzip.compress(text.encode("latin-1")))
    from test_harmony_5xx import _household

    project = _household()
    project["activities"][0]["label"] = "AAA 0"
    default, plain = _built(project)
    themed, payload = _built(project, theme=theme)
    assert themed.face.face.glyph("A")["rows"] != default.face.face.glyph("A")["rows"]
    assert payload != plain
    # Galmuri's slashed zero is Galmuri's: another typeface draws its own
    assert default.face.marks and not themed.face.marks


def test_a_5xx_example_is_the_555s_pictures_and_typeface_and_never_its_platform():
    try:
        themes.seed_examples()
        for remote in ("harmony-555", "harmony-525", "harmony-515", "harmony-xbox360"):
            example = themes.folder(remote) / themes.EXAMPLE
            assert (example / themes.MANIFEST).is_file(), remote
            assert (example / "THEME.md").is_file()
            assert (example / "images" / "backdrop.png").is_file()
            assert (example / typeface.FACE).is_file()
            assert not (example / "platform").exists()
            assert themes.names(remote) == []
        assert themes.seed_examples() == []
        # an owner's copy is a theme of that remote's, by name
        shutil.copytree(themes.folder("harmony-525") / themes.EXAMPLE,
                        themes.folder("harmony-525") / "Frames")
        assert themes.names("harmony-525") == ["Frames"]
    finally:
        shutil.rmtree(paths.user_folder("themes"), ignore_errors=True)


def test_a_project_names_its_theme_and_a_missing_one_is_refused(tmp_path):
    from afterglow import backends, remotes
    from afterglow.backends.contracts import BuildContext
    from afterglow.build_service import find_scaffold

    from test_harmony_5xx import _household

    theme = _example(tmp_path)
    asked = []

    def find_theme(remote_id, name):
        asked.append((remote_id, name))
        return theme if name == "Mario" else None
    lines = []
    context = BuildContext(root=tmp_path, log=lines.append, find_scaffold=find_scaffold,
                           find_theme=find_theme)
    profile = remotes.get("harmony-525")
    project = dict(_household(), settings={"out_file": "mine", "theme_folder": "Mario"})
    result = backends.for_profile(profile).build_project(project, profile, context)
    assert asked == [("harmony-525", "Mario")]
    assert result.artifact.is_file()
    assert any("with the theme 'Mario'" in line for line in lines)
    with pytest.raises(ValueError, match="no theme 'Luigi'"):
        backends.for_profile(profile).build_project(
            dict(project, settings={"theme_folder": "Luigi"}), profile, context)
