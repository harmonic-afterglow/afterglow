"""The editor frame the device and activity editors share: sections, not tabs.

A list on the left, the chosen section on the right, and the section's title and a line
saying what it is for across the top - where a wizard puts its page's, so adding
something and editing it look alike (StepWizard). The two editors used to be tab strips, and a tab strip shows a
wizard page without the title and subtitle the page was written with - so editing a
device lost every explanation adding it had given. The page's own title and subtitle
are shown here instead.

Sections most people never need are listed after a heading that says so, "Usually left
as they are": the values in them come from the device database or an imported
configuration, and are right unless something is wrong. Nothing is hidden - a heading
tells people when to edit and when to leave alone, which a hidden page cannot.
"""
from __future__ import annotations

from ..qt.QtCore import Qt
from ..qt.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QScrollArea, QStackedWidget,
                             QVBoxLayout, QWidget, QWizard, QWizardPage)

ROLE = Qt.ItemDataRole.UserRole
SELDOM = "Usually left as they are"


class SectionDialog(QDialog):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 640)
        self._names: list[str] = []
        self._seldom_heading = None

        # The section's title and explanation across the top, over the list, as a
        # wizard shows its page's - so adding and editing look like one thing.
        outer = QVBoxLayout(self)
        self.heading = QLabel()
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        self.explain = QLabel()
        self.explain.setWordWrap(True)
        self.explain.setContentsMargins(10, 0, 0, 0)
        outer.addWidget(self.heading)
        outer.addWidget(self.explain)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(line)
        self._headings: dict[str, tuple[str, str]] = {}
        body = QHBoxLayout()
        outer.addLayout(body, 1)

        self.list = QListWidget()
        self.list.setFixedWidth(190)
        self.list.setSpacing(1)
        body.addWidget(self.list)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.list.currentItemChanged.connect(self._chosen)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                        QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

    def add_section(self, name: str, label: str, widget: QWidget, *, seldom=False):
        """Add a section. `seldom` lists it under "Usually left as they are"."""
        if seldom and self._seldom_heading is None:
            self._seldom_heading = QListWidgetItem(SELDOM)
            self._seldom_heading.setFlags(Qt.ItemFlag.NoItemFlags)
            font = self._seldom_heading.font()
            font.setPointSizeF(font.pointSizeF() * 0.9)
            font.setBold(True)
            self._seldom_heading.setFont(font)
            self._seldom_heading.setForeground(self.palette().placeholderText())
            self.list.addItem(self._seldom_heading)
        elif not seldom and self._seldom_heading is not None:
            raise ValueError("the sections people need come before the seldom ones")
        item = QListWidgetItem(("    " if seldom else "") + label)
        item.setData(ROLE, name)
        self.list.addItem(item)
        self.stack.addWidget(_scrolled(widget))
        self._headings[name] = _heading(widget, label)
        self._names.append(name)
        if self.list.currentItem() is None:
            self.list.setCurrentItem(item)

    def section_names(self) -> list[str]:
        return list(self._names)

    def section_labels(self) -> list[str]:
        return [self.list.item(i).text().strip() for i in range(self.list.count())
                if self.list.item(i).data(ROLE)]

    def show_section(self, name: str):
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE) == name:
                self.list.setCurrentRow(i)
                return

    def current_section(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ROLE) if item else None

    def _chosen(self, item, _previous=None):
        if item is None or not item.data(ROLE):
            return
        name = item.data(ROLE)
        self.stack.setCurrentIndex(self._names.index(name))
        title, subtitle = self._headings[name]
        self.heading.setText(title)
        self.explain.setText(subtitle)
        self.explain.setVisible(bool(subtitle))
        self.section_shown(name)

    def section_shown(self, name: str):
        """Called whenever a section is brought up; editors refresh what depends on
        the other sections here."""


def _heading(widget: QWidget, label: str) -> tuple[str, str]:
    """A wizard page brings its title and explanation; any other widget is titled with
    its label."""
    if isinstance(widget, QWizardPage):
        return widget.title() or label, widget.subTitle()
    return label, ""


def _scrolled(widget: QWidget) -> QWidget:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(widget)
    return scroll


class StepWizard(QWizard):
    """A wizard that looks like the editors: the steps listed on the left, the current
    one marked, and each page under its title and explanation. Knowing a wizard is two
    steps long is half of it feeling simple."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.resize(900, 640)
        self.steps = QListWidget()
        self.steps.setFixedWidth(190)
        self.steps.setSpacing(1)
        self.steps.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.steps.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setSideWidget(self.steps)
        self._step_ids: list[int] = []
        self.currentIdChanged.connect(self._mark_step)

    def add_step(self, label: str, page: QWizardPage) -> int:
        page_id = self.addPage(page)
        self._step_ids.append(page_id)
        self.steps.addItem(QListWidgetItem(f"{len(self._step_ids)}. {label}"))
        return page_id

    def step_labels(self) -> list[str]:
        return [self.steps.item(i).text() for i in range(self.steps.count())]

    def hide_step(self, page_id: int, hidden: bool):
        """A step only some paths take, such as the commands of a learned device."""
        if page_id in self._step_ids:
            self.steps.item(self._step_ids.index(page_id)).setHidden(hidden)

    def _mark_step(self, page_id):
        for row, step in enumerate(self._step_ids):
            item = self.steps.item(row)
            font = item.font()
            font.setBold(step == page_id)
            item.setFont(font)
            item.setForeground(self.palette().text() if step == page_id
                               else self.palette().placeholderText())
