"""An activity's startup order must survive being opened and saved unchanged.

Startup is one ordered list and an input switch is an ordinary step in it. Holding
inputs in a separate table forces the editor to pick which switch to hand the builder as
the `input` field - which is always written last - leaving any other ordering between
switches and delays to be reconstructed rather than preserved.
"""


def devices():
    return [{"id": "40009001", "label": "Projector", "type": "Projector",
             "commands": [["PowerOn", "On", "", "01", None]],
             "inputs": [["HDMI 1", None]]},
            {"id": "40009002", "label": "Receiver", "type": "StereoReceiver",
             "commands": [["PowerOn", "On", "", "02", None]],
             "inputs": [["Bluray", None]]}]


def real_activity():
    """Shaped exactly like "Watch a Movie" as read off real hardware: the display
    switches first, waits for the picture to come up, then the receiver switches to
    match. `enter` is what the importer hands back - there is no top-level `input` key
    yet, because nothing has passed through the GUI."""
    return {
        "id": "50000002", "label": "Watch a Movie", "type": "VirtualDvd",
        "display": "40009001", "control": "40009002",
        "enter": [["input", "40009001", "HDMI 1"],
                  ["delay", "40009001", 3000],
                  ["input", "40009002", "Bluray"]],
        "leave": [], "roles": {}, "image_buttons": [], "soft_buttons": [],
        "hard_macros": {}, "properties": {},
    }


def collected(qapp_or_skip, existing):
    from afterglow.gui.activity_wizard import ActivityEditor
    return ActivityEditor(devices(), existing=existing)._collect()


def rebuilt_enter(spec):
    """What the builder actually emits for EnterActions, in order - `enter` followed
    by the standing `input` switch, exactly as `_gen_activity` writes it.

    Normalised to tuples: the macro editor round-trips a step through Qt table cells,
    which is free to hand a step back as a list where it started as a tuple. That is
    not a difference in what gets built - `_action()` reads either - so comparing the
    step contents rather than their container type is comparing what actually matters.
    """
    steps = list(spec.get("enter") or [])
    if spec.get("input"):
        steps.append(["input", spec["input"][0], spec["input"][1]])
    return [tuple(step) for step in steps]


def test_opening_and_saving_does_not_move_the_delay(qapp_or_skip):
    """The concrete regression, checked by device identity rather than just position -
    a step count alone does not catch the bug, since the wrong switch being held back
    as `input` still leaves *a* switch at each end of a two-switch, one-delay activity."""
    steps = rebuilt_enter(collected(qapp_or_skip, real_activity()))
    assert steps[0] == ("input", "40009001", "HDMI 1"), steps    # projector, first
    assert steps[1][0] == "delay", steps                          # the wait, unmoved
    assert steps[2] == ("input", "40009002", "Bluray"), steps    # receiver, last


def test_opening_and_saving_reproduces_the_exact_sequence(qapp_or_skip):
    before = real_activity()
    after = collected(qapp_or_skip, before)
    assert rebuilt_enter(after) == [tuple(s) for s in before["enter"]]


def test_a_single_switch_is_unaffected(qapp_or_skip):
    """The case that was already correct, and has to stay correct: with only one
    switch, first and last are the same row."""
    before = {**real_activity(), "enter": [["command", "40009001", "InputHdmi1"],
                                           ["delay", "40009001", 2000],
                                           ["input", "40009002", "CBL/SAT"]]}
    after = collected(qapp_or_skip, before)
    assert rebuilt_enter(after) == [tuple(s) for s in before["enter"]]


def test_reopening_a_saved_activity_is_stable(qapp_or_skip):
    """Save once, then open the *result* and save again - the second round has a
    standing `input` field instead of two embedded switches, which is the situation
    that made the first version of this fix flip-flop on which device was primary."""
    once = collected(qapp_or_skip, real_activity())
    twice = collected(qapp_or_skip, once)
    assert rebuilt_enter(twice) == rebuilt_enter(once)
