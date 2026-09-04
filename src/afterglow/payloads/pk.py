"""The ``PK\x03\x04`` ZIP payload verified on the Harmony 900.

Format reference: docs/harmony_pk/ezhex.md and docs/harmony_pk/configuration.md

The remote extracts these entries onto its filesystem, so it is not enough for the
payload to merely *be* a valid ZIP: entry order, per-entry Unix modes, stored-vs-deflated
choice and the Info-ZIP local extra fields all have to match. `unpack()` records that in
sidecar files so `build()` can reproduce it byte for byte.

This module name describes its storage adapter, not a Harmony architecture family.
"""
import io
import json
import os
import re
import struct
import zipfile
import zlib


SIDECARS = {".ezhex_order", ".ezhex_meta.json", ".ezhex_header"}  # bookkeeping, never zip entries

def _iter_local(payload):
    """Yield (offset, name, extra, header_len, comp_size) for each local file header."""
    off = 0
    while off + 30 <= len(payload) and payload[off:off + 4] == b"PK\x03\x04":
        flag, = struct.unpack("<H", payload[off + 6:off + 8])
        csize, = struct.unpack("<I", payload[off + 18:off + 22])
        nlen, elen = struct.unpack("<HH", payload[off + 26:off + 30])
        name = payload[off + 30:off + 30 + nlen].decode("utf-8", "replace")
        extra = payload[off + 30 + nlen:off + 30 + nlen + elen]
        total = 30 + nlen + elen + csize + (16 if flag & 0x08 else 0)
        yield off, name, extra, 30 + nlen + elen, csize
        off += total

def _patch_local_extras(payload, local_extras):
    """Rewrite each local header's extra field to `local_extras[name]`.

    Genuine Logitech payloads are Info-ZIP-made: the LOCAL header carries a longer
    extra than the central directory (UT with mtime+atime, ux with uid/gid), while the
    central record keeps the short form. Python's zipfile writes one `extra` to both, so
    a rebuilt payload is 8 bytes/entry short of the original. Patch the local headers
    back and fix up the central directory offsets so the archive stays valid.
    """
    if not local_extras:
        return payload
    out, remap, pos = bytearray(), {}, 0
    for off, name, extra, hlen, csize in _iter_local(payload):
        new_extra = local_extras.get(name, extra)
        remap[off] = len(out)
        nlen, = struct.unpack("<H", payload[off + 26:off + 28])
        head = bytearray(payload[off:off + 30 + nlen])
        struct.pack_into("<H", head, 26 + 2, len(new_extra))     # extra-field length
        out += head + new_extra + payload[off + hlen:off + hlen + csize]
        pos = off + hlen + csize
    tail = payload[pos:]                                          # central dir + EOCD
    cd_start = len(out)
    i = 0
    while i + 46 <= len(tail) and tail[i:i + 4] == b"PK\x01\x02":
        nlen, elen, clen = struct.unpack("<HHH", tail[i + 28:i + 34])
        rec = bytearray(tail[i:i + 46 + nlen + elen + clen])
        old_off, = struct.unpack("<I", rec[42:46])
        struct.pack_into("<I", rec, 42, remap.get(old_off, old_off))
        out += rec
        i += 46 + nlen + elen + clen
    eocd = bytearray(tail[i:])
    if eocd[:4] == b"PK\x05\x06":
        struct.pack_into("<I", eocd, 12, cd_start and len(out) - cd_start)  # cd size
        struct.pack_into("<I", eocd, 16, cd_start)                          # cd offset
    return bytes(out + eocd)




