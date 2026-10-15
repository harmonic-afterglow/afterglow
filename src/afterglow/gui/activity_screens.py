"""An activity's screen as a set of tabs, for a remote that shows it that way (the 1100).

The Harmony 1100 does not give an activity one page of buttons. It gives it up to four
tabs - Transport, Numbers, one of Favorites / Game controller / Discs, and a page of
buttons - each turned on by a property of the activity, each with named places of its
own and side bars down both edges (afterglow-research/harmony-1100.md). The remote's
profile describes them (`RemoteProfile.activity_screens`); this page edits them.

The activity keeps them as `screen_groups`, the form an imported 1100 activity already
has. Nothing is written until something here changes, so an activity from an older
project - its buttons in `soft_buttons`, no tabs of its own - builds as it always did.
"""
from __future__ import annotations

from ..qt.QtCore import Qt
from ..qt.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QMenu, QPushButton, QTabWidget, QVBoxLayout, QWidget,
                             QWizardPage)
from ..qt.QtGui import QCursor, QIcon

from .activity_buttons import ScreenButtonDialog, ScreenButtonsPage
from .icons import pixmap as glyph_pixmap

TITLES = {"Transport": "Transport", "Numbers": "Numbers", "Favorites": "Favourites",
          "GameController": "Game controller", "Discs": "Discs", "Misc": "Buttons"}
CORNER_CHOICE = 3        # Favourites, Game controller and Discs share a corner: one shows


def tab_groups(existing: dict) -> dict:
    """{group name: its buttons} as the activity has them. An activity with no tabs of
    its own has its plain list of buttons on the page of buttons."""
    groups = {name: list(buttons) for name, buttons in existing.get("screen_groups") or []}
    if not groups and existing.get("soft_buttons"):
        groups["Misc"] = [dict(_as_dict(entry), position=index)
                          for index, entry in enumerate(existing["soft_buttons"])
                          if entry is not None]
    return groups


def _as_dict(entry) -> dict:
    if isinstance(entry, dict):
        return dict(entry)
    return {"label": entry[0], "device": entry[1], "command": entry[2],
            **({"icon": entry[3]} if len(entry) > 3 else {})}


def slot_name(slot: str) -> str:
    """A place as people read it: SideBarLeft2 is Left 2, NumberStar is *."""
    for side in ("Left", "Right"):
        if slot.startswith(f"SideBar{side}"):
            return f"{side} {slot[len('SideBar') + len(side):]}"
    return {"NumberStar": "*", "NumberInput": "#", "FrameAdvance": "Slow",
            "SkipBack": "Skip back", "SkipForward": "Skip forward",
            "FastForward": "Fast forward", "DiscNext": "Next disc"}.get(
        slot, slot.replace("Number", "") if slot.startswith("Number") else slot)


class _SlotButton(QPushButton):
    """One named place: shows what is on it, and is clicked to change it."""

    def __init__(self, slot: str, page: "ActivityTabsPage", group: str):
        super().__init__()
        self.slot, self.page, self.group = slot, page, group
        self.setMinimumSize(88, 44)
        self.clicked.connect(self._menu)
        self.refresh()

    def entry(self):
        return self.page.slot_entry(self.group, self.slot)

    def refresh(self):
        entry = self.entry()
        icon = (entry or {}).get("icon")
        glyph = glyph_pixmap(icon, 24) if icon else None
        self.setIcon(QIcon(glyph) if glyph is not None and not glyph.isNull() else QIcon())
        # Logitech often leaves a fixed place unlabelled - the remote draws Play or 7
        # itself - so a place shows its own name when its button has no text.
        name = slot_name(self.slot)
        self.setText(f"{name}\n(nothing)" if entry is None
                     else (entry.get("label") or name))
        # an empty place is dimmed, as the remote dims one nothing is on
        self.setFlat(entry is None)
        self.setToolTip(f"{self.slot}: " + (self.page.describe(entry) if entry
                                            else "nothing"))

    def _menu(self):
        menu = QMenu(self)
        menu.addSection(self.slot)
        change = menu.addAction("Set…" if self.entry() is None else "Change…")
        clear = menu.addAction("Nothing")
        clear.setEnabled(self.entry() is not None)
        chosen = menu.exec(QCursor.pos())
        if chosen is change:
            self.page.edit_slot(self.group, self.slot)
        elif chosen is clear:
            self.page.set_slot(self.group, self.slot, None)


