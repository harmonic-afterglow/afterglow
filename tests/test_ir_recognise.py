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


def _padded(body: list[int], period: int) -> list[int]:
    return body + [-(period - sum(abs(pulse) for pulse in body))]


def _distance(value: int, bits: int, mark: int, zero: int, one: int) -> list[int]:
    return [pulse for i in range(bits)
            for pulse in (mark, -(one if value >> (bits - 1 - i) & 1 else zero))]


def _waveform(press, held, release=(), carrier=38000, name="OK") -> dict:
    return ir_signal.waveform(list(press) + list(held) + list(release), carrier_hz=carrier,
                              name=name, sections={"intro_pulses": len(press),
                                                   "repeat_pulses": len(held),
                                                   "release_pulses": len(release)})


def _renders(definition, command, phase):
    return ir_protocol.render_transmission(
        command, phase=phase, library={definition["id"]: definition})[0]["pulses_us"]


def test_a_nec_frame_no_library_protocol_reads_is_its_own_shape_its_ditto_held():
    # a TiVo: NEC's frame with a fourth byte that is not the command inverted
    data = _padded([8990, -4490] + _distance(0x8530200D, 32, 568, 552, 1662) + [568], 108000)
    ditto = _padded([8990, -2230, 568], 108000)
    signal = _waveform(data + ditto, ditto)
    assert ir_recognise.recognise(signal) is None
    definition, command = ir_recognise.infer(signal)
    assert command["transmission"]["press"] == [
        {"frame": "data", "arguments": {"payload": "0x8530200D"}}, {"frame": "ditto"}]
    assert command["transmission"]["hold"] == [{"frame": "ditto"}]
    assert ir_recognise._same(ditto, _renders(definition, command, "hold"))


def test_frames_eight_milliseconds_apart_are_frames():
    # an RCA: 24 bits, 8.2 ms between frames - and the fixed waveform its press is
    frame = [3929, -4000] + _distance(0xF8E1C6, 24, 500, 1000, 2000) + [500, -8200]
    signal = _waveform(frame * 3, frame, carrier=56000)
    definition, command = ir_recognise.infer(signal)
    assert definition["frames"]["data"]["parameters"] == {"payload": {"bits": 24}}
    assert [item["arguments"]["payload"] for item in command["transmission"]["press"]] \
        == ["0xF8E1C6"] * 3
    fixed = ir_recognise.repeated(signal)
    assert fixed["pulses_us"] == frame * 3 and "sections" not in fixed


def test_a_frame_split_by_a_long_space_reads_both_halves():
    # a Samsung36: 16 bits, a separator, 20 bits
    body = ([4500, -4480] + _distance(0x0400, 16, 495, 500, 1495) + [495, -4495]
            + _distance(0xE24DB, 20, 495, 500, 1495) + [495])
    frame = _padded(body, 119700)
    definition, command = ir_recognise.infer(_waveform(frame, frame))
    assert definition["bursts"]["separator"] == [495, -4495]
    assert command["transmission"]["press"] == [
        {"frame": "data", "arguments": {"payload": "0x0400", "payload2": "0xE24DB"}}]


def test_a_last_bit_whose_space_is_the_gap_is_read_by_its_mark():
    # a fan: no header, 12 bits each a long or short mark, the last one's space the gap
    body = [pulse for i in range(12) for pulse in
            ((1268, -425) if 0b110110000001 >> (11 - i) & 1 else (415, -1278))]
    frame = body[:-1] + [-7210]
    definition, command = ir_recognise.infer(_waveform(frame * 3, frame, carrier=37470))
    assert [item["arguments"]["payload"] for item in command["transmission"]["hold"]] \
        == ["0xD81"]
    assert "header" not in definition["bursts"]


def test_a_two_bit_code_sent_again_on_release_is_its_own_shape():
    # a Foxtel: RC-MM, sixteen two-bit symbols, and on release the code then a variant
    def frame(value, gap):
        symbols = [value >> (30 - 2 * i) & 3 for i in range(16)]
        body = [416, -277] + [p for s in symbols for p in (160, -(277 + 167 * s))] + [160]
        return body + [-gap]
    press = frame(0x2D4E1B3A, 89500)
    release = frame(0x2D4E1B3A, 19300) + frame(0x2D4F1B3A, 19300)
    signal = _waveform(press, press, release, carrier=36000)
    definition, command = ir_recognise.infer(signal)
    assert definition["alphabets"]["bits"]["bits_per_symbol"] == 2
    assert [item["arguments"]["payload"] for item in command["transmission"]["release"]] \
        == ["0x2D4E1B3A", "0x2D4F1B3A"]
    assert ir_recognise._same(release, _renders(definition, command, "release"))


def test_an_rc5_recording_and_its_alternate_are_the_toggling_rc5_command():
    spec = ir_protocol.catalog()["rc5-13"]

    def recording(state):
        press, _after = ir_protocol.transmission(spec, {"code": 1106}, "press", state=state)
        return _waveform(press * 4, press, carrier=36001, name="Exit")
    signal = recording({"toggle": 1})
    signal["alternate"] = {key: recording({"toggle": 0})[key]
                           for key in ("pulses_us", "sections")}
    found = ir_recognise.recognise(signal)
    assert (found["protocol"], found["parameters"]) == ("rc5-13", {"code": 1106})
    # two recordings of one toggle are no toggling code
    signal["alternate"] = {key: signal[key] for key in ("pulses_us", "sections")}
    assert ir_recognise.recognise(signal) is None


def test_each_kind_of_650_recording_builds_for_the_900():
    from afterglow import project_devices, remotes
    from afterglow.backends.harmony_pk import backend

    data = _padded([8990, -4490] + _distance(0x8530200D, 32, 568, 552, 1662) + [568], 108000)
    ditto = _padded([8990, -2230, 568], 108000)
    samsung = _padded([4500, -4480] + _distance(0x0400, 16, 495, 500, 1495) + [495, -4495]
                      + _distance(0xE24DB, 20, 495, 500, 1495) + [495], 119700)
    signals = {"Record": _waveform(data + ditto, ditto, name="Record"),
               "Eject": _waveform(samsung, samsung, name="Eject")}
    device = {"schema": project_devices.SCHEMA, "id": "40009001", "label": "DVR",
              "type": "Television", "commands": [[name, name, "", "", None] for name in signals],
              "signals": signals}
    [lowered] = backend.lower_devices([device], remotes.get("harmony-900"))
    assert lowered["signals"]["Record"]["kind"] == "protocol"
    # the 900's protocol element plays no space between two runs of bits: a frame split
    # so goes as the one fixed waveform its press is
    assert lowered["signals"]["Eject"]["kind"] == "waveform"
    assert "sections" not in lowered["signals"]["Eject"]
