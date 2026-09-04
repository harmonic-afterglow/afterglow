"""A refresh of the blaster list must not re-tick what the user unticked.

The Add-blasters dialog rebuilds its list on every scan tick and every poll, so the
current tick state has to be carried across; otherwise unticking a responding base and
letting a refresh land silently pairs hardware the user deselected.

"Not ticked" and "not previously on screen" need opposite defaults, so both sets are
tracked: a base the user unticked stays unticked, one that has just appeared is offered
ticked.
"""
import pytest

pytest.importorskip("PyQt6")


def receiver(mac, label, status=1):
    return {"mac": mac, "label": label, "firmware": "1.0", "status": status}


def macs_checked(dialog):
    from PyQt6.QtCore import Qt

    return {dialog._list.item(i).data(Qt.ItemDataRole.UserRole)["mac"]
            for i in range(dialog._list.count())
            if dialog._list.item(i).checkState() == Qt.CheckState.Checked}


def untick(dialog, mac):
    from PyQt6.QtCore import Qt

    for i in range(dialog._list.count()):
        item = dialog._list.item(i)
        if item.data(Qt.ItemDataRole.UserRole)["mac"] == mac:
            item.setCheckState(Qt.CheckState.Unchecked)
            return
    raise AssertionError(f"{mac} is not in the list")


@pytest.fixture
def dialog(qapp_or_skip, monkeypatch):
    from afterglow.gui import blaster_scan

    monkeypatch.setattr(blaster_scan, "_receivers", lambda: [])
    return blaster_scan.BlasterScanDialog(known_macs=[])


THREE = [receiver("00:11:22:33:44:01", 1),
         receiver("00:11:22:33:44:02", 2),
         receiver("00:11:22:33:44:03", 3)]


def test_a_responding_blaster_is_offered_ticked(dialog):
    """The default the fix must not change."""
    dialog._refresh_list(THREE)
    assert macs_checked(dialog) == {r["mac"] for r in THREE}


def test_a_refresh_keeps_what_the_user_unticked(dialog):
    """The regression. Two rebuilds with the same receivers must not resurrect a tick."""
    dialog._refresh_list(THREE)
    untick(dialog, "00:11:22:33:44:02")
    untick(dialog, "00:11:22:33:44:03")
    dialog._refresh_list(THREE)
    assert macs_checked(dialog) == {"00:11:22:33:44:01"}, (
        "a refresh re-ticked a base the user had deselected")


def test_a_blaster_that_appears_later_is_still_offered_ticked(dialog):
    """Unticking one must not make a genuinely new base default to off."""
    dialog._refresh_list(THREE[:2])
    untick(dialog, "00:11:22:33:44:02")
    dialog._refresh_list(THREE)
    assert macs_checked(dialog) == {"00:11:22:33:44:01", "00:11:22:33:44:03"}


def test_only_enabled_rows_are_returned_by_accept(dialog):
    """A base already in the project is shown ticked but disabled, and must not be
    returned as a new choice."""
    from afterglow.gui import blaster_scan

    dlg = blaster_scan.BlasterScanDialog(known_macs=["00:11:22:33:44:01"])
    dlg._refresh_list(THREE)
    dlg._accept()
    assert "00:11:22:33:44:01" not in {r["mac"] for r in dlg.chosen}
