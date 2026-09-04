#!/usr/bin/env python3
"""The `.ezhex` container: an XML header and a configuration payload.

Format reference: docs/harmony_pk/ezhex.md

This module handles the envelope and delegates the payload to the backend named by the
remote's profile (see afterglow.payloads).

    python -m afterglow.ezhex unpack configs/mine/dump.ezhex  out_dir
    python -m afterglow.ezhex pack   src_dir     out.ezhex
    python -m afterglow.ezhex verify out.ezhex
"""
import argparse
import os
import re

from . import payloads

CLOSE = b"</INFORMATION>"

class NotAnEzhex(ValueError):
    """The file has no <INFORMATION> header, so it is not a configuration container."""


def _split(raw):
    """(header, payload offset, declared payload size, declared checksum).

    The payload starts immediately after `</INFORMATION>` and its line ending. This used
    to search for the ZIP local-file magic instead, which quietly made the container
    ZIP-only: a Harmony One config, whose payload begins ``GSPM``, was reported as "not
    an ezhex". The envelope must not care what is inside it.
    """
    end = raw.find(CLOSE)
    if end < 0:
        raise NotAnEzhex("no <INFORMATION> header: not an ezhex")
    start = end + len(CLOSE)
    while start < len(raw) and raw[start] in (13, 10):     # skip the header's line ending
        start += 1
    size = re.search(rb"<BINARYDATASIZE>(\d+)", raw[:start])
    cks = re.search(rb"<CHECKSUM>(\d+)", raw[:start])
    return (raw[:start], start,
            int(size.group(1)) if size else len(raw) - start,
            int(cks.group(1)) if cks else None)

def checksum(payload: bytes) -> int:
    c = 0x69
    for b in payload:
        c ^= b
    return c


def backend_for(header: bytes, payload: bytes | None = None):
    """The payload type this config needs, from the remote it declares.

    When the header names no remote we ask the *bytes* what they are rather than
    assuming one architecture. Defaulting used to mean an unrecognised config was
    silently opened as a Harmony 900 payload.
    """
    from . import remotes
    try:
        return payloads.get(remotes.identify(header).payload)
    except remotes.UnknownRemote:
        if payload is None:
            raise
        return payloads.identify(payload)


def profile_of(path):
    """The remote profile a config on disk is for."""
    from . import remotes
    with open(path, "rb") as handle:
        return remotes.identify(_split(handle.read())[0])


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def _header_beside(path):
    """The `.ezhex_header` written next to an unpacked tree, or empty if there is none."""
    return _read_bytes(path) if os.path.isfile(path) else b""


def unpack(ezhex, out_dir):
    raw = _read_bytes(ezhex)
    header, pk, bds, cks = _split(raw)
    payload = raw[pk:pk + bds]
    calc = checksum(payload)
    print(f"payload {len(payload)} bytes | declared checksum {cks} | computed {calc} | "
          + ("OK" if calc == cks else "MISMATCH"))
    count = backend_for(header, payload).unpack(payload, out_dir)
    # Keep the original header verbatim: it identifies the remote and carries fields we
    # must not invent. pack_standalone reuses it and only refreshes size and checksum.
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, ".ezhex_header"), "wb") as handle:
        handle.write(header)
    print(f"extracted {count} entries -> {out_dir}")



