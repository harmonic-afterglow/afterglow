"""Bounded inventory of native Harmony 800 objects and command records.

This module reports structures without assigning portable meaning to them. Classification
is evidence for the next importer slice, not permission to mutate or relocate the image.

Format reference: docs/harmony_one/commands.md
"""
from .._gspm import share

share(globals(), "inventory")
