# Documentation

Reference documentation for supported remote architectures and configuration formats.

## Remote Architectures & Configuration Formats

| Directory | Architecture / Target | Format Reference |
|---|---|---|
| [harmony_pk/](harmony_pk/README.md) | Harmony 900 (`harmony_pk`) | `.ezhex` container, XML payload, `IrProto.bin`, `SsIr.bin` |
| [harmony_one/](harmony_one/README.md) | Harmony One (`harmony-one`) | arch-12 `GSPM` indexed image and native integrity |
| [harmony_800/](harmony_800/README.md) | Harmony 800 (`harmony-800`) | `GSGD` image read from the 800's firmware |

### Harmony 900 (`harmony_pk`) Format Documents

- [ezhex.md](harmony_pk/ezhex.md) — The `.ezhex` container: XML header, checksum, ZIP payload
- [configuration.md](harmony_pk/configuration.md) — The unpacked tree: `UserConfiguration.xml`, `platformconfig`, install scripts
- [irproto.md](harmony_pk/irproto.md) — `IrProto.bin`: the IR bytecode blocks and the `<Code>` values that select them
- [ssir.md](harmony_pk/ssir.md) — `SsIr.bin`: recorded waveforms for commands no protocol describes
- [ssir-sequences.md](harmony_pk/ssir-sequences.md) — `SsIr.bin` on the Harmony 1100: every command a recorded device sequence
- [remote-identities.md](harmony_pk/remote-identities.md) — Which remote a configuration is for, and profile status

### Harmony One (`harmony-one`) Format Documents

- [README.md](harmony_one/README.md) — What the `GSPM` image is, what Afterglow does with one, and where each part is described
- [image.md](harmony_one/image.md) — Identity, the outer structure and checksum, absolute pointers, what each section holds, the start-up list, timers, and how a whole image is laid out
- [firmware.md](harmony_one/firmware.md) — The factory configuration in firmware, what a configuration made from nothing contains, and the forty screens that belong to the firmware
- [commands.md](harmony_one/commands.md) — IR waveforms, section 5's command index and records, toggling (RC5/RC6) commands, command objects
- [screens.md](harmony_one/screens.md) — Section 6's screens, slots and key registers, how command screens and menu rows are drawn, paging, modes and their handler lists
- [drawing.md](harmony_one/drawing.md) — The drawing VM, fonts, pictures and their encodings, section 12's status overlays, touch geometry, where the artwork comes from
- [activity-engine.md](harmony_one/activity-engine.md) — Section 10's contexts, section 14's state machines, how an activity reaches its commands, the Activities menu
- [harmony-800-firmware.md](harmony_one/harmony-800-firmware.md) — What the Harmony 800's firmware, a reader that can be read, says about instructions, lists, the key stack and settings
- [generating.md](harmony_one/generating.md) — How a build generates an image from a project: layout, the hub, words and font codes, the device menu, command pages
- [options.md](harmony_one/options.md) — The Options screens and the date, time and sensitivity pickers; section 15's switch tables
- [idle.md](harmony_one/idle.md) — Key lights, wake and sleep, the firmware's events, start-up, and the charging screens
- [activities.md](harmony_one/activities.md) — Devices' power and input state variables, and how a build generates activities, Help and the Remote Assistant
- [reading.md](harmony_one/reading.md) — What an import relies on when it reads a configuration back, and what validation proves

### Harmony 800 (`harmony-800`) Format Documents

- [README.md](harmony_800/README.md) — What the `GSGD` image is and where the remote keeps it
- [image.md](harmony_800/image.md) — The header and close, the checksum, the Afterglow mark, what each section holds, and the embedded image
- [lists-and-instructions.md](harmony_800/lists-and-instructions.md) — Lists and their tags, the events the firmware posts, and the instructions it runs
- [hardware.md](harmony_800/hardware.md) — The lights, the keys and the battery levels
- [drawing.md](harmony_800/drawing.md) — Screens, the drawing VM, and touch
