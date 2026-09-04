"""Device state machines, number entry, and the activity power plan.

Everything here is a behaviour that vanished on import at least once, and that is
invisible until hardware misbehaves: a television with no power-on, a number pad that
does nothing, an amplifier left silent, a DVD player left running.

The rule this module enforces: **an importer may not silently drop what it does not
understand.** A state Afterglow has no field for still has to survive a rebuild.
"""
import re
import xml.etree.ElementTree as ET

import pytest
from conftest import entries_of

from afterglow.backends.harmony_pk import states
from afterglow.importer import build_project


def device_xml(body: str):
    return ET.fromstring(f"<Device><Id>1</Id>{body}</Device>")


# carrying the block faithfully
def test_states_roundtrip_is_byte_exact(configs, unpacked):
    """parse -> build must reproduce every real <States> and <Numeric> exactly.

    Byte-exact rather than "equivalent": these blocks are carried, not interpreted, so
    any difference is something the parser failed to see.
    """
    checked = 0
    for index, config in enumerate(configs):
        tree = unpacked(config, f"s{index}")
        root = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
        for device in root.findall("Device"):
            for tag, parse, build in (("States", states.parse_states, states.build_states),
                                      ("Numeric", states.parse_numeric, states.build_numeric)):
                node = device.find(tag)
                if node is None:
                    continue
                assert build(parse(device)) == ET.tostring(node, encoding="unicode"), (
                    f"{config.name}: device {device.findtext('Id')} {tag}")
                checked += 1
    if not checked:
        pytest.skip("no config has states")


def test_an_action_may_hold_several_actions():
    """Switching a television to an input can send a code *and* set another state.

    Reading only the first <Action> silently halved those.
    """
    device = device_xml(
        "<States><State><Id>Input</Id><DiscreteActions><ChangeAction>"
        "<Action><Target>Device</Target><Operation><Name>SendCommand</Name>"
        '<Parameter name="Command">HDMI</Parameter></Operation></Action>'
        "<Action><Target>Device</Target><Operation><Name>SetValue</Name>"
        '<Parameter name="State">InputType</Parameter></Operation></Action>'
        "<Name>HDMI</Name></ChangeAction></DiscreteActions></State></States>")
    parsed = states.parse_states(device)
    assert len(parsed[0]["actions"][0]["actions"]) == 2
    assert states.build_states(parsed) == ET.tostring(device.find("States"), encoding="unicode")


def test_a_bare_action_outside_a_container_survives():
    """`StartAction` hangs directly off <State>, not inside DiscreteActions.

    Assuming the container set dropped it and corrupted everything after it.
    """
    device = device_xml(
        "<States><State><Id>AV2Input</Id><Value>AV2</Value><StartAction>"
        "<Action><Target>Device</Target><Operation><Name>SendCommand</Name>"
        '<Parameter name="Command">AV2</Parameter></Operation></Action>'
        "</StartAction></State></States>")
    assert states.build_states(states.parse_states(device)) == ET.tostring(
        device.find("States"), encoding="unicode")


# the view the interface gets
def test_discrete_power_is_read_whatever_kind_it_uses():
    """Real televisions store Off as a SetAction and On as a ChangeAction.

    Reading only SetAction lost the on command, the builder then had no matched pair
    and no toggle either, and the device shipped with **no power state at all**.
    """
    device = device_xml(
        "<States><State><Id>Power</Id><Delay>10500</Delay><DiscreteActions>"
        "<SetAction><Action><Target>Device</Target><Operation><Name>SendCommand</Name>"
        '<Parameter name="Command">PowerOff</Parameter></Operation></Action>'
        "<Name>Off</Name></SetAction>"
        "<ChangeAction><Action><Target>Device</Target><Operation><Name>SendCommand</Name>"
        '<Parameter name="Command">PowerOn</Parameter></Operation></Action>'
        "<Name>On</Name></ChangeAction></DiscreteActions></State></States>")
    power = states.power_commands(states.parse_states(device))
    assert power == {"delay": 10500, "off": "PowerOff", "on": "PowerOn"}


