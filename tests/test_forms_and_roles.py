"""Forms give their fields room, and an activity's roles stay as they were.

Under KDE's Breeze a form kept every field at its size hint, so the activity's role
pickers were drawn a few letters wide. And those pickers had no "(none)": an activity
without a Display showed the first device instead, and saving the editor gave it that
device as its screen.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def grown(qapp_or_skip):
    from PyQt6.QtWidgets import QApplication, QStyleFactory

    from afterglow.gui.ui_helpers import let_form_fields_grow
    app = QApplication.instance()
    name = app.style().name()
    let_form_fields_grow(app)
    yield app
    app.setStyle(QStyleFactory.create(name))


def test_a_forms_fields_take_the_width_they_are_given(grown):
    from PyQt6.QtWidgets import QComboBox, QFormLayout, QWidget
    page = QWidget()
    form = QFormLayout(page)
    combo = QComboBox()
    combo.addItem("TV")
    form.addRow("Display:", combo)
    page.resize(700, 100)
    page.show()
    grown.processEvents()
    assert form.fieldGrowthPolicy() == QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
    assert combo.width() > 3 * combo.sizeHint().width()


def test_installing_it_twice_wraps_the_style_once(grown):
    from afterglow.gui.ui_helpers import _FormsGrow, let_form_fields_grow
    let_form_fields_grow(grown)
    assert isinstance(grown.style(), _FormsGrow)
    assert not isinstance(grown.style().baseStyle(), _FormsGrow)


DEVICES = [{"id": "1", "label": "TV", "type": "Television"},
           {"id": "2", "label": "Receiver", "type": "Receiver"}]


def test_an_activity_without_a_display_keeps_none(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityEditor
    existing = {"id": "1001", "label": "Listen to Radio", "control": "2",
                "volume": "2", "roles": {"PASSTHROUGH2": "1"}}
    editor = ActivityEditor(DEVICES, existing=existing, remote="harmony-900")
    assert editor.p1.disp_combo.currentText() == "(none)"
    spec = editor._collect()
    assert spec["display"] is None and spec["control"] == "2"
    assert spec["roles"] == {"PASSTHROUGH2": "1"}


def test_a_role_that_is_set_is_still_shown(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityEditor
    editor = ActivityEditor(DEVICES, existing={"id": "1001", "display": "1",
                                               "control": "1"}, remote="harmony-900")
    assert editor.p1.disp_combo.currentData() == "1"
    assert editor.p1.disp_combo.currentText() == "TV"


@pytest.mark.parametrize("name", ["ControlGroup_HardButtons", "ControlGroup_Transport",
                                  "ControlGroup_Numbers", "ControlGroup_Misc",
                                  "ControlGroup_Discs", "ControlGroup_GameController",
                                  "ControlGroup_Favorites", "HideModePlayGroup"])
def test_an_activity_property_seen_in_real_configurations_has_a_name(name):
    from afterglow import properties
    assert properties.describe("activity", name)["label"] != name
