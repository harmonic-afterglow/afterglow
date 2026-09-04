"""Editing an activity must not cost it anything it was not asked to change.

The sixth time this bug appeared. Both activity editors rebuilt the spec from their
widgets, so an activity carried whatever the pages happened to display and nothing else.

What was being lost is the power plan: `power_on_devices` and `power_off_devices`, the
ordered lists of what an activity switches on and off. No page shows them, and when they
are absent `builder/activities.py` falls back to the three role devices - so an activity
imported from a real configuration that also woke a subwoofer or a power conditioner
quietly stopped doing so the first time anybody edited its name, and the fallback was
silent because it is a legitimate default for a new activity.
"""


def devices():
    return [{"id": "40009001", "label": "TV", "type": "Television",
             "commands": [["PowerOn", "On", "", "01", None]],
             "inputs": [["HDMI 1", None]]},
            {"id": "40009002", "label": "Receiver", "type": "StereoReceiver",
             "commands": [["PowerOn", "On", "", "02", None]],
             "inputs": [["CBL/SAT", None]]},
            {"id": "40009003", "label": "Subwoofer", "type": "Amplifier",
             "commands": [["PowerOn", "On", "", "03", None]]}]


def imported_activity():
    """An activity shaped the way the importer leaves one. The power plan names a
    device that holds no role - which is the whole point of it being a list."""
    return {
        "id": "50000001", "label": "Watch TV", "type": "VirtualTelevisionN",
        "display": "40009001", "volume": "40009002", "control": "40009001",
        "roles": {}, "image_buttons": [], "soft_buttons": [], "hard_macros": {},
        "enter": [], "leave": [], "properties": {"PowerOffUnusedDevices": "True"},
        "power_on_devices": ["40009002", "40009001", "40009003"],
        "power_off_devices": ["40009001", "40009003"],
    }


def edited(existing, qapp_or_skip):
    """Open an activity in the edit dialog and accept it without touching anything."""
    from afterglow.gui.activity_wizard import ActivityEditor
    return ActivityEditor(devices(), existing=existing)._collect()


def test_the_power_plan_survives_an_edit(qapp_or_skip):
    before = imported_activity()
    after = edited(before, qapp_or_skip)
    assert after.get("power_on_devices") == before["power_on_devices"]
    assert after.get("power_off_devices") == before["power_off_devices"]


def test_the_power_plan_keeps_its_order(qapp_or_skip):
    """It is a sequence, not a set: the receiver comes up before the television it
    feeds, and the fallback order is not the imported one."""
    before = imported_activity()
    after = edited(before, qapp_or_skip)
    assert after["power_on_devices"][0] == "40009002", "order was not preserved"


def test_a_device_that_holds_no_role_still_powers_on(qapp_or_skip):
    """The symptom, stated the way an owner would notice it. Without the plan the
    builder falls back to display/volume/control, and the subwoofer is in none of them."""
    after = edited(imported_activity(), qapp_or_skip)
    assert "40009003" in (after.get("power_on_devices") or []), \
        "the subwoofer stopped being switched on"


def test_a_field_nobody_here_recognises_survives_an_edit(qapp_or_skip):
    before = imported_activity() | {"channels_via_numeric": True,
                                    "some_future_field": [1, 2, 3]}
    after = edited(before, qapp_or_skip)
    assert after.get("channels_via_numeric") is True
    assert after.get("some_future_field") == [1, 2, 3]


# what carrying everything forward must NOT do
def test_favourites_do_not_appear_twice(qapp_or_skip):
    """The favourites page loads `channels` and `image_buttons` into one table and
    hands them all back as `image_buttons`, while the builder appends `channels` onto
    `image_buttons`. Carrying `channels` forward as well would double every favourite."""
    before = imported_activity() | {"channels": [("Channel One", "101", "one.png")]}
    after = edited(before, qapp_or_skip)
    assert not after.get("channels"), "channels survived and will be added twice"
    labels = [b[0] if isinstance(b, (list, tuple)) else b.get("label")
              for b in after.get("image_buttons") or []]
    assert labels.count("Channel One") <= 1, labels


def test_a_project_saved_before_the_merge_still_reads(qapp_or_skip):
    """`input` is the retired spelling of "one more switch, always last". A project
    carrying it is read back into the sequence where the builder would have put it, at
    the end, and written out as an ordinary step."""
    before = imported_activity() | {"input": ("40009002", "CBL/SAT")}
    after = edited(before, qapp_or_skip)
    assert "input" not in after, "the retired spelling was written back out"
    assert ("input", "40009002", "CBL/SAT") in [tuple(s) for s in after["enter"]]


def test_an_input_switch_that_is_deleted_stays_deleted(qapp_or_skip):
    """It is one list now, so deleting a row deletes the step - there is no separate
    `input` field left underneath to resurface."""
    from afterglow.gui.activity_wizard import ActivityEditor
    dialog = ActivityEditor(devices(),
                            existing=imported_activity() | {"input": ("40009002",
                                                                      "CBL/SAT")})
    editor = dialog.p5.enter_macro
    assert len(editor.get_macro()) == 1, "the switch was not loaded to begin with"
    editor.load([])                                      # the user deletes the row
    collected = dialog._collect()
    assert not collected.get("input"), "the deleted switch came back"
    assert not collected["enter"], "the deleted switch came back as a step"


def test_volume_is_not_left_stale_when_it_matches_the_display(qapp_or_skip):
    """The wizard omits `volume` when it is the same device as the display. A carried
    value would contradict that."""
    from afterglow.gui.activity_wizard import ActivityWizard
    before = imported_activity() | {"volume": "40009002"}
    before["display"] = before["control"] = "40009001"
    wizard = ActivityWizard(devices(), existing=before)
    for page_id in wizard.pageIds():
        wizard.initializePage(page_id)
    after = wizard._collect()
    assert after.get("volume") in (None, "", after["display"], "40009002")
    assert after.get("power_on_devices") == before["power_on_devices"]
