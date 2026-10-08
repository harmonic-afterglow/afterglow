<img src="src/afterglow/branding/afterglow-icon.svg" alt="" width="120" align="right">

<div id="toc">
  <ul style="list-style: none">
    <summary>
      
[![Discord](https://img.shields.io/badge/-updates-5865f2?logo=discord&logoColor=white&labelColor=gray)](https://discord.gg/GEUdc2FfRH)
      <h1>Afterglow</h1> <!-- removes underline under the h1 -->
    </summary>
  </ul>
</div>

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

- Harmony 900
- Harmony 1100 - experimental: configurations are read, imported and built, and
  written only through **Test write**, which backs the remote up first and checks
  the result.

## Before you start

**Windows** needs nothing installed first. The first time a Harmony 900, 1000 or 1100
is connected, Afterglow offers to turn on **direct access**: it then talks to the remote
over USB itself, through a driver that comes with Windows, and Windows asks for
administrator permission once. That is faster and more reliable than Logitech's driver,
which is no longer maintained and is refused by many current PCs. Logitech's Harmony
Remote Software is not needed; where its driver is installed and loads, Afterglow can
still use it. Settings > Remote connection switches either way.

**macOS** needs nothing: Afterglow's macOS build talks to the remote over USB itself.
(Logitech's own Mac driver does not work on current macOS.)

**Linux** needs nothing. The first time you run it, Afterglow offers to turn on
**direct access**, so it talks to the remote over USB itself; that asks for your password
once. Settings > Remote connection has it, and the old network link, at any time.

## Using it

Download the build for your platform from
[Releases](https://github.com/harmonic-afterglow/afterglow/releases). They are standalone - no Python installation needed.

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
- Back on **Flash**, choose **Build Config**, then **Flash to Remote**.

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

**Your files** - projects, backups, your device library and logos - are all in
`Documents/Afterglow`. To send someone a project, use **File > Export Shareable Project**:
the `.afterglow` file it writes holds everything needed to build it, and **File > Open**
reads it.

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
- **[Logitech Harmony IR Archive](https://github.com/pickysysadmin/logitech-harmony-ir-archive)** — for preserving and sharing the archived Logitech IR device database.
- **[Flipper-IRDB](https://github.com/Lucaslhm/Flipper-IRDB)** — for the open community IR remote database.
- **[IRDB](https://github.com/probonopd/irdb)** — for the public open-source IR database.
- **The community** — who provided donor configuration dumps, hardware captures, and testing to make open Harmony configuration possible.

## AI Disclosure

This project has been developed with the assistance of AI tools and language models (including Anthropic's Claude, Google's Gemini, and OpenAI's ChatGPT). AI assistance was used for reverse-engineering analysis, code auditing and refractoring. All AI-assisted contributions are reviewed, tested, and validated against real hardware or automated test suites.
