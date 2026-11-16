"""Read the owned section-0 named-record chain in Harmony One images.

Restricting the grammar to section 0 and requiring a contiguous chain closed by `BEEF`
prevents ordinary bitmap or program bytes from becoming names merely because they resemble
an A7 record.

Format reference: docs/harmony_650_700/gspm.md, docs/harmony_one/README.md
"""
from .._gspm import share

share(globals(), "named_index")
