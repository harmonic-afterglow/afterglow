"""Where the data that ships with the application lives.

Four folders are not code but are not optional either - the device library, the
protocol and remote definitions, the remote's own artwork, and the scaffold each build
starts from. Every module that needed one used to count directories up from its own
`__file__`, which meant nine separate hardcoded answers to the same question and a
guarantee that moving the package would break all of them in different ways.

So it is asked once, here, by looking for the folders rather than by counting: walk up
from this file until a directory holds them. That works whether the package sits at the
top of a checkout, inside a `src/` folder, or installed with its data alongside, and it
does not care how deeply the module asking happens to be nested.
"""
from __future__ import annotations

import contextlib
from functools import lru_cache
import os
import sys
from pathlib import Path

# What marks the directory as the one: a checkout or an installed application has these
# beside the package. Only `library` is required - the others are checked so that a
# half-populated parent directory cannot win over the real one.
MARKERS = ("library", "scaffolds", "icons")


@lru_cache(maxsize=1)
def root() -> Path:
    """The directory the shipped data sits in.

    Inside the package when installed, so that `pip install` carries it; still found by
    looking rather than by counting, so a checkout that keeps it elsewhere works too.
    """
    # A frozen build unpacks its data beside the interpreter rather than beside the
    # source, so ask the bundler before looking at `__file__` - which inside a one-file
    # executable points into a temporary extraction directory that holds no markers.
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidate = Path(bundled)
        for folder in (candidate, candidate / "afterglow"):
            if all((folder / marker).is_dir() for marker in MARKERS):
                return folder
    here = Path(__file__).resolve()
    for folder in (here.parent, *here.parents):
        if all((folder / marker).is_dir() for marker in MARKERS):
            return folder
    # Nothing found: fall back to the historical answer - the directory containing the
    # package - so the failure is a missing file with a sensible path in the message
    # rather than an exception from here.
    return here.parent.parent


# What the application ships is one question; where the person using it keeps their own
# files is another, and conflating them is how dialogs ended up offering to save a
# project inside the package. Data moved in there deliberately; user files must not.
def _home() -> Path:
    """The user's home, or the working directory when the platform cannot say.

    `Path.home()` raises `RuntimeError: Could not determine home directory` when the
    environment does not name one - a scrubbed subprocess on Windows has no `USERPROFILE`,
    and the removability tests spawn exactly that. Nothing here is important enough to
    make *importing the application* fail, so fall back rather than raise.
    """
    try:
        return Path.home()
    except RuntimeError:
        return Path.cwd()


def _xdg(name: str) -> Path | None:
    """One XDG variable, or None when it is unset or unusable.

    The Base Directory Specification requires these to be absolute and says an
    implementation encountering a relative path "should consider the path invalid and
    ignore it". That is not pedantry here: a relative value resolves against the current
    working directory, so the library and the cache would land somewhere different
    depending on where the application was started - the exact failure `app_dir()` was
    changed to stop having.
    """
    value = os.environ.get(name)
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else None


def _documents_root() -> Path:
    """This user's documents folder, however the platform spells it.

    Linux records it in `~/.config/user-dirs.dirs` rather than the environment, and it is
    localised - a German desktop has `Dokumente` - so the file is read before guessing.
    Falls back to `~/Documents`, then to the home directory, which always exists.
    """
    configured = _xdg("XDG_DOCUMENTS_DIR")
    if configured:
        return configured
    if sys.platform not in ("win32", "darwin"):
        user_dirs = Path.home() / ".config" / "user-dirs.dirs"
        try:
            for line in user_dirs.read_text().splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "XDG_DOCUMENTS_DIR":
                    value = value.strip().strip('"')
                    return Path(os.path.expandvars(
                        value.replace("$HOME", str(Path.home())))).expanduser()
        except OSError:
            pass
    home = _home()
    documents = home / "Documents"
    return documents if documents.is_dir() else home


@lru_cache(maxsize=1)
def app_dir() -> Path:
    """Where the user's *own* files go - projects, dumps, built configurations.

    Their documents folder, not application data. These are files a person opens, names
    and looks for again, so they belong somewhere visible: `Documents/Afterglow`, beside
    everything else they own.

    The device library and prepared logos live here too, in `Library` and `Logos`: they
    are the user's own devices and pictures, and the first thing anyone sharing a problem
    was asked to dig out of a hidden folder. Only plumbing stays in `data_dir()` - the
    instance lock and the copied helper scripts - and disposable downloads in
    `cache_dir()`, neither of which belongs in a folder a sync client uploads.

    Never the source checkout: an installed copy has no writable one, and a frozen
    executable's directory is read-only.

    `AFTERGLOW_HOME` overrides it, which is how a checkout keeps its files local during
    development and how a test redirects them.
    """
    configured = os.environ.get("AFTERGLOW_HOME")
    folder = (Path(configured).expanduser() if configured
              else _documents_root() / "Afterglow")
    # Created on demand, and failure to create it is not fatal: this answers "where do
    # this user's files go", and a read-only or unwritable location is still the right
    # answer to show in a save dialog.
    with contextlib.suppress(OSError):
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def _platform_root(kind: str) -> Path:
    """Where this platform keeps per-user `cache` or `data`.

    The XDG variables are honoured first by both callers, so a Linux user who has set
    them keeps getting what they asked for, and a test can redirect either directory.
    This is only the fallback when nothing is configured.

    The XDG layout is not used unconditionally: on Windows and macOS it would put a
    user's learned devices somewhere the operating system does not look, back up or
    clear, making a cache permanent and a library invisible.
    """
    if sys.platform == "win32":
        # Both live under LOCALAPPDATA: it is per-machine and excluded from roaming
        # profiles, which is right for a device library and for disposable records.
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base).expanduser() if base else Path.home() / "AppData" / "Local"
        return root if kind == "data" else root / "Cache"
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" if kind == "data"
                else Path.home() / "Library" / "Caches")
    return Path.home() / (".local/share" if kind == "data" else ".cache")


