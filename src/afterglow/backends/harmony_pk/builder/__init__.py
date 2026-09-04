"""Turning lowered portable devices into a Harmony PK config tree.

    codes.py       IR command framing (NEC, NEC extended, Samsung)
    devices.py     one <Device> element and its ActionLists
    activities.py  activities: roles, power, macros, buttons
    protocols.py   which IrProto block each device uses, and its runtime index
    assemble.py    puts it together into a directory ready to pack

`build()` is the whole public surface; the rest is here so each piece can be read,
tested and changed on its own.
"""
from .assemble import BASE, BuildRequest, build
from .codes import (CODECS, SYNTHESIZABLE_PROTOCOLS, bitrev, code_pre, esc,
                    nec_code, necext_code, samsung_code)
from .protocols import NEC_ID, SAMSUNG_ID

__all__ = ["build", "BuildRequest", "BASE", "CODECS", "SYNTHESIZABLE_PROTOCOLS",
           "bitrev", "code_pre", "esc", "nec_code", "necext_code", "samsung_code",
           "NEC_ID", "SAMSUNG_ID"]
