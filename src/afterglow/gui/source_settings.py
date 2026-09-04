"""Application-wide device-source preferences and their setup dialog.

The private local library contains devices dumped, learned, or saved by this user and
lives outside both projects and the application checkout. External Afterglow databases
are different: they are HTTPS Git repositories, refreshed into a disposable cache.
Only the selected device is materialized into a project, so builds never depend on a
source remaining available.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..afterglow_sources import ExternalRepository, sync_repository
from ..corpus_provider import online_logitech_catalog


@dataclass(frozen=True)
class SourcePreferences:
    """The independently enabled catalogues shown by Add Device."""

    local_devices: bool = True
    # The Logitech archive is the device catalogue: 276,236 devices, and without it Add
    # Device has almost nothing to offer. It reads from a public GitHub mirror, one
    # record at a time, only for models the user actually opens - so it is on by default
    # while the other online catalogues stay opt-in.
    logitech_online: bool = True
    # Read the archive at its tip rather than the revision this release was tested
    # against. Off by default: a pinned revision is what makes a bug report reproducible,
    # and an upstream change cannot reach anyone until the pin is deliberately moved.
    # On, for checking whether something has already been fixed upstream.
    logitech_follow_latest: bool = False
    flipper_irdb_online: bool = False
    irdb_online: bool = False
    external_repositories: tuple[ExternalRepository, ...] = ()

    @classmethod
    def load(cls, settings: QSettings | None = None) -> "SourcePreferences":
        store = settings or QSettings("Afterglow", "Afterglow")
        raw = str(store.value("sources/external_afterglow_repositories", "[]"))
        try:
            records = json.loads(raw)
            repositories = tuple(
                ExternalRepository(str(record["url"]), bool(record.get("enabled", True)))
                for record in records if isinstance(record, dict) and record.get("url"))
        except (TypeError, ValueError, json.JSONDecodeError):
            repositories = ()
        return cls(
            local_devices=_boolean(store.value("sources/local_devices", True)),
            logitech_online=_boolean(store.value("sources/logitech_online", True)),
            logitech_follow_latest=_boolean(
                store.value("sources/logitech_follow_latest", False)),
            flipper_irdb_online=_boolean(
                store.value("sources/flipper_irdb_online", False)),
            irdb_online=_boolean(store.value("sources/irdb_online", False)),
            external_repositories=repositories,
        )

    def save(self, settings: QSettings | None = None) -> None:
        store = settings or QSettings("Afterglow", "Afterglow")
        records = [{"url": entry.normalized_url, "enabled": entry.enabled}
                   for entry in self.external_repositories]
        store.setValue("sources/local_devices", self.local_devices)
        store.setValue("sources/logitech_online", self.logitech_online)
        store.setValue("sources/logitech_follow_latest", self.logitech_follow_latest)
        store.setValue("sources/flipper_irdb_online", self.flipper_irdb_online)
        store.setValue("sources/irdb_online", self.irdb_online)
        store.setValue("sources/external_afterglow_repositories", json.dumps(records))
        for retired in (
            "sources/builtin_library",
            "sources/external_afterglow_databases",
            "sources/logitech_local",
            "sources/logitech_local_path",
        ):
            store.remove(retired)
        store.sync()


def _boolean(value) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


class SourceSettingsDialog(QDialog):
    """Enable the private library and remote device catalogues."""

    def __init__(self, preferences: SourcePreferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Device Sources")
        self.resize(680, 650)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose where Add Device may search. Selected devices are copied into "
            "the project.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.local = QGroupBox("Local devices")
        self.local.setCheckable(True)
        self.local.setChecked(preferences.local_devices)
        local_layout = QVBoxLayout(self.local)
        local_layout.addWidget(QLabel("Devices dumped, learned, or saved by you."))
        layout.addWidget(self.local)

        self.online = QGroupBox("Logitech Harmony IR database (online)")
        self.online.setCheckable(True)
        self.online.setChecked(preferences.logitech_online)
        online_layout = QVBoxLayout(self.online)
        online_layout.addWidget(QLabel(
            "Device definitions dumped from Logitech's former Harmony servers."))
        test_online = QPushButton("Test online source")
        test_online.clicked.connect(self._test_online)
        online_layout.addWidget(test_online, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.online)

        self.flipper_irdb = QGroupBox("Flipper-IRDB (online)")
        self.flipper_irdb.setCheckable(True)
        self.flipper_irdb.setChecked(preferences.flipper_irdb_online)
        flipper_layout = QVBoxLayout(self.flipper_irdb)
        flipper_layout.addWidget(QLabel(
            "Community-maintained Flipper Zero infrared remote files."))
        test_flipper = QPushButton("Test online source")
        test_flipper.clicked.connect(self._test_flipper)
        flipper_layout.addWidget(test_flipper, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.flipper_irdb)

        self.irdb = QGroupBox("IRDB (online)")
        self.irdb.setCheckable(True)
        self.irdb.setChecked(preferences.irdb_online)
        irdb_layout = QVBoxLayout(self.irdb)
        irdb_layout.addWidget(QLabel(
            "Crowd-sourced protocol, device, and function infrared codes."))
        test_irdb = QPushButton("Test online source")
        test_irdb.clicked.connect(self._test_irdb)
        irdb_layout.addWidget(test_irdb, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.irdb)

        external = QGroupBox("External Afterglow databases")
        external_layout = QVBoxLayout(external)
        external_layout.addWidget(QLabel(
            "Afterglow device databases hosted as Git repositories."))
        self.repositories = QListWidget()
        self.repositories.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        for repository in preferences.external_repositories:
            self._append_repository(repository)
        external_layout.addWidget(self.repositories)
        repository_buttons = QHBoxLayout()
        add_repository = QPushButton("Add repository…")
        add_repository.clicked.connect(self._add_repository)
        remove_repository = QPushButton("Remove")
        remove_repository.clicked.connect(self._remove_repository)
        test_repository = QPushButton("Test selected")
        test_repository.clicked.connect(self._test_repository)
        repository_buttons.addWidget(add_repository)
        repository_buttons.addWidget(remove_repository)
        repository_buttons.addWidget(test_repository)
        repository_buttons.addStretch()
        external_layout.addLayout(repository_buttons)
        layout.addWidget(external, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _append_repository(self, repository: ExternalRepository) -> None:
        item = QListWidgetItem(repository.name)
        item.setData(Qt.ItemDataRole.UserRole, repository.url)
        item.setToolTip(repository.normalized_url)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        state = Qt.CheckState.Checked if repository.enabled else Qt.CheckState.Unchecked
        item.setCheckState(state)
        self.repositories.addItem(item)

    def _repository_at(self, row: int) -> ExternalRepository:
        item = self.repositories.item(row)
        return ExternalRepository(
            str(item.data(Qt.ItemDataRole.UserRole)),
            item.checkState() == Qt.CheckState.Checked,
        )

    def preferences(self) -> SourcePreferences:
        repositories = tuple(self._repository_at(row)
                             for row in range(self.repositories.count()))
        return SourcePreferences(
            local_devices=self.local.isChecked(),
            logitech_online=self.online.isChecked(),
            flipper_irdb_online=self.flipper_irdb.isChecked(),
            irdb_online=self.irdb.isChecked(),
            external_repositories=repositories,
        )

    def _add_repository(self):
        selected, accepted = QInputDialog.getText(
            self, "Add Afterglow Database", "HTTPS Git repository URL:")
        if not accepted or not selected.strip():
            return
        repository = ExternalRepository(selected)
        try:
            repository.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Repository", str(exc))
            return
        existing = {self._repository_at(row).normalized_url
                    for row in range(self.repositories.count())}
        if repository.normalized_url not in existing:
            self._append_repository(repository)

    def _remove_repository(self):
        row = self.repositories.currentRow()
        if row >= 0:
            self.repositories.takeItem(row)

    def _validate_and_accept(self):
        try:
            for repository in self.preferences().external_repositories:
                repository.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Repository", str(exc))
            return
        self.accept()

    def _test_repository(self):
        row = self.repositories.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select Repository", "Select a repository first.")
            return
        repository = self._repository_at(row)

        def open_repository():
            from .widgets import load_repo_templates
            return load_repo_templates(sync_repository(repository))

        self._test_source(open_repository, "repository", count_label="devices")

    def _test_online(self):
        self._test_source(
            lambda: online_logitech_catalog().manufacturers(limit=100_000),
            "online source", count_label="manufacturers")

    def _test_flipper(self):
        from ..public_ir_sources import FlipperIrdbCatalog
        self._test_source(
            lambda: FlipperIrdbCatalog().manufacturers(limit=100_000),
            "online source", count_label="manufacturers")

    def _test_irdb(self):
        from ..public_ir_sources import IrdbCatalog
        self._test_source(
            lambda: IrdbCatalog().manufacturers(limit=100_000),
            "online source", count_label="manufacturers")

    def _test_source(self, opener, label: str, *, count_label: str):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            records = opener()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Source Unavailable", str(exc))
        else:
            QMessageBox.information(
                self, "Source Ready",
                f"The {label} contains {len(records):,} {count_label}.")
        finally:
            QApplication.restoreOverrideCursor()
