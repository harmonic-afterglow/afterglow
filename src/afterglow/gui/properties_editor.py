"""An editor for device and activity properties.

Two rules, and they pull against each other.

**Nothing the configuration carries is ever hidden** - including a property Afterglow
does not recognise, which is shown raw rather than dropped.

**Nothing is offered that the thing being edited cannot use.** A television has no disc
count and no cassette slots, and listing them made a real television show four settings
that meant something and twelve that did not - all of them reading "unset", which looked
like twelve things left undone. Which properties a type actually uses is measured from
real configurations and recorded as `applies_to`; a donor's television carries exactly
the four that apply to it, so filtered by type there is usually nothing unset at all.

Where something genuinely is absent, the control shows the value the remote will behave
as rather than an empty box, and the label is greyed to say it is not in the file. It is
written back only if you change it, so opening this page does not add settings.

Three kinds of row, all editable and all written back:

* described - a typed control (checkbox, number, combo) and a plain-language explanation
* present but undescribed - the raw name and its value, marked as not understood
* addable - anything else, via "Add property", because the catalog is evidence of what
  real configurations use, not a limit on what they may use
"""
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
                             QVBoxLayout, QWidget, QWizardPage)

from .. import properties as props



def unset_text(scope, name, catalog):
    """What "unset" actually means for this property, in words.

    "Unset" on its own tells nobody anything: it says the box is empty, not what the
    remote will do. What can be said depends on which of two things reads the property.

    A handful are read by the remote's own behaviour layer, and for those absence has a
    known meaning taken from the firmware - which is authoritative even where the value
    people normally write is something else. `PowerOffUnusedDevices` is usually written
    True, but leaving it out behaves as false, and only the second fact helps you.
    `AlwaysOn` is worth spelling out in full: leaving it out does not mean "not always
    on", it means the device is skipped by power handling altogether.

    The rest are read by the touchscreen rather than the behaviour layer, and nothing
    says what it does with a missing one - so the honest thing to offer is the value
    real configurations carry, described as that.
    """
    entry = props.describe(scope, name, catalog)
    absent = entry.get("when_absent")
    if absent and absent != "unknown":
        # Either a plain value or a sentence explaining something less obvious.
        return f"unset - {absent}" if ":" in absent else f"unset - behaves as {absent}"
    default = entry.get("default")
    if default is None:
        return "unset"
    if str(entry.get("default_from", "")).startswith("inferred"):
        return "unset - never seen in a real config, so nobody knows"
    return f"unset - real configs use {default}"


