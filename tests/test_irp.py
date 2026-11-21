"""The IRP renderer: every shipped definition parses and renders, and where a protocol
also has a shipped native definition, both send the same thing."""
import json

import pytest

from afterglow import ir_protocol, irp, paths
from afterglow.public_ir_sources import _flipper_signal, _irdb_signal


def _definitions():
    return json.loads(paths.library("irp", "protocols.json").read_text(
        encoding="utf-8"))["protocols"]


def test_every_shipped_definition_parses():
    for entry in _definitions():
        protocol = irp.parse(entry["irp"])
        assert protocol.carrier >= 0, entry["name"]


def _example(protocol) -> dict:
    """The lowest value each parameter without a default may take."""
    return {name: low for name, (low, _high, default) in protocol.parameters.items()
            if default is None}


def test_every_sendable_definition_renders_pulses():
    failed = []
    for entry in _definitions():
        if entry.get("decode_only"):
            continue
        protocol = irp.parse(entry["irp"])
        if not protocol.parameters and entry["name"] == "NEC-Shirriff":
            continue                          # "data:length", neither of them declared
        try:
            signal = irp.waveform_signal(entry, _example(protocol))
        except irp.IrpError as exc:
            if protocol.carrier > 0:          # unmodulated ones are refused, and say so
                failed.append(f"{entry['name']}: {exc}")
            continue
        pulses = signal["pulses_us"]
        assert all(pulses), entry["name"]
        assert all((a > 0) != (b > 0) for a, b in zip(pulses, pulses[1:])), entry["name"]
    assert not failed


def _close(ours, theirs):
    """The same marks and gaps, each within 3% or 60 us - IRP's NEC counts in 564 us
    units where the shipped definition says 562. The gap that ends a frame only has to
    be one: the definitions disagree on the frame period (NEC2: 108 ms in IRP, 95 here;
    JVC's lead-out), and a receiver waits for the next leader either way."""
    assert len(ours) == len(theirs), (ours, theirs)
    for a, b in zip(ours[:-1], theirs[:-1]):
        assert (a > 0) == (b > 0) and abs(a - b) <= max(60, abs(b) * 0.03), (ours, theirs)
    assert ours[-1] < -10_000 and theirs[-1] < -10_000


def _native(signal, phase):
    waveform, _state = ir_protocol.render_transmission(signal, phase=phase)
    return waveform["pulses_us"]


@pytest.mark.parametrize("protocol, device, subdevice, function, press, hold", [
    ("NEC1", 4, -1, 8, "intro", "repeat"),
    ("NEC1", 4, 7, 8, "intro", "repeat"),
    ("NEC2", 4, -1, 8, "repeat", "repeat"),
    ("NECx2", 7, 7, 2, "repeat", "repeat"),
    ("JVC", 3, -1, 23, "intro", "repeat"),
    ("Sony12", 1, -1, 21, None, "repeat"),
    ("Sony15", 151, -1, 42, None, "repeat"),
    ("Sony20", 26, 209, 51, None, "repeat"),
])
def test_irp_sends_what_the_shipped_definition_does(protocol, device, subdevice, function,
                                                    press, hold):
    signal, _why = _irdb_signal({"protocol": protocol, "device": str(device),
                                 "subdevice": str(subdevice), "function": str(function)})
    assert signal["kind"] == "protocol"          # read natively
    entry, values = irp.resolve("irdb", protocol, {
        "D": device, "S": subdevice if subdevice >= 0 else None, "F": function})
    rendered = irp.render(irp.parse(entry["irp"]), values)
    if press:
        _close(getattr(rendered, press), _native(signal, "press"))
    _close(getattr(rendered, hold), _native(signal, "hold"))


def test_rc5_sends_both_toggles_as_the_shipped_definition_does():
    signal, _why = _irdb_signal({"protocol": "RC5", "device": "5", "subdevice": "-1",
                                 "function": "53"})
    first = _native(signal, "press")
    _waveform, state = ir_protocol.render_transmission(signal, phase="press")
    second, _state = ir_protocol.render_transmission(signal, phase="press", state=state)
    entry, values = irp.resolve("irdb", "RC5", {"D": 5, "F": 53})
    ours = irp.waveform_signal(entry, values)
    sent = {tuple(ours["pulses_us"][:-1]), tuple(ours["alternate"]["pulses_us"][:-1])}
    assert sent == {tuple(first[:-1]), tuple(second["pulses_us"][:-1])}


