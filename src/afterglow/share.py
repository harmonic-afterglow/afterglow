"""A copy of a configuration that is safe to give to the project.

People hold back their dumps because a configuration can name its owner, and that is the
one thing the project does not need. The remote's backend knows where its format keeps
the owner's identity and replaces it; this module unpacks, asks it to, repacks, and
checks the result differs from the original only where it was meant to.

A remote whose backend cannot say where its owner is recorded gets no copy at all: a file
labelled safe that still carries a name is worse than none.
"""
from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
from pathlib import Path

from . import backends, ezhex, remotes


class NotAnonymisable(RuntimeError):
    """This remote's format cannot yet be cleaned of its owner's identity."""


def make_shareable(source, target) -> list[str]:
    """Write an anonymised copy of `source` to `target`; returns what was changed."""
    source, target = Path(source), Path(target)
    if target.resolve() == source.resolve():
        raise ValueError("the shareable copy must not replace the original")
    header = ezhex._split(source.read_bytes())[0]
    profile = remotes.identify(header)
    anonymise = getattr(backends.for_profile(profile), "anonymise", None)
    if not callable(anonymise):
        raise NotAnonymisable(
            f"Afterglow cannot yet tell where a {profile.model} configuration records "
            "its owner, so it will not label a copy as safe to share.")
    work = Path(tempfile.mkdtemp(prefix="afterglow-share-"))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(str(source), str(work / "tree"))
            changes = anonymise(work / "tree")
            ezhex.pack_standalone(str(work / "tree"), str(work / "copy.ezhex"),
                                  do_rehash=False)
        shutil.copyfile(work / "copy.ezhex", target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return changes
