"""Cancel leaves the project as it was: the activity editor works on its own copy of the
activity, so nothing a page changes reaches the project unless the editor is saved. Its
physical buttons page once changed the project's keys in place, so a Cancel kept them."""
from __future__ import annotations

import copy

import pytest

from afterglow import remotes

DEVICES = [{"id": "1", "label": "TV", "type": "Television",
            "commands": [[name, name, "", "01", None]
                         for name in ("PowerOn", "Menu", "Guide", "Number1", "Number2")]}]


def _activity():
    return {"id": "9", "label": "Watch TV", "type": "VirtualGeneric", "display": "1",
            "control": "1", "roles": {}, "properties": {}, "enter": [], "leave": [],
            "hard_macros": {"Menu": [["command", "1", "Guide"]],
                            "Guide": [["command", "1", "Menu"]]},
            "soft_buttons": [{"label": "Menu", "action": ["command", "1", "Menu"]},
                             {"label": "Guide", "action": ["command", "1", "Guide"]}],
            "image_buttons": [["BBC One", "channel", "12", ""]]}


@pytest.mark.parametrize("remote", [profile.id for profile in remotes.load_all()])
def test_cancelling_the_activity_editor_changes_nothing(qapp_or_skip, remote):
    from afterglow.gui.activity_wizard import ActivityEditor
    activity = _activity()
    before = copy.deepcopy(activity)
    editor = ActivityEditor(DEVICES, existing=activity, remote=remote,
                            activities=[activity])
    keys = editor.p4
    rows = [keys._slot(row) for row in range(keys.table.rowCount())]
    if "Menu" in rows:                                  # cleared in the list
        keys.table.setCurrentCell(rows.index("Menu"), 0)
        keys._clear_btn_clicked()
    if keys.changed_list.count():                       # back to default in the picture
        keys.changed_list.setCurrentRow(0)
        keys._reset_listed()
    for page in (editor.p3b, editor.p3):                # a screen button, a favourite
        if hasattr(page, "table") and page.table.rowCount():
            page.table.setCurrentCell(0, 1)
            page._remove()
    editor.p0.label_edit.setText("Renamed")
    editor.reject()
    assert activity == before
