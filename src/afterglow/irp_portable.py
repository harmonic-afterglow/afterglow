"""An IRP definition as a portable protocol: what a remote that sends protocols can keep.

`irp.py` renders a command to a recording - its intro, the part repeated while a key is
held, and its ending. A remote that stores recordings (the One, the 650 and 700, the 800,
the 1100) plays that as it is. A Harmony 900 keeps one fixed waveform per command and
plays it while the key is down, so a recording there loses a toggle that changes on
every press (RC6, MCE and RECS80 among them: a second press of the same key can read
as one long hold) and cannot send at all what a protocol sends when the key is let go
(Blaupunkt, Nokia's NRC16 and NRC17). What the 900 can send is a protocol: its own
generic element plays a portable definition, toggle and release included.

So this compiles an IRP definition into one (`ir_protocol`'s afterglow-ir-protocol/1):
- each pass of the IRP stream is a frame: its intro the press, its repeated part the
  hold, its ending the release; an extent (``^108m``) that ends a pass is the frame's
  period;
- a bit field of constants is drawn into the frame as it is; one of the command's values,
  or of an expression over them (``~F``, ``D^S^F``), is a parameter of the definition,
  named for the field, that the command carries already worked out;
- a one-bit field of a persistent variable that the stream turns over (``T:1`` with
  ``T=1-T``) is the definition's toggle.

Anything else - an extent inside a pass, an assignment other than the toggle's, a field
inside a symbol, a field over the toggle - is not compiled, and the command stays a
recording. Nothing is trusted on shape alone: a definition is used only when it renders,
for both toggle values, exactly what `irp.render` does for the same command.
"""
from __future__ import annotations

import hashlib
import json
import math

from . import ir_protocol, ir_signal, irp
from .irp import Bitfield, Assignment, IrpError, _Empty, _Env, _Renderer

# How far a compiled duration may be from the IRP's: both round to a microsecond, at
# different points (one per burst, one per merged run).
TOLERANCE_US = 3

# What has been compiled, by definition id: a command's signal names its definition,
# and the device that holds the command carries it (`definitions_for`).
_COMPILED: dict[str, dict] = {}


class NotCompiled(IrpError):
    """An IRP construct no portable definition can hold; the command stays a recording."""


def _names(node, protocol, seen=frozenset()) -> set:
    """The parameter and variable names an expression depends on, through definitions."""
    if isinstance(node, str):
        if node in protocol.definitions and node not in seen:
            return _names(protocol.definitions[node], protocol, seen | {node})
        return set() if node in irp._CONSTANTS else {node}
    if isinstance(node, tuple):
        out = set()
        for part in node[1:]:
            out |= _names(part, protocol, seen)
        return out
    return set()


class _Frames:
    """One section's frames as they are drawn: bursts, fields and a closing period."""

    def __init__(self, compiler, *, symbol: bool = False):
        self.compiler = compiler
        self.symbol = symbol              # a symbol keeps a gap it starts with
        self.frames: list[tuple] = []
        self.segments: list = []          # ("burst", [durations]) or ("field", {...})
        self.period = None
        self.dropped = 0.0                # a leading gap left out, still in the period

    # the renderer's output interface -------------------------------------------------
    def flash(self, us: float):
        self._duration(abs(us))

    def gap(self, us: float):
        self._duration(-abs(us))

    def extent(self, us: float):
        # an extent ends a frame: what follows it in the same pass is the next frame
        # (Denon's repeat is two frames, each ^67m)
        self.period = us
        self.close()

    def _duration(self, us: float):
        if us == 0:
            return
        if self.segments and self.segments[-1][0] == "burst":
            burst = self.segments[-1][1]
            if (burst[-1] > 0) == (us > 0):
                burst[-1] += us
            else:
                burst.append(us)
        elif not self.segments and us < 0 and not self.symbol:
            self.dropped += -us           # a frame never starts with a gap
            return
        else:
            self.segments.append(("burst", [us]))

    def field(self, segment: dict):
        self.segments.append(("field", segment))

    # frames ----------------------------------------------------------------------------
    def close(self):
        if self.segments:
            period = None if self.period is None else self.period - self.dropped
            self.frames.append(self.compiler.frame(self.segments, period))
        elif self.period is not None:
            raise NotCompiled("a frame of nothing but its period")
        self.segments, self.period, self.dropped = [], None, 0.0

    def kept(self):
        return (list(self.frames), [(kind, list(value) if kind == "burst" else value)
                                    for kind, value in self.segments], self.period,
                self.dropped)

    def restore(self, kept):
        self.frames, self.segments, self.period, self.dropped = kept


