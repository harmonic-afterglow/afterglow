"""What a remote can be told belongs to that remote.

The device types, the activity types and the physical keys come out of each model's own
firmware - one movie clip per type, and whatever buttons the case has. Held as constants
in the code they said, wrongly, that every Harmony is a Harmony 900: a remote with no
touchscreen has no screen buttons, and one with fewer keys has fewer slots.

They now live in `library/remotes/<model>.json`, and the point of these tests is that
moving them actually changed the behaviour rather than only the file they sit in - a
second model with a smaller vocabulary has to get different answers, and the builder has
to check an activity against the remote it is building for.
"""
import json

import pytest

from afterglow import remotes, vocabulary


def test_the_profile_carries_the_vocabulary():
    profile = remotes.get("harmony-900")
    assert len(profile.device_types) == 38
    assert len(profile.activity_types) == 23
    assert len(profile.hard_keys) == 41


def test_the_labels_are_ours_and_the_identifiers_are_not():
    """The firmware has no name table, so every identifier needs a readable label and a
    run-together one must actually have been separated."""
    import re
    for identifier, label in remotes.get("harmony-900").device_types.items():
        assert label
        if re.search(r"[a-z][A-Z]", identifier):
            assert label != identifier, identifier


def test_activity_types_keep_the_order_the_profile_gives_them():
    """The list is ordered by identifier, so the labels are not in alphabetical order -
    it opens "Listen to the CD Jukebox", "Listen to a CD", "Watch a DVD". Anything that
    sorts by the visible text would silently rearrange the menu, and a round trip
    through JSON is where an order quietly becomes something else."""
    types = remotes.get("harmony-900").activity_types
    assert types[0] == ("Listen to the CD Jukebox", "VirtualCdJukebox")
    assert [i for _l, i in types] == sorted(i for _l, i in types)
    assert [l for l, _i in types] != sorted(l for l, _i in types)


def test_asking_by_id_and_by_profile_agree():
    profile = remotes.get("harmony-900")
    assert vocabulary.device_types("harmony-900") == vocabulary.device_types(profile)
    assert vocabulary.activity_types() == vocabulary.activity_types(profile)


def test_a_profile_that_has_not_been_worked_out_answers_empty():
    """Rather than inheriting the Harmony 900's, which is the whole bug being fixed."""
    unknown = remotes.RemoteProfile(id="x", model="Some Other Harmony")
    assert unknown.device_types == {} and unknown.activity_types == []
    assert unknown.hard_keys == []


# the part that proves it is per-remote and not just relocated
def other_remote(tmp_path, **vocab):
    """A second model on disk, with a deliberately smaller vocabulary."""
    profile = json.loads((remotes.LIBRARY / "harmony-900.json").read_text())
    profile.update(id="test-model", model="Test Model",
                   identity={"arch": 15, "skin": 99}, status="untested")
    profile["vocabulary"] = {
        "device_types": {"Television": "Television"},
        "activity_types": [["Watch TV", "VirtualTelevisionN"]],
        "hard_keys": ["VolumeUp"],
        **vocab,
    }
    (tmp_path / "harmony-900.json").write_text(
        (remotes.LIBRARY / "harmony-900.json").read_text())
    (tmp_path / "test-model.json").write_text(json.dumps(profile))
    return tmp_path


def test_a_second_model_gets_its_own_answers(tmp_path):
    library = other_remote(tmp_path)
    small = remotes.get("test-model", library)
    big = remotes.get("harmony-900", library)
    assert small.device_types == {"Television": "Television"}
    assert len(big.device_types) == 38, "the two models must not share one list"
    assert small.hard_keys == ["VolumeUp"]


def test_the_builder_checks_against_the_remote_it_builds_for():
    """An activity type is valid or not depending on which remote it is for. Checked
    against a global list, a model without that type would have accepted it."""
    from afterglow.backends.harmony_pk.builder.activities import _known_activity_types
    known = _known_activity_types("harmony-900")
    assert "VirtualTelevisionN" in known
    assert "PowerOff" in known, "the all-off scene is written as an activity"


def test_an_unknown_type_names_the_model_it_was_checked_against():
    from afterglow.backends.harmony_pk.builder.activities import _check_activity_type
    with pytest.raises(ValueError, match="Harmony 900"):
        _check_activity_type("VirtualNonsense", "My Activity", "harmony-900")