class ActivityTabsPage(QWizardPage):
    """The tabs of an activity's screen: which show, which it opens on, and what is on
    each one's named places, its side bars and its page of buttons."""

    def __init__(self, devices, existing, parent=None, remote=None):
        super().__init__(parent)
        self.devices = devices
        self.remote = remote
        self.model = remote.activity_screens
        existing = existing or {}
        self._existing = existing
        self._groups = tab_groups(existing)
        self._properties = dict(existing.get("properties") or {})
        self._changed = False
        self._participating = None
        self.setTitle("Screen buttons")
        self.setSubTitle(
            "The tabs this activity's screen has on the remote, and what is on each. "
            "Click a place to put a command or a macro on it.")
        layout = QVBoxLayout(self)

        opens = QHBoxLayout()
        opens.addWidget(QLabel("Opens on:"))
        self.start = QComboBox()
        opens.addWidget(self.start)
        opens.addStretch()
        layout.addLayout(opens)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._shown: dict[str, QCheckBox] = {}
        self._slots: list[_SlotButton] = []
        self._misc = None
        for tab in self.model["tabs"]:
            self.tabs.addTab(self._tab(tab), TITLES.get(tab["group"], tab["group"]))
        self._fill_start()
        self.start.currentIndexChanged.connect(self._mark)

    # - Building the tabs ----------------------------------------------------
    def _tab(self, tab: dict) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        shown = QCheckBox("Show this tab")
        shown.setChecked(self._is_shown(tab))
        shown.toggled.connect(lambda on, tab=tab: self._toggled(tab, on))
        if tab.get("corner") == CORNER_CHOICE:
            shown.setToolTip("Favourites, Game controller and Discs share a corner of the "
                             "screen: the remote shows only one of them.")
        self._shown[tab["group"]] = shown
        layout.addWidget(shown)

        body = QHBoxLayout()
        body.addWidget(self._side_bar(tab["group"], "Left"))
        middle = QVBoxLayout()
        if tab.get("channels"):
            note = QLabel("Shows the activity's favourite channels, which are set on the "
                          "Favourites page.")
            note.setWordWrap(True)
            middle.addWidget(note)
        elif tab["group"] == "Misc":
            existing = {"label": self._existing.get("label"),
                        "soft_buttons": self._misc_entries()}
            self._misc = ScreenButtonsPage(self.devices, existing, remote=self.remote)
            self._misc.setTitle("")
            self._misc.setSubTitle("")
            self._misc.table.model().rowsInserted.connect(self._mark)
            self._misc.table.model().rowsRemoved.connect(self._mark)
            self._misc.table.model().rowsMoved.connect(self._mark)
            middle.addWidget(self._misc)
        else:
            layout_rows, note = self._layout(tab)
            if note:
                warning = QLabel(note)
                warning.setWordWrap(True)
                middle.addWidget(warning)
            grid = QGridLayout()
            for row, cells in enumerate(layout_rows):
                for column, slot in enumerate(cells):
                    if slot:
                        button = _SlotButton(slot, self, tab["group"])
                        self._slots.append(button)
                        grid.addWidget(button, row, column)
            box = QGroupBox()
            box.setLayout(grid)
            middle.addWidget(box)
            middle.addStretch()
        body.addLayout(middle, 1)
        body.addWidget(self._side_bar(tab["group"], "Right"))
        layout.addLayout(body, 1)
        return page

    def _side_bar(self, group: str, side: str) -> QGroupBox:
        box = QGroupBox(f"{side} side")
        column = QVBoxLayout(box)
        for slot in self.model.get("side_bars") or []:
            if slot.startswith(f"SideBar{side}"):
                button = _SlotButton(slot, self, group)
                self._slots.append(button)
                column.addWidget(button)
        column.addStretch()
        return box

    def _layout(self, tab: dict) -> tuple[list, str]:
        """The tab's places, and anything to say about them. The game controller tab
        draws the pad of the activity's main device - by its model, as the remote
        decides - and nothing at all for a model it does not know."""
        if "layouts" not in tab:
            return tab["layout"], ""
        model = next((d.get("model") for d in self.devices
                      if d.get("id") == self._existing.get("control")), None) or ""
        for name, models in (tab.get("layout_by_model") or {}).items():
            if model in models:
                return tab["layouts"][name], ""
        first = next(iter(tab["layouts"].values()))
        return first, (f"The remote shows this tab empty: it draws a pad only for a "
                       f"main device whose model is an Xbox or a PlayStation, and this "
                       f"activity's is {model or 'not set'}.")

    # - Tabs on and off ---------------------------------------------------------
    def _is_shown(self, tab: dict) -> bool:
        value = self._properties.get(tab["flag"])
        if value is not None:
            return value == "True"
        if self._existing.get("properties_complete"):
            return False
        return tab["flag"] in self.remote.activity_tabs(self._existing)

    def _toggled(self, tab: dict, on: bool):
        if on and tab.get("corner") == CORNER_CHOICE:
            for other in self.model["tabs"]:
                if other is not tab and other.get("corner") == CORNER_CHOICE:
                    self._shown[other["group"]].setChecked(False)
        self._fill_start()
        self._mark()

    def _fill_start(self):
        current = self.start.currentData() or self._properties.get(
            self.model.get("start_property", ""))
        self.start.blockSignals(True)
        self.start.clear()
        for tab in self.model["tabs"]:
            if self._shown[tab["group"]].isChecked():
                self.start.addItem(TITLES.get(tab["group"], tab["group"]), tab["group"])
        index = self.start.findData(current)
        self.start.setCurrentIndex(index if index >= 0 else self.start.findData("Numbers"))
        self.start.blockSignals(False)

    # - Places ------------------------------------------------------------------
    def slot_entry(self, group: str, slot: str):
        return next((entry for entry in self._groups.get(group) or []
                     if entry.get("slot") == slot), None)

    def set_slot(self, group: str, slot: str, entry):
        buttons = [b for b in self._groups.get(group) or [] if b.get("slot") != slot]
        if entry is not None:
            buttons.append(dict(entry, slot=slot))
        self._groups[group] = buttons
        for button in self._slots:
            if button.group == group and button.slot == slot:
                button.refresh()
        self._mark()

    def edit_slot(self, group: str, slot: str):
        current = self.slot_entry(group, slot)
        dialog = ScreenButtonDialog(self.devices, self, participating=self._participating,
                                    existing=current)
        if dialog.exec() and dialog.result_data:
            self.set_slot(group, slot, {k: v for k, v in dialog.result_data.items()
                                        if k != "slot"})

    def describe(self, entry: dict) -> str:
        if entry.get("macro"):
            return f"{len(entry['macro'])} steps"
        name = next((d.get("label", "?") for d in self.devices
                     if d.get("id") == entry.get("device")), entry.get("device"))
        return f"{name} · {entry.get('command')}"

    def set_participating(self, ids):
        self._participating = list(ids or [])
        if self._misc is not None:
            self._misc.set_participating(ids)

    def _misc_entries(self) -> list:
        """The page of buttons as a list in position order, a None for each gap."""
        misc = [entry for entry in self._groups.get("Misc") or [] if not entry.get("slot")]
        placed = {entry["position"]: entry for entry in misc
                  if entry.get("position") is not None}
        loose = [entry for entry in misc if entry.get("position") is None]
        return [placed.get(position) for position in range(max(placed, default=-1) + 1)
                ] + loose

    # - Out ---------------------------------------------------------------------
    def _mark(self, *_args):
        self._changed = True

    def apply(self, spec: dict) -> None:
        """Write the tabs into `spec` - after its properties, whose flags these are - if
        anything here was changed."""
        if not self._changed:
            return
        groups = dict(self._groups)
        if self._misc is not None:
            side = [entry for entry in groups.get("Misc") or [] if entry.get("slot")]
            listed = [dict(_as_dict(entry), position=index)
                      for index, entry in enumerate(self._misc.get_buttons())
                      if entry is not None]
            groups["Misc"] = side + listed
        # the activity's own order, then any tab it gains
        order = [name for name, _buttons in self._existing.get("screen_groups") or []]
        order += [tab["group"] for tab in self.model["tabs"] if tab["group"] not in order]
        spec["screen_groups"] = [[name, groups[name]] for name in order
                                 if groups.get(name)]
        spec.pop("soft_buttons", None)
        properties = dict(spec.get("properties") or {})
        for tab in self.model["tabs"]:
            properties[tab["flag"]] = ("True" if self._shown[tab["group"]].isChecked()
                                       else "False")
        if self.start.currentData():
            properties[self.model.get("start_property", "ActivityStartPage")] = \
                self.start.currentData()
        spec["properties"] = properties

    def get_buttons(self) -> list:
        """The page of buttons, for code that asks every screen page for its list."""
        return self._misc.get_buttons() if self._misc is not None else []
