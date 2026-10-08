"""The user's default remote: asked once, used at startup, offered after a move."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def setup(qapp_or_skip, tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings

    from afterglow.gui import default_remote

    profiles = [SimpleNamespace(id="harmony-900", model="Harmony 900"),
                SimpleNamespace(id="harmony-1100", model="Harmony 1100")]
    monkeypatch.setattr(default_remote, "remote_profiles", lambda: profiles)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    asked = []

    class Chooser:
        answer = "harmony-1100"

        def __init__(self, choices, title, intro, parent=None, selected=None):
            asked.append(selected)

        def exec(self):
            return self.answer is not None

        def chosen(self):
            return self.answer

    monkeypatch.setattr(default_remote, "ChooseRemoteDialog", Chooser)
    return SimpleNamespace(module=default_remote, settings=settings, asked=asked,
                           chooser=Chooser, profiles=profiles)


def test_only_a_remote_that_can_still_be_built_for_counts(setup):
    setup.settings.setValue(setup.module.DEFAULT_REMOTE_KEY, "harmony-one")
    assert setup.module.default_remote_id(setup.settings) is None
    setup.module.set_default_remote("harmony-1100", setup.settings)
    assert setup.module.default_remote_id(setup.settings) == "harmony-1100"


def test_the_first_start_asks_once(setup):
    assert setup.module.ask_at_first_start(None, setup.settings) == "harmony-1100"
    assert setup.module.default_remote_id(setup.settings) == "harmony-1100"
    assert setup.module.ask_at_first_start(None, setup.settings) is None
    assert len(setup.asked) == 1


def test_a_cancelled_first_question_is_not_asked_again(setup):
    setup.chooser.answer = None
    assert setup.module.ask_at_first_start(None, setup.settings) is None
    assert setup.module.ask_at_first_start(None, setup.settings) is None
    assert len(setup.asked) == 1
    assert setup.module.default_remote_id(setup.settings) is None


def test_nothing_to_ask_with_one_remote(setup, monkeypatch):
    monkeypatch.setattr(setup.module, "remote_profiles", lambda: setup.profiles[:1])
    assert setup.module.ask_at_first_start(None, setup.settings) is None
    assert setup.asked == []


def test_changing_it_later_starts_on_the_current_one(setup):
    setup.module.set_default_remote("harmony-1100", setup.settings)
    setup.chooser.answer = "harmony-900"
    assert setup.module.choose_default_remote(None, setup.settings) == "harmony-900"
    assert setup.asked == ["harmony-1100"]


def _answer(monkeypatch, module, button, tick=False):
    from PyQt6.QtWidgets import QMessageBox

    shown = []

    def exec_(box):
        shown.append(box.text())
        box.checkBox().setChecked(tick)
        return button
    monkeypatch.setattr(module.QMessageBox, "exec", exec_)
    return shown, QMessageBox.StandardButton


def test_a_move_offers_the_new_remote(setup, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    shown, _ = _answer(monkeypatch, setup.module, QMessageBox.StandardButton.Yes)
    setup.module.set_default_remote("harmony-900", setup.settings)
    assert setup.module.offer_after_change(None, setup.profiles[1], setup.settings)
    assert setup.module.default_remote_id(setup.settings) == "harmony-1100"
    # Already the default: nothing to offer.
    assert not setup.module.offer_after_change(None, setup.profiles[1], setup.settings)
    assert len(shown) == 1


def test_dont_ask_again_is_kept(setup, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    shown, _ = _answer(monkeypatch, setup.module, QMessageBox.StandardButton.No, tick=True)
    setup.module.set_default_remote("harmony-900", setup.settings)
    assert not setup.module.offer_after_change(None, setup.profiles[1], setup.settings)
    assert not setup.module.offer_after_change(None, setup.profiles[1], setup.settings)
    assert len(shown) == 1
    assert setup.module.default_remote_id(setup.settings) == "harmony-900"


def test_a_new_project_can_be_for_a_given_remote():
    from afterglow.gui.project import new_project

    assert new_project("harmony-1100")["settings"]["remote"] == "harmony-1100"
    assert new_project()["settings"]["remote"] == "harmony-900"


def test_the_startup_project_follows_the_choice_only_while_untouched(qapp_or_skip):
    from afterglow.gui.app import MainWindow

    window = MainWindow()
    window.start_with_default_remote("harmony-1100")
    assert window.project["settings"]["remote"] == "harmony-1100"
    window._mark_dirty()
    window.start_with_default_remote("harmony-900")
    assert window.project["settings"]["remote"] == "harmony-1100"
