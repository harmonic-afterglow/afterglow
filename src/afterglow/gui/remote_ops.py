"""Talking to the remote from the interface: read, write, learn, pair a blaster.

Every one of these blocks for seconds to minutes, so each runs on a worker thread and
reports back through signals. The work itself lives in `afterglow.concord` (USB, via
libconcord) and `afterglow.hao` (the remote's own event channel over USB-net) - this
module is only the threading and the wording.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .. import concord, hao


class RemoteWorker(QThread):
    """One remote operation. `log` for the transcript, `done` for the outcome."""

    log = pyqtSignal(str)
    progress = pyqtSignal(str, int, int)      # stage, current, total
    done = pyqtSignal(bool, str)              # succeeded, message
    result = pyqtSignal(object)               # operation-specific payload

    def __init__(self, operation: str, parent=None, **kwargs):
        super().__init__(parent)
        self.operation = operation
        self.kwargs = kwargs

    def _on_progress(self, stage, current, total):
        self.progress.emit(stage, current, total)

    def run(self):
        try:
            getattr(self, f"_{self.operation}")()
        except concord.NotAvailable as exc:
            self.done.emit(False, str(exc))
        except (concord.RemoteError, hao.NotReachable) as exc:
            self.done.emit(False, str(exc))
        except Exception as exc:              # a bug here must not kill the interface
            self.done.emit(False, f"{type(exc).__name__}: {exc}")

    # the operations
    def _identify(self):
        with concord.Remote() as remote:
            identity = remote.identity(self._on_progress)
        self.log.emit(f"{identity['mfg']} {identity['model']} "
                      f"(skin {identity['skin']}, firmware {identity['firmware']})")
        used, total = identity["config_used"], identity["config_total"]
        if total:
            self.log.emit(f"Configuration memory: {used} of {total} bytes used "
                          f"({used * 100 // total}%)")
        self.result.emit(identity)
        self.done.emit(True, f"Connected to {identity['model']}.")

    def _read(self):
        target = Path(self.kwargs["path"])
        with concord.Remote() as remote:
            identity = remote.identity()
            self.log.emit(f"Reading from {identity['model']}...")
            size = remote.save_config(target, self._on_progress)
        self.log.emit(f"Saved {target}")
        self.result.emit(target)
        self.done.emit(True, f"Read {size:,} bytes into {target.name}.")

    def _write(self):
        path = Path(self.kwargs["path"])
        with concord.Remote() as remote:
            identity = remote.identity()
            self.log.emit(f"Writing {path.name} to {identity['model']}...")
            remote.write_config(path, self._on_progress)
            # The write succeeded or write_config would have raised. Only the restart
            # is in question, and on Linux the USB link is routinely torn down and
            # re-enumerated faster than libconcord can follow. Say so plainly rather
            # than letting it read as a failed flash - a user who believes the flash
            # failed will flash again, which is the wrong instinct on a remote with no
            # vendor recovery.
            missed_restart = remote.last_restart_error
        if missed_restart:
            self.log.emit(f"(the remote stopped answering while it rebooted: "
                          f"{missed_restart})")
            # The reboot is the last step of a flash and the one most likely to look like
            # a failure, because the remote tears down the USB link to do it and can come
            # back slower than libconcord waits. The write is already done at this point,
            # so the first sentence has to say so - and the rest has to match what every
            # other connection message says, rather than sending a Windows user to a
            # shell script.
            self.done.emit(True,
                           "The configuration was written and verified. The remote is "
                           "restarting and dropped off USB before it came back, which "
                           "does not affect what was written. Give it a few seconds; if "
                           "it has not reappeared after 20 seconds, unplug it and plug "
                           "it back in." + hao.linux_link_note())
            return
        self.done.emit(True, "The configuration was written and verified.")

    def _learn(self):
        mode = self.kwargs.get("mode", concord.LEARN_SINGLE)
        timeout = int(self.kwargs.get("timeout_ms", 5000))
        with concord.Remote() as remote:
            if remote.set_learning_mode(mode, timeout):
                self.log.emit("Ready - press the key on the other remote.")
            else:
                self.log.emit("This libconcord has no learning modes; using its "
                              "default. Press the key on the other remote.")
            carrier, durations = remote.learn(self._on_progress)
        if not durations:
            self.done.emit(False, "Nothing was received. Try again, holding the other "
                                  "remote closer to the front of the Harmony.")
            return
        try:
            capture = concord.learned_capture(carrier, durations,
                                              self.kwargs.get("name", "learned"))
        except ValueError:
            # A capture that carries no usable durations is a bad reading, not a fault:
            # report it the same way as receiving nothing, rather than showing whatever
            # the validator said.
            self.done.emit(False, "The signal that came through was not usable. Try "
                                  "again, holding the other remote closer to the front "
                                  "of the Harmony.")
            return
        self.log.emit(f"Learned {len(durations) // 2} mark/space pairs, "
                      f"carrier {carrier} Hz")
        self.result.emit(capture)
        self.done.emit(True, f"Learned a code at {carrier} Hz.")

    def _pair(self):
        before = set(self.kwargs.get("before") or ())
        self.log.emit("Asking the remote to start pairing...")
        joined = hao.pair_receiver(
            wait=float(self.kwargs.get("wait", 45)),
            on_event=lambda name: self.log.emit(f"  {name}"))
        if not joined:
            self.result.emit([])
            self.done.emit(False, "No blaster joined. Put it in pairing mode and try "
                                  "again.")
            return
        # The radio is done; the settings file is written separately. Wait for it
        # rather than reading a file that may still say what it said before.
        self.log.emit("Paired - waiting for the remote to save the address...")
        receivers = hao.wait_for_new_receiver(before)
        if not receivers:
            self.result.emit([])
            self.done.emit(False, "A blaster joined, but the remote has not saved its "
                                  "address yet. Try adding it again.")
            return
        for receiver in receivers:
            self.log.emit(f"  Base {receiver.get('label')}  {receiver.get('mac')}")
        self.result.emit(receivers)
        self.done.emit(True, f"Added {len(receivers)} blaster(s).")


def run_with_progress(parent, operation: str, title: str, message: str, **kwargs):
    """Run a remote operation without freezing the interface.

    Every one of these blocks - learning waits five seconds for a keypress, pairing
    waits the better part of a minute. Calling them on the main thread stops the
    interface repainting, so the window greys out and the desktop offers to kill it.

    The work goes on a `RemoteWorker`; this spins a nested event loop so the dialog
    stays alive and the caller still reads as a straight line. Returns
    `(ok, message, result)`.
    """
    from PyQt6.QtCore import QEventLoop, Qt
    from PyQt6.QtWidgets import QProgressDialog

    dialog = QProgressDialog(message, None, 0, 0, parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setCancelButton(None)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    loop = QEventLoop()
    outcome = {"ok": False, "message": "", "result": None}

    worker = RemoteWorker(operation, parent, **kwargs)
    worker.log.connect(lambda line: dialog.setLabelText(f"{message}\n\n{line}"))
    worker.result.connect(lambda value: outcome.update(result=value))

    def finished(ok, text):
        outcome.update(ok=ok, message=text)
        loop.quit()

    worker.done.connect(finished)
    worker.finished.connect(loop.quit)          # also stop if run() dies outright
    worker.start()
    dialog.show()
    loop.exec()
    worker.wait()
    dialog.close()
    return outcome["ok"], outcome["message"], outcome["result"]


def blasters_in(config_path) -> list[dict]:
    """The receivers a saved configuration knows about, for showing after a re-read."""
    import contextlib
    import io
    import tempfile

    from .. import ezhex
    from ..rf import extract_rf

    work = tempfile.mkdtemp()
    with contextlib.redirect_stdout(io.StringIO()):
        ezhex.unpack(str(config_path), work)
    return ((extract_rf(work) or {}).get("receivers")) or []
