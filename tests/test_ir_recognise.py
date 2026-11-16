"""Recognising a recording as the protocol command it is (docs/ir-recognition.md)."""
from __future__ import annotations

from afterglow import ir_protocol, ir_recognise, ir_signal


def _recording(protocol: str, parameters: dict, *, repeats: int = 0) -> dict:
    """A command as a Harmony One keeps it: its press, perhaps repeated a little, and
    the frame it repeats while held."""
    spec = ir_protocol.catalog()[protocol]
    press, _state = ir_protocol.transmission(spec, parameters, "press")
    hold, _state = ir_protocol.transmission(spec, parameters, "hold")
    pulses = press + hold * repeats + hold
    return ir_signal.waveform(
        pulses, carrier_hz=spec["modulation"]["carrier_hz"], name="PowerOn",
        sections={"intro_pulses": len(press) + len(hold) * repeats,
                  "repeat_pulses": len(hold), "release_pulses": 0})


def _nudged(signal: dict) -> dict:
    """The same recording as Logitech renders it: every duration a little off."""
    out = dict(signal)
    out["pulses_us"] = [pulse - 10 if pulse > 0 else pulse + 12 for pulse in signal["pulses_us"]]
    out["carrier_hz"] = signal["carrier_hz"] + 1
    return out


def test_a_nec_recording_is_the_nec1_command_it_was_rendered_from():
    found = ir_recognise.recognise(_nudged(_recording("nec1", {"address": 4, "command": 8})))
    assert (found["protocol"], found["parameters"]) == ("nec1", {"address": 4, "command": 8})
    assert found["name"] == "PowerOn"


def test_a_sony_recording_that_repeats_once_more_is_still_the_sony_command():
    found = ir_recognise.recognise(_recording("sony12", {"code": 0x750}, repeats=1))
    assert (found["protocol"], found["parameters"]) == ("sony12", {"code": 0x750})


def test_a_recording_no_protocol_renders_back_is_not_recognised():
    noise = ir_signal.waveform([3000, -700, 450, -1300, 450, -700, 450, -20000],
                               carrier_hz=38000, sections={"intro_pulses": 4, "repeat_pulses": 4,
                                                "release_pulses": 0})
    assert ir_recognise.recognise(noise) is None
    assert ir_recognise.infer(noise) is None


def test_a_code_that_changes_while_held_is_kept_as_a_shape_of_its_own():
    # a Roku: NEC's frame, 32 bits, one code pressed and another while held
    def frame(value):
        bits = [pulse for i in range(32)
                for pulse in (562, -1688 if value >> (31 - i) & 1 else -562)]
        return [9000, -4500] + bits + [562]

    def padded(value):
        body = frame(value)
        return body + [-(108000 - sum(abs(p) for p in body))]
    press, held = padded(0x574354AB) + padded(0x574355AA), padded(0x574355AA)
    signal = ir_signal.waveform(press + held, carrier_hz=38000, name="OK",
                                sections={"intro_pulses": len(press),
                                                 "repeat_pulses": len(held),
                                                 "release_pulses": 0})
    assert ir_recognise.recognise(signal) is None
    definition, command = ir_recognise.infer(signal)
    payloads = [item["arguments"]["payload"] for item in command["transmission"]["press"]]
    assert payloads == ["0x574354AB", "0x574355AA"]
    assert command["protocol"] == definition["id"]
    rendered = ir_protocol.render_transmission(
        command, phase="hold", library={definition["id"]: definition})[0]
    assert ir_recognise._same(held, rendered["pulses_us"])


def test_a_one_recording_moved_to_the_900_keeps_its_command():
    from afterglow import migrate, project_devices, remotes

    device = {"schema": project_devices.SCHEMA, "id": "harmony-one-0", "label": "TV",
              "type": "Television", "commands": [["PowerOn", "PowerOn", "", "", None]],
              "signals": {"PowerOn": _nudged(_recording("nec1", {"address": 4, "command": 8}))}}
    project = {"devices": [device], "activities": [],
               "settings": {"remote": "harmony-one"}}
    moved, report = migrate.migrate(project, remotes.get("harmony-900"))
    assert "PowerOn" in moved["devices"][0]["signals"]
    assert not [row for row in report if row.get("change") == "removed"]
