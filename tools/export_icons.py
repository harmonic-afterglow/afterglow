#!/usr/bin/env python3
"""Pull the remote's own device/activity icons out of its firmware.

    python3 tools/export_icons.py path/to/61.hfw [--out icons]

The remote draws its interface in Flash. `app-main.swf`, inside the firmware image,
exports one movie clip per device type (`DEVICE_Television_MC`) and per activity type
(`00_SHARED_VirtualDvd_MC`), plus 87 button glyphs (`CUSTOM_myTV`) - which is where the
`<Icon>` names in a configuration come from. That list is the *authoritative* vocabulary:
what the remote actually supports, rather than what a name suggests it might.

This walks the firmware zip → region → SWF → tags, resolves each named clip to the
bitmaps it draws, and writes them out with their real names.

**The artwork is Logitech's.** Exporting it locally to see what an icon looks like, or to
redraw your own version, is the point; the output directory is not for redistribution.
"""
from __future__ import annotations

import argparse
import io
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DEFINE_BITS = 6
DEFINE_BITS_JPEG2 = 21
DEFINE_BITS_JPEG3 = 35
DEFINE_BITS_LOSSLESS = 20
DEFINE_BITS_LOSSLESS2 = 36
DEFINE_SHAPE = {2, 22, 32, 83}
DEFINE_SPRITE = 39
EXPORT_ASSETS = {56, 76}
PLACE_OBJECT = 4
PLACE_OBJECT2 = 26
PLACE_OBJECT3 = 70


def iter_tags(body: bytes, start: int = 0, end: int | None = None):
    """(code, data) for each tag. `start` skips the movie header when reading top level."""
    off = start
    end = len(body) if end is None else end
    while off + 2 <= end:
        code_len, = struct.unpack_from("<H", body, off)
        off += 2
        code, length = code_len >> 6, code_len & 0x3F
        if length == 0x3F:
            length, = struct.unpack_from("<I", body, off)
            off += 4
        yield code, body[off:off + length]
        off += length
        if code == 0:
            break


def movie_body(swf: bytes) -> bytes:
    """The tag stream, decompressed and with the frame header skipped."""
    sig = swf[:3]
    body = zlib.decompress(swf[8:]) if sig == b"CWS" else swf[8:]
    nbits = body[0] >> 3
    off = ((5 + nbits * 4) + 7) // 8 + 4          # RECT + frame rate + frame count
    return body[off:]


def collect(body: bytes):
    """(exports, images, sprites, shapes) keyed by character id."""
    exports, images, sprites, shapes = {}, {}, {}, {}
    for code, data in iter_tags(body):
        if code in EXPORT_ASSETS:
            count, = struct.unpack_from("<H", data, 0)
            pos = 2
            for _ in range(count):
                cid, = struct.unpack_from("<H", data, pos)
                pos += 2
                end = data.index(b"\0", pos)
                exports[cid] = data[pos:end].decode("latin1")
                pos = end + 1
        elif code in (DEFINE_BITS, DEFINE_BITS_JPEG2, DEFINE_BITS_JPEG3,
                      DEFINE_BITS_LOSSLESS, DEFINE_BITS_LOSSLESS2):
            cid, = struct.unpack_from("<H", data, 0)
            images[cid] = (code, data)
        elif code == DEFINE_SPRITE:
            cid, = struct.unpack_from("<H", data, 0)
            sprites[cid] = data[4:]
        elif code in DEFINE_SHAPE:
            cid, = struct.unpack_from("<H", data, 0)
            shapes[cid] = (code, data)
    return exports, images, sprites, shapes


def placed_ids(sprite_body: bytes):
    """Character ids a sprite places on stage."""
    out = []
    for code, data in iter_tags(sprite_body):
        if code == PLACE_OBJECT:
            if len(data) >= 2:
                out.append(struct.unpack_from("<H", data, 0)[0])
        elif code in (PLACE_OBJECT2, PLACE_OBJECT3):
            flags = data[0]
            pos = 3 if code == PLACE_OBJECT2 else 4
            if flags & 0x02 and pos + 2 <= len(data):      # PlaceFlagHasCharacter
                out.append(struct.unpack_from("<H", data, pos)[0])
    return out


def _skip_rect(data: bytes, pos: int) -> int:
    """A RECT is 5 bits of field width, then four fields of that width, byte-aligned."""
    nbits = data[pos] >> 3
    return pos + ((5 + 4 * nbits) + 7) // 8


def _skip_matrix(data: bytes, pos: int) -> int:
    """MATRIX: optional scale, optional rotate, then translate - all bit-packed."""
    bit = pos * 8

    def take(n):
        nonlocal bit
        value = 0
        for _ in range(n):
            value = (value << 1) | ((data[bit >> 3] >> (7 - (bit & 7))) & 1)
            bit += 1
        return value

    if take(1):
        take(2 * take(5))
    if take(1):
        take(2 * take(5))
    take(2 * take(5))
    return (bit + 7) // 8


def bitmap_ids_in_shape(entry) -> list:
    """Bitmap ids a shape paints with, read from its fill-style array.

    The array sits immediately after the shape's bounds, so the bounds must be skipped
    exactly. An earlier version guessed their length and therefore found nothing.
    """
    code, data = entry
    out = []
    pos = _skip_rect(data, 2)                      # after ShapeId, skip ShapeBounds
    if code == 83:                                 # DefineShape4 adds EdgeBounds + flags
        pos = _skip_rect(data, pos) + 1
    if pos >= len(data):
        return out
    count = data[pos]
    pos += 1
    if count == 0xFF and code != 2:
        count, = struct.unpack_from("<H", data, pos)
        pos += 2
    rgba = code in (32, 83)
    for _ in range(count):
        if pos >= len(data):
            break
        style = data[pos]
        pos += 1
        if style == 0x00:                          # solid colour
            pos += 4 if rgba else 3
        elif style in (0x10, 0x12, 0x13):          # gradients
            pos = _skip_matrix(data, pos)
            if style == 0x13:
                pos += 2
            records = data[pos] & 0x0F
            pos += 1 + records * (1 + (4 if rgba else 3))
        elif style in (0x40, 0x41, 0x42, 0x43):    # bitmap fills
            if pos + 2 > len(data):
                break
            out.append(struct.unpack_from("<H", data, pos)[0])
            pos = _skip_matrix(data, pos + 2)
        else:
            break
    return out


def resolve_images(cid, images, sprites, shapes, seen=None):
    """Every bitmap a character draws, following sprites and shapes."""
    seen = seen if seen is not None else set()
    if cid in seen:
        return []
    seen.add(cid)
    if cid in images:
        return [cid]
    found = []
    if cid in sprites:
        for child in placed_ids(sprites[cid]):
            found += resolve_images(child, images, sprites, shapes, seen)
    elif cid in shapes:
        for bid in bitmap_ids_in_shape(shapes[cid]):
            if bid in images:
                found.append(bid)
    return found


