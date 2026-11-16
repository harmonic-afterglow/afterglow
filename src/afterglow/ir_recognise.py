"""Recognise a recorded waveform as a protocol command: which protocol, with which values.

A remote that stores what it sends as recordings - the Harmony One, and the 650 and 700
that share its format - keeps a command as its press and the frame it repeats while held.
Logitech rendered those recordings from its protocols, so most of them are a protocol
command written out. A remote that sends protocols instead (the 900) cannot keep a press
and a separate repeat as one recording, but it can send the protocol.

Recognition is by synthesis, never by resemblance: a protocol's frame is walked over the
recording to read its fields, and the command is accepted only when that protocol,
rendered with those values, gives the recording back - its press followed by any number
of repeats, then its repeat - within a measuring tolerance. A protocol with sender state
(an RC5 toggle) is not tried: one recording cannot show the state it was made in.

Format reference: docs/ir-recognition.md
"""
from __future__ import annotations

import hashlib
import json

from . import ir_protocol, ir_signal

# How far a duration may be from the protocol's and still be it: Logitech renders its
# own timings ("8990" for NEC's 9000), and a period's padding is what is left of it.
TOLERANCE = 0.10
TOLERANCE_US = 80
GAP_TOLERANCE = 0.20
# How far the carrier may be: 38001 Hz is NEC's 38000.
CARRIER_TOLERANCE = 0.05
# A press is its own frames and then this many repeats at most - a tap that holds the
# repeat a little, as Logitech's do (a Sony command four frames long).
MOST_REPEATS = 8


def _close(actual: int, expected: int, *, gap: bool = False) -> bool:
    if (actual < 0) != (expected < 0):
        return False
    allowed = max(TOLERANCE_US, abs(expected) * (GAP_TOLERANCE if gap else TOLERANCE))
    return abs(abs(actual) - abs(expected)) <= allowed


def _same(actual: list[int], expected: list[int]) -> bool:
    """Whether two pulse trains are the same, a frame's last space - its padding to the
    period - measured more loosely."""
    if len(actual) != len(expected):
        return False
    return all(_close(a, e, gap=(index == len(expected) - 1 or abs(e) > 10000))
               for index, (a, e) in enumerate(zip(actual, expected)))


class _Walk:
    """A cursor over a recording, reading a frame's bursts and fields from it."""

    def __init__(self, pulses: list[int]):
        self.pulses, self.at = pulses, 0

    def take(self, durations: list[int]) -> bool:
        if self.at + len(durations) > len(self.pulses):
            return False
        if not all(_close(self.pulses[self.at + i], d) for i, d in enumerate(durations)):
            return False
        self.at += len(durations)
        return True

    def symbol(self, alphabet: dict, bursts: dict) -> str | None:
        """The symbol of ``alphabet`` the recording has next, or None."""
        for value, burst in alphabet["symbols"].items():
            if self.take(list(bursts[burst])):
                return value
        return None


def _read_frame(spec: dict, frame: str, walk: _Walk, parameters: dict) -> bool:
    """Read one frame's fields into ``parameters``; False when the recording is not it."""
    bursts, alphabets = spec["bursts"], spec["alphabets"]
    definitions = spec.get("parameters") or {}
    for segment in spec["frames"][frame]["segments"]:
        if "burst" in segment:
            if not walk.take(list(bursts[segment["burst"]])):
                return False
            continue
        if "field" not in segment:
            return False                              # sender state: not tried
        name = segment["field"]
        width = segment.get("bits", definitions.get(name, {}).get("bits"))
        alphabet = alphabets[segment.get("alphabet", next(iter(alphabets)))]
        if not width or alphabet.get("bits_per_symbol", 1) != 1:
            return False
        bits = []
        for _ in range(width):
            value = walk.symbol(alphabet, bursts)
            if value is None:
                return False
            bits.append(int(value))
        if segment.get("order", "msb") == "lsb":
            bits.reverse()
        value = int("".join(map(str, bits)), 2)
        if segment.get("transform") == "invert":
            value = ~value & ((1 << width) - 1)
        elif segment.get("transform"):
            return False
        # the first occurrence says the value; a repeat of it (NEC's inverted copy) is
        # checked when the whole command is rendered back
        current = parameters.get(name, 0)
        offset = segment.get("offset", 0)
        if name not in parameters or not (current >> offset) & ((1 << width) - 1):
            parameters[name] = current | value << offset
    # the frame's padding to its period, if the recording goes on
    if walk.at < len(walk.pulses) and walk.pulses[walk.at] < 0:
        walk.at += 1
    return True


def _parameters(spec: dict, press: list[int]) -> dict | None:
    """The values a protocol's press frames read from the start of a recording."""
    walk, parameters = _Walk(press), {}
    for occurrence in (spec.get("transmission") or {}).get("press") or []:
        for _ in range(occurrence.get("count", 1)):
            if not _read_frame(spec, occurrence["frame"], walk, parameters):
                return None
    return parameters if parameters else None


