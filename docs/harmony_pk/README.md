# Configuration format

Reference for the files a Harmony 900 configuration is made of. These describe the
format itself, independently of how Afterglow reads or writes it, so that the code can
stay short and point here rather than re-explaining the format in comments.

| Document | Covers |
|---|---|
| [ezhex.md](ezhex.md) | The `.ezhex` container: XML header, checksum, ZIP payload |
| [configuration.md](configuration.md) | The unpacked tree: `UserConfiguration.xml`, `platformconfig`, install scripts |
| [irproto.md](irproto.md) | `IrProto.bin`: the IR bytecode blocks and the `<Code>` values that select them |
| [ssir.md](ssir.md) | `SsIr.bin`: recorded waveforms for commands no protocol describes |
| [remote-identities.md](remote-identities.md) | Which remote a configuration is for, and which are supported |

## Status of the information

Everything here was established by reverse engineering: reading the remote's own firmware
(`ir_mgr`, `data_srv`, and the Lua interpreter in `Region_12` of `61.hfw`), comparing
donor configurations from several owners, and flashing the results to a Harmony 900.

Where a claim is confirmed on hardware it says so. Where a field's meaning is not known,
the format documents that it is preserved verbatim rather than guessing - a specification
that invents meaning for bytes it cannot regenerate is worse than one that admits the gap.

## Scope

The Harmony 900 is the only remote verified end to end. The 1000 and 1100 store
configurations the same way and have donor evidence, but are not claimed compatible until
a real flash and boot confirms it. The 880, 890 and 76x use a different architecture
entirely and none of this applies to them.
