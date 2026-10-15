"""Reusable widgets and the device-template loader."""

from pathlib import Path

from ..qt.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QDialog, QDialogButtonBox, QLineEdit
)
from ..qt.QtCore import QEvent, Qt, pyqtSignal

from .project import TemplateRepository
from .ui_helpers import bold_label, separator

from .constants import REPO_DIR


def load_repo_templates(database=None):
    """Every database device as a portable project template.

    New databases contain only ``afterglow-device/2`` records and portable protocol or
    waveform signals.  Old Harmony device files remain readable through that backend's
    migration hook, but their block ids and native bytes do not become project fields.
    """

    from .. import device_json

    external = database is not None
    root = Path(database).expanduser().resolve() if external else Path(REPO_DIR).parent
    devices = root / "devices"
    if not devices.is_dir() and not external:
        # A clean install starts with an empty private library. The old packaged
        # devices directory was personal data and is deliberately no longer shipped.
        return []
    if not devices.is_dir():
        raise ValueError(f"Afterglow database needs a devices/ directory: {root}")
    templates = []
    for spec in TemplateRepository(devices).load():
        try:
            template = device_json.to_project_device(spec, device_id="", library=root)
        except (ValueError, KeyError) as exc:
            print(f"[warn] {spec.get('model', '?')}: {exc}")
            continue
        # What the search page matches on, kept alongside the spec it will apply.
        template["_template_name"] = device_json.display_name(spec)
        template["remote_models"] = device_json.names(spec)
        template["_source_file"] = spec.get("_source_file")
        template["_database_root"] = str(root)
        templates.append(template)
    return templates
def build_repo_index(templates):
    """Build a two-level lookup: manufacturer -> list of templates.
    Also indexes by remote_models if present in the JSON.
    """
    return TemplateRepository.by_manufacturer(templates)
def sep():
    """A thin horizontal rule."""
    return separator()
def bold(text, size=None):
    return bold_label(text, size)
def _next_free_id(existing, prefix: str, start: int) -> str:
    """The first id above everything already in use.

    Counting from zero in a module-level variable looked fine until the application
    was restarted: the counter began again, the next thing created reused the first
    id, and two activities ended up sharing one. The remote keeps only one of them -
    so a config with three activities flashed as one, with nothing reporting a
    problem. Ids have to come from the project, not from how long the process has
    been running.
    """
    used = {str(value) for value in existing or ()}
    number = start
    while True:
        candidate = f"{prefix}{number:04d}"
        if candidate not in used:
            return candidate
        number += 1


def _new_id(existing=None):
    """A device id that is free in this project."""
    return _next_free_id(existing, "4000", 9001)
class _SuggestBox(QWidget):
    """A QLineEdit with an inline filtered list, opened by typing or by clicking.

    The list opens when the user does something - types, or clicks the box - and not
    when the choices behind it change. Loading a catalogue, switching source or
    pre-filling the box while editing an existing device all replace the choices, and
    a list that springs open because a background source finished loading is one the
    user has to dismiss before they can read what is under it.
    """
    item_chosen = pyqtSignal(str)

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.installEventFilter(self)
        layout.addWidget(self.edit)

        self.list = QListWidget()
        self.list.setVisible(False)
        self.list.setMaximumHeight(130)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.list)

        self.edit.textChanged.connect(self._on_text)
        self.list.itemClicked.connect(self._on_pick)

    def set_choices(self, choices):
        """Replace what the box can offer, without opening it."""
        self._choices = choices
        self._repopulate(self.edit.text(), open_it=self.list.isVisible())

    def eventFilter(self, watched, event):
        """Clicking the box opens its suggestions, the way a dropdown does."""
        if watched is self.edit and event.type() == QEvent.Type.MouseButtonPress:
            self._repopulate(self.edit.text(), open_it=True)
        return super().eventFilter(watched, event)

    def _on_text(self, text):
        self._repopulate(text, open_it=True)

    def _repopulate(self, text, *, open_it):
        choices = getattr(self, "_choices", [])
        q = text.strip().lower()
        self.list.clear()
        # A 21,000-model external manufacturer index is still cheap to hold as strings,
        # but manufacturing 21,000 hidden QListWidgetItems every time the box is cleared
        # is not. Suggestions exist only after the user has started a query.
        if not q:
            self.list.setVisible(False)
            return
        matches = [c for c in choices if q in c.lower()]
        for m in matches:
            self.list.addItem(m)
        self.list.setVisible(open_it and bool(matches))

    def _on_pick(self, item):
        self.edit.blockSignals(True)
        self.edit.setText(item.text())
        self.edit.blockSignals(False)
        self.list.setVisible(False)
        self.item_chosen.emit(item.text())

    def text(self):        return self.edit.text()
    def setText(self, v):  self.edit.setText(v); self.list.setVisible(False)
class RemotePickerDialog(QDialog):
    """Pick the key a command goes on, on the remote as it is drawn (keys_view): the
    command's own key marked, the keys other commands hold tinted and named on hover.
    A remote not drawn yet shows its keys as a grid, by the same widget.

    `used_slots` is {key: the command on it} - or, from older callers, just the keys.
    """

    def __init__(self, current_slot, used_slots, parent=None, remote=None, command=None):
        super().__init__(parent)
        from .. import vocabulary
        from .keys_view import ASSIGNED, CHANGED, FREE, RemoteKeys, legend

        self.setWindowTitle(f"Key for {command}" if command else "Choose a key")
        self.setModal(True)
        self.chosen = current_slot   # default = keep current
        used = (dict(used_slots) if isinstance(used_slots, dict)
                else {slot: None for slot in used_slots or ()})

        outer = QVBoxLayout(self)
        intro = QLabel("Click the key to put it on. A key another command is on moves "
                       "to this one.")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        self.keys = RemoteKeys(vocabulary.for_remote(remote))
        label = self.keys.label
        states = {}
        for key in self.keys.keys():
            if key == current_slot:
                states[key] = (ASSIGNED, f"{label(key)}: {command or 'this command'}")
            elif key in used:
                states[key] = (CHANGED, f"{label(key)}: " + (used[key] or "another command"))
            else:
                states[key] = (FREE, f"{label(key)}: free")
        self.keys.set_states(states)
        self.keys.select(current_slot)
        self.keys.key_clicked.connect(self._pick)
        self.keys.setMinimumSize(self.keys.sizeHint() * 1.2)
        outer.addWidget(self.keys, 1)
        outer.addSpacing(6)
        outer.addWidget(legend([(ASSIGNED, "This command"), (CHANGED, "Another command"),
                                (FREE, "Free")]))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        clear = buttons.addButton("No key", QDialogButtonBox.ButtonRole.ResetRole)
        clear.clicked.connect(lambda: self._pick(None))
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        # Wide enough for the legend under a tall remote; a wide remote sets its own.
        hint = self.sizeHint()
        self.resize(max(440, hint.width()), hint.height())

    def _pick(self, slot):
        self.chosen = slot
        self.accept()


def _new_act_id(existing=None):
    """An activity id that is free in this project."""
    return _next_free_id(existing, "1000", 1)
