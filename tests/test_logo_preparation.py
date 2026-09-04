"""A favourite's logo has to fit the cell the touchscreen draws it into.

The remote resizes nothing. It copies the file out of the configuration and paints it,
so whatever is put in is what appears - and a picture straight off a website is twenty
times too big in each direction.

This was written after finding that the fitting step existed but nothing called it: the
favourites dialog had been rewritten to copy the chosen file through untouched. It went
unnoticed because the logos to hand were already exactly 90x54, so every test and every
real config looked right.
"""
import pytest

pytest.importorskip("PIL")

from PIL import Image                                            # noqa: E402


@pytest.fixture
def prepare(qapp_or_skip):
    from afterglow.gui.activity_buttons import prepare_logo
    return prepare_logo


def source(tmp_path, size, name="Some Channel.png", colour=(255, 0, 0, 255)):
    path = tmp_path / name
    Image.new("RGBA", size, colour).save(path)
    return path


def test_an_oversized_picture_comes_back_the_size_of_the_cell(prepare, tmp_path):
    from afterglow.gui.activity_buttons import LOGO_H, LOGO_W
    out = prepare(source(tmp_path, (2000, 1500)))
    assert Image.open(out).size == (LOGO_W, LOGO_H)


def test_a_tiny_picture_is_not_left_tiny(prepare, tmp_path):
    """Scaling has to work in both directions; a 16-pixel favicon is a real thing to
    pick, and left alone it is a speck in the corner of the cell."""
    out = prepare(source(tmp_path, (16, 16)))
    image = Image.open(out)
    assert image.size == (90, 54)
    assert image.split()[3].getbbox()[2] > 20, "artwork was not scaled up to fill"


def test_the_artwork_is_centred_with_a_margin(prepare, tmp_path):
    from afterglow.gui.activity_buttons import LOGO_H, LOGO_W, _MIN_PADDING
    left, top, right, bottom = Image.open(
        prepare(source(tmp_path, (400, 400)))).split()[3].getbbox()
    assert left >= _MIN_PADDING and top >= _MIN_PADDING
    assert right <= LOGO_W - _MIN_PADDING and bottom <= LOGO_H - _MIN_PADDING
    assert abs(left - (LOGO_W - right)) <= 1, "not centred horizontally"
    assert abs(top - (LOGO_H - bottom)) <= 1, "not centred vertically"


def test_whatever_went_in_comes_out_as_a_png(prepare, tmp_path):
    """Every logo in every real configuration is a PNG, and the name is settled here so
    that the <Image> the config names and the file the build copies cannot disagree."""
    jpeg = tmp_path / "Logo Off A Website.jpg"
    Image.new("RGB", (800, 600), (0, 128, 255)).save(jpeg)
    out = prepare(jpeg)
    assert out.suffix == ".png"
    assert out.name == "logooffawebsite.png"
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_a_prepared_logo_is_small_enough_to_ship(prepare, tmp_path):
    """Logos in real dumps run 1.5-4 kB. The whole configuration goes onto the remote's
    flash, so a megabyte of favourite is not free."""
    out = prepare(source(tmp_path, (3000, 3000)))
    assert out.stat().st_size < 8000, out.stat().st_size


def test_a_prepared_logo_can_be_found_again(prepare, tmp_path):
    """The table previews a favourite by looking its filename up, so wherever prepared
    logos are written has to be one of the places that search covers."""
    from afterglow.gui.activity_buttons import _find_image
    out = prepare(source(tmp_path, (200, 200)))
    assert _find_image(out.name) == out
