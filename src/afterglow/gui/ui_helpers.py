"""Small reusable Qt presentation helpers."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QCompleter, QFrame, QLabel,
                             QListView)


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def bold_label(text: str, size: int | None = None) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    if size:
        font.setPointSize(size)
    label.setFont(font)
    return label


class FilterCombo(QComboBox):
    """A combo box that can be typed into to narrow a long list.

    Qt's default popup grows with the number of entries, so a device with seventy
    commands opens a list taller than the screen: the top and bottom run off it and the
    entry you want may not be reachable. That is not a cosmetic problem - it is how
    `CBL/SAT` got recorded as `DSPSimulation`.

    So: the popup is bounded and scrolls, and typing filters. Selection is still by
    `currentData()`, exactly as a plain combo.
    """

    def __init__(self, parent=None, visible_items: int = 12):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(visible_items)
        # A styled view is what makes setMaxVisibleItems actually bound the popup;
        # the native one ignores it on most platforms.
        self.setView(QListView())
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(completer)
        self.lineEdit().setPlaceholderText("type to filter…")

    def set_items(self, items):
        """`items` is [(text, data)] or [(text, data, icon)]."""
        self.clear()
        for entry in items:
            if len(entry) == 3:
                text, data, icon = entry
                self.addItem(icon, text, data)
            else:
                text, data = entry
                self.addItem(text, data)
        self.setCurrentIndex(0 if self.count() else -1)

    def select_data(self, value) -> bool:
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)
            return True
        return False


def order_by_participation(devices, participating):
    """Devices in this activity first, everything else after a separator.

    Ordering rather than filtering, deliberately. A macro may legitimately poke a
    device the activity does not otherwise use - closing the blinds when a film starts
    is exactly that - and hiding it would make a real setup impossible to express. But
    the ones the activity is built around should not have to be hunted for.

    Returns `(ordered_devices, index_to_put_a_separator_at)`.
    """
    if not participating:
        return list(devices), None
    wanted = set(participating)
    taking_part = [d for d in devices if d["id"] in wanted]
    others = [d for d in devices if d["id"] not in wanted]
    if not taking_part or not others:
        return taking_part + others, None
    return taking_part + others, len(taking_part)
