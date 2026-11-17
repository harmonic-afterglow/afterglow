"""A remote that does not answer: ask for it to be plugged in again, and ask it the moment it is back.

Some remotes - a Monster AV-100 (an 880) so far - take requests only in the moment
after they are plugged in. These drive `concord.Remote.identity` against a scripted
libconcord: what it says, in which order it tries things, and what it leaves alone.
"""
import pytest

from afterglow import concord

SILENT = 1                      # get_identity's "Unknown error": nothing came back


class Library:
    """libconcord, scripted: get_identity answers in turn, the remote comes and goes."""

    def __init__(self, answers, present):
        self.answers = list(answers)
        self.present = list(present)
        self.calls = []

    def get_identity(self, *_a):
        self.calls.append("identify")
        return self.answers.pop(0)

    def lc_remote_present(self):
        # the last state lasts
        return self.present.pop(0) if len(self.present) > 1 else self.present[0]

    def init_concord(self):
        self.calls.append("init")
        return 0

    def deinit_concord(self):
        self.calls.append("deinit")

    def lc_cancel(self, _on):
        pass

    def lc_strerror(self, _err):
        return b"Unknown error"


def _remote(library, monkeypatch, said):
    monkeypatch.setattr(concord.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concord, "REPLUG_HINT_AFTER_S", 3600)
    numbers = {"get_skin": 17, "get_arch": 8, "get_fw_ver_maj": 4, "get_fw_ver_min": 4,
               "get_config_bytes_used": 0, "get_config_bytes_total": 0,
               "is_config_dump_supported": 1, "is_config_update_supported": 1}
    for name, value in numbers.items():
        setattr(library, name, lambda value=value: value)
    for name in ("get_mfg", "get_model", "get_codename"):
        setattr(library, name, lambda: b"")
    remote = concord.Remote.__new__(concord.Remote)
    remote.lib = remote._direct = library
    remote._keep_alive = None
    remote._open = True
    remote.on_wait = said.append
    return remote


def test_a_silent_remote_is_asked_to_be_plugged_in_again(monkeypatch):
    said = []
    # there while libconcord waits, still there when asked, then pulled out, then back
    library = Library([SILENT, 0], present=[True, True, False, True])
    identity = _remote(library, monkeypatch, said).identity()
    assert identity["skin"] == 17
    assert said == [concord.REPLUG_ASK]
    assert library.calls == ["identify", "deinit", "init", "identify"]


def test_a_remote_pulled_out_while_waiting_is_asked_the_moment_it_is_back(monkeypatch):
    """libconcord says the remote is gone; it may be back already."""
    said = []
    library = Library([concord.LC_ERROR_CONNECT, 0], present=[True, True])
    _remote(library, monkeypatch, said).identity()
    assert said == [concord.REPLUG_BACK]


def test_a_remote_not_on_hid_is_not_waited_for(monkeypatch):
    """The USB network remotes (900, 1000, 1100) answer slowly for reasons of their own."""
    said = []
    library = Library([SILENT], present=[False])
    with pytest.raises(concord.RemoteError):
        _remote(library, monkeypatch, said).identity()
    assert said == [] and library.calls == ["identify"]


def test_nothing_waits_without_someone_to_tell(monkeypatch):
    library = Library([SILENT], present=[True])
    remote = _remote(library, monkeypatch, [])
    remote.on_wait = None
    with pytest.raises(concord.RemoteError):
        remote.identity()
    assert library.calls == ["identify"]


def test_cancel_stops_the_wait_for_the_remote(monkeypatch):
    said = []
    library = Library([SILENT, SILENT], present=[True])     # never pulled out
    remote = _remote(library, monkeypatch, said)
    remote.on_wait = lambda text: (said.append(text), text == concord.REPLUG_ASK
                                   and remote.cancel())
    with pytest.raises(concord.Cancelled):
        remote.identity()


def test_a_cancelled_identify_says_so():
    library = Library([concord.LC_ERROR_CANCELLED], present=[True])
    remote = concord.Remote.__new__(concord.Remote)
    remote.lib = remote._direct = library
    remote._keep_alive = None
    with pytest.raises(concord.Cancelled):
        remote.identity()


def test_the_early_word_does_not_ask_anyone_to_unplug():
    """While libconcord is still trying, the early word says only that: a remote pulled
    out mid-request is reported as gone and handled as REPLUG_BACK anyway."""
    assert "unplug" not in concord.REPLUG_HINT.lower()
    assert "unplug it" in concord.REPLUG_ASK
    assert "plug it back in" in concord.REPLUG_BACK.lower()
    assert "unplug it" not in concord.REPLUG_BACK


def test_the_wait_is_repeated_with_the_time_left(monkeypatch):
    """A person who missed the ask is told again every half minute, and when the remote
    has been pulled out the reminder asks only for it back."""
    clock = [0.0]
    said = []
    library = Library([SILENT, 0], present=[True] + [True] * 400 + [False] * 200 + [True])
    remote = _remote(library, monkeypatch, said)
    monkeypatch.setattr(concord.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(concord.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    remote.identity()
    assert said[0] == concord.REPLUG_ASK
    assert said[1] == concord.REPLUG_REMIND_UNPLUG.format(left="2:30")
    assert said[2] == concord.REPLUG_REMIND_UNPLUG.format(left="2:00")
    assert concord.REPLUG_REMIND_PLUG.format(left="1:30") in said
    assert all(text.isascii() for text in said)


def test_nobody_waits_past_the_limit(monkeypatch):
    clock = [0.0]
    library = Library([SILENT], present=[True])            # never pulled out
    remote = _remote(library, monkeypatch, [])
    monkeypatch.setattr(concord.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(concord.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    with pytest.raises(concord.RemoteError, match="3 minutes"):
        remote.identity()
