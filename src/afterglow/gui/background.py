"""Slow work - a download, an index fetched over the network - off the interface thread.

A catalogue's first answer can take a minute on a slow or captive network; asked on
the interface thread, the window stopped repainting and the desktop offered to kill
it. `call` runs the work on a thread behind a progress dialog with Cancel, spinning a
nested event loop so the caller still reads as a straight line.
"""
from __future__ import annotations

from ..qt.QtCore import QEventLoop, QThread, Qt, pyqtSignal


class Cancelled(Exception):
    """The person stopped waiting. The work itself may still finish, unseen."""


class _Worker(QThread):
    finished_with = pyqtSignal(object, object)          # result, exception

    def __init__(self, work):
        super().__init__()
        self._work = work

    def run(self):
        try:
            result = self._work()
        except BaseException as exc:                    # handed back, raised there
            self.finished_with.emit(None, exc)
        else:
            self.finished_with.emit(result, None)


# A thread whose dialog was cancelled runs on to its end; it is kept here until then,
# since destroying a running QThread aborts the process.
_ABANDONED: set = set()


def call(parent, message: str, work, *, title: str = "Please wait", delay_ms: int = 400):
    """``work()`` on a thread; its result, or its exception raised here. Cancel raises
    `Cancelled`. A dialog appears only if the work takes longer than ``delay_ms``."""
    from ..qt.QtWidgets import QProgressDialog

    dialog = QProgressDialog(message, "Cancel", 0, 0, parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(delay_ms)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    loop = QEventLoop()
    outcome = {}
    worker = _Worker(work)

    def done(result, error):
        outcome.update(result=result, error=error)
        loop.quit()

    worker.finished_with.connect(done)
    dialog.canceled.connect(loop.quit)
    worker.start()
    loop.exec()
    dialog.close()
    dialog.deleteLater()
    if "error" not in outcome:                         # cancelled: let it finish unseen
        _ABANDONED.add(worker)
        worker.finished.connect(lambda: _ABANDONED.discard(worker))
        raise Cancelled("stopped waiting")
    worker.wait()
    if outcome["error"] is not None:
        raise outcome["error"]
    return outcome["result"]


class _Steps(QThread):
    step = pyqtSignal(int)                              # which item is being worked on
    finished_with = pyqtSignal(object)                  # the error that stopped it, or None

    def __init__(self, items, work):
        super().__init__()
        self._items, self._work = items, work
        self.results, self.stop = [], False

    def run(self):
        try:
            for index, item in enumerate(self._items):
                if self.stop:
                    break
                self.step.emit(index)
                self.results.append(self._work(item))
        except BaseException as exc:                    # handed back, raised there
            self.finished_with.emit(exc)
        else:
            self.finished_with.emit(None)


def each(parent, items, work, message, *, title: str = "Please wait",
         delay_ms: int = 400) -> list:
    """``work(item)`` for each of ``items`` in turn on a thread, behind a progress dialog
    that says ``message(index, item)``. Their results, in order; Cancel stops before the
    next item and returns those done, so a long look-up keeps what it found."""
    from ..qt.QtWidgets import QProgressDialog

    items = list(items)
    dialog = QProgressDialog(message(0, items[0]) if items else "", "Cancel", 0,
                             len(items), parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(delay_ms)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    loop = QEventLoop()
    outcome = {}
    worker = _Steps(items, work)

    def step(index):
        dialog.setValue(index)
        dialog.setLabelText(message(index, items[index]))

    def done(error):
        outcome["error"] = error
        loop.quit()

    def cancel():
        worker.stop = True
        dialog.setLabelText("Stopping after this one...")

    worker.step.connect(step)
    worker.finished_with.connect(done)
    dialog.canceled.connect(cancel)
    worker.start()
    loop.exec()
    worker.wait()
    dialog.close()
    dialog.deleteLater()
    if outcome["error"] is not None:
        raise outcome["error"]
    return list(worker.results)
