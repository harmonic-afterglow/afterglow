"""IRP notation: any protocol it describes, rendered to the pulses a remote sends.

IRDB names each command by a protocol and its numbers - `NECx1, 7, 7, 2` - in the names
DecodeIR and IrpTransmogrifier gave them, and those projects define each one in IRP
notation, e.g. NEC1: ``{38.4k,564}<1,-1|1,-3>(16,-8,D:8,S:8,F:8,~F:8,1,^108m,(16,-4,1,^108m)*)
[D:0..255,S:0..255=255-D,F:0..255]``. Mapping each name by hand left half of IRDB
unusable - its most common protocol, plain "NEC", among them. This renders the notation
itself, so every protocol with a definition (library/irp/protocols.json, made from
IrpTransmogrifier's IrpProtocols.xml by tools/irp_protocols.py) becomes a waveform any
remote can send: its intro, the part repeated while a key is held, and the ending.

The notation (http://www.hifi-remote.com/wiki/index.php/IRP_Notation):
  {general spec}  carrier ("38.4k"), unit in microseconds or carrier periods ("564",
                  "26p"), bit order ("lsb" by default, or "msb")
  <a|b|...>      a bit specification: what each symbol is; 2 alternatives are bits, 4
                  are two-bit symbols, and so on
  ( ... )        an IR stream; after it "*" repeats it while held, "+" sends it once and
                  repeats it, "3" sends it 3 times, "2+" twice and then repeats
  16, -8         a flash and a gap, in units, or with "u", "m" or "p" (microseconds,
                  milliseconds, carrier periods)
  ^108m          an extent: a gap that ends the frame 108 ms after it began
  F:8, ~F:8, F:4:4, F:-6
                 a bit field: 8 bits of F, complemented, 4 bits from bit 4, 6 bits in
                  the other order
  T=1-T          an assignment (a toggle that changes each press)
  [a][b][c]      a variation: a in the intro, b in the repeat, c in the ending
  {C=...}        definitions after the stream; [D:0..255,S:0..255=255-D] parameters,
                  with defaults
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import paths

DEFAULT_CARRIER = 38000
DEFAULT_UNIT = 1.0


class IrpError(ValueError):
    """An IRP that cannot be read, or parameters it cannot render."""


# --- reading ----------------------------------------------------------------------------

_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<number>0x[0-9a-fA-F]+|0b[01]+|\d+(?:\.\d+)?|\.\d+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\*\*|<<|>>|<=|>=|==|!=|&&|\|\||::|\.\.|[{}()<>\[\]|,:;~^=+\-*/%&!#?@])
""", re.X)


def _tokens(text: str) -> list[tuple[str, str]]:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)      # a comment, as Replay's
    out, at = [], 0
    while at < len(text):
        match = _TOKEN.match(text, at)
        if not match:
            raise IrpError(f"cannot read IRP at {text[at:at + 20]!r}")
        at = match.end()
        if match.lastgroup != "space":
            out.append((match.lastgroup, match.group()))
    return out


@dataclass
class Duration:
    kind: str                      # "flash", "gap" or "extent"
    value: object                  # an expression
    unit: str = ""                 # "", "u", "m" or "p"


@dataclass
class Bitfield:
    value: object
    width: object
    offset: object = 0
    complement: bool = False
    reverse: bool = False
    infinite: bool = False


@dataclass
class Assignment:
    name: str
    value: object


@dataclass
class Variation:
    alternatives: list


@dataclass
class Stream:
    items: list
    repeat: str = ""               # "", "*", "+", "3", "3+"
    bitspec: list | None = None    # alternatives, each a list of items


@dataclass
class Protocol:
    carrier: float
    unit: float
    unit_periods: bool
    msb: bool
    stream: Stream
    definitions: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)   # name -> (low, high, default expr)
    persistent: set = field(default_factory=set)


