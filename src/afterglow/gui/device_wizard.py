"""Add and edit a device: search, import, learn commands."""

import copy
from collections import Counter
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox,
    QCheckBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QAbstractItemView, QHeaderView, QWizard, QWizardPage
)
from PyQt6.QtCore import Qt, pyqtSignal

from .ui_helpers import FilterCombo

from .constants import DEVICE_TYPES, DEVICE_TYPE_LABELS
from .rf_routing import rf_get, rf_options, rf_receivers
from .icons import populate as populate_types
from .properties_editor import PropertiesEditor, PropertiesPage
from .widgets import RemotePickerDialog, _SuggestBox, _new_id, bold, build_repo_index, sep


class DeviceWizard(QWizard):
    """Add a new device - 4 steps:
       1. Search  (typeahead lookup in repo)
       2. Identity (label, type, codec, etc.)
       3. Commands (IR command table)
       4. Timing   (delays, always-on flag)
    """

    def __init__(self, templates, parent=None, existing=None, project=None,
                 taken_ids=None, source_preferences=None):
        super().__init__(parent)
        existing = _portable_if_possible(existing)
        self.project = project
        self._taken_ids = list(
            taken_ids if taken_ids is not None
            else [d.get("id") for d in (project or {}).get("devices", [])])
        self.setWindowTitle("Add Device" if not existing else "Edit Device")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(660, 500)
        self.result_spec  = None
        self._existing    = existing or {}
        self._loaded_tpl  = None          # shared across pages
        self._inputs      = list((existing or {}).get("inputs") or [])

        self.page_search = SearchPage(
            templates, self._existing, source_preferences=source_preferences)
        self.page_identity = IdentityPage(self._existing, project=project)
        self.page_cmds     = CommandsPage(self._existing)
        self.page_timing   = TimingPage(self._existing)
        self.page_props    = PropertiesPage("device", self._existing.get("properties"),
                                    kind=self._existing.get("type"))

        self.addPage(self.page_search)
        self.addPage(self.page_identity)
        self.addPage(self.page_cmds)
        self.addPage(self.page_timing)
        self.addPage(self.page_props)

        # When a model is chosen on the search page, pre-fill the later pages
        self.page_search.template_selected.connect(self._on_template_selected)
        self.page_cmds.learned.connect(self._on_learned)

    def _on_learned(self):
        """Refresh the summary after a portable waveform was learned."""
        self.page_identity.refresh_protocol()

    def _on_template_selected(self, t):
        t = _portable_if_possible(t)
        self._loaded_tpl = t
        self._inputs = list(t.get("inputs") or [])
        # The type decides which properties are worth offering, so it has to reach the
        # Advanced page before the values do.
        self.page_props.set_kind(t.get("type"))
        if t.get("properties"):
            self.page_props.set_values(t["properties"])
        self.page_identity.apply_template(t)
        self.page_cmds.load_template(t)
        self.page_timing.load_template(t)

    def rf_token(self):
        """The IR output the user chose, applied by the caller once the id is known."""
        return self.page_identity.rf_combo.currentData()

    def accept(self):
        self.result_spec = self._collect()
        super().accept()

    def _collect(self):
        ident = self.page_identity
        cmds  = self.page_cmds
        tim   = self.page_timing
        template = self._loaded_tpl or {}
        # Everything the chosen library entry says, including the parts no widget here
        # shows: raw codes, numeric entry, states, per-command icons. See _carry.
        spec = _carry(template)
        command_rows = cmds.get_commands()
        spec.update({
            "schema":            "afterglow-project-device/1",
            "id":                ident.id_edit.text().strip() or _new_id(self._taken_ids),
            "label":             ident.label_edit.text().strip() or "Unnamed Device",
            "type":              ident.type_combo.currentData() or ident.type_combo.currentText(),
            "mfr":               ident.mfr_edit.text().strip(),
            "model":             ident.model_edit.text().strip(),
            **cmds.power_fields(),
            "properties":        self.page_props.values(),
            "always_on":         tim.always_on.isChecked(),
            "power_delay":       tim.pwr_delay.value(),
            "press_presilence":  tim.pre_sil.value(),
            "press_interkey":    tim.inter_key.value(),
            "hold_presilence":   tim.hold_sil.value(),
            "hold_interkey":     tim.hold_key.value(),
            "commands":          command_rows,
            # Tracks the template chosen on the search page, which is not necessarily
            # the one the spec was carried from if the user changed their mind.
            "inputs":            list(self._inputs or []),
        })
        spec["signals"] = cmds.updated_signals(command_rows)
        _attach_learned(spec, self._existing, cmds.learned_captures())
        from .. import project_devices
        project_devices.validate(spec)
        return spec
