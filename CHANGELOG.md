# Changelog

All notable changes to Afterglow will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0-beta.1] - Unreleased

The **Harmony One**, as an experimental remote: Afterglow builds its configuration from
your devices and activities - every screen, button, light and menu generated, nothing
copied from a previous configuration - and imports the one already on it. Like the
Harmony 1100, it is written only through **Test write**, which backs the remote up
first. Builds have booted on testers' remotes, with activities, favourites and the
Remote Assistant working; a write from inside Afterglow itself has not been reported
yet, and that is what this beta is for.

### Added

- **Harmony One configurations, built from scratch.** The Activities menu, the device
  list and each device's command pages; activities that switch devices on and off, set
  inputs, route the keys and show their own buttons, with favourite channels and their
  logos, Help, and the Remote Assistant asking whether everything turned on; Off;
  Options with Date and Time, Screen Sensitivity, Screen Sounds, the Remote Assistant
  switch and a Tutorial; the keypad lights, sleep and waking when picked up, and the
  USB and charging screens. A step can hold a command for as long as a device needs, and
  an input can be chosen in several steps.
- **Importing a Harmony One configuration** brings across its devices - with their
  commands' names, power, inputs and the keys they are on - and its activities, with
  their buttons, keys and favourites, the favourites' logos (into `Logos/Imported`),
  and the type of every device and activity. A One draws its text rather than storing
  it, so names are read from their letters' shapes, in any language. **Import Complete**
  says what could not be carried over.
- **Themes for the Harmony One.** `Documents/Afterglow/Themes/harmony-one/Example` is
  the look Afterglow ships, to copy and change - pictures, fonts and colours, and a
  TrueType font of your own. **Remote Settings > Theme** lists your themes; a project
  remembers its theme by name.
- **A folder for each kind of file** in `Documents/Afterglow`: `Projects`, `Dumps`
  (configurations read from a remote or imported), `Generated` (configurations built
  here) and `Themes`, beside `Library` and `Logos`. Each dialog opens in its own.
- The Flash tab's log says what a build wrote, and where.
- **Harmony One:** while it charges it shows the battery, then three photos in turn, as
  Logitech's configurations did, and goes back to what it was showing when it is lifted
  off; a charging problem shows its notice. A theme can replace the pictures.
- **Smart TVs wait for their apps, and every device for its inputs** - on the Harmony
  One, 900 and 1100. A TV's online input (Netflix, nearly always) is sent only once its
  apps are up, Logitech's own delay after power-on - the first time after power-on only,
  as Logitech's remotes did - and a device switching inputs gets Logitech's time to
  settle before the next command. Both come with a device from the Logitech database and
  are on its **Timing** page.

### Changed

