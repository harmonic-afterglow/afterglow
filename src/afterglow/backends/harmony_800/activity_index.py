"""Own Harmony 800 activities through their menus, contexts, and state engine.

An activity is retained as native evidence unless its section-10 ENTER/REFRESH hooks and
section-14 transitions reach indexed commands unambiguously. An empty result is explicitly
undetermined because RE-HARMONY did not establish the separate All Off/default-state path.

Format reference: docs/harmony_one/activity-engine.md
"""
from .._gspm import share

share(globals(), "activity_index")