class _Reader:
    def __init__(self, text: str):
        self.tokens = _tokens(text)
        self.at = 0
        # inside a bit specification "|" separates its symbols, not an OR; inside the
        # first branch of "a ? b : c", ":" ends it, not a bit field
        self.in_bitspec = 0
        self.in_ternary = 0

    def peek(self, ahead: int = 0):
        index = self.at + ahead
        return self.tokens[index] if index < len(self.tokens) else (None, None)

    def take(self, expected: str | None = None):
        kind, value = self.peek()
        if kind is None or (expected is not None and value != expected):
            raise IrpError(f"expected {expected!r}, found {value!r}")
        self.at += 1
        return value

    def accept(self, value: str) -> bool:
        if self.peek()[1] == value:
            self.at += 1
            return True
        return False

    # general spec
    def general(self):
        carrier, unit, periods, msb = DEFAULT_CARRIER, DEFAULT_UNIT, False, False
        self.take("{")
        while not self.accept("}"):
            kind, value = self.peek()
            if value in ("lsb", "msb"):
                self.take()
                msb = value == "msb"
            elif kind == "number":
                number = _number(self.take())
                suffix = self.peek()[1]
                if suffix == "k":
                    self.take()
                    carrier = number * 1000
                elif suffix == "p":
                    self.take()
                    unit, periods = number, True
                elif suffix == "%":
                    self.take()
                elif suffix == "u":
                    self.take()
                    unit = number
                else:
                    unit = number
            else:
                raise IrpError(f"unknown general spec item {value!r}")
            self.accept(",")
        return carrier, unit, periods, msb

    # streams
    def bitspec(self) -> list:
        self.take("<")
        self.in_bitspec += 1
        try:
            alternatives = [self.bare_items(stop=("|", ">"))]
            while self.accept("|"):
                alternatives.append(self.bare_items(stop=("|", ">")))
        finally:
            self.in_bitspec -= 1
        self.take(">")
        return alternatives

    def stream(self, bitspec=None) -> Stream:
        self.take("(")
        outer, self.in_bitspec = self.in_bitspec, 0
        try:
            items = self.bare_items(stop=(")",))
        finally:
            self.in_bitspec = outer
        self.take(")")
        return Stream(items, self.repeat_marker(), bitspec)

    def repeat_marker(self) -> str:
        kind, value = self.peek()
        if value in ("*", "+"):
            self.take()
            return value
        if kind == "number" and "." not in value:
            self.take()
            return value + ("+" if self.accept("+") else "")
        return ""

    def bare_items(self, stop) -> list:
        items = []
        if self.peek()[1] in stop:
            return items
        while True:
            items.append(self.item())
            if not self.accept(","):
                return items

    def item(self):
        kind, value = self.peek()
        if value == "<":
            spec = self.bitspec()
            return self.stream(spec)
        if value == "[":
            alternatives = []
            while self.accept("["):
                alternatives.append(self.bare_items(stop=("]",)))
                self.take("]")
            return Variation(alternatives)
        if value == "^":
            self.take()
            return Duration("extent", *self.duration_value())
        if value == "-" and self.peek(1)[0] in ("number", "name") \
                and self.peek(2)[1] not in (":",):
            self.take()
            return Duration("gap", *self.duration_value())
        if value == "(" and not self._is_parenthesised_bitfield():
            return self.stream()
        if kind == "name" and self.peek(1)[1] == "=" and self.peek(2)[1] != "=":
            name = self.take()
            self.take("=")
            return Assignment(name, self.expression())
        complement = self.accept("~")
        primary = self.primary()
        if self.accept("::"):
            return Bitfield(primary, 0, self.primary(), complement, infinite=True)
        if self.accept(":"):
            reverse = self.accept("-")
            width = self.primary()
            offset = self.primary() if self.accept(":") else 0
            return Bitfield(primary, width, offset, complement, reverse)
        if complement:
            raise IrpError("a complement needs a bit field")
        unit = ""
        if self.peek()[1] in ("m", "u", "p") and self.peek()[0] == "name":
            unit = self.take()
        return Duration("flash", primary, unit)

    def _is_parenthesised_bitfield(self) -> bool:
        depth, index = 0, self.at
        while index < len(self.tokens):
            value = self.tokens[index][1]
            if value == "(":
                depth += 1
            elif value == ")":
                depth -= 1
                if depth == 0:
                    following = self.tokens[index + 1][1] if index + 1 < len(self.tokens) \
                        else None
                    return following in (":", "::")
            index += 1
        return False

    def duration_value(self):
        value = self.primary()
        unit = ""
        if self.peek()[0] == "name" and self.peek()[1] in ("m", "u", "p"):
            unit = self.take()
        return value, unit

    # expressions, C precedence
    BINARY = [("?",), ("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="),
              ("<", "<=", ">", ">="), ("<<", ">>"), ("+", "-"), ("*", "/", "%"), ("**",)]

    def expression(self, level: int = 0):
        if level == len(self.BINARY):
            return self.unary()
        if self.BINARY[level] == ("?",):
            condition = self.expression(level + 1)
            if self.accept("?"):
                self.in_ternary += 1
                try:
                    yes = self.expression(level)
                finally:
                    self.in_ternary -= 1
                self.take(":")
                no = self.expression(level)
                return ("?", condition, yes, no)
            return condition
        left = self.expression(level + 1)
        while self.peek()[1] in self.BINARY[level] and not (
                self.in_bitspec and self.peek()[1] in ("|", ">")):
            op = self.take()
            right = self.expression(level + 1 if op != "**" else level)
            left = (op, left, right)
        return left

    def unary(self):
        value = self.peek()[1]
        if value in ("-", "~", "!", "#"):
            self.take()
            return ("u" + value, self.unary())
        primary = self.primary()
        if self.in_ternary and self.peek()[1] == ":":
            return primary
        if self.peek()[1] in (":", "::") and self.peek(1)[0] in ("number", "name", None) \
                or (self.peek()[1] == ":" and self.peek(1)[1] in ("-", "(")):
            if self.accept("::"):
                return ("bits", primary, None, self.primary(), False)
            self.take(":")
            reverse = self.accept("-")
            width = self.primary()
            offset = self.primary() if self.accept(":") else 0
            return ("bits", primary, width, offset, reverse)
        return primary

    def primary(self):
        kind, value = self.peek()
        if kind == "number":
            return _number(self.take())
        if kind == "name":
            return self.take()
        if value == "(":
            self.take()
            inner = self.expression()
            self.take(")")
            return inner
        if value == "-":
            self.take()
            return ("u-", self.primary())
        raise IrpError(f"expected a value, found {value!r}")

    def definitions(self) -> dict:
        out = {}
        self.take("{")
        while not self.accept("}"):
            name = self.take()
            self.take("=")
            out[name] = self.expression()
            self.accept(",")
        return out

    def parameters(self) -> tuple[dict, set]:
        out, persistent = {}, set()
        self.take("[")
        while not self.accept("]"):
            name = self.take()
            if self.accept("@"):
                persistent.add(name)
            self.take(":")
            low = self.expression(level=len(self.BINARY) - 3)
            self.take("..")
            high = self.expression(level=len(self.BINARY) - 3)
            default = self.expression() if self.accept("=") else None
            out[name] = (low, high, default)
            self.accept(",")
        return out, persistent


