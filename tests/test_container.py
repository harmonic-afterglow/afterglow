"""The `.ezhex` envelope and its ZIP payload.

Every assertion here is a bug that actually shipped. A config whose container differs from
Logitech's is refused by the remote, and the refusal says nothing about why - so the
container is checked byte by byte rather than by "does it unzip".
"""
import contextlib
import io
import zipfile

import pytest
from conftest import entries_of, payload_of

from afterglow import ezhex, payloads
from afterglow.payloads import pk


def test_payload_registry_uses_magic_name_and_reads_old_structural_name():
    """The magic-based name is canonical; the old structural name still resolves.

    This used to assert `payloads.DEFAULT == "pk"`. That constant was the coupling:
    the registry statically imported `pk`, so deleting the module stopped
    `afterglow.ezhex` importing at all, and an unidentifiable header was silently
    opened as a Harmony 900 payload. Types are discovered now, and the alias is
    declared by the module it belongs to rather than listed centrally.
    """
    assert not hasattr(payloads, "DEFAULT"), (
        "a default payload type reintroduces the assumption that one format is special")
    assert payloads.get("ziptree") is payloads.get("pk")
    assert "ziptree" in pk.ALIASES


def test_payload_types_are_discovered_not_listed():
    """Adding or removing a payload module must need no edit to the registry."""
    assert set(payloads.names()) >= {"pk", "blob"}
    for module in payloads.loaded():
        assert all(hasattr(module, attribute) for attribute in payloads.REQUIRED)


def test_payload_is_identified_by_its_own_magic_not_by_a_default(a_config):
    """An unrecognised remote must not fall through to whatever format ships first."""
    assert payloads.identify(payload_of(a_config)) is payloads.get("pk")
    # `blob` accepts anything, so it may only win when nothing else claims the bytes.
    assert payloads.identify(b"GSPM and then some") is payloads.get("blob")


def test_container_layer_names_no_payload_format():
    """`ezhex.py` is the envelope. It must not mention a concrete payload type."""
    import inspect

    source = inspect.getsource(ezhex)
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    for forbidden in ('"pk"', "'pk'", "IrProto", "userconfig"):
        assert forbidden not in code, (
            f"ezhex.py names {forbidden}; the container must delegate that knowledge "
            "to the payload type so a format can be deleted without editing it")


def test_roundtrip_is_byte_identical(configs, unpacked, tmp_path):
    """unpack -> pack must reproduce the file exactly.

    This is the property whose absence let a malformed header ship: the rebuilt config
    unzipped fine, verified fine, and the remote rejected it.
    """
    for index, config in enumerate(configs):
        tree = unpacked(config, f"t{index}")
        out = tmp_path / f"r{index}.ezhex"
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.pack_standalone(str(tree), str(out), do_rehash=False)
        assert out.read_bytes() == config.read_bytes(), f"{config.name} did not survive"


def test_header_line_endings(configs):
    """Real headers use CRLF. A doubled `\\r\\r\\n` is what broke every build once."""
    for config in configs:
        header, _start, _size, _cks = ezhex._split(config.read_bytes())
        assert header.count(b"\r\r\n") == 0, f"{config.name} has doubled line endings"
        assert header.count(b"\r\n") > 0


def test_generated_header_uses_crlf(a_config, unpacked, tmp_path):
    tree = unpacked(a_config)
    (tree / ".ezhex_header").unlink()                 # force the generated header
    out = tmp_path / "generated.ezhex"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.pack_standalone(str(tree), str(out), do_rehash=False)
    header, _s, _z, _c = ezhex._split(out.read_bytes())
    assert header.count(b"\r\r\n") == 0
    assert header.count(b"\r\n") > 0


def test_header_declares_the_remote(a_config):
    from afterglow import remotes
    header, _s, _z, _c = ezhex._split(a_config.read_bytes())
    identity = remotes.identity_of(header)
    assert identity["skin"] is not None
    assert remotes.identify(header).model


def test_split_does_not_assume_a_zip():
    """The envelope must not care what is inside it.

    `_split` used to locate the payload by searching for the ZIP magic, which made the
    'architecture-neutral' container unable to read any non-ZIP config at all.
    """
    header = (b'<?xml version="1.0"?>\r\n<INFORMATION>\r\n'
              b"    <BINARYDATASIZE>4</BINARYDATASIZE>\r\n"
              b"    <CHECKSUM>0</CHECKSUM>\r\n</INFORMATION>\r\n")
    raw = header + b"GSPM"
    _hdr, start, size, _cks = ezhex._split(raw)
    assert raw[start:start + size] == b"GSPM"


