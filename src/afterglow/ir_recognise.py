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
(an RC5 toggle) is read with the state the recording shows, and sent with the state the
sender keeps: a recording is one press, its toggle whichever it was made with.

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
    period - measured more loosely, and the recording's very last space at least as
    long: the silence after a recording's last frame is no part of the code."""
    if len(actual) != len(expected):
        return False
    last = len(expected) - 1
    return all(_close(a, e, gap=(index == last or abs(e) > 10000))
               or (index == last and a < 0 and e < 0 and -a > -e)
               for index, (a, e) in enumerate(zip(actual, expected)))


class _Walk:
    """A cursor over a recording, reading a frame's bursts and fields from it.

    A bi-phase code (RC5, RC6) draws a bit as a mark and a space in either order, so two
    of its half-bits that meet are one pulse of the recording: a burst may take part of a
    pulse, and the next takes the rest (``used``, how much of the pulse at ``at`` is
    taken). With ``partial`` False every burst takes whole pulses."""

    def __init__(self, pulses: list[int], *, partial: bool = True):
        self.pulses, self.at, self.used, self.partial = pulses, 0, 0, partial

    def take(self, durations: list[int]) -> bool:
        saved = self.at, self.used
        for duration in durations:
            if self.at >= len(self.pulses):
                self.at, self.used = saved
                return False
            pulse = self.pulses[self.at]
            sign = -1 if pulse < 0 else 1
            rest = sign * (abs(pulse) - self.used)
            allowed = max(TOLERANCE_US, abs(duration) * TOLERANCE)
            if _close(rest, duration):
                self.at, self.used = self.at + 1, 0
            elif (self.partial and (pulse < 0) == (duration < 0)
                    and abs(rest) > abs(duration) + allowed):
                self.used += abs(duration)
            else:
                self.at, self.used = saved
                return False
        return True

    def symbol(self, alphabet: dict, bursts: dict) -> str | None:
        """The symbol of ``alphabet`` the recording has next, or None - one that ends
        where a pulse ends before one that ends inside it: NEC's 0 is the start of its 1,
        and only a bi-phase half-bit runs on into the next."""
        saved, inside = (self.at, self.used), None
        for value, burst in alphabet["symbols"].items():
            if self.take(list(bursts[burst])):
                if not self.used:
                    return value
                if inside is None:
                    inside = value, (self.at, self.used)
                self.at, self.used = saved
        if inside is None:
            return None
        self.at, self.used = inside[1]
        return inside[0]

    def end_frame(self) -> None:
        """Past the frame's padding to its period, if the recording goes on."""
        if self.at < len(self.pulses) and self.pulses[self.at] < 0:
            self.at, self.used = self.at + 1, 0


def _read_bits(walk: _Walk, alphabet: dict, bursts: dict, width: int) -> int | None:
    bits = []
    for _ in range(width):
        value = walk.symbol(alphabet, bursts)
        if value is None:
            return None
        bits.append(int(value))
    return int("".join(map(str, bits)), 2)


def _read_frame(spec: dict, frame: str, walk: _Walk, parameters: dict) -> bool:
    """Read one frame's fields into ``parameters``; False when the recording is not it.
    A toggle is read and let go: the render back tries both."""
    bursts, alphabets = spec["bursts"], spec["alphabets"]
    definitions = spec.get("parameters") or {}
    for segment in spec["frames"][frame]["segments"]:
        if "burst" in segment:
            if not walk.take(list(bursts[segment["burst"]])):
                return False
            continue
        alphabet = alphabets[segment.get("alphabet", next(iter(alphabets)))]
        if alphabet.get("bits_per_symbol", 1) != 1:
            return False
        if "state" in segment:
            if _read_bits(walk, alphabet, bursts, 1) is None:
                return False
            continue
        if "field" not in segment:
            return False                              # a constant: not tried
        name = segment["field"]
        width = segment.get("bits", definitions.get(name, {}).get("bits"))
        if not width:
            return False
        value = _read_bits(walk, alphabet, bursts, width)
        if value is None:
            return False
        if segment.get("order", "msb") == "lsb":
            value = int(format(value, f"0{width}b")[::-1], 2)
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
    walk.end_frame()
    return True


