# Harmony One `GSPM` configuration

Harmony One configuration payloads are indexed binary images beginning `GSPM`. They are carried
inside the same XML-header EZHex envelope as other direct Harmony remotes, but they are not ZIP
files and do not share the Harmony 900 configuration semantics.

The observations in these documents agree across four independent Harmony One donor
configurations. They are also consistent with the arch-12 configuration base and cookie in
Concordance and with the remote validator analysis performed by RE-HARMONY.

## Documents

| Document | What it covers |
| --- | --- |
| [image.md](image.md) | Identity, the outer structure and checksum, absolute pointers, what each section holds, the start-up list, timers, and how a whole image is laid out |
| [firmware.md](firmware.md) | The factory configuration in firmware, what a configuration made from nothing contains, and the forty screens that belong to the firmware |
| [commands.md](commands.md) | IR waveforms, section 5's command index and records, toggling (RC5/RC6) commands, command objects |
| [screens.md](screens.md) | Section 6's screens, slots and key registers, how command screens and menu rows are drawn, paging, modes and their handler lists |
| [drawing.md](drawing.md) | The drawing VM, fonts, pictures and their encodings, section 12's status overlays, touch geometry, where the artwork comes from |
| [activity-engine.md](activity-engine.md) | Section 10's contexts, section 14's state machines, how an activity reaches its commands, the Activities menu |
| [harmony-800-firmware.md](harmony-800-firmware.md) | What the Harmony 800's firmware, a reader that can be read, says about instructions, lists, the key stack and settings |
| [generating.md](generating.md) | How a build generates an image from a project: layout, the hub, words and font codes, the device menu, command pages |
| [options.md](options.md) | The Options screens and the date, time and sensitivity pickers; section 15's switch tables |
| [idle.md](idle.md) | Key lights, wake and sleep, the firmware's events, start-up, and the charging screens |
| [activities.md](activities.md) | Devices' power and input state variables, and how a build generates activities, Help and the Remote Assistant |
| [reading.md](reading.md) | What an import relies on when it reads a configuration back, and what validation proves |

## What Afterglow does with an image

Afterglow validates an image, indexes what it can prove of it - section-5 command ownership,
command objects, press/hold/release waveform records, screen and key ownership, drawing programs,
section-7 fonts, section-19 touch geometry, device-menu rows, activity contexts and state
transitions - and imports the portable part. Every unmodelled native byte is preserved unchanged
alongside the project. A build never starts from that image: it generates the whole configuration
from the project ([generating.md](generating.md)). Earlier versions edited the
imported image in place instead - relocating sections, cloning screens, patching pointers; that
path was removed once generation covered everything it did, and the findings it produced are kept
here as format facts.
