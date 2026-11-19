"""The GSPM family's shared code: what the Harmony One, the 800, the arch-14 remotes
(600, 650, 665, 700) and arch 9, GSPM's parent (the 5xx), read and write alike.

The three backends began as copies of the One's, and a dozen of their modules stayed the
same. Each lives here once, in `shared/` - source, not a package: it is never imported on
its own. A member keeps a module of the same name that runs that source in its own package - `share(globals(), "bitmap")` - so the shared code's
`from . import gspm` reaches that member's own gspm, ui_index and the rest: one text, read
against each architecture's layout. A member that differs sets the difference after it
(the 800's bigger screen). A module whose behaviour differs between members is not here.

This is not a backend (backends.names skips it). It goes when its last member goes
(tests/test_removability.py).
"""
from __future__ import annotations

from pathlib import Path

_CODE: dict[str, object] = {}


def share(namespace: dict, name: str) -> None:
    """Run the family's module ``name`` in a member's module ``namespace``."""
    code = _CODE.get(name)
    if code is None:
        path = Path(__file__).with_name("shared") / f"{name}.py"
        code = _CODE[name] = compile(path.read_text("utf-8"), str(path), "exec",
                                     dont_inherit=True)
    exec(code, namespace)
