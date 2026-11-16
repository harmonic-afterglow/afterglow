"""Every tool says what it does when asked, and asking changes nothing: one run with
--help rewrote twelve of the 800's scaffold pictures, another tried to reach a remote."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = sorted(path.name for path in (ROOT / "tools").glob("*.py")
               if not path.name.startswith("_"))


def _tree() -> dict:
    """Every file the tools could write: the shipped package and the tools."""
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in ("src", "tools") for path in (ROOT / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts}


@pytest.fixture(scope="module")
def before():
    return _tree()


@pytest.mark.slow
@pytest.mark.parametrize("tool", TOOLS)
def test_help_says_and_does_nothing(tool, before):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    run = subprocess.run([sys.executable, str(ROOT / "tools" / tool), "--help"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip()
    assert _tree() == before


def test_the_800_artwork_fitter_needs_to_be_told(tmp_path):
    run = subprocess.run([sys.executable, str(ROOT / "tools/harmony_800_fit_artwork.py")],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert run.returncode == 2 and "--apply" in run.stderr