class _Compiler(_Renderer):
    def __init__(self, protocol, env):
        super().__init__(protocol, env)
        self.parts = {name: _Frames(self) for name in ("intro", "repeat", "ending")}
        self.bursts: dict[tuple, str] = {}
        self.alphabets: dict[int, tuple[str, int]] = {}
        self.alphabet_specs: dict[str, dict] = {}
        self.parameters: dict[str, int] = {}          # name -> bits
        self.values: dict[str, int] = {}              # name -> this command's value
        self.field_keys: dict[str, str] = {}          # expression key -> name
        self.toggles: set[str] = set()
        self.assigned: set[str] = set()

    # names ---------------------------------------------------------------------------
    def burst(self, durations: list) -> str:
        key = tuple(int(round(d)) for d in durations)
        if not all(key):
            raise NotCompiled("a burst that rounds to nothing")
        if key not in self.bursts:
            self.bursts[key] = f"b{len(self.bursts)}"
        return self.bursts[key]

    def frame(self, segments: list, period) -> tuple:
        out = []
        for kind, value in segments:
            if kind == "burst":
                out.append((("burst", self.burst(value)),))
            else:
                out.append(tuple(sorted(value.items())))
        return tuple(out), (int(round(period)) if period is not None else None)

    def alphabet(self, bitspec: list, outer) -> tuple[str, int]:
        found = self.alphabets.get(id(bitspec))
        if found:
            return found
        chunk = max(1, int(round(math.log2(len(bitspec)))))
        if 1 << chunk != len(bitspec) or chunk > 8:
            raise NotCompiled(f"a bit specification of {len(bitspec)} symbols")
        name = "bits" if not self.alphabets else f"bits{len(self.alphabets) + 1}"
        symbols = {}
        for value, items in enumerate(bitspec):
            scratch = _Frames(self, symbol=True)
            key = f"_symbol{len(self.parts)}"
            section, self.parts[key] = self.section, scratch
            self.section = key
            try:
                self.items(items, outer)
            finally:
                self.section = section
                del self.parts[key]
            if scratch.period is not None or len(scratch.segments) != 1 \
                    or scratch.segments[0][0] != "burst":
                raise NotCompiled("a symbol that is not a plain burst")
            symbols[format(value, f"0{chunk}b")] = self.burst(scratch.segments[0][1])
        self.alphabets[id(bitspec)] = (name, chunk)
        self.alphabet_specs[name] = {"bits_per_symbol": chunk, "symbols": symbols}
        return name, chunk

    # the stream ----------------------------------------------------------------------
    def one_pass(self, items: list, bitspec):
        out = self.out
        out.close()
        kept = out.kept()
        values = dict(self.env.values)
        try:
            self.items(items, bitspec)
        except _Empty:
            out.restore(kept)
            self.env.values = values
            return
        out.close()

    def item(self, item, bitspec):
        if isinstance(item, Assignment):
            if item.name in self.protocol.persistent:
                self.toggles.add(item.name)            # turned over between presses
                return
            # a value the stream sets (XMP's T, CanalSat's) is known for this command;
            # a field over it is its own parameter wherever it is sent
            self.assigned.add(item.name)
        super().item(item, bitspec)

    def bitfields(self, fields: list, chain):
        if chain is None:
            raise NotCompiled("a bit field outside any bit specification")
        bitspec, outer = chain
        name, chunk = self.alphabet(bitspec, outer)
        constant: list[Bitfield] = []

        def flush():
            if constant:
                super(_Compiler, self).bitfields(list(constant), chain)
                constant.clear()

        for item in fields:
            depends = set()
            for part in (item.value, item.width, item.offset):
                depends |= _names(part, self.protocol)
            if not depends:
                constant.append(item)
                continue
            if _names(item.width, self.protocol) | _names(item.offset, self.protocol):
                raise NotCompiled("a field whose width depends on the command")
            width = int(self.env.eval(item.width))
            offset = int(self.env.eval(item.offset))
            if constant and sum(int(self.env.eval(c.width)) for c in constant) % chunk:
                raise NotCompiled("constant bits that split a symbol")
            flush()
            if width % chunk:
                raise NotCompiled(f"a {width}-bit field in {chunk}-bit symbols")
            order = "msb" if self.protocol.msb != item.reverse else "lsb"
            persistent = depends & self.protocol.persistent
            if persistent:
                if item.value not in self.protocol.persistent or width != 1 or offset:
                    raise NotCompiled("a field computed from the toggle")
                segment = {"state": item.value, "order": order, "alphabet": name}
                if item.complement:
                    segment["transform"] = "invert"
                self.out.field(segment)
                continue
            value = int(self.env.eval(item.value))
            bits = (value >> offset) & ((1 << width) - 1)
            if item.complement:
                bits = ~bits & ((1 << width) - 1)
            key = json.dumps([item.value, width, offset, item.complement], default=str)
            if depends & self.assigned:
                key += f"#{len(self.field_keys)}"
            field_name = self.field_keys.get(key)
            if field_name is None:
                field_name = self._field_name(item.value, item.complement)
                self.field_keys[key] = field_name
                self.parameters[field_name] = width
            self.values[field_name] = bits
            self.out.field({"field": field_name, "order": order, "alphabet": name})
        flush()

    def _field_name(self, value, complement: bool) -> str:
        base = value if isinstance(value, str) else "x"
        base = ("not_" if complement else "") + base
        name, number = base, 2
        while name in self.parameters:
            name, number = f"{base}{number}", number + 1
        return name


