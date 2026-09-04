"""Nothing the user makes may land inside the package.

The interface kept defaulting its file dialogs to `HERE` - the directory the module
itself lives in - so importing a configuration unpacked it into `src/afterglow/gui/`,
and "Save Project As" offered to write the project there too. Both duly happened during
a hardware test, which is how a real living room's project file ended up staged for a
public commit.

`tabs.py` was corrected for this once; `app.py` was missed, because nothing checked.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "afterglow"
GUI = [p for p in PACKAGE.rglob("*.py")
       if not {"library", "icons", "scaffolds"} & set(p.parts)]


# The data the application ships lives inside the package deliberately, so that an
# install carries it. Everything else non-Python under the package is a stray.
# `linux` holds the USB-RNDIS helper and its udev rule. They belong inside the package
# so an installed copy carries them; at the top of a checkout they ship with nothing.
SHIPPED = ("library", "icons", "scaffolds", "backends", "linux", "branding")


def test_the_package_contains_only_code_and_the_data_it_ships():
    """What this is guarding against is a user's own file landing here - a project, an
    unpacked configuration, a dump - not the library and artwork that belong."""
    strays = [p.relative_to(ROOT) for p in PACKAGE.rglob("*")
              if p.is_file() and p.suffix != ".py"
              and "__pycache__" not in p.parts
              and not set(p.relative_to(PACKAGE).parts) & set(SHIPPED)]
    assert not strays, f"neither code nor shipped data, inside the package: {strays}"


@pytest.mark.parametrize("path", GUI, ids=lambda p: p.name)
def test_no_file_dialog_defaults_into_the_package(path):
    """`HERE` is the module's own directory. Offering it as the place to read or write
    a user's files is what put them in the package; ROOT is the application folder."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None)
        if name not in ("getOpenFileName", "getSaveFileName", "getExistingDirectory"):
            continue
        used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        assert "HERE" not in used, (
            f"{path.name}: a file dialog defaults to HERE, which is inside the package. "
            "Use ROOT (the application folder) or the file the user already chose.")
