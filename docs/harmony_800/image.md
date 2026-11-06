# The image: header, sections and the Afterglow mark

## Header and close

| Offset | Bytes | Meaning |
| --- | --- | --- |
| `0x00` | `GSGD` | magic (the One: `GSPM`) |
| `0x04` | `u32` | end vector: absolute address of the close marker |
| `0x08` | `u32` `0x1600` | constant |
| `0x0C` | 20 x `u32` | absolute section pointers, sections 0 to 19 - **all twenty present** |
| `0x5C` | 7 x `00` | zero |
| `0x63` | `CHJL` | marker (the One: `LWJL`) |
| `0x67` | `u8` | `00` in both factory images |

The image closes with a two-byte checksum and `OGSA` (the One: `PTYY`); the end vector points at
`OGSA`. The checksum is the One's: two XOR lanes seeded `0x21` and `0x43` over the bytes before
the checksum - but where the One's tools and Concordance skip an odd last byte, the 800's firmware
(`FUN_0800f144`, called from `FUN_0800efd0`) XORs it into the low lane. Logitech's images have an
even length, so the difference never shows in them; a generated image is padded with a zero to an
even length, so every reading agrees. A user configuration whose checksum fails is not used: the
remote boots its embedded one, which raises message 0, "Go to Website to update settings"
(`main()`, `FUN_0801148c`). This happened to the first generated image written to a remote.

## The Afterglow mark

Every image Afterglow builds ends its body - after the last section's contents, before the
checksum - with the project it was built from and a trailer naming it. Nothing points at
them, so the firmware never reads them; they are inside the checksummed bytes, and the end
vector alone finds them:

| Bytes | Meaning |
| --- | --- |
| `N` | the project: compact, key-sorted JSON (UTF-8), compressed with zlib |
| 16 | `AFTERGLOW-800` padded with zeros |
| `u16` | mark version, `1` |
| `u16` | zero |
| `u32` | `N` |
| `u32` | CRC-32 of the `N` bytes |
| 4 | `AGLW` |

The trailer's last byte is the one before the checksum; a zero before the project keeps the
whole of even length. Settings that only say where a build was written (`out_file`) are left
out of the project. An image without a sound mark - every configuration Logitech's software
made - is not read back; only Afterglow's own configurations are supported.

## Sections

`FUN_080147c0(n)` positions the reader at section *n*'s header pointer. What each section holds,
as the firmware reads it:

| Section | Contents | Reader |
| --- | --- | --- |
| 0 | name records (`Root`, `State`) | - |
| 1, 2, 3 | platform constants; 3 is the clock stamp | - |
| 4 | firmware message table: `u24` default mode, `u16` count, `{u8 id, u24 mode}` | `FUN_0801385c` |
| 5 | command index: device count, `u24` per device; device: `00`, `u16` count, `u24` per command (record `+11`) | `FUN_08015540` |
| 6 | screens: `u16` count, `00`, `u24` trailer per screen | `FUN_0801363c` |
| 7 | fonts: `u16` count, `u24` per font | `FUN_08013a76` |
| 8 | radio commands (empty, `00`, in both factory images) | `FUN_08010406` |
| 9 | start-up list, then the screens' key registers | `FUN_0800ba44` |
| 10 | contexts: `u8` count, `u24` per context | - |
| 11 | objects: `u16` count, `u24` per object | `FUN_08018e2c` |
| 12 | status overlays: `u16` count, `u24` each | `FUN_08013cc8` |
| 13 | timers: `u8` count | `FUN_0801697c` |
| 14 | engine records (state variables) | - |
| 15 | switch tables, then platform property tables | `FUN_0801886c` |
| 16 | `u8` count, `u24` per platform property table (into section 15's tail) | - |
| 17, 18 | `00`, `00 00` | - |
| 19 | touch templates: `u8` count, `u24` each | `FUN_0800d248` |

Section 4's opening bytes are the same bytes the One's notes read as a "key table": read as the
800 firmware reads them, they map firmware message ids (`FUN_080138bc(id)`) to screens.

## The embedded image

`/fw/embeddedcfg` is the 800's minimal configuration, the counterpart of the One's
`Region_3.EZHex`: thirty text screens (the firmware's messages), one font, one context, five
objects, no devices. Its start-up object pushes context 0, enters screen 0 ("Go to Website to
update settings") and enters screen 28 ("USB CONNECTED") when variable `0x10` (USB) is set.
