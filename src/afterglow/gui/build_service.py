"""Qt wrapper around the headless build service."""
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..applog import LOG
from ..build_service import ConfigBuildService

__all__ = ["ConfigBuildService", "BuildWorker"]


class BuildWorker(QThread):
    log = pyqtSignal(str)
    success = pyqtSignal()
    failure = pyqtSignal(str)

    def __init__(self, root: Path, project: dict):
        super().__init__()
        self.root, self.project = root, project

    def run(self) -> None:
        try:
            ConfigBuildService(self.root, self.log.emit).build(self.project)
            self.success.emit()
        except Exception as exc:  # shown to the user by UpdateTab
            # The one line shown is rarely enough to find the cause; the log keeps where.
            LOG.exception("Build failed")
            self.failure.emit(str(exc))
