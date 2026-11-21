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


def _library(*signals):
    from afterglow import irp_portable
    return {**ir_protocol.catalog(), **irp_portable.definitions_for(signals)}


def _press(signal, state=None):
    """What one press sends, and the sender's state after it."""
    if signal["kind"] == "waveform":
        return signal["pulses_us"], None
    waveform, state = ir_protocol.render_transmission(
        signal, phase="press", state=state, library=_library(signal))
    return waveform["pulses_us"], state


def test_kaseikyo_from_flipper_matches_irdb_panasonic():
    """A Panasonic TV's Power: IRDB 'Panasonic' 128,0,61 and Flipper's Kaseikyo."""
    irdb, _why = _irdb_signal({"protocol": "Panasonic", "device": "128", "subdevice": "0",
                               "function": "61"})
    flipper, _why = _flipper_signal({"type": "parsed", "protocol": "Kaseikyo",
                                     "address": "80 02 20 00", "command": "D0 03 00 00"})
    assert _press(irdb)[0] == _press(flipper)[0]


def test_kaseikyo_from_flipper_ends_with_the_xor_of_the_bytes_before_it():
    """JVC's vendor (01 03) has a parity nibble of 2, where IrpTransmogrifier's Kaseikyo
    checksum and Flipper's differ."""
    signal, _why = _flipper_signal({"type": "parsed", "protocol": "Kaseikyo",
                                    "address": "A0 03 01 01", "command": "5B 02 00 00"})
    pulses = _press(signal)[0][2:2 + 96]
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


@pytest.mark.parametrize("device, subdevice, function", [
    (116, 15, 12), (4, 15, 255), (127, 0, 0)])
def test_mce_from_irdb_is_the_shipped_rc6_mce_and_sends_what_mce_does(
        device, subdevice, function):
    """IRDB's MCE (the Xbox 360's, Windows Media Center's) is read into the shipped,
    hardware-checked rc6-mce, which the 900 sends with its own RC6 element: a press and
    the next are MCE with T=0 and T=1. rc6-mce writes each bit the other way up."""
    signal, _why = _irdb_signal({"protocol": "MCE", "device": str(device),
                                 "subdevice": str(subdevice), "function": str(function)})
    assert signal["protocol"] == "rc6-mce"
    entry, values = irp.resolve("irdb", "MCE", {"D": device, "S": subdevice,
                                                "F": function})
    protocol = irp.parse(entry["irp"])
    first, state = _press(signal)
    second, _state = _press(signal, state)
    _close(first, irp.render(protocol, {**values, "T": 0}).repeat)
    _close(second, irp.render(protocol, {**values, "T": 1}).repeat)


@pytest.mark.parametrize("source, name, given, toggles, release", [
    ("irdb", "RECS80", {"D": 3, "F": 20}, True, False),
    ("irdb", "RC6", {"D": 0, "F": 12}, True, False),
    ("irdb", "Blaupunkt", {"D": 1, "F": 5}, False, True),
    ("irdb", "NRC17", {"D": 3, "F": 9}, False, True),
    ("irdb", "Denon", {"D": 2, "F": 9}, False, False),
    ("irdb", "XMP-1", {"D": 3, "S": 4, "F": 9}, False, False),
    ("flipper", "Kaseikyo", {"A": 0x200280, "C": 0x3D0}, False, False),
])
def test_an_irp_command_compiles_to_a_protocol_that_sends_the_same(
        source, name, given, toggles, release):
    """irp_portable accepts a definition only when it renders the IRP back; this says
    the protocols IRDB uses most are among them, toggle and release included."""
    from afterglow import irp_portable
    entry, values = irp.resolve(source, name, given)
    definition, _parameters = irp_portable.compile_command(entry, values)
    assert bool(definition.get("state")) == toggles
    assert bool(definition["transmission"]["release"]) == release


def test_what_no_definition_can_hold_stays_a_recording():
    """Zenith's field widths are the command's own: it is sent as rendered."""
    signal, _why = _irdb_signal({"protocol": "Zenith", "device": "6", "subdevice": "0",
                                 "function": "9"})
    assert signal["kind"] == "waveform"


def test_every_remote_plays_a_recording():
    """The 1100 looked every recording up as a protocol and refused it."""
    from afterglow import backends, remotes
    signal, _why = _irdb_signal({"protocol": "Zenith", "device": "6", "subdevice": "0",
                                 "function": "9"})
    refused = {profile.id: answer.get("reason") for profile in remotes.load_all()
               if not (answer := backends.for_profile(profile).capability(
                   signal, profile)).get("supported")}
    assert not refused


# what the 900's generic protocol element cannot play: RC6 mode 0's toggle is its
# double-width trailer bit, a second alphabet in one run of symbols; XMP is two halves
# with a gap between them. Neither may be frozen into one recording, which would lose
# the toggle (RC6) or the repeat (XMP).
NOT_ON_THE_900 = {"RC6", "XMP-1"}


def test_every_remote_takes_what_irp_compiles():
    from afterglow import backends, remotes
    signals = {
        "MCE": _irdb_signal({"protocol": "MCE", "device": "116", "subdevice": "15",
                             "function": "12"})[0],
        "RECS80": _irdb_signal({"protocol": "RECS80", "device": "3", "subdevice": "-1",
                                "function": "20"})[0],
        "Blaupunkt": _irdb_signal({"protocol": "Blaupunkt", "device": "1",
                                   "subdevice": "-1", "function": "5"})[0],
        "Denon": _irdb_signal({"protocol": "Denon", "device": "2", "subdevice": "-1",
                               "function": "9"})[0],
        "Kaseikyo": _flipper_signal({"type": "parsed", "protocol": "Kaseikyo",
                                     "address": "80 02 20 00",
                                     "command": "D0 03 00 00"})[0],
        "RC6": _flipper_signal({"type": "parsed", "protocol": "RC6",
                                "address": "00 00 00 00", "command": "0C 00 00 00"})[0],
        "XMP-1": _irdb_signal({"protocol": "XMP-1", "device": "3", "subdevice": "4",
                               "function": "9"})[0],
    }
    library = _library(*signals.values())
    refused = {}
    for profile in remotes.load_all():
        backend = backends.for_profile(profile)
        for name, signal in signals.items():
            answer = backend.capability(signal, profile, library=library)
            expected = not (profile.id == "harmony-900" and name in NOT_ON_THE_900)
            if bool(answer.get("supported")) != expected:
                refused[(profile.id, name)] = answer.get("reason")
    assert not refused


def test_the_900_keeps_a_toggle_and_a_release_through_a_build(tmp_path):
    """Built for a 900 and read back: RECS80's toggle, Blaupunkt's release frame and
    MCE's rc6-mce are still there - as a recording, the toggle never changed and the
    release could not be sent at all."""
    import contextlib
    import io
    from afterglow import device_json, importer
    from afterglow.build_service import ConfigBuildService
    from afterglow.public_ir_sources import IRDB_INDEX_URL, IRDB_RAW_URL, IrdbCatalog
    codes = ("functionname,protocol,device,subdevice,function\n"
             "POWER,RECS80,3,-1,20\nVOL+,Blaupunkt,1,-1,5\nPLAY,MCE,116,15,12\n")

    def fetch(url):
        if url == IRDB_INDEX_URL:
            return "Test/TV/1,-1.csv\n"
        assert url.startswith(IRDB_RAW_URL)
        return codes

    catalog = IrdbCatalog(fetch=fetch, remote_id="harmony-900")
    result = catalog.materialize(catalog.models("Test", "TV")[0])
    assert result["counts"]["excluded"] == 0
    spec = device_json.to_project_device(result["template"], device_id="40009001")
    spec["label"] = "Test TV"
    out = tmp_path / "irp.ezhex"
    project = {"devices": [spec], "activities": [], "settings": {
        "out_file": str(out), "remote": "harmony-900", "first_name": "T",
        "last_name": "U"}}
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(tmp_path, lambda _m: None).build(project)
        device = importer.import_file(str(out)).project["devices"][0]
    signals = device["signals"]
    carried = device.get("portable_protocol_definitions") or {}
    assert all(signal["kind"] == "protocol" for signal in signals.values())
    assert carried[signals["POWER"]["protocol"]].get("state")
    assert carried[signals["VOL+"]["protocol"]]["transmission"]["release"]
    assert signals["PLAY"]["protocol"] == "rc6-mce"
