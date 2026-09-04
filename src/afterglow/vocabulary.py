"""What a remote can be told, read from the remote's own profile.

The device types, the activity types and the physical keys are not one list shared by
every Harmony. They come out of each model's own firmware - one movie clip per type in
its `app-main.swf`, and whatever buttons its case actually has. A remote without a
touchscreen has no screen buttons; one with fewer keys has fewer slots. Holding them as
constants in the code said, wrongly, that every remote is a Harmony 900.

So they live in `library/remotes/<model>.json` beside the rest of what identifies a
remote, and this module is the way to ask for them. The identifiers are Logitech's. The
readable labels are this project's: the firmware has no name table for either set, and the
friendly names the web configurator showed went away with the service.

`for_remote()` takes a profile, an id, or nothing - and with nothing it answers for the
only model Afterglow will write for. The module-level names below are that same answer,
kept so the ordinary case reads as plainly as it did when this was a hardcoded list.
"""
from __future__ import annotations

from functools import lru_cache

from . import remotes


@lru_cache(maxsize=8)
def _profile(remote_id: str | None):
    if remote_id:
        return remotes.get(remote_id)
    # No remote named: the one this build is for. Only verified models can be written,
    # and exactly one is, so "the verified one" is unambiguous today - and the moment a
    # second appears this raises rather than silently answering for the wrong remote.
    verified = [p for p in remotes.load_all() if p.verified]
    if len(verified) == 1:
        return verified[0]
    raise remotes.UnknownRemote(
        "which remote's vocabulary? more than one model is verified, so it has to be "
        "named: vocabulary.for_remote('harmony-900')")


def for_remote(remote=None):
    """The profile whose vocabulary applies. Accepts a profile, an id, or nothing."""
    if isinstance(remote, remotes.RemoteProfile):
        return remote
    return _profile(remote)


def device_types(remote=None) -> dict:
    """{identifier: readable label}, in the order to offer them."""
    return for_remote(remote).device_types


def activity_types(remote=None) -> list:
    """[(label, identifier)] in menu order, which is neither alphabetical nor the order
    the identifiers sort in."""
    return for_remote(remote).activity_types


def hard_keys(remote=None) -> list:
    """The physical buttons, by the name a configuration calls them."""
    return for_remote(remote).hard_keys


# The same answers for the single model Afterglow writes for. Kept as names because most
# of the interface has no reason to ask about a remote it is not building for.
DEVICE_TYPE_LABELS = device_types()
DEVICE_TYPES = list(DEVICE_TYPE_LABELS)
ACTIVITY_TYPES = activity_types()
HARD_KEYS = hard_keys()
