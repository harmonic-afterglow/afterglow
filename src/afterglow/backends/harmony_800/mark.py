"""The Afterglow mark: what makes a Harmony 800 configuration one this backend can read.

Only configurations Afterglow builds are read back. Logitech's own 800 configurations are
not supported - their screens and objects are laid out by a builder nobody can consult -
so a configuration has to say it is ours before anything is read from it. Every image this
backend builds carries, at the end of its body, the project it was built from, compressed,
and a trailer naming it: reading one back gives exactly that project, and an image without
a sound mark is refused rather than guessed at.

The firmware reaches everything through the header's section pointers, so the mark is
never read on the remote; it lies inside the checksummed body, ending where the checksum
starts, so the end vector alone finds it.

Pure standard library.

Format reference: docs/harmony_800/gsgd.md
"""

from __future__ import annotations

import json
import struct
import zlib

from . import gsgd

MAGIC = b"AFTERGLOW-800\x00\x00\x00"
END = b"AGLW"
VERSION = 1
TRAILER = struct.Struct("<16sHHII4s")      # magic, version, reserved, length, crc32, end
# Settings that only say where a build was written on the machine that built it.
LOCAL_SETTINGS = ("out_file",)


class NotAfterglow(ValueError):
    """A configuration this backend did not build, or whose mark is damaged."""


def project_bytes(project: dict) -> bytes:
    """The project as the mark carries it: JSON, compact and in a fixed key order, without
    the settings that only concern the machine that built it, compressed."""
    settings = {key: value for key, value in (project.get("settings") or {}).items()
                if key not in LOCAL_SETTINGS}
    carried = {**project, "settings": settings} if "settings" in project else dict(project)
    text = json.dumps(carried, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return zlib.compress(text.encode("utf-8"), 9)


def append(body: bytearray, project: dict) -> bytearray:
    """``body`` with the mark after it - the project, then the trailer - padded so that the
    whole stays of even length and the trailer ends where the checksum will start."""
    data = project_bytes(project)
    if (len(body) + len(data)) % 2:
        body += b"\x00"
    body += data
    body += TRAILER.pack(MAGIC, VERSION, 0, len(data), zlib.crc32(data), END)
    return body


def read(payload: bytes) -> dict:
    """The mark of an image: ``{"version", "project"}``. Raises NotAfterglow, naming why,
    for an image without one or with one that does not hold together."""
    try:
        image = gsgd.trimmed(payload)
        close = struct.unpack_from("<I", image, 4)[0] - gsgd.base_of(image)
    except (ValueError, struct.error) as error:
        raise NotAfterglow(f"not a Harmony 800 configuration: {error}") from error
    end = close - 2                                  # the checksum's two bytes
    start = end - TRAILER.size
    if start < gsgd.HEADER_SIZE:
        raise NotAfterglow("too short to carry an Afterglow mark")
    magic, version, _reserved, length, crc, closing = TRAILER.unpack_from(image, start)
    if magic != MAGIC or closing != END:
        raise NotAfterglow("this configuration was not made by Afterglow; the Harmony 800's "
                           "own configurations from Logitech are not supported")
    if version > VERSION:
        raise NotAfterglow(f"made by a newer Afterglow (mark version {version}); update to "
                           "read it")
    data = image[start - length:start]
    if length > start - gsgd.HEADER_SIZE or zlib.crc32(data) != crc:
        raise NotAfterglow("the Afterglow mark is damaged: its project does not check out")
    try:
        project = json.loads(zlib.decompress(data).decode("utf-8"))
    except (zlib.error, UnicodeDecodeError, ValueError) as error:
        raise NotAfterglow(f"the Afterglow mark is damaged: {error}") from error
    return {"version": version, "project": project}
