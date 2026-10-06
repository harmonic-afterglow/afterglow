# Changelog

All notable changes to Afterglow will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0-beta.1] - 2026-10-06

A beta for testing on real remotes. Everything below passes the test suite and the
Harmony 900's own boot logic, but has not yet been flashed onto many remotes - please
report how it goes.

### Fixed

- **Harmony 900 configurations that froze the remote**: a device that can only step
  through its inputs was written without its input names, which stopped the remote's
  behaviour layer from loading - Help froze, Remote info did nothing and Advanced RF
  settings opened blank. Input names are now kept, and a cycle without them is left out
  rather than written broken.
- **Physical buttons that could not be mapped in an activity** (#5): every button on the
  Harmony 900 can now be assigned, under the names the remote answers to - Pg Up/Pg Dn,
  the transport skips, the colour buttons, Info, Guide, Exit and the two keys beside 0.
  Projects saved with the old names are renamed when opened.
- **"Failed with error 14" when reading or writing on Windows**, for files in folders
  whose names are not plain ASCII.
- **A remote refused as "not proven compatible"** because its board micro revision
  (0.1.15) differed from the 0.1.0 every configuration file records.
- **Remote info showing the configuration as last updated in 2020**: each build now
  carries the time it was made.
- Help text cut off under some desktop styles (KDE's Breeze).
- Unpacking and repacking a configuration is byte-identical on systems using zlib-ng
  (Arch, Fedora).

### Added

- **The remote a project is for**, shown in a new status bar along the bottom with the
  project's contents, file and saved state - each clickable. Clicking the remote moves
  the project to another remote, showing every change before anything is saved.
- **Unsaved changes** are marked in the title and the status bar, edits in Remote
  Settings included, and New, Open and Import ask before replacing unsaved work.
- **Shareable projects** (`.afterglow`): one file holding a project and every protocol
  and picture it needs, so it builds on any computer. File > Export Shareable Project;
  File > Open reads them.
- **An activity's power plan**: which devices turn on, in what order, and which turn off.
- **How a device switches inputs**: directly, by stepping with one command, or not at
  all, and how it takes channel numbers.
- **Help > Connecting a Remote**, walking through the driver and the first connection.
- **Test write** for remotes still in testing: the remote is backed up first, the
  result is read back and checked, and the backup can be restored.
- Learn from remote explains what is missing instead of being greyed out without
  libconcord.

### Changed

- Your device library and prepared logos now live in `Documents/Afterglow` (`Library`
  and `Logos`) beside your projects, instead of hidden application data. An existing
  library is copied there on first start and the old folder renamed, never deleted.
- Remotes are described by profiles, and the interface follows the project's remote:
  only what that remote can do is offered.

## [0.1.1] - 2026-09-07

### Fixed

- Convert and embed protocol definitions from the Logitech Harmony archive when no
  external protocol database is installed, instead of aborting device creation with a
  `LookupError`.
- Preserve the Pronto waveform fallback when neither a reviewed nor mechanically
  converted protocol definition is available.

### Removed

- Remove the redundant online-database source text box and the inaccessible legacy local
  Logitech archive folder mode from the Device Wizard.

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
