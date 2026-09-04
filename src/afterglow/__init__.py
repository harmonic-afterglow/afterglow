"""afterglow"""

# The project's own page, used by the interface to send someone to the README. Kept here
# rather than read from package metadata because a frozen build has no `dist-info` to
# read; `test_the_homepage_matches_the_packaging_metadata` keeps it honest against
# `pyproject.toml`.
HOMEPAGE = "https://github.com/harmonic-afterglow/afterglow"


def _resolve_version() -> str:
    """What build this is, answered in the way that suits how it was obtained.

    Three sources, most specific first:

    1. `_build.py`, written by the bundle workflow. This is the only one that can
       identify a downloaded executable: a frozen build carries no `dist-info`, so
       package metadata is unavailable, and a tag build and a push build of the same
       commit have to be distinguishable.
    2. Installed package metadata, for `pip install`.
    3. The version declared in `pyproject.toml`, for a plain checkout.

    Never raises. A version string is for telling someone which build they are running,
    and failing to produce one must not stop the application starting.
    """
    try:
        from ._build import VERSION            # type: ignore[attr-defined]
        return VERSION
    except Exception:                           # noqa: BLE001
        pass
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("afterglow")
        except PackageNotFoundError:
            pass
    except Exception:                           # noqa: BLE001
        pass
    return _declared_version()


def _declared_version() -> str:
    """The version in `pyproject.toml`, for a checkout that was never installed."""
    import tomllib
    from pathlib import Path

    candidate = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
    try:
        return tomllib.loads(candidate.read_text())["project"]["version"]
    except Exception:                           # noqa: BLE001
        return "unknown"


__version__ = _resolve_version()
