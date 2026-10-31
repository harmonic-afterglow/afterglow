"""What earlier Afterglow releases sent for a command on the Harmony 1100.

The 1100 stores no protocol programs: a build renders every command into the press and
hold sequences the remote plays (`ssir_sequence`). Read back from the remote - which is
what importing an 1100's configuration does - those sequences are recordings, and a
project keeps them as recordings: replayed exactly, whatever the build that made them got
wrong. A tester's 900 devices, built for the 1100 by 0.3.0-beta.5 and imported again,
kept that release's bug through every later fix: Win+1 from an MCE keyboard never sent
the keyboard's "nothing held" frame, so it did nothing.

Each generation here is one way Afterglow has rendered a command, with the releases that
did it. A recording that is exactly what a generation renders from a protocol was made by
Afterglow from that protocol, and can become that protocol again - rendered afresh by the
current code, with every fix since. Nothing else is touched: the match must be exact, so a
genuine recording (Logitech's own, or a learned code) never matches.

When a fix changes how the 1100 renders, the rendering it replaces is added here as a new
generation, and projects made with it are repaired the next time they are opened.
"""
from __future__ import annotations

from dataclasses import dataclass

from ... import ir_protocol

_MAX_VARIANTS = 4
_RELEASE_GAP_US = 40_000           # ssir_sequence's gap after a release ending on a mark


@dataclass(frozen=True)
class Generation:
    id: str
    releases: str                  # which Afterglow releases rendered this way
    sends_release: str             # "never", "silent" or "always"


GENERATIONS = (
    Generation("1100-render-press-only", "0.2.0-beta.2 to 0.3.0-beta.4", "never"),
    Generation("1100-render-silent-release", "0.3.0-beta.5", "silent"),
    Generation("1100-render-release", "0.3.0-beta.6 and later", "always"),
)


def _merged(pulses) -> list[int]:
    """Adjacent marks or spaces as one: how a stored sequence keeps them."""
    out: list[int] = []
    for pulse in pulses:
        if out and (out[-1] > 0) == (pulse > 0):
            out[-1] += pulse
        else:
            out.append(int(pulse))
    return out


def presses(signal: dict, library, generation: Generation) -> list[list[int]]:
    """The press, per toggle state, that `generation` rendered for `signal`."""
    variants: list[list[int]] = []
    state = None
    for _ in range(_MAX_VARIANTS):
        press, after = ir_protocol.render_transmission(signal, phase="press", state=state,
                                                       library=library)
        ir_protocol.render_transmission(signal, phase="hold", state=after, library=library)
        release, _ignored = ir_protocol.render_transmission(signal, phase="release",
                                                            state=after, library=library)
        pulses = list(press["pulses_us"]) if press else []
        tail = list(release["pulses_us"]) if release else []
        silent = tail and not any(pulse > 0 for pulse in tail)
        if tail and (generation.sends_release == "always"
                     or (generation.sends_release == "silent" and silent)):
            if tail[-1] > 0:
                tail.append(-_RELEASE_GAP_US)
            pulses += tail
        pulses = _merged(pulses)
        if variants and pulses == variants[0]:
            break
        variants.append(pulses)
        state = after
    return variants


def rendered_by(recording: dict, candidate: dict, library) -> Generation | None:
    """The generation whose rendering of `candidate` is exactly `recording`, if any."""
    pulses = recording.get("pulses_us")
    if recording.get("kind") != "waveform" or not pulses or candidate.get("kind") != "protocol":
        return None
    target = _merged(pulses)
    for generation in GENERATIONS:
        try:
            variants = presses(candidate, library, generation)
        except (LookupError, ValueError):
            return None
        if variants and variants[0] == target:
            return generation
    return None