def test_jvc_from_irdb_and_flipper_is_sent_lowest_bit_first():
    """IRDB's JVC 3,23 and Flipper's address 03, command 17 are one code: address then
    command, each lowest bit first (IRP JVC: D:8,F:8 lsb)."""
    irdb, _why = _irdb_signal({"protocol": "JVC", "device": "3", "subdevice": "-1",
                               "function": "23"})
    flipper, _why = _flipper_signal({"type": "parsed", "protocol": "JVC",
                                     "address": "03 00 00 00", "command": "17 00 00 00"})
    assert irdb["parameters"] == flipper["parameters"] == {"code": 0b11000000_11101000}


def test_kaseikyo_from_flipper_matches_irdb_panasonic():
    """A Panasonic TV's Power: IRDB 'Panasonic' 128,0,61 and Flipper's Kaseikyo."""
    irdb, _why = _irdb_signal({"protocol": "Panasonic", "device": "128", "subdevice": "0",
                               "function": "61"})
    flipper, _why = _flipper_signal({"type": "parsed", "protocol": "Kaseikyo",
                                     "address": "80 02 20 00", "command": "D0 03 00 00"})
    assert irdb["pulses_us"] == flipper["pulses_us"]


def test_kaseikyo_from_flipper_ends_with_the_xor_of_the_bytes_before_it():
    """JVC's vendor (01 03) has a parity nibble of 2, where IrpTransmogrifier's Kaseikyo
    checksum and Flipper's differ."""
    signal, _why = _flipper_signal({"type": "parsed", "protocol": "Kaseikyo",
                                    "address": "A0 03 01 01", "command": "5B 02 00 00"})
    pulses = signal["pulses_us"][2:2 + 96]
    bits = [1 if -gap > 900 else 0 for gap in pulses[1::2]]
    data = [sum(bit << i for i, bit in enumerate(bits[at:at + 8])) for at in range(0, 48, 8)]
    assert data[:2] == [0x03, 0x01]
    assert data[2] == (0xA << 4) | 2 and data[3] == 0x00 | (0xB << 4)
    assert data[4] == 0x25 | (1 << 6)
    assert data[5] == data[2] ^ data[3] ^ data[4]


def test_plain_nec_from_irdb_is_sent():
    """IRDB names an NEC1 frame seen without its repeat 'NEC' - the Xbox 360's."""
    signal, why = _irdb_signal({"protocol": "NEC", "device": "128", "subdevice": "38",
                                "function": "12"})
    assert signal is not None, why
    assert signal["protocol"] == "nec-ext"


def test_a_refused_name_says_why():
    signal, why = _irdb_signal({"protocol": "Barco", "device": "1", "subdevice": "-1",
                                "function": "2"})
    assert signal is None and "Barco" in why and "carrier" in why


def test_every_remote_takes_what_irp_renders():
    """A rendered command is a recording with an intro, a repeat and, for a toggle, the
    other press: every remote has to accept it, the 1100 included, which looked every
    recording up as a protocol and refused it."""
    from afterglow import backends, remotes
    signals = {
        "RC6": _flipper_signal({"type": "parsed", "protocol": "RC6",
                                "address": "00 00 00 00", "command": "0C 00 00 00"})[0],
        "Kaseikyo": _flipper_signal({"type": "parsed", "protocol": "Kaseikyo",
                                     "address": "80 02 20 00",
                                     "command": "D0 03 00 00"})[0],
        "MCE": _irdb_signal({"protocol": "MCE", "device": "116", "subdevice": "15",
                             "function": "12"})[0],
        "Tivo": _irdb_signal({"protocol": "Tivo unit=3", "device": "133",
                              "subdevice": "48", "function": "16"})[0],
    }
    refused = {}
    for profile in remotes.load_all():
        backend = backends.for_profile(profile)
        for name, signal in signals.items():
            answer = backend.capability(signal, profile)
            if not answer.get("supported"):
                refused[(profile.id, name)] = answer.get("reason")
    assert not refused
