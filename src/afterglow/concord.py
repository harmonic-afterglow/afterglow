#!/usr/bin/env python3
"""Talking to the remote over USB, through libconcord.

Afterglow used to tell the user to run the `concordance` command themselves. This
speaks to the library directly instead, so reading, writing and IR learning are things
the application does rather than instructions it prints.

## What this deliberately does not do

libconcord still carries the calls that reported back to `members.harmonyremote.com` -
`post_preconfig`, `post_postconfig`, `post_connect_test_success`. That service is gone,
and none of them are bound here. `update_configuration()` on its own is the whole
device-side write; the web calls were always separable, and `concordance` skips them
with `--noweb`.

## Safety

Writing is the one operation that can leave a remote unusable, and there is no vendor
server to recover from any more. So:

  * `write_config()` refuses a file that is not a configuration for the remote that is
    actually attached - it compares the file's `<SKIN>` against the connected remote's.
  * flash is invalidated by `update_configuration` itself, which is also what re-reads
    and verifies afterwards. This module does not reimplement that sequence.
  * nothing here writes unless asked to. Reading, identifying and learning are safe and
    do not touch the configuration.

## Threading

Every call blocks, some for tens of seconds. The GUI runs them on a worker thread; the
progress callback is invoked from inside the library on that same thread.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys
from pathlib import Path

# Every name libconcord is installed under, across the platforms it builds for. The
# Windows entries matter: libconcord is autotools/libtool with `-version-info 6:0:0`, so
# a MinGW build produces `libconcord-6.dll`, and none of the Unix names would ever match
# it. `ctypes.util.find_library` is still tried afterwards as a last resort, but on
# Windows it only searches PATH for an exact `concord.dll`, so it does not cover this.
LIBRARY_NAMES = (
    "libconcord.so.6", "libconcord.so",          # Linux
    "libconcord.6.dylib", "libconcord.dylib",    # macOS
    "libconcord-6.dll", "libconcord.dll", "concord.dll",   # Windows (MinGW libtool)
    "concord",
)

# Learning modes. Harmony 900 only - `set_learning_mode` is documented as such.
LEARN_SINGLE = 0        # wait a fixed time, return one IR frame
LEARN_STREAM = 1        # record for the whole timeout, silence included

# The stages a callback may report, so progress can be described rather than counted.
STAGES = {
    7: "Identifying the remote",
    8: "Starting the update",
    9: "Preparing flash",
    10: "Erasing",
    11: "Writing configuration",
    12: "Verifying",
    13: "Finishing",
    14: "Reading configuration",
    15: "Writing firmware",
    16: "Reading firmware",
    17: "Reading safe mode",
    18: "Restarting the remote",
    19: "Setting the clock",
    20: "Network",
    21: "Learning",
    0xFF: "Planning",
}

LC_CALLBACK = ctypes.CFUNCTYPE(
    None, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
    ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))


class NotAvailable(RuntimeError):
    """libconcord is not installed, so the remote cannot be reached."""


class RemoteError(RuntimeError):
    """The library refused an operation. Carries libconcord's own message."""


# Every way of reaching the remote fails the same way and has the same answer, so they
# say the same thing. It lives here because USB is the transport underneath all of them -
# the network channel in `hao` and the shell in `remote_shell` only exist while the remote
# is plugged in - and because this module depends on neither of those, so they can import
# it without a cycle.
NOT_CONNECTED_ADVICE = (
    "If the remote is plugged in, it has most likely not finished connecting yet. Wait a "
    "few seconds and try again; if it still will not connect after 20 seconds, unplug it "
    "and plug it back in."
)


