"""Reading a Harmony One configuration back into a project.

A generated image is the test bed: what was put in is known, so what is read back can be
compared field by field. Logitech's own configurations are read the same way; the ones
the maintainer has are checked when present (configs/one/), and skipped otherwise.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from afterglow.backends.harmony_one import generate, labels, ui_index

from test_harmony_one_activities import PROJECT

ROOT = Path(__file__).resolve().parents[1]
ONE_CONFIGS = sorted((ROOT / "configs" / "one").glob("*.ezhex")) if (
    ROOT / "configs" / "one").is_dir() else []


@pytest.fixture(scope="module")
def built():
    return generate.build(PROJECT)


def _all_text(image) -> tuple[set[str], labels.Text]:
    text = labels.Text(image)
    out = set()
    for screen in ui_index.screen_slots(image):
        for slot in screen["slots"]:
            out |= {item["text"] for item in labels.screen_text(
                image, slot["program_offset"], text)}
    return out, text


def test_every_label_a_build_draws_reads_back_by_the_shape_of_its_glyphs(built):
    # Each font slot numbers its own characters from 1, so a code means nothing across
    # fonts; the glyphs' shapes are what say which character each is.
    drawn, text = _all_text(built["image"])
    assert text.unknown == 0
    for device in PROJECT["devices"]:
        assert device["label"] in drawn
        assert {name for name in device["signals"] if len(name) < 9} <= drawn
    assert {"Watch TV", "Listen to Music"} <= drawn


def test_a_shape_two_characters_share_is_the_one_the_image_has_no_other_code_for():
    # Logitech's faces draw a capital I and a small l alike in some sizes; the image gives
    # each character one code, so the code another font reads as l leaves the other one I.
    fonts, shared = labels.read_fonts([{7: "l", 8: "Il"}, {7: "Il", 8: "Il"}])
    assert fonts == [{7: "l", 8: "I"}, {7: "l", 8: "I"}]
    assert shared == {7: "l"}
    # with nothing to tell them apart, it stays unread rather than guessed
    fonts, _shared = labels.read_fonts([{8: "Il"}])
    assert fonts == [{}]


@pytest.mark.parametrize("path", ONE_CONFIGS, ids=lambda path: path.name)
def test_a_logitech_configuration_s_text_reads_back_whatever_its_glyph_layout(path, tmp_path):
    from afterglow import ezhex

    ezhex.unpack(str(path), str(tmp_path))
    drawn, text = _all_text((tmp_path / "payload.bin").read_bytes())
    assert text.unknown == 0
    assert drawn
