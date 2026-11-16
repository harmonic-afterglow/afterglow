"""What an activity's planned steps (activities.py) become in a generated Harmony One: the
instructions that send a device's command, wait before its next send, or write its power
and input variables, whose transitions send what changing them takes.

Format reference: docs/harmony_one/activities.md
"""
from .._gspm import share

share(globals(), "actions")
