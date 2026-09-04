"""Opaque non-PK payloads, including Harmony One's ``GSPM`` configuration.

The Harmony 900 payload starts with ``PK\x03\x04`` and is a ZIP filesystem archive.
Harmony One starts with ``GSPM`` and contains a different indexed configuration tree.
Afterglow can read that payload, verify it and re-wrap it unchanged, which is enough to
inspect a remote and keep a working backup - but not to author one: its master index and
sections of screens, objects and key bindings are a separate format that this project has
not reverse-engineered.

RE-HARMONY (github.com/Unkn0wn-dx/RE-HARMONY) does exactly that work for the Harmony One.
If you want to author for one today, use that; this backend exists so Afterglow identifies
the remote honestly and refuses rather than writing something plausible and wrong.
"""
import os

NAME = "blob"
PAYLOAD_FILE = "payload.bin"

# This type accepts any bytes by design, so it must never win identification against a
# format that actually recognises them. The registry consults it only when nothing else
# claims the payload.
LAST_RESORT = True


def claims(src_dir: str) -> bool:
    return os.path.isfile(os.path.join(src_dir, PAYLOAD_FILE))

# Four-byte tags seen at the start of a configuration blob, by architecture - read off
# real configs, one remote per entry (Harmony 688/670, 880/885, 890, One, 650).
MAGIC = {7: b"BMBM", 8: b"TPTP", 10: b"TPTP", 12: b"GSPM", 14: b"GSPM"}


class NotAuthorable(NotImplementedError):
    """The blob's internal structure is not implemented; it can be copied, not composed."""


def unpack(payload: bytes, out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, PAYLOAD_FILE), "wb") as handle:
        handle.write(payload)
    return 1


def build(src_dir: str) -> bytes:
    path = os.path.join(src_dir, PAYLOAD_FILE)
    if not os.path.isfile(path):
        raise NotAuthorable(
            f"{src_dir} has no {PAYLOAD_FILE}: a blob payload can only be rebuilt from one "
            f"read off a remote. Authoring this payload format is not implemented."
        )
    with open(path, "rb") as handle:
        return handle.read()


def describe(payload: bytes) -> str:
    tag = payload[:4]
    known = next((f"arch {a}" for a, m in MAGIC.items() if m == tag), "unrecognised")
    return f"raw blob, {len(payload)} bytes, magic {tag!r} ({known})"
