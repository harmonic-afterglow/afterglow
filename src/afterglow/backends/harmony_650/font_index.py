"""Complete a Harmony One font from the glyphs its own image already contains.

A font indexes the whole repertoire but carries only the glyphs its own labels needed,
which is why a title or menu row cannot always be renamed to what a user wants. The
missing glyphs often exist in the image already, in another font of the same typeface
that happened to need them, and filling a null slot with one of those is the smallest
possible change: no glyph data is written, the record does not move or change size, and
nothing that draws today can be affected, because a label using that code could not have
been drawn before.

Two fonts count as the same typeface only when they declare the same height and every
code they both carry has an identical decoded shape. Where compatible fonts disagree
about a code, that code is left unresolved rather than picked from one of them.

Format reference: docs/harmony_650_700/gspm.md, docs/harmony_one/README.md
"""
from .._gspm import share

share(globals(), "font_index")