def _number(text: str) -> float | int:
    if text.startswith(("0x", "0X")):
        return int(text, 16)
    if text.startswith(("0b", "0B")):
        return int(text, 2)
    return float(text) if "." in text else int(text)


@lru_cache(maxsize=512)
def parse(text: str) -> Protocol:
    """Read one protocol's IRP."""
    reader = _Reader(text.strip())
    carrier, unit, periods, msb = reader.general()
    bitspec = reader.bitspec()
    stream = reader.stream(bitspec)
    definitions: dict = {}
    parameters: dict = {}
    persistent: set = set()
    while reader.peek()[0] is not None:
        if reader.peek()[1] == "{":
            definitions.update(reader.definitions())
        elif reader.peek()[1] == "[":
            parameters, persistent = reader.parameters()
        else:
            raise IrpError(f"unexpected {reader.peek()[1]!r} after the IR stream")
    return Protocol(carrier, unit, periods, msb, stream, definitions, parameters, persistent)


# --- rendering --------------------------------------------------------------------------

# IrpTransmogrifier's named constants
_CONSTANTS = {"UINT8_MAX": 0xFF, "UINT16_MAX": 0xFFFF, "UINT24_MAX": 0xFFFFFF,
              "UINT32_MAX": 0xFFFFFFFF, "UINT64_MAX": 0xFFFFFFFFFFFFFFFF}


class _Empty(Exception):
    """An empty alternative of a variation: the pass it is in sends nothing at all."""


