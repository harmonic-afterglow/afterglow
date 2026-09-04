"""Where the user's own files land, on each platform.

`data_dir()` holds the private device library - devices dumped or learned off the user's
own hardware - and `cache_dir()` holds disposable records from optional sources. The XDG
layout is not used unconditionally: on Windows and macOS it puts the library somewhere
the operating system does not look, back up or clear, making a cache permanent and a
library invisible.

Most users are expected to be on Windows or macOS, neither of which has been tested
against real hardware, so the parts checkable without a remote are worth pinning down.
"""
import sys

import pytest

from afterglow import paths


@pytest.fixture(autouse=True)
def _no_xdg(monkeypatch):
    """The XDG variables win everywhere; clear them so the fallback is what is tested."""
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    paths.data_dir.cache_clear()
    paths.cache_dir.cache_clear()
    yield
    paths.data_dir.cache_clear()
    paths.cache_dir.cache_clear()


def resolve(monkeypatch, platform, env=None):
    monkeypatch.setattr(sys, "platform", platform)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    paths.data_dir.cache_clear()
    paths.cache_dir.cache_clear()
    return paths.data_dir(), paths.cache_dir()


def test_linux_uses_the_xdg_layout(monkeypatch):
    """Unchanged, deliberately: an existing Linux install must keep its library."""
    data, cache = resolve(monkeypatch, "linux")
    assert data.as_posix().endswith(".local/share/afterglow")
    assert cache.as_posix().endswith(".cache/afterglow")


def test_macos_uses_library_not_dotfiles(monkeypatch):
    data, cache = resolve(monkeypatch, "darwin")
    assert "Library/Application Support/afterglow" in data.as_posix()
    assert "Library/Caches/afterglow" in cache.as_posix()
    assert ".local" not in data.as_posix()


def test_windows_uses_localappdata(monkeypatch):
    data, cache = resolve(monkeypatch, "win32",
                          {"LOCALAPPDATA": r"C:\Users\somebody\AppData\Local"})
    assert "AppData" in str(data) and str(data).endswith("afterglow")
    assert "Cache" in str(cache)
    assert ".local" not in data.as_posix()


def test_windows_falls_back_when_localappdata_is_unset(monkeypatch):
    """A stripped environment (a service, a bare shell) must still resolve somewhere."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    data, _cache = resolve(monkeypatch, "win32")
    assert str(data).endswith("afterglow")


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_an_explicit_xdg_setting_always_wins(monkeypatch, tmp_path, platform):
    """Honoured on every platform, so a test or a packaged build can redirect it."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "c"))
    paths.data_dir.cache_clear()
    paths.cache_dir.cache_clear()
    assert paths.data_dir() == tmp_path / "d" / "afterglow"
    assert paths.cache_dir() == tmp_path / "c" / "afterglow"


def test_user_data_is_never_inside_the_installed_package():
    """The distinction `paths` exists to keep: shipped data versus the user's own.
    Conflating them is how a project once got saved inside the package."""
    shipped = paths.root().resolve()
    for user_path in (paths.data_dir(), paths.cache_dir(), paths.user_library()):
        assert shipped not in user_path.resolve().parents
        assert user_path.resolve() != shipped


def test_the_windows_dll_names_are_among_the_ones_we_try():
    """libconcord is autotools/libtool with `-version-info 6:0:0`, so a MinGW build is
    `libconcord-6.dll`. None of the Unix names match it, and on Windows
    `ctypes.util.find_library` only looks for an exact `concord.dll` on PATH."""
    from afterglow import concord

    assert "libconcord-6.dll" in concord.LIBRARY_NAMES
    assert any(n.endswith(".dylib") for n in concord.LIBRARY_NAMES)
    assert any(n.endswith(".so.6") for n in concord.LIBRARY_NAMES)
