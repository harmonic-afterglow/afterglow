"""An RF Wireless Extender is read the three read-only ways, and nothing is written.

An extender (skins 20 and 24) identifies on a remote's USB protocol but has no user
configuration region. Read tries its memory, configuration region 0 the 6.0 way, and
its regions, and saves whatever comes in a zip with every answer.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from afterglow import concord, extender_dump


class _Unit:
    """A fake extender: memory at `memory` (start -> bytes), INVALID_ADDRESS elsewhere."""

    def __init__(self, regions=None, memory=None, config6=None, memory_status=None):
        self.regions, self.memory = regions or {}, memory or {}
        self.config6, self.memory_status = config6, memory_status
        self.asked, self.memory_asked = [], []

    def read_memory(self, address, size):
        self.memory_asked.append((address, size))
        if self.memory_status is not None:
            return b"", self.memory_status
        for start, data in self.memory.items():
            if start <= address < start + len(data):
                return data[address - start:address - start + size], 0
        return b"", extender_dump.INVALID_ADDRESS

    def read_legacy_config(self, region=0):
        if self.config6 is None:
            return b"", 0x0B
        return self.config6, 0

    def read_region(self, region, on_progress=None):
        self.asked.append(region)
        if region not in self.regions:
            raise concord.RemoteError(f"reading region {region}: unsupported")
        return self.regions[region]


IDENTITY = {"skin": 24, "arch": 10, "model": "Harmony 896"}


def test_only_the_extenders_skins_are_read_this_way():
    assert extender_dump.regions_for(24) == [8, 9, 7]
    assert extender_dump.regions_for(20) == [8, 9, 7]
    for skin in (61, 63, 19, None, "x"):          # the 900, 1100, 890, and nonsense
        assert extender_dump.regions_for(skin) == []


def test_listed_regions_win_and_7_goes_last():
    assert extender_dump.order([0, 1, 2, 7, 5, 9], [8, 9, 7]) == [0, 1, 2, 5, 9, 7]
    assert extender_dump.order([], [8, 9, 7]) == [8, 9, 7]


def test_memory_blocks_that_answer_are_read_whole(tmp_path):
    flash = bytes(range(256)) * 256                    # 64 KB at 0
    unit = _Unit(memory={0: flash, 0x100000: b"\x01" * 0x10000})
    saved, size = extender_dump.save(unit, tmp_path / "x.ezhex", [], IDENTITY)
    with zipfile.ZipFile(saved) as archive:
        assert archive.read("memory-000000.bin") == flash
        assert archive.read("memory-100000.bin") == b"\x01" * 0x10000
        about = json.loads(archive.read("identity.json"))
    assert size == 0x20000
    assert about["notes"]["config6"] == "refused, status 0B"
    assert len(unit.memory_asked) == 256 + 2, "every 64 KB probed, two blocks read"


def test_a_memory_service_that_says_no_is_not_probed_further(tmp_path):
    unit = _Unit(regions={9: b"state"}, memory_status=0x05)
    extender_dump.save(unit, tmp_path / "x.ezhex", [9], IDENTITY)
    assert unit.memory_asked == [(0, 16)]


def test_everything_that_comes_is_saved_and_refusals_noted(tmp_path):
    unit = _Unit(regions={9: b"state"}, config6=b"config")
    lines = []
    saved, size = extender_dump.save(unit, tmp_path / "x.ezhex", [8, 9, 7], IDENTITY,
                                     log=lines.append)
    assert unit.asked == [8, 9, 7], "a refused region does not stop the rest"
    with zipfile.ZipFile(saved) as archive:
        assert archive.read("config6-00.bin") == b"config"
        assert archive.read("region-09.bin") == b"state"
        about = json.loads(archive.read("identity.json"))
    assert size == 11
    assert set(about["notes"]["regions_refused"]) == {"8", "7"}
    assert any("Region 7 not read" in line for line in lines)


def test_a_unit_that_hands_over_nothing_is_an_error(tmp_path):
    with pytest.raises(concord.RemoteError, match="handed over nothing"):
        extender_dump.save(_Unit(), tmp_path / "x.ezhex", [8, 7], IDENTITY)
    assert not (tmp_path / "x.zip").exists()


def test_read_saves_an_extender_not_a_configuration(tmp_path, monkeypatch):
    from afterglow.gui import remote_ops
    saved_config = []
    unit = _Unit(regions={8: b"x", 9: b"y", 7: b"z"})

    class Remote:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def identity(self, *_a):
            return {"mfg": "Logitech", "model": "Harmony 896", "skin": 24, "arch": 10,
                    "firmware": "2.5", "config_valid": True, "can_read": True}

        def listed_regions(self):
            return []

        read_memory = staticmethod(unit.read_memory)
        read_legacy_config = staticmethod(unit.read_legacy_config)
        read_region = staticmethod(unit.read_region)

        def save_config(self, path, *_a):
            saved_config.append(path)

    monkeypatch.setattr(remote_ops.concord, "Remote", Remote)
    worker = remote_ops.RemoteWorker("read", None, path=str(tmp_path / "unit.ezhex"))
    said, results = {}, []
    worker.done.connect(lambda ok, text: said.update(ok=ok, text=text))
    worker.result.connect(results.append)
    worker.run()
    assert said["ok"] is True, said
    assert unit.asked == [8, 9, 7] and saved_config == []
    assert results == [tmp_path / "unit.zip"]
