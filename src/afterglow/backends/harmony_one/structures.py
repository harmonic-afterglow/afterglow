"""The byte forms of the GSPM structures a generated Harmony One image is built from.

Key registers, screen slots and trailers, contexts, the command index, navigation and
device objects, font and engine records, and the clock stamp: each written exactly as
measured in Logitech's images. Where they go is the layout's business; these only say
what the bytes are.

Format reference: docs/harmony_one/image.md
"""
from .._gspm import share

share(globals(), "structures")
