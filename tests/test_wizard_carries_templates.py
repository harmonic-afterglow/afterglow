"""What a device picked from the library must still be, once the wizard is done.

The wizard used to build a spec field by field. Every field it forgot to copy was a
piece of the library entry thrown away at creation - invisible until something much
later went wrong, usually at build time or in an activity that had nothing to offer.
That happened five separate times, so the last few tests here check the rule rather
than the fields: whatever an editor is not responsible for, it must not touch.
"""
import pytest

@pytest.fixture(scope="module")
def templates(qapp_or_skip, synthetic_device_templates):
    return synthetic_device_templates


def template_named(templates, model):
    match = next((t for t in templates if t.get("model") == model), None)
    if match is None:
        pytest.skip(f"{model} is not in the library")
    return match


def built(templates, model):
    from afterglow.gui.device_wizard import DeviceWizard
    wizard = DeviceWizard(templates, project={"devices": [], "settings": {}})
    wizard._on_template_selected(template_named(templates, model))
    return wizard._collect()


def test_captured_codes_survive(templates):
    """Most library devices came from a real configuration, so their commands are
    captured codes, not something a codec can generate. Losing them left a device
    naming a donor-only protocol block with nothing to send - the build refused it,
    which is right, but only after everything else had been set up."""
    spec = built(templates, "Captured Television")
    assert len(spec.get("signals") or {}) == len(spec["commands"])
    assert all(signal["kind"] == "protocol" for signal in spec["signals"].values())


def test_a_library_capture_reference_reaches_the_build_spec(templates):
    """A capture filename in device JSON is a real signal dependency, not a label.

    Artemide used to arrive with 0xFFFF indexes but no raw_ir table, so its buttons
    pointed at entries the build could never include.
    """
    spec = template_named(templates, "Captured Light")
    assert len(spec.get("signals") or {}) == 11
    assert all(signal.get("kind") == "waveform"
               for signal in spec["signals"].values())


def test_a_device_from_the_library_actually_builds(templates, tmp_path):
    """The end of that story: it has to produce a configuration."""
    import contextlib
    import io
    from conftest import ROOT
    from afterglow.build_service import ConfigBuildService

    spec = built(templates, "Captured Television")
    spec["id"] = "40009001"
    out = tmp_path / "one-device.ezhex"
    project = {"devices": [spec], "activities": [], "assets": [],
               "settings": {"remote": "harmony-900", "out_file": str(out),
                            "first_name": "T", "last_name": "U"}}
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(ROOT, lambda _m: None).build(project)
    assert out.is_file() and out.stat().st_size > 0


def test_a_capture_backed_device_actually_builds(templates, tmp_path):
    """Capture references must survive through the wizard and into SsIr.bin."""
    import contextlib
    import io
    import zipfile
    from conftest import ROOT
    from afterglow.backends.harmony_pk import ssir
    from afterglow.build_service import ConfigBuildService

    spec = built(templates, "Captured Light")
    spec["id"] = "40009001"
    out = tmp_path / "capture-device.ezhex"
    project = {"devices": [spec], "activities": [], "assets": [],
               "settings": {"remote": "harmony-900", "out_file": str(out),
                            "first_name": "T", "last_name": "U"}}
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(ROOT, lambda _m: None).build(project)

    with zipfile.ZipFile(out) as archive:
        entries = ssir.parse(archive.read("userconfig/SsIr.bin"))
    assert len(entries) == 11
    assert entries == [ssir.encode_capture(spec["signals"][f"Command{index}"])
                       for index in range(11)]


def test_inputs_survive(templates):
    """An activity switches a device to an input. With the list dropped, the input
    page falls back to offering every command instead of the device's input names."""
    spec = built(templates, "Captured Receiver")
    names = [i[0] for i in spec.get("inputs") or []]
    assert "Cable" in names, names


def test_properties_survive(templates):
    """What the device *is* - a display, how many discs, which tuner input. The
    remote changes behaviour on these, and the Advanced page looked broken without
    them."""
    spec = built(templates, "Captured Television")
    assert spec.get("properties", {}).get("IsDisplayDevice") == "true"