def _bundled_candidates():
    """Every libconcord a frozen build carries, by full path.

    `ctypes.CDLL("libconcord.so.6")` asks the *system* loader, which knows nothing about
    a PyInstaller archive, so a bundled copy would sit unused beside the executable while
    the application reported the library missing.

    Found by **pattern, not by exact name**. `LIBRARY_NAMES` lists the names a library is
    installed under, and a bundler does not have to use any of them: given
    `libconcord.so.6.0.0` PyInstaller renamed it to the SONAME `libconcord.so.6` on one
    machine and kept the full version on a CI runner, so matching the list exactly found
    it in one place and not the other - a bundle that carried the library and reported it
    missing.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if not bundled:
        return []
    root = Path(bundled)
    found = []
    for pattern in ("libconcord*.so*", "libconcord*.dylib", "*concord*.dll"):
        found.extend(sorted(root.glob(pattern)))
    return found


# Why each attempt to load the library failed, most recent run only. A bundled library
# that will not load is indistinguishable from one that was never bundled unless the
# loader records which it was - typically a missing dependency such as `libzip` or
# `libhidapi-0` beside the DLL.
LOAD_ERRORS: list[str] = []


def _load():
    LOAD_ERRORS.clear()
    for candidate in _bundled_candidates():
        try:
            return ctypes.CDLL(str(candidate))
        except OSError as exc:
            LOAD_ERRORS.append(f"{candidate}: {exc}")
            continue
    for name in LIBRARY_NAMES:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    # Last resort, and deliberately defensive. `find_library` shells out and consults the
    # platform's own machinery - on Windows that reaches `shutil.which`, which calls into
    # `_winapi`. Anything it raises is an environment quirk, not an answer about whether
    # the library is present, and it must not become an unhandled error inside what is
    # only a probe: CI reached this line (no libconcord installed) with `sys.platform`
    # faked to win32 and got `'NoneType' object has no attribute
    # 'NeedCurrentDirectoryForExePath'` out of the standard library.
    try:
        found = ctypes.util.find_library("concord")
    except Exception:                                              # noqa: BLE001
        found = None
    if found:
        try:
            return ctypes.CDLL(found)
        except OSError:
            pass
    install = {
        "linux": "build and install that, then run ldconfig",
        "darwin": "build and install that (see its INSTALL.mac); Homebrew covers the "
                  "dependencies",
        "win32": "build it with MinGW (see its INSTALL.windows) and put libconcord-6.dll "
                 "somewhere on PATH",
    }.get(sys.platform, "build and install it for this platform")
    raise NotAvailable(
        f"libconcord was not found. It comes with Concordance "
        f"(github.com/jaymzh/concordance); {install}. Afterglow can still author "
        f"configurations without it - only reading from and writing to the remote "
        f"need it.")


# Whether anyone has actually reached a remote from this platform.
#
# The USB side is the hard part, and it is not libconcord's doing. The remote enumerates
# as a USB network adapter and then *waits for a DHCP server* to lease it 169.254.1.2.
# Logitech's Windows driver provides that server. Nothing in this project, and nothing in
# Concordance either, automates it outside Linux - Concordance's own helper
# (`start_concordance_dhcpd.sh`) is bash, dnsmasq, nmcli and udev.
#
# So this is deliberately not phrased as "supported/unsupported". Authoring, building,
# importing and the whole format layer are portable and covered by CI on all three
# platforms. Only the part that touches hardware is Linux-tested, and saying otherwise
# to someone about to write to a remote that has no vendor recovery would be dishonest.
# Platforms where a driver has to be installed before a remote can be reached, whether or
# not the path is proven. Kept apart from `LINK_SUPPORT` because the two answer different
# questions: that one says whether anyone has done it, this one says whether something
# must be installed first. Windows is now `tested` *and* still needs the driver.
# Both need Logitech's own software installed for its driver; Afterglow cannot replace
# it. The 7.8 release covers Windows and macOS.
NEEDS_DRIVER = frozenset({"win32", "darwin"})

LINK_SUPPORT = {
    # No instruction to run anything: Afterglow sets the USB link up itself now,
    # and telling somebody to run a script we already ran is how a fixed problem keeps
    # looking like an unfixed one.
    "linux": ("tested",
              "The remote waits for a DHCP lease before it will answer, which Afterglow "
              "arranges - see Settings → Set up the USB link."),
    "darwin": ("untested",
               "Nobody has reached a remote from macOS yet. It needs Logitech's old "
               "Harmony Remote Software installed for its driver - see the README for "
               "where to get it. Authoring and building configurations work normally."),
    "win32": ("tested",
              "Install Logitech's old Harmony Remote Software first. Afterglow needs "
              "its driver to reach the remote and cannot replace it; see the README for "
              "where to get it. Confirmed working on Windows 10 and Windows 11."),
}


def link_support() -> tuple[str, str]:
    """`("tested"|"untested", explanation)` for reaching a remote on this platform.

    `{helper}` is filled in here rather than in the table above, because resolving it
    materialises the script beside the user's files - a side effect that has no business
    running at import time, and would run on every import of this module.
    """
    return LINK_SUPPORT.get(
        sys.platform,
        ("untested", "This platform has never been tried against a remote. Authoring "
                     "and building work normally."))


def available() -> bool:
    """Is the library present? Used to grey out what cannot work."""
    try:
        _load()
        return True
    except NotAvailable:
        return False


class Remote:
    """A connected remote. Use as a context manager; every call may raise RemoteError.

        with Remote() as remote:
            print(remote.identity())
            data = remote.read_config()
    """

    def __init__(self):
        self.lib = _load()
        self._bind()
        self._open = False
        # Set by restart(): libconcord's message when the remote was not seen coming
        # back. Not an error - see restart() - but worth showing once.
        self.last_restart_error = None

    # plumbing
    def _bind(self):
        lib = self.lib
        for name, restype, argtypes in (
            ("init_concord", ctypes.c_int, []),
            ("deinit_concord", ctypes.c_int, []),
            ("lc_strerror", ctypes.c_char_p, [ctypes.c_int]),
            ("get_mfg", ctypes.c_char_p, []),
            ("get_model", ctypes.c_char_p, []),
            ("get_codename", ctypes.c_char_p, []),
            ("get_skin", ctypes.c_int, []),
            ("get_arch", ctypes.c_int, []),
            ("get_fw_ver_maj", ctypes.c_int, []),
            ("get_fw_ver_min", ctypes.c_int, []),
            ("get_config_bytes_used", ctypes.c_int, []),
            ("get_config_bytes_total", ctypes.c_int, []),
            ("is_config_dump_supported", ctypes.c_int, []),
            ("is_config_update_supported", ctypes.c_int, []),
            ("get_identity", ctypes.c_int, [LC_CALLBACK, ctypes.c_void_p]),
            ("reset_remote", ctypes.c_int, [LC_CALLBACK, ctypes.c_void_p]),
            ("read_and_parse_file", ctypes.c_int,
             [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]),
            ("delete_opfile_obj", None, []),
            ("update_configuration", ctypes.c_int,
             [LC_CALLBACK, ctypes.c_void_p, ctypes.c_int]),
            ("read_config_from_remote", ctypes.c_int,
             [ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
              ctypes.POINTER(ctypes.c_uint32), LC_CALLBACK, ctypes.c_void_p]),
            ("delete_blob", None, [ctypes.POINTER(ctypes.c_uint8)]),
            ("write_config_to_file", ctypes.c_int,
             [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32, ctypes.c_char_p,
              ctypes.c_int]),
            ("learn_from_remote", ctypes.c_int,
             [ctypes.POINTER(ctypes.c_uint32),
              ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),
              ctypes.POINTER(ctypes.c_uint32), LC_CALLBACK, ctypes.c_void_p]),
            ("delete_ir_signal", None, [ctypes.POINTER(ctypes.c_uint32)]),
        ):
            function = getattr(lib, name, None)
            if function is None:
                continue                      # older builds lack the newer calls
            function.restype = restype
            function.argtypes = argtypes
        # H900 learning modes arrived late; treat them as optional.
        self.has_learning_modes = hasattr(lib, "set_learning_mode")
        if self.has_learning_modes:
            lib.set_learning_mode.restype = ctypes.c_int
            lib.set_learning_mode.argtypes = [ctypes.c_int, ctypes.c_uint32]
        self.can_learn = hasattr(lib, "learn_from_remote")

    def _check(self, err, what):
        if err:
            message = self.lib.lc_strerror(err)
            raise RemoteError(f"{what}: "
                              f"{message.decode() if message else f'error {err}'}")

    def _callback(self, on_progress):
        """Wrap a `(stage_text, current, total) -> None` in libconcord's signature."""
        if on_progress is None:
            return LC_CALLBACK(lambda *a: None)

        def relay(stage, _count, current, total, _kind, _arg, _stages):
            try:
                on_progress(STAGES.get(stage, f"stage {stage}"), current, total)
            except Exception:                 # a failing UI must not abort a flash
                pass
        holder = LC_CALLBACK(relay)
        self._keep_alive = holder             # ctypes will not keep this for us
        return holder

    # lifetime
    def __enter__(self):
        try:
            self._check(self.lib.init_concord(), "connecting to the remote")
        except RemoteError as exc:
            # libconcord says "Error connecting or finding the remote", which reads as
            # "this remote is not supported" when the usual cause is that it is supported
            # and simply is not ready yet. A Harmony enumerates on USB in stages and only
            # answers once the last one is up, so an attempt made a second after plugging
            # in fails against hardware that is sitting right there working.
            #
            # Not a Windows problem, though it is worst there: the driver binds the
            # interface after enumeration, adding a delay on top of the remote's own.
            # Nothing here can wait for it - libconcord has already given up - so the
            # honest thing is to say what the state probably is and what ends it.
            raise RemoteError(f"{exc}\n\n{NOT_CONNECTED_ADVICE}") from exc
        self._open = True
        return self

    def __exit__(self, *_exc):
        if self._open:
            self.lib.deinit_concord()
            self._open = False

    # reading
    def identity(self, on_progress=None) -> dict:
        """Who is attached. Also the connectivity test - it talks to the remote."""
        self._check(self.lib.get_identity(self._callback(on_progress), None),
                    "identifying the remote")

        def text(name):
            value = getattr(self.lib, name)()
            return value.decode(errors="replace") if value else ""

        return {
            "mfg": text("get_mfg"),
            "model": text("get_model"),
            "codename": text("get_codename"),
            "skin": self.lib.get_skin(),
            "arch": self.lib.get_arch(),
            "firmware": f"{self.lib.get_fw_ver_maj()}.{self.lib.get_fw_ver_min()}",
            "config_used": self.lib.get_config_bytes_used(),
            "config_total": self.lib.get_config_bytes_total(),
            "can_read": self.lib.is_config_dump_supported() == 0,
            "can_write": self.lib.is_config_update_supported() == 0,
        }

    def save_config(self, path, on_progress=None) -> int:
        """Read the configuration off the remote and save it as a `.ezhex`.

        `read_config_from_remote` hands back the **binary blob only** - no envelope.
        `write_config_to_file` is what builds the `<INFORMATION>` header around it, and
        it is what `concordance -c` uses, so the file this writes is the same shape.
        Writing the blob unwrapped produces a file nothing can read back, including
        Afterglow's own importer.
        """
        blob = ctypes.POINTER(ctypes.c_uint8)()
        size = ctypes.c_uint32()
        self._check(self.lib.read_config_from_remote(
            ctypes.byref(blob), ctypes.byref(size),
            self._callback(on_progress), None), "reading the configuration")
        try:
            self._check(self.lib.write_config_to_file(
                blob, size.value, str(path).encode(), 0), f"saving to {path}")
        finally:
            self.lib.delete_blob(blob)
        return size.value

    def read_config(self, on_progress=None) -> bytes:
        """The raw configuration blob, with no envelope around it.

        Use `save_config()` to write a file - see the note there about the header.
        """
        blob = ctypes.POINTER(ctypes.c_uint8)()
        size = ctypes.c_uint32()
        self._check(self.lib.read_config_from_remote(
            ctypes.byref(blob), ctypes.byref(size),
            self._callback(on_progress), None), "reading the configuration")
        try:
            return bytes(bytearray(blob[i] for i in range(size.value)))
        finally:
            self.lib.delete_blob(blob)

    # writing
    def write_config(self, path, on_progress=None, reset=True) -> None:
        """Flash a `.ezhex` onto the attached remote.

        Refuses a file built for a different model. libconcord would likely refuse it
        too, but not before invalidating flash, and a remote whose flash has been
        invalidated and not rewritten does not boot.
        """
        path = Path(path)
        if not path.is_file():
            raise RemoteError(f"no such configuration: {path}")

        identity = self.identity()
        if not identity["can_write"]:
            raise RemoteError(f"{identity['model']} does not support configuration "
                              "updates through libconcord")
        self._verify_intended_for(path, identity)

        kind = ctypes.c_int()
        self._check(self.lib.read_and_parse_file(str(path).encode(),
                                                 ctypes.byref(kind)),
                    f"reading {path.name}")
        try:
            # Always 1 (== do not reset), because we do the restart ourselves below.
            #
            # Letting libconcord reset makes the write and the restart one call with one
            # return code, and the restart is the part that routinely "fails": it reboots
            # the remote, then waits for it to reappear on USB. On Linux the RNDIS
            # interface goes away and comes back with a new address, so libconcord often
            # cannot see it again inside its timeout and returns "Error connecting or
            # finding the remote" - *after* the configuration was written perfectly.
            #
            # Reported as-is that reads as a failed flash, which is the one thing a user
            # must not be misled about on hardware that has no vendor recovery: the
            # natural response to "the flash failed" is to flash again. Splitting them
            # means a write error stays fatal and a restart error stays a warning.
            self._check(self.lib.update_configuration(
                self._callback(on_progress), None, 1),
                "writing the configuration")
        finally:
            self.lib.delete_opfile_obj()
        if reset:
            self.restart(on_progress)

    def restart(self, on_progress=None) -> bool:
        """Reboot the remote. True if it was seen coming back, False if it was not.

        Never raises. Losing sight of the remote after a reboot is expected on Linux and
        says nothing about whether the configuration on it is good - the remote reboots
        either way, it is just no longer answering on a USB link that has been torn down
        and re-enumerated. The caller decides how loudly to mention it.

        `libconcord`'s own `reset_remote` deinitialises the library before it waits, and
        only re-initialises it if the remote answers again. So on the failure path this
        object no longer holds an open connection, and `__exit__` must not close it twice.
        """
        error = self.lib.reset_remote(self._callback(on_progress), None)
        if error:
            self._open = False
            self.last_restart_error = (
                self.lib.lc_strerror(error) or b"").decode() or f"error {error}"
            return False
        self.last_restart_error = None
        return True

    @staticmethod
    def _verify_intended_for(path: Path, identity: dict) -> None:
        """The file's own header says which remote it is for. Believe it."""
        from . import ezhex, remotes
        try:
            header, _start, _size, _checksum = ezhex._split(path.read_bytes())
        except Exception as exc:
            raise RemoteError(f"{path.name} is not a configuration file: {exc}") from exc
        wanted = remotes.identity_of(header)
        skin = wanted.get("skin")
        if skin is not None and identity.get("skin") not in (None, -1) \
                and skin != identity["skin"]:
            raise RemoteError(
                f"{path.name} is built for skin {skin}, but the attached remote is "
                f"{identity['model']} (skin {identity['skin']}). Refusing to write it.")

    def reset(self, on_progress=None) -> None:
        """Reboot the remote."""
        self._check(self.lib.reset_remote(self._callback(on_progress), None),
                    "restarting the remote")

    # learning
    def set_learning_mode(self, mode: int, timeout_ms: int) -> bool:
        """False when the installed libconcord predates learning modes."""
        if not self.has_learning_modes:
            return False
        self._check(self.lib.set_learning_mode(mode, timeout_ms),
                    "setting the learning mode")
        return True

    def learn(self, on_progress=None) -> tuple[int, list[int]]:
        """Listen for one IR code. Returns `(carrier_hz, [mark, space, ...])` in us.

        The durations alternate and always start with a mark. libconcord derives the
        carrier from the first burst's cycle count, so it is a measurement: expect it
        to move by a few hertz between presses of the same key.
        """
        if not self.can_learn:
            raise RemoteError(
                "This libconcord has no IR learning. It arrived in Concordance's "
                "6ec3fae 'Add H900 learning'; a build from before that cannot learn.")
        carrier = ctypes.c_uint32()
        signal = ctypes.POINTER(ctypes.c_uint32)()
        length = ctypes.c_uint32()
        self._check(self.lib.learn_from_remote(
            ctypes.byref(carrier), ctypes.byref(signal), ctypes.byref(length),
            self._callback(on_progress), None), "learning an IR code")
        try:
            return carrier.value, [signal[i] for i in range(length.value)]
        finally:
            self.lib.delete_ir_signal(signal)


