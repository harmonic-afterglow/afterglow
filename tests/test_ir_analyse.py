"""The probe analyser's comparison logic."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


def test_a_capture_is_scored_as_a_whole_keypress():
    """`press, hold x N, release` in one capture, with N reported.

    A capture is one keypress, not one phase: comparing against a single phase leaves
    the measurement this exists to make - how many times the repeat ran, and whether the
    finish played - to be done by hand.

    The numbers are ones a Harmony 900 emitted. A carried `hold_minimum` of 3 gives
    exactly three holds on a tap, and a protocol with a release phase ends with one
    finish however long the key is held.
    """
    import ir_analyse

    press = [600, -600, 600, -1800, 600, -8000]
    hold = [600, -1800, 600, -8000]
    finish = [600, -600, 600, -600, 600, -8000]
    phases = {"press": press, "hold": hold, "release": finish}

    tap = press[:-1] + [-8000] + hold[:-1] + [-8000] + hold[:-1] + [-8000] + hold[:-1]
    score = ir_analyse.score_lifecycle(phases, tap, absolute_us=200, relative=0.12)
    assert score["holds"] == 3 and not score["release"]

    whole = press[:-1] + [-8000] + hold[:-1] + [-8000] + finish[:-1]
    score = ir_analyse.score_lifecycle(phases, whole, absolute_us=200, relative=0.12)
    assert score["holds"] == 1 and score["release"], score

    # A different protocol must not be read as this one. Comparing signed mark+space sums
    # collapses a 600 us unit and an 800 us unit to 200 us apart and they match each
    # other; comparing *periods* keeps them 400-800 us apart and they do not.
    other = [800, -800, 800, -2400, 800, -8000]
    assert ir_analyse.score_lifecycle(
        phases, other, absolute_us=200, relative=0.12) is None
