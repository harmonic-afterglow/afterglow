"""A word-wrapped label is never given less height than its text needs at its width.

Under KDE's Breeze a QFormLayout measured wrapped help text at one width and laid it out
narrower, cutting off its last lines. The application-wide filter pins each wrapped
label's minimum height to its height for the width it actually got.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _remove_the_filter_afterwards():
    yield
    from afterglow.gui.ui_helpers import remove_wrapped_label_fix
    remove_wrapped_label_fix()


def test_a_wrapped_label_keeps_room_for_every_line(qapp_or_skip):
    from PyQt6.QtWidgets import QApplication, QLabel

    from afterglow.gui.ui_helpers import keep_wrapped_labels_whole
    keep_wrapped_labels_whole(QApplication.instance())
    label = QLabel("The remote has no way to switch this device, so it asks you "
                   "instead of trying. " * 3)
    label.setWordWrap(True)
    label.show()                    # Qt holds a hidden widget's resize events back
    label.resize(120, 10)
    QApplication.processEvents()
    assert label.minimumHeight() == label.heightForWidth(120) > 10

    label.resize(600, label.height())
    QApplication.processEvents()
    assert label.minimumHeight() == label.heightForWidth(600)    # shrinks back when wider


def test_an_unwrapped_label_is_left_alone(qapp_or_skip):
    from PyQt6.QtWidgets import QApplication, QLabel

    from afterglow.gui.ui_helpers import keep_wrapped_labels_whole
    keep_wrapped_labels_whole(QApplication.instance())
    label = QLabel("Manual power")
    label.show()
    label.resize(40, 5)
    QApplication.processEvents()
    assert label.minimumHeight() == 0