class SearchPage(QWizardPage):
    """Step 1 - search the device database by typing manufacturer then model."""
    template_selected = pyqtSignal(dict)

    def __init__(self, templates, existing, parent=None, archive_path=None,
                 source_preferences=None):
        super().__init__(parent)
        self.setTitle("Find Device")
        self.setSubTitle(
            "Type a manufacturer name to search the database, then select a model. "
            "You can skip this step and fill in details manually on the next page."
        )
        self._local_repo_index = build_repo_index(templates)
        self._repo_index = self._local_repo_index
        self._external_repo_indexes = {}
        self._online_catalogs = {}
        self._all_archive_models = {}
        self._matched_online_cats = []
        self._source_errors = {}
        self._matched_mfr = None
        # Next is gated on this. "Not listed" is the one source that needs no selection,
        # because it exists precisely for devices the database does not have.
        self._chosen = False
        self._archive = None
        self._archive_models = {}
        self._archive_path = archive_path
        if source_preferences is None:
            from .source_settings import SourcePreferences
            source_preferences = SourcePreferences()
        self._sources = source_preferences

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Search-by selector
        row = QHBoxLayout()
        row.addWidget(QLabel("Search by:"))
        self.search_type = QComboBox()
        # "All" first, and selected by default: someone adding a device knows the make
        # and model, not which catalogue happens to hold it. The individual sources stay
        # for narrowing a search that returns too much.
        self.search_type.addItem("All sources", "all")
        if self._sources.local_devices:
            self.search_type.addItem("Local devices · Device Model", "device")
        if self._sources.logitech_online:
            self.search_type.addItem(
                "Logitech Harmony database · Online", "logitech_online")
        if self._sources.flipper_irdb_online:
            self.search_type.addItem("Flipper-IRDB · Online", "flipper_irdb_online")
        if self._sources.irdb_online:
            self.search_type.addItem("IRDB · Online", "irdb_online")
        for number, repository in enumerate(self._sources.external_repositories):
            if repository.enabled:
                self.search_type.addItem(
                    f"Afterglow database · {repository.name}",
                    f"afterglow_external:{number}")
        # Kept only for callers of the old direct SearchPage API; the application no
        # longer offers Logitech checkouts as a configured source.
        if archive_path is not None:
            self.search_type.addItem(
                "Logitech Harmony archive · Legacy local", "archive")
        # The third answer to "how do I find this device?" is that you cannot - it is
        # not in the library. Learning belongs here, next to the other two ways of
        # identifying a device, rather than as a separate button somewhere else.
        self.search_type.addItem("Not listed - learn from its own remote", "learn")
        self.search_type.setFixedWidth(390)
        self.search_type.currentIndexChanged.connect(self._on_search_type_changed)
        row.addWidget(self.search_type)
        row.addStretch()
        layout.addLayout(row)

        # Clickable enabled sources chips layout (shown when in "All sources" mode)
        self._sources_chips_widget = QWidget()
        chips_layout = QHBoxLayout(self._sources_chips_widget)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(6)
        chips_layout.addWidget(
            QLabel("Active sources (ordered by dominance - duplicates overridden):")
        )
        for i in range(1, self.search_type.count()):
            data = self.search_type.itemData(i)
            text = self.search_type.itemText(i)
            if data != "learn":
                btn = QPushButton(text)
                btn.setFlat(True)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    "color: #1a73e8; font-weight: bold; border: none; padding: 0 4px;"
                )
                btn.clicked.connect(lambda _, index=i: self.search_type.setCurrentIndex(index))
                chips_layout.addWidget(btn)
        chips_layout.addStretch()
        layout.addWidget(self._sources_chips_widget)

        # The external source is optional and user-selected. It remains outside the
        # project and package; only the chosen device's portable signals enter a project.
        self._archive_section = QWidget()
        archive_layout = QVBoxLayout(self._archive_section)
        archive_layout.setContentsMargins(0, 0, 0, 0)
        archive_layout.setSpacing(4)
        self._archive_heading = bold("Archive source")
        archive_layout.addWidget(self._archive_heading)
        archive_row = QHBoxLayout()
        self._archive_edit = QLineEdit()
        self._archive_edit.setPlaceholderText("Folder containing manifest.json and index.json")
        self._archive_edit.editingFinished.connect(self._open_archive)
        self._archive_browse = QPushButton("Browse…")
        self._archive_browse.clicked.connect(self._browse_archive)
        archive_row.addWidget(self._archive_edit, stretch=1)
        archive_row.addWidget(self._archive_browse)
        archive_layout.addLayout(archive_row)
        self._archive_note = QLabel()
        self._archive_note.setWordWrap(True)
        archive_layout.addWidget(self._archive_note)
        self._archive_section.setVisible(False)
        layout.addWidget(self._archive_section)

        if self._archive_path:
            self._archive_edit.setText(str(self._archive_path))

        # Manufacturer
        self._mfr_label = bold("Manufacturer")
        layout.addWidget(self._mfr_label)
        self._mfr_box = _SuggestBox("e.g. Samsung, Yamaha, Eurolan…")
        self._mfr_box.set_choices(sorted(self._repo_index.keys()))
        self._mfr_box.item_chosen.connect(self._on_mfr_chosen)
        self._mfr_box.edit.textChanged.connect(self._on_mfr_typed)
        layout.addWidget(self._mfr_box)

        # Model (hidden until a manufacturer is matched)
        self._model_section = QWidget()
        ml = QVBoxLayout(self._model_section)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(4)
        ml.addWidget(bold("Model"))
        self._model_box = _SuggestBox("e.g. QE55S90D, HTR-5630…")
        self._model_box.item_chosen.connect(self._on_model_chosen)
        self._model_box.edit.textChanged.connect(self._on_model_typed)
        ml.addWidget(self._model_box)
        self._model_section.setVisible(False)
        self._model_section_wanted = False
        layout.addWidget(self._model_section)

        # Confirmation label
        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet("color: green;")
        self._status_lbl.setVisible(False)
        layout.addWidget(self._status_lbl)

        self._capabilities = QTableWidget(0, 3)
        self._capabilities.setHorizontalHeaderLabels(
            ["Command", "Source conversion", "Harmony 900"])
        self._capabilities.horizontalHeader().setStretchLastSection(True)
        self._capabilities.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._capabilities.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._capabilities.setMaximumHeight(180)
        self._capabilities.setVisible(False)
        layout.addWidget(self._capabilities)

        # Shown instead of the search boxes when the device is not in the library.
        self._learn_note = QLabel(
            "This device will be built from codes captured off its own remote.\n\n"
            "Click Next, name it on the Details page, then use "
            "\u2018Learn from remote\u2026\u2019 on the Commands page: point the "
            "original remote at the front of the Harmony and press each key you want."
            "\n\nThe remote must be plugged in and connected.")
        self._learn_note.setWordWrap(True)
        self._learn_note.setVisible(False)
        layout.addWidget(self._learn_note)

        layout.addStretch()

        # Pre-fill when editing an existing device
        if existing.get("mfr"):
            self._mfr_box.setText(existing["mfr"])
            self._refresh_model_choices(existing["mfr"])
        if existing.get("model"):
            self._model_box.setText(existing["model"])
        self._on_search_type_changed()

    def _set_chosen(self, chosen):
        """Record whether a device is selected, and let the wizard re-check Next."""
        self._chosen = chosen
        self.completeChanged.emit()

    def isComplete(self):
        """Next is only offered once there is something to carry to the next page.

        Every source but "Not listed" produces a device by selection, and going on
        without one lands on a details page with nothing filled in - not an error the
        wizard can report, just an empty form the user has to work out. "Not listed" is
        exempt: it exists for devices no source has.
        """
        if self.search_type.currentData() == "learn":
            return True
        return self._chosen

    def _archive_mode(self):
        return self.search_type.currentData() in {
            "archive", "logitech_online", "flipper_irdb_online", "irdb_online"}

    def _external_mode(self):
        return str(self.search_type.currentData()).startswith("afterglow_external:")

    def _on_search_type_changed(self):
        mode = self.search_type.currentData()
        learning = mode == "learn"
        archive = self._archive_mode()
        self._sources_chips_widget.setVisible(mode == "all")
        self._archive_section.setVisible(archive)
        self._mfr_label.setVisible(not learning)
        self._mfr_box.setVisible(not learning)
        self._model_section.setVisible(not learning and self._model_section_wanted)
        self._learn_note.setVisible(learning)
        self._status_lbl.setVisible(False)
        self._capabilities.setVisible(False)
        self._set_chosen(False)
        if archive:
            self._archive = None
            if mode != "archive":
                labels = {
                    "logitech_online": "Logitech Harmony database",
                    "flipper_irdb_online": "Flipper-IRDB",
                    "irdb_online": "IRDB",
                }
                self._archive_heading.setText("Live online database")
                self._archive_edit.setText(labels[mode])
                self._archive_edit.setReadOnly(True)
                self._archive_browse.setVisible(False)
            else:
                self._archive_heading.setText("Legacy local archive folder")
                self._archive_edit.setText(str(self._archive_path or ""))
                self._archive_edit.setReadOnly(False)
                self._archive_browse.setVisible(True)
            self._open_archive()
        elif self._external_mode():
            self._archive = None
            if mode not in self._external_repo_indexes:
                from ..afterglow_sources import sync_repository
                from .widgets import load_repo_templates
                number = int(mode.partition(":")[2])
                repository = self._sources.external_repositories[number]
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    root = sync_repository(repository)
                    templates = load_repo_templates(root)
                    self._external_repo_indexes[mode] = build_repo_index(templates)
                except (OSError, ValueError) as exc:
                    self._external_repo_indexes[mode] = {}
                    self._source_errors[mode] = str(exc)
                finally:
                    QApplication.restoreOverrideCursor()
            self._repo_index = self._external_repo_indexes.get(mode, {})
            self._mfr_box.set_choices(sorted(self._repo_index))
            self._model_section_wanted = False
            self._model_section.setVisible(False)
            if mode in self._source_errors:
                self._status_lbl.setText(self._source_errors[mode])
                self._status_lbl.setStyleSheet("color: #b00020;")
                self._status_lbl.setVisible(True)
            else:
                self._refresh_model_choices(self._mfr_box.text())
        elif mode == "all":
            self._archive = None
            self._repo_index = self._merged_repo_index()
            self._mfr_box.set_choices(sorted(self._repo_index.keys()))
            self._refresh_model_choices(self._mfr_box.text())
        elif not learning:
            self._archive = None
            self._repo_index = self._local_repo_index
            self._mfr_box.set_choices(sorted(self._repo_index.keys()))
            self._refresh_model_choices(self._mfr_box.text())

    def _open_online_catalogs(self):
        """Ensure enabled online catalogues are lazily initialized for 'All sources'."""
        from ..corpus_provider import online_logitech_catalog
        from ..public_ir_sources import FlipperIrdbCatalog, IrdbCatalog

        openers = {
            "logitech_online": lambda: online_logitech_catalog(
                follow_latest=self._sources.logitech_follow_latest),
            "flipper_irdb_online": FlipperIrdbCatalog,
            "irdb_online": IrdbCatalog,
        }
        for mode_key, opener in openers.items():
            if getattr(self._sources, mode_key, False) and mode_key not in self._online_catalogs:
                try:
                    self._online_catalogs[mode_key] = opener()
                except (OSError, ValueError) as exc:
                    self._source_errors[mode_key] = str(exc)

    def _merged_repo_index(self) -> dict:
        """Every catalogue at once, with local library taking precedence."""
        merged: dict = {}
        for manufacturer, templates in self._local_repo_index.items():
            merged[manufacturer] = list(templates)
        for index in self._external_repo_indexes.values():
            for manufacturer, templates in index.items():
                have = merged.setdefault(manufacturer, [])
                known = {str(t.get("model", "")).casefold() for t in have}
                have.extend(t for t in templates
                            if str(t.get("model", "")).casefold() not in known)

        self._open_online_catalogs()
        for mode_key, cat in self._online_catalogs.items():
            try:
                for entry in cat.manufacturers(limit=100_000):
                    merged.setdefault(entry.name, [])
            except (OSError, ValueError):
                pass
        return merged

    def _on_mfr_typed(self, text):
        self._refresh_model_choices(text)

    def _on_mfr_chosen(self, mfr):
        self._refresh_model_choices(mfr)

    def _on_model_typed(self, text):
        mode = self.search_type.currentData()
        if mode == "all" and self._matched_online_cats:
            offline_choices = [t.get("model", "?") for t in self._repo_index.get(self._matched_mfr, [])] if self._matched_mfr in self._repo_index else []
            if not self._matched_mfr or len(text.strip()) < 2:
                self._all_archive_models = {}
                self._model_box.set_choices(offline_choices)
                return

            names = {}
            all_choices = list(offline_choices)
            # More dominant sources (local library, external repos) take precedence.
            # Duplicates from less dominant (online) sources are omitted.
            seen_models = {c.casefold() for c in offline_choices}

            for matched_mfr, cat in self._matched_online_cats:
                try:
                    models = cat.models(matched_mfr, text, limit=300)
                except (LookupError, OSError, ValueError):
                    continue
                unique_models = [m for m in models if m.name.casefold() not in seen_models]
                repeated = Counter(m.name for m in unique_models)
                for model in unique_models:
                    display = model.name
                    if repeated[model.name] > 1:
                        display = f"{model.name}  · catalogue {model.global_device_id}"
                    while display in names or display in all_choices:
                        display = f"{display} ·"
                    names[display] = (model, cat)
                    all_choices.append(display)
                    seen_models.add(model.name.casefold())

            self._all_archive_models = names
            self._model_box.set_choices(all_choices)
            return

        if not self._archive_mode() or not self._archive:
            return
        if not self._matched_mfr or len(text.strip()) < 2:
            self._archive_models = {}
            self._model_box.set_choices([])
            return
        try:
            models = self._archive.models(self._matched_mfr, text, limit=300)
        except (LookupError, OSError, ValueError) as exc:
            self._archive_note.setText(str(exc))
            self._archive_note.setStyleSheet("color: #b00020;")
            return
        repeated = Counter(model.name for model in models)
        names = {}
        for model in models:
            display = model.name
            if repeated[model.name] > 1:
                display = f"{model.name}  · catalogue {model.global_device_id}"
            while display in names:
                display = f"{display} ·"
            names[display] = model
        self._archive_models = names
        self._model_box.set_choices(list(names))

    def _refresh_model_choices(self, mfr):
        mode = self.search_type.currentData()
        if mode == "all":
            matched = next(
                (k for k in self._repo_index if k.lower() == mfr.strip().lower()), None)
            self._matched_online_cats = []
            for mode_key, cat in self._online_catalogs.items():
                try:
                    m_obj = cat.manufacturer(mfr)
                    self._matched_online_cats.append((m_obj.name, cat))
                except (LookupError, OSError, ValueError):
                    pass

            if not matched and not self._matched_online_cats:
                self._model_section_wanted = False
                self._model_section.setVisible(False)
                return

            if matched != self._matched_mfr:
                self._model_box.setText("")
            self._matched_mfr = matched or (self._matched_online_cats[0][0] if self._matched_online_cats else "")

            offline_choices = [t.get("model", "?") for t in self._repo_index.get(matched, [])] if matched else []
            self._all_archive_models = {}
            self._model_box.set_choices(offline_choices)
            self._model_section_wanted = True
            self._model_section.setVisible(True)
            return

        if self._archive_mode():
            if not self._archive:
                self._model_section_wanted = False
                self._model_section.setVisible(False)
                return
            try:
                matched = self._archive.manufacturer(mfr).name
            except LookupError:
                self._model_section_wanted = False
                self._model_section.setVisible(False)
                return
            self._matched_mfr = matched
            self._archive_models = {}
            self._model_box.set_choices([])
            self._model_box.setText("")
            self._model_section_wanted = True
            self._model_section.setVisible(True)
            return
        matched = next(
            (k for k in self._repo_index if k.lower() == mfr.strip().lower()), None)
        if not matched:
            self._model_section_wanted = False
            self._model_section.setVisible(False)
            return
        if matched != self._matched_mfr:
            self._model_box.setText("")
        self._matched_mfr = matched
        tmpls = self._repo_index[matched]
        choices = [t.get("model", "?") for t in tmpls]
        self._model_box.set_choices(choices)
        self._model_section_wanted = True
        self._model_section.setVisible(True)

    def _on_model_chosen(self, model_str):
        if not self._matched_mfr:
            return
        if self.search_type.currentData() == "all":
            if model_str in self._all_archive_models:
                model, cat = self._all_archive_models[model_str]
                self._select_archive_model(model, catalog=cat)
                return
            for t in self._repo_index.get(self._matched_mfr, []):
                if t.get("model", "").lower() == model_str.lower():
                    self._fire(t); return
                if model_str in t.get("remote_models", []):
                    self._fire(t); return
            return

        if self._archive_mode():
            model = self._archive_models.get(model_str)
            if model is not None:
                self._select_archive_model(model)
            return
        for t in self._repo_index.get(self._matched_mfr, []):
            if t.get("model", "").lower() == model_str.lower():
                self._fire(t); return
            if model_str in t.get("remote_models", []):
                self._fire(t); return

    def _browse_archive(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Logitech Harmony IR archive", self._archive_edit.text())
        if chosen:
            self._archive_path = Path(chosen)
            self._archive_edit.setText(chosen)
            self._open_archive()

    def _open_archive(self):
        if not self._archive_mode():
            return
        mode = self.search_type.currentData()
        selected = str(self._archive_path or "")
        if mode == "archive" and not selected:
            self._archive = None
            self._archive_note.setText("Choose the legacy archive folder first.")
            self._archive_note.setStyleSheet("color: #b00020;")
            return
        try:
            from ..corpus_provider import LogitechCatalog, online_logitech_catalog
            from ..public_ir_sources import FlipperIrdbCatalog, IrdbCatalog

            openers = {
                "logitech_online": lambda: online_logitech_catalog(
                    follow_latest=self._sources.logitech_follow_latest),
                "flipper_irdb_online": FlipperIrdbCatalog,
                "irdb_online": IrdbCatalog,
            }
            self._archive = (LogitechCatalog(selected) if mode == "archive"
                             else openers[mode]())
            manufacturers = self._archive.manufacturers(limit=100_000)
        except (OSError, ValueError) as exc:
            self._archive = None
            self._archive_note.setText(f"Could not open archive: {exc}")
            self._archive_note.setStyleSheet("color: #b00020;")
            self._mfr_box.set_choices([])
            return
        self._archive_note.setText(
            f"Ready: {len(manufacturers):,} manufacturers.")
        self._archive_note.setStyleSheet("color: green;")
        self._mfr_box.set_choices([entry.name for entry in manufacturers])
        self._matched_mfr = None
        self._model_section_wanted = False
        self._model_section.setVisible(False)

    def _select_archive_model(self, model, catalog=None):
        cat = catalog or self._archive
        if not cat:
            return
        try:
            result = cat.materialize(model)
            from .. import device_json
            template = device_json.to_project_device(result["template"], device_id="")
        except (OSError, ValueError) as exc:
            self._status_lbl.setText(f"Cannot use this device: {exc}")
            self._status_lbl.setStyleSheet("color: #b00020;")
            self._status_lbl.setVisible(True)
            self._capabilities.setVisible(False)
            return
        template["_template_name"] = model.name
        self._show_capabilities(result)
        counts = result["counts"]
        self._status_lbl.setText(
            f"SUCCESS: {model.manufacturer} {model.name}: {counts['supported']} of "
            f"{counts['source']} commands are faithful on Harmony 900 - click Next")
        self._status_lbl.setStyleSheet("color: green;")
        self._status_lbl.setVisible(True)
        self._set_chosen(True)
        self.template_selected.emit(template)

    def _show_capabilities(self, result):
        rows = result["commands"]
        self._capabilities.setRowCount(len(rows))
        for row, command in enumerate(rows):
            values = (
                command["name"],
                command["classification"],
                command["reason"],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 2 and not command["supported"]:
                    item.setToolTip("Excluded from the materialized device")
                self._capabilities.setItem(row, column, item)
        self._capabilities.resizeColumnsToContents()
        self._capabilities.horizontalHeader().setStretchLastSection(True)
        self._capabilities.setVisible(True)

    def _fire(self, t):
        name = t.get("_template_name") or t.get("label", "?")
        ncmds = len(t.get("commands", []))
        self._status_lbl.setText(f"SUCCESS: {name} ({ncmds} commands) - click Next to continue")
        self._status_lbl.setStyleSheet("color: green;")
        self._status_lbl.setVisible(True)
        self._capabilities.setVisible(False)
        self._set_chosen(True)
        self.template_selected.emit(t)
class IdentityPage(QWizardPage):
    """Step 2 - label, device type, manufacturer, model, codec and power command.
    Pre-filled by SearchPage when a template is selected; all fields stay editable.
    """

    def __init__(self, existing, parent=None, project=None):
        super().__init__(parent)
        self.project = project
        self.setTitle("Device Details")
        self.setSubTitle(
            "Review and adjust the device details. "
            "These were pre-filled from the database if you selected a model."
        )
        form = QFormLayout(self)

        self.label_edit = QLineEdit(existing.get("label", ""))
        form.addRow("Display label:", self.label_edit)

        self.type_combo = QComboBox()
        # Editable, and the device's own type is always present: a type never
        # seen must survive being edited rather than being replaced by the first entry.
        self.type_combo.setEditable(True)
        existing_type = (existing.get("type") or "").strip()
        types = list(DEVICE_TYPES)
        if existing_type and existing_type not in types:
            types.insert(0, existing_type)
        self._type_index = {name: i for i, name in enumerate(types)}
        populate_types(self.type_combo, types, labels=DEVICE_TYPE_LABELS)
        if existing.get("type") in DEVICE_TYPES:
            index = self.type_combo.findData(existing["type"])
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
        form.addRow("Device type:", self.type_combo)

        self.mfr_edit   = QLineEdit(existing.get("mfr", ""))
        self.model_edit = QLineEdit(existing.get("model", ""))
        form.addRow("Manufacturer:", self.mfr_edit)
        form.addRow("Model:",        self.model_edit)

        self.id_edit = QLineEdit(existing.get("id", ""))
        self.id_edit.setReadOnly(True)
        self.id_edit.setPlaceholderText("assigned automatically")
        self.id_edit.setStyleSheet("color: gray;")
        self._existing_id = existing.get("id")
        # Internal identity: activities and devices reference each other by id, and
        # editing one silently breaks every reference to it. Shown, never editable.
        form.addRow("Device ID:", self.id_edit)

        # Where this device's commands are transmitted from: the remote's own front IR
        # LED, or a wireless RF blaster base. Set here rather than on the device list,
        # because it is a property of the device, not a shortcut.
        # Which output THIS device uses. Pairing a blaster is a remote-level thing and
        # lives on the Remote Settings tab, so this page is never a prerequisite for it.
        self.rf_combo = QComboBox()
        self._refresh_rf_options()
        form.addRow("IR output:", self.rf_combo)

        form.addRow(sep())

        # Protocols belong to individual portable signals.  There is deliberately no
        # remote-specific codec or block picker here: the selected backend decides how to
        # reproduce each signal when the project is built.
        self._existing = existing
        self.proto_label = QLabel(self._protocol_text())
        self.proto_label.setWordWrap(True)
        self.proto_label.setStyleSheet("color: gray;")
        form.addRow("IR protocol:", self.proto_label)

        # (Power command is now chosen on the Commands page)

    def _protocol_text(self):
        """Summarise the portable signals without exposing a backend's encoding."""
        signals = (self._existing or {}).get("signals") or {}
        protocols = sorted({signal.get("protocol") for signal in signals.values()
                            if signal.get("kind") == "protocol"})
        waveforms = sum(signal.get("kind") == "waveform" for signal in signals.values())
        opaque = sum(signal.get("kind") == "backend-opaque" for signal in signals.values())
        parts = protocols
        if waveforms:
            parts.append(f"{waveforms} recorded waveform(s)")
        if opaque:
            parts.append(f"{opaque} undecoded imported command(s)")
        return ", ".join(parts) if parts else "Choose a device or learn a command."

    def _has_recorded_codes(self) -> bool:
        signals = (self._existing or {}).get("signals") or {}
        return bool(signals) and all(signal.get("kind") == "waveform"
                                     for signal in signals.values())

    def refresh_protocol(self):
        """Called after learning, so the label stops saying there is nothing yet."""
        self.proto_label.setText(self._protocol_text())

    def _refresh_rf_options(self):
        wanted = self.rf_combo.currentData() if self.rf_combo.count() else \
            rf_get(self.project or {}, self._existing_id)
        self.rf_combo.clear()
        for display, token in rf_options(self.project or {}):
            self.rf_combo.addItem(display, token)
        index = self.rf_combo.findData(wanted)
        self.rf_combo.setCurrentIndex(index if index >= 0 else 0)
        if not rf_receivers(self.project or {}):
            self.rf_combo.setToolTip(
                "No blaster is paired. Pair one on the Remote Settings tab, or import "
                "a configuration that already has one.")

    def apply_template(self, t):
        """Called by DeviceWizard when SearchPage fires template_selected."""
        if t.get("label"):  self.label_edit.setText(t["label"])
        if t.get("type") and t["type"] in DEVICE_TYPES:
            index = self.type_combo.findData(t["type"])
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
        if t.get("mfr"):   self.mfr_edit.setText(t["mfr"])
        if t.get("model"): self.model_edit.setText(t["model"])
        self._existing = t
        self.proto_label.setText(self._protocol_text())
class CommandsPage(QWizardPage):
    learned = pyqtSignal()

    def __init__(self, existing, parent=None):
        super().__init__(parent)
        # Which commands already carry a captured code. For those the address and
        # command columns are not merely unused - `builder.devices.code_for` returns
        # the stored code and never looks at them - so showing them as editable 00s
        # invited people to type values that could not possibly do anything.
        self._signals = dict((existing or {}).get("signals") or {})
        self.setTitle("IR Commands")
        self.setSubTitle(
            "Add or import commands. Click a button in the 'Hard Key' column "
            "to map it to a physical remote button."
        )
        layout = QVBoxLayout(self)

        # - Power commands ----------------------------------------------
        # Three fields, because devices genuinely differ. A discrete pair (separate On
        # and Off codes) is what lets an activity turn a television on without turning
        # an already-on one off; a toggle is one code that flips it. Some devices have
        # only one of a pair - a stereo with a dedicated standby key. Collapsing all of
        # this to a single "power command" silently threw the other half away.
        pwr_row = QHBoxLayout()
        # Filterable: these list every command the device has, which for a television
        # is sixty-five entries and a popup taller than the screen.
        self.pwr_on_combo = FilterCombo()
        self.pwr_off_combo = FilterCombo()
        self.pwr_combo = FilterCombo()               # the toggle
        for label, combo in (("Power on:", self.pwr_on_combo),
                             ("Power off:", self.pwr_off_combo),
                             ("Power toggle:", self.pwr_combo)):
            combo.addItem("(none)", None)
            combo.setMinimumWidth(150)
            pwr_row.addWidget(QLabel(label))
            pwr_row.addWidget(combo)
        pwr_row.addStretch()
        layout.addLayout(pwr_row)

        # - Toolbar ------------------------------------------------------
        btn_row = QHBoxLayout()
        self.add_btn    = QPushButton("Add Command")
        self.remove_btn = QPushButton("Remove")
        self.learn_btn  = QPushButton("Learn from remote…")
        self.learn_btn.setToolTip(
            "Point the original remote at the Harmony and press a key. Needs "
            "libconcord and a connected remote.")
        for b in (self.add_btn, self.remove_btn, self.learn_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # - Command table (col 4 = clickable hard-key button) --------------
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Label", "Address (hex)", "Command (hex)", "Hard Key"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Only cols 0-3 are text-editable; col 4 is opened via cell click
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                   QAbstractItemView.EditTrigger.SelectedClicked)
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table)

        # Duplicate warning label
        self._dup_lbl = QLabel()
        self._dup_lbl.setStyleSheet("color: orange;")
        self._dup_lbl.setVisible(False)
        layout.addWidget(self._dup_lbl)

        # Load existing commands
        for cmd in existing.get("commands", []):
            self._add_row(*self._with_signal_fields(cmd))
        self._refresh_pwr_combo(existing.get("power_cmd"),
                                on=existing.get("power_on_cmd"),
                                off=existing.get("power_off_cmd"))

        self.add_btn.clicked.connect(self._add_empty)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.learn_btn.clicked.connect(self._learn_command)
        from .. import concord
        if not concord.available():
            self.learn_btn.setEnabled(False)
            self.learn_btn.setToolTip("libconcord is not installed - see the README")

    # - Template loading ---------------------------------------------
    def load_template(self, t):
        self.table.setRowCount(0)
        self._signals = dict(t.get("signals") or {})
        for cmd in t.get("commands", []):
            self._add_row(*self._with_signal_fields(cmd))
        self._refresh_pwr_combo(t.get("power_cmd"), on=t.get("power_on_cmd"),
                                off=t.get("power_off_cmd"))

    # - Row management -----------------------------------------------
    def _add_empty(self):
        self._add_row("NewCommand", "New", "00", "00", None)
        self._refresh_pwr_combo()

    def _with_signal_fields(self, command):
        """Fill old projects whose semantic signals predate populated table cells."""
        from .. import device_json

        row = list(command)
        while len(row) < 5:
            row.append(None if len(row) == 4 else "")
        address, value = device_json.command_fields(self._signals.get(str(row[0]), {}))
        if not row[2]:
            row[2] = address
        if not row[3]:
            row[3] = value
        return row

    def _add_row(self, name, label, addr, cmd, hardslot):
        r = self.table.rowCount()
        self.table.insertRow(r)
        # A command with a captured code is played back as-is; its address and command
        # bytes are not consulted. Rather than offer two boxes that quietly do nothing,
        # show what will actually be sent, and keep the stored values out of sight so
        # nothing is lost on the way back out.
        signal = self._signals.get(str(name)) or {}
        captured = signal.get("kind") in ("waveform", "backend-opaque")
        for col, val in enumerate([str(name), str(label), str(addr), str(cmd)]):
            item = QTableWidgetItem(val)
            if captured and col in (2, 3):
                item.setData(Qt.ItemDataRole.UserRole, val)      # keep the real value
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setForeground(Qt.GlobalColor.gray)
                if col == 2:
                    item.setText("captured")
                    item.setToolTip("This command plays a captured code. Its address "
                                    "and command bytes are not used.")
                else:
                    kind = signal.get("kind", "captured")
                    item.setText(kind)
                    item.setToolTip(
                        "This signal has no editable address/command parameter.")
            self.table.setItem(r, col, item)
        # Hard key column: a button showing the current mapping
        self._set_hard_key_btn(r, hardslot)

    def _set_hard_key_btn(self, row, slot, keep_extra=True):
        """Place or replace the hard-key button in column 4 for the given row.

        A command can sit on more than one key - a set-top box with Menu on both Menu
        and Exit is ordinary, and donors carry several. The button can only show one, so
        it shows the first and carries the rest; taking `slot[0]` and discarding the
        remainder meant opening a device and pressing Save silently unbound the second
        key, undoing on the way out exactly what the importer had just been fixed to
        keep.
        """
        slots = ([s for s in slot if s] if isinstance(slot, (list, tuple))
                 else ([slot] if slot else []))
        if keep_extra:
            previous = self._hard_slots(row)
            if slots and len(previous) > 1:
                slots = slots[:1] + [s for s in previous[1:] if s not in slots]
        primary = slots[0] if slots else None
        label = primary if primary else "(none)"
        if len(slots) > 1:
            label += f"  +{len(slots) - 1}"
        btn = QPushButton(label)
        if len(slots) > 1:
            btn.setToolTip("Also on: " + ", ".join(slots[1:]))
        btn.setProperty("hardslots", slots)
        btn.setProperty("hardslot", primary)
        btn.setFlat(False)
        btn.clicked.connect(lambda _, r=row: self._open_picker(r))
        self.table.setCellWidget(row, 4, btn)

    def _hard_slots(self, row):
        """Every key this row's command sits on, in order."""
        widget = self.table.cellWidget(row, 4)
        if widget is None:
            return []
        slots = widget.property("hardslots")
        if slots:
            return list(slots)
        single = widget.property("hardslot")
        return [single] if single else []

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._check_duplicates()
        self._refresh_pwr_combo()

    # - Remote picker ------------------------------------------------
    def _on_cell_clicked(self, row, col):
        if col == 4:
            self._open_picker(row)

    def _open_picker(self, row):
        btn = self.table.cellWidget(row, 4)
        current = btn.property("hardslot") if btn else None
        # Collect all slots in use by OTHER rows
        used = set()
        for r in range(self.table.rowCount()):
            if r == row: continue
            used.update(self._hard_slots(r))
        dlg = RemotePickerDialog(current, used, self)
        if dlg.exec():
            self._set_hard_key_btn(row, dlg.chosen)
            self._check_duplicates()

    # - Duplicate detection -------------------------------------------
    def _check_duplicates(self):
        slots = []
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 4)
            s = w.property("hardslot") if w else None
            slots.append(s)
        counts = Counter(s for s in slots if s)
        dups = {s for s, n in counts.items() if n > 1}
        # Colour the rows and buttons
        for r, s in enumerate(slots):
            w = self.table.cellWidget(r, 4)
            if not w: continue
            if s and s in dups:
                w.setStyleSheet("background: #c0392b; color: white;")
            else:
                w.setStyleSheet("")
        if dups:
            self._dup_lbl.setText(
                "WARNING: duplicate hard key mapping: " + ", ".join(sorted(dups)) +
                " - the last command in the list wins on the remote."
            )
            self._dup_lbl.setVisible(True)
        else:
            self._dup_lbl.setVisible(False)

    # - Power command dropdowns ----------------------------------------
    def _power_combos(self):
        return {"power_on_cmd": self.pwr_on_combo, "power_off_cmd": self.pwr_off_combo,
                "power_cmd": self.pwr_combo}

    def _refresh_pwr_combo(self, select=None, on=None, off=None):
        """Re-populate the power dropdowns from the current table contents."""
        names = []
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0) or QTableWidgetItem("")).text().strip()
            if name:
                names.append(name)
        for wanted, combo in zip((on, off, select), (self.pwr_on_combo,
                                                     self.pwr_off_combo, self.pwr_combo)):
            previous = wanted if wanted is not None else combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(none)", None)
            for name in names:
                combo.addItem(name, name)
            index = combo.findData(previous)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def get_power_cmd(self):
        return self.pwr_combo.currentData()

    def power_fields(self) -> dict:
        """Only the power fields that are actually set, for the device spec."""
        return {key: combo.currentData()
                for key, combo in self._power_combos().items() if combo.currentData()}

    # - Flipper import ------------------------------------------------
    def _learn_command(self):
        """Learn one command straight off the original remote.

        The learned waveform is stored as a recorded capture, which is how the format
        carries a code no protocol describes: the command's <Code> points into
        SsIr.bin and its <Protocol> is -1.
        """
        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        from .remote_ops import run_with_progress

        name, ok = QInputDialog.getText(
            self, "Learn a command",
            "What is this key called? (e.g. PowerOn, VolumeUp)")
        name = (name or "").strip()
        if not ok or not name:
            return

        ok, message, capture = run_with_progress(
            self, "learn", "Learning",
            f"Point the original remote at the front of the Harmony and press "
            f"\u2018{name}\u2019\u2026",
            name=name)
        if not ok or not capture:
            QMessageBox.warning(self, "Learning failed",
                                message or "Nothing was received.")
            return

        self._learned = getattr(self, "_learned", {})
        self._learned[name] = capture
        self._add_row(name, name, "", "", None)
        self._refresh_pwr_combo()
        self.learned.emit()
        pairs = len(capture["pulses_us"]) // 2
        QMessageBox.information(
            self, "Learned",
            f"{name}: {pairs} mark/space pairs at {capture['carrier_hz']} Hz.\n\n"
            "It is stored as a recorded waveform, so it will be written into the "
            "remote's capture table rather than generated from a protocol.")

    def learned_captures(self) -> dict:
        """Codes learned in this dialog, for the device spec."""
        return dict(getattr(self, "_learned", {}))

    # - Data extraction -----------------------------------------------
    def get_commands(self):
        cmds = []
        for r in range(self.table.rowCount()):
            name  = (self.table.item(r, 0) or QTableWidgetItem("")).text().strip()
            label = (self.table.item(r, 1) or QTableWidgetItem("")).text().strip()
            # For a captured command the cells show the code, not the bytes; the real
            # values live behind them so a round trip through this page changes nothing.
            def cell(col, fallback="00"):
                item = self.table.item(r, col)
                if item is None:
                    return fallback
                kept = item.data(Qt.ItemDataRole.UserRole)
                return (kept if kept is not None else item.text()).strip()
            addr  = cell(2)
            cmd   = cell(3)
            # One key stays a plain string, several become a list - the shape the
            # builder and the importer both already use.
            slots = self._hard_slots(r)
            hard = slots[0] if len(slots) == 1 else (slots or None)
            if name:
                cmds.append((name, label, addr, cmd, hard))
        return cmds

    def updated_signals(self, commands=None):
        """Return one portable signal for every command row."""
        import copy

        from .. import device_json

        rows = commands if commands is not None else self.get_commands()
        updated = dict(self._signals)
        exemplars = [signal for signal in updated.values()
                     if signal.get("kind") == "protocol"]
        protocol_ids = {signal.get("protocol") for signal in exemplars}
        exemplar = exemplars[0] if len(protocol_ids) == 1 else None
        for row in rows:
            name = str(row[0])
            if name not in updated and exemplar is not None:
                updated[name] = copy.deepcopy(exemplar)
                updated[name]["name"] = name
        wanted = {str(row[0]) for row in rows}
        updated = {name: signal for name, signal in updated.items() if name in wanted}
        return device_json.update_signal_fields(updated, rows)


