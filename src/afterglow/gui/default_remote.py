"""The remote the user has: each startup and each new project are for it.

Asked once, on the first start, after the connection questions. Settings > Default
Remote changes it, and moving a project to another remote offers to make that one the
default.
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QCheckBox, QMessageBox

from .remote_bar import ChooseRemoteDialog
from .tabs import remote_profiles

DEFAULT_REMOTE_KEY = "ui/default_remote"
ASKED_KEY = "ui/default_remote_asked"
OFFER_NEVER_KEY = "ui/default_remote_never_offer"


def _settings(settings=None) -> QSettings:
    return settings if settings is not None else QSettings("Afterglow", "Afterglow")


def default_remote_id(settings=None) -> str | None:
    """The chosen remote, if it is still one configurations can be built for."""
    chosen = _settings(settings).value(DEFAULT_REMOTE_KEY, "", type=str)
    return chosen if chosen in {profile.id for profile in remote_profiles()} else None


def set_default_remote(remote_id: str, settings=None) -> None:
    store = _settings(settings)
    store.setValue(DEFAULT_REMOTE_KEY, remote_id)
    store.setValue(ASKED_KEY, True)
    store.sync()


def choose_default_remote(parent, settings=None) -> str | None:
    """Ask which remote the user has. The chosen id, or None if they cancelled."""
    store = _settings(settings)
    dialog = ChooseRemoteDialog(
        remote_profiles(), "Your remote",
        "Which Harmony do you have? Afterglow starts with a project for it, and new "
        "projects are for it unless you choose otherwise. Settings → Default Remote "
        "changes it later.", parent, selected=default_remote_id(store))
    chosen = dialog.chosen() if dialog.exec() else None
    if chosen:
        set_default_remote(chosen, store)
    return chosen


def ask_at_first_start(parent, settings=None) -> str | None:
    """Ask once, when there is a choice to make. The chosen id, or None."""
    store = _settings(settings)
    if store.value(ASKED_KEY, False, type=bool) or len(remote_profiles()) < 2:
        return None
    chosen = choose_default_remote(parent, store)
    store.setValue(ASKED_KEY, True)             # a cancel is an answer too
    store.sync()
    return chosen


def offer_after_change(parent, profile, settings=None) -> bool:
    """After a project moved to `profile`: offer to make it the default. True if made."""
    store = _settings(settings)
    if profile.id == default_remote_id(store) or \
            store.value(OFFER_NEVER_KEY, False, type=bool):
        return False
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Default remote")
    box.setText(f"Make the {profile.model} your default remote?")
    box.setInformativeText("Afterglow then starts with a project for it, and new "
                           "projects are for it.")
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    never = QCheckBox("Don't ask again")
    box.setCheckBox(never)
    answer = box.exec()
    if never.isChecked():
        store.setValue(OFFER_NEVER_KEY, True)
        store.sync()
    if answer == QMessageBox.StandardButton.Yes:
        set_default_remote(profile.id, store)
        return True
    return False
