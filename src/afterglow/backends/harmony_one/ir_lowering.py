"""Lower portable IR meaning into Harmony One waveform and carrier records.

This module stops at native, relocatable pieces. Object indexes and placement in a GSPM
image belong to later build stages and must not be inferred from waveform bytes.

Format reference: docs/harmony_one/commands.md
"""
from .._gspm import share

share(globals(), "ir_lowering")