class TimingPage(QWizardPage):
    def __init__(self, existing, parent=None):
        super().__init__(parent)
        self.setTitle("Timing & Options")
        self.setSubTitle("Set IR timing delays and device behaviour in activities.")
        layout = QFormLayout(self)

        self.always_on = QCheckBox(
            "Always On (device is never powered off by activities or PowerOff macro)")
        self.always_on.setChecked(existing.get("always_on", False))
        layout.addRow(self.always_on)
        layout.addRow(sep())

        self.pwr_delay = QSpinBox()
        self.pwr_delay.setRange(0, 30000); self.pwr_delay.setSingleStep(500)
        self.pwr_delay.setSuffix(" ms")
        self.pwr_delay.setValue(existing.get("power_delay", 1500))
        layout.addRow("Power-on delay:", self.pwr_delay)

        self.pre_sil = QSpinBox()
        self.pre_sil.setRange(0, 5000); self.pre_sil.setSingleStep(50)
        self.pre_sil.setSuffix(" ms")
        self.pre_sil.setValue(existing.get("press_presilence", 1000))
        layout.addRow("Input pre-silence:", self.pre_sil)

        self.inter_key = QSpinBox()
        self.inter_key.setRange(0, 2000); self.inter_key.setSingleStep(50)
        self.inter_key.setSuffix(" ms")
        self.inter_key.setValue(existing.get("press_interkey", 500))
        layout.addRow("Inter-key delay:", self.inter_key)

        # The press-and-HOLD pair, which governs how fast volume and channel ramp when
        # a key is held down. Every dump agrees on 50/100, but they are per-device
        # values in the format, and they were previously written as constants.
        self.hold_sil = QSpinBox()
        self.hold_sil.setRange(0, 2000); self.hold_sil.setSingleStep(10)
        self.hold_sil.setSuffix(" ms")
        self.hold_sil.setValue(existing.get("hold_presilence", 50))
        layout.addRow("Hold pre-silence:", self.hold_sil)

        self.hold_key = QSpinBox()
        self.hold_key.setRange(0, 2000); self.hold_key.setSingleStep(10)
        self.hold_key.setSuffix(" ms")
        self.hold_key.setValue(existing.get("hold_interkey", 100))
        layout.addRow("Hold repeat gap:", self.hold_key)

    def load_template(self, t):
        """A device that is always on, or needs a long warm-up, says so itself."""
        self.always_on.setChecked(bool(t.get("always_on")))
        if t.get("power_delay") is not None:
            self.pwr_delay.setValue(int(t["power_delay"]))


