"""Rows put in order by dragging their grip: devices, activities, steps, buttons.

The device and activity lists had no way to change their order at all, and the step
and power lists had Up and Down buttons. These drag the way a person does - press,
move, release on the view - and check the order that results.
"""
from __future__ import annotations

ONE = {"settings": {"remote": "harmony-one"}, "activities": [],
       "devices": [{"id": str(n), "label": label, "type": "Television"}
                   for n, label in enumerate(["TV", "Receiver", "Player"], start=1)]}


def _drag(view, from_row, to_row):
    """Press on one row, move past the middle of another, let go."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication

    view.resize(500, 400)
    view.show()
    QApplication.processEvents()
    model = view.model()
    start = view.visualRect(model.index(from_row, 0)).center()
    target = view.visualRect(model.index(to_row, 0))
    # below the middle when moving down, above it when moving up
    end_y = target.bottom() - 2 if to_row > from_row else target.top() + 2
    viewport = view.viewport()

    def send(kind, x, y, buttons):
        point = QPointF(x, y)
        QApplication.sendEvent(viewport, QMouseEvent(
            kind, point, viewport.mapToGlobal(point), Qt.MouseButton.LeftButton,
            buttons, Qt.KeyboardModifier.NoModifier))

    left = Qt.MouseButton.LeftButton
    send(QEvent.Type.MouseButtonPress, 4, start.y(), left)
    send(QEvent.Type.MouseMove, 4, (start.y() + end_y) / 2, left)
    send(QEvent.Type.MouseMove, 4, end_y, left)
    send(QEvent.Type.MouseButtonRelease, 4, end_y, Qt.MouseButton.NoButton)


def test_devices_are_put_in_order_by_dragging(qapp_or_skip):
    import copy

    from afterglow.gui.tabs import DevicesTab
    project = copy.deepcopy(ONE)
    tab = DevicesTab(project, [])
    changed = []
    tab.changed.connect(lambda: changed.append(True))
    _drag(tab.cards, 0, 2)                                  # the TV to the bottom
    assert [d["label"] for d in project["devices"]] == ["Receiver", "Player", "TV"]
    assert changed
    assert tab.cards.card(2).spec["label"] == "TV"          # and the cards follow


def test_activities_are_put_in_order_by_dragging(qapp_or_skip):
    import copy

    from afterglow.gui.tabs import ActivitiesTab
    project = copy.deepcopy(ONE)
    project["activities"] = [{"id": str(1000 + n), "label": label, "display": "1"}
                             for n, label in enumerate(["Watch TV", "Music", "Game"])]
    tab = ActivitiesTab(project)
    _drag(tab.cards, 2, 0)                                  # Game to the top
    assert [a["label"] for a in project["activities"]] == ["Game", "Watch TV", "Music"]


def test_a_click_is_not_a_drag(qapp_or_skip):
    from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem

    from afterglow.gui.drag_rows import RowDragger
    table = QTableWidget(3, 1)
    for row in range(3):
        table.setItem(row, 0, QTableWidgetItem(str(row)))
    moves = []
    RowDragger(table, lambda a, b: moves.append((a, b)))
    _drag(table, 1, 1)
    assert moves == []


def test_startup_steps_are_put_in_order_by_dragging(qapp_or_skip):
    from afterglow.gui.macro import MacroEditorWidget
    devices = ONE["devices"]
    steps = [("command", "1", "PowerOn"), ("delay", None, 500), ("command", "2", "Input")]
    editor = MacroEditorWidget(devices, steps)
    assert not hasattr(editor, "up_btn")                    # the buttons it replaces
    _drag(editor.table, 2, 0)
    assert [tuple(step) for step in editor.get_macro()] == [
        ("command", "2", "Input"), ("command", "1", "PowerOn"), ("delay", None, 500)]


def test_only_what_is_switched_on_has_an_order(qapp_or_skip):
    from afterglow.gui.activity_power import ActivityPowerPage
    page = ActivityPowerPage(ONE["devices"], {"power_on_devices": ["1", "2"],
                                              "power_off_devices": ["3"]})
    _drag(page.table, 1, 0)
    assert page.get_plan() == (["2", "1"], ["3"])
    _drag(page.table, 2, 0)                                 # off: stays where it is
    assert page.get_plan() == (["2", "1"], ["3"])


def test_screen_buttons_keep_their_place_when_edited_and_move_when_dragged(qapp_or_skip):
    from afterglow.gui.activity_buttons import ScreenButtonsPage
    buttons = [{"label": name, "device": "1", "command": name}
               for name in ("Netflix", "YouTube", "Subtitles")]
    page = ScreenButtonsPage(ONE["devices"], {"soft_buttons": buttons})
    _drag(page.table, 0, 2)
    assert [b["label"] for b in page.get_buttons()] == ["YouTube", "Subtitles", "Netflix"]
    entries = page.get_buttons()
    entries[0] = {**entries[0], "label": "YT"}
    page._set_rows(entries, 0)                              # what an edit does now
    assert [b["label"] for b in page.get_buttons()] == ["YT", "Subtitles", "Netflix"]


def test_a_card_is_dragged_by_its_grip(qapp_or_skip):
    """As the mouse does it: pressed on the grip, inside the card, inside the list."""
    import copy

    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QLabel

    from afterglow.gui.tabs import DevicesTab
    project = copy.deepcopy(ONE)
    tab = DevicesTab(project, [])
    tab.resize(600, 500)
    tab.show()
    QTest.qWaitForWindowExposed(tab)
    grip = tab.cards.card(0).findChildren(QLabel)[0]
    start = grip.mapTo(tab, grip.rect().center())
    bottom = tab.cards.visualRect(tab.cards.model().index(2, 0)).bottom()
    end = tab.cards.viewport().mapTo(tab, QPoint(10, bottom - 3))
    window = tab.windowHandle()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    for step in range(1, 11):
        QTest.mouseMove(window, start + (end - start) * step / 10)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    assert [d["label"] for d in project["devices"]] == ["Receiver", "Player", "TV"]


def test_a_card_says_only_what_is_known(qapp_or_skip):
    """A device imported from a configuration has no make or model: its line started
    with a lone dot. An activity without a screen said "Display: ?"."""
    from afterglow.gui.tabs import ActivityCard, DeviceCard
    from PyQt6.QtWidgets import QLabel
    device = DeviceCard({"id": "1", "label": "TV", "type": "Television", "commands": []},
                        lambda *_: None, lambda *_: None, project=ONE)
    line = device.findChildren(QLabel)[-1].text()
    assert not line.lstrip().startswith("·") and line.startswith("Television")
    activity = ActivityCard({"id": "1001", "label": "Radio", "control": "1"},
                            {"1": {"label": "Tuner"}}, lambda *_: None, lambda *_: None)
    assert "Display" not in activity.findChildren(QLabel)[-1].text()
    assert "Control: Tuner" in activity.findChildren(QLabel)[-1].text()
