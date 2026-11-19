"""An activity's Sound and Picture layouts: the defaults Logitech's software chose, and a
project's choices over them (activity_layouts)."""
from afterglow import activity_layouts as layouts


def _device(did, kind, *commands):
    """A device with ``commands``, each a name or (name, key)."""
    rows = []
    for command in commands:
        name, key = command if isinstance(command, tuple) else (command, None)
        rows.append([name, name, None, None, key])
    return {"id": did, "type": kind, "label": did, "commands": rows}


MENU = [(key, key) for key in ("DirectionUp", "DirectionDown", "DirectionLeft",
                               "DirectionRight", "Select", "Menu", "Exit", "Info", "Guide")]
VOLUME = [("VolumeUp", "VolumeUp"), ("VolumeDown", "VolumeDown"), ("Mute", "VolumeMute")]
TV = _device("tv", "Television", *MENU, *VOLUME, "PictureMode", "Aspect", "Sleep")
AMP = _device("amp", "Receiver", *MENU, *VOLUME, "SurroundMode", "InputTV")
BOX = _device("box", "Satellite", *MENU, "Record")
RADIO = _device("radio", "RadioTuner", *VOLUME)
DEVICES = [TV, AMP, BOX, RADIO]


def _activity(**fields):
    return {"id": "1", "label": "Watch TV", "power_on_devices": ["tv", "amp", "box"],
            "control": "box", "volume": "amp", "display": "tv", **fields}


def test_sound_is_the_amplifiers_volume_and_picture_the_tvs_menu_never_the_source_box():
    resolved = layouts.resolve(_activity(), DEVICES)
    assert resolved["sound"]["device"] == "amp"
    assert sorted(resolved["sound"]["hard_macros"]) == ["VolumeDown", "VolumeMute",
                                                        "VolumeUp"]
    assert resolved["sound"]["hard_macros"]["VolumeMute"] == [["command", "amp", "Mute"]]
    assert resolved["picture"]["device"] == "tv"
    assert set(resolved["picture"]["hard_macros"]) == set(layouts.PICTURE_KEYS)
    assert all(macro[0][1] == "tv" for macro in resolved["picture"]["hard_macros"].values())


def test_a_tv_playing_its_own_sound_also_works_its_sound_menu_from_the_sound_layout():
    resolved = layouts.resolve(_activity(volume="tv", power_on_devices=["tv", "box"]),
                               DEVICES)
    assert resolved["sound"]["device"] == "tv"
    assert set(layouts.VOLUME_KEYS + layouts.MENU_KEYS) == set(
        resolved["sound"]["hard_macros"])


def test_picture_finds_the_screen_when_the_display_is_the_source_and_a_radio_has_none():
    # an activity whose Display names the box it watches: the TV it turns on shows it
    assert layouts.resolve(_activity(display="box"), DEVICES)["picture"]["device"] == "tv"
    radio = {"id": "2", "label": "Radio", "power_on_devices": ["radio"],
             "volume": "radio", "display": "radio"}
    assert set(layouts.resolve(radio, DEVICES)) == {"sound"}


def test_without_types_to_go_by_picture_is_the_display():
    untyped = [dict(device, type="HomeAppliance") for device in DEVICES]
    assert layouts.resolve(_activity(display="box"), untyped)["picture"]["device"] == "box"


def test_screen_buttons_are_the_devices_sound_or_picture_settings_on_no_key():
    resolved = layouts.resolve(_activity(), DEVICES)
    assert resolved["sound"]["soft_buttons"] == [["SurroundMode", "amp", "SurroundMode"]]
    assert resolved["picture"]["soft_buttons"] == [["PictureMode", "tv", "PictureMode"],
                                                   ["Aspect", "tv", "Aspect"]]


def test_a_projects_choices_override_the_defaults_key_by_key():
    activity = _activity(layouts={
        "sound": {"hard_macros": {"Red": [["command", "amp", "InputTV"]], "VolumeMute": []},
                  "soft_buttons": []},
        "picture": {"device": None}})
    resolved = layouts.resolve(activity, DEVICES)
    assert set(resolved) == {"sound"}
    # an empty macro keeps the activity's own command on that key
    assert sorted(resolved["sound"]["hard_macros"]) == ["Red", "VolumeDown", "VolumeUp"]
    assert resolved["sound"]["soft_buttons"] == []


def test_another_device_takes_its_own_defaults():
    activity = _activity(layouts={"sound": {"device": "tv"}})
    resolved = layouts.resolve(activity, DEVICES)["sound"]
    assert resolved["device"] == "tv"
    assert resolved["hard_macros"]["VolumeUp"] == [["command", "tv", "VolumeUp"]]


def test_what_a_project_stores_is_only_what_differs_from_the_defaults():
    activity = _activity()
    assert layouts.minimal(activity, DEVICES, layouts.resolve(activity, DEVICES)) == {}
    changed = layouts.resolve(activity, DEVICES)
    changed["picture"]["hard_macros"].pop("Guide")
    changed["sound"]["soft_buttons"] = []
    del changed["picture"]["hard_macros"]["Info"]
    stored = layouts.minimal(activity, DEVICES, changed)
    assert stored == {"sound": {"soft_buttons": []},
                      "picture": {"hard_macros": {"Info": [], "Guide": []}}}
    assert layouts.resolve(dict(activity, layouts=stored), DEVICES) == changed
    # a layout the configuration does not have is stored as none
    assert layouts.minimal(activity, DEVICES, {}) == {"sound": {"device": None},
                                                      "picture": {"device": None}}


def test_a_devices_own_layouts_go_by_its_type_unless_the_project_says():
    assert layouts.device_kinds(TV) == ("sound", "picture")
    assert layouts.device_kinds(AMP) == ("sound",)
    assert layouts.device_kinds(BOX) == ("sound", "picture")
    assert layouts.device_kinds({"type": "Light"}) == ()
    assert layouts.device_kinds(dict(TV, layouts=["picture"])) == ("picture",)
    own = layouts.device_layout(AMP, "sound")
    assert own["device"] == "amp" and "DirectionUp" in own["hard_macros"]
    assert own["soft_buttons"] == [["SurroundMode", "amp", "SurroundMode"]]


def test_sound_and_picture_settings_are_the_ones_logitechs_database_files_there():
    for name in ("DolbyProLogic", "VolumeCenterUp", "Mono/Stereo", "Bass +"):
        assert layouts.is_layout_command("sound", name), name
    for name in ("PipSwap", "Aspect16:9", "P.Size", "ContrastUp", "Picture Adjust"):
        assert layouts.is_layout_command("picture", name), name
    for name in ("Sleep", "Netflix", "PowerToggle", "Number1", "Eject"):
        assert not layouts.is_layout_command("sound", name), name
        assert not layouts.is_layout_command("picture", name), name
