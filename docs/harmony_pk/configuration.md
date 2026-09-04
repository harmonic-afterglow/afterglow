# The unpacked configuration tree

The [`.ezhex`](ezhex.md) ZIP payload extracts to a filesystem tree that the remote
installs. The parts that matter:

    .preinstall                 shell scripts the remote EXECUTES during install
    .postinstall
    .version
    META-INF/MANIFEST.MF
    userconfig/UserConfiguration.xml
    platformconfig/*.dat
    IrProto.bin                 see irproto.md
    SsIr.bin                    see ssir.md

## Install scripts and line endings

`.preinstall` and `.postinstall` are shell scripts the remote runs. With CRLF endings the
shebang reads `#!/bin/sh\r`, an interpreter that does not exist; the script fails and the
remote rejects the whole configuration *after* reporting the transfer as successful.

The tree deliberately **mixes** line endings, so "normalise everything" is itself a
corruption:

| Endings | Files |
|---|---|
| LF | `.preinstall`, `.postinstall`, every `platformconfig` file |
| CRLF | `.version`, `META-INF/MANIFEST.MF` |

The `platformconfig` `.dat` files are parsed line by line, so a trailing `\r` corrupts
every value in them.

## File modes

Modes are part of the format, not an accident of whatever produced the archive.

| Path | Mode |
|---|---|
| `META-INF/` | `40777` |
| other directories | `40775` |
| `.preinstall`, `.postinstall` | `100775` - executed by the remote |
| `.version`, `META-INF/MANIFEST.MF` | `100666` |
| `userconfig/*` | `100775` |
| `platformconfig/system_*.dat` | `100666` - see below |
| `platformconfig/{tilt,sleep,pmic}cfg.dat`, `batt_lvls.dat` | `100644` |

### Why `system_*.dat` must be world-writable

`data_srv` holds every setting and drives the interface, and it runs as `nobody`. The
remote's update manager extracts a shipped configuration as `root`. At `0600 root:root`
the service can neither read nor write these files: every save fails with `EACCES`, the
remote falls back to compiled-in defaults at boot, and it appears to forget both flashed
settings and ones changed on the device itself.

A configuration read *off* a remote shows `0600`, which is correct there only because
`data_srv` created those files and owns them. **Do not copy the mode from a dump.**

## `UserConfiguration.xml`

Plain XML: the devices, the activities, and how the remote should behave.

### Device states

A Harmony tracks what everything is set to rather than firing codes blindly. That
tracking is the `<States>` block, and it is why an activity can turn a television on
without turning it off again when it was already on.

    <State><Id>Power</Id><Value>Off</Value><Value>On</Value><Delay>10500</Delay>
      <DiscreteActions>                 pick a value directly
        <SetAction><Name>Off</Name>    ... </SetAction>
        <ChangeAction><Name>On</Name>  ... </ChangeAction>
      </DiscreteActions>
      <RelativeActions>                 step through the values
        <NextAction> ... </NextAction>
        <PrevAction> ... </PrevAction>
      </RelativeActions>
    </State>

`setType` 1 is `SetAction`, 2 is `ChangeAction`.

### Timing properties

Every device carries four timing properties. The press pair governs discrete taps; the
hold pair governs press-and-hold repeats such as volume or channel ramping.

| Property | Meaning | Typical |
|---|---|---|
| `PressPreSilence` | Quiet gap the remote enforces *before* each discrete tap. Sets the minimum time between rapid taps of the same key. | 1000 |
| `PressInterKey` | Gap between different keys | 500 |
| `HoldPreSilence` | As above, for held keys | 50 |
| `HoldInterKey` | Interval between repeats while held | 100 |

The stock `PressPreSilence` of 1000 makes repeated taps feel about a second apart;
lowering it (300 is common) makes them responsive. Every available dump agrees on 50/100
for the hold pair, so those are sound defaults - but they are defaults, not constants, and
a configuration that carries its own values keeps them.

### Power

`<Delay>` on the Power state is how long the remote waits after powering a device on
before running the rest of an activity. Televisions need several seconds before they
accept IR again.

Two shapes, and which one a device uses depends on the codes it has:

**Discrete** - distinct On and Off codes in `DiscreteActions`. Powering a device on is
then idempotent, so starting an activity cannot switch off a television that was already
on.

**Toggle** - one code that cycles, expressed as `RelativeActions/NextAction`.

### Input

Directly selectable inputs go in `DiscreteActions`, one `SetAction` per input. A device
that can only step through its inputs has no code selecting any one of them, and uses
`RelativeActions` with `NextAction`/`PrevAction`.

**The two containers are mutually exclusive.** `State.lua` reads `RelativeActions` and
only falls through to `DiscreteActions` in an `elseif`, so a state carrying both has its
discrete selections ignored entirely - every directly selectable input silently becomes a
stepper, with nothing in the configuration looking wrong.

An input's selection is not always a single press. Many devices need `InputNext`, a
settling wait, then a second press; sending only the first step selects whatever input
happens to be adjacent.

### Element order

Inside a `SetAction`, `<Action>` comes before `<Name>`. Every real configuration does it
this way.

### Number entry


`<Numeric>` is direct channel entry and has **three** digit sets - `FirstDigit`,
`MiddleDigit` and `LastDigit` - because a receiver may need a different code for the
leading digit of a channel than for the rest.

### Commands

`SendCommand` carries a `Duration` independently of its `Modifier`: a device needing a
long press is written as `Modifier=Press` alongside `Duration=2000`.

### Inter-device delay

Presilence is an inter-device delay. It is applied only inside an activity, and only when
the device being addressed changes.

## Properties

Devices and activities carry properties describing what the hardware *is* (a tuner's
input, a changer's disc count) and how an activity should behave (which page it opens on,
whether unused devices power off). The remote changes its behaviour based on them, so a
property that is present in the configuration but invisible in an editor is impossible to
find when it is the cause of a problem. Preserve everything; describe what is known;
never hide the rest.
