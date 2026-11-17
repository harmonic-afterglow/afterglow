"""The Flash tab's Cancel: at the right edge, and there only while connecting."""
import pytest


@pytest.fixture
def tab(qapp_or_skip, monkeypatch):
    from afterglow.qt.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from afterglow.gui import usb_driver
    monkeypatch.setattr(usb_driver, "offer_before_operation", lambda *_a: None)
    from afterglow.gui.app import MainWindow
    from afterglow.gui.tabs import UpdateTab
    win = MainWindow()
    tab = win.findChildren(UpdateTab)[0]
    monkeypatch.setattr(tab, "_warn_if_the_link_is_down", lambda: None)
    yield tab
    win.close()


def test_cancel_sits_at_the_right_edge(tab):
    from afterglow.qt.QtWidgets import QHBoxLayout
    row = next(l for l in tab.findChildren(QHBoxLayout) if l.indexOf(tab.flash_btn) >= 0)
    items = [row.itemAt(i) for i in range(row.count())]
    assert items[-1].widget() is tab.cancel_btn
    assert items[-2].spacerItem() is not None        # pushed right by the stretch


def test_cancel_is_there_only_while_connecting(tab):
    tab._busy(True)                                  # building before a flash
    assert tab.cancel_btn.isHidden()
    worker = tab._run("identify")
    assert not tab.cancel_btn.isHidden() and tab.cancel_btn.isEnabled()
    worker.identified.emit()                         # the remote answered: reading or writing
    assert tab.cancel_btn.isHidden()
    tab._busy(False)
    assert tab.cancel_btn.isHidden()


def test_a_failed_connection_takes_cancel_away(tab):
    tab._run("identify")
    tab._busy(False)                                 # what the end of any operation does
    assert tab.cancel_btn.isHidden()
