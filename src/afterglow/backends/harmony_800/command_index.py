"""Read the Harmony 800's authoritative device-to-command index.

Section 5 is the path the firmware uses to resolve the high and low bytes of a command
ID. It owns command records; byte-pattern scans do not. Section-11 command objects add
runtime device IDs, which are retained as evidence rather than mistaken for device names.

Format reference: docs/harmony_one/commands.md
"""
from .._gspm import share

share(globals(), "command_index")

DEVICE_NAME = "Harmony 800 device {index}"