def rehash(work_dir):
    """Recompute IrProto.bin's [CRC32][len] header from its data, and sync the
    ProtocolCacheHash (+ <Protocols><Hash>) EVERYWHERE it is stored. The hash lives
    in 3 places: the IrProto.bin header, UserConfiguration.xml AND ActionLists.xml.
    Editing the block changes the CRC; if any copy is left stale the remote refuses
    to boot the main software (this is what froze the earlier Samsung-block edit --
    normal NEC builds never hit it because they reuse the block byte-for-byte, so the
    CRC never changes). Call after editing/splicing IrProto.bin. Returns the hash.

    Returns None when this tree has no IrProto.bin. The caller is the container layer,
    which must not know that this format keeps its protocol table in
    `userconfig/IrProto.bin` - deciding whether there is anything to rehash is this
    module's job, not `ezhex.py`'s."""
    ip_path = os.path.join(work_dir, "userconfig", "IrProto.bin")
    if not os.path.isfile(ip_path):
        return None
    with open(ip_path, "rb") as handle:
        ip = handle.read()
    data = ip[8:]                                   # everything after the 8-byte header is protocol data
    crc = zlib.crc32(data) & 0xFFFFFFFF
    with open(ip_path, "wb") as f:
        f.write(struct.pack("<I", crc))             # CRC32, little-endian
        f.write(struct.pack("<I", len(data)))       # data length, little-endian
        f.write(data)
    hs = "0x%08X" % crc
    for name in ("UserConfiguration.xml", "ActionLists.xml"):   # every XML copy of the hash
        p = os.path.join(work_dir, "userconfig", name)
        if not os.path.isfile(p):
            continue
        with open(p, "r", encoding="utf-8") as handle:
            x = handle.read()
        x = re.sub(r'(ProtocolCacheHash">)0x[0-9A-Fa-f]+(<)', r"\g<1>" + hs + r"\g<2>", x)
        x = re.sub(r'(<Hash>)0x[0-9A-Fa-f]+(</Hash>)', r"\g<1>" + hs + r"\g<2>", x)
        with open(p, "w", encoding="utf-8") as handle:
            handle.write(x)
    print(f"rehash: IrProto data {len(data)} B -> CRC32 {hs} (synced to UserConfiguration.xml + ActionLists.xml)")
    return hs

# The permissions the remote expects, as a function of where a file sits. These become
# real filesystem modes when the remote unpacks the config, which is why they are not
# cosmetic: `.preinstall`/`.postinstall` have to be executable or the config does not
# install. Derived by observation and checked against every entry of three genuine
# configs (168/168) -- so a config can be built correctly from nothing, without copying
# another config to crib its metadata from.
def mode_for(path):
    if path == "META-INF/":
        return 0o40777
    if path.endswith("/"):
        return 0o40775
    if path in (".preinstall", ".postinstall"):
        return 0o100775                              # the remote executes these
    if path in (".version", "META-INF/MANIFEST.MF"):
        return 0o100666
    if path.startswith("userconfig/"):
        return 0o100775
    if path.startswith("platformconfig/"):
        name = path.split("/", 1)[1]
        if name.startswith("system_"):
            # World-writable, and it has to be. `data_srv` holds every setting and
            # runs as `nobody`; the remote's update manager extracts what is shipped as
            # root. At 0600 root:root the service can neither read nor write these, so
            # every save fails with EACCES and the remote falls back to compiled-in
            # defaults at boot, appearing to forget both flashed and on-device settings.
            #
            # A dump shows 0600, which is correct there only because `data_srv` created
            # those files and owns them. Do not copy the mode from a dump.
            return 0o100666
        if name in ("tiltcfg.dat", "sleepcfg.dat", "pmiccfg.dat", "batt_lvls.dat"):
            return 0o100644
        return 0o100664
    return 0o100664


def _build_zip_standalone(src_dir):
    """Build a ZIP payload from src_dir without needing a template.
    Sets proper Unix metadata so .preinstall/.postinstall are executable.
    If the tree came from unpack(), .ezhex_meta.json restores each entry's original
    mode/compression/timestamp exactly (see unpack) -- required for the remote to
    accept the config; the heuristic below is only for from-scratch trees."""
    buf = io.BytesIO()
    # Read ordering file if present
    order_path = os.path.join(src_dir, ".ezhex_order")
    if os.path.isfile(order_path):
        with open(order_path, "r", encoding="utf-8") as f:
            order = [line.strip() for line in f if line.strip()]
    else:
        order = None

    import json
    meta_path = os.path.join(src_dir, ".ezhex_meta.json")
    meta = {}
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = {m["name"]: m for m in json.load(f)}
        if order is None:
            order = list(meta)

    def _make_zinfo(rel, is_dir=False):
        m = meta.get(rel)
        if m:                                   # reproduce the original entry exactly
            zi = zipfile.ZipInfo(filename=rel, date_time=tuple(m["date_time"]))
            zi.compress_type = m["compress_type"]
            zi.create_system = m["create_system"]
            zi.create_version = m["create_version"]
            zi.extract_version = m["extract_version"]
            zi.external_attr = m["external_attr"]
            zi.internal_attr = m["internal_attr"]
            zi.flag_bits = m["flag_bits"]
            zi.extra = bytes.fromhex(m["extra"])
            zi.comment = bytes.fromhex(m.get("comment", ""))
            return zi
        zi = zipfile.ZipInfo(filename=rel, date_time=(2020, 2, 15, 6, 42, 14))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.create_system = 3  # Unix
        zi.create_version = 20
        zi.extract_version = 20
        zi.external_attr = mode_for(rel) << 16
        return zi

    on_disk = []  # (rel_path, is_dir)
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        for d in sorted(dirs):
            rel = os.path.relpath(os.path.join(root, d), src_dir).replace("\\", "/") + "/"
            on_disk.append((rel, True))
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(root, fn), src_dir).replace("\\", "/")
            if rel in SIDECARS:
                continue
            on_disk.append((rel, False))

    if order:
        # The recorded order is authoritative (it *is* the original entry sequence,
        # directory entries included). Emit it first, dropping anything since deleted,
        # then append files added to the tree afterwards.
        present = {rel for rel, _ in on_disk}
        entries = [(rel, rel.endswith("/")) for rel in order
                   if rel.endswith("/") or rel in present]
        listed = set(order)
        entries += [(rel, d) for rel, d in on_disk if rel not in listed]
    else:
        entries = on_disk

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, is_dir in entries:
            zi = _make_zinfo(rel, is_dir)
            if is_dir:
                z.writestr(zi, b"")
            else:
                full = os.path.join(src_dir, rel.replace("/", os.sep))
                with open(full, "rb") as handle:
                    z.writestr(zi, handle.read())
    # Restore the original (longer) Info-ZIP local-header extras -- see _patch_local_extras.
    return _patch_local_extras(buf.getvalue(),
                               {n: bytes.fromhex(m["extra_local"]) for n, m in meta.items()
                                if m.get("extra_local")})


# the payload-type interface
NAME = "pk"
ALIASES = ("ziptree",)   # the former structural name; private files outlive renames
MAGIC = b"PK\x03\x04"    # what this type is named for


def sniff(payload: bytes) -> bool:
    """Identify by the payload's own magic, so no caller has to assume a format."""
    return payload[:len(MAGIC)] == MAGIC


def claims(src_dir: str) -> bool:
    """An unpacked PK tree is the one carrying this type's rebuild sidecars."""
    return any(os.path.isfile(os.path.join(src_dir, sidecar)) for sidecar in SIDECARS)


def unpack(payload: bytes, out_dir: str) -> int:
    """Payload -> a directory tree, plus the sidecars needed to rebuild it exactly.
    Returns the number of entries."""
    os.makedirs(out_dir, exist_ok=True)
    archive = zipfile.ZipFile(io.BytesIO(payload))
    archive.extractall(out_dir)
    with open(os.path.join(out_dir, ".ezhex_order"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(i.filename for i in archive.infolist()))
    local = {name: extra for _o, name, extra, _h, _c in _iter_local(payload)}
    meta = [{"name": i.filename, "date_time": list(i.date_time),
             "compress_type": i.compress_type, "create_system": i.create_system,
             "create_version": i.create_version, "extract_version": i.extract_version,
             "external_attr": i.external_attr, "internal_attr": i.internal_attr,
             "flag_bits": i.flag_bits, "extra": i.extra.hex(), "comment": i.comment.hex(),
             "extra_local": local.get(i.filename, i.extra).hex()}
            for i in archive.infolist()]
    with open(os.path.join(out_dir, ".ezhex_meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=1)
    return len(archive.infolist())


def build(src_dir: str) -> bytes:
    """A directory tree -> the payload bytes.

    Entry metadata comes from the tree's own `.ezhex_meta.json` when it was unpacked from
    a config (so repacking is byte-exact), and otherwise from `mode_for()`. There is
    deliberately no way to take it from another config: that is how a foreign remote's
    state used to travel into a freshly built one.
    """
    return _build_zip_standalone(src_dir)


def describe(payload: bytes) -> str:
    try:
        return f"ZIP tree, {len(zipfile.ZipFile(io.BytesIO(payload)).infolist())} entries"
    except zipfile.BadZipFile:
        return "not a readable ZIP"
