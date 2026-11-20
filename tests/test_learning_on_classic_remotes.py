"""Learning on the remotes that are not on the USB network link: the One, 600/650/665/700
and 800.

They learn a key through libconcord's own capture (HID on the One and the 650 family, MH
on the 800). Only the network-link remotes have learning modes, and libconcord answers
LC_ERROR when asked to set one on any other - which Afterglow took for a failure, so the
One said "unknown error" and never listened. These check that the mode is skipped, that
the remotes offer learning, and that a learned key builds into each one's image.
"""
from __future__ import annotations

import pytest

from afterglow import concord, remotes


class _Lib:
    def __init__(self, answer):
        self.answer = answer

    def set_learning_mode(self, _mode, _timeout):
        return self.answer

    def lc_strerror(self, _err):
        return b"cannot connect"


def _remote(answer):
    remote = object.__new__(concord.Remote)
    remote.lib = _Lib(answer)
    remote.has_learning_modes = True
    return remote


def test_a_remote_without_learning_modes_learns_its_own_way():
    assert _remote(concord.LC_ERROR).set_learning_mode(concord.LEARN_SINGLE, 5000) is False
    assert _remote(0).set_learning_mode(concord.LEARN_SINGLE, 5000) is True


def test_any_other_answer_is_still_an_error():
    with pytest.raises(concord.RemoteError):
        _remote(concord.LC_ERROR_CONNECT).set_learning_mode(concord.LEARN_SINGLE, 5000)


@pytest.mark.parametrize("remote", ["harmony-one", "harmony-650", "harmony-700",
                                    "harmony-800", "harmony-900", "harmony-1100"])
def test_the_remotes_offer_learning(remote):
    assert remotes.get(remote).can("ir_learning")


def _learned():
    return concord.learned_capture(38000, [900, 450] * 16 + [900, 20000], "ServiceMenu")


@pytest.mark.slow
@pytest.mark.parametrize("backend", ["harmony_one", "harmony_650", "harmony_800"])
def test_a_learned_key_builds_into_the_image(backend):
    import importlib
    lowering = importlib.import_module(f"afterglow.backends.{backend}.ir_lowering")
    build = (importlib.import_module("afterglow.backends.harmony_650.compose").build
             if backend == "harmony_650" else
             importlib.import_module(f"afterglow.backends.{backend}.generate").build)
    capture = _learned()
    project = {"devices": [{"label": "TV", "type": "Television",
                            "signals": {"ServiceMenu": capture},
                            "commands": [["ServiceMenu", "Service Menu", "", "", None]]}],
               "activities": []}
    image = build(project)["image"]
    press = lowering.lower(capture).press_waveform
    if backend == "harmony_650":
        # a press with no hold starts at its first mark on arch 14 (compose._press_alone)
        while not int.from_bytes(press[:2], "little") & 0x8000:
            press = press[2:]
    assert press in image