def test_an_activity_can_remap_every_key_its_remote_has(qapp_or_skip, tmp_path):
    """GitHub #5. The page offered a fixed nineteen keys, so Guide, Info and the rest
    could not be given an activity's own action - and it was the same nineteen for
    any remote. It is the profile's list, plus any key an imported activity binds."""
    from afterglow.gui.activity_wizard import ActivityHardButtonsPage
    page = ActivityHardButtonsPage([], {"hard_macros": {"Mystery": []}},
                                   remote=remotes.get("harmony-900"))
    assert page.slots[:-1] == remotes.get("harmony-900").hard_keys
    assert "Guide" in page.slots and page.slots[-1] == "Mystery"
    small = remotes.get("test-model", other_remote(tmp_path))
    assert ActivityHardButtonsPage([], {}, remote=small).slots == ["VolumeUp"]


def test_the_vocabulary_survives_a_round_trip_through_json():
    profile = remotes.get("harmony-900")
    again = remotes._from_json(profile.to_json())
    assert again.device_types == profile.device_types
    assert again.activity_types == profile.activity_types
    assert again.hard_keys == profile.hard_keys


# the Advanced tab's options are the remote's own
def library_with(tmp_path, device_props):
    """A second model declaring a different set of device properties."""
    profile = json.loads((remotes.LIBRARY / "harmony-900.json").read_text())
    profile.update(id="test-model", model="Test Model",
                   identity={"arch": 15, "skin": 99}, status="untested")
    profile["properties"] = {"device": device_props, "activity": {}}
    (tmp_path / "harmony-900.json").write_text(
        (remotes.LIBRARY / "harmony-900.json").read_text())
    (tmp_path / "test-model.json").write_text(json.dumps(profile))
    return remotes.get("test-model", tmp_path)


def test_a_remote_can_have_an_option_the_900_does_not(tmp_path):
    """The reason this moved. Another model is not a subset of this one - it can carry
    settings nothing here has ever heard of, and they have to survive being offered,
    described as far as anything knows, and written back."""
    from afterglow import properties as props
    profile = library_with(tmp_path, {
        "BacklightBrightness": {"applies_to": "all", "default": "5",
                                "read_by": "remote", "when_absent": "false"},
    })
    cat = props.catalog(profile)
    assert "BacklightBrightness" in cat["device"]
    assert "AlwaysOn" not in cat["device"], "it inherited the 900's list"


def test_a_remote_can_lack_an_option_the_900_has(tmp_path):
    """And the reverse: a property the 900 has must not be offered for a model that
    does not have it, however well described it is here."""
    from afterglow import properties as props
    profile = library_with(tmp_path, {
        "AlwaysOn": {"applies_to": "all", "default": "false", "read_by": "remote",
                     "when_absent": "skipped: ..."},
    })
    cat = props.catalog(profile)
    assert set(cat["device"]) == {"AlwaysOn"}
    for absent in ("NumDiscs", "TunerInput", "Scart", "Dimmer"):
        assert absent not in cat["device"], f"{absent} leaked in from the 900"


def test_a_property_only_the_remote_knows_is_still_usable(tmp_path):
    """Declared by the model, described by nobody. It has to come through presentable
    rather than as a hole - the same rule that keeps an unrecognised property in an
    imported configuration visible."""
    from afterglow import properties as props
    profile = library_with(tmp_path, {
        "SomethingNewEntirely": {"applies_to": "all", "default": "7"},
    })
    cat = props.catalog(profile)
    entry = props.describe("device", "SomethingNewEntirely", cat)
    assert entry["label"] == "SomethingNewEntirely"
    assert entry["type"] == "text", "an undescribed property must still be editable"
    assert entry["default"] == "7", "what the remote does know was dropped"


def test_the_shared_descriptions_still_reach_the_merged_catalogue():
    """The other half of the split: the remote says which and the catalogue says what,
    and a property must end up with both."""
    from afterglow import properties as props
    entry = props.catalog()["device"]["AlwaysOn"]
    assert entry["type"] == "bool" and entry["casing"] == "lower"   # from definitions
    assert entry["read_by"] == "remote"                              # from the profile
    assert "keep this device switched on" in entry["description"]


def test_scart_is_offered_even_though_no_configuration_has_ever_had_it(qapp_or_skip):
    """Measuring applies_to from observations gave SCART an empty list, and filtering
    by that hid a real setting from every device type. Never observed is not never
    applicable - whether a device is on a SCART lead is about the wiring, not the kind
    of thing it is."""
    from afterglow.gui.properties_editor import PropertiesEditor
    for kind in ("Television", "Receiver", "DvdCd"):
        assert "Scart" in PropertiesEditor("device", {}, kind=kind)._rows, kind


# which remote a project is for
def two_verified(tmp_path):
    """A library where a second model has also been verified."""
    profile = json.loads((remotes.LIBRARY / "harmony-900.json").read_text())
    profile.update(id="test-model", model="Test Model", identity={"arch": 15, "skin": 99})
    (tmp_path / "harmony-900.json").write_text(
        (remotes.LIBRARY / "harmony-900.json").read_text())
    (tmp_path / "test-model.json").write_text(json.dumps(profile))
    return tmp_path


