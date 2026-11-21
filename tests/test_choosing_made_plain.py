"""What blind first-time users ran into choosing things: a type list in the identifiers'
order (a set-top box forty rows down), every new activity a "Custom / Other", "SONY STAR"
picked for "Sony", "Apple Apple TV", a Logitech protocol by its identifier, and a remote
called "experimental" with nothing to say what that means."""
from __future__ import annotations

import pytest

from afterglow import project_devices, remotes, vocabulary


def test_device_types_are_offered_by_their_label():
    labels = vocabulary.device_types("harmony-900")
    shown = [labels[name] for name in vocabulary.device_type_choices("harmony-900")]
    assert shown == sorted(shown, key=str.casefold)
    assert shown[0] == "A/V switch" and "Set-top box" in shown


def test_activity_types_start_with_custom_then_go_by_label():
    shown = [label for label, _type in vocabulary.activity_type_choices("harmony-900")]
    assert shown[0] == "Custom / Other"
    assert shown[1:] == sorted(shown[1:], key=str.casefold)


@pytest.mark.parametrize("name, kind", [
    ("Watch TV", "VirtualTelevisionN"),
    ("watch  tv", "VirtualTelevisionN"),
    ("Movie night", "VirtualDvd"),
    ("Watch a movie on TV", "VirtualDvd"),
    ("Blu-ray", "VirtualDvd"),
    ("Play Xbox", "VirtualGameConsole"),
    ("Listen to Music", "VirtualMusicServer"),
    ("Radio", "VirtualRadioSimple"),
    ("Lights", None),
    ("", None),
])
def test_an_activity_s_name_says_its_type(name, kind):
    assert vocabulary.activity_type_for_name(name, "harmony-900") == kind


def test_a_remote_without_activity_types_gets_none_from_a_name():
    profile = remotes.get("harmony-900")
    import dataclasses
    bare = dataclasses.replace(profile, vocabulary={**profile.vocabulary,
                                                    "activity_types": []})
    assert vocabulary.activity_type_for_name("Watch TV", bare) is None


def test_a_new_activity_takes_the_type_its_name_says_until_one_is_chosen(qapp_or_skip):
    from afterglow.gui.activity_wizard import ActivityIdentityPage
    page = ActivityIdentityPage({}, remote=remotes.get("harmony-900"))
    assert page.type_combo.currentData() == "VirtualGeneric"
    page.label_edit.textEdited.emit("Watch TV")
    assert page.type_combo.currentData() == "VirtualTelevisionN"
    page.label_edit.textEdited.emit("Movie night")
    assert page.type_combo.currentData() == "VirtualDvd"
    page.type_combo.setCurrentIndex(page.type_combo.findData("VirtualTiVo"))
    page.type_combo.activated.emit(page.type_combo.currentIndex())
    page.label_edit.textEdited.emit("Watch TV")
    assert page.type_combo.currentData() == "VirtualTiVo"
    # an activity that has a type keeps it, whatever it is renamed
    kept = ActivityIdentityPage({"id": "1", "label": "TV", "type": "VirtualPvr"},
                                remote=remotes.get("harmony-900"))
    kept.label_edit.textEdited.emit("Movie night")
    assert kept.type_combo.currentData() == "VirtualPvr"


def test_the_device_type_list_is_in_label_order(qapp_or_skip):
    from afterglow.gui.device_wizard import IdentityPage
    project = {"devices": [], "settings": {"remote": "harmony-900"}}
    page = IdentityPage({"label": "Box", "type": "SetTopBox"}, project=project)
    texts = [page.type_combo.itemText(i) for i in range(page.type_combo.count())]
    assert texts == sorted(texts, key=str.casefold)
    assert page.type_combo.currentData() == "SetTopBox"


def test_the_name_typed_comes_first_whatever_its_case():
    from afterglow.gui.widgets import suggestion_order
    makers = ["SONY STAR", "Sony", "Sony Ericsson", "SonySat", "Hisony", "Sonytel"]
    assert suggestion_order(makers, "sony") == [
        "Sony", "Sony Ericsson", "SONY STAR", "SonySat", "Sonytel", "Hisony"]
    assert suggestion_order(makers, "Sony ")[0] == "Sony"


@pytest.mark.parametrize("maker, model, line", [
    ("Apple", "Apple TV (4K / 4th generation)", "Apple TV (4K / 4th generation)"),
    ("Samsung", "UN55TU7000", "Samsung UN55TU7000"),
    ("Sony", "SonyBDP", "Sony SonyBDP"),
    ("", "UE55", "UE55"),
    ("Denon", None, "Denon"),
])
def test_the_maker_is_said_once(maker, model, line):
    assert project_devices.make_and_model(maker, model) == line


def test_a_logitech_protocol_is_named_as_logitech_named_it():
    from afterglow.gui.device_wizard import _protocol_name
    device = {"portable_protocol_definitions": {"logitech-476-379492f53de8": {
        "provenance": {"source_name": "Sharp 48 Bit 2"}}}}
    assert _protocol_name("logitech-476-379492f53de8", device) == \
        "Sharp 48 Bit 2 (Logitech database)"
    assert _protocol_name("logitech-9-abc", {}) == "Logitech database"
    assert _protocol_name("samsung32", device) == "samsung32"


@pytest.mark.parametrize("category, kind", [
    ("Set Top Box", "SetTopBox"), ("Cable_Box", "CableBox"), ("Satellite", "Satellite"),
    ("Air Conditioner", "ClimateControl"), ("TV", "Television")])
def test_a_public_source_s_category_is_read_as_logitech_reads_it(category, kind):
    from afterglow.public_ir_sources import _device_type
    assert _device_type(category) == kind


def test_experimental_and_verified_are_explained(qapp_or_skip):
    from afterglow.gui.remote_bar import ChooseRemoteDialog, status_meaning
    from afterglow.qt.QtWidgets import QLabel
    from afterglow.gui.default_remote import remote_profiles
    experimental = next(p for p in remotes.load_all() if p.status == "experimental")
    assert "tried on few remotes" in status_meaning(experimental)
    dialog = ChooseRemoteDialog(remote_profiles(), "Your remote", "Which?")
    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Experimental:" in texts and "Verified:" in texts


def test_a_three_column_preview_is_as_wide_as_a_two_column_one(qapp_or_skip):
    """The 1100's device page, three buttons across, ran off the edge of the editor."""
    from afterglow.gui.screen_preview import ScreenPreview
    three, two = ScreenPreview(3, 3), ScreenPreview(2, 3)
    assert three._cells[0].width() * 3 <= two._cells[0].width() * 2
    three.set_buttons([("DirectionDown", None)])
    text = three._cells[0].text()
    assert text.endswith("..") and "DirectionDown".startswith(text[:-2]) and text.isascii()


def test_a_long_review_row_is_broken_into_lines(qapp_or_skip):
    from afterglow.gui.remote_bar import MigrationDialog
    detail = ", ".join(f"Setting number {n}" for n in range(20))
    dialog = MigrationDialog(
        remotes.get("harmony-900"), remotes.get("harmony-650"),
        [{"subject": "Remote's own settings", "change": "removed", "detail": detail}])
    child = dialog.tree.topLevelItem(0).child(0)
    assert "\n" in child.text(1) and child.toolTip(1) == detail
