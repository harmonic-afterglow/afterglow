"""The launcher must not shadow the package it launches.

`afterglow.py` sits beside `src/afterglow/`, and Python puts a script's own directory on
the path before anything else. So without care `import afterglow` finds the launcher -
a module with no submodules - and every `from afterglow.gui import ...` fails with
"'afterglow' is not a package", which breaks the whole suite.

The launcher avoids it by putting `src/` ahead of its own directory. These tests hold
that arrangement in place, because the failure appears far from its cause.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "afterglow.py"


def test_the_launcher_exists_and_is_runnable():
    assert LAUNCHER.is_file()
    assert LAUNCHER.read_text().startswith("#!")


def run(code, cwd):
    """Run a snippet with the launcher's directory on the path, the way Python sets it
    up for `python3 afterglow.py`."""
    prelude = (f"import sys; sys.path.insert(0, {str(ROOT)!r})\n"
               f"exec(open({str(LAUNCHER)!r}).read().split('from afterglow.gui')[0],"
               f" {{'__file__': {str(LAUNCHER)!r}}})\n"
               f"sys.path.insert(0, {str(ROOT / 'src')!r})\n")
    return subprocess.run([sys.executable, "-c", prelude + code],
                          capture_output=True, text=True, cwd=cwd)


@pytest.mark.parametrize("cwd", [ROOT, ROOT.parent], ids=["in-folder", "from-outside"])
def test_import_afterglow_finds_the_package_not_the_launcher(cwd):
    done = run("import afterglow; print(afterglow.__file__)", cwd)
    assert done.returncode == 0, done.stderr
    found = Path(done.stdout.strip())
    assert found == ROOT / "src" / "afterglow" / "__init__.py", found


def test_the_package_is_importable_as_a_package(tmp_path):
    """The symptom the shadowing actually produces."""
    done = run("from afterglow import ezhex, paths, vocabulary; print('ok')", tmp_path)
    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


def test_the_application_finds_its_data_from_anywhere(tmp_path):
    """Shipped data is found by where the code is; the user's files are found per user.

    `app_dir()` is one folder per user, never the source checkout: an installed copy has
    no writable one and would fall through to the working directory, putting the same
    action in a different place depending on where the terminal was. It is also the only
    answer that survives being bundled into a read-only executable.
    """
    done = run("from afterglow import paths\n"
               "print(paths.app_dir())\n"
               # No protocol library is shipped: definitions come from the imported
               # configuration or an archive record. The remotes it *does* ship still
               # have to be found.
               "assert paths.library('remotes').is_dir(), 'no remote profiles'\n"
               "assert paths.user_library().parent == paths.data_dir(), 'wrong private library'\n"
               "assert paths.icons('buttons').is_dir(), 'no artwork'\n"
               "assert paths.scaffolds('harmony-900').is_dir(), 'no scaffold'\n",
               tmp_path)
    assert done.returncode == 0, done.stderr
    reported = Path(done.stdout.strip())
    assert reported != ROOT, "the user's files must not be written into the application"
    assert reported != tmp_path, "nor into whatever directory it happened to start in"

    # And it is the same answer wherever it is run from, which is the property that makes
    # a saved project findable again.
    elsewhere = run("from afterglow import paths\nprint(paths.app_dir())\n",
                    tmp_path.parent)
    assert Path(elsewhere.stdout.strip()) == reported


def test_the_self_check_detects_a_bundle_that_would_start_and_do_nothing(tmp_path,
                                                                        monkeypatch):
    """`--self-check` is what the bundle workflow runs before publishing.

    A frozen build can launch perfectly and be useless: the backend and payload
    registries resolve members by name, which a bundler's static analysis cannot see, so
    a naive build produces an application that can neither open an `.ezhex` nor write
    one. That is invisible until someone tries to use it.
    """
    # `selfcheck.run` imports `afterglow.gui` on purpose: a bundle that cannot start its
    # interface is exactly what this is looking for. So the check needs Qt to pass, and
    # without it the correct outcome is to skip rather than to report a failure.
    pytest.importorskip("PyQt6.QtWidgets")
    done = subprocess.run([sys.executable, str(ROOT / "afterglow.py"), "--self-check"],
                          capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "self-check OK" in done.stdout
    assert "harmony-pk" in done.stdout and "pk" in done.stdout

    # And it must actually fail when a registry comes up empty, or it guards nothing.
    # The check lives in the package, not the launcher: a frozen build cannot use
    # `afterglow.py` as its entry point, because a script named after the package
    # shadows it in the extraction directory.
    from afterglow import payloads, selfcheck

    monkeypatch.setattr(payloads, "names", lambda: [])
    assert selfcheck.run() == 1


def test_the_users_files_go_to_their_documents_not_application_data(tmp_path,
                                                                   monkeypatch):
    """Projects and built configurations are files a person opens by hand.

    They belong somewhere visible - `Documents/Afterglow` - not in application data,
    which is hidden on Linux and buried on Windows. The application's *own* storage
    (the device library, the copied link helper) stays in `data_dir()`, because nobody
    opens those.

    Linux records the documents folder in `~/.config/user-dirs.dirs` rather than the
    environment, and it is localised, so the file is read before guessing at `Documents`.
    """
    from afterglow import paths

    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / "Dokumente").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text(
        'XDG_DOCUMENTS_DIR="$HOME/Dokumente"\n')

    monkeypatch.delenv("AFTERGLOW_HOME", raising=False)
    monkeypatch.delenv("XDG_DOCUMENTS_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    paths.app_dir.cache_clear()
    try:
        assert paths.app_dir() == home / "Dokumente" / "Afterglow"
        assert paths.app_dir() != paths.data_dir(), (
            "the user's documents and the application's storage are different places")
    finally:
        paths.app_dir.cache_clear()


def test_a_relative_xdg_variable_is_ignored_rather_than_obeyed(monkeypatch, tmp_path):
    """The Base Directory Specification requires these to be absolute.

    It says an implementation encountering a relative path "should consider the path
    invalid and ignore it", and that is not pedantry: a relative value resolves against
    the current working directory, so the device library would be in a different place
    depending on where the application was started - the same failure that made
    `app_dir()` return the source checkout or the terminal's directory by turns.
    """
    from afterglow import paths

    monkeypatch.setenv("XDG_DATA_HOME", "relative/path")
    paths.data_dir.cache_clear()
    try:
        assert paths.data_dir().is_absolute()
        assert "relative" not in str(paths.data_dir())

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        paths.data_dir.cache_clear()
        assert paths.data_dir() == tmp_path / "afterglow", (
            "an absolute value must still be honoured")
    finally:
        paths.data_dir.cache_clear()


def test_importing_the_interface_touches_no_filesystem_and_needs_no_home(tmp_path):
    """Importing a module must not resolve, create, or require anything on disk.

    `gui/constants.py` had `ROOT = paths.app_dir()` at module scope, so importing the
    interface resolved the user's documents folder and *created a directory* as a side
    effect - and raised outright where the platform cannot name a home, which is what a
    scrubbed subprocess on Windows gets: `RuntimeError: Could not determine home
    directory`. It took down three removability tests, which spawn exactly that.
    """
    # The subprocess imports the interface, so this needs Qt even though what it asserts
    # is about the filesystem.
    pytest.importorskip("PyQt6.QtWidgets")
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
        "import afterglow.gui.constants as constants\n"
        "print(callable(constants.user_files))\n"
    )
    # No HOME, no USERPROFILE: the condition the runner produced.
    environment = {"PATH": os.environ.get("PATH", ""),
                   "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          cwd=tmp_path, env=environment)
    assert done.returncode == 0, done.stderr
    assert "True" in done.stdout, "the user directory must be a call, not a constant"
