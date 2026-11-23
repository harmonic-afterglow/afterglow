"""IR learning on the 600/650/665/700 family: the remote learns with libconcord's default
mode, and a learned capture is built into an arch-14 image and read back."""
from __future__ import annotations

import pytest

from afterglow import concord, payloads, remotes
from afterglow.backends.harmony_650 import backend


class _Lib:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def set_learning_mode(self, mode, timeout_ms):
        self.calls.append((mode, timeout_ms))
        return self.answer

    def lc_strerror(self, err):
        return b"some failure"


def _remote(answer):
    remote = concord.Remote.__new__(concord.Remote)
    remote.lib = _Lib(answer)
    remote.has_learning_modes = True
    return remote


def test_a_hid_remote_has_no_learning_modes_and_learns_with_the_default():
    """libconcord answers LC_ERROR for every remote that is not usbnet: that is "no modes
    here", not a failure, so learning goes on with learn_from_remote's default."""
    remote = _remote(concord.LC_ERROR)
    assert remote.set_learning_mode(concord.LEARN_SINGLE, 5000) is False
    assert remote.lib.calls == [(concord.LEARN_SINGLE, 5000)]


def test_a_usbnet_remote_still_sets_its_mode_and_other_errors_still_raise():
    assert _remote(0).set_learning_mode(concord.LEARN_STREAM, 3000) is True
    with pytest.raises(concord.RemoteError):
        _remote(concord.LC_ERROR_UNSUPP).set_learning_mode(concord.LEARN_SINGLE, 5000)


class _LearnLib:
    """learn_from_remote answering `answer`, having captured `count` durations."""

    def __init__(self, answer, count):
        self.answer, self.count, self.deleted = answer, count, 0

    def learn_from_remote(self, carrier, signal, length, _cb, _arg):
        import ctypes
        carrier._obj.value = 38000
        length._obj.value = self.count
        self.buffer = (ctypes.c_uint32 * max(1, self.count))(*([500] * self.count))
        signal._obj.contents = ctypes.c_uint32.from_buffer(self.buffer)
        return self.answer

    def delete_ir_signal(self, _signal):
        self.deleted += 1

    def lc_strerror(self, err):
        return b"Error while reading from the remote"


def _learner(answer, count):
    remote = concord.Remote.__new__(concord.Remote)
    remote.lib = _LearnLib(answer, count)
    remote.can_learn = True
    return remote


def test_a_try_without_a_signal_on_a_hid_remote_is_nothing_received():
    """A 665 whose wait for the first IR word runs out answers LC_ERROR_READ with nothing
    captured - seen on hardware for every 5 s try without a key press. That is an empty
    capture, which the learn dialog reports as "Nothing was received", not a fault."""
    remote = _learner(concord.LC_ERROR_READ, 0)
    assert remote.learn() == (38000, [])
    assert remote.lib.deleted == 1


def test_a_read_error_after_something_was_captured_still_raises():
    with pytest.raises(concord.RemoteError):
        _learner(concord.LC_ERROR_READ, 4).learn()


def test_the_650_family_offers_learning():
    assert remotes.get("harmony-650").can("ir_learning")


def test_a_learned_capture_is_built_into_an_arch14_image_and_comes_back(tmp_path):
    """A capture as concord.learned_capture makes it - here a Teufel-style NEC frame as a
    One4All sent it, measured, not a protocol - is lowered into the image's IR records and
    imported again with the same marks and spaces."""
    from afterglow.backends.harmony_650 import compose

    durations = [9000, 4500]
    for byte in (0x02, 0xFD, 0x05, 0xFA):
        for bit in range(8):
            durations += [560, 1690] if (byte >> bit) & 1 else [560, 560]
    durations += [560, 40000]
    capture = concord.learned_capture(38000, durations, "VolumeUp")
    device = {"id": "amp", "label": "Amp", "type": "Amplifier",
              "signals": {"VolumeUp": capture},
              "commands": [["VolumeUp", "", "", "", "VolumeUp"]]}
    built = compose.build({"devices": [device]}, stamp_fields=(0, 0, 12, 0, 0, 2026))
    payloads.get("blob").unpack(built["image"], str(tmp_path))
    [read] = backend.import_project(str(tmp_path), remotes.get("harmony-650"),
                                    {"name": "t"}).project["devices"]
    # a key no screen labels comes back under a generic name; the waveform is what counts
    [signal] = read["signals"].values()
    assert signal["pulses_us"] == capture["pulses_us"]