def merge_zero_durations(durations: list[int]) -> list[int]:
    """Drop zero-length entries, joining the neighbours they separated.

    libconcord reports a space as `t_off`, and `t_off` is genuinely 0 when two bursts run
    together with no measurable gap - the odd-word branch computes `t - t_on`, which is
    zero whenever the total equals the on time. It is a real measurement, not corruption.

    A zero-length element cannot be transmitted and has no meaning on its own: two marks
    separated by a zero space *are* one longer mark. So the entry is removed and its
    neighbours summed, which is the same waveform expressed without the artefact.

    Removing an entry flips the mark/space parity of everything after it, so polarity is
    tracked explicitly rather than read back off the index.
    """
    merged: list[tuple[int, int]] = []
    for index, duration in enumerate(durations):
        if duration <= 0:
            continue
        polarity = index % 2                    # 0 mark, 1 space; libconcord starts on a mark
        if merged and merged[-1][0] == polarity:
            merged[-1] = (polarity, merged[-1][1] + duration)
        else:
            merged.append((polarity, duration))
    while merged and merged[0][0] == 1:         # a waveform starts with a mark
        merged.pop(0)
    return [duration if polarity == 0 else -duration for polarity, duration in merged]


def learned_capture(carrier_hz: int, durations: list[int], name: str) -> dict:
    """A learned signal as a portable Afterglow waveform.

    `carrier_hz` records what the remote measured. The Harmony PK backend converts it to
    SsIr's u32 carrier period in nanoseconds when building; imported captures separately
    retain their exact observed integer period as native evidence.

    Raises `ValueError` when nothing usable was received, which the interface reports as
    a failed capture rather than an error.
    """
    from . import ir_signal

    pulses = merge_zero_durations(durations)
    if not pulses:
        raise ValueError("no usable mark/space durations were received")
    return ir_signal.waveform(
        pulses,
        name=name,
        carrier_hz=carrier_hz,
        provenance={"kind": "measured", "tool": "libconcord learn_from_remote"},
    )


def needs_driver() -> bool:
    """Whether this platform needs a driver Afterglow does not install."""
    return sys.platform in NEEDS_DRIVER
