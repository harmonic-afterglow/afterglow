"""Two things the device pages got wrong, both found by using them.

**Address and Command did nothing.** For a command that carries a captured code -
which is every command on a device imported from a real configuration -
`builder.devices.code_for` returns the stored code and never looks at the address or
command bytes. The table offered two editable boxes anyway, pre-filled with 00, so the
only honest description of them was decorative.

**Changing the model produced a device that would not build.** The Search tab is on the
edit dialog too, so a model can be swapped. Doing it replaced the command list on screen
while `_collect` went on carrying the previous model's codes and protocol: 61 of 72
commands ended up with no code, and the build stopped.
"""
import pytest

@pytest.fixture(scope="module")
def templates(qapp_or_skip, synthetic_device_templates):
    return synthetic_device_templates


def model(templates, name):
    match = next((t for t in templates if t.get("model") == name), None)
    if match is None:
        pytest.skip(f"{name} is not in the library")
    return match


def made(templates, name):
    from afterglow.gui.device_wizard import DeviceWizard
    wizard = DeviceWizard(templates, project={"devices": [], "settings": {}})
    wizard._on_template_selected(model(templates, name))
    spec = wizard._collect()
    spec["id"] = "40009001"
    return spec


# captured codes
def test_a_captured_command_does_not_offer_bytes_that_are_ignored(templates):
    from PyQt6.QtCore import Qt
    from afterglow.gui.device_wizard import DeviceWizard
    wizard = DeviceWizard(templates, project={"devices": [], "settings": {}})
    wizard._on_template_selected(model(templates, "Captured Controller"))
    table = wizard.page_cmds.table
    for column in (2, 3):
        item = table.item(0, column)
        assert not (item.flags() & Qt.ItemFlag.ItemIsEditable), \
            "a byte the builder never reads is still offered for editing"
    assert table.item(0, 2).text() == "captured"
    assert table.item(0, 3).text() == "backend-opaque"


def test_a_generated_command_stays_editable(templates):
    """The columns are real for a device whose codes are built from a codec - this must
    not have been fixed by disabling them everywhere."""
    from PyQt6.QtCore import Qt
    from afterglow.gui.device_wizard import DeviceWizard
    wizard = DeviceWizard(templates, project={"devices": [], "settings": {}})
    wizard._on_template_selected(model(templates, "Generated Player"))
    item = wizard.page_cmds.table.item(0, 2)
    assert item.flags() & Qt.ItemFlag.ItemIsEditable
    assert item.text() and item.text() != "captured"


def test_semantic_signal_parameters_fill_the_hex_cells_and_edits_reach_the_signal(
        qapp_or_skip):
    from afterglow import ir_signal
    from afterglow.gui.device_wizard import CommandsPage

    existing = {
        "commands": [["Youtube", "YouTube", "", "", None]],
        "signals": {
            "Youtube": ir_signal.protocol_signal(
                "samsung32", {"address": 0x07, "command": 0xFA}),
        },
    }
    page = CommandsPage(existing)

    assert page.table.item(0, 2).text() == "07"
    assert page.table.item(0, 3).text() == "FA"
    page.table.item(0, 3).setText("F4")
    signals = page.updated_signals()
    assert signals["Youtube"]["parameters"] == {"address": 0x07, "command": "F4"}


def test_showing_the_code_does_not_lose_the_stored_bytes(templates):
    """The cell shows the code; the values behind it have to survive a round trip."""
    original = model(templates, "Captured Controller")["commands"]
    rebuilt = made(templates, "Captured Controller")["commands"]
    assert [tuple(c)[:4] for c in rebuilt] == [tuple(c)[:4] for c in original]


# swapping the model
def swapped(templates, was, now):
    from afterglow.gui.device_wizard import DeviceEditor
    device = made(templates, was)
    editor = DeviceEditor(templates, existing=device,
                          project={"devices": [device], "settings": {}})
    editor._on_template_selected(model(templates, now))
    return device, editor._collect()


def test_switching_model_leaves_every_command_with_a_code(templates):
    _before, after = swapped(templates, "Captured Controller", "Captured Receiver")
    names = {name for name, *_rest in after["commands"]}
    signalled = set(after.get("signals") or {})
    assert not (names - signalled), f"{len(names - signalled)} commands have no signal"


def test_switching_model_takes_the_new_protocol(templates):
    before, after = swapped(templates, "Captured Controller", "Captured Receiver")
    before_protocols = {signal.get("protocol") for signal in before["signals"].values()}
    after_protocols = {signal.get("protocol") for signal in after["signals"].values()}
    expected = {signal.get("protocol") for signal in
                model(templates, "Captured Receiver")["signals"].values()}
    assert after_protocols != before_protocols, "kept the old model's protocol"
    assert after_protocols == expected


def test_switching_model_keeps_the_id_the_activities_reference(templates):
    """The one thing that must not change: everything else in the project points at
    this device by id."""
    before, after = swapped(templates, "Captured Controller", "Captured Receiver")
    assert after["id"] == before["id"] == "40009001"


def test_a_swapped_device_builds(templates, build):
    _before, after = swapped(templates, "Captured Controller", "Captured Receiver")
    assert build({"devices": [after], "activities": [], "assets": []}).stat().st_size > 0


def test_the_editor_can_say_which_commands_activities_rely_on(templates):
    """So a swap that takes one away can be reported rather than discovered later."""
    from afterglow.gui.device_wizard import DeviceEditor
    device = {"id": "40009001", "label": "Media Centre", "type": "MediaCenterPC",
              "commands": [["MyTV", "My TV", "00", "00", None]]}
    project = {"devices": [device], "settings": {}, "activities": [
        {"label": "Watch TV",
         "soft_buttons": [{"label": "My TV", "device": "40009001", "command": "MyTV"}]},
        {"label": "Music",
         "hard_macros": {"Menu": [["command", "40009001", "MyMusic"]]}},
        {"label": "Elsewhere",
         "hard_macros": {"Menu": [["command", "49999999", "NotOurs"]]}},
    ]}
    used = DeviceEditor(templates, existing=device, project=project)._commands_activities_use()
    assert used == {"MyTV": ["Watch TV"], "MyMusic": ["Music"]}
    assert "NotOurs" not in used, "picked up a command belonging to another device"
