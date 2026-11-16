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
render is NEC1. A protocol with sender state (an RC5 toggle) is not tried: one recording
cannot show the state it was made in.

## The recording's own frame shape

A recording no library protocol renders back is read for its own shape: a header (a mark
and a space, or one mark), a run of bits each drawn in one of two shapes (mark then space -
pulse distance, NEC's - or space then mark after the header - pulse width, Sony's), an
optional trailing mark, and the frame's period. Each frame's bits become a payload, as
Logitech's generic protocols store theirs: a Roku sends a different code while its key is
held, which no library protocol says. The shape is a protocol of its own (`recorded-<hash>`)
added to the device, and accepted, as above, only when it renders the recording back.

On a tester's One (2026-11-16): the Vizio is NEC1 (83 commands), the Sony receiver Sony 12-
and 15-bit (59), the Sony DVD Sony 20-bit (43); the Roku (27) and a PS3 adapter (68) are
their own shapes. Built for a 900, every one of the 230 commands the One keeps a repeat
for replays as the One sent it, tapped and held.

## Where it is used

The 900/1100 builder (`harmony_pk.backend.lower_devices`) replaces each recording it
cannot store - a press and a different repeat - with the command it is, before lowering.
The project keeps the recordings: a project moved back to the One still has them.
