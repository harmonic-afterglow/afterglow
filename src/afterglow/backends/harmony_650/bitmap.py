"""Read and write the pictures a Harmony One configuration draws.

Bitmaps are most of a configuration: 1.1 to 1.5 MB of the 1.3 to 1.8 MB in the four
images measured, around 85 per cent. Every backdrop, button frame, row frame, softkey
and icon the remote shows is stored here rather than in firmware, which is why a
configuration generated from a project has to supply them and why they can be ours.

Pixels are RGB565, big-endian, after a five-byte header. Mode 0 stores every pixel of
every row. Mode 1 runs them - a byte with the high bit set leaves that many pixels
untouched, a byte without it introduces that many stored pixels, `80` closes a row and
`00` closes the picture - which is the same run encoding, and the same byte order, that a
font glyph uses. Nothing in the format carries
an alpha channel; a run simply declines to write, so what was already on the screen shows
through.

Format reference: docs/harmony_650_700/gspm.md, docs/harmony_one/README.md
"""
from .._gspm import share

share(globals(), "bitmap")
