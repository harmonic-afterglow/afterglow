"""Favourites without logos: the Harmony 650's and 700's Favourites page offers no logo to
pick, since no configuration Logitech built for them has one; the One's still does."""
from __future__ import annotations

import pytest

from afterglow import remotes


def _devices():
    return [{"id": "1", "label": "TV", "type": "Television",
             "commands": [[f"Number{d}", str(d), "", "01", None] for d in range(10)]}]


def test_the_650_and_700_have_favourites_without_logos_and_the_one_with():
    for remote in ("harmony-650", "harmony-700"):
        profile = remotes.get(remote)
        assert "favourites" in profile.activity_pages
        assert profile.favourite_logos is False
    assert remotes.get("harmony-one").favourite_logos is True


def test_a_profile_says_true_or_false_about_logos():
    with pytest.raises(ValueError, match="favourite_logos"):
        remotes._check_interface("x", {"tabs": ["devices", "flash"],
                                       "device_pages": ["identity", "commands"],
                                       "activity_pages": ["identity", "roles"],
                                       "settings": ["output_file"], "timing": [],
                                       "favourite_logos": "no",
                                       "languages": [["English", "enu"]]}, {})


@pytest.mark.parametrize("remote, logos", [("harmony-650", False), ("harmony-one", True)])
def test_the_favourites_page_offers_a_logo_only_where_the_remote_has_them(
        qapp_or_skip, remote, logos):
    from afterglow.gui.activity_buttons import FavouriteDialog, FavouritesPage
    page = FavouritesPage(_devices(), {"image_buttons": [["BBC One", "channel", "1", ""]]},
                          remote=remotes.get(remote))
    assert page.table.isColumnHidden(0) is not logos
    assert page.get_buttons() == [("BBC One", "channel", "1", "")]
    dialog = FavouriteDialog(_devices(), logos=logos)
    assert dialog.preview.isVisibleTo(dialog) is logos


def _activity(**fields):
    return {"id": "9", "label": "Humax", "type": "VirtualGeneric", "display": "1",
            "control": "1", "roles": {}, "image_buttons": [], "soft_buttons": [
                {"label": "Media", "action": ["command", "1", "Number1"]},
                {"label": "Guide", "action": ["command", "1", "Number2"]}],
            "hard_macros": {}, "enter": [], "leave": [], "properties": {}, **fields}


def test_the_650s_screen_page_draws_its_four_corners_text_only():
    for remote in ("harmony-650", "harmony-700"):
        profile = remotes.get(remote)
        assert profile.screen_grid("activity") == (2, 2)
        assert profile.screen_icons is False
        assert profile.favourites_button == "Favorite Channels"
    one = remotes.get("harmony-one")
    assert one.screen_icons is True and one.favourites_button is None


def test_the_screen_preview_puts_favorite_channels_first_while_there_are_favourites(
        qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityEditor
    editor = ActivityEditor(_devices(), existing=_activity(), remote="harmony-650")
    screen, favourites = editor.p3b, editor.p3
    assert screen.table.isColumnHidden(0)
    assert screen.preview.isVisibleTo(screen)
    assert [b and b[0] for b in screen.preview.buttons] == ["Media", "Guide"]
    favourites._add_row("TVP1", "channel", "1", "")
    assert [b and b[0] for b in screen.preview.buttons] == [
        "Favorite Channels", "Media", "Guide"]
    screen.preview.picked.emit(2)                 # Guide, the list's second row
    assert screen.table.currentRow() == 1
    favourites.table.removeRow(0)
    assert [b and b[0] for b in screen.preview.buttons] == ["Media", "Guide"]


def test_the_650s_picture_leaves_its_screen_out(qapp_or_skip):
    from afterglow.gui.keys_view import RemoteKeys
    profile = remotes.get("harmony-650")
    art = profile.hard_key_art
    top, bottom = art["cut"][:2]
    view = RemoteKeys(profile)
    assert view._view.height() == art["view"][3] - (bottom - top)
    # the screen's keys go with it; Menu, below, moves up by the band
    assert "Screen key, top left" not in view._fixed and "Watch TV" in view._fixed
    menu = art["keys"]["Menu"]
    assert view._keys["Menu"].boundingRect().top() < menu[1] - (bottom - top) + 2



def test_no_remote_drawing_needs_a_font():
    """Every label is outlines: text would be drawn in whatever font a PC has, or none."""
    for remote in ("harmony-900", "harmony-1100", "harmony-650", "harmony-700",
                   "harmony-800", "harmony-one"):
        svg = remotes.get(remote).hard_key_art["svg"].read_text(encoding="utf-8")
        assert "<text" not in svg and "font-family" not in svg, remote


def test_a_650_shows_no_device_or_activity_icons_of_another_remotes(qapp_or_skip):
    """Its menus are names alone; the 900's pictures would be no 650's."""
    from afterglow.gui import icons
    for remote in ("harmony-650", "harmony-700"):
        profile = remotes.get(remote)
        assert profile.type_icons == (None, None)
        assert icons.artwork_for("Television", profile) is None
        assert icons.pixmap("VirtualDvd", 24, profile).isNull()
    one = remotes.get("harmony-one")
    assert icons.artwork_for("Television", one) is not None
