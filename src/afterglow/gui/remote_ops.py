"""Talking to the remote from the interface: read, write, learn, pair a blaster.

Every one of these blocks for seconds to minutes, so each runs on a worker thread and
reports back through signals. The work itself lives in `afterglow.concord` (USB, via
libconcord) and `afterglow.hao` (the remote's own event channel over USB-net) - this
module is only the threading and the wording.
"""
from __future__ import annotations

from pathlib import Path

from ..qt.QtCore import QThread, pyqtSignal

from ..applog import LOG

from .. import concord, hao

# A Harmony 900 in Safe Mode (and an 1100, the same firmware family) still answers on
# USB: it can be read, and a configuration written to it is how it gets out.
DAMAGED_CONFIG_NOTE = (
    "The configuration on the remote is damaged or missing - most often a write that did "
    "not finish - so there is nothing on it to read or back up. Writing a configuration "
    "repairs it: your backup (Settings > Flash a configuration file), or a build with "
    "Flash to Remote.")
SAFE_MODE_NOTE = ("The remote is in Safe Mode. It can still be read, and writing a "
                  "configuration to it - Flash, or Settings › Flash a Configuration File "
                  "with a backup - is how it is brought back.")


def _check_backup(path: Path) -> None:
    """A backup that could not be put back is no backup: whole, and checksummed."""
    from .. import ezhex
    _header, payload, checksum, outside = ezhex.read(path.read_bytes())
    if not payload or outside < 0 or (
            checksum is not None and ezhex.checksum(payload) != checksum):
        raise ValueError(f"{path.name} came back incomplete")