@lru_cache(maxsize=1)
def cache_dir() -> Path:
    """Cache for optional records fetched from explicitly enabled data sources.

    Source records are neither shipped application data nor project data.  Keeping them
    under the platform's cache root means they can be discarded at any time without
    breaking a saved project, and avoids writing generated data into a checkout.
    """
    configured = _xdg("XDG_CACHE_HOME")
    if configured:
        return configured / "afterglow"
    return _platform_root("cache") / "afterglow"


@lru_cache(maxsize=1)
def data_dir() -> Path:
    """Private application plumbing: the instance lock and the copied helper scripts.

    Unlike :func:`app_dir`, nothing here is a file a person opens, and unlike
    :func:`root`, it is never part of the installed package or source checkout. The
    device library used to live here; :func:`adopt_previous_library` moves it.
    """
    configured = _xdg("XDG_DATA_HOME")
    if configured:
        return configured / "afterglow"
    return _platform_root("data") / "afterglow"


def user_library(*parts) -> Path:
    """The current user's dumped, learned and saved devices, in `Documents/Afterglow`."""
    return app_dir().joinpath("Library", *parts)


def logos_dir() -> Path:
    """Logos prepared for the favourites grid, which projects refer to by path."""
    return app_dir() / "Logos"


# What a previous version left in application data, and what it was renamed to once
# moved, so a second start does not move it again and nothing is deleted.
MOVED_SUFFIX = "-moved-to-Documents"


def _merge_into(source: Path, target: Path) -> int:
    """Copy every file under `source` that `target` does not already have."""
    import shutil
    copied = 0
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        destination = target / item.relative_to(source)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        copied += 1
    return copied


def adopt_previous_library(old_logos: Path | None = None) -> list[str]:
    """Bring the device library (and logos) from where earlier versions kept them.

    Called once at start-up by the application, never on import: a test or a script
    must not reach into the real application data. The library is copied and the old
    folder renamed, so it is never used again and never lost. Logos are only copied:
    saved projects name the old files by path, and must keep building.
    """
    notes = []
    old = data_dir() / "library"
    if old.is_dir():
        copied = _merge_into(old, user_library())
        with contextlib.suppress(OSError):
            old.rename(old.with_name(old.name + MOVED_SUFFIX))
        if copied:
            notes.append(f"moved {copied} library files from {old} to {user_library()}")
    if old_logos is not None and old_logos.is_dir() and old_logos != logos_dir():
        copied = _merge_into(old_logos, logos_dir())
        if copied:
            notes.append(f"copied {copied} logos from {old_logos} to {logos_dir()}")
    return notes


def library(*parts) -> Path:
    """The shared device, protocol and remote definitions."""
    return root().joinpath("library", *parts)


def icons(*parts) -> Path:
    """The glyphs and artwork extracted from the remote's firmware."""
    return root().joinpath("icons", *parts)


def branding(*parts) -> Path:
    """Application artwork: the window icon and the mark."""
    return root().joinpath("branding", *parts)


def helper(*parts) -> Path:
    """Scripts the user runs themselves, outside the application.

    `linux/harmony_net.sh` needs root and stays running, so it is invoked from a terminal
    rather than by Afterglow. It still has to be *found*, which it was not: it lived at
    the top of the checkout, shipped with neither an install nor a bundle, and the
    messages naming it quoted a path that exists only in a source tree.
    """
    return root().joinpath("linux", *parts)


def usable_helper(name: str) -> Path:
    """A helper script at a stable path the user can actually run.

    The shipped copy is inside the package, which is fine for a checkout and wrong
    everywhere else: an installed one sits under `site-packages`, and a frozen one lives
    in a temporary extraction directory that is mode 700 and disappears when the process
    exits - so `sudo <that path>` fails, or works once and then vanishes.

    Copy it beside the user's own files instead, where the path is stable, predictable and
    the same sentence in every deployment. Refreshed whenever the shipped copy differs, so
    an upgrade does not leave a stale script behind.
    """
    source = helper(name)
    if not source.is_file():
        return source
    target = data_dir() / "linux" / name
    # The whole set, not just the file asked for: `install_harmony_udev.sh` installs
    # `99-harmony-usbnet.rules` from beside itself, so materialising one script without
    # its rule would leave a copy that cannot do its job.
    for candidate in sorted(source.parent.iterdir()):
        if not candidate.is_file():
            continue
        beside = target.parent / candidate.name
        if beside.is_file() and beside.read_bytes() == candidate.read_bytes():
            continue
        beside.parent.mkdir(parents=True, exist_ok=True)
        beside.write_bytes(candidate.read_bytes())
        beside.chmod(0o755 if candidate.suffix == ".sh" else 0o644)
    return target


def scaffolds(*parts) -> Path:
    """The unpacked configuration each build starts from, per remote model."""
    return root().joinpath("scaffolds", *parts)
