"""Duplicate on a device's or an activity's row: a copy under its own id and name,
opened in its editor, saved under the original - or not made at all if the editor is
cancelled. An activity that works, copied to change one input, was the request."""
import pytest

from afterglow import project_devices


def _project():
    tv = {"id": "40000001", "label": "TV", "mfr": "Sony", "model": "KD-55",
          "type": "Television", "commands": [["PowerOn"], ["InputHdmi1"]]}
    amp = {"id": "40000002", "label": "AVR", "type": "Amplifier",
           "commands": [["InputSat"], ["InputDvd"]]}
    watch = {"id": "10000001", "label": "Watch TV", "type": "VirtualTelevisionN",
             "display": tv["id"], "volume": amp["id"], "control": tv["id"],
             "input": [amp["id"], "InputSat"], "activity_button": "Watch",
             "layouts": {"sound": {"device": amp["id"]}, "picture": {"device": None}}}
    return {"devices": [tv, amp], "activities": [watch],
            "power_off_all": [tv["id"], amp["id"]],
            "settings": {"rf": {"receivers": [{"label": "1", "mac": "00"}],
                                "assign": {tv["id"]: "1-A"}}}}


def test_a_copy_is_numbered_after_what_is_taken():
    assert project_devices.copy_label("Watch TV", ["Watch TV"]) == "Watch TV (2)"
    assert project_devices.copy_label("Watch TV", ["Watch TV", "watch tv (2)"]) \
        == "Watch TV (3)"
    # a copy of a copy counts on from the original's name
    assert project_devices.copy_label("Watch TV (2)", ["Watch TV", "Watch TV (2)"]) \
        == "Watch TV (3)"


def test_an_activity_copy_has_its_own_id_and_name_and_not_the_original_s_key():
    project = _project()
    original = project["activities"][0]
    copy = project_devices.activity_copy(project["activities"], original, "10000002")
    assert copy["id"] == "10000002" and copy["label"] == "Watch TV (2)"
    assert "activity_button" not in copy
    assert copy["input"] == original["input"] and copy["layouts"] == original["layouts"]
    # a copy, not the same lists: changing one leaves the other
    copy["input"][1] = "InputDvd"
    copy["layouts"]["sound"]["device"] = None
    assert original["input"][1] == "InputSat"
    assert original["layouts"]["sound"]["device"] == "40000002"


def test_a_device_copy_goes_under_its_original_and_off_turns_it_off():
    project = _project()
    tv = project["devices"][0]
    copy = project_devices.device_copy(project, tv, "40000003")
    assert copy["label"] == "TV (2)" and copy["commands"] == tv["commands"]
    assert copy["commands"] is not tv["commands"]
    project_devices.place_device_copy(project, tv, copy)
    assert [d["id"] for d in project["devices"]] == ["40000001", "40000003", "40000002"]
    assert "40000003" in project["power_off_all"]


def test_a_device_left_out_of_off_stays_out_for_its_copy():
    project = _project()
    project["power_off_all"] = ["40000002"]
    tv = project["devices"][0]
    copy = project_devices.device_copy(project, tv, "40000003")
    project_devices.place_device_copy(project, tv, copy)
    assert project["power_off_all"] == ["40000002"]


def _accepting(monkeypatch, cls, seen=None):
    def exec_(self):
        if seen is not None:
            seen["title"] = self.windowTitle()
        self.accept()
        return 1
    monkeypatch.setattr(cls, "exec", exec_)


def test_duplicate_activity_opens_the_copy_and_saves_it_under_the_original(
        qapp_or_skip, monkeypatch):
    from afterglow.gui import tabs
    seen = {}
    real = tabs.ActivityEditor

    def editor(*args, **kwargs):
        made = real(*args, **kwargs)
        seen["name"] = made.p0.label_edit.text()
        return made
    _accepting(monkeypatch, real, seen)
    monkeypatch.setattr(tabs, "ActivityEditor", editor)
    project = _project()
    project["activities"].append({"id": "10000009", "label": "Listen", "type":
                                  "VirtualMusicServer", "display": None,
                                  "control": "40000002"})
    tab = tabs.ActivitiesTab(project)
    assert [a.text() for a in tab.cards.card(0).menu.actions()] == ["Duplicate", "Delete"]
    tab.cards.card(0).menu.actions()[0].trigger()     # the row menu's entry
    assert seen["title"] == "Duplicate Activity"
    assert seen["name"] == "Watch TV (2)"
    assert [a["label"] for a in project["activities"]] == ["Watch TV", "Watch TV (2)",
                                                            "Listen"]
    copy = project["activities"][1]
    assert copy["id"] not in ("10000001", "10000009")
    assert copy["display"] == "40000001" and copy["volume"] == "40000002"
    assert copy["layouts"]["sound"]["device"] == "40000002"
    # the key still starts the original
    assert project["activities"][0]["activity_button"] == "Watch"
    assert copy.get("activity_button") != "Watch"
    assert tab.cards.count() == 3


def test_a_cancelled_duplicate_adds_nothing(qapp_or_skip, monkeypatch):
    from afterglow.gui import tabs
    monkeypatch.setattr(tabs.ActivityEditor, "exec", lambda self: 0)
    monkeypatch.setattr(tabs.DeviceEditor, "exec", lambda self: 0)
    project = _project()
    tabs.ActivitiesTab(project).duplicate_activity(0)
    tabs.DevicesTab(project, []).duplicate_device(0)
    assert len(project["activities"]) == 1 and len(project["devices"]) == 2
    assert project["power_off_all"] == ["40000001", "40000002"]


def test_duplicate_device_is_new_goes_out_where_the_original_does(
        qapp_or_skip, monkeypatch):
    from afterglow.gui import tabs
    from afterglow.gui.project import new_device_ids
    from afterglow.gui.rf_routing import rf_get
    seen = {}
    real = tabs.DeviceEditor

    _accepting(monkeypatch, real, seen)
    project = _project()
    tab = tabs.DevicesTab(project, [])
    names = [a.text() for a in tab.cards.card(0).menu.actions()]
    assert names[-2:] == ["Duplicate", "Delete"]
    duplicate = next(a for a in tab.cards.card(0).menu.actions() if a.text() == "Duplicate")
    assert not duplicate.icon().isNull()
    duplicate.trigger()
    assert seen["title"] == "Duplicate Device"
    assert [d["label"] for d in project["devices"]] == ["TV", "TV (2)", "AVR"]
    copy = project["devices"][1]
    assert copy["id"] not in ("40000001", "40000002")
    assert [c[0] for c in copy["commands"]] == ["PowerOn", "InputHdmi1"]
    assert new_device_ids(project) == (copy["id"],)
    assert rf_get(project, copy["id"]) == "1-A"
    assert copy["id"] in project["power_off_all"]
    # nothing that used the original is moved onto the copy
    assert project["activities"][0]["display"] == "40000001"


@pytest.mark.parametrize("row", [0, 1])
def test_the_title_says_it_is_a_copy(qapp_or_skip, monkeypatch, row):
    from afterglow.gui import tabs
    titles = []
    monkeypatch.setattr(tabs.ActivityEditor, "exec",
                        lambda self: titles.append(self.windowTitle()) or 0)
    project = _project()
    project["activities"].append(dict(project["activities"][0], id="10000002",
                                      label="Other"))
    tabs.ActivitiesTab(project).duplicate_activity(row)
    assert titles == ["Duplicate Activity"]
