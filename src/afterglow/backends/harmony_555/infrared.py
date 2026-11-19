"""Write a 5xx's infrared: class-5 bodies spelled from a dictionary of pulse blocks.

A 5xx command record is the 650's, its class byte 5: its press, hold and release pointers
name a *body* - a symbol table and the indexes of the symbols to play - where class 1
names the duration words themselves (docs/harmony_5xx/ahcm.md, "Infrared"):

    body    u24 table, u16 n, u8 index[n]
    table   u8 count, u24 symbol[count]
    symbol  u16 count, u16 word[count], u16 0

Here a waveform the shared lowering wrote (ir_lowering: duration words, bit 15 a mark,
ending in the zero word) is cut into mark-led chunks - a mark and the spaces after it, a
leading run of spaces a chunk of its own - and each distinct chunk is one symbol, shared
by every command of the device. That is the shape Logitech's records have, and it keeps
every symbol far under the 127 words the firmware's pulse queue takes in one block
(harmony-decompiler's FORMAT.md 5af: a 39-command device whose symbols were whole
waveforms of 69 to 154 words sent nothing).
"""
from __future__ import annotations

import struct

MARK = 0x8000
MOST_WORDS = 127            # one symbol, the firmware's pulse queue
MOST_SYMBOLS = 255
CLASS_5 = 5
CLASS_AT = 11               # the record's class byte


def words_of(waveform: bytes) -> list[int]:
    """A class-1 waveform's words, without the zero that ends it."""
    words = list(struct.unpack(f"<{len(waveform) // 2}H", waveform))
    if not words or words[-1] != 0:
        raise ValueError("a waveform ends with its zero word")
    return words[:-1]


def chunks(words: list[int]) -> list[tuple[int, ...]]:
    """Mark-led chunks: each mark with the spaces after it; leading spaces alone."""
    out: list[list[int]] = []
    for word in words:
        if not word:
            raise ValueError("a zero word inside a waveform")
        if word & MARK or not out:
            out.append([word])
        else:
            out[-1].append(word)
    for chunk in out:
        while len(chunk) > MOST_WORDS:
            raise ValueError(f"a {len(chunk)}-word pulse block passes the firmware's "
                             f"{MOST_WORDS}")
    return [tuple(chunk) for chunk in out]


class Dictionary:
    """One device's symbols, as many tables as it needs, each at most 255 symbols."""

    def __init__(self):
        self.tables: list[list[tuple[int, ...]]] = [[]]
        self.at: list[dict[tuple[int, ...], int]] = [{}]

    def spell(self, waveform: bytes) -> tuple[int, list[int]]:
        """The table a waveform is spelled from and the symbols it plays."""
        parts = chunks(words_of(waveform))
        table = len(self.tables) - 1
        new = {part for part in parts if part not in self.at[table]}
        if len(self.tables[table]) + len(new) > MOST_SYMBOLS:
            self.tables.append([])
            self.at.append({})
            table += 1
        indexes = []
        for part in parts:
            if part not in self.at[table]:
                self.at[table][part] = len(self.tables[table])
                self.tables[table].append(part)
            indexes.append(self.at[table][part])
        return table, indexes


def symbol(words: tuple[int, ...]) -> bytes:
    return struct.pack(f"<H{len(words)}HH", len(words), *words, 0)


def body(table_address: int, indexes: list[int]) -> bytes:
    if len(indexes) > 0xFFFF:
        raise ValueError("a class-5 body names at most 65535 symbols")
    return table_address.to_bytes(3, "little") + struct.pack("<H", len(indexes)) + bytes(indexes)


def table(symbol_addresses: list[int]) -> bytes:
    return bytes([len(symbol_addresses)]) + b"".join(
        address.to_bytes(3, "little") for address in symbol_addresses)


def classed(record: bytes) -> bytes:
    """A record the shared writer built (class 1), made class 5."""
    out = bytearray(record)
    out[CLASS_AT] = CLASS_5
    return bytes(out)
