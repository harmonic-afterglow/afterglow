"""The artwork a generated Harmony One configuration draws.

The pictures live in the remote's scaffold directory as PNG files so that an owner can
replace them. These tests hold the shipped set to the display's limits, and hold the
loader to reporting what the display cannot keep rather than quietly changing it.
"""

from __future__ import annotations

import json

import pytest

from afterglow import imaging, paths
from afterglow.backends.harmony_one import assets, bitmap


SCAFFOLD = paths.scaffolds("harmony-one")


def test_the_shipped_scaffold_declares_and_supplies_every_picture():
    report = assets.audit(SCAFFOLD)

    assert report["ok"] is True, report["problem"]
    assert report["missing"] == []
    assert len(report["pictures"]) >= 40
    assert len(report["fonts"]) == 18
    # Eight battery levels, because the status program switches on eight cases.
    for level in range(8):
        assert f"status/battery-{level}" in report["pictures"]


def test_the_shipped_artwork_is_exactly_what_the_display_can_show():
    """Nothing shipped may lose colour or a soft edge on the way in.

    The loader reports both, and that report is only useful as a warning about somebody's
    own artwork if what we ship never triggers it. The shipped set came out of the format
    itself, so it is already RGB565 and already one-bit transparent.
    """
    loaded = assets.load(SCAFFOLD)

    assert loaded["notes"] == {}


def test_every_shipped_picture_survives_the_trip_into_the_format_and_back():
    loaded = assets.load(SCAFFOLD)

    for role, item in sorted(loaded["pictures"].items()):
        decoded = bitmap.decode(item["body"], 0)
        assert (decoded["width"], decoded["height"]) == (item["width"], item["height"]), role
        assert decoded["rows"] == item["rows"], role
        # and back out as a file somebody could open again
        again = imaging.decode(imaging.encode(assets.to_image(decoded["rows"])))
        assert again["rows"] == assets.to_image(item["rows"]), role


def test_every_shipped_picture_fits_what_the_reader_will_accept():
    loaded = assets.load(SCAFFOLD)

    for role, item in loaded["pictures"].items():
        assert 1 <= item["width"] <= bitmap.MAX_WIDTH, role
        assert 1 <= item["height"] <= bitmap.MAX_HEIGHT, role
        assert item["mode"] in (bitmap.RAW, bitmap.RUNS), role


def test_the_manifest_names_a_file_for_every_picture_and_no_others(tmp_path):
    manifest = json.loads((SCAFFOLD / assets.MANIFEST).read_text("utf-8"))
    declared = {entry["file"] for entry in manifest["pictures"].values()}
    declared |= {entry["file"] for entry in manifest.get("fonts", {}).values()}

    present = {
        str(path.relative_to(SCAFFOLD)).replace("\\", "/")
        for path in SCAFFOLD.rglob("*.png")
    }

    assert declared == present


def test_a_picture_whose_size_disagrees_with_the_manifest_is_refused(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "small.png").write_bytes(
        imaging.encode([[(0, 0, 0, 255)] * 4] * 4))
    (tmp_path / assets.MANIFEST).write_text(json.dumps({
        "schema": assets.SCHEMA, "remote": "harmony-one",
        "pictures": {"thing": {"file": "images/small.png", "size": [8, 8]}},
    }), "utf-8")

    with pytest.raises(ValueError, match="is 4x4, but the manifest says 8x8"):
        assets.load(tmp_path)


def test_a_picture_the_manifest_names_but_does_not_ship_is_an_error(tmp_path):
    (tmp_path / assets.MANIFEST).write_text(json.dumps({
        "schema": assets.SCHEMA, "remote": "harmony-one",
        "pictures": {"thing": {"file": "images/absent.png"}},
    }), "utf-8")

    with pytest.raises(FileNotFoundError, match="which does not exist"):
        assets.load(tmp_path)


def test_transparency_is_reported_as_hardened_rather_than_blended(tmp_path):
    """The format has no alpha channel, so a soft edge cannot survive; say so."""
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "soft.png").write_bytes(imaging.encode([
        [(255, 0, 0, 255), (255, 0, 0, 90), (255, 0, 0, 200), (255, 0, 0, 0)]]))
    (tmp_path / assets.MANIFEST).write_text(json.dumps({
        "schema": assets.SCHEMA, "remote": "harmony-one",
        "pictures": {"soft": {"file": "images/soft.png"}},
    }), "utf-8")

    loaded = assets.load(tmp_path)

    item = loaded["pictures"]["soft"]
    # below half opaque leaves the screen alone, at or above it draws
    assert [pixel is None for pixel in item["rows"][0]] == [False, True, False, True]
    assert loaded["notes"]["soft"]["partial_alpha"] == 2


def test_a_picture_with_transparency_cannot_ask_to_store_every_pixel(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "gap.png").write_bytes(
        imaging.encode([[(1, 2, 3, 0), (1, 2, 3, 255)]]))
    (tmp_path / assets.MANIFEST).write_text(json.dumps({
        "schema": assets.SCHEMA, "remote": "harmony-one",
        "pictures": {"gap": {"file": "images/gap.png", "mode": "raw"}},
    }), "utf-8")

    with pytest.raises(ValueError, match="cannot store every pixel"):
        assets.load(tmp_path)


