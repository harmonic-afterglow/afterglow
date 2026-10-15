# Documentation

Reference documentation for supported remote architectures and configuration formats.

## Remote Architectures & Configuration Formats

| Directory | Architecture / Target | Format Reference |
|---|---|---|
| [harmony_pk/](harmony_pk/README.md) | Harmony 900 (`harmony_pk`) | `.ezhex` container, XML payload, `IrProto.bin`, `SsIr.bin` |
| [harmony_one/](harmony_one/gspm.md) | Harmony One (`harmony-one`) | arch-12 `GSPM` indexed image and native integrity |
| [harmony_800/](harmony_800/gsgd.md) | Harmony 800 (`harmony-800`) | `GSGD` image read from the 800's firmware |

### Harmony 900 (`harmony_pk`) Format Documents

- [ezhex.md](harmony_pk/ezhex.md) — The `.ezhex` container: XML header, checksum, ZIP payload
- [configuration.md](harmony_pk/configuration.md) — The unpacked tree: `UserConfiguration.xml`, `platformconfig`, install scripts
- [irproto.md](harmony_pk/irproto.md) — `IrProto.bin`: the IR bytecode blocks and the `<Code>` values that select them
- [ssir.md](harmony_pk/ssir.md) — `SsIr.bin`: recorded waveforms for commands no protocol describes
- [ssir-sequences.md](harmony_pk/ssir-sequences.md) — `SsIr.bin` on the Harmony 1100: every command a recorded device sequence
- [remote-identities.md](harmony_pk/remote-identities.md) — Which remote a configuration is for, and profile status

### Harmony One (`harmony-one`) Format Documents

- [gspm.md](harmony_one/gspm.md) — The arch-12 indexed image, address space, close marker and checksum

### Harmony 800 (`harmony-800`) Format Documents

- [gsgd.md](harmony_800/gsgd.md) — The `GSGD` image: sections, lists, instructions, drawing and touch, as the firmware reads them