class _Env:
    def __init__(self, protocol: Protocol, values: dict):
        self.protocol = protocol
        self.values = dict(values)

    def get(self, name: str) -> int:
        if name in self.values:
            return self.values[name]
        if name in self.protocol.definitions:
            return int(self.eval(self.protocol.definitions[name]))
        if name in _CONSTANTS:
            return _CONSTANTS[name]
        raise IrpError(f"no value for {name!r}")

    def eval(self, node) -> float | int:
        if isinstance(node, (int, float)):
            return node
        if isinstance(node, str):
            return self.get(node)
        op = node[0]
        if op == "bits":
            _op, value, width, offset, reverse = node
            value = int(self.eval(value))
            offset = int(self.eval(offset))
            if width is None:
                return value >> offset
            width = int(self.eval(width))
            bits = (value >> offset) & ((1 << width) - 1)
            return _reversed(bits, width) if reverse else bits
        if op == "?":
            return self.eval(node[2]) if self.eval(node[1]) else self.eval(node[3])
        if op.startswith("u"):
            value = self.eval(node[1])
            return {"u-": lambda v: -v, "u~": lambda v: ~int(v), "u!": lambda v: int(not v),
                    "u#": lambda v: bin(int(v) & 0xFFFFFFFFFFFFFFFF).count("1")}[op](value)
        a, b = self.eval(node[1]), self.eval(node[2])
        if op in ("&&", "||"):
            return int(bool(a) and bool(b)) if op == "&&" else int(bool(a) or bool(b))
        a_int, b_int = int(a), int(b)
        return {
            "|": lambda: a_int | b_int, "^": lambda: a_int ^ b_int, "&": lambda: a_int & b_int,
            "==": lambda: int(a == b), "!=": lambda: int(a != b), "<": lambda: int(a < b),
            "<=": lambda: int(a <= b), ">": lambda: int(a > b), ">=": lambda: int(a >= b),
            "<<": lambda: a_int << b_int, ">>": lambda: a_int >> b_int,
            "+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b,
            "/": lambda: int(a / b) if b else 0, "%": lambda: a_int % b_int if b_int else 0,
            "**": lambda: a_int ** b_int,
        }[op]()


def _reversed(value: int, width: int) -> int:
    out = 0
    for _ in range(width):
        out = (out << 1) | (value & 1)
        value >>= 1
    return out


class _Out:
    """Durations as they go out: flashes and gaps merged, extents measured."""

    def __init__(self):
        self.durations: list[float] = []
        self.since_extent = 0.0

    def flash(self, us: float):
        self._add(abs(us))

    def gap(self, us: float):
        self._add(-abs(us))

    def _add(self, us: float):
        if us == 0:
            return
        self.since_extent += abs(us)
        if self.durations and (self.durations[-1] > 0) == (us > 0):
            self.durations[-1] += us
        elif not self.durations and us < 0:
            return                       # a stream never starts with a gap
        else:
            self.durations.append(us)

    def extent(self, us: float):
        self.gap(max(us - self.since_extent, 0) or 0)
        self.since_extent = 0.0


@dataclass
class Rendered:
    carrier_hz: int
    intro: list[int]
    repeat: list[int]
    ending: list[int]


