"""Read Harmony 800 screen key registers without assigning button vocabulary.

Section 6 reaches the exact key registers used by each screen. Command resolution then
follows section-11 object references to IDs already owned by section 5. Navigation,
multi-command actions, and other classes stay explicitly counted rather than being
flattened into portable hard-key assignments.

Format reference: docs/harmony_one/screens.md
"""
from .._gspm import share

share(globals(), "key_index")
