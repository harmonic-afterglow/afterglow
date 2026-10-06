"""A build says when it was made: the remote's Remote info shows this as its last update.

The scaffold every build starts from carries LastUpdated 20200215, so every
configuration Afterglow wrote told the remote it had last been updated in 2020.
"""
from __future__ import annotations

import io
import re
import time
import zipfile

from afterglow import ezhex, ir_signal


def _project():
    return {"activities": [], "devices": [{
        "schema": "afterglow-project-device/1", "id": "1", "label": "TV",
        "type": "Television", "mfr": "T", "model": "M",
        "commands": [["PowerToggle", "PowerToggle", "", "", None]],
        "signals": {"PowerToggle": ir_signal.protocol_signal(
            "nec1", {"address": 1, "command": 1})}}]}


def _last_updated(path):
    raw = path.read_bytes()
    _h, start, size, _c = ezhex._split(raw)
    xml = zipfile.ZipFile(io.BytesIO(raw[start:start + size])).read(
        "userconfig/UserConfiguration.xml").decode()
    return re.search(r'<Property name="LastUpdated">([^<]*)<', xml).group(1)


def test_a_build_is_stamped_with_the_time_it_was_made(build, monkeypatch):
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    before = time.strftime("%Y%m%d %H%M%S")
    stamp = _last_updated(build(_project()))
    assert re.fullmatch(r"\d{8} \d{6}", stamp)
    assert stamp >= before and not stamp.startswith("2020")


def test_source_date_epoch_pins_it_for_reproducible_builds(build, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1767225600")       # 2026-01-01 00:00 UTC
    assert _last_updated(build(_project())) == "20260101 000000"
