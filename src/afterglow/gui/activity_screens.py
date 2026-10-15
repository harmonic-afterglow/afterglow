"""An activity's screen as a set of tabs, for a remote that shows it that way (the 1100).

The Harmony 1100 does not give an activity one page of buttons. It gives it up to four
screens, picked with the icons in the corners of the display - Transport, Numbers, one of
Favorites / Game controller / Discs, and a page of buttons - each turned on by a property
of the activity, each with named places of its own and side bars down both edges
(afterglow-research/harmony-1100.md). The remote's profile describes them
(`RemoteProfile.activity_screens`); this page edits them.

A fixed place - Play, 7, A - is its own picture. What it sends comes, unless the owner
says otherwise, from the activity's main device: the builder fills it there
(`RemoteProfile.place_defaults`) and this page only shows what that will be. The
activity keeps what the owner chose as `screen_groups`, the form an imported 1100
activity already has; a place emptied on purpose is kept as `{"slot", "blank": True}`.
Nothing is written until something here changes, so an activity from an older project -
its buttons in `soft_buttons`, no tabs of its own - builds as it always did.
"""
from __future__ import annotations

from ..qt.QtCore import QMimeData, QRect, QSize, Qt
from ..qt.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QMenu, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
                             QStyle, QStyleOptionButton, QStylePainter, QTabWidget,
                             QVBoxLayout, QWidget, QWizardPage)
from ..qt.QtGui import QColor, QCursor, QDrag

from .activity_buttons import FavouritesPage, ScreenButtonDialog, ScreenButtonsPage
from .icons import pixmap as glyph_pixmap

TITLES = {"Transport": "Transport", "Numbers": "Numbers", "Favorites": "Favourites",
          "GameController": "Game controller", "Discs": "Discs", "Misc": "Buttons"}


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


PLACE_MIME = "application/x-afterglow-place"


def _dragged(event, group: str):
    """The side-bar place a drag carries, if it is one from this same screen."""
    data = event.mimeData()
    if not data.hasFormat(PLACE_MIME):
        return None
    dragged_group, _, slot = bytes(data.data(PLACE_MIME)).decode().partition("\n")
    return slot if dragged_group == group else None


class _Grip(QLabel):
    """The handle a side button is dragged by, on its outer edge: drop it on another
    place on this screen's side bars and the two change places."""

    def __init__(self, button: "_SlotButton"):
        super().__init__("⠿")
        self.button = button
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move this button to another place on the side bars")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Ignored)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        data = QMimeData()
        data.setData(PLACE_MIME, f"{self.button.group}\n{self.button.slot}".encode())
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.setPixmap(self.button.grab())
        drag.exec(Qt.DropAction.MoveAction)


