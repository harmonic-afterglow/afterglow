"""Any one remote backend or payload type must be deletable.

This is the project's architectural rule stated as an experiment rather than as a
convention: **every piece of code is remote-agnostic unless it lives inside that
remote's `backends/<name>/` folder or a `payloads/<type>.py` module.** Removing support
for a remote, or for a container payload format, has to be `rm -r` - not a refactor.

Conventions decay silently. This one already had: `payloads/__init__.py` did
`from . import blob, pk` and exported `DEFAULT = pk.NAME`, so deleting `pk.py` stopped
`afterglow.ezhex` importing at all, and `ezhex.rehash()` called `payloads.get("pk")`
by name. Nothing failed, because nothing checked. The test below is what checks.

It works by building a package tree with one component removed and importing everything
that is left. Python files are copied; the shipped data directories are symlinked, so a
full pass costs a few hundred kilobytes rather than a megabyte and a half.
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "afterglow"
DATA_DIRS = ("library", "icons", "scaffolds")


def backend_names():
    return sorted(path.name for path in (PACKAGE / "backends").iterdir()
                  if path.is_dir() and not path.name.startswith("__"))


def payload_names():
    return sorted(path.stem for path in (PACKAGE / "payloads").glob("*.py")
                  if not path.name.startswith("__"))


def _tree_without(tmp_path: Path, removed: Path) -> Path:
    """A copy of the package with ``removed`` absent, data directories symlinked."""
    src = tmp_path / "src"
    target = src / "afterglow"
    target.mkdir(parents=True)
    for entry in PACKAGE.iterdir():
        if entry.name in DATA_DIRS:
            (target / entry.name).symlink_to(entry, target_is_directory=True)
        elif entry.name == "__pycache__":
            continue
        elif entry.is_dir():
            shutil.copytree(entry, target / entry.name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(entry, target / entry.name)
    doomed = target / removed.relative_to(PACKAGE)
    assert doomed.exists(), f"{removed} is not part of the package"
    shutil.rmtree(doomed) if doomed.is_dir() else doomed.unlink()
    return src


def _import_everything(src: Path) -> str:
    """Import every remaining module in a subprocess; return '' or the failures."""
    program = textwrap.dedent("""
        import importlib, pkgutil, sys
        import afterglow
        broken = []
        for module in pkgutil.walk_packages(afterglow.__path__, 'afterglow.'):
            if '.gui' in module.name:      # needs PyQt6, covered by its own tests
                continue
            try:
                importlib.import_module(module.name)
            except ImportError as exc:     # a missing sibling is the coupling we hunt
                broken.append(f'{module.name}: {type(exc).__name__}: {exc}')
            except Exception:
                pass                       # runtime errors are not import coupling
        sys.stdout.write('\\n'.join(broken))
    """)
    # Run from the pruned tree, not the repository: the checkout's own `afterglow.py`
    # launcher sits on `sys.path[0]` and would shadow the package under test.
    result = subprocess.run([sys.executable, "-c", program], capture_output=True,
                            text=True, cwd=str(src),
                            env={"PYTHONPATH": str(src), "PATH": ""})
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("name", backend_names())
def test_removing_one_remote_backend_breaks_nothing(name, tmp_path):
    src = _tree_without(tmp_path, PACKAGE / "backends" / name)
    broken = _import_everything(src)
    assert not broken, (
        f"deleting backends/{name}/ broke:\n{broken}\n"
        "Shared code must reach a backend through afterglow.backends, never by import.")


@pytest.mark.parametrize("name", payload_names())
def test_removing_one_payload_type_breaks_nothing(name, tmp_path):
    src = _tree_without(tmp_path, PACKAGE / "payloads" / f"{name}.py")
    broken = _import_everything(src)
    assert not broken, (
        f"deleting payloads/{name}.py broke:\n{broken}\n"
        "Payload types are discovered; nothing outside the package may import one.")


def _shared_modules():
    """Every module that is neither a backend nor a payload type."""
    skip = (PACKAGE / "backends", PACKAGE / "payloads")
    return [path for path in PACKAGE.rglob("*.py")
            if not any(parent in path.parents or parent == path.parent
                       for parent in skip)]


def _registry_literals(path: Path):
    """Component names passed as literals to a registry lookup.

    Matching bare strings anywhere would be wrong: `public_ir_sources.py` compares a
    GitHub tree entry against `"blob"`, which has nothing to do with the payload module
    of that name. What actually constitutes coupling is *resolving* a component by a
    hardcoded name, so look for the call, not the word.
    """
    registries = {"payloads", "backends"}
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "get":
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id in registries):
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                yield argument.value


@pytest.mark.parametrize("path", sorted(_shared_modules()),
                         ids=lambda path: str(path.relative_to(PACKAGE)))
def test_shared_code_never_resolves_a_component_by_a_hardcoded_name(path):
    """A string literal is coupling too - that is how `payloads.get("pk")` survived.

    Checked against the components actually installed, so this keeps working when a
    remote is added or removed rather than encoding today's list.
    """
    concrete = set(backend_names()) | set(payload_names())
    concrete |= {name.replace("_", "-") for name in concrete}
    offenders = sorted(set(_registry_literals(path)) & concrete)
    assert not offenders, (
        f"{path.relative_to(PACKAGE)} resolves {offenders} by name; select a backend "
        "from the remote profile and a payload type from the bytes or the tree")


@pytest.mark.parametrize("path", sorted(_shared_modules()),
                         ids=lambda path: str(path.relative_to(PACKAGE)))
def test_shared_code_never_imports_a_concrete_component(path):
    imported = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = f"{'.' * node.level}{node.module or ''}"
            imported.update(f"{base}.{alias.name}" for alias in node.names)
            imported.add(base)
    for name in set(backend_names()) | set(payload_names()):
        leaked = sorted(module for module in imported
                        if module.split(".")[-1] == name
                        or f"backends.{name}" in module or f"payloads.{name}" in module)
        assert not leaked, (
            f"{path.relative_to(PACKAGE)} imports {leaked}; that makes the component "
            "undeletable and the profile's declaration decorative")


def test_the_registries_agree_with_what_is_installed():
    """Discovery must reflect the filesystem, not a hand-maintained list."""
    from afterglow import backends, payloads

    assert set(payloads.names()) == set(payload_names())
    for name in backend_names():
        module = backends.get(name.replace("_", "-"))
        assert all(callable(getattr(module, attribute)) for attribute in backends.REQUIRED)


def test_the_bundle_spec_lists_every_dynamically_loaded_package():
    """A frozen build must be told what the registries load by name.

    `backends` and `payloads` are discovered with `pkgutil.iter_modules`, which is what
    makes a remote or a container format deletable. A bundler reads `import` statements,
    finds neither, and produces an executable that starts and can neither open an
    `.ezhex` nor build one - `iter_modules` has no directory to walk inside a one-file
    archive either.

    So the spec carries them as `hiddenimports`. This checks the spec still names both
    packages, because the failure it prevents does not appear until someone runs the
    frozen build.
    """
    spec = (ROOT / "packaging" / "afterglow.spec").read_text()
    for package in ("afterglow.backends", "afterglow.payloads"):
        assert f'collect_submodules("{package}")' in spec, (
            f"{package} is loaded dynamically and must be in hiddenimports")

    # And the data `paths.root()` looks for has to arrive together, keeping its names.
    for marker in ("library", "scaffolds", "icons"):
        assert f'"afterglow/{marker}"' in spec, f"{marker} is not bundled"

    # The USB link helper too: three modules quote its path in an error, and
    # `paths.usable_helper` cannot copy out a file the bundle never carried.
    assert '"afterglow/linux"' in spec, "the USB link helper is not bundled"
