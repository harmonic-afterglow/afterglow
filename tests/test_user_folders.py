"""The folders a person's own files go in, and the themes kept there."""
from __future__ import annotations

import shutil

from afterglow import paths, themes


def test_start_up_creates_a_folder_for_each_kind_of_file_and_keeps_an_old_projects_one():
    home = paths.app_dir()
    old = home / "projects"
    for kind in paths.FOLDERS:
        shutil.rmtree(home / paths.FOLDERS[kind], ignore_errors=True)
    old.mkdir(parents=True, exist_ok=True)
    (old / "kept.json").write_text("{}")
    try:
        paths.prepare_user_folders()
        for name in paths.FOLDERS.values():
            assert (home / name).is_dir()
        # shareable projects used to unpack into a lowercase folder; it is the same one now
        assert (home / "Projects" / "kept.json").is_file()
    finally:
        for name in paths.FOLDERS.values():
            shutil.rmtree(home / name, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)


def test_each_themed_remote_gets_an_example_that_is_never_offered():
    try:
        notes = themes.seed_examples()
        example = themes.folder("harmony-one") / themes.EXAMPLE
        assert (example / themes.MANIFEST).is_file()
        assert notes and str(example) in notes[0]
        assert themes.names("harmony-one") == []
        assert themes.path("harmony-one", themes.EXAMPLE) is None
        # an owner's copy of it is a theme, found by its name
        shutil.copytree(example, themes.folder("harmony-one") / "Mario")
        assert themes.names("harmony-one") == ["Mario"]
        assert themes.path("harmony-one", "Mario") == themes.folder("harmony-one") / "Mario"
        assert themes.path("harmony-one", "../Mario") is None
        # and it is not copied again
        assert themes.seed_examples() == []
        # only a remote whose profile offers themes gets a folder
        assert not themes.folder("harmony-900").exists()
    finally:
        shutil.rmtree(paths.user_folder("themes"), ignore_errors=True)
