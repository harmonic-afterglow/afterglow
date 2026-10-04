"""A shareable copy of a dump carries nothing about its owner, and nothing else changes.

People held back their configurations because a dump names its owner. The copy replaces
exactly that - the account id, first and last name, measured as the only personal fields
in eighteen Harmony 900 configurations - and must otherwise be the same configuration.
"""
from __future__ import annotations

import contextlib
import io
import re
import zipfile

import pytest

from afterglow import ezhex, share


def _entries(path):
    raw = path.read_bytes()
    _header, start, size, _checksum = ezhex._split(raw)
    archive = zipfile.ZipFile(io.BytesIO(raw[start:start + size]))
    return {name: archive.read(name) for name in archive.namelist()}


def test_a_shared_dump_names_nobody_and_is_otherwise_the_same(configs, tmp_path):
    for index, config in enumerate(configs):
        copy = tmp_path / f"shared-{index}.ezhex"
        changes = share.make_shareable(config, copy)

        before, after = _entries(config), _entries(copy)
        assert set(before) == set(after)
        assert [name for name in before if before[name] != after[name]] in (
            [], ["userconfig/UserConfiguration.xml"])
        original = before["userconfig/UserConfiguration.xml"].decode("utf-8", "replace")
        owner = re.search(r"<User><Id>([^<]*)</Id>.*?<FirstName>([^<]*)</FirstName>"
                          r"<LastName>([^<]*)</LastName>", original, re.S).groups()
        # Searched in every entry's decompressed content: the raw file is deflated, so
        # a name could sit in it unseen by a search of its bytes.
        shared = copy.read_bytes()[:ezhex._split(copy.read_bytes())[1]] + b"".join(
            after.values())
        # As a whole field: a donor's first name "Mark" is also inside a light made by
        # "Marks", which is the user's own device data and stays.
        for value in owner:
            if value not in ("10000000", "Harmony", "User"):
                assert f">{value}<".encode() not in shared, f"{config.name}: owner kept"
        assert changes or owner == ("10000000", "Harmony", "User")
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.verify(str(copy))


def test_the_original_is_never_overwritten(a_config):
    with pytest.raises(ValueError, match="must not replace"):
        share.make_shareable(a_config, a_config)


def test_a_remote_whose_owner_cannot_be_found_gets_no_copy(a_config, tmp_path, monkeypatch):
    """Labelling a copy safe while it still carries a name is worse than refusing."""
    from afterglow import backends

    class Backend:
        pass
    monkeypatch.setattr(backends, "for_profile", lambda _profile: Backend())
    with pytest.raises(share.NotAnonymisable):
        share.make_shareable(a_config, tmp_path / "x.ezhex")
    assert not (tmp_path / "x.ezhex").exists()