def _segments(frame) -> list[dict]:
    out = []
    for segment in frame:
        segment = dict(segment)
        if segment.get("alphabet") == "bits":
            del segment["alphabet"]
        out.append(segment)
    return out


def compile_command(entry: dict, values: dict) -> tuple[dict, dict]:
    """The portable definition for this IRP command, and the command's parameters for it.
    NotCompiled when the definition cannot hold it, or does not render it back."""
    protocol = irp.parse(entry["irp"])
    if protocol.carrier <= 0:
        raise NotCompiled("sent without a carrier")
    given = irp._defaults(protocol, values)
    compiler = _Compiler(protocol, _Env(protocol, given))
    try:
        compiler.stream(protocol.stream, None)
    except _Empty:
        pass
    for part in compiler.parts.values():
        part.close()
    intro, repeat, ending = (compiler.parts[name].frames
                             for name in ("intro", "repeat", "ending"))
    if not intro and not repeat:
        raise NotCompiled("nothing to send")
    # a persistent one-bit value is the sender's toggle, turned over between presses -
    # by the stream's own T=1-T, or left to the sender (RECS80, Velleman: T@ alone)
    used_state = {dict(segment).get("state") for frames in (intro, repeat, ending)
                  for frame, _period in frames for segment in frame} - {None}

    names: dict[tuple, str] = {}
    frames: dict[str, dict] = {}

    def frame_name(frame) -> str:
        if frame not in names:
            name = f"f{len(names)}"
            names[frame] = name
            body = {"segments": _segments(frame[0])}
            if frame[1] is not None:
                body["minimum_period_us"] = frame[1]
            frames[name] = body
        return names[frame]

    def phase(sequence) -> list[dict]:
        out: list[dict] = []
        for frame in sequence:
            name = frame_name(frame)
            if out and out[-1]["frame"] == name:
                out[-1]["count"] = out[-1].get("count", 1) + 1
            else:
                out.append({"frame": name})
        return out

    press = phase(intro or repeat)
    # a protocol with no repeated part sends its frames again while held, as the
    # recording does (irp._recording)
    hold = phase(repeat or intro)
    release = phase(ending)
    state = {}
    for name in sorted(used_state):
        first = given.get(name, 0) & 1
        # a portable toggle turns over before each press; the IRP's first press sends
        # its default, so it starts from the other value
        state[name] = {"kind": "toggle", "initial": first ^ 1, "advance": "press"}
    definition = {
        "schema": ir_protocol.SCHEMA,
        "name": f"{entry['name']} (IRP)",
        "modulation": {"kind": "carrier", "carrier_hz": int(round(protocol.carrier))},
        "parameters": {name: {"bits": bits}
                       for name, bits in sorted(compiler.parameters.items())},
        "bursts": {name: list(key) for key, name in compiler.bursts.items()},
        "alphabets": compiler.alphabet_specs,
        "frames": frames,
        "transmission": {"press": press, "hold": hold, "release": release},
    }
    if state:
        definition["state"] = state
    if not definition["alphabets"]:
        definition["alphabets"] = {"bits": {"bits_per_symbol": 1, "symbols": {
            "0": next(iter(definition["bursts"])), "1": next(iter(definition["bursts"]))}}}
    meaning = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
    slug = "".join(c if c.isalnum() else "-" for c in entry["name"].casefold()).strip("-")
    definition = {"schema": ir_protocol.SCHEMA,
                  "id": f"irp-{slug}-{hashlib.sha256(meaning).hexdigest()[:10]}",
                  **{k: v for k, v in definition.items() if k != "schema"},
                  "provenance": {"kind": "irp", "irp": entry["irp"],
                                 "source": "compiled from its IRP by irp_portable.py"}}
    parameters = dict(compiler.values)
    _check(definition, parameters, protocol, given, sorted(used_state))
    _COMPILED[definition["id"]] = definition
    return definition, parameters