def test_a_manifest_of_the_wrong_schema_is_refused(tmp_path):
    (tmp_path / assets.MANIFEST).write_text(json.dumps({
        "schema": "something-else/9", "pictures": {}}), "utf-8")

    with pytest.raises(ValueError, match="declares schema"):
        assets.read_manifest(tmp_path)


def test_a_directory_with_no_manifest_says_so_rather_than_loading_nothing(tmp_path):
    with pytest.raises(FileNotFoundError, match="declares no assets"):
        assets.read_manifest(tmp_path)


# The heights the interface draws the owner's own words at: button labels, the softkey
# row and a screen's title are all 14 pixels in every donor measured.
TEXT_HEIGHT = 14
PRINTABLE = {chr(code) for code in range(0x20, 0x7F)}


def test_every_font_that_carries_typed_text_draws_all_of_printable_ascii():
    """A font that cannot spell a device's name cannot label a button for it.

    No donor has `$%&;<=>@[]^_`, a backtick, or `{|}~` at any size - the vendor shipped
    only the characters their own configurations drew - so these are derived from each
    font's own strokes or drawn, and a build must not be able to lose them.
    """
    loaded = assets.load(SCAFFOLD)

    fonts = [f for f in loaded["fonts"].values() if f["height"] == TEXT_HEIGHT]
    assert fonts, f"the scaffold ships no {TEXT_HEIGHT} pixel font"
    for font in fonts:
        characters = {item["char"] for item in font["glyphs"].values() if item["char"]}
        assert not PRINTABLE - characters, (
            f"{font['file']} cannot draw {sorted(PRINTABLE - characters)}")


def test_a_glyph_code_is_never_reused_within_a_font():
    """Codes are the font's own index, and the added ones continue past the vendor's."""
    loaded = assets.load(SCAFFOLD)

    for role, font in sorted(loaded["fonts"].items()):
        characters = [item["char"] for item in font["glyphs"].values() if item["char"]]
        assert len(characters) == len(set(characters)), f"{role} draws a character twice"


def test_every_shipped_glyph_survives_the_trip_into_the_format_and_back():
    loaded = assets.load(SCAFFOLD)

    for role, font in sorted(loaded["fonts"].items()):
        assert font["glyphs"], role
        for code, glyph in sorted(font["glyphs"].items()):
            decoded = bitmap.decode_glyph(glyph["body"], 0)
            assert decoded["width"] == glyph["width"], f"{role} {code}"
            assert decoded["height"] == font["height"], f"{role} {code}"
            assert decoded["rows"] == glyph["rows"], f"{role} {code}"


def test_a_font_is_one_colour_and_its_shadow_rather_than_a_mixture():
    """A borrowed glyph is recoloured, so no font spells a word in two colours.

    Filling a font's gaps from another font of the same typeface is how the shipped set
    is completed, and those fonts differ only in colour - so a glyph that arrives
    unrecoloured makes a single label parti-coloured.
    """
    loaded = assets.load(SCAFFOLD)

    for role, font in sorted(loaded["fonts"].items()):
        colours = {
            pixel for glyph in font["glyphs"].values()
            for row in glyph["rows"] for pixel in row if pixel is not None
        }
        assert len(colours) <= 2, f"{role} draws {len(colours)} colours: {sorted(colours)}"


def test_a_glyph_that_would_sit_outside_its_sheet_is_refused(tmp_path):
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "f.png").write_bytes(
        imaging.encode([[(255, 255, 255, 255)] * 4] * 6))
    (tmp_path / assets.MANIFEST).write_text(json.dumps({
        "schema": assets.SCHEMA, "remote": "harmony-one", "pictures": {},
        "fonts": {"f": {"file": "fonts/f.png", "height": 6,
                        "glyphs": [{"code": 1, "char": "H", "x": 2, "width": 8}]}},
    }), "utf-8")

    with pytest.raises(ValueError, match="outside a sheet 4 wide"):
        assets.load(tmp_path)


def test_a_label_of_any_printable_ascii_encodes_through_a_scaffold_font():
    """The manifest, not the donor-derived repertoire, says what a generated font draws."""
    from afterglow.backends.harmony_one import screen_program

    loaded = assets.load(SCAFFOLD)
    font = next(f for f in loaded["fonts"].values() if f["height"] == TEXT_HEIGHT)
    report, widths = assets.mapping(font), assets.widths(font)

    label = "".join(sorted(PRINTABLE - {" "}))
    codes = screen_program._encode(label, report, widths)

    assert len(codes) == len(label)
    assert all(code in widths for code in codes)


def test_a_character_no_font_draws_is_still_refused_by_name():
    loaded = assets.load(SCAFFOLD)
    font = next(f for f in loaded["fonts"].values() if f["height"] == TEXT_HEIGHT)

    with pytest.raises(ValueError, match="not established"):
        from afterglow.backends.harmony_one import screen_program
        screen_program._encode("caf\u00e9", assets.mapping(font), assets.widths(font))
