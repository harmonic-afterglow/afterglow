"""The Remote Settings controls are live, and a change survives to the package.

These were disabled for most of the project's life because flashing a setting did
nothing, and the cause was unknown. It turned out to be ours: we shipped
`platformconfig/system_*.dat` mode 0600, copied off a dump. On a working remote those
files are 0600 *and owned by `data_srv`*; the ones we ship are extracted by the update
manager as root, and `data_srv` runs as nobody. It could neither read nor write them, so
it failed every save with EACCES and used built-in defaults on every boot.

Confirmed on hardware after the fix: a config built with `backlight_level=35` was
flashed, and the remote came back with the file at 35, mode 0666, and the live settings
service reporting 35. See `test_settings_file_modes.py` for the mode invariant itself.

This guards the other half - that the UI actually offers the control and that what the
user picks reaches the built configuration.
"""
import io
import zipfile


from afterglow import preferences as prefs


def value_in(path, filename):
    data = open(path, "rb").read()
    zf = zipfile.ZipFile(io.BytesIO(data[data.find(b"PK\x03\x04"):]))
    return zf.read(f"platformconfig/{filename}").decode("utf-8", "replace").strip()


def test_every_preference_reaches_the_package(build, tmp_path):
    """The end-to-end claim the UI now makes to the user: pick a value, flash, done."""
    chosen = {"time_format": "Civilian", "sound": "1", "theme": "2",
              "large_font": "0", "backlight_level": "35",
              "backlight_timeout": "30", "child_lock": "1"}
    device = {"id": "40009001", "label": "TV", "type": "Television",
              "commands": [["PowerOn", "On", "07", "01", None]],
              "power_on_cmd": "PowerOn"}
    # a copy: the fixture adds out_file/remote to whatever dict it is handed
    out = build({"devices": [device], "activities": [], "assets": [],
                 "settings": dict(chosen)})
    for key, value in chosen.items():
        filename = prefs.PREFERENCES[key][0]
        assert value_in(out, filename) == value, f"{key} did not reach the package"


def test_the_settings_controls_are_enabled(qapp_or_skip):
    """The regression this file is named for. They were deliberately disabled, and the
    reason no longer holds - but `save()` always read them, so leaving them disabled
    silently discarded the user's choice rather than failing loudly."""
    from afterglow.gui.tabs import SettingsTab

    project = {"settings": {}, "devices": [], "activities": [], "assets": []}
    tab = SettingsTab(project)
    assert tab.prefs, "no preference controls were built"
    disabled = [k for k, w in tab.prefs.items() if not w.isEnabled()]
    assert not disabled, f"still disabled: {disabled}"


def test_choosing_a_setting_saves_it_into_the_project(qapp_or_skip):
    from afterglow.gui.tabs import SettingsTab

    project = {"settings": {}, "devices": [], "activities": [], "assets": []}
    tab = SettingsTab(project)
    widget = tab.prefs["backlight_level"]
    widget.setValue(35)
    tab.save()
    assert project["settings"]["backlight_level"] == "35"