# Keys that describe where a library entry came from rather than what the device is.
# They belong to the library file format and mean nothing to a project or the builder.
_LIBRARY_ONLY = frozenset({
    "names", "fingerprint", "source", "notes", "manufacturer", "encoding",
    "remote_models", "_template_name", "_source_file", "_database_root",
})

# Power is stored either as one toggle command or as a discrete on/off pair, so the
# keys belonging to the mode that was not chosen have to go before the chosen one is
# written - otherwise switching a device from toggle to discrete leaves both behind.
_POWER_KEYS = ("power_cmd", "power_on_cmd", "power_off_cmd")


def _portable_if_possible(device):
    """Accept old project/library records only at the UI's input edge.

    Normal application callers already provide portable devices. This defensive
    migration keeps an old saved project editable without letting native fields flow
    through the widgets or back into a newly saved project.
    """
    if not device:
        return device
    from .. import device_json, project_devices

    if project_devices.is_portable(device):
        return project_devices.clean(device)
    try:
        root = device.get("_database_root")
        return device_json.to_project_device(
            device,
            str(device.get("id") or ""),
            library=Path(root) if root else None,
        )
    except (KeyError, LookupError, TypeError, ValueError):
        # A partially entered device may not have enough IR evidence to migrate yet.
        # Keep it inspectable; collection gives the precise missing-signal error.
        return device


