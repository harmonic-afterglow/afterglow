"""The build layer must not need the interface.

Unpacking, rebuilding and verifying a configuration is deliberately pure standard
library, so it works on a bare Python with nothing installed - that is what makes the
format side usable as a library, testable without a display, and safe to run on a
machine that will never have PyQt.

`builder/activities.py` broke that quietly: it reached into `gui.constants` for the list
of activity types. The import sat behind a `try` that swallowed the failure, so on a
machine without PyQt the builder did not crash - it just silently stopped checking
activity types, and the check existed because an invented type had already shipped once.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "afterglow"
CORE = [p for p in PACKAGE.rglob("*.py")
        if "gui" not in p.relative_to(PACKAGE).parts]


def imports(path):
    """Every module named by an import in this file, however it is spelled."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield ("." * node.level) + (node.module or "")


@pytest.mark.parametrize("path", CORE, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_core_module_imports_the_interface(path):
    for name in imports(path):
        assert "gui" not in name.split("."), \
            f"{path.relative_to(ROOT)} imports {name}: the build layer must not need " \
            "the interface. Firmware vocabulary belongs in afterglow/vocabulary.py."


@pytest.mark.parametrize("path", CORE, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_core_module_imports_a_third_party_package(path):
    """PyQt and Pillow are optional extras, declared under [gui]. Anything the build
    path touches has to come out of the standard library."""
    banned = {"PyQt6", "PIL", "numpy", "requests"}
    for name in imports(path):
        assert name.split(".")[0] not in banned, \
            f"{path.relative_to(ROOT)} imports {name}, which is a GUI-only extra"


def test_a_configuration_builds_with_the_interface_unimportable():
    """The rule, demonstrated rather than inspected: build the acceptance configuration
    in a Python where importing PyQt6 raises, the way a machine without it behaves."""
    script = f'''
import sys, types, contextlib, io, tempfile
from pathlib import Path

class Blocked:
    """find_spec, not find_module: the old hook was removed in 3.12 and a finder that
    only defines it is silently ignored, which made this whole check pass vacuously."""
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("PyQt6", "PIL"):
            raise ImportError(f"{{name}} is not installed")
        return None
sys.meta_path.insert(0, Blocked())
sys.path.insert(0, {str(ROOT / "src")!r})

for blocked in ("PyQt6", "PIL"):          # prove the blocker actually blocks
    try:
        __import__(blocked)
    except ImportError:
        pass
    else:
        raise AssertionError(f"{{blocked}} imported anyway - the block does not work")

from afterglow.build_service import ConfigBuildService
from afterglow.backends.harmony_pk.builder.activities import _known_activity_types

# Not an empty set: an unimportable interface must not turn the check into a no-op.
assert "VirtualTelevisionN" in _known_activity_types()

# A synthetic device exercises the build without depending on private user data.
root = Path({str(ROOT)!r})
device = {{
    "id": "40009001", "label": "Test Television", "type": "Television",
    "mfr": "Test", "model": "Synthetic", "codec": "nec",
    "protocol": "a7b8a0e6c639",
    "commands": [["PowerToggle", "Power", "01", "02", None]],
    "power_cmd": "PowerToggle",
}}

project = {{
    "devices": [device], "activities": [], "assets": [],
    "settings": {{"remote": "harmony-900", "first_name": "T", "last_name": "U",
                  "out_file": str(Path(tempfile.mkdtemp()) / "out.ezhex")}},
}}
with contextlib.redirect_stdout(io.StringIO()):
    ConfigBuildService(Path({str(ROOT)!r}), lambda _m: None).build(project)
assert Path(project["settings"]["out_file"]).stat().st_size > 0
print("ok")
'''
    done = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout
