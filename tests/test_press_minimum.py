"""A device's fewest frames a press sends (Logitech's `pressMinRepeats`): a Sony receiver
ignored the one frame Sony 15-bit's own press sends (a tester's STR-K750P, 2026-11)."""
from __future__ import annotations

import contextlib
import io
import zipfile

from afterglow import ezhex, ir_signal, project_devices
from afterglow.corpus_provider import _archive_timing


def test_the_archive_s_press_minimum_comes_with_the_device():
    assert _archive_timing({"interKeyDelay": 100, "pressMinRepeats": 3})["press_minimum"] == 3
    assert "press_minimum" not in _archive_timing({"pressMinRepeats": 1})


def _frames_sent(build, minimum: int | None) -> int:
    from afterglow.backends.harmony_pk import irproto, ir_vm

    device = {"schema": project_devices.SCHEMA, "id": "40009001", "label": "Receiver",
              "type": "Receiver", "commands": [["PowerOn", "PowerOn", "", "", None]],
              "signals": {"PowerOn": ir_signal.protocol_signal("sony15", {"code": 0x5D30})},
              **({"press_minimum": minimum} if minimum else {})}
    out = build({"devices": [device], "activities": [], "assets": []},
                name=f"minimum-{minimum}.ezhex")
    raw = out.read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    archive = zipfile.ZipFile(io.BytesIO(raw[start:start + size]))
    table = out.with_suffix(".IrProto.bin")
    table.write_bytes(archive.read("userconfig/IrProto.bin"))
    payload = irproto.read_payload(str(table))
    config = archive.read("userconfig/UserConfiguration.xml").decode()
    code = config.split("<Name>PowerOn</Name>", 1)[1].split("<Code>", 1)[1].split("<", 1)[0]
    pulses = ir_vm.simulate_transmission(payload, code).pulses_us
    return sum(1 for pulse in pulses if pulse >= 2000)


def test_a_press_sends_at_least_the_device_s_minimum_of_frames(build):
    with contextlib.redirect_stdout(io.StringIO()):
        assert _frames_sent(build, None) == 3          # the library's Sony press
        assert _frames_sent(build, 5) == 5