def _carry(base: dict) -> dict:
    """The starting point for a device spec: everything the base already said.

    Both editors used to assemble a fresh dictionary out of named widget values, which
    meant anything not named was dropped on the floor. Raw codes, inputs, properties,
    numeric and states were each lost that way, found one at a time and months apart,
    and every field the library gains would have been next.

    Starting from the base and overwriting only what the widgets own inverts the
    default: a field nobody here recognises survives instead of vanishing.
    """
    spec = {key: copy.deepcopy(value) for key, value in (base or {}).items()
            if key not in _LIBRARY_ONLY}
    for key in _POWER_KEYS:
        spec.pop(key, None)
    return spec


def _attach_learned(spec: dict, existing: dict, learned: dict) -> None:
    """Fold learned portable waveforms into the device's signal map."""
    if not learned:
        return
    signals = dict(spec.get("signals") or existing.get("signals") or {})
    for name, capture in learned.items():
        signals[name] = capture
    spec["signals"] = signals


class DeviceEditor(QDialog):
    def __init__(self, templates, parent=None, existing=None, project=None,
                 source_preferences=None):
        super().__init__(parent)
        existing = _portable_if_possible(existing)
        self.project = project
        self.setWindowTitle("Edit Device")
        self.resize(660, 600)
        self.result_spec  = None
        self._existing    = existing or {}
        self._loaded_tpl  = None      # a different model picked on the Search tab

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self.page_search = SearchPage(
            templates, self._existing, source_preferences=source_preferences)
        self.page_identity = IdentityPage(self._existing, project=project)
        self.page_cmds     = CommandsPage(self._existing)
        self.page_timing   = TimingPage(self._existing)
        self.page_props    = PropertiesEditor("device", self._existing.get("properties"),
                                      kind=self._existing.get("type"))
        
        self.tabs.addTab(self.page_search, "Search")
        self.tabs.addTab(self.page_identity, "Identity")
        self.tabs.addTab(self.page_cmds, "Commands")
        self.tabs.addTab(self.page_timing, "Timing")
        self.tabs.addTab(self.page_props, "Advanced")
        
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
        self.page_search.template_selected.connect(self._on_template_selected)
        self.page_cmds.learned.connect(self._on_learned)

    def _on_learned(self):
        """Refresh the summary after a portable waveform was learned."""
        self.page_identity.refresh_protocol()

    def _on_template_selected(self, t):
        # Picking a model here replaces the device. Remembering which one is the whole
        # point: without it the pages showed the new model's commands while _collect
        # went on carrying the old model's codes, and the build stopped with dozens of
        # commands that had no code at all.
        self._loaded_tpl = t
        # The type decides which properties are worth offering, so it has to reach the
        # Advanced page before the values do.
        self.page_props.set_kind(t.get("type"))
        if t.get("properties"):
            self.page_props.set_values(t["properties"])
        self.page_identity.apply_template(t)
        self.page_cmds.load_template(t)
        self.page_timing.load_template(t)

    def rf_token(self):
        """The IR output the user chose, applied by the caller once the id is known."""
        return self.page_identity.rf_combo.currentData()

    def _commands_activities_use(self):
        """{command name: [activity label]} - what the rest of the project expects this
        device to be able to do. Swapping models can take a command away, and the
        activity that used it would quietly stop working."""
        used = {}
        device_id = str(self._existing.get("id") or "")
        for activity in (self.project or {}).get("activities") or []:
            label = activity.get("label", "?")
            steps = list(activity.get("enter") or []) + list(activity.get("leave") or [])
            for macro in (activity.get("hard_macros") or {}).values():
                steps += list(macro or [])
            for button in activity.get("soft_buttons") or []:
                if isinstance(button, dict):
                    steps += list(button.get("macro") or [])
                    if button.get("device") and button.get("command"):
                        steps.append(("command", button["device"], button["command"]))
                elif len(button) >= 3:
                    steps.append(("command", button[1], button[2]))
            for step in steps:
                if (len(step) >= 3 and step[0] == "command"
                        and str(step[1]) == device_id):
                    used.setdefault(step[2], []).append(label)
        return used

    def accept(self):
        spec = self._collect()
        # Replacing the model can take away a command an activity is built on. The
        # build does not fail for it - the activity simply loses that button, or a
        # macro step goes nowhere - so it has to be said out loud beforehand.
        if self._loaded_tpl:
            has = {name for name, *_rest in spec.get("commands") or []}
            lost = {cmd: where for cmd, where in self._commands_activities_use().items()
                    if cmd not in has}
            if lost:
                listed = "\n".join(f"  {cmd}  - used by {', '.join(sorted(set(where)))}"
                                   for cmd, where in sorted(lost.items()))
                answer = QMessageBox.warning(
                    self, "Some activities use commands this model does not have",
                    f"{self._loaded_tpl.get('model') or 'The new model'} has no "
                    f"equivalent of:\n\n{listed}\n\nThose buttons and macro steps "
                    "will stop doing anything. The configuration will still "
                    "build.\n\nReplace the device anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
        self.result_spec = spec
        super().accept()

    def _collect(self):
        ident = self.page_identity
        cmds  = self.page_cmds
        tim   = self.page_timing
        # Editing a device must not cost it anything this dialog has no page for. An
        # imported device carries states, per-command icons and learned waveforms that
        # nothing here shows; rebuilding the spec from the widgets alone deleted them.
        # If a different model was picked on the Search tab this is a replacement, so
        # everything that describes the hardware comes from the new model: its codes,
        # its protocol, its states, its inputs. Only what the project owns - the id the
        # activities reference, and the name the user gave it - is kept. Carrying the
        # old device forward here is what produced a device whose command list came
        # from one model and whose codes came from another.
        source = self._loaded_tpl or self._existing
        spec = _carry(source)
        command_rows = cmds.get_commands()
        spec.update({
            "schema":            "afterglow-project-device/1",
            "id":                ident.id_edit.text().strip() or self._existing.get("id", ""),
            "label":             ident.label_edit.text().strip() or "Unnamed Device",
            "type":              ident.type_combo.currentData() or ident.type_combo.currentText(),
            "mfr":               ident.mfr_edit.text().strip(),
            "model":             ident.model_edit.text().strip(),
            **cmds.power_fields(),
            "properties":        self.page_props.values(),
            "always_on":         tim.always_on.isChecked(),
            "power_delay":       tim.pwr_delay.value(),
            "press_presilence":  tim.pre_sil.value(),
            "press_interkey":    tim.inter_key.value(),
            "hold_presilence":   tim.hold_sil.value(),
            "hold_interkey":     tim.hold_key.value(),
            "commands":          command_rows,
        })
        spec["signals"] = cmds.updated_signals(command_rows)
        _attach_learned(spec, self._existing, cmds.learned_captures())
        from .. import project_devices
        project_devices.validate(spec)
        return spec