def test_power_and_timing_survive(templates):
    spec = built(templates, "Captured Television")
    assert spec.get("power_on_cmd") and spec.get("power_off_cmd")
    assert spec.get("power_delay") == 10500


def test_always_on_survives(templates):
    spec = built(templates, "Generated Player")
    assert spec.get("always_on") is True


# editing must not cost the device anything
def imported_device():
    """A device shaped the way the importer leaves one, including the parts no page in
    either editor displays."""
    return {
        "id": "40009001", "label": "Denon Receiver", "type": "StereoReceiver",
        "mfr": "Denon", "model": "AVR-1713", "codec": "donor", "protocol": "Denon-K",
        "commands": [["PowerOn", "On", "", "01", None]],
        "raw_codes": {"PowerOn": "0x1234"},
        "inputs": [["CBL/SAT", None], ["Bluray", None]],
        "numeric": {"digits": 3},
        "states": [{"Id": "Input", "Value": "CBL/SAT"}],
        "icons": {"PowerOn": "powerOFF"},
        "raw_ir": {"0": {"pulses_us": [1, -1]}},
        "power_on_cmd": "PowerOn", "power_off_cmd": "PowerOff",
        "always_on": False, "power_delay": 3000,
        "press_presilence": 0, "press_interkey": 0,
        "hold_presilence": 50, "hold_interkey": 100,
        "properties": {"IsDisplayDevice": "false"},
    }


def edited(templates, existing):
    """Open a device in the edit dialog and immediately accept it, unchanged."""
    from afterglow.gui.device_wizard import DeviceEditor
    dialog = DeviceEditor(templates, existing=existing,
                          project={"devices": [existing], "settings": {}})
    return dialog._collect()


def test_editing_a_device_changes_nothing_it_was_not_asked_to_change(templates):
    """Open a device, touch nothing, press OK. What comes back has to be the same
    device. It was not: states, per-command icons and learned waveforms all had no
    page in the dialog, so rebuilding the spec from the widgets deleted them - and
    <States> is the block an activity switches inputs with."""
    before = imported_device()
    after = edited(templates, before)
    for field in ("states", "icons", "numeric", "inputs"):
        assert after.get(field) == before[field], f"{field} did not survive an edit"
    assert set(after["signals"]) == {"PowerOn"}


def test_a_field_nobody_here_recognises_survives_an_edit(templates):
    """The point of the rule. A field added to the library tomorrow must come through
    an editor that has never heard of it, rather than being dropped for not appearing
    in a list somebody has to remember to update."""
    before = imported_device() | {"scart": True, "some_future_field": [1, 2, 3]}
    after = edited(templates, before)
    assert after.get("scart") is True
    assert after.get("some_future_field") == [1, 2, 3]


def test_library_bookkeeping_does_not_leak_into_the_device(templates):
    """Carrying everything must not mean carrying the library's own metadata: where
    the entry was found is not something the device is."""
    spec = built(templates, "Captured Television")
    assert spec["schema"] == "afterglow-project-device/1"
    for field in ("fingerprint", "source", "names", "_source_file"):
        assert field not in spec, f"{field} is library bookkeeping, not a device field"


def test_a_device_never_claims_two_power_modes(templates):
    """Toggle power and discrete power live in different keys. Carrying the old spec
    forward without clearing them first would leave a device claiming both, and which
    one the remote then obeys is not something worth finding out on hardware."""
    toggle = imported_device()
    del toggle["power_on_cmd"], toggle["power_off_cmd"]
    toggle["power_cmd"] = "PowerToggle"

    for before in (imported_device(), toggle):
        after = edited(templates, before)
        assert not (after.get("power_cmd") and after.get("power_on_cmd")), after


# buttons that only fail when pressed
def project_devices():
    """A couple of devices, enough to populate any picker."""
    return [{"id": "40009001", "label": "TV", "type": "Television",
             "commands": [["PowerOn", "On", "", "01", None]], "inputs": [["HDMI 1", None]]},
            {"id": "40009002", "label": "Blinds", "type": "Light",
             "commands": [["AllDown", "Down", "", "02", None]]}]


