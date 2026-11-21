"""A remote sold under several names - the 600, 650 and 665 - is each of them: the
project says which by its skin, and the skin is shown, kept and changed like the remote.
It was lost when the remote was made the default, unreachable through Change remote, and
the window called every one of them "Harmony 600 / 650 / 665"."""
from __future__ import annotations

import dataclasses

import pytest

from afterglow import ezhex, remotes


def test_a_model_is_named_by_its_skin():
    profile = remotes.get("harmony-650")
    assert remotes.model_name(profile, 71) == "Harmony 600"
    assert remotes.model_name(profile, 75) == "Harmony 665"
    assert remotes.model_name(profile, None) == profile.model
    assert remotes.model_name(profile, 61) == profile.model      # not one of its skins


def test_change_remote_offers_the_projects_other_models(qapp_or_skip):
    from afterglow.gui.remote_bar import ChooseRemoteDialog
    profiles = [p for p in remotes.load_all() if p.buildable]
    dialog = ChooseRemoteDialog(profiles, "Change remote", "", exclude=("harmony-650", 72),
                                known=profiles)
    offered = {(dialog.list.item(i).data(256), dialog.list.item(i).data(257))
               for i in range(dialog.list.count()) if dialog.list.item(i).data(256)}
    assert ("harmony-650", 72) not in offered
    assert {("harmony-650", 71), ("harmony-650", 75)} <= offered
    assert ("harmony-700", remotes.get("harmony-700").skins[0]) in offered


def test_making_a_600_the_default_keeps_it_a_600(qapp_or_skip, tmp_path, monkeypatch):
    from afterglow.qt.QtCore import QSettings
    from afterglow.qt.QtWidgets import QMessageBox

    from afterglow.gui import default_remote
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    default_remote.set_default_remote("harmony-900", settings)
    assert default_remote.offer_after_change(None, remotes.get("harmony-650"), settings,
                                             skin=71)
    assert default_remote.default_remote_id(settings) == "harmony-650"
    assert default_remote.default_remote_skin(settings) == 71


@pytest.fixture
def window(qapp_or_skip, monkeypatch):
    from afterglow.qt.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from afterglow.gui.app import MainWindow
    win = MainWindow()
    win.project["settings"].update(remote="harmony-650", skin=71)
    win._reload_tabs()
    yield win
    win._dirty = False
    win.close()


def test_the_status_bar_names_the_model(window):
    assert window.status.remote.text().startswith("Harmony 600 ")


@pytest.mark.parametrize("skin, offered", [(71, False), (72, True)])
def test_reading_another_model_of_the_remote_offers_to_move(window, tmp_path, monkeypatch,
                                                            skin, offered):
    from afterglow.qt.QtWidgets import QMessageBox
    asked, moved = [], []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda _p, _t, text, *a: asked.append(text)
                        or QMessageBox.StandardButton.Yes)
    window.update_tab.migrate_requested.disconnect()
    window.update_tab.migrate_requested.connect(lambda *args: moved.append(args))
    read = dataclasses.replace(remotes.get("harmony-650"), skin=skin)
    path = tmp_path / "read.ezhex"
    path.write_bytes(ezhex.header_for_profile(read) + b"GSPM")
    window.update_tab._name_what_was_read(str(path))
    assert bool(asked) is offered
    if offered:
        assert "Harmony 650" in asked[0] and "Harmony 600" in asked[0]
        assert moved == [("harmony-650", 72)]


def test_the_chooser_lists_each_model_and_searches_them(qapp_or_skip):
    from afterglow.gui.remote_bar import ChooseRemoteDialog
    profiles = [p for p in remotes.load_all() if p.buildable]
    dialog = ChooseRemoteDialog(profiles, "New project", "", known=profiles)

    def shown():
        return [dialog.list.item(i).text().rsplit(" - ", 1)[0] for i in range(dialog.list.count())
                if not dialog.list.item(i).isHidden() and dialog.list.item(i).data(256)]
    assert {"Harmony 600", "Harmony 650", "Harmony 665", "Harmony 700"} <= set(shown())
    dialog.search.setText("harmony 6")
    assert set(shown()) >= {"Harmony 600", "Harmony 650", "Harmony 665"}
    assert "Harmony 700" not in shown() and "Harmony 900" not in shown()
    assert dialog.chosen() == "harmony-650"           # the current one is among those shown
    dialog.search.setText("665")
    assert shown() == ["Harmony 665"] and dialog.chosen_skin() == 75