def _same(ours: list[int], theirs: list[int]) -> bool:
    ours = [d for d in ours]
    theirs = [d for d in theirs]
    # the IRP renderer closes a frame that ends on a flash with a 1 us gap
    if theirs and theirs[-1] == -1 and (not ours or ours[-1] > 0):
        theirs = theirs[:-1]
    if len(ours) != len(theirs):
        return False
    # a period pads to what is left of it, so a frame's closing gap carries every
    # rounding before it (Nokia's 1p units: 6 us over a frame)
    return all((a > 0) == (b > 0) and abs(a - b) <= max(TOLERANCE_US, abs(b) * 0.002)
               for a, b in zip(ours, theirs))


def _check(definition: dict, parameters: dict, protocol, given: dict, toggles: list):
    """The definition renders this command as the IRP does, for each toggle value."""
    spec = ir_protocol.Protocol(definition)
    state = None
    for turn in range(2 if toggles else 1):
        values = dict(given)
        for name in toggles:
            values[name] = (given.get(name, 0) + turn) & 1
        expected = irp.render(protocol, values)
        press, state = spec.transmission(parameters, "press", state=state)
        hold, state = spec.transmission(parameters, "hold", state=state)
        release, state = spec.transmission(parameters, "release", state=state)
        intro = expected.intro or expected.repeat
        if not (_same(press, intro) and _same(hold, expected.repeat or expected.intro)
                and _same(release, expected.ending)):
            raise NotCompiled("the compiled definition does not render the IRP back")


def protocol_signal(entry: dict, values: dict, *, provenance: dict | None = None) -> dict:
    """A command as a protocol signal naming its compiled definition."""
    definition, parameters = compile_command(entry, values)
    return ir_signal.protocol_signal(
        definition["id"], parameters, name=entry["name"],
        provenance={**(provenance or {}), "irp": entry["name"],
                    "irp_parameters": dict(values)})


def definitions_for(signals) -> dict[str, dict]:
    """The compiled definitions these signals name, for the device that holds them."""
    out = {}
    for signal in signals:
        if isinstance(signal, dict) and signal.get("kind") == "protocol":
            found = _COMPILED.get(signal.get("protocol"))
            if found is not None:
                out[found["id"]] = found
    return out
