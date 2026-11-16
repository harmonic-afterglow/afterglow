"""A remote sold in Europe says a skin of its own - the 650 sold there says 74, the 700 69,
the 900 60, the One 59, the 800 87 (Logitech's MyHarmony catalogue, Region 2). It is the
same remote: its backup opens as one, a build for it says its skin again, and a write to
it passes the identity checks."""
from __future__ import annotations

import dataclasses
import zipfile

import pytest

from afterglow import concord, ezhex, remotes
from afterglow.backends import BuildContext, for_profile

pytestmark = pytest.mark.slow

EUROPEAN = {"harmony-650": 74, "harmony-700": 69, "harmony-900": 60,
            "harmony-one": 59, "harmony-800": 87}


def _header(profile, skin):
    return ezhex.header_for_profile(dataclasses.replace(profile, skin=skin))


@pytest.mark.parametrize("remote_id,skin", sorted(EUROPEAN.items()))
def test_a_european_remote_is_the_remote_it_was_sold_as(remote_id, skin):
    profile = remotes.get(remote_id)
    header = _header(profile, skin)
    assert remotes.identify(header).id == remote_id
    identity = remotes.identity_of(header)
    assert profile.identity_mismatches(identity, require_all=True) == []
    # a European remote's name says so, rather than passing for its American sibling
    assert remotes.model_name(profile, skin) != remotes.model_name(profile, profile.skin)


def _skin_byte(remote_id, image: bytes) -> int:
    import importlib
    backend = remote_id.replace("-", "_").replace("harmony_700", "harmony_650")
    gspm = importlib.import_module(f"afterglow.backends.{backend}.gspm")
    return image[gspm.section_ranges(image)[1][0] + 2]


def _build(remote_id, skin, tmp_path):
    profile = remotes.get(remote_id)
    context = BuildContext(root=tmp_path, log=lambda _line: None,
                           find_scaffold=lambda _id, _root: None)
    project = {"devices": [], "activities": [],
               "settings": {"out_file": "europe", "skin": skin}}
    return profile, for_profile(profile).build_project(project, profile, context).artifact


@pytest.mark.parametrize("remote_id", ["harmony-one", "harmony-650", "harmony-700"])
def test_a_build_for_a_european_one_650_or_700_says_its_skin(remote_id, tmp_path):
    skin = EUROPEAN[remote_id]
    profile, path = _build(remote_id, skin, tmp_path)
    raw = path.read_bytes()
    header, start, size, _checksum = ezhex._split(raw)
    assert remotes.identity_of(header)["skin"] == skin
    assert _skin_byte(remote_id, raw[start:start + size]) == skin
    remote = {**remotes.identity_of(_header(profile, skin))}
    assert concord.file_mismatches(path, remote) == []


def test_a_build_for_a_european_800_says_its_skin_and_imports_as_one(tmp_path):
    from afterglow import importer
    from afterglow.backends.harmony_800 import backend

    profile, path = _build("harmony-800", 87, tmp_path)
    with zipfile.ZipFile(path) as archive:
        assert b"<SKIN>87</SKIN>" in archive.read(ezhex.MH_DESCRIPTION)
    assert _skin_byte("harmony-800", backend.read_configuration_file(path)) == 87
    assert concord.file_mismatches(path, {"arch": 18, "skin": 87, "software_type": 0}) == []
    project = importer.import_file(path).project
    assert (project["settings"]["remote"], project["settings"]["skin"]) == ("harmony-800", 87)


def test_a_project_cannot_name_a_skin_its_remote_is_not_sold_as(tmp_path):
    with pytest.raises(ValueError, match="skin 54"):
        _build("harmony-800", 54, tmp_path)