class PropertiesEditor(QWidget):
    """Edit one device's or one activity's <Property> entries."""

    def __init__(self, scope: str, values: dict | None = None, parent=None,
                 kind: str | None = None, remote: str | None = None):
        super().__init__(parent)
        self.scope = scope
        self.kind = kind or None
        # Which properties exist at all is the remote's business, not a global list:
        # another model has settings this one has never heard of, and lacks some of
        # these. Naming none asks the model Afterglow builds for.
        self.catalog = props.catalog(remote)
        self._rows: dict[str, callable] = {}
        self._values = dict(values or {})

        outer = QVBoxLayout(self)
        blurb = QLabel(
            f"What this {scope} can carry. Anything already in the configuration is filled "
            "in; a setting that is not shows what the remote does without it, greyed, and "
            "is only written if you change it. Anything Afterglow does not recognise is "
            "kept exactly as it was.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color: gray;")
        outer.addWidget(blurb)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        self.form = QFormLayout(inner)
        area.setWidget(inner)
        outer.addWidget(area, stretch=1)

        row = QHBoxLayout()
        row.addStretch()
        add = QPushButton("Add property…")
        add.clicked.connect(self._add_custom)
        row.addWidget(add)
        outer.addLayout(row)

        self._build()

    def set_values(self, values: dict) -> None:
        """Replace what is filled in - used when a device template is chosen.

        A library entry knows what the device *is* (a display, how many discs, which
        tuner input). Without this the Advanced page stayed blank no matter which
        device was picked, which read as broken rather than empty.
        """
        self._values = dict(values or {})
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()
        self._build()

    # building rows
    def set_kind(self, kind: str | None) -> None:
        """The device or activity type, which decides what is worth offering."""
        kind = kind or None
        if kind != self.kind:
            self.kind = kind
            self.set_values(self._values)

    def _relevant(self):
        """Every property worth a row: the ones this type uses, plus whatever the
        configuration already carries - which is never hidden, even if the type is not
        one the property has been seen on. The measurement behind `applies_to` is six
        configurations, not the whole world."""
        # Suppressed rows still have to survive being here. `values()` is built from the
        # rows, so a property with no row would be dropped from the device entirely -
        # which for AlwaysOn would mean deleting the one property whose absence takes a
        # device out of the remote's power handling altogether.
        self._hidden = {}
        for name, value in self._values.items():
            entry = self.catalog[self.scope].get(name) or {}
            if entry.get("transient") or entry.get("edited_on"):
                self._hidden[name] = value

        shown = set(self._values) - set(self._hidden)
        for name in props.known(self.scope, self.catalog):
            entry = self.catalog[self.scope][name]
            # Some properties are not settings at all. IsNewDevice is written for you
            # and cleared by the remote itself, so offering it as a choice invites
            # somebody to set it and wonder why it does not stay set.
            if entry.get("transient"):
                continue
            # Others are settings, but they already have a control of their own. Always
            # on appeared here *and* on the Timing page, and this was the copy that did
            # nothing: the builder derives the property from the Timing checkbox, so
            # whatever was chosen here was silently overwritten on the way out.
            if entry.get("edited_on"):
                continue
            applies = entry.get("applies_to", "all")
            if applies == "all" or self.kind is None or self.kind in applies:
                shown.add(name)
        return shown

    def _build(self):
        for name in sorted(self._relevant()):
            self._add_row(name, self._values.get(name))

    def _add_row(self, name, value):
        entry = props.describe(self.scope, name, self.catalog)
        present = value is not None
        widget, getter = self._control(name, entry, value)
        self._rows[name] = getter

        label = QLabel(entry["label"] + ("" if entry["known"] else "  (not recognised)"))
        label.setToolTip(name)
        if not present:
            label.setStyleSheet("color: gray;")      # available, not currently set

        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(widget)
        if entry["description"]:
            hint = QLabel(entry["description"])
            hint.setWordWrap(True)
            hint.setStyleSheet("color: gray; font-size: 11px;")
            box.addWidget(hint)
        self.form.addRow(label, holder)

    def _must_be_written(self, entry):
        """Whether an absent property has to be written out even if left at its default.

        Almost never. The exception is a property the remote reads where absence is not
        the same as the default value - AlwaysOn, where a missing property means the
        device is skipped by power handling rather than "not always on". Showing false
        and then writing nothing would make the box a lie.
        """
        absent = entry.get("when_absent", "unknown")
        return absent not in ("unknown",) and ":" in absent

    def _control(self, name, entry, value):
        """A control matched to the property's type, showing what the remote will do.

        An absent property is not drawn as an empty box. It is drawn holding the value
        the remote behaves as, with its label greyed, and it returns None from its
        getter unless the user moves it - so looking does not write.
        """
        kind = entry["type"]
        default = entry.get("default")
        absent = value is None
        shown = default if absent else value
        force = absent and self._must_be_written(entry)

        if kind == "bool":
            box = QCheckBox()
            as_bool = False
            if shown is not None:
                as_bool = props.parse_value(self.scope, name, shown, self.catalog)
            box.setChecked(bool(as_bool))
            box.setText("" if not absent else "not in the configuration")
            was = as_bool

            def get(box=box, name=name, value=value, was=was, force=force):
                now = box.isChecked()
                if value is None and now == was and not force:
                    return None                  # untouched, and absence is harmless
                if value is not None and now == props.parse_value(
                        self.scope, name, value, self.catalog):
                    return value                 # untouched: keep the config's spelling
                return props.format_value(self.scope, name, now, self.catalog)
            return box, get

        if kind == "int":
            spin = QSpinBox()
            spin.setRange(0, 100000)
            start = int(shown) if str(shown).lstrip("-").isdigit() else 0
            spin.setValue(start)

            def get(spin=spin, value=value, start=start, force=force):
                now = spin.value()
                if value is None and now == start and not force:
                    return None
                return str(now)
            return spin, get

        options = props.suggestions(self.scope, name, self.catalog)
        if options:
            combo = QComboBox()
            combo.setEditable(True)          # observed values are a hint, not a limit
            for option in options:
                combo.addItem(option)
            if shown is not None and combo.findText(str(shown)) < 0:
                combo.addItem(str(shown))
            combo.setCurrentText("" if shown is None else str(shown))

            def get(combo=combo, value=value, shown=shown, force=force):
                text = combo.currentText().strip()
                if value is None and text == ("" if shown is None else str(shown)) \
                        and not force:
                    return None
                return text or None
            return combo, get

        edit = QLineEdit("" if shown is None else str(shown))

        def get(edit=edit, value=value, shown=shown, force=force):
            text = edit.text().strip()
            if value is None and text == ("" if shown is None else str(shown)) \
                    and not force:
                return None
            return text or None
        return edit, get

    def _add_custom(self):
        name, ok = QInputDialog.getText(self, "Add property", "Property name:")
        name = name.strip()
        if ok and name and name not in self._rows:
            self._add_row(name, "")

    # result
    def values(self) -> dict:
        """{name: text} for every property that is set. Unset rows are omitted rather
        than written as empty, so a build does not invent settings the user never made."""
        out = dict(getattr(self, "_hidden", {}))     # rows suppressed, values kept
        for name, getter in self._rows.items():
            text = getter()
            if text is not None:
                out[name] = text
        return out


class PropertiesPage(QWizardPage):
    """The same editor as a wizard step."""

    def __init__(self, scope: str, values: dict | None = None, parent=None,
                 kind: str | None = None, remote: str | None = None):
        super().__init__(parent)
        self.setTitle("Advanced")
        self.setSubTitle(
            f"What else this {scope} can specify. Optional: a setting not in the "
            "configuration shows what the remote does without it.")
        self.editor = PropertiesEditor(scope, values, self, kind=kind,
                                       remote=remote)
        layout = QVBoxLayout(self)
        layout.addWidget(self.editor)

    def values(self) -> dict:
        return self.editor.values()

    def set_values(self, values: dict) -> None:
        self.editor.set_values(values)

    def set_kind(self, kind: str | None) -> None:
        self.editor.set_kind(kind)
