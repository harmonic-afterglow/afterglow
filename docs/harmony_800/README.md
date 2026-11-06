# Harmony 800 `GSGD` configuration image

The Harmony 800 ("Ravenswood", USB `046d:c127`, arch `0x12`, skin `0x56`) is a touchscreen
remote with a slide-out QWERTY keyboard and a Unifying radio. Its configuration is a sibling of
the Harmony One's `GSPM` image ([harmony_one/](../harmony_one/README.md)); everything here was
read from the 800's own firmware (0.7.1, STM32F102, dumped over SWD) and checked against the two
images a factory remote carries - `/cfg/usercfg` and `/fw/embeddedcfg`. Function names are the
firmware's addresses (`FUN_08xxxxxx`).

## Documents

| Document | What it covers |
| --- | --- |
| [image.md](image.md) | The header and close, the checksum, the Afterglow mark, what each section holds, and the embedded image |
| [lists-and-instructions.md](lists-and-instructions.md) | Lists and their tags, the events the firmware posts, and the instructions it runs |
| [hardware.md](hardware.md) | The lights, the keys and the battery levels |
| [drawing.md](drawing.md) | Screens, the drawing VM, and touch |

## Where the images live

The remote serves files over the MH protocol (Concordance's `remote_mh.cpp`). Its file table
(firmware `0x08016300`) places the two configurations on the SPI flash:

| File | SPI flash | Size | Base address |
| --- | --- | --- | --- |
| `/cfg/usercfg` | `0x050000` | `0x390000` | `0x050000` |
| `/fw/embeddedcfg` | `0x030000` | `0x10000` | `0x030000` |

Addresses inside an image are absolute (`base + offset`, `u24`). At boot `FUN_080146fc` uses the
user configuration when its checksum holds and falls back to the embedded one otherwise.