- **The Logitech device database is read from Afterglow's own archive**,
  [harmony-ir-archive](https://github.com/harmonic-afterglow/harmony-ir-archive): the
  capture of Logitech's service as it answered, served a device at a time - looking a
  device up fetches a few hundred kilobytes, never the database. It carries what the
  earlier source left out, such as which inputs are a TV's apps and how long they take.

- A device's **Timing** page, and the device and activity **Advanced** pages, show only
  what the remote's builder uses: the Harmony One has the power-on delay, the delay
  between a channel's digits, the input and apps delays and Always on.
- The activity list shows a type's name ("Watch a DVD"), as the editor does.
- Shareable projects unpack into `Projects`; an existing lowercase `projects` folder is
  renamed to it.
- Importing no longer leaves a `<name>_extracted` folder beside the file: it is
  unpacked out of sight, and the pictures the project uses are kept in
  `Logos/Imported/<name>`. Folders left by earlier versions can be deleted once no
  project made before this one is built again.
- **Harmony One:** a device's pages leave out what its keys already send - VolumeUp on
  VolumeUp, 1 on Number1 - as Logitech's do, and keep a command put on a key in another's
  place (Return on Exit). An imported configuration's press-only copies and nameless
  codes are on no page either. Kāt's devices now show the buttons Logitech showed.

- **Harmony One: Help, the Remote Assistant and the Tutorial are Logitech's.** Help re-sends
  what the activity set, asks whether that fixed it, then asks after each device and input
  in turn, re-sending whatever is not right. The Remote Assistant shows Logitech's notes
  after a start and after Off - a new remote opens on its welcome - until it is hidden;
  Options turns it back on. The Tutorial is Logitech's eleven pages with their pictures of
  the remote, keeping a small page counter.

### Fixed

- Learning an imported configuration into the device library failed when a device had
  an input that no command selects.
- A macro of one step was described as "1 steps".
- The Harmony One's Remote Assistant asked whether a TV was "set to InputHdmi1"; it
  now says "HDMI 1".
- Reading a Harmony One built here back in could misread a look-alike letter ("Xbox
  One" as "Xbox ane"), skipping that device's buttons.


### Known issues

- **Harmony One:**
  - Its screens are in English only: an imported configuration in another language is
    rebuilt in English.
  - Logitech's Off turns off whatever is on; an imported configuration's Off turns off
    every device that has a power command, which comes to the same.
  - Commands a Logitech configuration never shows on any button or key have no name in
    it, and keep a numbered one ("Command 12"). A favourite that shows only a logo is
    named after its channel or the command it sends.
  - A letter none of the configurations Afterglow has learned from draws, in that size
    of font, cannot be read: it shows as � and Import Complete lists the names that
    have one.

## [0.2.0] - 2026-10-10

The first stable release of 0.2.0. Since 0.1.1, across four betas: Harmony 900
configurations no longer freeze the remote, every physical button can be mapped, a macOS
app, direct USB access on Windows and Linux without Logitech's driver, Test write with
automatic backup, shareable projects, and the Harmony 1100 as an experimental remote. The
betas below list each change.

The **Harmony 1100 stays experimental**: it is written only through Test write, which
backs the remote up first. Its configurations have been checked against the 1100's own
firmware (6.9 to 7.7), two real remotes' configurations rebuild exactly, and one tester
has flashed a build - but few have tried it yet. Please report how it goes.

### Fixed

- **Held buttons on an imported Harmony 1100 could send garbage.** Logitech stores the
  repeat signal some devices send while a button is held (NEC's) once per device, and
  points the other held commands at it; a rebuilt configuration pointed them at the
  wrong place. They now point where Logitech's did, byte for byte.
- An imported Harmony 1100 on the newer board (0.5) was rebuilt naming board 0.3.
- The Harmony 1100's favourite-channels page setting showed as unrecognised.

## [0.2.0-beta.4] - 2026-10-08

Every Harmony 1100 is recognised now, whichever model number and board it has.

### Fixed

- **Harmony 1100s with the newer board (0.5)** were "not supported" and could not be
  backed up: the profile knew only board 0.3. Both boards, and both model numbers
  (skins 62 and 63), are the same remote.
- Test write's backup of a Harmony 1100 failed asking for `ActionLists.xml`, a Harmony
  900 file the 1100 never has.
- "Configuration memory: … of 1 bytes used" on the 900, 1000 and 1100, whose total
  libconcord cannot know: only the size is shown.

## [0.2.0-beta.3] - 2026-10-08

Afterglow talks to the remote over USB itself on Windows and Linux too, and backups
can be put back from inside the app.

### Added

- **Direct access on Windows.** The first time a Harmony 900, 1000 or 1100 is
  connected, Afterglow offers to put it on a USB driver that comes with Windows
  instead of Logitech's, which is no longer maintained and is refused by many current
  PCs. Windows asks for administrator permission once. **Settings > Remote
  connection** shows how the remote is connected and switches either way. A remote
  plugged into a different USB port is a new device to Windows, so Afterglow asks
  again there.
- **Direct access on Linux**, offered on the first start alongside the network link: a
  udev rule that lets you open the remote, installed with one password prompt.
- **Settings > Flash a Configuration File** writes any `.ezhex` onto the remote as it
  is - a backup, to put the remote back how it was - like `concordance -C`. A file
  made for a different remote is refused unless **Force** is ticked.
- **A default remote.** The first start asks which Harmony you have, after the
  connection questions, and Afterglow then starts with a project for it instead of
  always the Harmony 900. Moving a project to another remote offers to make that one
  the default (with "Don't ask again"); **Settings > Default Remote** changes it.

### Changed

- Reading from and writing to the remote say **Connecting to the remote** while it is
  being found, which can take up to 20 seconds.
- Running from source, `AFTERGLOW_LIBCONCORD` names the libconcord to use, ahead of the
  one installed on the system.

### Known issues

- With a large configuration, the Harmony 900's screen can stay white after a restart
  until the remote has gone to sleep once; it is normal from then on.

## [0.2.0-beta.2] - 2026-10-07

The Harmony 1100 joins as an experimental remote, and Afterglow gets a macOS app.

### Added

- **Harmony 1100** (experimental): its configurations are read and imported - every
  command, activities and their touchscreen pages - and built back. Writing goes
  through Test write, which backs the remote up first and checks the result.
- **A macOS app** (`.dmg`) for Apple Silicon, and Intel where the build succeeds. It
  talks to the Harmony 900/1000/1100 over USB by itself: no driver to install.
  Logitech's own Mac driver does not work on current macOS.
- The bundles carry Afterglow's own libconcord
  ([harmonic-afterglow/concordance](https://github.com/harmonic-afterglow/concordance),
  branch `usbnet-link`), which reaches the 900/1000/1100 over USB itself wherever it can
  claim the remote, and falls back to the network link (Logitech's driver on Windows)
  where it cannot.

### Fixed

- **The macOS app crashing on Apple Silicon** when talking to a remote a second time,
  or on quitting after it had: every call into libconcord now runs on one thread.
- **Searching the Logitech database failing on macOS** with a certificate error: the
  app now checks downloads against the system's own certificates.
- **Skip and replay keys that did nothing**: a device's own command for them -
  ChapterNext, NextTrack, Replay and the like - now goes on the skip keys when nothing
  else is there, as in Logitech's configurations. Existing projects are filled once
  when opened; imported ones are left as they were.
- A key Logitech bound to a held command sent it only once when held.
- Reading a configuration from a remote shortly after a reset could crash: the
  remote's configuration had grown since it was measured. It is now measured again.
- Under KDE's Breeze, form fields stayed at their smallest size, leaving the role
  pickers a few letters wide.
- An activity could not be left without a Display, Control or Volume device.

### Changed

- The tabs run straight on from the title bar, with no frame of their own; on macOS
  without a line between them. The current tab's name is no longer underlined under
  Breeze and Oxygen.
- Device, activity and button pictures are taken from the Harmony 1100's PNGs, without
  the speckle the 900's left in every shadow.
- Each remote's profile decides which tabs, editor pages, settings and languages are
  shown for it.

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
