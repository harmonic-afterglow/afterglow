"""The remote's picture in the editors: every key the remote has is drawn, a click on a
key is that key, and no two keys' shapes overlap - for every remote with a drawing.
Shapes are found in the drawing itself (its outlines, a rocker cut into its keys, the
650's screen band left out), so a redrawn art.svg can break any of these."""
from __future__ import annotations

import pytest

from afterglow import remotes

DRAWN = [profile for profile in remotes.load_all() if getattr(profile, "hard_key_art", None)]


def _inside(shape, n=12):
    """Points of ``shape``, from a grid over its bounds."""
    from afterglow.qt.QtCore import QPointF
    box = shape.boundingRect()
    points = (QPointF(box.x() + box.width() * (i + .5) / n,
                      box.y() + box.height() * (j + .5) / n)
              for i in range(n) for j in range(n))
    return [point for point in points if shape.contains(point)]


@pytest.fixture(params=DRAWN, ids=lambda profile: profile.id)
def picture(request, qapp_or_skip):
    from afterglow.gui.keys_view import RemoteKeys
    widget = RemoteKeys(request.param)
    widget.resize(400, 800)
    return request.param, widget


def test_every_key_the_remote_has_is_drawn(picture):
    profile, widget = picture
    art = profile.hard_key_art
    assert widget.has_picture()
    drawn = set(art["keys"]) | set(art.get("unassignable") or {})
    assert set(profile.hard_keys) <= drawn
    assert set(art["keys"]) <= set(widget.keys())


def test_a_click_on_a_key_is_that_key(picture):
    _profile, widget = picture
    to_widget = widget._transform()
    for key, shape in widget._keys.items():
        points = _inside(shape)
        assert points, f"{key} has no shape"
        hits = [widget.key_at(to_widget.map(point)) for point in points]
        # all but the odd point on an edge, or in the sliver a d-pad's parts share
        assert hits.count(key) >= 0.9 * len(hits), f"{key}: {set(hits)}"


def test_no_two_keys_overlap(picture):
    _profile, widget = picture
    names = list(widget._keys)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            a, b = widget._keys[first], widget._keys[second]
            if not a.boundingRect().intersects(b.boundingRect()):
                continue
            points = _inside(a, 16)
            shared = sum(b.contains(point) for point in points) / len(points)
            assert shared <= 0.05, f"{first} and {second} share {shared:.0%}"


def test_a_remote_without_a_drawing_shows_its_keys_as_a_grid(qapp_or_skip):
    import dataclasses

    from afterglow.gui.keys_view import RemoteKeys
    profile = dataclasses.replace(remotes.get("harmony-900"), art=None)
    widget = RemoteKeys(profile)
    assert not widget.has_picture()
    assert set(widget.keys()) == set(profile.hard_keys)


def test_the_keys_can_be_walked_and_picked_from_the_keyboard(qapp_or_skip):
    from afterglow.qt.QtCore import Qt
    from afterglow.qt.QtTest import QTest

    from afterglow.gui.keys_view import RemoteKeys
    widget = RemoteKeys(remotes.get("harmony-650"))
    widget.resize(300, 600)
    picked = []
    widget.key_clicked.connect(picked.append)
    order = widget.keys()
    QTest.keyClick(widget, Qt.Key.Key_Right)
    QTest.keyClick(widget, Qt.Key.Key_Right)
    QTest.keyClick(widget, Qt.Key.Key_Return)
    assert picked == [order[1]]
    QTest.keyClick(widget, Qt.Key.Key_Left)
    QTest.keyClick(widget, Qt.Key.Key_Space)
    assert picked == [order[1], order[0]]
