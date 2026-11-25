"""Which models in the IR database imported devices are (device_match), asked first.

A Harmony One, 650 or 5xx keeps a device's commands but not its maker or model, so an
import leaves "Humax DVR" knowing nothing of what it is. After such an import Afterglow
asks whether to look its devices up by the codes they send; a device whose codes and
name point at one model is set, and where many models send the same codes - one Panasonic
set is 459 models - the person picks from all of them, with a search. Find model... on a
device's menu opens the same window for one device. A remote whose configuration keeps
every device's model (the 900, the 1100: capability "device_models") is never asked.
"""
from __future__ import annotations

import logging

from .. import device_match
from ..qt.QtCore import Qt
from ..qt.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QVBoxLayout, QWidget,
)

LEAVE = "Leave as it is"
TITLE = "Find models"


def _archive():
    from .. import harmony_archive, paths
    from ..corpus_provider import logitech_archive_url
    return harmony_archive.ApiArchive(
        logitech_archive_url(), paths.cache_dir() / "sources" / "harmony-ir-archive")


def _model_name(model: dict) -> str:
    """"Apple Apple TV" is "Apple TV": a model often names its maker already."""
    maker, name = str(model.get("manufacturer") or ""), str(model.get("model") or "")
    if name.casefold().startswith(maker.casefold() + " ") or not maker:
        return name
    return f"{maker} {name}".strip()


def _model_text(suggestion: dict, model: dict) -> str:
    kind = model.get("type") or ""
    return " - ".join(part for part in (
        _model_name(model), kind,
        f"sends {suggestion['matched']} of {suggestion['keyed']} of its commands") if part)


def _matches(query: str, model: dict) -> bool:
    said = " ".join(str(model.get(field) or "") for field in
                    ("manufacturer", "model", "type")).casefold()
    return all(word in said for word in query.casefold().split())