def _renders_back(spec: dict, parameters: dict, press: list[int], repeat: list[int]) -> bool:
    try:
        pressed, _state = ir_protocol.transmission(spec, parameters, "press")
        held, _state = ir_protocol.transmission(spec, parameters, "hold")
    except (KeyError, LookupError, ValueError):
        return False
    if not held:
        return not repeat and _same(press, pressed)
    if not any(_same(press, pressed + held * count) for count in range(MOST_REPEATS + 1)):
        return False
    if not repeat:
        return True
    return len(repeat) % len(held) == 0 and _same(repeat, held * (len(repeat) // len(held)))


def recognise(signal: dict, library=None) -> dict | None:
    """The protocol command a waveform signal is, or None when no protocol in ``library``
    renders it back. The name is kept; the recording is not, as the protocol says it."""
    if signal.get("kind") != "waveform" or signal.get("alternate"):
        return None
    pulses = list(signal["pulses_us"])
    sections = signal.get("sections") or {}
    if sections.get("release_pulses"):
        return None
    intro = sections.get("intro_pulses", len(pulses)) if sections else len(pulses)
    press, repeat = pulses[:intro], pulses[intro:intro + sections.get("repeat_pulses", 0)]
    carrier = signal.get("carrier_hz") or 0
    # the narrowest protocol first: NEC1, whose address is checked by its inverted
    # copy, before extended NEC, which renders the same frame with a 16-bit address
    catalog = ir_protocol.catalog(library)
    narrowest = sorted(catalog, key=lambda pid: (sum(
        item.get("bits", 0) for item in (catalog[pid].get("parameters") or {}).values()), pid))
    for protocol_id in narrowest:
        spec = catalog[protocol_id]
        if spec.get("state"):
            continue
        modulation = spec.get("modulation") or {}
        expected = modulation.get("carrier_hz") or 0
        if bool(expected) != bool(carrier) or (
                expected and abs(carrier - expected) > expected * CARRIER_TOLERANCE):
            continue
        parameters = _parameters(spec, press)
        if parameters is None or not _renders_back(spec, parameters, press, repeat):
            continue
        return ir_signal.protocol_signal(
            protocol_id, parameters, name=signal.get("name", ""),
            provenance={"kind": "recognised-waveform", "protocol": protocol_id,
                        "source": (signal.get("provenance") or {}).get("kind", "")})
    return None


# What separates a recording's frames: a space this long is a frame's padding, not a bit.
FRAME_GAP_US = 10000


def _frames(pulses: list[int]) -> list[list[int]]:
    """A recording's frames, each with the space that ends it."""
    out, current = [], []
    for pulse in pulses:
        current.append(pulse)
        if pulse < 0 and -pulse >= FRAME_GAP_US:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def _group(pairs: list[tuple[int, int]]) -> list[tuple[int, int]] | None:
    """The two shapes a frame's bits are drawn in, shortest first, each the mean of the
    pairs that are it; None when the pairs are not two shapes."""
    groups: list[list[tuple[int, int]]] = []
    for pair in pairs:
        for group in groups:
            if _close(pair[0], group[0][0]) and _close(pair[1], group[0][1]):
                group.append(pair)
                break
        else:
            groups.append([pair])
    if len(groups) != 2:
        return None
    shapes = [tuple(round(sum(item[i] for item in group) / len(group)) for i in (0, 1))
              for group in groups]
    return sorted(shapes, key=lambda shape: abs(shape[0]) + abs(shape[1]))


def _layout(frame: list[int]) -> dict | None:
    """A frame's shape: its header, the two bit shapes, its trailer and how many bits,
    as a pulse-distance (mark, space - NEC) or pulse-width (space, mark after a leading
    mark - Sony) code is drawn; None when it is neither."""
    body = frame[:-1] if frame and frame[-1] < 0 and -frame[-1] >= FRAME_GAP_US else frame
    for header, trailer in ((2, 1), (1, 0)):
        bits = body[header:len(body) - trailer]
        if len(bits) < 8 or len(bits) % 2:
            continue
        shapes = _group([(bits[i], bits[i + 1]) for i in range(0, len(bits), 2)])
        if shapes is None:
            continue
        return {"header": body[:header], "trailer": body[len(body) - trailer:],
                "symbols": shapes, "bits": len(bits) // 2}
    return None


def _payload(frame: list[int], layout: dict) -> int | None:
    """The bits a frame of ``layout`` carries, first bit most significant."""
    walk = _Walk(frame)
    if not walk.take(list(layout["header"])):
        return None
    value = 0
    for _ in range(layout["bits"]):
        for bit, shape in enumerate(layout["symbols"]):
            if walk.take(list(shape)):
                value = value << 1 | bit
                break
        else:
            return None
    return value if walk.take(list(layout["trailer"])) else None


def _same_layout(a: dict, b: dict) -> bool:
    flat = lambda layout: (list(layout["header"]) + [p for s in layout["symbols"] for p in s]
                           + list(layout["trailer"]))
    return (a["bits"] == b["bits"] and len(flat(a)) == len(flat(b))
            and all(_close(x, y) for x, y in zip(flat(a), flat(b))))


def infer(signal: dict) -> tuple[dict, dict] | None:
    """A protocol of the recording's own frame shape, and the command in it: ``(protocol
    definition, protocol signal)``, each frame's bits a payload of its own, as Logitech's
    generic protocols store theirs (a Roku sends a different code while a key is held).
    None when the frames are not one shape of header, two bit shapes and trailer, or the
    protocol does not render the recording back."""
    if signal.get("kind") != "waveform" or signal.get("alternate"):
        return None
    pulses = list(signal["pulses_us"])
    sections = signal.get("sections") or {}
    if sections.get("release_pulses"):
        return None
    intro = sections.get("intro_pulses", len(pulses)) if sections else len(pulses)
    press, repeat = pulses[:intro], pulses[intro:intro + sections.get("repeat_pulses", 0)]
    pressed, held = _frames(press), _frames(repeat)
    if not pressed:
        return None
    layout = _layout(pressed[0])
    if layout is None:
        return None
    periods, payloads = [], {"press": [], "hold": []}
    for phase, frames in (("press", pressed), ("hold", held)):
        for frame in frames:
            other = _layout(frame)
            value = _payload(frame, layout)
            if value is None or (other is not None and not _same_layout(layout, other)):
                return None
            payloads[phase].append(value)
            if frame[-1] < 0 and -frame[-1] >= FRAME_GAP_US:
                periods.append(sum(abs(pulse) for pulse in frame))
    if not periods:
        return None
    period = round(sorted(periods)[len(periods) // 2] / 100) * 100
    carrier = signal.get("carrier_hz")
    bits = layout["bits"]
    segments = [{"burst": "header"}] if layout["header"] else []
    segments.append({"field": "payload", "bits": bits, "order": "msb", "alphabet": "bits"})
    if layout["trailer"]:
        segments.append({"burst": "trailer"})
    shape = {
        "modulation": ({"kind": "carrier", "carrier_hz": round(carrier)} if carrier
                       else {"kind": "unmodulated"}),
        "parameters": {"Code0": {"bits": bits}},
        "bursts": {"header": list(layout["header"]), "trailer": list(layout["trailer"]),
                   "zero": list(layout["symbols"][0]), "one": list(layout["symbols"][1])},
        "alphabets": {"bits": {"bits_per_symbol": 1, "symbols": {"0": "zero", "1": "one"}}},
        "frames": {"data": {"segments": segments, "parameters": {"payload": {"bits": bits}},
                            "minimum_period_us": period}},
        "transmission": {"press": [{"frame": "data", "bind": {"payload": "Code0"}}],
                         "hold": [{"frame": "data", "bind": {"payload": "Code0"}}],
                         "release": []},
    }
    if not layout["header"]:
        del shape["bursts"]["header"]
    if not layout["trailer"]:
        del shape["bursts"]["trailer"]
    fingerprint = hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()
    definition = {"schema": ir_protocol.SCHEMA, "id": f"recorded-{fingerprint[:12]}",
                  "name": f"Recorded {bits}-bit code",
                  **shape,
                  "provenance": {"kind": "inferred-from-recording",
                                 "source": (signal.get("provenance") or {}).get("kind", "")}}
    hexes = (bits + 3) // 4

    def occurrences(values):
        return [{"frame": "data", "arguments": {"payload": f"0x{value:0{hexes}X}"}}
                for value in values]
    command = ir_signal.protocol_signal(
        definition["id"], {}, name=signal.get("name", ""),
        transmission={"press": occurrences(payloads["press"]),
                      "hold": occurrences(payloads["hold"]), "release": []},
        provenance={"kind": "recognised-waveform", "protocol": definition["id"],
                    "source": (signal.get("provenance") or {}).get("kind", "")})
    try:
        ir_protocol.validate(definition)
        library = {definition["id"]: definition}
        rendered = ir_protocol.render_transmission(command, phase="press", library=library)[0]
        again = (ir_protocol.render_transmission(command, phase="hold", library=library)[0]
                 if payloads["hold"] else None)
    except (KeyError, LookupError, ValueError):
        return None
    if rendered is None or not _same(press, rendered["pulses_us"]):
        return None
    if repeat and (again is None or not _same(repeat, again["pulses_us"])):
        return None
    return definition, command
