"""The shipped data: remote profiles, type vocabulary, properties, icons.

These are the files that decide what the interface can offer. When one of them is wrong
the tool does not crash - it quietly cannot express something, or expresses it as
something else, which is how a donor's DVD player became a television.
"""
import json

import pytest
from conftest import ROOT

LIBRARY = ROOT / "src" / "afterglow" / "library"

from afterglow import preferences, properties, remotes


# remote profiles
def test_profiles_load():
    profiles = remotes.load_all()
    assert profiles, "no remote profiles"
    for profile in profiles:
        assert profile.id and profile.model
        assert profile.status in (remotes.VERIFIED, remotes.UNTESTED)


def test_every_config_is_identified(configs):
    from afterglow import ezhex
    for config in configs:
        header, _s, _z, _c = ezhex._split(config.read_bytes())
        assert remotes.identify(header).skin is not None


def test_only_verified_profiles_ship():
    """Untested remotes are not shipped at all - see docs/harmony_pk/remote-identities.md.

    A wrong config on a remote nobody has tried cannot be recovered from a vendor
    server any more, so an identity that has only been read is not offered as a
    build target.
    """
    assert [p.id for p in remotes.load_all() if not p.verified] == []


def test_untested_profile_refuses_to_build():
    """The gate itself still holds, for a profile someone adds locally."""
    profile = remotes.RemoteProfile(id="x", model="Untried", status=remotes.UNTESTED)
    with pytest.raises(remotes.NotWritable):
        profile.require_writable()


def test_an_unshipped_remote_is_still_named_on_import():
    """Dropping the profiles must not make a foreign config unidentifiable rubbish:
    the skin table still says which remote it belongs to."""
    header = b"<INTENDEDVERSION><PROTOCOL>12</PROTOCOL><SKIN>54</SKIN></INTENDEDVERSION>"
    with pytest.raises(remotes.UnknownRemote, match="Harmony One"):
        remotes.identify(header)


def test_verified_profiles_have_a_scaffold():
    from afterglow import paths
    for profile in remotes.load_all():
        if profile.verified:
            assert paths.scaffolds(profile.id).is_dir(), (
                f"{profile.model} is verified but has no scaffold to build from")


def test_profiles_have_unique_identities():
    seen = {}
    for profile in remotes.load_all():
        if profile.skin is None:
            continue
        assert profile.skin not in seen, f"skin {profile.skin} claimed twice"
        seen[profile.skin] = profile.id


# type vocabulary
def test_vocabulary_covers_every_real_config(configs, unpacked):
    """The type lists came from the firmware, so a real config cannot use a type that is
    missing from them. When they were hand-written, five real types were absent and
    editing such a device silently changed what it was."""
    import re
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui.constants import ACTIVITY_TYPES, DEVICE_TYPES
    activity_types = {t for _label, t in ACTIVITY_TYPES} | {"PowerOff"}
    for index, config in enumerate(configs):
        tree = unpacked(config, f"v{index}")
        xml = (tree / "userconfig" / "UserConfiguration.xml").read_text(errors="replace")
        for found in re.findall(r"<Device><Id>\d+</Id><Type>([^<]+)</Type>", xml):
            assert found in DEVICE_TYPES, f"{config.name}: device type {found!r} missing"
        for found in re.findall(r"<Activity><Id>-?\d+</Id><Type>([^<]+)</Type>", xml):
            assert found in activity_types, f"{config.name}: activity type {found!r} missing"


def test_every_type_has_a_readable_name():
    """The interface shows names, not identifiers. `TvDvdVcr` is not a name.

    The firmware has no name table for these - Logitech's friendly names lived on the
    web configurator - so the labels are ours and every type must have one.
    """
    import re
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui.constants import DEVICE_TYPE_LABELS, DEVICE_TYPES
    assert set(DEVICE_TYPES) == set(DEVICE_TYPE_LABELS)
    for identifier, label in DEVICE_TYPE_LABELS.items():
        assert label, identifier
        # A run-together identifier (`TvDvdVcr`, `SetTopBox`) must have been separated;
        # a single-word one (`Amplifier`) is already readable and may stand.
        if re.search(r"[a-z][A-Z]", identifier):
            assert label != identifier, f"{identifier} is not a readable name"


def test_type_labels_are_distinct():
    """Two types reading the same in the dropdown is a way to pick the wrong one."""
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui.constants import DEVICE_TYPE_LABELS
    labels = list(DEVICE_TYPE_LABELS.values())
    assert len(labels) == len(set(labels))


# properties
def test_property_catalogue_is_well_formed():
    catalogue = properties.catalog()
    assert catalogue[properties.DEVICE] and catalogue[properties.ACTIVITY]
    for scope in (properties.DEVICE, properties.ACTIVITY):
        for name, entry in catalogue[scope].items():
            assert entry["type"] in ("bool", "int", "enum", "text"), name
            if entry["type"] == "bool":
                assert entry.get("casing") in ("lower", "title"), name


