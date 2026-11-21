"""What a remote can be told, read from the remote's own profile.

The device types, the activity types and the physical keys are not one list shared by
every Harmony. They come out of each model's own firmware - one movie clip per type in
its `app-main.swf`, and whatever buttons its case actually has. A remote without a
touchscreen has no screen buttons; one with fewer keys has fewer slots. Holding them as
constants in the code said, wrongly, that every remote is a Harmony 900.

So they live in `library/remotes/<model>/profile.json` beside the rest of what identifies a
remote, and this module is the way to ask for them. The identifiers are Logitech's. The
readable labels are this project's: the firmware has no name table for either set, and the
friendly names the web configurator showed went away with the service.

Every question names its remote - a profile, an id, or nothing for `remotes.default()`.
There are deliberately no module-level answers: computed once at import they answered
for one model for the life of the process, whichever remote the project was for.
"""
from __future__ import annotations

from functools import lru_cache
import re

from . import remotes


@lru_cache(maxsize=8)
def _profile(remote_id: str | None):
    return remotes.get(remote_id) if remote_id else remotes.default()


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


def hard_key_layout(remote=None) -> list[dict]:
    """Where the physical buttons sit on the case, for drawing a picture of it."""
    return for_remote(remote).hard_key_layout


# The activity type an activity without one has: "Custom / Other".
GENERIC_ACTIVITY = "VirtualGeneric"


def device_type_choices(remote=None) -> list[str]:
    """The device types as a list offers them: by their readable label, A to Z, as the
    identifiers' order put "A/V switch" among the As by "AudioVideoSwitch" and a set-top
    box forty rows down."""
    labels = device_types(remote)
    return sorted(labels, key=lambda name: labels[name].casefold())


def activity_type_choices(remote=None) -> list:
    """[(label, identifier)] as a list offers them: "Custom / Other" first, the rest by
    label, A to Z."""
    return sorted(activity_types(remote),
                  key=lambda pair: (pair[1] != GENERIC_ACTIVITY, pair[0].casefold()))


# Words in an activity's name that say its type, checked in this order: "Watch a movie on
# TV" is a movie. Each type is used only where the remote has it.
_NAMED = (
    (("movie", "film", "dvd", "blu-ray", "bluray", "blu ray", "cinema"), "VirtualDvd"),
    (("game", "xbox", "playstation", "nintendo", "switch"), "VirtualGameConsole"),
    (("radio",), "VirtualRadioSimple"),
    (("cd",), "VirtualCdMulti"),
    (("tivo",), "VirtualTiVo"),
    (("pvr", "recording", "recordings", "dvr"), "VirtualPvr"),
    (("teletext",), "VirtualTeletext"),
    (("presentation",), "VirtualPresentation"),
    (("picture", "pictures", "photo", "photos"), "VirtualMediaCenterPictures"),
    (("tv", "television"), "VirtualTelevisionN"),
    (("music", "listen"), "VirtualMusicServer"),
)


def activity_type_for_name(name: str, remote=None) -> str | None:
    """The type an activity's name says, for a new activity whose type nobody chose:
    "Watch TV" is Watch TV, "Movie night" Watch a DVD. None where the name says none the
    remote has."""
    pairs = activity_types(remote)
    have = {identifier for _label, identifier in pairs}
    wanted = " ".join(name.casefold().split())
    if not wanted:
        return None
    for label, identifier in pairs:
        if label.casefold() == wanted:
            return identifier
    words = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", wanted))
    for keys, identifier in _NAMED:
        if identifier in have and any(
                (key in words) if " " not in key else (key in wanted) for key in keys):
            return identifier
    return None
