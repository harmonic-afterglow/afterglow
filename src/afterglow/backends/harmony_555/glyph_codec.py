"""Decode Harmony One text with the repertoire declared by its native image.

Harmony One firmware families do not all assign the same character to the same
numeric glyph code. The section-7 repertoire size identifies the four layouts
currently established by independent images; unknown layouts remain undecoded.
Bitmap parsing is still required so a claimed layout cannot silently include a
code for which the image has no drawable glyph.

Format reference: docs/harmony_650_700/gspm.md, docs/harmony_one/README.md
"""
from .._gspm import share

share(globals(), "glyph_codec")
