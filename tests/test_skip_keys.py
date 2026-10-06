"""The transport skip keys send the device's own skip, whatever the device calls it.

A DVD player's skip is ChapterNext, a CD player's NextTrack; only a command named
SkipForward/SkipBack used to land on the keys, so on most devices both did nothing.
"""
from afterglow import project_devices, remotes

KEYS = remotes.get("harmony-900").hard_keys


def _device(*names, **bound):
    return {"id": "1", "label": "DVD",
            "commands": [[n, n, "", "", bound.get(n)] for n in names]}


def test_a_chapter_or_track_skip_goes_on_the_skip_keys():
    assert project_devices.free_key_assignments(
        {"ChapterNext": None, "ChapterPrev": None, "Play": "Play"}, KEYS) == \
        {"ChapterNext": "SkipForward", "ChapterPrev": "SkipBack"}
    assert project_devices.free_key_assignments(
        {"NextTrack": None, "PreviousTrack": None}, KEYS) == \
        {"NextTrack": "SkipForward", "PreviousTrack": "SkipBack"}


def test_a_key_already_bound_is_left_alone():
    assert project_devices.free_key_assignments(
        {"SkipForward": "SkipForward", "NextChapter": None, "Replay": None}, KEYS) == \
        {"Replay": "SkipBack"}


def test_a_remote_without_the_keys_gets_nothing():
    assert project_devices.free_key_assignments({"ChapterNext": None}, ["Play"]) == {}


def test_an_existing_project_is_filled_once():
    project = {"devices": [_device("ChapterNext", "ChapterPrev")]}
    assert project_devices.fill_free_keys(project, KEYS) == 2
    commands = project["devices"][0]["commands"]
    assert [c[4] for c in commands] == ["SkipForward", "SkipBack"]
    commands[0][4] = None                         # its owner clears one on purpose
    assert project_devices.fill_free_keys(project, KEYS) == 0
    assert commands[0][4] is None


def test_an_imported_configuration_keeps_its_keys_as_they_were(configs, unpacked):
    """An owner who left a skip key empty meant it."""
    import contextlib
    import io
    from afterglow.importer import build_project
    with contextlib.redirect_stdout(io.StringIO()):
        project = build_project(str(unpacked(configs[0])))
    before = [[c[4] for c in d["commands"]] for d in project["devices"]]
    project_devices.fill_free_keys(project, KEYS)
    assert [[c[4] for c in d["commands"]] for d in project["devices"]] == before