class _SlotButton(QPushButton):
    """One named place: shows what is on it, and is clicked to change it."""

    def __init__(self, slot: str, page: "ActivityTabsPage", group: str,
                 shows=("label", "icon")):
        super().__init__()
        self.slot, self.page, self.group = slot, page, group
        # what the remote draws here from the configuration; nothing, where the
        # place's own picture is the button
        self.shows = tuple(shows)
        self._glyph = None
        self.setMinimumSize(8, 8)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.clicked.connect(self._menu)
        self.setAcceptDrops(group is not None and slot.startswith("SideBar"))
        self.refresh()

    def dragEnterEvent(self, event):
        if _dragged(event, self.group) not in (None, self.slot):
            event.acceptProposedAction()

    def dropEvent(self, event):
        source = _dragged(event, self.group)
        if source not in (None, self.slot):
            self.page.swap_slots(self.group, source, self.slot)
            event.acceptProposedAction()

    def entry(self):
        """What the owner put here: a button, `{"blank": True}`, or None."""
        return self.page.slot_entry(self.group, self.slot)

    def refresh(self):
        entry = self.entry()
        default = self.page.default_for(self.group, self.slot)
        name = slot_name(self.slot)
        own = entry is not None and not entry.get("blank")
        if own:
            sends, said = self.page.describe(entry, brief=True), self.page.describe(entry)
        elif entry is None and default is not None:
            sends, said = (self.page.describe(default, brief=True),
                           self.page.describe(default))
        else:
            sends = said = None
        icon = (entry or {}).get("icon") if "icon" in self.shows else None
        glyph = glyph_pixmap(icon, 64) if icon else None
        # drawn by paintEvent, behind the label, as the remote draws it
        self._glyph = glyph if glyph is not None and not glyph.isNull() else None
        shown = entry if own else default if entry is None else None
        label = (shown or {}).get("label") if "label" in self.shows else None
        if sends is None:
            self.setText(f"{name}\n(nothing)")
        elif label or self._glyph is not None:
            # a side bar draws its icon with the label over it (floater-group-1); an
            # icon alone is a button with no label
            self.setText(label or "")
        else:
            # a default is in brackets: it follows the main device until it is changed
            self.setText(f"{name}\n{sends}" if own else f"{name}\n({sends})")
        how = "set here" if own else "the main device's own"
        self.setToolTip(f"{self.slot}: " + (f"{said} - {how}" if said else
                                            "nothing; the remote dims it"))

    def paintEvent(self, event):
        """A side bar's icon, centred, with its label over it - the remote's way."""
        if self._glyph is None:
            return super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        text, option.text = option.text, ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        side = int(min(self.width(), self.height()) * 0.7)
        icon = self._glyph.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((self.width() - icon.width()) // 2,
                           (self.height() - icon.height()) // 2, icon)
        if text:
            # white with a dark outline, as the remote writes over its icons: readable
            # on any of them
            centre = int(Qt.AlignmentFlag.AlignCenter)
            painter.setPen(QColor("black"))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(self.rect().translated(dx, dy), centre, text)
            painter.setPen(QColor("white"))
            painter.drawText(self.rect(), centre, text)

    def _menu(self):
        entry, default = self.entry(), self.page.default_for(self.group, self.slot)
        empty = ((entry is not None and entry.get("blank"))
                 or (entry is None and default is None))
        menu = QMenu(self)
        menu.addSection(self.slot)
        change = menu.addAction("Set…" if empty else "Send something else…")
        clear = menu.addAction("Nothing")
        clear.setEnabled(not empty)
        back = None
        if default is not None and entry is not None:
            back = menu.addAction(f"Back to default ({self.page.describe(default)})")
        chosen = menu.exec(QCursor.pos())
        if chosen is change:
            self.page.edit_slot(self.group, self.slot, self.shows)
        elif chosen is clear:
            # with a default to come back, "nothing" has to be said out loud
            self.page.set_slot(self.group, self.slot,
                               {"blank": True} if default is not None else None)
        elif back is not None and chosen is back:
            self.page.set_slot(self.group, self.slot, None)


class _ScreenFrame(QWidget):
    """The remote's screen, at its own shape: 4:3, the 1100's 320 x 240 - the side bars
    down its edges and the screen's places between them. However the window is sized
    the screen keeps its shape, centred, and its text grows and shrinks with it."""

    ASPECT = 4 / 3
    SIDE = 0.2              # each side bar's share of the width

    def __init__(self, left: QWidget, middle: QWidget, right: QWidget):
        super().__init__()
        self.parts = (left, middle, right)
        for part in self.parts:
            part.setParent(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(240, 180)

    def sizeHint(self):
        return QSize(560, 420)

    def screen_rect(self) -> QRect:
        """The largest 4:3 rectangle the widget holds, centred."""
        width = min(self.width(), int(self.height() * self.ASPECT))
        height = int(width / self.ASPECT)
        return QRect((self.width() - width) // 2, (self.height() - height) // 2,
                     width, height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        screen = self.screen_rect()
        side = int(screen.width() * self.SIDE)
        left, middle, right = self.parts
        left.setGeometry(screen.x(), screen.y(), side, screen.height())
        middle.setGeometry(screen.x() + side, screen.y(), screen.width() - 2 * side,
                           screen.height())
        right.setGeometry(screen.right() + 1 - side, screen.y(), side, screen.height())
        font = self.font()
        # 9 points on a screen 360 pixels tall, in proportion either way
        font.setPointSizeF(max(5.0, min(20.0, screen.height() / 40)))
        for part in self.parts:
            part.setFont(font)


class ActivityTabsPage(QWizardPage):
    """The screens of an activity: which show, which it opens on, and what is on each
    one's named places, its side bars and its page of buttons."""

    def __init__(self, devices, existing, parent=None, remote=None):
        super().__init__(parent)
        self.devices = devices
        self.remote = remote
        self.model = remote.activity_screens
        existing = existing or {}
        self._existing = existing
        self._groups = tab_groups(existing)
        self._properties = dict(existing.get("properties") or {})
        self._control = existing.get("control")
        self._changed = False
        self._participating = None
        self._defaults: dict = {}
        self.setTitle("Screen buttons")
        self.setSubTitle(
            "The 1100 shows an activity as up to four screens, picked with the icons in "
            "the corners of its display. A place in brackets sends the main device's own "
            "command; click a place to change it.")
        layout = QVBoxLayout(self)

        opens = QHBoxLayout()
        opens.addWidget(QLabel("Opens on:"))
        self.start = QComboBox()
        opens.addWidget(self.start)
        opens.addStretch()
        layout.addLayout(opens)

        self._on = {tab["group"]: self._is_shown(tab) for tab in self.model["tabs"]}
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._shown: dict[str, QCheckBox] = {}
        self._slots: list[_SlotButton] = []
        self._places: dict[str, QGroupBox] = {}
        self._notes: dict[str, QLabel] = {}
        self._misc = None
        self.favourites = None          # the activity's favourites, on the 1100 here
        self._favourites_warning = None
        self.top_right = None
        self._choice_tabs: list[str] = []
        corners: dict = {}
        for tab in self.model["tabs"]:
            corners.setdefault(tab.get("corner"), []).append(tab)
        # the remote's own order decides when a shared corner has more than one on
        for tabs in corners.values():
            if len(tabs) > 1:
                first = next((tab["group"] for tab in tabs if self._on[tab["group"]]),
                             None)
                for tab in tabs:
                    self._on[tab["group"]] = tab["group"] == first
        self._recompute_defaults()
        for corner, tabs in corners.items():
            if len(tabs) == 1:
                self.tabs.addTab(self._single(tabs[0]), self.screen_title(tabs[0]))
            else:
                self.tabs.addTab(self._choice(tabs), self._corner_name(corner))
        self._fill_start()
        self._favourites_note()
        self.start.currentIndexChanged.connect(self._mark)

    def _corner_name(self, corner) -> str:
        return (self.model.get("corners") or {}).get(str(corner)) or f"Corner {corner}"

    def screen_title(self, tab: dict) -> str:
        """A screen by its corner, as an owner finds it: "Top left: Transport"."""
        corner = (self.model.get("corners") or {}).get(str(tab.get("corner")))
        name = TITLES.get(tab["group"], tab["group"])
        return f"{corner}: {name}" if corner else name

    # - Building the tabs ----------------------------------------------------
    def _single(self, tab: dict) -> QWidget:
        """A corner with one screen: shown or not, and the screen."""
        page = QWidget()
        layout = QVBoxLayout(page)
        shown = QCheckBox("Show this screen")
        shown.setChecked(self._on[tab["group"]])
        shown.toggled.connect(lambda on, tab=tab: self._set_on(tab["group"], on))
        self._shown[tab["group"]] = shown
        layout.addWidget(shown)
        layout.addWidget(self._body(tab), 1)
        return page

    def _choice(self, tabs: list) -> QWidget:
        """A corner several screens share - the 1100's top right: Favourites, Game
        controller or Discs. The remote shows one at most, so one is chosen."""
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel("Shows:"))
        self.top_right = QComboBox()
        self.top_right.addItem("Nothing", None)
        bodies = QStackedWidget()
        bodies.addWidget(QLabel("This corner shows nothing."))
        for tab in tabs:
            self.top_right.addItem(TITLES.get(tab["group"], tab["group"]), tab["group"])
            bodies.addWidget(self._body(tab))
        self._choice_tabs = [tab["group"] for tab in tabs]
        current = next((name for name in self._choice_tabs if self._on[name]), None)
        self.top_right.setCurrentIndex(self.top_right.findData(current))
        bodies.setCurrentIndex(self.top_right.currentIndex())

        def chosen(index):
            bodies.setCurrentIndex(index)
            group = self.top_right.itemData(index)
            for name in self._choice_tabs:
                self._on[name] = name == group
            self._screens_changed()
            self._favourites_note()
        self.top_right.currentIndexChanged.connect(chosen)
        row.addWidget(self.top_right)
        row.addStretch()
        layout.addLayout(row)
        self._favourites_warning = QLabel()
        self._favourites_warning.setWordWrap(True)
        layout.addWidget(self._favourites_warning)
        layout.addWidget(bodies, 1)
        return page

    def _body(self, tab: dict) -> QWidget:
        """A screen as the remote lays it out - its side bars, and between them its
        places - and, for the page of buttons, the list that fills it."""
        if tab["group"] == "Misc":
            existing = {"label": self._existing.get("label"),
                        "soft_buttons": self._misc_entries()}
            self._misc = ScreenButtonsPage(self.devices, existing, remote=self.remote)
            self._misc.setTitle("")
            self._misc.setSubTitle("")
            self._misc.table.model().rowsInserted.connect(self._mark)
            self._misc.table.model().rowsRemoved.connect(self._mark)
            self._misc.table.model().rowsMoved.connect(self._mark)
            # its page of buttons, drawn where the remote draws it
            middle = self._misc.preview
            middle.setTitle("Your buttons - set in the list below")
            middle.let_scale()
        elif tab.get("channels"):
            # the favourites are this screen: on the 1100 they show nowhere else
            self.favourites = FavouritesPage(self.devices, self._existing,
                                             remote=self.remote)
            self.favourites.setTitle("")
            self.favourites.setSubTitle("")
            for signal in (self.favourites.table.model().rowsInserted,
                           self.favourites.table.model().rowsRemoved):
                signal.connect(lambda *_: self._favourites_note())
            middle = self.favourites.preview
            middle.setTitle("Your favourites - set in the list below")
            middle.let_scale()
        else:
            middle = QGroupBox()
            QGridLayout(middle)
        if tab["group"] != "Misc" and not tab.get("channels"):
            # the remote draws these itself: an owner picks what they send, nothing more
            draws = tab.get("draws", ("label", "icon"))
            middle.setTitle("Fixed - the remote's own picture, with your label"
                            if "label" in draws else "Fixed - the remote's own picture")
            middle.setToolTip("The remote draws these buttons itself. You choose only "
                              "what each one sends.")
            self._places[tab["group"]] = middle
        frame = _ScreenFrame(self._side_bar(tab["group"], "Left"), middle,
                             self._side_bar(tab["group"], "Right"))
        if tab["group"] in self._places:
            self._fill_places(tab)
        widget = QWidget()
        column = QVBoxLayout(widget)
        column.setContentsMargins(0, 0, 0, 0)
        note = QLabel()
        note.setWordWrap(True)
        note.hide()
        self._notes[tab["group"]] = note
        column.addWidget(note)
        listed = None
        if self._misc is not None and tab["group"] == "Misc":
            listed, text = self._misc, (
                "This list is the buttons in the middle of the screen above: in its "
                "order, 3 across and 2 down, a page at a time. A gap leaves a place empty.")
        elif self.favourites is not None and tab.get("channels"):
            listed, text = self.favourites, (
                "This list is the logos in the middle of the screen above: in its order, "
                "3 across and 2 down, a page at a time.")
        if listed is None:
            column.addWidget(frame, 1)
            return widget
        # the screen above, the list that fills it below, and a divider to share them
        below = QWidget()
        below_layout = QVBoxLayout(below)
        below_layout.setContentsMargins(0, 0, 0, 0)
        explain = QLabel(text)
        explain.setWordWrap(True)
        below_layout.addWidget(explain)
        below_layout.addWidget(listed, 1)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(frame)
        split.addWidget(below)
        split.setChildrenCollapsible(False)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        column.addWidget(split, 1)
        return widget

    def _fill_places(self, tab: dict):
        """(Re)lay a screen's fixed places - the game pad changes with the main device."""
        box = self._places[tab["group"]]
        grid = box.layout()
        while grid.count():
            widget = grid.takeAt(0).widget()
            if widget in self._slots:
                self._slots.remove(widget)
            widget.deleteLater()
        layout_rows, note = self._layout(tab)
        if tab["group"] in self._notes:
            self._notes[tab["group"]].setText(note)
            self._notes[tab["group"]].setVisible(bool(note))
        for row, cells in enumerate(layout_rows):
            for column, slot in enumerate(cells):
                if slot:
                    button = _SlotButton(slot, self, tab["group"],
                                         shows=tab.get("draws", ("label", "icon")))
                    self._slots.append(button)
                    grid.addWidget(button, row, column)
        if note:
            empty = QLabel("(the remote shows nothing here)")
            grid.addWidget(empty, 0, 0)

    def _side_bar(self, group: str, side: str) -> QGroupBox:
        box = QGroupBox("Your buttons")
        box.setToolTip(f"The {side.lower()} side bar: your own buttons, with a label or "
                       "an icon, on every screen of its own.")
        column = QVBoxLayout(box)
        for slot in self.model.get("side_bars") or []:
            if slot.startswith(f"SideBar{side}"):
                button = _SlotButton(slot, self, group,
                                     shows=self.model.get("side_bar_draws",
                                                          ("label", "icon")))
                self._slots.append(button)
                row = QHBoxLayout()
                row.setSpacing(2)
                grip = _Grip(button)
                # the handle on the outer edge, away from the screen's middle
                for widget in ((grip, button) if side == "Left" else (button, grip)):
                    row.addWidget(widget, 0 if widget is grip else 1)
                column.addLayout(row)
        return box

    def _main_device(self) -> dict:
        return next((d for d in self.devices if d.get("id") == self._control), {})

    def _layout(self, tab: dict) -> tuple[list, str]:
        """The tab's places, and anything to say about them. The game controller tab
        draws the pad of the activity's main device - by its model, as the remote
        decides - and nothing at all for a model it does not know."""
        model = self._main_device().get("model") or ""
        rows = self.remote.tab_layout(tab, model)
        if rows is not None:
            return rows, ""
        if "layouts" not in tab:
            return [], ""
        return [], (f"The remote shows this screen empty: it draws a pad only for a main "
                    f"device whose model is an Xbox or a PlayStation, and this "
                    f"activity's is {model or 'not set'}. The side bars still work.")

    def set_main_device(self, device_id):
        """The activity's main device, as its Devices page now says: the defaults and
        the game pad follow it."""
        if device_id == self._control:
            return
        self._control = device_id
        self._recompute_defaults()
        for tab in self.model["tabs"]:
            if "layouts" in tab and tab["group"] in self._places:
                self._fill_places(tab)
        self._refresh()

    # - Screens on and off -------------------------------------------------------
    def _is_shown(self, tab: dict) -> bool:
        value = self._properties.get(tab["flag"])
        if value is not None:
            return value == "True"
        if self._existing.get("properties_complete"):
            return False
        return tab["flag"] in self.remote.activity_tabs(self._existing)

    def is_shown(self, group: str) -> bool:
        return self._on[group]

    def show_screen(self, group: str, on: bool):
        """Turn a screen on or off, as its checkbox or its corner's choice does."""
        if group in self._shown:
            self._shown[group].setChecked(on)
        elif self.top_right is not None:
            current = self.top_right.currentData()
            self.top_right.setCurrentIndex(self.top_right.findData(
                group if on else (None if current == group else current)))

    def _set_on(self, group: str, on: bool):
        self._on[group] = on
        self._screens_changed()

    def _screens_changed(self):
        self._recompute_defaults()
        self._refresh()
        self._fill_start()
        self._mark()

    def _fill_start(self):
        current = self.start.currentData() or self._properties.get(
            self.model.get("start_property", ""))
        self.start.blockSignals(True)
        self.start.clear()
        for tab in self.model["tabs"]:
            if self._on[tab["group"]]:
                self.start.addItem(self.screen_title(tab), tab["group"])
        index = self.start.findData(current)
        if index < 0:      # as a new activity would open
            index = self.start.findData(self.remote.start_screen(
                [tab["group"] for tab in self.model["tabs"] if self._on[tab["group"]]]))
        self.start.setCurrentIndex(index if index >= 0 else 0)
        self.start.blockSignals(False)

    # - Places ------------------------------------------------------------------
    def _recompute_defaults(self):
        act = {"type": self._existing.get("type"), "control": self._control,
               "properties_complete": self._existing.get("properties_complete"),
               "properties": {tab["flag"]: "True" if self._on[tab["group"]] else "False"
                              for tab in self.model["tabs"]}}
        self._defaults = self.remote.place_defaults(
            act, {d.get("id"): d for d in self.devices})

    def default_for(self, group: str, slot: str):
        """What the place sends if the owner leaves it: {device, command}, or None."""
        found = (self._defaults.get(group) or {}).get(slot)
        return dict(found) if found else None

    def slot_entry(self, group: str, slot: str):
        return next((entry for entry in self._groups.get(group) or []
                     if entry.get("slot") == slot), None)

    def set_slot(self, group: str, slot: str, entry):
        buttons = [b for b in self._groups.get(group) or [] if b.get("slot") != slot]
        if entry is not None:
            buttons.append(dict(entry, slot=slot))
        self._groups[group] = buttons
        self._refresh(group, slot)
        self._mark()

    def swap_slots(self, group: str, first: str, second: str):
        """Two places on a screen's side bars change what is on them."""
        a, b = self.slot_entry(group, first), self.slot_entry(group, second)
        buttons = [entry for entry in self._groups.get(group) or []
                   if entry.get("slot") not in (first, second)]
        buttons += [dict(entry, slot=slot) for entry, slot in ((a, second), (b, first))
                    if entry is not None]
        self._groups[group] = buttons
        self._refresh(group, first)
        self._refresh(group, second)
        self._mark()

    def _refresh(self, group=None, slot=None):
        for button in self._slots:
            if group is None or (button.group == group and button.slot == slot):
                button.refresh()

    def edit_slot(self, group: str, slot: str, shows=("label", "icon")):
        current = self.slot_entry(group, slot)
        if current is None or current.get("blank"):
            current = self.default_for(group, slot)
        icons = (self.model.get("side_bar_icons") if slot.startswith("SideBar")
                 else None)
        dialog = ScreenButtonDialog(self.devices, self, participating=self._participating,
                                    existing=current, shows=shows, icons=icons)
        if dialog.exec() and dialog.result_data:
            self.set_slot(group, slot, {k: v for k, v in dialog.result_data.items()
                                        if k not in ("slot", "blank")})

    def describe(self, entry: dict, brief: bool = False) -> str:
        """What a place sends: "TV: Play" - or, `brief`, only "Play" where the main
        device sends it, which is what every default is."""
        if entry.get("macro"):
            return f"{len(entry['macro'])} steps"
        if brief and entry.get("device") == self._control:
            return str(entry.get("command"))
        name = next((d.get("label", "?") for d in self.devices
                     if d.get("id") == entry.get("device")), entry.get("device"))
        return f"{name}: {entry.get('command')}"

    def set_participating(self, ids):
        self._participating = list(ids or [])
        if self._misc is not None:
            self._misc.set_participating(ids)
        if self.favourites is not None:
            self.favourites.set_participating(ids)

    def _favourites_note(self):
        """Favourites the remote will not show: they are kept, but this corner shows
        something else."""
        if self._favourites_warning is None or self.favourites is None:
            return
        count = len(self.favourites.get_buttons())
        hidden = count and not any(self._on[tab["group"]] for tab in self.model["tabs"]
                                   if tab.get("channels"))
        self._favourites_warning.setText(
            f"This activity has {count} favourite{'s' * (count != 1)}, which the remote "
            "shows only when this corner shows Favourites. They are kept." if hidden
            else "")
        self._favourites_warning.setVisible(bool(hidden))

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
            properties[tab["flag"]] = "True" if self._on[tab["group"]] else "False"
        if self.start.currentData():
            properties[self.model.get("start_property", "ActivityStartPage")] = \
                self.start.currentData()
        spec["properties"] = properties

    def get_buttons(self) -> list:
        """The page of buttons, for code that asks every screen page for its list."""
        return self._misc.get_buttons() if self._misc is not None else []