def test_split_rejects_a_non_container():
    with pytest.raises(ezhex.NotAnEzhex):
        ezhex._split(b"this is not a configuration")


def test_entry_modes_are_ones_real_configs_use(configs):
    """`mode_for()` must produce a mode some real config actually uses for that path.

    Not a single right answer: real configs disagree on four files
    (`batt_lvls`, `pmiccfg`, `sleepcfg`, `tiltcfg` - one donor ships them 0o775 where
    five ship 0o644) and both variants are configs that run. So the rule is checked
    against the set of observed modes rather than against one of them, which is the
    strongest claim the evidence supports.

    `platformconfig/system_*.dat` are the documented exception, and the reason is that
    a real config is a *dump*. Those files show 0600 there because on a working remote
    `data_srv` created them and owns them, and 0600 is fine when the owner is `nobody`.
    A file *we* ship is extracted by the update manager as root, and 0600 root:root is
    unreadable and unwritable by `data_srv` - which silently reverted every setting to a
    default on the next boot until it was found. Copying that mode off a dump was the
    bug; see `test_settings_file_modes.py` and `mode_for()`.
    """
    def is_settings_file(name):
        return name.startswith("platformconfig/system_") and name.endswith(".dat")

    observed = {}
    for config in configs:
        for info in entries_of(config).infolist():
            observed.setdefault(info.filename, set()).add((info.external_attr >> 16) & 0xFFFF)
    assert observed, "no entries to check"
    assert any(is_settings_file(n) for n in observed), (
        "no settings files in the fixtures - the exception below would pass vacuously")
    for name, modes in observed.items():
        if is_settings_file(name):
            continue
        assert pk.mode_for(name) in modes, (
            f"{name}: rule says {oct(pk.mode_for(name))}, "
            f"real configs use {[oct(m) for m in sorted(modes)]}")


def test_load_bearing_modes_never_vary(configs):
    """The modes that matter are the same everywhere: directories and the install
    scripts. If these ever disagreed, `mode_for` would be guessing at something the
    remote actually depends on."""
    for config in configs:
        for info in entries_of(config).infolist():
            mode = (info.external_attr >> 16) & 0xFFFF
            if info.filename.endswith("/") or info.filename in (".preinstall", ".postinstall"):
                assert mode == pk.mode_for(info.filename), info.filename


def test_install_scripts_are_executable(configs):
    for config in configs:
        for info in entries_of(config).infolist():
            if info.filename in (".preinstall", ".postinstall"):
                assert (info.external_attr >> 16) & 0o111, "install script is not executable"


def test_checksum_matches(configs):
    for config in configs:
        raw = config.read_bytes()
        _hdr, start, size, declared = ezhex._split(raw)
        assert ezhex.checksum(raw[start:start + size]) == declared


def test_local_extras_are_preserved(a_config, unpacked, tmp_path):
    """Info-ZIP local headers carry more than the central directory.

    Losing the difference is silent - the archive is still valid - but the file is 8
    bytes per entry shorter than the original.
    """
    tree = unpacked(a_config)
    out = tmp_path / "again.ezhex"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.pack_standalone(str(tree), str(out), do_rehash=False)
    original = {n: e for _o, n, e, _h, _c in pk._iter_local(payload_of(a_config))}
    rebuilt = {n: e for _o, n, e, _h, _c in pk._iter_local(payload_of(out))}
    assert original == rebuilt


def test_sidecars_never_enter_the_payload(a_config, unpacked, tmp_path):
    tree = unpacked(a_config)
    out = tmp_path / "s.ezhex"
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.pack_standalone(str(tree), str(out), do_rehash=False)
    names = set(entries_of(out).namelist())
    assert not (names & set(pk.SIDECARS if hasattr(pk, "SIDECARS") else ezhex.SIDECARS))


def test_payload_is_a_readable_zip(configs):
    for config in configs:
        assert zipfile.ZipFile(io.BytesIO(payload_of(config))).testzip() is None