_EZHEX_HEADER = (
    '<?xml version="1.0"?>\r\n'
    '<INFORMATION>\r\n'
    '    <USERMESSAGES>\r\n'
    '        <USERMESSAGE>\r\n'
    '            <VERSIONS>\r\n'
    '                <VERSION>\r\n'
    '                    <PROTOCOL>{arch}</PROTOCOL>\r\n'
    '                    <SKIN>{skin}</SKIN>\r\n'
    '                    <FLASH>{flash}</FLASH>\r\n'
    '                    <BOARD>{board}</BOARD>\r\n'
    '                    <SOFTWARETYPE>{software_type}</SOFTWARETYPE>\r\n'
    '                </VERSION>\r\n'
    '            </VERSIONS>\r\n'
    '            <TYPE>DoNothing</TYPE>\r\n'
    '            <ABORTPROCESSING>True</ABORTPROCESSING>\r\n'
    '        </USERMESSAGE>\r\n'
    '        <USERMESSAGE>\r\n'
    '            <VERSIONS>\r\n'
    '                <VERSION></VERSION>\r\n'
    '            </VERSIONS>\r\n'
    '            <TYPE>Warning</TYPE>\r\n'
    '            <TEXT>This configuration file is not compatible with your Harmony Remote.</TEXT>\r\n'
    '        </USERMESSAGE>\r\n'
    '        <USERMESSAGE>\r\n'
    '            <VERSIONS>\r\n'
    '                <VERSION></VERSION>\r\n'
    '            </VERSIONS>\r\n'
    '            <TYPE>Abort</TYPE>\r\n'
    '        </USERMESSAGE>\r\n'
    '    </USERMESSAGES>\r\n'
    '    <INTENDEDVERSION>\r\n'
    '        <PROTOCOL>{arch}</PROTOCOL>\r\n'
    '        <SKIN>{skin}</SKIN>\r\n'
    '        <FLASH>{flash}</FLASH>\r\n'
    '        <BOARD>{board}</BOARD>\r\n'
    '        <SOFTWARETYPE>{software_type}</SOFTWARETYPE>\r\n'
    '    </INTENDEDVERSION>\r\n'
    '    <TRANSFERTYPE>Winsock</TRANSFERTYPE>\r\n'
    '    <CONFIGURATION>\r\n'
    '        <CONFIGOPTION>\r\n'
    '            <KEY>InstructionNoHarmony</KEY>\r\n'
    '            <TITLE>No Harmony Detected</TITLE>\r\n'
    '            <IMAGE>0</IMAGE>\r\n'
    '            <VALUE>Plug the USB cable into your Harmony, or press any button on your Harmony to wake it up.</VALUE>\r\n'
    '        </CONFIGOPTION>\r\n'
    '    </CONFIGURATION>\r\n'
    '    <POSTOPTIONS>\r\n'
    '        <SERVER>members.harmonyremote.com</SERVER>\r\n'
    '        <PATH>EasyZapper/New/ProcUpdate/Receive_Zaps.asp</PATH>\r\n'
    '        <TIMEOUT>60000</TIMEOUT>\r\n'
    '        <HEADERS>\r\n'
    '            <HEADER>\r\n'
    '                <KEY>Cookie</KEY>\r\n'
    '                <VALUE>Monster</VALUE>\r\n'
    '            </HEADER>\r\n'
    '        </HEADERS>\r\n'
    '        <PARAMETERS>\r\n'
    '            <PARAMETER>\r\n'
    '                <KEY>UserId</KEY>\r\n'
    '                <VALUE>0</VALUE>\r\n'
    '            </PARAMETER>\r\n'
    '        </PARAMETERS>\r\n'
    '    </POSTOPTIONS>\r\n'
    '    <TIPPOSTOPTIONS>\r\n'
    '        <SERVER>members.harmonyremote.com</SERVER>\r\n'
    '        <TIMEOUT>60000</TIMEOUT>\r\n'
    '        <HEADERS>\r\n'
    '            <HEADER>\r\n'
    '                <KEY>Cookie</KEY>\r\n'
    '                <VALUE>Monster</VALUE>\r\n'
    '            </HEADER>\r\n'
    '        </HEADERS>\r\n'
    '    </TIPPOSTOPTIONS>\r\n'
    '    <TIMEPOSTOPTIONS>\r\n'
    '        <SERVER>members.harmonyremote.com</SERVER>\r\n'
    '        <PATH>EasyZapper/GetTime.asp</PATH>\r\n'
    '        <TIMEOUT>60000</TIMEOUT>\r\n'
    '    </TIMEPOSTOPTIONS>\r\n'
    '    <COMPLETEPOSTOPTIONS>\r\n'
    '        <SERVER>members.harmonyremote.com</SERVER>\r\n'
    '        <PATH>EasyZapper/New/ProcUpdate/Receive_Complete.asp</PATH>\r\n'
    '        <TIMEOUT>60000</TIMEOUT>\r\n'
    '        <HEADERS>\r\n'
    '            <HEADER>\r\n'
    '                <KEY>Cookie</KEY>\r\n'
    '                <VALUE>Monster</VALUE>\r\n'
    '            </HEADER>\r\n'
    '        </HEADERS>\r\n'
    '        <PARAMETERS>\r\n'
    '            <PARAMETER>\r\n'
    '                <KEY>UserId</KEY>\r\n'
    '                <VALUE>0</VALUE>\r\n'
    '            </PARAMETER>\r\n'
    '        </PARAMETERS>\r\n'
    '    </COMPLETEPOSTOPTIONS>\r\n'
    '    <BINARYDATASIZE>{bds}</BINARYDATASIZE>\r\n'
    '    <CHECKSUM>{cks}</CHECKSUM>\r\n'
    '</INFORMATION>\r\n'
)


