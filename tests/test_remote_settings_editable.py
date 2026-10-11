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
from afterglow import remotes


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
        filename = prefs.definitions(remotes.get("harmony-900"))[key]["file"]
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


def test_a_harmony_one_offers_its_themes_by_name_and_a_900_does_not(qapp_or_skip):
    # The One's look is a theme from Documents/Afterglow/Themes/harmony-one, chosen by
    # name and kept as `theme_folder`, apart from the 900's own `theme` preference. The
    # Example there is a copy of the default to start from, so it is not offered.
    import shutil

    from afterglow import paths, themes
    from afterglow.gui.tabs import SettingsTab

    folder = themes.folder("harmony-one")
    for name in ("Mario", themes.EXAMPLE):
        (folder / name).mkdir(parents=True, exist_ok=True)
        (folder / name / themes.MANIFEST).write_text("{}")
    try:
        one = {"settings": {"remote": "harmony-one"}, "devices": [], "activities": []}
        tab = SettingsTab(one)
        assert tab.form.isRowVisible(tab.theme_row)
        offered = [tab.theme.itemText(index) for index in range(tab.theme.count())]
        assert offered == ["Default", "Mario"]
        tab.theme.setCurrentIndex(1)
        tab.save()
        assert one["settings"]["theme_folder"] == "Mario"
        tab.theme.setCurrentIndex(0)
        tab.save()
        assert "theme_folder" not in one["settings"]
        nine = {"settings": {"remote": "harmony-900"}, "devices": [], "activities": []}
        assert not SettingsTab(nine).form.isRowVisible(SettingsTab(nine).theme_row)
    finally:
        shutil.rmtree(paths.user_folder("themes"))

def test_the_timing_page_offers_what_the_remote_s_builder_uses(qapp_or_skip):
    # The One's builder uses the power-on delay, the delay between digits and Always on;
    # the 900's pre-silences and hold timings mean nothing to it, so they are not shown.
    from afterglow.gui.device_wizard import DeviceEditor

    one = {"settings": {"remote": "harmony-one"}, "devices": [], "activities": []}
    page = DeviceEditor([], None, existing={}, project=one).page_timing
    form = page.layout()
    assert form.isRowVisible(page.pwr_delay) and form.isRowVisible(page.inter_key)
    assert not form.isRowVisible(page.pre_sil) and not form.isRowVisible(page.hold_key)
    nine = {"settings": {"remote": "harmony-900"}, "devices": [], "activities": []}
    page = DeviceEditor([], None, existing={}, project=nine).page_timing
    assert page.layout().isRowVisible(page.hold_key)