def _parameters(spec: dict, press: list[int]) -> dict | None:
    """The values a protocol's press frames read from the start of a recording."""
    walk, parameters = _Walk(press), {}
    for occurrence in (spec.get("transmission") or {}).get("press") or []:
        for _ in range(occurrence.get("count", 1)):
            if not _read_frame(spec, occurrence["frame"], walk, parameters):
                return None
    return parameters if parameters else None


def _states(spec: dict) -> list[dict]:
    """Every sender state a protocol may be in before a press: each toggle 0 or 1."""
    names = sorted(spec.get("state") or {})
    return [{name: count >> index & 1 for index, name in enumerate(names)}
            for count in range(1 << len(names))]


def _renders_back(spec: dict, parameters: dict, press: list[int],
                  repeat: list[int]) -> list[dict]:
    """The sender states before a press with which the protocol, with ``parameters``,
    renders the recording back: none when it does not."""
    out = []
    for state in _states(spec):
        try:
            pressed, after = ir_protocol.transmission(spec, parameters, "press", state=state)
            held, _after = ir_protocol.transmission(spec, parameters, "hold", state=after)
        except (KeyError, LookupError, ValueError):
            return []
        if not held:
            if not repeat and _same(press, pressed):
                out.append(state)
            continue
        if not any(_same(press, pressed + held * count) for count in range(MOST_REPEATS + 1)):
            continue
        if not repeat or (len(repeat) % len(held) == 0
                          and _same(repeat, held * (len(repeat) // len(held)))):
            out.append(state)
    return out


def _split(recording: dict) -> tuple[list[int], list[int]]:
    """A recording's press and its repeat."""
    pulses = list(recording["pulses_us"])
    sections = recording.get("sections") or {}
    intro = sections.get("intro_pulses", len(pulses)) if sections else len(pulses)
    return pulses[:intro], pulses[intro:intro + sections.get("repeat_pulses", 0)]


def recognise(signal: dict, library=None) -> dict | None:
    """The protocol command a waveform signal is, or None when no protocol in ``library``
    renders it back. The name is kept; the recording is not, as the protocol says it.

    A recording with an alternate - the 650's two recordings of a toggling code, one for
    each toggle - is a protocol with sender state whose one state renders the recording
    and whose other renders the alternate."""
    if signal.get("kind") != "waveform":
        return None
    if (signal.get("sections") or {}).get("release_pulses"):
        return None
    press, repeat = _split(signal)
    alternate = signal.get("alternate")
    if alternate is not None and (alternate.get("sections") or {}).get("release_pulses"):
        return None
    carrier = signal.get("carrier_hz") or 0
    # the narrowest protocol first: NEC1, whose address is checked by its inverted
    # copy, before extended NEC, which renders the same frame with a 16-bit address
    catalog = ir_protocol.catalog(library)
    narrowest = sorted(catalog, key=lambda pid: (sum(
        item.get("bits", 0) for item in (catalog[pid].get("parameters") or {}).values()), pid))
    for protocol_id in narrowest:
        spec = catalog[protocol_id]
        if alternate is not None and not spec.get("state"):
            continue
        modulation = spec.get("modulation") or {}
        expected = modulation.get("carrier_hz") or 0
        if bool(expected) != bool(carrier) or (
                expected and abs(carrier - expected) > expected * CARRIER_TOLERANCE):
            continue
        parameters = _parameters(spec, press)
        if parameters is None:
            continue
        states = _renders_back(spec, parameters, press, repeat)
        if not states:
            continue
        if alternate is not None:
            others = _renders_back(spec, parameters, *_split(alternate))
            if not any(state != other for state in states for other in others):
                continue
        return ir_signal.protocol_signal(
            protocol_id, parameters, name=signal.get("name", ""),
            provenance={"kind": "recognised-waveform", "protocol": protocol_id,
                        "source": (signal.get("provenance") or {}).get("kind", "")})
    return None


def repeated(signal: dict) -> dict | None:
    """The recording as one fixed waveform, when its press is its repeat sent a whole
    number of times: a tap sends the press, and a held key sends it again and again,
    which is the repeat over and over. None when it is not. Its alternate, the other
    toggle's recording, goes with it when it is so too, and is let go when not."""
    if signal.get("kind") != "waveform":
        return None

    def fixed(recording):
        sections = recording.get("sections") or {}
        if sections.get("release_pulses"):
            return None
        press, repeat = _split(recording)
        if not press or not repeat or len(press) % len(repeat):
            return None
        if not _same(press, repeat * (len(press) // len(repeat))):
            return None
        out = {key: value for key, value in recording.items() if key != "sections"}
        out["pulses_us"] = press
        return out
    out = fixed(signal)
    if out is None:
        return None
    alternate = fixed(signal["alternate"]) if signal.get("alternate") else None
    out.pop("alternate", None)
    if alternate is not None:
        out["alternate"] = alternate
    return out


# What separates a recording's frames: a space this long is a frame's padding, not a bit.
FRAME_GAP_US = 10000


def _frames(pulses: list[int], gap: int = FRAME_GAP_US) -> list[list[int]]:
    """A recording's frames, each with the space that ends it."""
    out, current = [], []
    for pulse in pulses:
        current.append(pulse)
        if pulse < 0 and -pulse >= gap:
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
    walk = _Walk(frame, partial=False)
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


# What separates a recorded code's frames when its shape is read: RCA's 8 ms between
# frames, a fan's 7 ms, but not the 4.5 ms of NEC's leader or the separator in the
# middle of a Samsung36 frame. The code index keeps FRAME_GAP_US, as the archive's copy
# of it does.
SHAPE_GAP_US = 6000
# A frame this short that carries no bits is a ditto: NEC's "still held" frame.
DITTO_PULSES = 6


def _body(frame: list[int]) -> list[int]:
    return frame[:-1] if frame and frame[-1] < 0 and -frame[-1] >= SHAPE_GAP_US else frame


def _levels(pairs: list[tuple[int, int]], groups: list[list[int]]):
    """The four symbols of a two-bit pulse-distance code (RC-MM's), when the pairs are
    one mark and spaces a whole number of steps apart, at most three steps: shortest
    first, a level the frame does not use put in its place. None when they are not."""
    if not 3 <= len(groups) <= 4:
        return None
    mark = round(sum(pairs[i][0] for i in range(len(pairs))) / len(pairs))
    if not all(_close(pair[0], mark) for pair in pairs) or mark < 0:
        return None
    spaces = sorted(round(sum(pairs[i][1] for i in group) / len(group)) for group in groups)
    spaces.reverse()                      # spaces are negative: shortest first
    step = min(abs(b - a) for a, b in zip(spaces, spaces[1:]))
    if step < 2 * TOLERANCE_US:
        return None
    base = abs(spaces[0])
    steps = [(abs(space) - base) / step for space in spaces]
    if any(abs(k - round(k)) > 0.15 or round(k) > 3 for k in steps):
        return None
    return [(mark, -(base + k * step)) for k in range(4)]


def _shapes(pairs: list[tuple[int, int]]):
    """``(the bit shapes, separator)`` of a frame's pairs: two shapes, shortest first, or
    the four of a two-bit code; and one pair in the middle with a longer space that
    splits the bits (a Samsung36's), as ``(index, pair)``, or None. None when the pairs
    are none of these."""
    groups: list[list[int]] = []
    for index, pair in enumerate(pairs):
        for group in groups:
            first = pairs[group[0]]
            if _close(pair[0], first[0]) and _close(pair[1], first[1]):
                group.append(index)
                break
        else:
            groups.append([index])
    levels = _levels(pairs, groups)
    if levels is not None:
        return levels, None
    separator = None
    if len(groups) == 3:
        lone = [group for group in groups if len(group) == 1]
        if len(lone) != 1 or lone[0][0] in (0, len(pairs) - 1):
            return None
        index = lone[0][0]
        groups.remove(lone[0])
        separator = index, pairs[index]
    elif len(groups) != 2:
        return None
    shapes = [tuple(round(sum(pairs[i][k] for i in group) / len(group)) for k in (0, 1))
              for group in groups]
    # shortest first, and of two as long (a pulse-width code's) the shorter mark
    shapes.sort(key=lambda shape: (abs(shape[0]) + abs(shape[1]), abs(shape[0])))
    if separator is not None:
        mark, space = separator[1]
        if (mark < 0 or not any(_close(mark, shape[0]) for shape in shapes)
                or abs(space) < 1.5 * max(abs(shape[1]) for shape in shapes)):
            return None
    return shapes, separator


def _shape(frame: list[int]) -> dict | None:
    """A frame's shape for a protocol of its own: its header, its bit shapes, a
    separator, its trailer - or an open end, its last bit's space the frame's gap - and
    how many bits; None when it is none of these. A header or trailer that is one of the
    bits is not one."""
    body = _body(frame)
    for header, trailer, open_end in ((2, 1, False), (1, 0, False), (2, 0, True),
                                      (0, 1, False), (0, 0, True)):
        rest = len(body) - header - trailer - open_end
        if rest < 16 or rest % 2:
            continue
        bits = body[header:header + rest]
        found = _shapes([(bits[i], bits[i + 1]) for i in range(0, rest, 2)])
        if found is None:
            continue
        shapes, separator = found
        width = len(shapes).bit_length() - 1
        marks_differ = len(shapes) == 2 and not _close(shapes[0][0], shapes[1][0])
        if header == 2 and any(_close(body[0], s[0]) and _close(body[1], s[1])
                               for s in shapes):
            continue
        if trailer and marks_differ and any(_close(body[-1], s[0]) for s in shapes):
            continue
        if open_end and (not marks_differ or body[-1] < 0
                         or not any(_close(body[-1], s[0]) for s in shapes)):
            continue
        return {"header": body[:header], "trailer": body[len(body) - trailer:] if trailer
                else [], "symbols": shapes, "separator": separator, "open": open_end,
                "width": width,
                "bits": (rest // 2 - (separator is not None)) * width + open_end}
    return None


def _same_shape(a: dict, b: dict) -> bool:
    def flat(shape):
        out = list(shape["header"]) + [p for s in shape["symbols"] for p in s]
        return out + list(shape["trailer"]) + list((shape["separator"] or (0, ()))[1])
    where = lambda shape: (shape["separator"] or (None,))[0]
    return (a["bits"] == b["bits"] and a["open"] == b["open"] and where(a) == where(b)
            and len(flat(a)) == len(flat(b))
            and all(_close(x, y) for x, y in zip(flat(a), flat(b))))


def _read(frame: list[int], shape: dict) -> list[int] | None:
    """The bits a frame of ``shape`` carries, first bit most significant: one value, or
    two either side of its separator."""
    walk = _Walk(frame, partial=False)
    if not walk.take(list(shape["header"])):
        return None
    values, value = [], 0
    separator, width = shape["separator"], shape["width"]
    pairs = (shape["bits"] - shape["open"]) // width + (separator is not None)
    for index in range(pairs):
        if separator and index == separator[0]:
            if not walk.take(list(separator[1])):
                return None
            values.append(value)
            value = 0
            continue
        for symbol, burst in enumerate(shape["symbols"]):
            if walk.take(list(burst)):
                value = value << width | symbol
                break
        else:
            return None
    if shape["open"]:
        if walk.at >= len(frame) or frame[walk.at] < 0:
            return None
        marks = [bit for bit, symbol in enumerate(shape["symbols"])
                 if _close(frame[walk.at], symbol[0])]
        if len(marks) != 1:
            return None
        value = value << 1 | marks[0]
        walk.at += 1
    elif not walk.take(list(shape["trailer"])):
        return None
    walk.end_frame()
    return values + [value] if walk.at == len(frame) else None


PHASES = ("press", "hold", "release")


def infer(signal: dict) -> tuple[dict, dict] | None:
    """A protocol of the recording's own frame shape, and the command in it: ``(protocol
    definition, protocol signal)``, each frame's bits a payload of its own, as Logitech's
    generic protocols store theirs (a Roku sends a different code while a key is held).
    A short frame with no bits is a ditto, the same each time (NEC's "still held"). A
    frame of the same bits behind a leader of its own is a frame of its own (an RCA's
    first, behind a 20 ms leader). The frames sent on release are frames of the same shape, padded to a period of their own.
    None when the frames are not one shape of header, bit shapes, separator and trailer
    and dittos, or the protocol does not render the recording back."""
    if signal.get("kind") != "waveform" or signal.get("alternate"):
        return None
    pulses = list(signal["pulses_us"])
    sections = signal.get("sections") or {}
    lengths = ([sections.get("intro_pulses", 0), sections.get("repeat_pulses", 0),
                sections.get("release_pulses", 0)] if sections else [len(pulses), 0, 0])
    recorded, at = {}, 0
    for phase, length in zip(PHASES, lengths):
        recorded[phase], at = pulses[at:at + length], at + length
    split = {phase: _frames(recorded[phase], SHAPE_GAP_US) for phase in PHASES}
    if not split["press"]:
        return None
    shape = _shape(split["press"][0])
    if shape is None:
        return None
    ditto = None
    # the leaders a data frame is sent behind: the first frame's, then any other
    leaders = [list(shape["header"])]
    periods = {"data": [], "ditto": [], "release": []}
    occurrences = {phase: [] for phase in PHASES}
    for phase in PHASES:
        for frame in split[phase]:
            other = _shape(frame)
            led = (other is not None and other["header"] and shape["header"]
                   and len(other["header"]) == len(shape["header"])
                   and _same_shape({**shape, "header": other["header"]}, other))
            values = _read(frame, shape)
            if values is not None and (other is None or _same_shape(shape, other)):
                kind = "release" if phase == "release" else "data"
                occurrences[phase].append((kind if kind == "release" else "data", values))
            elif led and phase != "release":
                number = next((number for number, leader in enumerate(leaders)
                               if len(leader) == len(other["header"]) and all(
                                   _close(a, b) for a, b in zip(leader, other["header"]))),
                              None)
                if number is None:
                    number = len(leaders)
                    leaders.append(list(other["header"]))
                    periods[f"data{number + 1}"] = []
                kind = "data" if number == 0 else f"data{number + 1}"
                values = _read(frame, {**shape, "header": leaders[number]})
                if values is None:
                    return None
                occurrences[phase].append((kind, values))
            elif (phase != "release" and len(_body(frame)) <= DITTO_PULSES
                  and _body(frame)[0] > 0):
                kind = "ditto"
                if ditto is None:
                    ditto = _body(frame)
                elif len(ditto) != len(_body(frame)) or not all(
                        _close(a, b) for a, b in zip(_body(frame), ditto)):
                    return None
                occurrences[phase].append(("ditto", None))
            else:
                return None
            if len(_body(frame)) < len(frame):
                periods[kind].append(sum(abs(pulse) for pulse in frame))
    if not periods["data"] or (ditto is not None and not periods["ditto"]):
        return None

    def period(values):
        return round(sorted(values)[len(values) // 2] / 100) * 100
    carrier = signal.get("carrier_hz")
    bits, width = shape["bits"], shape["width"]
    widths = ([shape["separator"][0] * width, bits - shape["separator"][0] * width]
              if shape["separator"] else [bits])
    fields = ["payload", "payload2"][:len(widths)]
    segments = [{"burst": "header"}] if shape["header"] else []
    for number, (field, size) in enumerate(zip(fields, widths)):
        if number:
            segments.append({"burst": "separator"})
        segments.append({"field": field, "bits": size, "order": "msb", "alphabet": "bits"})
    if shape["trailer"]:
        segments.append({"burst": "trailer"})
    names = (["zero", "one"] if width == 1
             else [f"symbol{number}" for number in range(len(shape["symbols"]))])
    bursts = {"header": list(shape["header"]), "trailer": list(shape["trailer"]),
              **{name: list(symbol) for name, symbol in zip(names, shape["symbols"])}}
    if shape["separator"]:
        bursts["separator"] = list(shape["separator"][1])
    if ditto is not None:
        bursts["ditto"] = list(ditto)
    for name in ("header", "trailer"):
        if not bursts[name]:
            del bursts[name]
    local = {field: {"bits": size} for field, size in zip(fields, widths)}
    frames = {"data": {"segments": segments, "parameters": local,
                       "minimum_period_us": period(periods["data"])}}
    # a frame sent on release that is padded to a period of its own is a frame of its own
    release_frame = "data"
    if periods["release"] and period(periods["release"]) != frames["data"][
            "minimum_period_us"]:
        release_frame = "release"
        frames["release"] = {"segments": segments, "parameters": local,
                             "minimum_period_us": period(periods["release"])}
    if ditto is not None:
        frames["ditto"] = {"segments": [{"burst": "ditto"}],
                           "minimum_period_us": period(periods["ditto"])}
    for number, leader in enumerate(leaders[1:], 2):
        bursts[f"header{number}"] = leader
        frames[f"data{number}"] = {
            "segments": [{"burst": f"header{number}"}] + segments[1:], "parameters": local,
            "minimum_period_us": period(periods[f"data{number}"] or periods["data"])}
    codes = [f"Code{number}" for number in range(len(widths))]
    data = {"frame": "data", "bind": dict(zip(fields, codes))}
    symbols = {format(number, f"0{width}b"): name for number, name in enumerate(names)}
    shape_definition = {
        "modulation": ({"kind": "carrier", "carrier_hz": round(carrier)} if carrier
                       else {"kind": "unmodulated"}),
        "parameters": {code: {"bits": size} for code, size in zip(codes, widths)},
        "bursts": bursts,
        "alphabets": {"bits": {"bits_per_symbol": width, "symbols": symbols}},
        "frames": frames,
        "transmission": {"press": [data],
                         "hold": [{"frame": "ditto"}] if ditto is not None else [data],
                         "release": []},
    }
    fingerprint = hashlib.sha256(json.dumps(shape_definition, sort_keys=True).encode()
                                 ).hexdigest()
    definition = {"schema": ir_protocol.SCHEMA, "id": f"recorded-{fingerprint[:12]}",
                  "name": f"Recorded {bits}-bit code",
                  **shape_definition,
                  "provenance": {"kind": "inferred-from-recording",
                                 "source": (signal.get("provenance") or {}).get("kind", "")}}

    def sequence(items, release=False):
        out = []
        for frame, values in items:
            if values is None:
                out.append({"frame": "ditto"})
                continue
            out.append({"frame": release_frame if release else frame, "arguments": {
                field: f"0x{value:0{(size + 3) // 4}X}"
                for field, size, value in zip(fields, widths, values)}})
        return out
    command = ir_signal.protocol_signal(
        definition["id"], {}, name=signal.get("name", ""),
        transmission={"press": sequence(occurrences["press"]),
                      "hold": sequence(occurrences["hold"]),
                      "release": sequence(occurrences["release"], release=True)},
        provenance={"kind": "recognised-waveform", "protocol": definition["id"],
                    "source": (signal.get("provenance") or {}).get("kind", "")})
    try:
        ir_protocol.validate(definition)
        library = {definition["id"]: definition}
        for phase in PHASES:
            if not recorded[phase]:
                continue
            rendered = ir_protocol.render_transmission(command, phase=phase,
                                                       library=library)[0]
            if rendered is None or not _same(recorded[phase], rendered["pulses_us"]):
                return None
    except (KeyError, LookupError, ValueError):
        return None
    return definition, command


# The width of a header class: Logitech's recordings draw NEC's 9000 us leader 8990.
HEADER_CLASS_US = 250


def fingerprint(pulses: list[int]) -> str | None:
    """A command's first frame as the IR archive's code index keys it (docs/ir-
    recognition.md, "The code index"): its header's first mark in classes of 250 us, how
    many bits it carries and their value, as ``"<class>-<bits>-<hex>"``. Two renderings
    of one code - Logitech's recording, the archive's Pronto - give one key; a frame that
    is not a header, two bit shapes and a trailer is keyed by its pairs instead
    (`_symbols_key`), and one that is neither gives None."""
    frames = _frames(list(pulses))
    for frame in frames:
        layout = _layout(frame)
        if layout is None:
            continue
        value = _payload(frame, layout)
        if value is None:
            continue
        header = abs(layout["header"][0]) if layout["header"] else 0
        return f"{round(header / HEADER_CLASS_US)}-{layout['bits']}-{value:x}"
    for frame in frames:
        key = _symbols_key(frame)
        if key:
            return key
    return None


# How many kinds of pair, and how few pairs, a frame keyed by its pairs may have.
MOST_SYMBOLS, FEWEST_PAIRS = 8, 8


def _symbols_key(frame: list[int]) -> str | None:
    """A frame the key above cannot read - bits split by a longer space (Samsung's
    36-bit, the Flirc's), bi-phase (RC5, RC6), spaces of four lengths (XMP) - keyed by
    its (mark, space) pairs: a header when its mark is longer than any other, then each
    pair as the rank of its kind, the kinds ordered by length: ``"g<header class>-<pairs>-
    <ranks>"``. The "g" keeps it from ever being a key the rules above give, so an index
    built before it reads the same. None for a frame of too few pairs or too many kinds."""
    body = frame[:-1] if frame and frame[-1] < 0 and -frame[-1] >= FRAME_GAP_US else frame
    if not body or body[0] < 0:
        return None
    if len(body) % 2:                      # the last mark, its space the frame's gap
        body = body + [-1]
    pairs = [(body[i], body[i + 1]) for i in range(0, len(body), 2)]
    if any(mark < 0 or space > 0 for mark, space in pairs):
        return None
    header = 0
    if len(pairs) > 1 and all(pairs[0][0] > 1.5 * mark for mark, _space in pairs[1:]):
        header = pairs[0][0]
        pairs = pairs[1:]
    if len(pairs) < FEWEST_PAIRS:
        return None
    kinds: list[list[tuple[int, int]]] = []
    of = []
    for pair in pairs:
        for number, kind in enumerate(kinds):
            if _close(pair[0], kind[0][0]) and _close(pair[1], kind[0][1]):
                kind.append(pair)
                of.append(number)
                break
        else:
            kinds.append([pair])
            of.append(len(kinds) - 1)
    if len(kinds) > MOST_SYMBOLS:
        return None
    means = [(sum(m for m, _s in kind) / len(kind), sum(-s for _m, s in kind) / len(kind))
             for kind in kinds]
    order = sorted(range(len(kinds)), key=lambda k: (means[k][0] + means[k][1], means[k][0]))
    rank = {kind: place for place, kind in enumerate(order)}
    ranks = "".join(str(rank[number]) for number in of)
    return f"g{round(header / HEADER_CLASS_US)}-{len(pairs)}-{ranks}"
