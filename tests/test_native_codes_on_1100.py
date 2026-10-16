"""A 900's native-only commands play on an 1100.

A Harmony 900 configuration's commands are Codes for its own IrProto programs. The import
makes them portable, except where an RC5/RC6 program declares a toggle bit: that block is
not promoted (a 900 rebuild carries the declaration by block id), and its semantic
decoder needs the `rc6-mce` library protocol, which is not installed. So every RC6 command
- Xbox 360, Windows Media Center, the MCE keyboard - arrived native-only, and a tester's
1100 build of his 900 devices stopped with "a backend-opaque signal has nothing to play
back" for each of them.

A 900 plays such a Code as it is. An 1100 needs pulses, so the program is promoted at
playback, by the same conversion the import uses and proves against the carrier VM.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from afterglow import ir_signal
from afterglow.backends.harmony_pk import ssir_sequence

# The RC6 program as a 900 configuration carries it (imported, `protocol_definition`).
RC6_BLOCK = json.loads(
    (Path(__file__).parent / "fixtures" / "native-rc6-mce-block.json").read_text())
XBOX_360_OK = "0x08002C0100000100FFC02F8C00"       # fields the RC6-MCE decoder refuses
MCE_KEYBOARD_BACK = "0x0800F40103000100FFC1EF7000"


def _native(code, definition=RC6_BLOCK):
    native = {"format": "command-code", "code": code, "protocol_block_id": "6bd42e0eea79"}
    if definition is not None:
        native["protocol_definition"] = definition
    return ir_signal.backend_opaque({"harmony-pk": native}, name="OK")


@pytest.mark.parametrize("code", [XBOX_360_OK, MCE_KEYBOARD_BACK])
def test_an_rc6_code_renders_as_rc6_with_its_toggle(code):
    carrier, variants = ssir_sequence._renders(_native(code), None)
    assert carrier == 36200
    assert len(variants) == 2, "RC6 alternates its toggle bit between presses"
    first, second = (press for press, _hold in variants)
    assert first[:2] == second[:2] == [2632, -900], "the RC6 leader"
    assert first != second, "the two presses must differ in the toggle bit"
    assert all(press and hold for press, hold in variants)


def test_it_becomes_1100_sequences():
    press, hold = ssir_sequence.for_signal(_native(XBOX_360_OK), press_presilence=1000,
                                           hold_presilence=50)
    assert len(press.variants) == len(hold.variants) == 2


def test_a_code_without_its_program_still_says_so():
    with pytest.raises(ValueError, match="nothing to play back"):
        ssir_sequence._renders(_native(XBOX_360_OK, definition=None), None)