class RemoteWorker(QThread):
    """One remote operation. `log` for the transcript, `done` for the outcome."""

    log = pyqtSignal(str)
    progress = pyqtSignal(str, int, int)      # stage, current, total
    done = pyqtSignal(bool, str)              # succeeded, message
    result = pyqtSignal(object)               # operation-specific payload
    # a write that stopped before anything was done, for the person to confirm: what
    # differs, and whether it looks like another remote (concord.OtherRemote) rather
    # than an unconfirmed revision of its model (concord.UnconfirmedRemote)
    unconfirmed = pyqtSignal(list, bool)

    def __init__(self, operation: str, parent=None, **kwargs):
        super().__init__(parent)
        self.operation = operation
        self.kwargs = kwargs
        # Everything an operation says, and how it ended, also goes to the log file.
        self.log.connect(lambda line: LOG.info("%s: %s", operation, line))
        self.done.connect(lambda ok, message: (LOG.info if ok else LOG.warning)(
            "%s %s: %s", operation, "finished" if ok else "failed", message))

    def _on_progress(self, stage, current, total):
        self.progress.emit(stage, current, total)

    def _remote(self):
        """The remote, saying so first: finding it alone can take 20 seconds."""
        self.progress.emit("Connecting to the remote", 0, 0)
        # In Safe Mode the remote asks for its USB link only every 4 to 32 seconds, and
        # libconcord waits for the next time: the first connection can take that long.
        self.log.emit("Connecting to the remote... (in Safe Mode this can take up to "
                      "half a minute)")
        return concord.Remote()

    def run(self):
        try:
            getattr(self, f"_{self.operation}")()
        except concord.UnconfirmedRemote as exc:
            self.unconfirmed.emit(list(exc.cautions),
                                  isinstance(exc, concord.OtherRemote))
            self.done.emit(False, f"{exc} Waiting for your answer.")
        except concord.NotAvailable as exc:
            self.done.emit(False, str(exc))
        except (concord.RemoteError, hao.NotReachable) as exc:
            LOG.warning("%s: %r", self.operation, exc, exc_info=True)
            self.done.emit(False, str(exc))
        except Exception as exc:              # a bug here must not kill the interface
            LOG.exception("%s stopped", self.operation)
            self.done.emit(False, f"{type(exc).__name__}: {exc}")

    # the operations
    def _identify(self):
        with self._remote() as remote:
            identity = remote.identity(self._on_progress)
        self.log.emit(f"{identity['mfg']} {identity['model']} "
                      f"(skin {identity['skin']}, firmware {identity['firmware']})")
        if identity.get("safe_mode"):
            self.log.emit(SAFE_MODE_NOTE)
        if identity.get("config_valid") is False:
            self.log.emit(DAMAGED_CONFIG_NOTE)
        used, total = identity["config_used"], identity["config_total"]
        # libconcord cannot learn the size of the configuration region on the usbnet
        # remotes (900, 1000, 1100) and reports 1 for it.
        if total > 1 and used <= total:
            self.log.emit(f"Configuration memory: {used:,} of {total:,} bytes used "
                          f"({used * 100 // total}%)")
        elif used:
            self.log.emit(f"Configuration: {used:,} bytes")
        self.result.emit(identity)
        self.done.emit(True, f"Connected to {identity['model']}"
                             f"{' in Safe Mode' if identity.get('safe_mode') else ''}.")

    def _read(self):
        target = Path(self.kwargs["path"])
        with self._remote() as remote:
            identity = remote.identity(self._on_progress)
            if identity.get("safe_mode"):
                self.log.emit(SAFE_MODE_NOTE)
            if identity.get("config_valid") is False:
                raise concord.RemoteError(DAMAGED_CONFIG_NOTE)
            self.log.emit(f"Reading from {identity['model']}...")
            size = remote.save_config(target, self._on_progress)
        self.log.emit(f"Saved {target}")
        self.result.emit(target)
        self.done.emit(True, f"Read {size:,} bytes into {target.name}.")

    def _write(self):
        path = Path(self.kwargs["path"])
        backup = self.kwargs.get("backup")
        accept = {"accept_unconfirmed": bool(self.kwargs.get("accept_unconfirmed")),
                  "accept_mismatched": bool(self.kwargs.get("accept_mismatched"))}
        with self._remote() as remote:
            identity = remote.identity(self._on_progress)
            # whether it may be written at all, before a backup is taken for it
            remote.check_write(path, identity, **accept)
            if identity.get("safe_mode"):
                self.log.emit(SAFE_MODE_NOTE)
            if backup and identity.get("config_valid") is False:
                # nothing whole to keep: the write is what repairs it
                self.log.emit(DAMAGED_CONFIG_NOTE)
                self.log.emit("No backup was taken: there is no whole configuration on "
                              "the remote to save.")
                backup = None
            if backup:
                # Same connection, before anything is changed. No backup, no write.
                self.log.emit(f"Saving what is on the {identity['model']} now...")
                try:
                    remote.save_config(Path(backup), self._on_progress)
                    _check_backup(Path(backup))
                except (concord.RemoteError, OSError, ValueError) as exc:
                    raise concord.RemoteError(
                        f"The remote could not be backed up, so nothing was written: "
                        f"{exc}") from exc
                self.log.emit(f"Backed up to {backup}")
            self.log.emit(f"Writing {path.name} to {identity['model']}...")
            remote.write_config(path, self._on_progress, **accept)
            # The write succeeded or write_config would have raised. Only the restart
            # is in question, and on Linux the USB link is routinely torn down and
            # re-enumerated faster than libconcord can follow. Say so plainly rather
            # than letting it read as a failed flash - a user who believes the flash
            # failed will flash again, which is the wrong instinct on a remote with no
            # vendor recovery.
            missed_restart = remote.last_restart_error
        self._written(missed_restart)

    def _flash(self):
        path = Path(self.kwargs["path"])
        force = bool(self.kwargs.get("force"))
        with self._remote() as remote:
            identity = remote.identity(self._on_progress)
            if identity.get("safe_mode"):
                self.log.emit(SAFE_MODE_NOTE)
            if identity.get("config_valid") is False:
                self.log.emit(DAMAGED_CONFIG_NOTE)
            self.log.emit(f"Writing {path.name} to {identity['model']}"
                          f"{' (forced)' if force else ''}...")
            remote.flash_file(path, self._on_progress, force=force)
            missed_restart = remote.last_restart_error
        self._written(missed_restart)

    def _written(self, missed_restart):
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
        with self._remote() as remote:
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


def run_with_progress(parent, operation: str, title: str, message: str, **kwargs):
    """Run a remote operation without freezing the interface.

    Every one of these blocks - learning waits five seconds for a keypress, pairing
    waits the better part of a minute. Calling them on the main thread stops the
    interface repainting, so the window greys out and the desktop offers to kill it.

    The work goes on a `RemoteWorker`; this spins a nested event loop so the dialog
    stays alive and the caller still reads as a straight line. Returns
    `(ok, message, result)`.
    """
    from ..qt.QtCore import QEventLoop, Qt
    from ..qt.QtWidgets import QProgressDialog

    from .usb_driver import offer_before_operation
    offer_before_operation(parent)
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

    def progress(stage, current, total):
        # How far along, as the Flash tab shows it: a busy bar said nothing about
        # whether a two-minute write was nearly done or stuck.
        dialog.setLabelText(f"{message}\n\n{stage}"
                            + (f" - {current * 100 // total}%" if total else ""))
        dialog.setRange(0, total or 0)
        if total:
            dialog.setValue(min(current, total))
    worker.progress.connect(progress)
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
    if not outcome["ok"] and not outcome["message"]:
        # The worker ended without a word: an empty error box reads as a crash.
        outcome["message"] = ("It stopped without saying why. Help > Show log file has "
                              "what it did; please attach it to a bug report.")
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
