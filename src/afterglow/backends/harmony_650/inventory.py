"""Bounded inventory of native Harmony One objects and command records.

This module reports structures without assigning portable meaning to them. Classification
is evidence for the next importer slice, not permission to mutate or relocate the image.

Format reference: docs/harmony_650_700/gspm.md, docs/harmony_one/README.md
"""
from .._gspm import share

share(globals(), "inventory")