def test_boolean_casing_follows_its_scope():
    """Devices write `false`, activities write `False`. The same word in the wrong case
    is a different string to the remote."""
    assert properties.format_value(properties.DEVICE, "AlwaysOn", True) == "true"
    assert properties.format_value(properties.ACTIVITY, "TrainingWheels", True) == "True"


def test_unknown_property_is_still_usable():
    entry = properties.describe(properties.DEVICE, "SomethingNobodyHasSeen")
    assert entry["known"] is False
    assert entry["label"] == "SomethingNobodyHasSeen"


def test_every_device_and_activity_property_is_catalogued(configs, unpacked):
    """Only device and activity properties: the catalogue does not claim to cover the
    config's own metadata (`version`, `ProtocolCacheHash`), the user's settings
    (`LocaleId`, `TimeDisplayFormat`) or per-command timing, which are handled elsewhere.
    """
    import xml.etree.ElementTree as ET
    catalogue = properties.catalog()
    for index, config in enumerate(configs):
        tree = unpacked(config, f"pr{index}")
        root = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
        for tag, scope in (("Device", "device"), ("Activity", "activity")):
            known = set(catalogue[scope])
            for element in root.findall(tag):
                for prop in element.findall("Properties/Property"):
                    name = prop.attrib.get("name")
                    assert name in known, (
                        f"{config.name}: {scope} property {name!r} is not in "
                        "library/properties.json")


# preferences
def test_a_preference_maps_to_one_file_each():
    """One setting, one file - and no two settings may claim the same file."""
    files = [filename for filename, _v, _x in preferences.PREFERENCES.values()]
    assert len(files) == len(set(files))
    for filename in files:
        assert filename.endswith(".dat")


def test_unset_preferences_are_not_written(tmp_path):
    """A preference the project does not mention must be left alone: the scaffold's
    value is a real remote's value, and replacing it with a guess is worse."""
    (tmp_path / "platformconfig").mkdir()
    written = preferences.apply(str(tmp_path), {"time_format": "Civilian"})
    assert written == ["system_timeformat.dat"]
    assert not (tmp_path / "platformconfig" / "system_sound.dat").exists()


def test_preferences_are_labelled():
    for key in preferences.PREFERENCES:
        assert key in preferences.LABELS, f"{key} has no label for the interface"


def test_every_preference_has_a_value_to_show():
    """No preference may present as "unset".

    A setting the user can see is one the build writes, so each is either a choice
    with a default among its options, or a number with a range.
    """
    for key in preferences.PREFERENCES:
        default = preferences.DEFAULTS[key]
        choices = preferences.CHOICES.get(key)
        if choices:
            assert str(default) in [value for _label, value in choices], key
        else:
            low, high = preferences.RANGES[key]
            assert low <= int(default) <= high, key


def test_theme_values_are_the_firmware_order_not_the_menu_order():
    """A trap worth a test: the remote lists Default, Diode, Tron, Polymer, but
    `GeneralOptions.done_theme()` stores hennessey 0, diode 1, **polymer 2, tron 3**,
    and the artwork is prefixed in a third order again. Reading the values off the
    menu gives two of the four themes the wrong number.
    """
    assert dict(preferences.CHOICES["theme"]) == {
        "Default (Hennessey)": "0", "Diode": "1", "Polymer": "2", "Tron": "3"}


def test_backlight_timeout_stays_within_two_digits():
    """The remote parses its own field with `int(text.substr(0, 2))`, so a 3-digit
    timeout reads back truncated and silently changes when that screen is opened."""
    _low, high = preferences.RANGES["backlight_timeout"]
    assert high <= 99


def test_a_declared_choice_matches_what_the_file_accepts():
    for key, (_file, values, _xml) in preferences.PREFERENCES.items():
        if values and key in preferences.CHOICES:
            offered = {value for _label, value in preferences.CHOICES[key]}
            assert offered <= set(values), f"{key} offers a value the remote has no name for"


# icons
def test_icons_cover_the_vocabulary():
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui import icons
    from afterglow.gui.constants import ACTIVITY_TYPES, DEVICE_TYPES
    if not icons.have_artwork():
        pytest.skip("icon artwork not extracted")
    assert icons.missing(DEVICE_TYPES) == []
    assert icons.missing([t for _label, t in ACTIVITY_TYPES]) == []


def test_button_glyphs_are_available():
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui import icons
    if not icons.have_artwork():
        pytest.skip("icon artwork not extracted")
    buttons = list((icons.ARTWORK / "buttons").glob("*.png"))
    assert len(buttons) > 50, "the button glyph set looks incomplete"


