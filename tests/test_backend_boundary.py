"""Architecture-specific encoders stay behind the backend registry."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "afterglow"
BACKENDS = PACKAGE / "backends"
PORTABLE = (
    PACKAGE / "ir_signal.py",
    PACKAGE / "ir_protocol.py",
    PACKAGE / "project_devices.py",
    PACKAGE / "device_json.py",
)


def outside_backends():
    return [path for path in PACKAGE.rglob("*.py")
            if BACKENDS not in path.parents and path.name != "__init__.py"]


def imported_modules(path: Path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield f"{'.' * node.level}{node.module}"


@pytest.mark.parametrize("path", sorted(outside_backends()),
                         ids=lambda path: str(path.relative_to(PACKAGE)))
def test_shared_code_never_imports_a_concrete_backend(path):
    leaked = [module for module in imported_modules(path)
              if "backends.harmony_pk" in module]
    assert not leaked, (
        f"{path.relative_to(PACKAGE)} imports {leaked}; shared code must select the "
        "profile's backend through afterglow.backends")


@pytest.mark.parametrize("path", PORTABLE, ids=lambda path: path.name)
def test_portable_modules_do_not_import_harmony_native_formats(path):
    imported = set(imported_modules(path))
    for module in ("irproto", "ssir", "protocol_json", "ir_compile"):
        assert module not in imported


def test_every_profile_resolves_a_complete_backend():
    from afterglow import backends, remotes

    for profile in remotes.load_all():
        if (profile.infrared or {}).get("backend"):
            backend = backends.for_profile(profile)
            assert all(callable(getattr(backend, name)) for name in backends.REQUIRED)


def test_registry_can_load_a_new_backend_without_core_changes(monkeypatch):
    from afterglow import backends

    calls = []
    fake = SimpleNamespace(**{
        name: (lambda *args, _name=name, **kwargs: calls.append(_name))
        for name in backends.REQUIRED
    })
    monkeypatch.setattr(
        backends, "import_module",
        lambda name: fake if name.endswith(".example.backend") else None,
    )

    assert backends.get("example") is fake
    fake.lower_devices([])
    assert calls == ["lower_devices"]


def test_pre_rename_backend_names_remain_read_aliases():
    from afterglow import backends

    assert backends.get("harmony-z") is backends.get("harmony-pk")
    assert backends.get("harmony-ziptree") is backends.get("harmony-pk")


def test_portable_protocol_definitions_have_no_native_lowering_metadata():
    """Nothing shipped may carry a remote's native encoding.

    Skips when nothing is shipped. The library is empty by design - protocols are
    generated from an imported configuration - so this guards anything added later
    rather than anything present now, and a green tick would misrepresent that.
    """
    import json

    definitions = sorted((PACKAGE / "library" / "protocols").glob("*.json"))
    if not definitions:
        pytest.skip("no protocols are shipped; the library is generated on import")
    for path in definitions:
        assert "native" not in json.loads(path.read_text()), path.name


def test_no_protocol_catalogue_of_any_kind_is_shipped():
    """The application carries no protocol definitions - native or portable.

    Native blocks are an intermediate that importing produces and building consumes, and
    the portable definitions do not ship either: every protocol comes from the IrProto
    blocks of the configuration being imported, or is generated from an archive record.

    The suite still needs definitions to build from, so it keeps twelve under
    `tests/fixtures/protocols` and points `ir_protocol.LIBRARY` at them (see
    `conftest.py`). This asserts the *product*, which is why it reads the package
    directly rather than the active library.
    """
    native = BACKENDS / "harmony_pk" / "protocols"
    assert not list(native.glob("*.json"))

    shipped = PACKAGE / "library" / "protocols"
    assert not list(shipped.glob("*.json")), (
        "the application must not ship protocol definitions; the suite's live in "
        "tests/fixtures/protocols")

def test_project_devices_reject_native_builder_fields():
    from afterglow import ir_signal, project_devices

    device = {
        "schema": project_devices.SCHEMA,
        "id": "1",
        "label": "Test",
        "type": "Receiver",
        "commands": [["Power", "Power", "", "", None]],
        "signals": {
            "Power": ir_signal.protocol_signal(
                "nec1", {"address": 1, "command": 2}),
        },
        "raw_codes": {"Power": "0x00"},
    }
    with pytest.raises(ValueError, match="backend fields: raw_codes"):
        project_devices.validate(device)


def test_lowering_is_transient_and_does_not_mutate_the_portable_project():
    from copy import deepcopy

    from afterglow import backends, ir_signal, project_devices, remotes

    device = {
        "schema": project_devices.SCHEMA,
        "id": "1",
        "label": "Test",
        "type": "Television",
        "commands": [["Power", "Power", "07", "02", None]],
        "signals": {
            "Power": ir_signal.protocol_signal(
                "samsung32", {"address": 0x07, "command": 0x02}),
        },
    }
    before = deepcopy(device)
    profile = remotes.get("harmony-900")
    lowered = backends.for_profile(profile).lower_devices([device], profile)[0]

    assert device == before
    assert lowered["protocol"] == "e8f716b9ee19"
    definition = lowered["protocol_definitions"]["e8f716b9ee19"]
    assert definition["id"] == "e8f716b9ee19"
    assert definition["element_count"] == 2
    assert "protocol" not in device and "raw_codes" not in device