def unpremultiply(img):
    """Undo premultiplied alpha.

    The colour in these bitmaps is already multiplied by the alpha - a pixel that is
    10% opaque holds 10% of its colour, which is why fully transparent pixels are black.
    Compositing that as if it were straight alpha multiplies a second time, and the soft
    drop shadow every icon carries comes out roughly twice as dark: the "double shadow".
    """
    from PIL import Image
    pixels = img.load()
    width, height = img.size
    out = Image.new("RGBA", img.size)
    target = out.load()
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                target[x, y] = (0, 0, 0, 0)
            else:
                target[x, y] = (min(255, r * 255 // a), min(255, g * 255 // a),
                                min(255, b * 255 // a), a)
    return out


def trim(img):
    """Crop away fully transparent margins.

    The sprites sit on a fixed canvas with a lot of empty space (a television fills about
    half of its 90x90 box, all of it top-aligned), so an untrimmed icon scaled to 20px
    looks tiny. The shadow has alpha, so it is kept.
    """
    bbox = img.getchannel("A").getbbox()
    return img.crop(bbox) if bbox else img


def save_image(code: int, data: bytes, path_base: Path) -> Path | None:
    """Write one image tag out, as PNG where we must decode it ourselves."""
    if code in (DEFINE_BITS, DEFINE_BITS_JPEG2):
        jpeg = data[2:]
        path = path_base.with_suffix(".jpg")
        path.write_bytes(jpeg.replace(b"\xff\xd9\xff\xd8", b"", 1))
        return path
    if code == DEFINE_BITS_JPEG3:
        # JPEG colour plus a separately zlib-compressed 8-bit alpha plane. Writing only
        # the JPEG leaves every icon on a black square; the alpha is what makes them
        # cut-outs, which is what you want to trace.
        from PIL import Image
        alpha_off, = struct.unpack_from("<I", data, 2)
        jpeg = data[6:6 + alpha_off].replace(b"\xff\xd9\xff\xd8", b"", 1)
        rgb = Image.open(io.BytesIO(jpeg)).convert("RGB")
        path = path_base.with_suffix(".png")
        try:
            alpha_raw = zlib.decompress(data[6 + alpha_off:])
            alpha = Image.frombytes("L", rgb.size, alpha_raw[:rgb.size[0] * rgb.size[1]])
            rgb.putalpha(alpha)
            rgb = unpremultiply(rgb)
        except (zlib.error, ValueError):
            pass                                   # no usable alpha: keep it opaque
        rgb = trim(rgb)
        rgb.save(path)
        return path
    if code in (DEFINE_BITS_LOSSLESS, DEFINE_BITS_LOSSLESS2):
        fmt = data[2]
        width, height = struct.unpack_from("<HH", data, 3)
        pos = 7
        table = 0
        if fmt == 3:
            table = data[pos] + 1
            pos += 1
        raw = zlib.decompress(data[pos:])
        from PIL import Image
        if fmt == 3:
            palette = raw[:table * 4]
            stride = (width + 3) & ~3
            pixels = raw[table * 4:]
            img = Image.new("RGBA", (width, height))
            out = []
            for y in range(height):
                for x in range(width):
                    i = pixels[y * stride + x] * 4
                    r, g, b, a = palette[i:i + 4]
                    out.append((r, g, b, a))
            img.putdata(out)
        else:                                     # 32-bit ARGB, rows padded to 4 bytes
            img = Image.frombytes("RGBA", (width, height), raw[:width * height * 4])
            a, r, g, b = img.split()
            img = Image.merge("RGBA", (r, g, b, a))
        path = path_base.with_suffix(".png")
        trim(img).save(path)
        return path
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("firmware", type=Path, help="a .hfw firmware image")
    parser.add_argument("--out", type=Path, default=ROOT / "icons")
    args = parser.parse_args(argv)

    # firmware zip -> the region holding app/ -> app-main.swf
    swf = None
    with zipfile.ZipFile(args.firmware) as fw:
        for region in fw.namelist():
            if not region.lower().endswith(".ezhex"):
                continue
            blob = fw.read(region)
            if blob[:2] != b"PK":
                continue
            with zipfile.ZipFile(io.BytesIO(blob)) as inner:
                for name in inner.namelist():
                    if name.endswith("app-main.swf"):
                        swf = inner.read(name)
                        break
            if swf:
                break
    if not swf:
        raise SystemExit(f"no app-main.swf inside {args.firmware}")

    body = movie_body(swf)
    exports, images, sprites, shapes = collect(body)
    print(f"{len(exports)} exported symbols, {len(images)} bitmaps")

    groups = {
        "devices": lambda s: s.startswith("DEVICE_") and s.endswith("_MC"),
        "activities": lambda s: s.startswith("00_SHARED_Virtual") and s.endswith("_MC"),
        "buttons": lambda s: s.startswith("CUSTOM_"),
    }
    written = {}
    for group, matches in groups.items():
        folder = args.out / group
        folder.mkdir(parents=True, exist_ok=True)
        names = []
        for cid, symbol in sorted(exports.items(), key=lambda kv: kv[1]):
            if not matches(symbol):
                continue
            clean = (symbol.replace("DEVICE_", "").replace("00_SHARED_", "")
                     .replace("CUSTOM_", "").removesuffix("_MC"))
            names.append(clean)
            found = resolve_images(cid, images, sprites, shapes)
            for n, bid in enumerate(dict.fromkeys(found)):
                suffix = "" if n == 0 else f"_{n}"
                code, data = images[bid]
                try:
                    save_image(code, data, folder / f"{clean}{suffix}")
                except Exception as exc:
                    print(f"  ! {clean}: {type(exc).__name__}: {exc}")
        written[group] = names
        made = len(list(folder.glob("*")))
        print(f"  {group:11} {len(names):3} symbols -> {made} image(s) in {folder}")

    (args.out / "TYPES.md").write_text(
        "# Types the firmware actually supports\n\n"
        "Read out of `app-main.swf`, so this is the real vocabulary - not a guess.\n\n"
        f"## Device types ({len(written['devices'])})\n\n"
        + "\n".join(f"- {n}" for n in written["devices"])
        + f"\n\n## Activity types ({len(written['activities'])})\n\n"
        + "\n".join(f"- {n}" for n in written["activities"])
        + f"\n\n## Button icons ({len(written['buttons'])})\n\n"
        "These are the values a configuration's `<Icon>` may take.\n\n"
        + "\n".join(f"- {n}" for n in written["buttons"]) + "\n")
    print(f"vocabulary -> {args.out / 'TYPES.md'}")


if __name__ == "__main__":
    main()