# library data
def test_library_files_are_valid_json():
    """Every shipped library file parses. Remote profiles are always present; the rest
    of the library is generated on import and is empty here."""
    seen = 0
    for folder in ("protocols", "devices", "captures", "remotes"):
        for path in (LIBRARY / folder).glob("*.json"):
            json.loads(path.read_text())
            seen += 1
    assert seen, "no library files were checked at all"


def test_device_definitions_reference_a_real_protocol():
    from afterglow.backends.harmony_pk import protocol_json
    catalogue = protocol_json.catalog()
    by_file = {path.name for path in (LIBRARY / "protocols").glob("*.json")}
    devices = sorted((LIBRARY / "devices").glob("*.json"))
    if not devices:
        pytest.skip("no devices are shipped; the library is generated on import")
    for path in devices:
        spec = json.loads(path.read_text())
        reference = spec.get("protocol", "")
        assert reference in by_file or reference in catalogue, (
            f"{path.name} references {reference!r}, which is not in the protocol library")


def test_the_builder_refuses_an_activity_type_the_remote_lacks():
    """An invented type is written into the config and the activity simply does not
    work; nothing about the build says so. The reference config carried
    `VirtualMusicOther` for a while, which does not exist."""
    from afterglow.backends.harmony_pk.builder.activities import _check_activity_type
    with pytest.raises(ValueError, match="does not have"):
        _check_activity_type("VirtualMusicOther", "Listen to Music")
    _check_activity_type("VirtualMusicServer", "Listen to Music")


def test_the_builder_refuses_an_icon_the_remote_lacks():
    """An <Icon> names a glyph in the remote's own set. A name it does not have draws
    nothing, so the button looks broken rather than plain."""
    from afterglow.backends.harmony_pk.builder.activities import _check_icon, _known_icons
    if not _known_icons():
        pytest.skip("icon artwork not extracted")
    with pytest.raises(ValueError, match="does not have"):
        _check_icon("down", "Blinds Down")
    _check_icon("stop", "Stop")


def test_the_scaffold_is_found_from_anywhere():
    """It is looked for beside the package and up from the caller's root. Passing a
    directory inside the package sent the search into afterglow/gui and reported a
    missing scaffold that was present all along."""
    import tempfile
    from pathlib import Path
    from afterglow.build_service import find_scaffold
    inside_the_package = ROOT / "src" / "afterglow" / "gui"
    assert inside_the_package.is_dir(), "this test stopped covering the case it names"
    # A directory with no scaffold anywhere above it. `Path("/tmp")` was hardcoded,
    # which on Windows is a "C:/tmp" that need not exist at all.
    for start in (ROOT, inside_the_package, Path(tempfile.gettempdir())):
        assert find_scaffold("harmony-900", start) is not None, start
    assert find_scaffold("harmony-900") is not None          # no root at all
    assert find_scaffold("no-such-remote", ROOT) is None


def test_remote_settings_are_shown_and_editable(qapp_or_skip):
    """Theme, backlight, sound and the rest are the remote's own settings.

    These were locked for most of this project's life, because a configuration carrying
    different values was flashed and the remote went on using its own. The cause was
    ours: we shipped `platformconfig/system_*.dat` mode 0600, a mode copied off a dump.
    On a remote those files are 0600 *and owned by `data_srv`*; the ones we ship are
    extracted by the update manager as root, and `data_srv` runs as nobody - so it could
    neither read nor write them, failed every save with EACCES, and used built-in
    defaults on every boot.

    Shipping 0666 fixes it, confirmed on hardware: a config built with
    `backlight_level=35` was flashed and the remote came back reporting 35.
    """
    from afterglow import preferences
    from afterglow.gui.tabs import SettingsTab

    tab = SettingsTab({"settings": {}})
    for key in preferences.PREFERENCES:
        assert key in tab.prefs, f"{key} disappeared from the interface"
        assert tab.prefs[key].isEnabled(), f"{key} is still locked"
    # The things that do work must stay editable.
    for widget in (tab.remote, tab.out_file, tab.first_name, tab.last_name,
                   tab.locale, tab.add_blaster_btn):
        assert widget.isEnabled()


def test_an_imported_configs_settings_are_kept(qapp_or_skip, a_config, unpacked):
    """Locked does not mean discarded: what a configuration carries has to survive
    being opened and saved, or importing would quietly erase it."""
    from afterglow.gui.tabs import SettingsTab
    from afterglow.importer import build_project

    project = build_project(str(unpacked(a_config)))
    original = {k: v for k, v in project["settings"].items()
                if k in ("theme", "sound", "time_format", "backlight_level",
                         "large_font", "child_lock", "backlight_timeout")}
    if not original:
        pytest.skip("this config carries no remote settings")
    tab = SettingsTab(project)
    tab.refresh()
    tab.save()
    for key, value in original.items():
        assert project["settings"][key] == value, f"{key} changed on save"