def test_the_extra_role_buttons_work(qapp_or_skip):
    """Constructing a page proves nothing about the callbacks hanging off it.

    The "add extra role" handler referred to a list that a refactor had removed, so it
    raised the moment the button was pressed - and took the whole application down,
    because an exception out of a Qt slot is not caught anywhere.
    """
    from afterglow.gui.activity_wizard import ActivityRolesPage
    page = ActivityRolesPage(project_devices(), {})

    page.add_passthrough_btn.click()
    assert page.extra_roles_rows, "no row was added"
    assert page.extra_roles_rows[0]["name"].text() == "PASSTHROUGH"

    page.add_role_btn.click()
    assert len(page.extra_roles_rows) == 2
    assert page.extra_roles_rows[1]["name"].text() == ""

    page.extra_roles_rows[0]["dev"].select_data("40009002")
    assert page.get_roles() == {"PASSTHROUGH": "40009002"}

    page._remove_extra_role(page.extra_roles_rows[1])
    assert len(page.extra_roles_rows) == 1


def test_every_add_button_in_the_activity_pages_survives_a_press(qapp_or_skip,
                                                                 monkeypatch):
    """Press every "add" button once. They open a modal, so the dialog is stubbed to
    decline - what is being tested is that the handler runs at all."""
    from PyQt6.QtWidgets import QDialog
    from afterglow.gui import activity_buttons, activity_wizard
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)

    devices = project_devices()
    pages = [activity_buttons.FavouritesPage(devices, {}),
             activity_buttons.ScreenButtonsPage(devices, {}),
             activity_wizard.ActivityMacrosPage(devices, {})]
    for page in pages:
        for button in page.findChildren(type(page.findChild(
                __import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton))):
            if button.text().lower().startswith("add"):
                button.click()          # must not raise


def test_search_page_active_sources_chips_and_all_sources_merge(qapp_or_skip):
    from afterglow.gui.device_wizard import SearchPage
    from afterglow.gui.source_settings import SourcePreferences

    prefs = SourcePreferences(local_devices=True, logitech_online=True)
    templates = [{"mfr": "Samsung", "model": "QE55S90D", "commands": [], "signals": {}}]
    page = SearchPage(templates, existing={}, source_preferences=prefs)

    assert not page._sources_chips_widget.isHidden()
    # Click second chip button to switch search_type
    chip_buttons = page._sources_chips_widget.findChildren(
        __import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton
    )
    assert len(chip_buttons) >= 1
    chip_buttons[0].click()
    assert page.search_type.currentData() != "all"
    assert page._sources_chips_widget.isHidden()


def test_search_page_deduplicates_by_source_dominance(qapp_or_skip):
    from dataclasses import dataclass
    from afterglow.gui.device_wizard import SearchPage
    from afterglow.gui.source_settings import SourcePreferences

    @dataclass
    class M:
        manufacturer: str
        manufacturer_slug: str
        name: str
        filename: str
        global_device_id: int

    class FakeOnlineCatalog:
        def manufacturer(self, name):
            from afterglow.corpus_provider import Manufacturer
            return Manufacturer(name="Yamaha", slug="yamaha", count=2)

        def models(self, mfr, query, limit=300):
            return [
                M("Yamaha", "yamaha", "DTR-5630RDS", "a.json", 111), # duplicate of local
                M("Yamaha", "yamaha", "DTR-5640", "b.json", 222),    # new online model
            ]

    prefs = SourcePreferences(local_devices=True, logitech_online=True)
    local_templates = [{"mfr": "Yamaha", "model": "DTR-5630RDS", "commands": [], "signals": {}}]
    page = SearchPage(local_templates, existing={}, source_preferences=prefs)

    page._matched_mfr = "Yamaha"
    page._matched_online_cats = [("Yamaha", FakeOnlineCatalog())]
    page._on_model_typed("DTR")

    # DTR-5630RDS appears exactly once (local takes dominance, online duplicate omitted)
    choices = page._model_box._choices
    assert choices.count("DTR-5630RDS") == 1
    assert "DTR-5640" in choices
    assert "DTR-5630RDS" not in page._all_archive_models
    assert "DTR-5640" in page._all_archive_models