def test_a_project_is_for_the_remote_it_names():
    project = {"settings": {"remote": "harmony-900"}}
    assert remotes.for_project(project).id == "harmony-900"


def test_a_project_naming_no_remote_gets_the_one_verified_model():
    assert remotes.for_project({"settings": {}}).id == remotes.default().id
    assert remotes.default().verified


def test_with_two_verified_models_a_project_has_to_say_which(tmp_path):
    """Picking one would build for the wrong remote - quietly, which is the bug."""
    library = two_verified(tmp_path)
    with pytest.raises(remotes.UnknownRemote, match="settings.remote"):
        remotes.for_project({"settings": {}}, library)
    assert remotes.for_project(
        {"settings": {"remote": "test-model"}}, library).id == "test-model"


def test_the_keypad_picture_is_the_remotes_own():
    """Every button drawn is one the case has, under the name a configuration uses."""
    profile = remotes.get("harmony-900")
    layout = profile.hard_key_layout
    assert layout, "the 900 has a keypad"
    named = [cell["key"] for cell in layout if cell["key"]]
    assert set(named) <= set(profile.hard_keys)
    assert len(named) == len(set(named)), "a key drawn twice"
    assert remotes.RemoteProfile(id="x", model="Other").hard_key_layout == []


def test_no_shared_module_names_a_particular_remote():
    """Outside a backend and the profiles, a remote is whatever the project says.

    Seven modules each fell back to "harmony-900" on their own; a project for any other
    remote would have been imported, catalogued or built as a 900 by whichever one it
    reached first.
    """
    import tokenize
    from pathlib import Path

    import afterglow
    root = Path(afterglow.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        if "backends" in path.relative_to(root).parts:
            continue
        with path.open("rb") as handle:
            for token in tokenize.tokenize(handle.readline):
                if token.type == tokenize.STRING and token.string.strip("\"'rbf") in {
                        profile.id for profile in remotes.load_all()}:
                    offenders.append(f"{path.relative_to(root)}:{token.start[0]}")
    assert offenders == []


def test_the_900s_keys_are_the_names_its_configurations_bind():
    """Measured over eighteen Logitech configurations: the profile once said Replay, Skip,
    InputAV and Back, which none of them binds, and could not bind Pg Up or Pg Dn."""
    keys = remotes.get("harmony-900").hard_keys
    for name in ("SkipBack", "SkipForward", "UpArrow", "DownArrow", "NumberPlus",
                 "NumberEnter"):
        assert name in keys
    for name in ("Replay", "Skip", "InputAV", "Back", "Home", "InputHDMI"):
        assert name not in keys
    assert all(cell["key"] for cell in remotes.get("harmony-900").hard_key_layout)


def test_a_project_saved_with_the_old_key_names_is_renamed_on_load():
    from afterglow import project_devices
    project = {"settings": {"remote": "harmony-900"}, "devices": [], "activities": [
        {"hard_macros": {"Replay": [["command", "1", "Rew"]],
                         "Skip": [["command", "1", "Next"]], "Menu": []}}]}
    project["devices"] = [{"commands": [["Next", "Next", "", "", "Skip"],
                                        ["Both", "Both", "", "", ["InputAV", "Back"]]]}]
    assert project_devices.rename_hard_keys(
        project, remotes.get("harmony-900").hard_key_aliases) == 5
    assert set(project["activities"][0]["hard_macros"]) == {"SkipBack", "SkipForward", "Menu"}
    assert project["devices"][0]["commands"][0][4] == "SkipForward"
    assert project["devices"][0]["commands"][1][4] == ["NumberEnter", "NumberPlus"]


def test_the_catalogue_puts_commands_on_the_keys_the_900_has():
    from afterglow.corpus_provider import _hard_key
    keys = remotes.get("harmony-900").hard_keys
    assert _hard_key("SkipForward", keys) == "SkipForward"
    assert _hard_key("SkipBack", keys) == "SkipBack"
    assert _hard_key("Enter", keys) == "NumberEnter"
    assert _hard_key("Clear", keys) == "NumberPlus"
    assert _hard_key("PageUp", keys) == "UpArrow"


def test_the_page_keys_by_their_printed_names_bind_on_the_900():
    """GitHub #5: a hand-edited project bound PageUp and PageDown, which the remote ignores."""
    from afterglow import project_devices
    project = {"devices": [], "activities": [{"hard_macros": {
        "PageUp": [["command", "1", "LeftArrow", "Press"]],
        "PageDown": [["command", "1", "RightArrow", "Press"]]}}]}
    assert project_devices.rename_hard_keys(
        project, remotes.get("harmony-900").hard_key_aliases) == 2
    assert set(project["activities"][0]["hard_macros"]) == {"UpArrow", "DownArrow"}
