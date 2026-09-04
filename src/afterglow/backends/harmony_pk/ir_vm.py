"""Execute the carrier-program subset of a PK-family ``IrProto`` payload.

This is a development oracle for the native protocol compiler, not an application
runtime.  The remote still executes Logitech's ``irgen`` binary.  We execute the same
five carrier routines in Python so a generated block can be checked against the
portable waveform before it is ever flashed.

The implementation follows ``attic/decompiled.c`` deliberately closely.  In particular,
the 30-byte element state retains the firmware's byte offsets and overloaded pointer at
``+8``.  Replacing that state with a tidier protocol-specific model would make NEC easy
while hiding precisely the RC6/RCMM behaviours this oracle is meant to catch.

Both levels are available: ``simulate_sequence`` isolates the first playable sequence,
while ``simulate_transmission`` follows the firmware's stage delimiters, minimum-repeat
byte and duration policy.  A physical key can be held indefinitely on the remote, so the
oracle represents that external state as an explicit finite number of extra replays.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log2


PROTOCOL_BASE = 5
MAX_GAP_US = 0x7FFF
STATE_SIZE = 0x1E


class IrVmError(ValueError):
    """The native program or command stream is invalid for the carrier VM."""


def _u16(data: bytes | bytearray, offset: int) -> int:
    try:
        return data[offset] | data[offset + 1] << 8
    except IndexError as exc:
        raise IrVmError(f"u16 read outside buffer at {offset}") from exc


def _u32(data: bytes | bytearray, offset: int) -> int:
    return _u16(data, offset) | _u16(data, offset + 2) << 16


def _set_u16(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 2] = int(value & 0xFFFF).to_bytes(2, "little")


def _set_u32(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 4] = int(value & 0xFFFFFFFF).to_bytes(4, "little")


def _code_bytes(code: str | bytes | bytearray) -> bytes:
    if isinstance(code, (bytes, bytearray)):
        return bytes(code)
    text = code.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise IrVmError(f"invalid native Code {code!r}") from exc


@dataclass(frozen=True)
class Simulation:
    """Native carrier output plus the sequence boundaries that produced it."""

    carrier_hz: int
    pulses_us: tuple[int, ...]
    words: tuple[int, ...]
    sequence_stages: tuple[int, ...] = ()
    sequence_word_counts: tuple[int, ...] = ()
    sequence_elements: tuple[tuple[int, ...], ...] = ()


def normalise_pulses(pulses) -> tuple[int, ...]:
    """Merge adjacent durations with the same carrier state.

    ``irgen`` may emit a long frame gap as several 0x7fff words, while the portable
    renderer represents the same uninterrupted space once.  Carrier-state transitions,
    not storage chunks, are the observable waveform.
    """
    out: list[int] = []
    for pulse in pulses:
        if not pulse:
            continue
        if out and (out[-1] > 0) == (pulse > 0):
            out[-1] += pulse
        else:
            out.append(pulse)
    return tuple(out)


class CarrierVm:
    """Literal carrier-VM state around one payload and one native command Code."""

    def __init__(self, payload: bytes, code: str | bytes, *, toggle_state: int = 0):
        self.payload = bytes(payload)
        self.code = _code_bytes(code)
        if len(self.payload) < 10 or self.payload[PROTOCOL_BASE] != 1:
            raise IrVmError("IrProto payload has no carrier protocol table at offset 5")
        if len(self.code) < 7:
            raise IrVmError("native Code is too short to contain a command sequence")

        # ir_mgr prefixes seven transport bytes before calling ProcessIrCmd.  That
        # routine selects the u16 protocol index from Code bytes 0..1, then copies Code
        # byte 5 onward into the cursor buffer consumed by sequence_init.
        self.protocol_index = _u16(self.code, 0)
        count = _u16(self.payload, PROTOCOL_BASE + 1)
        if self.protocol_index >= count:
            raise IrVmError(
                f"Code selects protocol {self.protocol_index}, payload has {count}")
        table_slot = PROTOCOL_BASE + 3 + self.protocol_index * 2
        self.block = PROTOCOL_BASE + _u16(self.payload, table_slot)
        if self.block + 7 > len(self.payload):
            raise IrVmError(f"protocol block starts outside payload at {self.block}")

        self.command = self.code[5:]
        self.cursor = 0
        self.saved_cursor = 0
        self.sequence_stage = 2       # StartIrfire's initial carrier stage
        self.sequence_repeat = 0      # byte +0x31 beside the firmware's stage byte
        self.sequence = bytearray(2)  # count, current element
        self.state = bytearray(STATE_SIZE)
        self.element = 0
        self.toggle_state = toggle_state & 0b11
        self.total_elapsed_us = 0     # StartIrfire state +0x40, across all elements
        self.element_trace: list[int] = []

    def _payload_byte(self, offset: int) -> int:
        if not 0 <= offset < len(self.payload):
            raise IrVmError(f"payload read outside buffer at {offset}")
        return self.payload[offset]

    def _command_byte(self) -> int:
        if self.cursor >= len(self.command):
            raise IrVmError("native Code ended while the VM was reading command data")
        value = self.command[self.cursor]
        self.cursor += 1
        return value

    def sequence_init(self) -> bool:
        """Port of ``ir_carrier_sequence_init`` for the current command cursor."""
        if self.sequence_stage >= 6 or self.cursor >= len(self.command):
            return False
        if self.command[self.cursor] == 0:
            self.sequence_stage += 1
            while self.sequence_stage < 6:
                self.cursor += 1
                if self.cursor >= len(self.command) or self.command[self.cursor] != 0:
                    break
                self.sequence_stage += 1
        if self.sequence_stage >= 6 or self.cursor >= len(self.command):
            return False
        self.saved_cursor = self.cursor
        self.sequence[0] = self._command_byte()
        self.sequence[1] = 0
        return True

    def _toggle(self, value: int, bit_offset: int) -> int:
        """Port of ``ir_carrier_data_section_bit_toggle``."""
        first = self._payload_byte(self.element + 2)
        if first == 0xFF:
            return value
        if bit_offset <= first < bit_offset + 8:
            mask = 1 << (7 - (first - bit_offset))
            value = value | mask if self.toggle_state & 1 else value & ~mask
        second = self._payload_byte(self.element + 3)
        if second != 0xFF and bit_offset <= second < bit_offset + 8:
            mask = 1 << (7 - (second - bit_offset))
            value = value | mask if self.toggle_state & 2 else value & ~mask
        return value & 0xFF

    def _select_duration(self) -> None:
        symbol = (_u16(self.state, 0x18) >> 8) & self.state[0x1C]
        pointer = (PROTOCOL_BASE + _u16(self.payload, self.element + 10)
                   + self._payload_byte(self.element + 9) * 2 * symbol)
        _set_u32(self.state, 8, pointer)

    def data_section_init(self) -> None:
        """Port of ``ir_carrier_data_section_init``."""
        symbols = self._payload_byte(self.element + 8)
        if symbols == 0:
            raise IrVmError("data section declares an empty symbol alphabet")
        bits = int(ceil(log2(symbols))) if symbols > 1 else 0
        self.state[0x1B] = bits
        self.state[0x1C] = (1 << bits) - 1 if bits else 0
        value = self._toggle(self._command_byte(), 0)
        self.state[0x1D] = 0
        shifted = value << bits
        _set_u16(self.state, 0x18, shifted)
        self.state[0x1A] = 8 - bits
        self._select_duration()

    def data_section_process(self) -> None:
        """Port of ``ir_carrier_data_section_process``."""
        remaining = self.state[0x1A]
        bits = self.state[0x1B]
        accumulator = _u16(self.state, 0x18)
        if remaining < bits:
            value = self._command_byte()
            self.state[0x1D] = (self.state[0x1D] + 8) & 0xFF
            value = self._toggle(value, self.state[0x1D])
            accumulator = (value | (accumulator << remaining)) & 0xFFFF
            accumulator = accumulator << (bits - remaining) & 0xFFFF
            self.state[0x1A] = 8 - (bits - remaining)
        else:
            accumulator = accumulator << bits & 0xFFFF
            self.state[0x1A] = remaining - bits
        _set_u16(self.state, 0x18, accumulator)
        self._select_duration()

    def element_init(self) -> bool:
        """Port of ``ir_carrier_element_init``."""
        if self.cursor >= len(self.command):
            return False
        index = self._command_byte()
        element_count = self._payload_byte(self.block + 6)
        if index >= element_count:
            raise IrVmError(
                f"command selects element {index}, block has {element_count}")
        self.element = PROTOCOL_BASE + _u16(
            self.payload, self.block + 7 + index * 2)
        self.element_trace.append(index)
        if self.element + 16 > len(self.payload):
            raise IrVmError(f"element {index} starts outside payload at {self.element}")

        before = _u16(self.payload, self.element + 12)
        after = _u16(self.payload, self.element + 14)
        if before and self._payload_byte(PROTOCOL_BASE + before):
            self.state[0] = 0
            _set_u16(self.state, 2, 1)
            self.state[6] = self._payload_byte(PROTOCOL_BASE + before)
            _set_u32(self.state, 8, PROTOCOL_BASE + before + 1)
        elif _u16(self.payload, self.element + 10):
            self.state[0] = 1
            _set_u16(self.state, 2, _u16(self.payload, self.element))
            self.state[6] = self._payload_byte(self.element + 9)
            self.data_section_init()
        elif after and self._payload_byte(PROTOCOL_BASE + after):
            self.state[0] = 2
            _set_u16(self.state, 2, 1)
            self.state[6] = self._payload_byte(PROTOCOL_BASE + after)
            _set_u32(self.state, 8, PROTOCOL_BASE + after + 1)
        else:
            raise IrVmError(f"element {index} has no playable carrier section")

        _set_u16(self.state, 4, 0)
        self.state[7] = 0
        _set_u32(self.state, 0x0C, _u32(self.payload, self.element + 4))
        self.state[0x14] = 0
        _set_u16(self.state, 0x16, 0)
        _set_u32(self.state, 0x10, 0)
        return True

    def prepare_next_data(self) -> bool:
        """Port the element/section portion of ``ir_carrier_prepare_next_data``.

        ``False`` means this sequence's elements are complete. The outer stage policy is
        kept in :meth:`advance_sequence` so one sequence remains independently testable.
        """
        phase = self.state[0]
        if phase < 3:
            repeat = self.state[7]
            self.state[7] = (repeat + 1) & 0xFF
            if self.state[6] <= self.state[7]:
                emitted = _u16(self.state, 4) + 1
                _set_u16(self.state, 4, emitted)
                if emitted < _u16(self.state, 2):
                    self.state[7] = 0
                    self.data_section_process()
                else:
                    self.state[0] = phase + 1
                    if phase == 0:
                        if not _u16(self.payload, self.element + 10):
                            self.state[0] = 2
                        else:
                            _set_u16(self.state, 4, 0)
                            _set_u16(self.state, 2, _u16(self.payload, self.element))
                            self.state[6] = self._payload_byte(self.element + 9)
                            self.state[7] = 0
                            self.data_section_init()
                    if self.state[0] == 2:
                        after = _u16(self.payload, self.element + 14)
                        if not after or not self._payload_byte(PROTOCOL_BASE + after):
                            self.state[0] += 1
                        else:
                            _set_u16(self.state, 2, 1)
                            _set_u16(self.state, 4, 0)
                            self.state[6] = self._payload_byte(PROTOCOL_BASE + after)
                            self.state[7] = 0
                            _set_u32(self.state, 8, PROTOCOL_BASE + after + 1)

        if self.state[0] == 3:
            total = _u32(self.state, 0x0C)
            elapsed = _u32(self.state, 0x10)
            if total == 0xFFFFFFFF or total <= elapsed:
                _set_u16(self.state, 0x16, 0)
                self.state[0] += 1
                self.state[0x14] = 0
            else:
                self.state[0x14] = 1
                _set_u16(self.state, 0x16, min(total - elapsed, MAX_GAP_US))

        if self.state[0] != 4:
            return True
        current = self.sequence[1]
        self.sequence[1] = (current + 1) & 0xFF
        if self.sequence[1] < self.sequence[0]:
            return self.element_init()
        return False

    def advance_sequence(self, *, held_replays: int = 0,
                         duration_us: int = 0) -> bool:
        """Apply the firmware's outer stage-3 repeat policy and start the next sequence.

        The real condition is::

            minimum count not met OR key is still held OR requested duration not met

        ``held_replays`` is a deterministic substitute for polling the remote's physical
        key flags: it requests that many additional stage-3 executions after the first.
        The Code's byte 4 remains authoritative for the minimum count. ``duration_us``
        models the non-held timed-send path. The two external modes are mutually exclusive
        in the firmware and therefore here as well.
        """
        if held_replays < 0 or duration_us < 0:
            raise IrVmError("held replay count and duration must be non-negative")
        if held_replays and duration_us:
            raise IrVmError("held replay count and timed duration are mutually exclusive")

        repeat = False
        if self.sequence_stage == 3:
            minimum_repeats = self.code[4]
            repeat = (
                self.sequence_repeat + 1 < minimum_repeats
                or self.sequence_repeat < held_replays
                or (duration_us > 0 and self.total_elapsed_us < duration_us)
            )
        if repeat:
            self.sequence_repeat = (self.sequence_repeat + 1) & 0xFF
            self.cursor = self.saved_cursor
        else:
            self.sequence_stage += 1

        # The C caller only enters sequence_init below stage 5. sequence_init may consume
        # a zero delimiter and advance to stage 5, which is how a finish sequence is
        # reached. A sequence that fails to initialise terminates the command at stage 6.
        if self.sequence_stage < 5:
            if self.sequence_init() and self.element_init():
                return True
        self.sequence_stage = 6
        return False

    def _next_word(self) -> int:
        if self.state[0x14]:
            word = _u16(self.state, 0x16)
        else:
            pointer = _u32(self.state, 8)
            word = _u16(self.payload, pointer)
            _set_u32(self.state, 8, pointer + 2)
        elapsed = word & 0x7FFF
        _set_u32(self.state, 0x10, _u32(self.state, 0x10) + elapsed)
        self.total_elapsed_us += elapsed
        return word

    def _result(self, words, stages=(), counts=(), elements=()) -> Simulation:
        period_ns = _u32(self.payload, self.block + 1)
        carrier_hz = round(1_000_000_000 / period_ns) if period_ns else 0
        pulses = tuple((word & 0x7FFF) * (1 if word & 0x8000 else -1)
                       for word in words if word & 0x7FFF)
        return Simulation(
            carrier_hz, pulses, tuple(words), tuple(stages), tuple(counts),
            tuple(tuple(sequence) for sequence in elements))

    def run_sequence(self, *, max_words: int = 10000) -> Simulation:
        if not self.sequence_init() or not self.element_init():
            raise IrVmError("native Code contains no playable command sequence")
        words = []
        while True:
            if len(words) >= max_words:
                raise IrVmError(f"carrier VM exceeded {max_words} duration words")
            words.append(self._next_word())
            if not self.prepare_next_data():
                break
        return self._result(
            words, [self.sequence_stage], [len(words)], [self.element_trace])

    def run_transmission(self, *, held_replays: int = 0, duration_us: int = 0,
                         max_words: int = 10000) -> Simulation:
        """Execute all stage-delimited sequences for one bounded native transmission."""
        if held_replays < 0 or duration_us < 0:
            raise IrVmError("held replay count and duration must be non-negative")
        if held_replays and duration_us:
            raise IrVmError("held replay count and timed duration are mutually exclusive")
        if not self.sequence_init() or not self.element_init():
            raise IrVmError("native Code contains no playable command sequence")

        words: list[int] = []
        stages: list[int] = []
        counts: list[int] = []
        elements: list[tuple[int, ...]] = []
        element_start = 0
        while True:
            stages.append(self.sequence_stage)
            start = len(words)
            while True:
                if len(words) >= max_words:
                    raise IrVmError(f"carrier VM exceeded {max_words} duration words")
                words.append(self._next_word())
                if not self.prepare_next_data():
                    break
            counts.append(len(words) - start)
            elements.append(tuple(self.element_trace[element_start:]))
            next_element_start = len(self.element_trace)
            if not self.advance_sequence(
                    held_replays=held_replays, duration_us=duration_us):
                break
            element_start = next_element_start
        return self._result(words, stages, counts, elements)


def simulate_sequence(payload: bytes, code: str | bytes, *, toggle_state: int = 0,
                      max_words: int = 10000) -> Simulation:
    """Execute the first native sequence selected by ``code``."""
    return CarrierVm(payload, code, toggle_state=toggle_state).run_sequence(
        max_words=max_words)


def simulate_transmission(payload: bytes, code: str | bytes, *, toggle_state: int = 0,
                          held_replays: int = 0, duration_us: int = 0,
                          max_words: int = 10000) -> Simulation:
    """Execute the Code's complete bounded press/hold/finish lifecycle."""
    return CarrierVm(payload, code, toggle_state=toggle_state).run_transmission(
        held_replays=held_replays, duration_us=duration_us, max_words=max_words)