def test_an_indirect_input_is_still_listed():
    """An input may set a second state rather than send a code. It still exists."""
    device = device_xml(
        "<States><State><Id>Input</Id><DiscreteActions>"
        "<SetAction><Action><Target>Device</Target><Operation><Name>SetValue</Name>"
        '<Parameter name="State">InputType</Parameter>'
        '<Parameter name="Value">HDMI 1</Parameter></Operation></Action>'
        "<Name>HDMI 1</Name></SetAction></DiscreteActions></State></States>")
    assert states.input_list(states.parse_states(device)) == [["HDMI 1", None]]


def test_editing_power_leaves_every_other_state_alone():
    """Changing a television's power command must not discard its input tree."""
    device = device_xml(
        "<States><State><Id>Power</Id></State>"
        "<State><Id>InputType</Id><Value>HDMI</Value></State></States>")
    parsed = states.parse_states(device)
    edited = states.set_power(parsed, "1", on="On", off="Off", toggle=None, delay=500)
    assert [s["id"] for s in edited] == ["Power", "InputType"]
    assert states.power_commands(edited) == {"delay": 500, "on": "On", "off": "Off"}


# what reaches the rebuilt config
@pytest.fixture
def rebuilt(a_config, unpacked, build):
    tree = unpacked(a_config)
    project = build_project(str(tree))
    original = ET.parse(tree / "userconfig" / "UserConfiguration.xml").getroot()
    out = ET.fromstring(entries_of(build(project)).read("userconfig/UserConfiguration.xml"))
    return original, out


def test_every_device_keeps_its_states_and_digits(rebuilt):
    original, out = rebuilt
    after = {d.findtext("Id"): d for d in out.findall("Device")}
    for device in original.findall("Device"):
        ident = device.findtext("Id")
        assert ident in after, f"device {ident} disappeared"
        was = {s.findtext("Id") for s in device.findall("States/State")}
        now = {s.findtext("Id") for s in after[ident].findall("States/State")}
        assert was <= now, f"device {ident} lost states {sorted(was - now)}"
        digits = len(device.findall("Numeric//Digit"))
        assert len(after[ident].findall("Numeric//Digit")) == digits, (
            f"device {ident} lost number entry")


def test_activities_keep_their_power_plan(rebuilt):
    """An activity says what to turn on *and* what to turn off. Without the off list
    the previous activity's devices stay running."""
    original, out = rebuilt
    after = {a.findtext("Id"): a for a in out.findall("Activity")}
    for activity in original.findall("Activity"):
        ident = activity.findtext("Id")
        if activity.find("Power") is None or ident not in after:
            continue
        for tag in ("On", "Off"):
            was = {e.text for e in activity.findall(f"Power/{tag}")}
            now = {e.text for e in after[ident].findall(f"Power/{tag}")}
            assert was <= now, f"activity {ident} lost {tag} {sorted(was - now)}"


def test_unknown_roles_survive(rebuilt):
    """PASSTHROUGH is a real role with no field of its own. Dropping it also dropped
    that device from the activity's power-on list, so the amplifier stayed silent."""
    original, out = rebuilt
    after = {a.findtext("Id"): a for a in out.findall("Activity")}
    for activity in original.findall("Activity"):
        ident = activity.findtext("Id")
        if ident not in after:
            continue
        was = {(r.findtext("Name"), r.findtext("DeviceId")) for r in activity.findall("Role")}
        now = {(r.findtext("Name"), r.findtext("DeviceId")) for r in after[ident].findall("Role")}
        assert was <= now, f"activity {ident} lost roles {sorted(was - now)}"


