"""Help as Logitech's One configurations run it, where ours differed (compared page by
page against seven of Logitech's own):

- an answer of No to "Is the TV on?" sends its power and goes on, where ours waited the
  whole power-on delay first - up to 20 s with the screen frozen;
- a device the remote cannot switch on, and an input no command selects, are asked to be
  seen to by hand: "Ensure the PS4 is on." with OK, then whether that fixed it;
- an input no command selects survives reading a Logitech configuration back;
- a build of ours reads back a command "O" as O, not 0, though its font draws them alike.
"""
from __future__ import annotations

import tempfile

import pytest

from afterglow import ir_signal, payloads, remotes
from afterglow.backends.harmony_one import backend, generate, importing

pytestmark = pytest.mark.slow


def _nec(address: int, command: int):
    pulses = [9000, -4500]
    for byte in (address, ~address & 0xFF, command, ~command & 0xFF):
        for bit in range(8):
            pulses += [560, -1690] if (byte >> bit) & 1 else [560, -560]
    return ir_signal.waveform(pulses + [560, -40000], carrier_hz=38000)


PROJECT = {
    "devices": [
        {"id": "tv", "label": "TV", "type": "Television",
         "signals": {"PowerOn": _nec(4, 1), "PowerOff": _nec(4, 2),
                     "InputHdmi1": _nec(4, 3), "InputHdmi2": _nec(4, 4)},
         "power_on_cmd": "PowerOn", "power_off_cmd": "PowerOff", "power_delay": 9000,
         "inputs": [["HDMI 1", "InputHdmi1"], ["HDMI 2", "InputHdmi2"]]},
        # a console the remote has no power command for
        {"id": "ps4", "label": "PS4", "type": "GameConsole",
         "signals": {"Play": _nec(6, 1), "O": _nec(6, 2), "0": _nec(6, 3)},
         "commands": [["Play", "Play", "", "", None], ["O", "O", "", "", None],
                      ["0", "0", "", "", None]]},
        # a PC whose inputs are chosen by hand, and a power toggle
        {"id": "pc", "label": "PC", "type": "Computer",
         "signals": {"Power": _nec(8, 1)}, "power_cmd": "Power", "power_delay": 3000,
         "inputs": [["Media"], ["Games"]]},
    ],
    "activities": [
        {"id": "1", "label": "Play PS4", "power_on_devices": ["tv", "ps4", "pc"],
         "enter": [["input", "tv", "HDMI 2"], ["input", "pc", "Games"]],
         "display": "tv", "control": "ps4", "volume": "tv"},
    ],
}


@pytest.fixture(scope="module")
def image():
    return generate.configuration(PROJECT)


def _pages(payload):
    """Every page of every screen: its text, joined, and what each of its zones does."""
    read = importing.Image(payload)
    out = []
    for screen in read.screens:
        for slot in screen["slots"]:
            text = " ".join(item["text"] for item in read.page_text(slot["program_offset"]))
            out.append((text, [read.row(entry) for entry in slot["entries"]], read))
    return out


def test_help_sends_a_device_s_power_and_goes_on_without_waiting(image):
    answers = [steps for text, zones, _read in _pages(image) if "the TV on?" in text
               for steps in zones if any(step[0] == importing.SEND for step in steps)]
    assert answers, "no answer sends the TV's power"
    for steps in answers:
        assert not any(step[0] == importing.WAIT for step in steps), steps
        assert steps[-1][0] == importing.MODE


def test_help_asks_for_what_the_remote_cannot_send_to_be_seen_to(image):
    pages = _pages(image)
    texts = [" ".join(text.split()) for text, _zones, _read in pages]
    for wanted in ("Ensure the PS4 is on.", "Ensure the PC is set to the Games input."):
        [(text, zones, read)] = [page for page, flat in zip(pages, texts) if wanted in flat]
        # one answer, OK, which sends nothing and asks whether that fixed it
        [steps] = [steps for steps in zones if steps]
        assert [step[0] for step in steps] == [importing.MODE]
        entered = read.screens[steps[0][1]]["slots"][0]
        assert "Did that fix the problem?" in " ".join(
            item["text"] for item in read.page_text(entered["program_offset"]))
    # and no question asks after the PS4's power, which there is none of
    assert not any("the PS4 on?" in text for text in texts)


def _project_of(payload):
    folder = tempfile.mkdtemp()
    payloads.get("blob").unpack(payload, folder)

    class Context(dict):
        def log(self, *_a):
            pass
    return backend.import_project(folder, remotes.get("harmony-one"), Context()).project


def test_a_build_reads_back_its_o_and_its_zero(image):
    [ps4] = [device for device in _project_of(image)["devices"]
             if device["label"] == "PS4"]
    assert {"O", "0"} <= set(ps4["signals"])
    assert ps4["signals"]["O"]["pulses_us"] == PROJECT["devices"][1]["signals"]["O"]["pulses_us"]


def test_inputs_no_command_selects_are_read_back(image):
    project = _project_of(image)
    [pc] = [device for device in project["devices"] if device["label"] == "PC"]
    assert [entry[1:] for entry in pc["inputs"]] == [[], []]
    [activity] = project["activities"]
    assert ["input", pc["id"], "Input 2"] in activity["enter"]


def test_a_variable_whose_every_transition_does_nothing_is_inputs_set_by_hand():
    # Logitech's own: a Media Center PC's seven inputs, 42 transitions between them,
    # each sending nothing
    record = {"limit": 6, "transitions": [
        {"from": a, "to": b, "operand": 0, "category": 0}
        for a in range(7) for b in range(7) if a != b]}
    states = {}
    importing._state(states, record, False, importing.Image.__new__(importing.Image))
    assert states["inputs"] == {"direct": [None] * 7}
