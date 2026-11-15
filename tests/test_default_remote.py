"""The user's default remote: asked once, used at startup, offered after a move."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def setup(qapp_or_skip, tmp_path, monkeypatch):
    from afterglow.qt.QtCore import QSettings

    from afterglow.gui import default_remote

    profiles = [SimpleNamespace(id="harmony-900", model="Harmony 900", skins=(61,)),
                SimpleNamespace(id="harmony-1100", model="Harmony 1100", skins=(62, 63))]
    monkeypatch.setattr(default_remote, "remote_profiles", lambda: profiles)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    asked = []

    class Chooser:
        answer = "harmony-1100"

        skin = None

        def __init__(self, choices, title, intro, parent=None, selected=None, **_rest):
            asked.append(selected)

        def exec(self):
            return self.answer is not None

        def chosen(self):
            return self.answer

        def chosen_skin(self):
            return self.skin

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
    from afterglow.qt.QtWidgets import QMessageBox

    shown = []

    def exec_(box):
        shown.append(box.text())
        box.checkBox().setChecked(tick)
        return button
    monkeypatch.setattr(module.QMessageBox, "exec", exec_)
    return shown, QMessageBox.StandardButton


def test_a_move_offers_the_new_remote(setup, monkeypatch):
    from afterglow.qt.QtWidgets import QMessageBox

    shown, _ = _answer(monkeypatch, setup.module, QMessageBox.StandardButton.Yes)
    setup.module.set_default_remote("harmony-900", setup.settings)
    assert setup.module.offer_after_change(None, setup.profiles[1], setup.settings)
    assert setup.module.default_remote_id(setup.settings) == "harmony-1100"
    # Already the default: nothing to offer.
    assert not setup.module.offer_after_change(None, setup.profiles[1], setup.settings)
    assert len(shown) == 1


def test_dont_ask_again_is_kept(setup, monkeypatch):
    from afterglow.qt.QtWidgets import QMessageBox

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


def test_the_model_picked_is_remembered_with_the_remote(setup):
    setup.chooser.answer, setup.chooser.skin = "harmony-1100", 63
    assert setup.module.choose_default_remote(None, setup.settings) == "harmony-1100"
    assert setup.module.default_remote_skin(setup.settings) == 63
    setup.chooser.answer, setup.chooser.skin = "harmony-900", None
    setup.module.choose_default_remote(None, setup.settings)
    assert setup.module.default_remote_skin(setup.settings) is None


def test_the_chooser_lists_every_model_and_searches_them(qapp_or_skip):
    from afterglow import remotes
    from afterglow.gui.remote_bar import ChooseRemoteDialog
    profiles = [remotes.get(r) for r in ("harmony-900", "harmony-650", "harmony-700")]
    dialog = ChooseRemoteDialog(profiles, "Your remote", "Which?", selected="harmony-650",
                                selected_skin=71)
    texts = [dialog.list.item(i).text() for i in range(dialog.list.count())]
    assert any(text.startswith("Harmony 600 ") for text in texts)
    assert any(text.startswith("Harmony 665 ") for text in texts)
    assert "Harmony Touch" in texts                        # listed, not supported yet
    assert (dialog.chosen(), dialog.chosen_skin()) == ("harmony-650", 71)
    dialog.search.setText("665")
    shown = [dialog.list.item(i).text() for i in range(dialog.list.count())
             if not dialog.list.item(i).isHidden()]
    assert shown == ["Harmony 665 · experimental"]
    assert (dialog.chosen(), dialog.chosen_skin()) == ("harmony-650", 75)
    dialog.search.setText("touch")
    assert dialog.chosen() is None                          # only a greyed one matches