def header_for_profile(profile, bds=0, cks=0):
    """Generate a header that declares `profile`'s remote."""
    return _EZHEX_HEADER.format(bds=bds, cks=cks, arch=profile.arch, skin=profile.skin,
                                flash=profile.flash, board=profile.board,
                                software_type=profile.software_type or 0).encode("utf-8")


def _header_for(src_dir, payload, profile=None):
    """The header for this config.

    A tree unpacked from an existing config keeps that config's header verbatim, so
    repacking is byte-exact. A config built from scratch gets one generated from the
    remote profile - the identity comes from the profile, not from someone else's file.
    """
    path = os.path.join(src_dir, ".ezhex_header")
    if os.path.isfile(path) and profile is None:
        header = _read_bytes(path)
    else:
        if profile is None:
            from . import remotes
            profile = remotes.get("harmony-900")
        header = header_for_profile(profile)
    header = re.sub(rb"<BINARYDATASIZE>\d+</BINARYDATASIZE>",
                    ("<BINARYDATASIZE>%d</BINARYDATASIZE>" % len(payload)).encode(), header)
    return re.sub(rb"<CHECKSUM>\d+</CHECKSUM>",
                  ("<CHECKSUM>%d</CHECKSUM>" % checksum(payload)).encode(), header)


def pack_standalone(src_dir, out_path, do_rehash=True, profile=None):
    """Pack a directory into an ezhex without needing a template."""
    header_path = os.path.join(src_dir, ".ezhex_header")
    header = _header_beside(header_path)
    # No header means this tree was not unpacked from a config, so the tree itself has
    # to say what it is. `ezhex.py` must not guess a format, and must not know which
    # files any format keeps - both are the payload type's business.
    backend = backend_for(header) if header else payloads.identify_tree(src_dir)
    if do_rehash and hasattr(backend, "rehash"):
        backend.rehash(src_dir)
    payload = backend.build(src_dir)
    header = _header_for(src_dir, payload, profile)
    with open(out_path, "wb") as handle:
        handle.write(header)
        handle.write(payload)
    print(f"wrote {out_path}: header {len(header)} + payload {len(payload)} bytes | "
          f"checksum {checksum(payload)}")


def verify(ezhex):
    raw = _read_bytes(ezhex)
    _, pk, bds, cks = _split(raw)
    payload = raw[pk:pk + bds]
    calc = checksum(payload)
    trailing = len(raw) - (pk + bds)
    print(f"BINARYDATASIZE={bds}  actual_payload={len(raw)-pk}  trailing_bytes={trailing}")
    print(f"CHECKSUM declared={cks}  computed={calc}  -> {'OK' if calc==cks else 'MISMATCH'}")
    header = raw[:pk]
    try:
        from . import remotes
        print("remote:", remotes.describe(remotes.identify(header)).splitlines()[0])
    except Exception as exc:
        print("remote: unidentified -", exc)
    print("payload:", backend_for(header, payload).describe(payload))


def rehash(work_dir):
    """Re-sync whatever internal digests this tree's payload type keeps.

    Which digests those are is the payload type's knowledge, not this module's; a tree
    whose type has none, or has nothing to sync, is a no-op rather than an error.
    """
    header_path = os.path.join(work_dir, ".ezhex_header")
    header = _header_beside(header_path)
    backend = backend_for(header) if header else payloads.identify_tree(work_dir)
    return backend.rehash(work_dir) if hasattr(backend, "rehash") else None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read and write .ezhex configuration files.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("unpack"); up.add_argument("ezhex"); up.add_argument("out_dir")
    pk = sub.add_parser("pack"); pk.add_argument("src_dir"); pk.add_argument("out")
    vf = sub.add_parser("verify"); vf.add_argument("ezhex")
    args = parser.parse_args(argv)
    if args.cmd == "unpack":
        unpack(args.ezhex, args.out_dir)
    elif args.cmd == "pack":
        pack_standalone(args.src_dir, args.out)
    else:
        verify(args.ezhex)


if __name__ == "__main__":
    main()