class _Renderer:
    def __init__(self, protocol: Protocol, env: _Env):
        self.protocol = protocol
        self.env = env
        self.parts = {"intro": _Out(), "repeat": _Out(), "ending": _Out()}
        self.section = "intro"
        self.split = False

    @property
    def out(self) -> _Out:
        return self.parts[self.section]

    def micro(self, value: float, unit: str) -> float:
        if unit == "u":
            return value
        if unit == "m":
            return value * 1000
        period = 1e6 / self.protocol.carrier if self.protocol.carrier else 1
        if unit == "p":
            return value * period
        base = self.protocol.unit * (period if self.protocol.unit_periods else 1)
        return value * base

    def stream(self, stream: Stream, bitspec: tuple | None):
        # (symbols, the enclosing bitspec): a symbol is itself sent with the enclosing
        # one, as Sejin's and Zenith's are bit fields in <-1|1>
        if stream.bitspec is not None and (bitspec is None or stream.bitspec is not bitspec[0]):
            bitspec = (stream.bitspec, bitspec)
        marker = stream.repeat
        if marker in ("*", "+") or marker.endswith("+"):
            if self.split:
                raise IrpError("more than one repeated part")
            times = 1 if marker == "+" else int(marker[:-1]) if marker.endswith("+") \
                and marker != "+" else 0
            for _ in range(times):
                self.one_pass(stream.items, bitspec)
            self.split = True
            self.section = "repeat"
            self.one_pass(stream.items, bitspec)
            self.section = "ending"
            if any(isinstance(item, Variation) and len(item.alternatives) > 2
                   for item in stream.items):
                self.one_pass(stream.items, bitspec)
            return
        for _ in range(int(marker) if marker else 1):
            self.items(stream.items, bitspec)

    def one_pass(self, items: list, bitspec):
        """One pass of a repeated stream; one whose variation is empty for this section
        ([][T=0][T=1]: nothing first, then T=0 while held) sends nothing."""
        out = self.out
        kept = (list(out.durations), out.since_extent, dict(self.env.values))
        try:
            self.items(items, bitspec)
        except _Empty:
            out.durations, out.since_extent, self.env.values = \
                kept[0], kept[1], kept[2]

    def items(self, items: list, bitspec):
        # Bit fields in a row are one run of bits, cut into symbols as a whole: with
        # two-bit symbols a 1-bit field and the next are one symbol (Grundig16's T:1,F:8).
        run: list = []
        for item in items:
            if isinstance(item, Bitfield) and not item.infinite:
                run.append(item)
                continue
            if run:
                self.bitfields(run, bitspec)
                run = []
            self.item(item, bitspec)
        if run:
            self.bitfields(run, bitspec)

    def item(self, item, bitspec: list):
        if isinstance(item, Duration):
            value = float(self.env.eval(item.value))
            us = self.micro(value, item.unit)
            if item.kind == "extent":
                self.out.extent(us)
            elif item.kind == "gap" or value < 0:
                self.out.gap(us)
            else:
                self.out.flash(us)
        elif isinstance(item, Bitfield):
            self.bitfields([item], bitspec)
        elif isinstance(item, Assignment):
            self.env.values[item.name] = int(self.env.eval(item.value))
        elif isinstance(item, Variation):
            index = {"intro": 0, "repeat": 1, "ending": 2}[self.section]
            if index < len(item.alternatives):
                if not item.alternatives[index]:
                    raise _Empty
                self.items(item.alternatives[index], bitspec)
        elif isinstance(item, Stream):
            self.stream(item, bitspec)
        else:
            raise IrpError(f"cannot render {item!r}")

    def bitfields(self, fields: list, chain):
        """Bit fields in a row, as the bit specification's symbols."""
        if chain is None:
            raise IrpError("a bit field outside any bit specification")
        bitspec, outer = chain
        chunk = max(1, int(round(math.log2(len(bitspec)))))
        if 1 << chunk != len(bitspec):
            raise IrpError(f"a bit specification of {len(bitspec)} symbols")
        bits: list[int] = []
        for item in fields:
            value = int(self.env.eval(item.value))
            offset = int(self.env.eval(item.offset))
            width = int(self.env.eval(item.width))
            field = (value >> offset) & ((1 << width) - 1) if width > 0 else 0
            if item.complement:
                field = ~field & ((1 << width) - 1)
            # msb sends the highest bit first; a negative width turns the field round
            order = list(range(width - 1, -1, -1)) if self.protocol.msb != item.reverse \
                else list(range(width))
            bits += [(field >> bit) & 1 for bit in order]
        if len(bits) % chunk:
            raise IrpError(f"{len(bits)} bits in {chunk}-bit symbols")
        for at in range(0, len(bits), chunk):
            group = bits[at:at + chunk]
            symbol = 0
            # a symbol's first bit is its highest in msb order, its lowest in lsb
            for bit in (group if self.protocol.msb else reversed(group)):
                symbol = (symbol << 1) | bit
            self.items(bitspec[symbol], outer)


def _defaults(protocol: Protocol, values: dict) -> dict:
    out = {name: int(value) for name, value in values.items() if value is not None}
    pending = {name: spec for name, spec in protocol.parameters.items()
               if name not in out}
    for _ in range(len(pending) + 1):
        for name, (_low, _high, default) in list(pending.items()):
            if default is None:
                continue
            try:
                out[name] = int(_Env(protocol, out).eval(default))
            except IrpError:
                continue
            del pending[name]
    missing = [name for name, (_l, _h, default) in pending.items() if default is None]
    if missing:
        raise IrpError(f"no value for parameter(s) {', '.join(missing)}")
    for name, (low, high, _default) in protocol.parameters.items():
        env = _Env(protocol, out)
        if not env.eval(low) <= out[name] <= env.eval(high):
            raise IrpError(f"{name}={out[name]} is outside {env.eval(low)}..{env.eval(high)}")
    return out


def render(protocol: Protocol | str, values: dict) -> Rendered:
    """The protocol's intro, repeat and ending for these parameter values."""
    protocol = parse(protocol) if isinstance(protocol, str) else protocol
    env = _Env(protocol, _defaults(protocol, values))
    renderer = _Renderer(protocol, env)
    try:
        renderer.stream(protocol.stream, None)
    except _Empty:                  # outside any repeat: the frame is not sent
        pass
    values_out = env.values

    def pulses(out: _Out) -> list[int]:
        durations = [int(round(d)) for d in out.durations if round(d)]
        if durations and durations[-1] > 0:
            durations.append(-1)            # every frame ends with a gap
        return durations

    rendered = Rendered(int(round(protocol.carrier)), pulses(renderer.parts["intro"]),
                        pulses(renderer.parts["repeat"]), pulses(renderer.parts["ending"]))
    rendered.state = values_out
    return rendered


