"""Prove a built copy has everything it needs, without opening a window.

Lives in the package rather than in the launcher because the launcher cannot be the
bundle's entry point: it is called `afterglow.py`, the package is called `afterglow`, and
in a frozen build the entry script sits in the extraction directory where it *shadows the
package it is trying to import*. The dev launcher and `packaging/main.py` both call in
here instead.
"""
from __future__ import annotations

from importlib import import_module


def run() -> int:
    """Return 0 when this copy can actually do its job, 1 with reasons when it cannot.

    A bundle can start perfectly and be useless. The backend and payload registries
    resolve their members by name at runtime, which a bundler's static analysis cannot
    see, so a naive build produces an application that launches and can neither open an
    `.ezhex` nor write one. The shipped data has the same problem from the other side:
    it is found by looking for `library`, `scaffolds` and `icons`, which a bundle has to
    carry under those names.

    Neither failure is visible until someone tries to use the thing, which is far too
    late. This checks both and is what the bundle workflow runs before publishing.
    """
    from . import backends, paths, payloads, remotes

    problems: list[str] = []

    installed = backends.installed()
    if not installed:
        problems.append("no infrared backends resolved (the bundle is missing them)")
    for name in installed:
        try:
            backends.get(name)
        except Exception as exc:                                   # noqa: BLE001
            problems.append(f"backend {name!r} does not load: {exc}")

    names = payloads.names()
    if not names:
        problems.append("no container payloads resolved (cannot open or write .ezhex)")
    for name in names:
        try:
            payloads.get(name)
        except Exception as exc:                                   # noqa: BLE001
            problems.append(f"payload {name!r} does not load: {exc}")

    for marker in ("icons", "scaffolds", "branding"):
        if not (paths.root() / marker).is_dir():
            problems.append(f"shipped data is missing: {marker}")
    if not paths.helper("harmony_net.sh").is_file():
        problems.append("the USB link helper is missing")

    profiles = [profile.id for profile in remotes.load_all()]
    if not profiles:
        problems.append("no remote profiles resolved")

    # The interface is the part a bundler is most likely to under-collect, but core code
    # may not import a third-party package - so ask the interface package to import
    # itself, which is a fact about *this* build and not a dependency of this module.
    try:
        import_module("afterglow.gui")
    except Exception as exc:                                       # noqa: BLE001
        problems.append(f"the interface does not load: {exc}")

    if problems:
        print("Afterglow self-check FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"Afterglow self-check OK: backends {sorted(installed)}, "
          f"payloads {sorted(names)}, remotes {sorted(profiles)}, "
          f"data {paths.root()}")
    return 0


def import_check(config: str) -> int:
    """Read one real configuration, and report what came out.

    `run()` proves the registries resolve. This proves they resolve into something that
    works: unpacking a container, parsing its protocol blocks, converting every command.
    A bundle can pass the first and fail this one - a payload that imports but cannot
    reach its shipped data, say - and the difference matters, because opening a file is
    the first thing anyone will do.
    """
    import contextlib
    import io
    import tempfile

    from . import ezhex, importer

    with tempfile.TemporaryDirectory() as tmp:
        # `ezhex` is the container layer: it reads the header and hands the payload to
        # whichever module claims it, which is the same route the interface takes.
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(config, tmp)
        # Then the dispatcher, which picks the backend from the configuration's own
        # header. Naming one backend here would tie a general check to one remote.
        project = importer.build_project(tmp)

    kinds: dict[str, int] = {}
    for device in project["devices"]:
        for signal in (device.get("signals") or {}).values():
            kinds[signal["kind"]] = kinds.get(signal["kind"], 0) + 1
    opaque = kinds.get("backend-opaque", 0)
    print(f"imported {len(project['devices'])} devices, signals {kinds}")
    if opaque:
        print(f"  {opaque} command(s) did not convert")
        return 1
    return 0


def concord_check() -> int:
    """Report whether the remote library is reachable, and from where.

    Loading it is the one thing a bundle cannot be assumed to do. `ctypes.CDLL(name)`
    asks the system loader, which knows nothing about a frozen archive, so a bundled copy
    would sit unused beside the executable while the application reported it missing -
    `concord._load()` looks in `sys._MEIPASS` first for exactly that reason, and this
    proves the lookup works rather than assuming it.

    A missing library is not a failure here. Everything except reading from and writing
    to the remote works without it, and that is the difference this prints.
    """
    from . import concord

    if not concord.available():
        status, explanation = concord.link_support()
        print("libconcord: NOT available - authoring and building still work")
        # A library that was bundled and refused to load is a different problem from one
        # that was never bundled, and only the loader knows which happened.
        for failure in concord.LOAD_ERRORS:
            print(f"  found but did not load: {failure}")
        print(f"  platform link support: {status}")
        print(f"  {explanation}")
        return 1
    print(f"libconcord: available ({concord._load()._name})")
    return 0
