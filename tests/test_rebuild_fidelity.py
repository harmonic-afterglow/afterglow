"""Importing a real configuration and building it again must not change what the remote does.

A rebuild that passes every structural check can still behave differently. Eleven of one
owner's Harmony 900 backups came back with keys bound that Logitech had left unbound - 27
of them on an activity that bound none - and with `AlwaysOn` written as false on devices
that had none, which makes activities start switching a camera and a bank of radio
sockets they never touched. Each difference was small; together they meant editing one
activity name could change how the whole remote behaves.

So per device and per activity, the keys bound, the properties and their values, and the
states declared must come back exactly as they went in.
"""
from __future__ import annotations

import contextlib
import io
import re
import zipfile

from afterglow import build_service, ezhex, importer


def _user_configuration(path) -> str:
    raw = path.read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    return zipfile.ZipFile(io.BytesIO(raw[start:start + size])).read(
        "userconfig/UserConfiguration.xml").decode("utf-8", "replace")


def _behaviour(xml: str) -> dict:
    out = {}
    for kind, pattern in (("device", r"<Device><Id>(\d+)</Id>.*?</Device>"),
                          ("activity", r"<Activity><Id>(-?\d+)</Id>.*?</Activity>")):
        for match in re.finditer(pattern, xml, re.S):
            body = match.group(0)
            keys = set()
            for group in re.findall(
                    r'<ControlGroup name="HardButtons">(.*?)</ControlGroup>', body, re.S):
                keys |= set(re.findall(r'<Button name="([^"]+)"', group))
            out[(kind, match.group(1))] = {
                "keys": keys,
                "properties": dict(re.findall(
                    r'<Property name="([^"]+)">([^<]*)</Property>', body)),
                "states": {re.match(r"<Id>([^<]*)", state).group(1)
                           for state in re.findall(r"<State>(.*?)</State>", body, re.S)},
            }
    return out


def test_a_rebuilt_real_configuration_behaves_as_the_original(configs, tmp_path):
    for index, config in enumerate(configs):
        tree, out = tmp_path / f"tree-{index}", tmp_path / f"rebuilt-{index}.ezhex"
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(str(config), str(tree))
            project = importer.build_project(str(tree))
            project["settings"].update(out_file=str(out), first_name="T", last_name="U")
            build_service.ConfigBuildService(tmp_path, lambda _m: None).build(project)
        before = _behaviour(_user_configuration(config))
        after = _behaviour(_user_configuration(out))
        for owner, original in before.items():
            assert owner in after, f"{config.name}: {owner} is gone"
            for aspect, value in original.items():
                assert after[owner][aspect] == value, (
                    f"{config.name}: {owner} {aspect} changed: {value} -> "
                    f"{after[owner][aspect]}")
