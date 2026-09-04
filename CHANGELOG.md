# Changelog

All notable changes to Afterglow will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-04

### Added

- **Initial release of Afterglow** — standalone local configuration author, builder, and flasher for Logitech Harmony remotes following the official service shutdown.
- **Logitech Harmony 900 Support (`harmony_pk`)**:
  - Full reverse-engineered support for `.ezhex` container packaging, XML configuration structure, checksum verification, and install scripts.
  - Native emission for `IrProto.bin` IR bytecode blocks and `SsIr.bin` captured raw waveforms.
  - Support for devices, discrete/toggle power, multi-step inputs, macro activities, routed states, channel prefixes, and key mappings.
  - Full control over remote hardware settings (backlight level, font size, tilt sensor, child lock, key beep, clock).
- **Multi-Source Device Catalogue**:
  - Built-in local device template library.
  - Online database search for the Logitech Harmony IR Archive (276,236 devices), Flipper-IRDB, and IRDB public catalogues.
  - Unified "All sources" search with source precedence ordering (Local > External Repos > Online Databases) and duplicate entry suppression.
  - Interactive source chip buttons for quick single-source filtering.
- **IR Protocol Engine**:
  - Generic IR compiler achieving 99.98% command reproduction across 2,067,455 unique commands in the Logitech archive.
  - Portable IR protocol grammar enabling full round-trip conversion and hardware-independent signal definitions.
  - Raw IR capture and remote learning engine for uncatalogued handsets.
- **Desktop Application & Utilities**:
  - PyQt6 multi-tab interface (Find/Edit Devices, Activity Builder, Button Mapping, Remote Settings, Flash Operations).
  - Standalone executable packaging for Linux and Windows.
  - Automatic Linux USB network link helper setup (`harmony_net.sh` / udev rule integration).
  - Direct USB operations: backup reading, configuration flashing, and RF blaster pairing.
