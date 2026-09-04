"""The regression gate that matters: unpack -> pack must be BYTE-IDENTICAL.

This is the test that would have caught the bug that made every build refuse to
flash. `pack_standalone` used to write a header with a doubled `\\r\\r\\n` after
every line (real ones use CRLF), flatten every entry's Unix mode to one value,
deflate entries the original stored, and drop the 8 bytes of Info-ZIP extra that
live only in the local header. Each of those is invisible to "does it unzip?" and
fatal to "will the remote take it".

Any config the maintainer has is a valid fixture; the test skips whatever is not
present, because none of it can be committed (see README, "What is deliberately
not here").
"""
import contextlib
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from afterglow import ezhex  # noqa: E402

# Real configs, in the order we most want them checked. Two are Logitech-made
# donor dumps, two came off a remote; between them they cover both Info-ZIP
# variants (with and without local extra fields).
FIXTURES = ["configs/donor-2/backup.ezhex", "configs/donor-1/backup.ezhex",
            "configs/mine/dump.ezhex", "home.ezhex"]


def _present():
    return [p for p in FIXTURES if (ROOT / p).is_file()]


@pytest.mark.parametrize("name", FIXTURES)
def test_roundtrip_is_byte_identical(name, tmp_path):
    src = ROOT / name
    if not src.is_file():
        pytest.skip(f"{name} not present (real configs are never committed)")
    out = tmp_path / "repacked.ezhex"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(src), str(tmp_path / "tree"))
        ezhex.pack_standalone(str(tmp_path / "tree"), str(out), do_rehash=False)
    assert out.read_bytes() == src.read_bytes(), (
        f"{name} did not survive unpack->pack. The remote rejects configs whose "
        f"container differs from Logitech's, so this must stay exact."
    )


def test_header_uses_single_crlf(tmp_path):
    """A generated header (no original to reuse) must use CRLF, never `\\r\\r\\n`."""
    src = _present()
    if not src:
        pytest.skip("no config available to build a header from")
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(ROOT / src[0]), str(tmp_path / "t"))
    (tmp_path / "t" / ".ezhex_header").unlink()      # force the generated header
    out = tmp_path / "gen.ezhex"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.pack_standalone(str(tmp_path / "t"), str(out), do_rehash=False)
    header, _, _, _ = ezhex._split(out.read_bytes())
    assert header.count(b"\r\r\n") == 0
    assert header.count(b"\r\n") > 0