def test_protocol_toggle_bit_survives(rebuilt):
    """RC5/RC6-family protocols flip a toggle bit between presses so the device can
    tell a second press from a held key. Dropping it made repeats read as one press."""
    original, out = rebuilt
    if not original.findall("Protocols/Protocol"):
        pytest.skip("this config declares no per-protocol metadata")
    was = {ET.tostring(p.find("CodeSequence"), encoding="unicode")
           for p in original.findall("Protocols/Protocol") if p.find("CodeSequence") is not None}
    now = {ET.tostring(p.find("CodeSequence"), encoding="unicode")
           for p in out.findall("Protocols/Protocol") if p.find("CodeSequence") is not None}
    assert was <= now, "a protocol lost its toggle bit"


def test_a_device_with_only_an_off_command_still_powers_off(rebuilt):
    """A stereo with a dedicated standby key has a discrete Off and no discrete On.
    Requiring a matched pair left it running when the user pressed Off."""
    original, out = rebuilt
    was = {e.text for a in original.findall("Activity") if a.findtext("Id") == "-1"
           for e in a.findall("Power/Off")}
    now = {e.text for a in out.findall("Activity") if a.findtext("Id") == "-1"
           for e in a.findall("Power/Off")}
    if not was:
        pytest.skip("config has no all-off activity")
    assert was <= now, f"all-off activity lost {sorted(was - now)}"


# the action vocabulary macros are built from
def test_every_firmware_operation_we_offer_builds():
    """Four of the firmware's five operations (HAO.lua `handleAction`).

    SendFlush is deliberately absent: it appears in no configuration available, so its
    correct use is unknown and authoring a guess would produce a config that looks
    right and is not.
    """
    from afterglow.backends.harmony_pk.builder.actions import _action
    assert "SendCommand" in _action(("command", "7", "Play"))
    assert "Hold" in _action(("command", "7", "VolUp", "Hold"))
    assert "SetValue" in _action(("state", "7", "InputType", "HDMI 1"))
    assert "SendDelay" in _action(("delay", "7", 500))
    assert "SendNumber" in _action(("number", "7", 101))


def test_an_unknown_step_is_refused_not_guessed():
    from afterglow.backends.harmony_pk.builder.actions import _action
    with pytest.raises(ValueError, match="bad action step"):
        _action(("teleport", "7", "away"))


@pytest.mark.parametrize("step", [
    ["command", "7", "Play"],
    ["command", "7", "VolUp", "Hold"],
    ["state", "7", "InputType", "HDMI 1"],
    ["input", "7", "HDMI 2"],
    ["delay", "7", 500],
    ["number", "7", "101"],
])
def test_action_steps_survive_a_round_trip(step):
    """Build a step, read it back, get the same step.

    Each of these was lost once: the modifier was dropped so Hold became Press, a
    SetValue on anything but `Input` returned None and vanished mid-sequence, and
    SendNumber was not parsed at all.
    """
    from afterglow.backends.harmony_pk.builder.actions import _action
    from afterglow.backends.harmony_pk.importer import parse_action
    assert parse_action(ET.fromstring(_action(tuple(step)))) == step


# favourites and hard keys
def test_a_hard_key_may_run_a_whole_macro():
    """A hard key can point at a named ActionList, not just one command.

    Rebuilding it from the button's ActionId kept the first step and threw the rest
    away, so a three-step macro came back as one command.
    """
    from afterglow.backends.harmony_pk.builder import activities
    macro = [["command", "7", "Menu"], ["delay", "7", 500], ["command", "7", "Guide"]]
    device = {"id": "7", "label": "Box", "commands": [["Menu", "Menu", "", "01", None],
                                                      ["Guide", "Guide", "", "02", None]]}
    _xml, lists = activities._gen_activity(
        {"id": "1", "label": "TV", "control": "7", "display": "7",
         "hard_macros": {"Menu": macro}}, {"7": device})
    steps = ET.fromstring(lists[0]).findall("Action")
    assert len(steps) == 3, "the macro lost steps on the way out"


