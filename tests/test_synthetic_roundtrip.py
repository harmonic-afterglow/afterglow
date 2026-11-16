"""The round-trip gate, on a configuration made here, so it runs everywhere - CI too.

Real configurations are never committed, so `test_ezhex_roundtrip` and the container
tests skip on a checkout without `configs/`. This file builds one with the properties
those tests exist for: a CRLF header, stored and deflated entries side by side, Unix
modes, Info-ZIP local extra fields longer than the central directory's - and a GSPM
blob for the 650 and 700. unpack -> pack must give back the same bytes.
"""
from __future__ import annotations

import contextlib
import io
import struct
import zipfile

import pytest

from afterglow import ezhex, remotes
from afterglow.payloads import pk

# Info-ZIP's "UT" extended timestamp: the local header carries mtime and atime, the
# central directory mtime alone; and "ux" (uid/gid) only locally - as Logitech's do.
CENTRAL_UT = struct.pack("<HHB I", 0x5455, 5, 3, 1_600_000_000)
LOCAL_UT = struct.pack("<HHB II", 0x5455, 9, 3, 1_600_000_000, 1_600_000_100)
LOCAL_UX = struct.pack("<HH", 0x7875, 0)

ENTRIES = [  # name, contents, stored?, mode
    ("userconfig/", b"", True, 0o40755),
    ("userconfig/UserConfiguration.xml", b"<Configuration>" + b"<Device/>" * 400
     + b"</Configuration>", False, 0o100644),
    ("userconfig/image/", b"", True, 0o40755),
    ("userconfig/image/logo.png", bytes(range(256)) * 4, True, 0o100644),
    ("bin/", b"", True, 0o40755),
    ("bin/run.sh", b"#!/bin/sh\r\nexit 0\r\n", False, 0o100755),
]


def _payload() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data, stored, mode in ENTRIES:
            info = zipfile.ZipInfo(name, date_time=(2020, 9, 13, 12, 26, 40))
            info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = mode << 16
            info.extra = CENTRAL_UT
            archive.writestr(info, data)
    return pk._patch_local_extras(buffer.getvalue(),
                                  {name: LOCAL_UT + LOCAL_UX for name, *_ in ENTRIES})


def _ezhex(payload: bytes, remote: str) -> bytes:
    return ezhex.header_for_profile(remotes.get(remote), bds=len(payload),
                                    cks=ezhex.checksum(payload)) + payload


@pytest.fixture
def synthetic(tmp_path):
    path = tmp_path / "synthetic.ezhex"
    path.write_bytes(_ezhex(_payload(), "harmony-900"))
    return path


def _repack(path, tmp_path, *, keep_header=True):
    tree = tmp_path / "tree"
    out = tmp_path / "repacked.ezhex"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(path), str(tree))
        if not keep_header:
            (tree / ".ezhex_header").unlink()
        ezhex.pack_standalone(str(tree), str(out), do_rehash=False,
                              profile=None if keep_header else remotes.get("harmony-900"))
    return out.read_bytes()


def test_the_fixture_has_what_the_gate_is_for(synthetic):
    payload = ezhex.read(synthetic.read_bytes()).payload
    archive = zipfile.ZipFile(io.BytesIO(payload))
    kinds = {info.compress_type for info in archive.infolist()}
    assert kinds == {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
    local = {name: extra for _o, name, extra, _h, _c in pk._iter_local(payload)}
    assert all(local[info.filename] != info.extra for info in archive.infolist())
    assert b"\r\n" in ezhex.read(synthetic.read_bytes()).header


def test_unpack_then_pack_is_byte_identical(synthetic, tmp_path):
    assert _repack(synthetic, tmp_path) == synthetic.read_bytes()


def test_a_generated_header_uses_single_crlf(synthetic, tmp_path):
    header = ezhex.read(_repack(synthetic, tmp_path, keep_header=False)).header
    assert header.count(b"\r\r\n") == 0 and header.count(b"\r\n") > 0


def test_modes_and_local_extras_survive(synthetic, tmp_path):
    payload = ezhex.read(_repack(synthetic, tmp_path, keep_header=False)).payload
    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert {info.filename: info.external_attr >> 16 for info in archive.infolist()} == {
        name: mode for name, _data, _stored, mode in ENTRIES}
    local = {name: extra for _o, name, extra, _h, _c in pk._iter_local(payload)}
    assert set(local.values()) == {LOCAL_UT + LOCAL_UX}


@pytest.mark.parametrize("remote", ["harmony-650", "harmony-700"])
def test_a_gspm_blob_round_trips(remote, tmp_path):
    import importlib
    compose = importlib.import_module(f"afterglow.backends.{remote.replace('-', '_')}.compose")
    household = importlib.import_module(f"test_{remote.replace('-', '_')}")._household()
    image = compose.build(household, stamp_fields=(0, 0, 12, 0, 0, 2026))["image"]
    path = tmp_path / "built.ezhex"
    path.write_bytes(_ezhex(image, remote))
    assert _repack(path, tmp_path) == path.read_bytes()
