"""Index Harmony 800 drawing programs, touch geometry, and owned menu labels.

Text remains a sequence of image-local glyph codes until its font mapping is proved.  A
menu row is owned by the touch zone that opens its target screen, rather than by scanning
for plausible strings or assuming every menu replica has the same row order.

Format reference: docs/harmony_one/drawing.md
"""
from .._gspm import share

share(globals(), "ui_index")
