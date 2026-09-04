# Documentation

Reference documentation for supported remote architectures and configuration formats.

## Remote Architectures & Configuration Formats

| Directory | Architecture / Target | Format Reference |
|---|---|---|
| [harmony_pk/](harmony_pk/README.md) | Harmony 900 (`harmony_pk`) | `.ezhex` container, XML payload, `IrProto.bin`, `SsIr.bin` |

### Harmony 900 (`harmony_pk`) Format Documents

- [ezhex.md](harmony_pk/ezhex.md) — The `.ezhex` container: XML header, checksum, ZIP payload
- [configuration.md](harmony_pk/configuration.md) — The unpacked tree: `UserConfiguration.xml`, `platformconfig`, install scripts
- [irproto.md](harmony_pk/irproto.md) — `IrProto.bin`: the IR bytecode blocks and the `<Code>` values that select them
- [ssir.md](harmony_pk/ssir.md) — `SsIr.bin`: recorded waveforms for commands no protocol describes
- [remote-identities.md](harmony_pk/remote-identities.md) — Which remote a configuration is for, and profile status
