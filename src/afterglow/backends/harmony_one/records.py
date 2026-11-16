"""Build relocatable Harmony One command records and command objects.

Addresses passed here are offsets in the GSPM image. Placement, table insertion, and
relocation remain separate operations so a valid record cannot imply a safe image edit.

Format reference: docs/harmony_one/commands.md
"""
from .._gspm import share

share(globals(), "records")