def test_a_macro_may_claim_an_unused_hard_key():
    """Putting a macro on a colour button the device does not otherwise use is the
    ordinary case. Only offering keys the device already occupied dropped it."""
    from afterglow.backends.harmony_pk.builder import activities
    device = {"id": "7", "label": "Box", "commands": [["Menu", "Menu", "", "01", None]]}
    xml, lists = activities._gen_activity(
        {"id": "1", "label": "TV", "control": "7", "display": "7",
         "hard_macros": {"Red": [["command", "7", "Menu"]]}}, {"7": device})
    assert lists, "the macro was dropped"
    assert 'name="Red"' in xml


def test_a_favourite_dials_the_digit_keys_the_device_actually_has():
    """Digit keys are named "0".."9" in real configs, not "Number0".."Number9".

    Assuming the latter emitted commands no device had: the favourite built, verified,
    and did nothing at all when pressed.
    """
    from afterglow.backends.harmony_pk.builder import activities
    device = {"id": "7", "label": "Box",
              "commands": [[str(d), str(d), "", f"0{d}", None] for d in range(10)]}
    xml, _lists = activities._gen_activity(
        {"id": "1", "label": "TV", "control": "7", "display": "7",
         "channels": [("BBC", "101", "bbc.png")]}, {"7": device})
    sent = re.findall(r'name="Command">([^<]+)<', ET.tostring(
        ET.fromstring(xml).find(".//Channel"), encoding="unicode"))
    assert sent == ["1", "0", "1"]


def test_a_favourite_on_a_device_with_no_digits_is_refused():
    """Better to fail the build than ship a button that quietly does nothing."""
    from afterglow.backends.harmony_pk.builder import activities
    device = {"id": "7", "label": "Box", "commands": [["Play", "Play", "", "01", None]]}
    with pytest.raises(ValueError, match="no number keys"):
        activities._gen_activity(
            {"id": "1", "label": "TV", "control": "7", "display": "7",
             "channels": [("BBC", "101", "bbc.png")]}, {"7": device})


def test_the_favourite_confirm_key_survives_a_round_trip():
    """Many receivers need the number confirmed with OK. Reading only the digits
    dropped it, and the favourite typed the channel and sat there."""
    from afterglow.backends.harmony_pk.builder import activities
    from afterglow.backends.harmony_pk.importer import parse_action
    device = {"id": "7", "label": "Box",
              "commands": [[str(d), str(d), "", f"0{d}", None] for d in range(10)]
                          + [["Select", "OK", "", "AA", None]]}
    xml, _lists = activities._gen_activity(
        {"id": "1", "label": "TV", "control": "7", "display": "7",
         "channels": [("BBC", "101", "bbc.png")], "channel_confirm": "Select"},
        {"7": device})
    channel = ET.fromstring(xml).find(".//Channel")
    commands = [parse_action(a)[2] for a in channel.findall("Actions/Action")]
    assert commands == ["1", "0", "1", "Select"]


# parts of the format nothing here models
def test_a_numeric_range_state_survives():
    """A state may be a numeric RANGE rather than a list of values - `MinValue` /
    `MaxValue` / `InitialValue`, all read by State.lua. Nothing here models them, so
    they must be carried rather than dropped."""
    device = device_xml(
        "<States><State><Id>Volume</Id><MinValue>0</MinValue><MaxValue>100</MaxValue>"
        "<InitialValue>20</InitialValue><RelativeActions><NextAction>"
        "<Action><Target>Device</Target><Operation><Name>SendCommand</Name>"
        '<Parameter name="Command">VolUp</Parameter></Operation></Action>'
        "</NextAction></RelativeActions></State></States>")
    assert states.build_states(states.parse_states(device)) == ET.tostring(
        device.find("States"), encoding="unicode")


def test_numeric_prefix_actions_survive():
    """`Start`, `GreaterTen` and `GreaterHundred` (Numeric.lua) are the actions run
    before dialling and the prefix a receiver needs for a two- or three-digit channel.
    Dropping them makes every multi-digit channel tune to the wrong place."""
    device = device_xml(
        '<Numeric><FixedDigits>0</FixedDigits><GreaterTen><Action><Target>Device</Target>'
        "<Operation><Name>SendCommand</Name>"
        '<Parameter name="Command">Dash</Parameter></Operation></Action></GreaterTen>'
        '<FirstDigit><Digit value="1"><Action><Target>Device</Target><Operation>'
        '<Name>SendCommand</Name><Parameter name="Command">1</Parameter>'
        "</Operation></Action></Digit></FirstDigit></Numeric>")
    assert states.build_numeric(states.parse_numeric(device)) == ET.tostring(
        device.find("Numeric"), encoding="unicode")


