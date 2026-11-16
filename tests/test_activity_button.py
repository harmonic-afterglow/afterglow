"""Which activity key starts an activity, on a remote that has them (the Harmony 650 and
700's Watch TV, Watch a Movie and Listen to Music): chosen on the activity's first page,
one activity a key, as MyHarmony's "Customize Activity Buttons"."""
from __future__ import annotations



def _devices():
    return [{"id": "1", "label": "TV", "type": "Television",
             "commands": [["PowerOn", "On", "", "01", None]]}]


def _activity(**fields):
    return {"id": "9", "label": "Play Xbox", "type": "VirtualGeneric", "display": "1",
            "control": "1", "roles": {}, "image_buttons": [], "soft_buttons": [],
            "hard_macros": {}, "enter": [], "leave": [], "properties": {}, **fields}




def test_an_activity_keeps_its_key_and_can_be_given_another(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityEditor
    editor = ActivityEditor(_devices(), existing=_activity(activity_button="Music"),
                            remote="harmony-650")
    assert editor.p0.button_combo.currentData() == "Music"
    assert editor._collect()["activity_button"] == "Music"
    editor.p0.button_combo.setCurrentIndex(editor.p0.button_combo.findData("TV"))
    assert editor._collect()["activity_button"] == "TV"
    editor.p0.button_combo.setCurrentIndex(0)                  # None
    assert "activity_button" not in editor._collect()


def test_a_remote_without_activity_keys_offers_none_and_keeps_what_it_had(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityEditor
    editor = ActivityEditor(_devices(), existing=_activity(activity_button="Music"),
                            remote="harmony-one")
    assert editor.p0.button_combo is None
    assert editor._collect()["activity_button"] == "Music"


def test_a_key_starts_one_activity():
    from afterglow.gui.activity_wizard import one_activity_a_button
    first, second = _activity(activity_button="TV"), _activity(id="8")
    activities = [first, second]
    second["activity_button"] = "TV"
    one_activity_a_button(activities, second)
    assert "activity_button" not in first and second["activity_button"] == "TV"


def test_the_physical_buttons_picture_lights_the_activity_key_and_sets_it(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityEditor
    editor = ActivityEditor(_devices(), existing=_activity(activity_button="Movie"),
                            remote="harmony-650")
    view = editor.p4.keys_view
    assert view._chosen == "Watch a Movie"
    assert set(view._choosable) == {"Watch TV", "Watch a Movie", "Listen to Music"}
    view.fixed_clicked.emit("Watch TV")                      # a click in the picture
    assert editor.p0.button_combo.currentData() == "TV"
    assert editor._collect()["activity_button"] == "TV"
    view.fixed_clicked.emit("Watch TV")                      # again: off the key
    assert editor.p0.button_combo.currentData() is None
    assert view._chosen is None
    editor.p0.button_combo.setCurrentIndex(editor.p0.button_combo.findData("Music"))
    assert view._chosen == "Listen to Music"


def test_a_remote_without_activity_keys_offers_none_in_the_picture(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityEditor
    editor = ActivityEditor(_devices(), existing=_activity(), remote="harmony-one")
    assert editor.p4.keys_view._choosable == {}


def test_a_key_another_activity_has_can_be_taken_with_a_warning(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityEditor, one_activity_a_button
    movie = _activity(id="1", label="Movie night", activity_button="Movie")
    this = _activity(id="2", label="Play Xbox")
    activities = [movie, this]
    editor = ActivityEditor(_devices(), existing=this, remote="harmony-650",
                            activities=activities)
    combo = editor.p0.button_combo
    at = combo.findData("Movie")
    assert "Movie night" in combo.itemText(at)
    assert not editor.p0.button_warning.isVisibleTo(editor.p0)
    combo.setCurrentIndex(at)
    assert editor.p0.button_warning.isVisibleTo(editor.p0)
    assert "Movie night" in editor.p0.button_warning.text()
    # the picture says so too, and lights the key
    assert "Movie night" in editor.p4.keys_view._choosable["Watch a Movie"]
    spec = editor._collect()
    assert spec["activity_button"] == "Movie"
    activities[1] = spec
    one_activity_a_button(activities, spec)
    assert "activity_button" not in movie
    combo.setCurrentIndex(combo.findData("TV"))        # a free key: no warning
    assert not editor.p0.button_warning.isVisibleTo(editor.p0)


def test_a_project_naming_no_key_is_given_the_keys_its_build_would_bind():
    """The build gives the keys to the first three activities when none names one; the
    editor showed None for all of them. Written into the project as it is opened, the
    keys are what the editor shows, and they build the same."""
    from afterglow import project_devices
    project = {"settings": {"remote": "harmony-650"}, "devices": [],
               "activities": [_activity(id=str(i), label=f"A{i}") for i in range(4)]}
    project_devices.normalise_project(project)
    assert [a.get("activity_button") for a in project["activities"]] == [
        "Movie", "TV", "Music", None]
    # and a project that names one is left as it is
    project["activities"][1].pop("activity_button")
    project_devices.normalise_project(project)
    assert [a.get("activity_button") for a in project["activities"]] == [
        "Movie", None, "Music", None]


def test_a_new_activity_takes_the_first_free_key(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityWizard
    taken = [_activity(id="1", activity_button="TV")]
    wizard = ActivityWizard(_devices(), activities=taken, remote="harmony-650")
    assert wizard.identity.button_combo.currentData() == "Movie"