class MatchReview(QDialog):
    """One row a device, and for the one selected every model that sends its codes,
    searchable, with "Leave as it is" first. `chosen[i]` is ``(suggestion, model)`` or
    None for row i; a confident match starts chosen."""

    def __init__(self, rows, parent=None):
        """`rows`: ``(device, found, preset)`` each - the device, its suggestions
        (device_match.suggest) and the ``(suggestion, model)`` it starts as, or None."""
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.rows = rows
        self.options = [device_match.candidates(found) for _device, found, _preset in rows]
        self.chosen = [preset for _device, _found, preset in rows]
        self.resize(820 if len(rows) > 1 else 560, 480)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Many models send the same codes. Pick the model each device is, or leave "
            "it as it is. A picked model gives the device its maker and model, and names "
            "the commands the remote could not." if len(rows) > 1 else
            "The models that send this device's codes, the closest first. A picked model "
            "gives the device its maker and model, and names the commands the remote "
            "could not.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        body = QHBoxLayout()
        self.devices = QListWidget()
        self.devices.setAccessibleName("Devices")
        for index in range(len(rows)):
            self.devices.addItem(QListWidgetItem(self._device_text(index)))
        self.devices.currentRowChanged.connect(self._show_device)
        self.devices.setMaximumWidth(300)
        self.devices.setVisible(len(rows) > 1)
        body.addWidget(self.devices)

        right = QWidget()
        side = QVBoxLayout(right)
        side.setContentsMargins(0, 0, 0, 0)
        self.question = QLabel()
        self.question.setWordWrap(True)
        side.addWidget(self.question)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search makers and models")
        self.search.setAccessibleName("Search makers and models")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        side.addWidget(self.search)
        self.models = QListWidget()
        self.models.setAccessibleName("Models")
        self.models.currentItemChanged.connect(self._pick)
        side.addWidget(self.models)
        self.count = QLabel()
        self.count.setStyleSheet("color: gray;")
        side.addWidget(self.count)
        body.addWidget(right, stretch=1)
        layout.addLayout(body, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        first = next((i for i, preset in enumerate(self.chosen) if preset is None), 0)
        self.devices.setCurrentRow(first)
        self._show_device(first)

    def _device_text(self, index: int) -> str:
        device = self.rows[index][0]
        chosen = self.chosen[index]
        picked = _model_name(chosen[1]) if chosen else LEAVE.casefold()
        return f"{device.get('label') or 'Device'} - {picked}"

    def _show_device(self, index: int):
        if not 0 <= index < len(self.rows):
            return
        self._row = index
        device = self.rows[index][0]
        # a search is for one device: "e55" for the TV hid every model of the next one
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.question.setText(f"Which model is {device.get('label') or 'this device'}?")
        self.models.blockSignals(True)
        self.models.clear()
        leave = QListWidgetItem(LEAVE)
        leave.setData(Qt.ItemDataRole.UserRole, None)
        self.models.addItem(leave)
        current = leave
        for number, (suggestion, model) in enumerate(self.options[index]):
            item = QListWidgetItem(_model_text(suggestion, model))
            item.setData(Qt.ItemDataRole.UserRole, number)
            self.models.addItem(item)
            if self.chosen[index] and self.chosen[index][1] is model:
                current = item
        self.models.setCurrentItem(current)
        self.models.blockSignals(False)
        self._filter(self.search.text())

    def _filter(self, text: str):
        options = self.options[self._row]
        shown = 0
        for row in range(1, self.models.count()):
            item = self.models.item(row)
            hidden = not _matches(text, options[item.data(Qt.ItemDataRole.UserRole)][1])
            item.setHidden(hidden)
            shown += not hidden
        self.count.setText(f"{shown} of {len(options)} models" if text.strip() else
                           f"{len(options)} models")

    def _pick(self, item, _previous=None):
        if item is None:
            return
        number = item.data(Qt.ItemDataRole.UserRole)
        self.chosen[self._row] = None if number is None else self.options[self._row][number]
        self.devices.item(self._row).setText(self._device_text(self._row))


def look_up(parent, project: dict, indices, *, ask: bool) -> bool:
    """Look ``project``'s devices at ``indices`` up in the IR database and set those
    picked. ``ask``: an import's offer - asked first, and a confident match set without
    a window when nothing else needs choosing. Whether anything changed."""
    from . import background

    devices = [project["devices"][index] for index in indices]
    if not devices:
        return False
    if ask:
        names = ", ".join(device.get("label") or "Device" for device in devices)
        if QMessageBox.question(
                parent, TITLE,
                f"{len(devices)} imported device(s) do not say what make or model they "
                f"are: {names}.\n\nLook them up in the IR database by the codes they "
                "send? Afterglow reads the database over the internet, a few seconds a "
                "device. A device whose codes and name point at one model is set; where "
                "several models fit, you pick.\n\nYou can also do this later, one device "
                "at a time, with Find model... in a device's menu.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return False

    archive = _archive()

    def work(device):
        try:
            return device_match.plausible(
                device_match.suggest(device, archive, limit=device_match.CONFIRMED))
        except Exception as exc:                   # offline, or the archive is down
            return exc

    try:
        results = background.each(
            parent, devices, work,
            lambda index, device: f"Looking up {device.get('label') or 'a device'} "
                                  f"({index + 1} of {len(devices)})...", title=TITLE)
    except background.Cancelled:
        return False
    errors = [result for result in results if isinstance(result, Exception)]
    if errors and len(errors) == len(results):
        QMessageBox.warning(parent, TITLE, f"The database could not be read: {errors[0]}")
        return False

    rows, missing, failed = [], [], []
    for device, found in zip(devices, results):
        label = device.get("label") or "Device"
        if isinstance(found, Exception):
            logging.getLogger(__name__).warning("looking up %s: %s", label, found)
            failed.append(label)
        elif not found:
            missing.append(label)
        else:
            rows.append((device, found, device_match.confident(device, found)))
    unread = (f"The database could not be read for: {', '.join(failed)}. Try Find model... "
              "on them later." if failed else "")
    if not rows:
        QMessageBox.information(
            parent, TITLE, "\n\n".join(part for part in (
                ("No model in the database sends "
                 + (f"{missing[0]}'s codes." if len(missing) == 1 else
                    "these devices' codes: " + ", ".join(missing) + ".")) if missing else "",
                unread) if part))
        return False

    chosen = [preset for _device, _found, preset in rows]
    if not ask or any(preset is None for preset in chosen):
        review = MatchReview(rows, parent)
        accepted = review.exec()
        chosen = review.chosen
        review.deleteLater()
        if not accepted:
            return False

    lines, named = [], 0
    for (device, _found, _preset), pick in zip(rows, chosen):
        if pick is None:
            continue
        suggestion, model = pick
        named += len(device_match.apply(device, suggestion, model,
                                        project.get("activities") or []))
        lines.append(f"- {device.get('label') or 'Device'}: {_model_name(model)}")
    if not lines and not missing and not failed:
        return False
    parts = []
    if lines:
        parts.append("Set what these devices are:\n" + "\n".join(lines))
    if named:
        parts.append(f"{named} command(s) the remote could not name are now called what "
                     "their model calls them.")
    if missing:
        parts.append("No model in the database sends the codes of: "
                     + ", ".join(missing) + ".")
    if unread:
        parts.append(unread)
    QMessageBox.information(parent, TITLE, "\n\n".join(parts))
    return bool(lines)


def offer_after_import(parent, project: dict) -> bool:
    """An import's offer to look its devices up: only on a remote whose configuration
    does not keep each device's model, and only for devices that say none and send
    enough codes to be matched by more than chance."""
    from .. import remotes

    try:
        if remotes.for_project(project).can("device_models"):
            return False
    except LookupError:
        return False
    indices = [index for index, device in enumerate(project.get("devices") or [])
               if device_match.worth_looking_up(device)]
    return look_up(parent, project, indices, ask=True) if indices else False
