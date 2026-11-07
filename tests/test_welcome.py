"""The welcome after a write: a project's "first flash only" decided from what the remote
holds before the write, through each backend's `afterglow_built`."""
from __future__ import annotations

from pathlib import Path

import pytest

from afterglow import welcome

ROOT = Path(__file__).resolve().parents[1]
LOGITECH_650 = sorted((ROOT / "configs" / "650").glob("*.ezhex")) if (
    ROOT / "configs" / "650").is_dir() else []


def _project(remote="harmony-one", **settings):
    return {"devices": [], "activities": [],
            "settings": {"remote": remote, **settings}}


def _ours() -> bytes:
    from afterglow.backends.harmony_one import generate
    return bytes(generate.build(_project(), stamp_fields=(0, 0, 12, 0, 0, 2026))["image"])


def test_a_project_names_first_flash_only_unless_it_chose_otherwise():
    assert welcome.setting(_project()) == "first"
    assert welcome.setting(_project(welcome="always")) == "always"
    assert welcome.setting(_project(welcome="something else")) == "first"


def test_a_projects_own_choice_wins_over_what_the_remote_holds():
    assert welcome.decide(_project(welcome="never"), None) == "never"
    assert welcome.decide(_project(welcome="always"), _ours()) == "always"


def test_first_flash_only_welcomes_a_remote_with_nothing_of_ours():
    assert welcome.decide(_project(), None) == "always"          # nothing could be read
    assert welcome.decide(_project(), b"") == "always"
    assert welcome.decide(_project(), _ours()) == "never"        # one of ours already


@pytest.mark.skipif(not LOGITECH_650, reason="Logitech's 650 configurations")
def test_first_flash_only_welcomes_a_remote_holding_logitechs_configuration():
    assert welcome.decide(_project("harmony-650"),
                          LOGITECH_650[0].read_bytes()) == "always"
