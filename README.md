<a href="https://harmonic-afterglow.github.io/"><img src="src/afterglow/branding/afterglow-icon.svg" alt="Afterglow website" width="100" align="right"></a>


[![Discord](https://img.shields.io/badge/-updates-5865f2?logo=discord&logoColor=white&labelColor=gray)](https://discord.gg/GEUdc2FfRH)
      <h1>Afterglow</h1> <!-- removes underline under the h1 -->


**Set up a Logitech Harmony remote after the service shut down.**

Logitech closed the Harmony service in 2025. The remotes still work - they just cannot be *reconfigured*, because every way to change what a button does went through a server that no longer answers.

Afterglow builds the configuration on your own computer and writes it back over USB.
Nothing is sent anywhere.

> [!WARNING]
> Not affiliated with, endorsed by, or connected to Logitech. *Harmony* and *Logitech*
> are trademarks of Logitech International S.A.

> [!CAUTION]
> We're not responsible for bricked devices, dead flashes,
> thermonuclear war, or you getting fined because your
> receiver blasted music at full volume. Please ask questions
> if you have any concerns about certain functions included
> in this software before using it! YOU are choosing to make 
> these operations, and if you point the finger at us for
> messing up your device, we will laugh at you.

## Which remotes are supported?

- **Supported**
  - Harmony 900
- **Experimental** - configurations are read, imported, built and written, but not yet
  confirmed on every remote. Before each write Afterglow saves what is on the remote to
  the `Dumps` folder, and **Settings › Flash a Configuration File** puts it back.
  - Harmony 1100
  - Harmony One
  - Harmony 800 - a prototype Logitech never sold

## Before you start

Nothing needs installing: no Python, no Logitech software, no driver.

- **Windows 10 and 11** - the first time a remote is connected, Afterglow offers
  **direct access**, talking to it over USB itself; Windows asks for administrator
  permission once. **Settings › Remote connection** switches back to Logitech's driver.
- **Windows 7, 8 and 32-bit Windows** - download `afterglow-windows7-x86.exe`. Windows 7
  needs update KB2533623 (or KB3063858). When turning direct access on, choose **Install
  this driver software anyway**: the driver is Windows' own WinUSB, and only the small
  file pointing the remote at it, which is not signed, comes from Afterglow.
- **macOS 11 and later** - nothing to do. For an Intel Mac on 10.13 to 10.15, download
  `afterglow-macos-x86_64-legacy.dmg`.
- **Linux** (x86_64 or ARM64; Ubuntu 20.04, Debian 11, Fedora 32 or newer) - download the
  AppImage for your machine, make it executable (`chmod +x`) and run it. The first time,
  Afterglow offers direct access, which asks for your password once.

## Using it

Download the build for your platform from
[Releases](https://github.com/harmonic-afterglow/afterglow/releases).

On macOS, open the `.dmg` and drag Afterglow to Applications. The app is not notarized,
so the first time macOS will refuse to open it: open it once, then go to
**System Settings > Privacy & Security** and choose **Open Anyway**.

> [!IMPORTANT]
> **Save a backup before anything else.** On the **Flash** tab, choose **Read from
> Remote** and keep the file somewhere safe. It is your only way back to the setup you
> have now: **Settings > Flash a Configuration File** puts it back.

Then:

- **File > Import** that backup to bring your existing devices and activities into Afterglow - or skip it and start from an empty project.
- Set your equipment up on the **Devices** and **Activities** tabs.
- Back on **Flash**, choose **Flash to Remote**. It builds the project as it is and writes it;
  **File > Export .ezhex** saves the built file instead, without writing anything.

### What you can set up

- **Devices** - from your own library, by **learning codes off the original remote**, from an online database if you enable one, or from a configuration you imported.
- **Activities** - "Watch TV" turns on the television and the amplifier, switches both to the right input, and routes each key to whichever device should receive it.
- **Every physical button** in an activity, and **the power plan** - which devices turn on, in what order, and which turn off.
- **How each device switches inputs** - directly, by stepping through them with one button, or not at all - and how it takes channel numbers.
- **IR output per device** - the remote's front emitter, or a wireless RF blaster including its two wired mini-emitters. New blasters can be paired from the app.
- **Remote settings** - clock, key beep, large font, backlight, child lock.
- **The remote's own artwork** - the device, activity and button icons it draws.

Configurations are built from scratch.
Importing takes your devices and activities and leaves the other remote's state behind.

**Your files** are all in `Documents/Afterglow`, a folder for each kind:

- `Projects` - your projects, and shareable projects you open
- `Dumps` - configurations read from a remote, ones you import, and the backup taken
  before writing an experimental remote
- `Generated` - configurations Afterglow builds, which **Flash** writes
- `Themes` - looks for the remotes whose screens can be restyled; each comes with an
  `Example` and a `README.md` saying what to change
- `Backups` - earlier versions of each project, kept every time it is saved (**File > Show
  Earlier Versions**)
- `Library` - your own devices, and what you learn from the original remote
- `Logos` - favourite-channel logos; an import keeps the pictures it brings in
  `Logos/Imported`

Each dialog opens in its own folder. To send someone a project, use **File > Export
Shareable Project**: the `.afterglow` file it writes holds everything needed to build
it, and **File > Open** reads it.

## Something went wrong

**The remote will not connect.** Give it a few seconds - it is not ready the instant it is plugged in. If it still will not connect after 20 seconds, unplug it and plug it back in.

**Flashing succeeded but the remote rejected the configuration.** Re-flash your backup with **Settings > Flash a Configuration File**, then open an issue with what you built.

**On Linux or Windows the remote is not found.** Settings > Remote connection, and turn on direct access.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the architecture, and [docs/](docs/) for the configuration format itself - the container, the IR bytecode, the device and activity XML.

Running from source instead of a release build:

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,gui]'
.venv/bin/python afterglow.py          # or: python3 afterglow.py
.venv/bin/python -m pytest
```

From source it uses the libconcord installed on the system. To use Afterglow's own build
instead (needed for direct access), point `AFTERGLOW_LIBCONCORD` at the library file, for
example `AFTERGLOW_LIBCONCORD=~/concordance/libconcord/.libs/libconcord.so.6`.

## Special Thanks

- **[Concordance / libconcord](https://github.com/jaymzh/concordance)** — for reverse engineering the Harmony USB protocol and maintaining `libconcord`.
- **[Logitech Harmony IR Archive](https://github.com/pickysysadmin/logitech-harmony-ir-archive)** — for capturing, preserving and sharing Logitech's device database, which Afterglow reads from its own copy, [harmony-ir-archive](https://github.com/harmonic-afterglow/harmony-ir-archive).
- **[Flipper-IRDB](https://github.com/Lucaslhm/Flipper-IRDB)** — for the open community IR remote database.
- **[IRDB](https://github.com/probonopd/irdb)** — for the public open-source IR database.
- **The community** — who provided donor configuration dumps, hardware captures, and testing to make open Harmony configuration possible.

## AI Disclosure

This project has been developed with the assistance of AI tools and language models (including Anthropic's Claude, Google's Gemini, and OpenAI's ChatGPT). AI assistance was used for reverse-engineering analysis, code auditing and refractoring. All AI-assisted contributions are reviewed, tested, and validated against real hardware or automated test suites.