# --- the shipped definitions, and the names IRDB and Flipper give them ---------------

@lru_cache(maxsize=1)
def definitions() -> dict[str, dict]:
    """{name casefolded: {"name", "irp"}} for every protocol shipped, by name and by its
    other names."""
    data = json.loads(paths.library("irp", "protocols.json").read_text(encoding="utf-8"))
    out = {}
    for entry in data["protocols"]:
        for name in [entry["name"], *entry.get("other_names", [])]:
            out.setdefault(name.casefold(), entry)
    return out


@lru_cache(maxsize=1)
def source_names() -> dict:
    """The spellings IRDB and Flipper use that are not IrpTransmogrifier's own names:
    {source: {spelling: {"protocol" or "irp" and "name", "set"}}}
    (library/irp/source-names.json)."""
    return json.loads(paths.library("irp", "source-names.json").read_text(
        encoding="utf-8"))["sources"]


def resolve(source: str, name: str, given: dict) -> tuple[dict, dict]:
    """The definition a source's protocol name means, and the parameter values for it:
    ``given`` (IRDB's D, S and F; Flipper's address A and command C) with what the
    source's name sets (source-names.json). IrpError, saying why, when nothing defines
    it."""
    key = name.strip().casefold()
    alias = source_names().get(source, {}).get(key)
    if alias is not None and alias.get("refused"):
        raise IrpError(alias["refused"])
    if alias and alias.get("irp"):          # a source's own variant, defined where named
        entry = {"name": alias.get("name") or name.strip(), "irp": alias["irp"]}
    else:
        target = alias.get("protocol") if alias else name.strip()
        entry = definitions().get((target or "").casefold())
    if entry is None:
        raise IrpError(f"no IRP definition for {source} protocol {name!r}")
    values = {k: int(v) for k, v in given.items() if v is not None}
    for parameter, expression in ((alias or {}).get("set") or {}).items():
        reader = _Reader(str(expression))
        values[parameter] = int(_Env(parse(entry["irp"]), values).eval(reader.expression()))
    declared = set(parse(entry["irp"]).parameters)
    if source == "flipper":                      # the address and command were only read
        values = {k: v for k, v in values.items() if k in declared}
    return entry, values


def waveform_signal(entry: dict, values: dict, *, provenance: dict | None = None) -> dict:
    """A portable waveform signal for one command: intro, repeat and ending as its
    sections, and - for a protocol whose toggle changes each press - the other press
    as its alternate."""
    from . import ir_signal

    protocol = parse(entry["irp"])
    values = {k: v for k, v in values.items() if k in protocol.parameters}
    first = render(protocol, values)
    toggles = [name for name in protocol.persistent if name not in values]
    alternate = None
    if toggles:
        # the next press: what the stream turned it to, or the other value where the
        # stream leaves it to the sender (RECS80's T@ with no T=1-T)
        turned = {name: first.state[name] if first.state[name] != _start(protocol, name)
                  else 1 - first.state[name] for name in toggles}
        second = render(protocol, {**values, **turned})
        if (second.intro, second.repeat) != (first.intro, first.repeat):
            alternate = _recording(second)
    if first.carrier_hz <= 0:
        raise IrpError(f"sent without a carrier (0 kHz), which Afterglow's commands "
                       f"cannot hold")
    recording = _recording(first)
    if not recording["pulses_us"]:
        raise IrpError("the protocol renders no pulses")
    return ir_signal.waveform(
        recording["pulses_us"], carrier_hz=first.carrier_hz,
        sections=recording["sections"], alternate=alternate, name=entry["name"],
        provenance={**(provenance or {}), "irp": entry["name"], "parameters": values})


def _start(protocol: Protocol, name: str) -> int:
    default = protocol.parameters[name][2]
    return int(_Env(protocol, {}).eval(default)) if default is not None else 0


def _recording(rendered: Rendered) -> dict:
    intro, repeat, ending = rendered.intro, rendered.repeat, rendered.ending
    if not repeat:                   # a protocol with no repeated part sends its frame
        intro, repeat = [], intro    # again while held
    sections = {"intro_pulses": len(intro), "repeat_pulses": len(repeat)}
    if ending:
        sections["release_pulses"] = len(ending)
    return {"pulses_us": intro + repeat + ending, "sections": sections}
