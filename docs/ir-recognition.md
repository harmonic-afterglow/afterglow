# Recognising a recording as a protocol command

`ir_recognise.py`. A Harmony One - and the 650 and 700, which share its format - stores
every command as a recording: the frames a press sends, then the frame it repeats while
the key is held (`sections`: `intro_pulses`, `repeat_pulses`). A Harmony 900 stores one
fixed waveform per command (SsIr) or a protocol (IrProto), so a recording with a separate
repeat cannot go across as it is. Logitech made those recordings from its protocols, so
they can go across as the protocol command they are.

## By synthesis

A recording is never matched by resemblance. A protocol's press frames are walked over the
recording to read its fields (each bit is whichever of the alphabet's two shapes is next),
and the command is accepted only when that protocol, rendered with those values, gives the
recording back:

- the press is the protocol's press followed by up to eight of its hold frames - a tap that
  repeats a little, as Logitech's do (a Sony command the One sends four frames of, the
  protocol's three and one repeat);
- the repeat is the protocol's hold frame, once or more;
- every duration within 10 % or 80 us, a frame's padding to its period within 20 %;
  the carrier within 5 % (38001 Hz is NEC's 38000).

The library's narrowest protocol is tried first, so a frame NEC1 and extended NEC both
render is NEC1. A bi-phase code (RC5, RC6) draws two half-bits that meet as one pulse, so
a burst may take part of a recorded pulse and the next the rest. A protocol with sender
state (an RC5 toggle) is read with whichever toggle renders the recording back; the 650
keeps a toggling code's other recording as its `alternate`, and then the other toggle
must render that one back.

## The recording's own frame shape

A recording no library protocol renders back is read for its own shape: a header (a mark
and a space, or one mark), a run of bits each drawn in one of two shapes (mark then space -
pulse distance, NEC's - or space then mark after the header - pulse width, Sony's), an
optional trailing mark, and the frame's period. Each frame's bits become a payload, as
Logitech's generic protocols store theirs: a Roku sends a different code while its key is
held, which no library protocol says. The shape is a protocol of its own (`recorded-<hash>`)
added to the device, and accepted, as above, only when it renders the recording back.

The shape may also be:

- a ditto: a short frame with no bits, the same each time, sent while a key is held
  (NEC's; a TiVo's, an Apple TV's, a Yamaha's, an LG's 4.5 ms one);
- a separator: one pair in the middle with a longer space, splitting the bits in two
  fields (Samsung36's);
- an open end: no trailer, the last bit read by its mark, its space the frame's gap (a
  pulse-width fan code);
- two bits a symbol: one mark and four spaces a step apart (RC-MM's, a Foxtel's);
- frames sent on release, of the same shape, padded to a period of their own;
- a frame of the same bits behind a leader of its own: a frame of its own (an RCA's
  first, behind a 20 ms leader, then the usual 4.3 ms one).

Frames are split at spaces of 6 ms or more (RCA's 8.2 ms between frames), not the code
index's 10 ms, which the archive's copy keeps.

On a tester's One (2026-11-16): the Vizio is NEC1 (83 commands), the Sony receiver Sony 12-
and 15-bit (59), the Sony DVD Sony 20-bit (43); the Roku (27) and a PS3 adapter (68) are
their own shapes. Built for a 900, every one of the 230 commands the One keeps a repeat
for replays as the One sent it, tapped and held.

## Where it is used

The 900/1100 builder (`harmony_pk.backend.lower_devices`) replaces each recording it
cannot store - a press and a different repeat - with the command it is, before lowering:
a library protocol; else a shape of its own, when the 900's generic protocol element can
play it; else, when the press is only the repeat sent a few times (`repeated`), the one
fixed waveform it then is. The element plays one run of bits, so a separator's frame
goes as a fixed waveform. The project keeps the recordings: a project moved back to the
One still has them.

On the 600/650/665/700 dumps (2026-11-16), every one of the 3078 distinct commands with
a repeat or a release builds for the 900: 2934 as protocols, 144 as fixed waveforms
(Flirc, Samsung DVD, a 600's RC6 mode 0 DVD).

## The code index

`fingerprint` reads a command's first frame as the recording's own shape does - a header,
bits in one of two shapes, a trailer - and keys it as `"<header class>-<bits>-<hex>"`: the
header's first mark in classes of 250 us, how many bits, their value. It names no
protocol, so a code recorded off a remote and Logitech's Pronto of it give one key.

Afterglow's IR archive (harmonic-afterglow/harmony-ir-archive, `build_index.py`) keys every
command of every command set that has a Pronto with the same rules - the functions are a
copy, and the manifest's `code_key` is their version - into
`codes/<sha1(key)[:2]>.json.gz` (key -> command set and name) and
`codeset_devices/<codeset[:3]>.json.gz` (command set -> the models that use it). 1,771,049
of the archive's 2,214,024 commands are keyed, into 92,295 keys.

`device_match.suggest` looks up a dozen of a device's keys, ranks the command sets by how
many of them each sends and, among equals, by how much a model's manufacturer, model and
type agree with the device's name - "Sony AV Receiver" finds Sony's receivers - and reads
the best few sets whole to count every command they send. On a tester's One: the Vizio is a
Vizio E320i-A0 set (78 of 83 commands), the PS3 a Sony PlayStation 3 (69 of 69), the Sony
DVD a BDP-S590 set (43 of 43), the Roku a Roku Express 4K Plus (27 of 27).

A suggestion is offered, never applied: the Devices tab's "Find model" lists them, and the
model picked gives the device its manufacturer and model, and each command the import could
not name (`Command 1F`) the name that model's set gives it.
