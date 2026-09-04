"""Finding blasters: open the remote's inclusion window and watch what joins.

Pairing is not a scan. The link is Z-Wave, the PC has no radio, and a blaster only
appears by being *included* - which needs its button pressed. So this opens the
remote's inclusion window, waits with a visible clock, and shows the remote's own list
updating as receivers join.

Two things make it behave rather than guess:

* the remote saves its RF settings with a fire-and-forget POST, so the list is read
  live from `http://<remote>/xmluserrfsetting` (`hao.receivers_now`) rather than
  inferred from the pairing event, which fires earlier;
* a receiver the remote already knows does not announce itself as *new*, so "what is
  out there?" cannot be answered from the pairing event alone. It is answered from
  `<ControllerStatus>` instead, which the remote maintains as a live reachability flag:
  `RF:ReceiverLinkUp` from the network manager sets it to 1 and persists, `LinkDown`
  sets it to 0 and persists (`RFService.lua`). So the settings file always says which
  blasters are actually reachable - including ones paired long ago.

That is what removes the need to erase the pairing table before scanning. Erasing was
only ever a way to make known blasters visible again; the status flag makes them
visible without unpairing anything.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QMessageBox,
                             QProgressBar, QPushButton, QVBoxLayout)

from .. import hao

DEFAULT_WINDOW = 60          # seconds; the remote's own dialog waits about this long


def _receivers():
    """The remote's receiver list, empty if it cannot be read.

    Opening the dialog must not fail because the remote is asleep - the window is where
    the user is told about that. This is the interface boundary, so it catches
    everything on purpose: `hao.receivers_now` handles the situations it can name, and
    anything it cannot must still leave a window the user can read.

    (The former name, `_receivers_or_none`, promised a `None` it never returned.)
    """
    try:
        return hao.receivers_now()
    except Exception:                    # noqa: BLE001 - a dialog must still open
        return []


def responding(receiver: dict) -> bool:
    """Is this blaster reachable right now?

    `<ControllerStatus>` is maintained by the remote from the network manager's link
    events - `RF:ReceiverLinkUp` sets 1, `LinkDown` sets 0, and each persists the
    settings. A receiver with no status recorded is treated as present rather than
    absent: the flag is a positive signal, and an old configuration may predate it.
    """
    return receiver.get("status", 1) != 0


class BlasterScanDialog(QDialog):
    """Run an inclusion window, then let the user choose what to add."""

    def __init__(self, known_macs, parent=None, window: int = DEFAULT_WINDOW):
        super().__init__(parent)
        self.setWindowTitle("Add blasters")
        self.resize(560, 420)
        self._known = set(known_macs or ())
        # Everything the remote already knows, as of opening this dialog. Populated
        # here and not only in start(): the list is drawn once before any scan, and
        # with this empty every blaster fell into the "newly paired" branch - a base
        # that had been paired for weeks was announced as new the moment the window
        # opened.
        self._before: set = {r.get("mac") for r in _receivers()}
        self._scanned = False
        self._window = window
        self._left = window
        self.chosen: list[dict] = []
        self.forgot_pairings = False

        layout = QVBoxLayout(self)
        self._explain = QLabel(
            "The remote will listen for blasters for one minute. Press the pairing "
            "button on each blaster you want to add while it is listening - they will "
            "appear below as they join.")
        self._explain.setWordWrap(True)
        layout.addWidget(self._explain)

        self._clock = QLabel()
        self._clock.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._clock)
        self._bar = QProgressBar()
        self._bar.setRange(0, window)
        self._bar.setVisible(False)
        layout.addWidget(self._bar)

        layout.addWidget(QLabel("Blasters the remote knows:"))
        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        row = QHBoxLayout()
        self._start = QPushButton("Start listening")
        self._start.clicked.connect(self.start)
        self._stop = QPushButton("Stop waiting")
        self._stop.setEnabled(False)
        self._stop.clicked.connect(self.finish)
        row.addWidget(self._start)
        row.addWidget(self._stop)
        row.addStretch()
        layout.addLayout(row)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                         | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._accept)
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self._buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._refresh_list(_receivers())

    # the listening window
    def start(self):
        if not hao.probe().get(hao.HAO_PORT):
            QMessageBox.warning(
                self, "The remote did not answer",
                "The remote's event channel is not reachable.\n\nCheck that the "
                "remote is plugged in and awake, or pair on the remote itself: "
                "Options → RF Receiver Settings → Advanced → Add.")
            return
        try:
            self._before = {r.get("mac") for r in _receivers()}
            hao.start_pairing()
            self._scanned = True
        except hao.NotReachable as exc:
            QMessageBox.warning(self, "Could not start", str(exc))
            return

        self._start.setEnabled(False)
        self._stop.setEnabled(True)
        self._bar.setVisible(True)
        self._left = self._window
        self._tick()
        self._timer.start(1000)

    def _tick(self):
        """Once a second: update the clock and re-read the remote's list.

        The read is a sub-kilobyte HTTP GET, so polling it every second is cheap and
        keeps the interface responsive - no thread needed for the waiting itself.
        """
        self._clock.setText(f"Listening - {self._left}s left. "
                            "Press the pairing button on each blaster now.")
        self._bar.setValue(self._window - self._left)
        self._refresh_list(_receivers())
        if self._left <= 0:
            self.finish()
            return
        self._left -= 1

    def finish(self):
        """Stop waiting and offer everything that is actually out there.

        "Found" means *responding*, not *new*. A blaster paired months ago is just as
        real as one included a moment ago, and the remote says which are reachable
        through `<ControllerStatus>`, so both are offered. One that is known but silent
        is shown as not responding and is not offered.
        """
        self._timer.stop()
        self._stop.setEnabled(False)
        self._bar.setVisible(False)
        receivers = _receivers()
        self._refresh_list(receivers)
        offerable = [r for r in receivers
                     if responding(r) and r.get("mac") not in self._known]
        silent = [r for r in receivers if not responding(r)]
        if offerable:
            self._clock.setText(f"Finished - {len(offerable)} blaster(s) to add. "
                                "Tick the ones you want.")
        elif silent:
            self._clock.setText(
                f"Finished - nothing to add. {len(silent)} blaster(s) the remote "
                "knows are not responding; check they are powered and in range.")
        else:
            self._clock.setText(
                "Finished - nothing new. Every blaster the remote can reach is "
                "already in this project.")
        self._start.setEnabled(True)
        self._start.setText("Listen again")
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(bool(offerable))

    # the list
    def _refresh_list(self, receivers):
        """Everything the remote knows, saying plainly which are already in the project.

        Showing the pre-existing ones is deliberate: hiding them makes an empty list
        look like a failure when in fact the blaster is already set up.
        """
        # The list is rebuilt on every scan and poll, so the current tick state has to
        # be carried across or a refresh silently re-ticks what the user deselected.
        #
        # `seen` is separate from `ticked` because "not ticked" and "not previously on
        # screen" need opposite defaults: a base the user unticked stays unticked, and a
        # base that has only just appeared is offered ticked.
        seen, ticked = set(), set()
        for i in range(self._list.count()):
            item = self._list.item(i)
            mac = (item.data(Qt.ItemDataRole.UserRole) or {}).get("mac")
            seen.add(mac)
            if item.checkState() == Qt.CheckState.Checked:
                ticked.add(mac)
        self._list.clear()
        for receiver in receivers:
            mac = receiver.get("mac")
            already = mac in self._known
            live = responding(receiver)
            if not live:
                note = " - not responding"
            elif already:
                note = " - already in this project"
            elif mac in self._before:
                note = " - already paired, responding"
            elif self._scanned:
                note = " - newly paired"
            else:
                # Not seen when the dialog opened and no scan has run, so it appeared
                # some other way (paired from the remote's own menu meanwhile).
                note = " - responding"
            item = QListWidgetItem(
                f"Base {receiver.get('label')}   {mac}"
                f"   firmware {receiver.get('firmware', '?')}{note}")
            item.setData(Qt.ItemDataRole.UserRole, receiver)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # Only something reachable and not already here can be added.
            if already or not live:
                item.setCheckState(Qt.CheckState.Checked if already
                                   else Qt.CheckState.Unchecked)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            elif mac in seen:
                item.setCheckState(Qt.CheckState.Checked if mac in ticked
                                   else Qt.CheckState.Unchecked)
            else:
                item.setCheckState(Qt.CheckState.Checked)
            self._list.addItem(item)

    def _accept(self):
        self.chosen = [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
            and self._list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled]
        self.accept()

    def reject(self):
        self._timer.stop()
        super().reject()