# things that build cleanly and lose data on the remote
def test_two_activities_may_not_share_an_id():
    """The remote stores one entry per id, so a duplicate is silent data loss: the
    config builds, verifies, flashes, and only one of the activities is there.

    This happened. An id generator counting from zero each time the application
    started gave the same id to the first activity of every session, and a config with
    three activities arrived on the remote as one.
    """
    from afterglow.backends.harmony_pk.builder.assemble import _check_unique_ids
    activities = [{"id": "10000001", "label": "Watch TV"},
                  {"id": "10000001", "label": "Watch a Movie"}]
    with pytest.raises(ValueError, match="share an id"):
        _check_unique_ids([], activities)
    _check_unique_ids([], [{"id": "10000001"}, {"id": "10000002"}])


def test_two_devices_may_not_share_an_id():
    from afterglow.backends.harmony_pk.builder.assemble import _check_unique_ids
    with pytest.raises(ValueError, match="share an id"):
        _check_unique_ids([{"id": "40009001", "label": "TV"},
                           {"id": "40009001", "label": "Box"}], [])


def test_new_ids_come_from_the_project_not_a_counter(qapp_or_skip):
    """A module-level counter restarts with the application; the project does not."""
    from afterglow.gui.widgets import _new_act_id, _new_id
    assert _new_act_id([]) == "10000001"
    assert _new_act_id(["10000001"]) == "10000002"
    assert _new_act_id(["10000001", "10000002", "10000003"]) == "10000004"
    assert _new_id(["40009001"]) == "40009002"


def test_a_delay_names_the_device_it_holds_up(qapp_or_skip):
    """A delay is per-device: the remote marks that device busy and lets commands to
    others carry on. A pause meant to separate two presses on one box, attached to a
    different device, does nothing at all - and the remote shows the wrong name while
    it waits."""
    from afterglow.gui.macro import MacroEditorWidget
    editor = MacroEditorWidget([{"id": "7", "label": "Box", "commands": []},
                                {"id": "9", "label": "TV", "commands": []}],
                               [["command", "7", "Menu"]])
    assert editor._previous_device() == "7", "a delay would default to the wrong device"


def test_a_favourite_without_its_image_is_caught(tmp_path):
    """A favourite names its logo in the configuration; the file has to be copied in
    beside it. The interface collected the chosen pictures and then dropped them, so
    the config referred to images it did not contain and the remote drew a blank."""
    import contextlib
    import io
    from conftest import ROOT, entries_of
    from afterglow.build_service import ConfigBuildService

    device = {"id": "7", "label": "Box", "type": "Pvr", "power_cmd": "PowerToggle",
              "commands": [[str(d), str(d), "7A", f"0{d}", None] for d in range(10)]
                          + [["PowerToggle", "Power", "7A", "AA", None]]}
    activity = {"id": "1", "label": "TV", "display": "7", "control": "7",
                "channels": [("Channel One", "101", "channel-one.png")]}
    # A logo made here rather than borrowed from a folder that is only on one machine:
    # this test used to need the maintainer's own channel art to pass.
    logo = tmp_path / "channel-one.png"
    logo.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"))
    out = tmp_path / "favs.ezhex"
    project = {"devices": [device], "activities": [activity],
               "assets": [{"source": str(logo), "name": "channel-one.png"}],
               "settings": {"remote": "harmony-900", "out_file": str(out),
                            "first_name": "T", "last_name": "U"}}
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(ROOT, lambda _m: None).build(project)
    names = entries_of(out).namelist()
    assert "userconfig/image/channel-one.png" in names, "the logo was not copied in"
