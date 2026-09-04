"""Simple and Advanced are two views of one sequence, not two half-editors of it.

Simple is offered only when it can express everything the sequence does. A view that
silently drops what it cannot show would discard exactly the deliberate delay somebody
added for a slow projector.
"""
import pytest

# `gui.macro` imports PyQt6 itself, and this import runs at collection - before any
# fixture could skip. Without the guard the whole module errors on an interpreter that
# has no PyQt6 instead of skipping, which is what a build-layer contributor gets.
pytest.importorskip("PyQt6.QtWidgets")

from afterglow.gui.macro import (SimpleStartupList, StartupEditor,  # noqa: E402
                                 can_be_simple, why_not_simple)


def devices():
    return [{"id": "1", "label": "Projector", "type": "Projector",
             "commands": [["PowerOn", "On", "07", "01", None]],
             "inputs": [["HDMI 1", None]]},
            {"id": "2", "label": "Receiver", "type": "StereoReceiver",
             "commands": [["PowerOn", "On", "07", "02", None]],
             "inputs": [["Bluray", None]]}]


PLAIN = [["input", "1", "HDMI 1"], ["input", "2", "Bluray"]]
WITH_WAIT = [["input", "1", "HDMI 1"], ["delay", "1", 3000], ["input", "2", "Bluray"]]


def steps(editor):
    return [tuple(s) for s in editor.get_macro()]


# which view opens
def test_a_plain_sequence_opens_simple(qapp_or_skip):
    editor = StartupEditor(devices(), PLAIN)
    assert editor.stack.currentWidget() is editor.simple


def test_a_sequence_with_a_wait_opens_advanced(qapp_or_skip):
    editor = StartupEditor(devices(), WITH_WAIT)
    assert editor.stack.currentWidget() is editor.advanced


def test_an_empty_activity_opens_simple(qapp_or_skip):
    """A new activity should not be met with a step list."""
    assert StartupEditor(devices(), []).stack.currentWidget().__class__ is SimpleStartupList


# the rule
def test_simple_cannot_be_chosen_for_a_sequence_it_cannot_describe(qapp_or_skip):
    editor = StartupEditor(devices(), WITH_WAIT)
    assert not editor.simple_btn.isEnabled()
    assert "wait" in editor.reason.text()


def test_the_reason_names_what_is_in_the_way(qapp_or_skip):
    assert why_not_simple(PLAIN) == ""
    assert "a wait" in why_not_simple(WITH_WAIT)
    both = why_not_simple([["input", "1", "x"], ["delay", "1", 5], ["command", "2", "P"]])
    assert "a command" in both and "a wait" in both


def test_adding_a_wait_in_advanced_withdraws_simple(qapp_or_skip):
    """The rule has to hold as the sequence is edited, not only when it is opened.

    Driven the way a user does it - switch to Advanced, add a step - rather than by
    emitting the model's signal by hand, which is both unlike the real flow and, when
    tried, took the interpreter down with it.
    """
    editor = StartupEditor(devices(), PLAIN)
    assert editor.simple_btn.isEnabled()

    editor.advanced_btn.setChecked(True)                  # user picks Advanced
    editor.advanced._add_row("delay", "1", 3000)          # ...and adds a wait

    assert not editor.simple_btn.isEnabled(), "Simple stayed offered after a wait"
    assert "wait" in editor.reason.text()


# nothing is lost either way
@pytest.mark.parametrize("sequence", [PLAIN, WITH_WAIT, []],
                         ids=["plain", "with-wait", "empty"])
def test_a_sequence_survives_being_opened_and_read_back(sequence, qapp_or_skip):
    assert steps(StartupEditor(devices(), sequence)) == [tuple(s) for s in sequence]


def test_switching_to_advanced_carries_the_inputs_across(qapp_or_skip):
    editor = StartupEditor(devices(), PLAIN)
    editor.advanced_btn.setChecked(True)              # user picks Advanced
    assert editor.stack.currentWidget() is editor.advanced
    assert steps(editor) == [tuple(s) for s in PLAIN]


def test_switching_back_to_simple_carries_them_back(qapp_or_skip):
    editor = StartupEditor(devices(), PLAIN)
    editor.advanced_btn.setChecked(True)
    editor.simple_btn.setChecked(True)
    assert editor.stack.currentWidget() is editor.simple
    assert steps(editor) == [tuple(s) for s in PLAIN]


def test_a_wait_cannot_be_lost_by_going_through_simple(qapp_or_skip):
    """The one that matters. Somebody's projector needs three seconds; no sequence of
    clicks in this widget may quietly take that away."""
    editor = StartupEditor(devices(), WITH_WAIT)
    editor.simple_btn.setChecked(True)                # refused: it cannot be shown
    assert steps(editor) == [tuple(s) for s in WITH_WAIT], "the wait went missing"


def test_load_re_picks_the_view_for_the_new_sequence(qapp_or_skip):
    editor = StartupEditor(devices(), PLAIN)
    editor.load(WITH_WAIT)
    assert editor.stack.currentWidget() is editor.advanced
    assert steps(editor) == [tuple(s) for s in WITH_WAIT]
    editor.load(PLAIN)
    assert editor.stack.currentWidget() is editor.simple


def test_can_be_simple_is_honest_about_every_step_kind():
    assert can_be_simple([]) and can_be_simple(PLAIN)
    for kind in ("command", "delay", "state", "number"):
        assert not can_be_simple([["input", "1", "x"], [kind, "1", "y"]]), kind


def test_next_is_refused_until_a_device_is_selected(qapp_or_skip,
                                                    synthetic_device_templates):
    """Every source but "Not listed" produces a device by selection.

    Going on without one lands on a details page with nothing filled in - not an error
    the wizard can report, just an empty form the user has to work out. "Not listed" is
    exempt: it exists for devices no source has.
    """
    from afterglow.gui.device_wizard import SearchPage

    page = SearchPage(synthetic_device_templates, existing={})

    # A searching source, nothing chosen yet.
    for index in range(page.search_type.count()):
        if page.search_type.itemData(index) != "learn":
            page.search_type.setCurrentIndex(index)
            break
    assert page.isComplete() is False, "Next must be refused with nothing selected"

    # Choosing one enables it.
    template = dict(synthetic_device_templates[0])
    page._fire(template)
    assert page.isComplete() is True

    # "Not listed" needs no selection.
    learn = next(i for i in range(page.search_type.count())
                 if page.search_type.itemData(i) == "learn")
    page.search_type.setCurrentIndex(learn)
    assert page.isComplete() is True

    # Going back to a searching source discards the earlier choice: it belonged to a
    # different source, and the details page would be filled from nothing.
    for index in range(page.search_type.count()):
        if page.search_type.itemData(index) != "learn":
            page.search_type.setCurrentIndex(index)
            break
    assert page.isComplete() is False
