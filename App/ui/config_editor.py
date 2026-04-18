"""
ui.config_editor
~~~~~~~~~~~~~~~~
Configuration editor tab.

Layout
------
Left panel  : scrollable list of saved configurations + New/Delete/Import/Export
Right panel : form editor with:
              - Name, read-only lock, last-modified timestamp
              - Panel count + interactive 4×4 pad selectors
                (left-click = toggle active, right-click = toggle faulty)
              - Test type combo
              - Timing & trial settings
              - Randomisation options
              - Reaction-time band table with colour picker
              - Save button
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from PyQt6.QtCore    import Qt, pyqtSignal
from PyQt6.QtGui     import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QPushButton, QCheckBox, QListWidget, QListWidgetItem,
    QMessageBox, QFileDialog, QScrollArea, QSplitter,
    QColorDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
)

from data.models import (
    TestConfiguration, TestType, PadOrder,
    PadConfig, ReactionBand,
)
from data.storage import StorageManager
from ui.pad_grid import PadGridWidget


class ConfigEditorWidget(QWidget):
    """Full configuration CRUD editor."""

    config_saved = pyqtSignal(object)   # TestConfiguration

    def __init__(self, storage: StorageManager,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._storage         = storage
        self._current_cfg: Optional[TestConfiguration] = None
        # per-panel state — indexed [panel][pad]
        self._pad_active: list[list[bool]] = []
        self._pad_faulty: list[list[bool]] = []
        self._grid_widgets: list[PadGridWidget] = []
        self._grid_group_widgets: list[QGroupBox] = []
        self._setup_ui()
        self._refresh_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        # ---- Left: config list -----------------------------------------
        left = QWidget()
        lv   = QVBoxLayout(left)
        lv.addWidget(QLabel("<b>Saved Configurations</b>"))

        self._cfg_list = QListWidget()
        self._cfg_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._cfg_list.currentItemChanged.connect(self._on_list_selection)
        lv.addWidget(self._cfg_list, 1)

        btns = QHBoxLayout()
        self._new_btn = QPushButton("New")
        self._del_btn = QPushButton("Delete")
        self._imp_btn = QPushButton("Import…")
        self._exp_btn = QPushButton("Export…")
        for b in (self._new_btn, self._del_btn, self._imp_btn, self._exp_btn):
            btns.addWidget(b)
        lv.addLayout(btns)

        self._new_btn.clicked.connect(self._new_config)
        self._del_btn.clicked.connect(self._delete_config)
        self._imp_btn.clicked.connect(self._import_config)
        self._exp_btn.clicked.connect(self._export_config)
        splitter.addWidget(left)

        # ---- Right: editor (scrollable) --------------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        right  = QWidget()
        ev     = QVBoxLayout(right)
        self._build_editor(ev)
        scroll.setWidget(right)
        splitter.addWidget(scroll)
        splitter.setSizes([220, 780])

    def _build_editor(self, layout: QVBoxLayout) -> None:
        # ---- Identity --------------------------------------------------
        id_grp = QGroupBox("Configuration Identity")
        idf    = QFormLayout(id_grp)
        self._name_edit   = QLineEdit()
        self._name_edit.setPlaceholderText("Enter a descriptive name")
        self._readonly_chk = QCheckBox("Lock as read-only")
        self._modified_lbl = QLabel("—")
        self._modified_lbl.setStyleSheet("color:#78909C; font-size:10px;")
        idf.addRow("Name:",          self._name_edit)
        idf.addRow("",               self._readonly_chk)
        idf.addRow("Last modified:", self._modified_lbl)
        layout.addWidget(id_grp)

        # ---- Panel count -----------------------------------------------
        panel_grp  = QGroupBox("Panel Settings")
        pf         = QFormLayout(panel_grp)
        self._num_panels_spin = QSpinBox()
        self._num_panels_spin.setRange(1, 4)
        self._num_panels_spin.valueChanged.connect(self._on_num_panels_changed)
        pf.addRow("Number of panels:", self._num_panels_spin)
        layout.addWidget(panel_grp)

        # ---- Pad selector grids ----------------------------------------
        self._pads_grp = QGroupBox(
            "Active Pads  (left-click = toggle active · right-click = faulty)")
        self._pads_row = QHBoxLayout(self._pads_grp)
        layout.addWidget(self._pads_grp)

        # ---- Test type -------------------------------------------------
        tt_grp = QGroupBox("Test Type")
        tf     = QFormLayout(tt_grp)
        self._test_type_combo = QComboBox()
        for tt in TestType:
            self._test_type_combo.addItem(
                tt.name.replace("_", " ").title(), tt)
        tf.addRow("Test type:", self._test_type_combo)
        layout.addWidget(tt_grp)

        # ---- Timing & Trials -------------------------------------------
        tm_grp = QGroupBox("Timing & Trials")
        tmf    = QFormLayout(tm_grp)

        self._timeout_spin   = QSpinBox();  self._timeout_spin.setRange(100, 30000);   self._timeout_spin.setSuffix(" ms")
        self._trials_spin    = QSpinBox();  self._trials_spin.setRange(1, 1000)
        self._isi_spin       = QSpinBox();  self._isi_spin.setRange(0, 10000);         self._isi_spin.setSuffix(" ms")
        self._warmup_spin    = QSpinBox();  self._warmup_spin.setRange(0, 50)
        self._rest_n_spin    = QSpinBox();  self._rest_n_spin.setRange(0, 500);        self._rest_n_spin.setSpecialValueText("Disabled")
        self._rest_dur_spin  = QSpinBox();  self._rest_dur_spin.setRange(1000, 60000); self._rest_dur_spin.setSuffix(" ms")

        tmf.addRow("Timeout per trial:",        self._timeout_spin)
        tmf.addRow("Number of trials:",         self._trials_spin)
        tmf.addRow("Inter-stimulus interval:",  self._isi_spin)
        tmf.addRow("Warm-up trials:",           self._warmup_spin)
        tmf.addRow("Rest break every N trials:", self._rest_n_spin)
        tmf.addRow("Rest break duration:",      self._rest_dur_spin)
        layout.addWidget(tm_grp)

        # ---- Randomisation ---------------------------------------------
        rand_grp = QGroupBox("Randomisation")
        rf       = QFormLayout(rand_grp)
        self._pad_order_combo = QComboBox()
        for po in PadOrder:
            self._pad_order_combo.addItem(
                po.name.replace("_", " ").title(), po)
        self._ratio_spin = QDoubleSpinBox()
        self._ratio_spin.setRange(0.0, 1.0)
        self._ratio_spin.setSingleStep(0.05)
        self._ratio_spin.setDecimals(2)
        self._ratio_spin.setToolTip(
            "Fraction of selective-mode trials where a touch is expected "
            "(1.0 = always green, 0.0 = always red)")
        rf.addRow("Pad order:",              self._pad_order_combo)
        rf.addRow("Green : red ratio:",      self._ratio_spin)
        layout.addWidget(rand_grp)

        # ---- RT Bands --------------------------------------------------
        rt_grp = QGroupBox("Reaction Time Bands  (up to 5)")
        rtl    = QVBoxLayout(rt_grp)
        self._rt_table = QTableWidget(5, 3)
        self._rt_table.setHorizontalHeaderLabels(
            ["Upper bound (ms)", "Colour", "Label"])
        self._rt_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._rt_table.setMaximumHeight(175)
        self._rt_table.setToolTip(
            "Trials whose RT falls at or below the upper bound are shown "
            "in that row's colour.  Leave rows blank to use fewer bands.")
        rtl.addWidget(self._rt_table)

        rt_btn_row = QHBoxLayout()
        self._rt_color_btn = QPushButton("Pick colour for selected row…")
        self._rt_color_btn.clicked.connect(self._pick_rt_color)
        self._rt_reset_btn = QPushButton("Reset to defaults")
        self._rt_reset_btn.clicked.connect(self._reset_rt_bands)
        rt_btn_row.addWidget(self._rt_color_btn)
        rt_btn_row.addWidget(self._rt_reset_btn)
        rtl.addLayout(rt_btn_row)
        layout.addWidget(rt_grp)

        # ---- Validation feedback ---------------------------------------
        self._validation_lbl = QLabel("")
        self._validation_lbl.setWordWrap(True)
        self._validation_lbl.setStyleSheet("color:#E53935;")
        layout.addWidget(self._validation_lbl)

        # ---- Save ------------------------------------------------------
        save_row = QHBoxLayout()
        self._save_btn = QPushButton("💾  Save Configuration")
        self._save_btn.setDefault(True)
        self._save_btn.setStyleSheet(
            "QPushButton { background:#1565C0; color:white; "
            "padding:8px 20px; border-radius:4px; font-weight:bold; }"
            "QPushButton:hover { background:#0D47A1; }")
        self._save_btn.clicked.connect(self._save_config)
        save_row.addStretch()
        save_row.addWidget(self._save_btn)
        layout.addLayout(save_row)
        layout.addStretch()

        # Initialise grids with 1 panel
        self._rebuild_pad_grids(1)

    # ------------------------------------------------------------------
    # Pad grid management
    # ------------------------------------------------------------------

    def _rebuild_pad_grids(self, num_panels: int) -> None:
        """Recreate the pad-selector grids for *num_panels* panels."""
        # Remove existing grid groups from layout
        for grp in self._grid_group_widgets:
            self._pads_row.removeWidget(grp)
            grp.deleteLater()
        self._grid_group_widgets.clear()
        self._grid_widgets.clear()

        # Extend state arrays as needed
        while len(self._pad_active) < num_panels:
            self._pad_active.append([True] * 16)
            self._pad_faulty.append([False] * 16)

        for panel in range(num_panels):
            grid = PadGridWidget(panel_index=panel)
            grid.pad_left_clicked.connect(
                lambda idx, p=panel: self._toggle_active(p, idx))
            grid.pad_right_clicked.connect(
                lambda idx, p=panel: self._toggle_faulty(p, idx))
            self._grid_widgets.append(grid)

            grp = QGroupBox(f"Panel {panel + 1}")
            gv  = QVBoxLayout(grp)
            gv.addWidget(grid)
            self._grid_group_widgets.append(grp)
            self._pads_row.addWidget(grp)

            self._sync_grid(panel)

    def _sync_grid(self, panel: int) -> None:
        """Redraw the grid cells to reflect current active/faulty state."""
        if panel >= len(self._grid_widgets):
            return
        grid = self._grid_widgets[panel]
        for pad in range(16):
            faulty = self._pad_faulty[panel][pad]
            active = self._pad_active[panel][pad]
            grid.set_faulty(pad, faulty)
            grid.set_selected(pad, active and not faulty)
            if not faulty and not active:
                grid.clear_pad(pad)

    def _toggle_active(self, panel: int, pad: int) -> None:
        if panel < len(self._pad_active):
            self._pad_active[panel][pad] = not self._pad_active[panel][pad]
            self._sync_grid(panel)

    def _toggle_faulty(self, panel: int, pad: int) -> None:
        if panel < len(self._pad_faulty):
            self._pad_faulty[panel][pad] = not self._pad_faulty[panel][pad]
            self._sync_grid(panel)

    def _on_num_panels_changed(self, value: int) -> None:
        self._rebuild_pad_grids(value)

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        self._cfg_list.clear()
        for cfg in self._storage.list_configs(sort_by="name"):
            item = QListWidgetItem(cfg.name)
            item.setData(Qt.ItemDataRole.UserRole, cfg)
            if cfg.read_only:
                item.setToolTip("🔒 Read-only")
            self._cfg_list.addItem(item)

    def _on_list_selection(self,
                            item: Optional[QListWidgetItem],
                            _prev: Optional[QListWidgetItem] = None
                            ) -> None:
        if item is None:
            return
        cfg: TestConfiguration = item.data(Qt.ItemDataRole.UserRole)
        self._load_to_form(cfg)

    # ------------------------------------------------------------------
    # Form ↔ model
    # ------------------------------------------------------------------

    def _load_to_form(self, cfg: TestConfiguration) -> None:
        self._current_cfg = cfg
        self._validation_lbl.setText("")

        self._name_edit.setText(cfg.name)
        self._readonly_chk.setChecked(cfg.read_only)
        self._modified_lbl.setText(cfg.last_modified[:19].replace("T", " "))
        self._num_panels_spin.blockSignals(True)
        self._num_panels_spin.setValue(cfg.num_panels)
        self._num_panels_spin.blockSignals(False)

        # Rebuild grids and load pad state
        self._pad_active = [[True] * 16 for _ in range(cfg.num_panels)]
        self._pad_faulty = [[False] * 16 for _ in range(cfg.num_panels)]
        for pc in cfg.pads:
            if pc.panel < cfg.num_panels:
                self._pad_active[pc.panel][pc.pad] = not pc.faulty
                self._pad_faulty[pc.panel][pc.pad] = pc.faulty
        self._rebuild_pad_grids(cfg.num_panels)

        idx = self._test_type_combo.findData(cfg.test_type)
        self._test_type_combo.setCurrentIndex(max(0, idx))
        self._timeout_spin.setValue(cfg.timeout_ms)
        self._trials_spin.setValue(cfg.num_trials)
        self._isi_spin.setValue(cfg.isi_ms)
        self._warmup_spin.setValue(cfg.warmup_trials)
        self._rest_n_spin.setValue(cfg.rest_every_n)
        self._rest_dur_spin.setValue(cfg.rest_duration_ms)

        idx2 = self._pad_order_combo.findData(cfg.pad_order)
        self._pad_order_combo.setCurrentIndex(max(0, idx2))
        self._ratio_spin.setValue(cfg.green_red_ratio)

        # RT bands
        self._rt_table.clearContents()
        for row, band in enumerate(cfg.rt_bands[:5]):
            self._rt_table.setItem(row, 0, QTableWidgetItem(str(band.max_ms)))
            ci = QTableWidgetItem(band.color)
            ci.setBackground(QColor(band.color))
            self._rt_table.setItem(row, 1, ci)
            self._rt_table.setItem(row, 2, QTableWidgetItem(band.label))

    def _form_to_config(self) -> TestConfiguration:
        pads: list[PadConfig] = []
        for panel in range(self._num_panels_spin.value()):
            for pad in range(16):
                faulty = (panel < len(self._pad_faulty) and
                          self._pad_faulty[panel][pad])
                active = (panel < len(self._pad_active) and
                          self._pad_active[panel][pad])
                if active or faulty:
                    pads.append(PadConfig(panel=panel, pad=pad, faulty=faulty))

        bands: list[ReactionBand] = []
        for row in range(5):
            ms_item    = self._rt_table.item(row, 0)
            color_item = self._rt_table.item(row, 1)
            label_item = self._rt_table.item(row, 2)
            if ms_item and ms_item.text().strip():
                try:
                    bands.append(ReactionBand(
                        max_ms=int(ms_item.text()),
                        color=color_item.text() if color_item else "#888888",
                        label=label_item.text() if label_item else "",
                    ))
                except ValueError:
                    pass

        cfg_id = (self._current_cfg.id
                  if self._current_cfg else str(uuid.uuid4()))
        return TestConfiguration(
            name             = self._name_edit.text().strip() or "Unnamed",
            id               = cfg_id,
            read_only        = self._readonly_chk.isChecked(),
            last_modified    = datetime.now().isoformat(),
            num_panels       = self._num_panels_spin.value(),
            pads             = pads,
            test_type        = self._test_type_combo.currentData(),
            timeout_ms       = self._timeout_spin.value(),
            num_trials       = self._trials_spin.value(),
            isi_ms           = self._isi_spin.value(),
            warmup_trials    = self._warmup_spin.value(),
            rest_every_n     = self._rest_n_spin.value(),
            rest_duration_ms = self._rest_dur_spin.value(),
            pad_order        = self._pad_order_combo.currentData(),
            green_red_ratio  = self._ratio_spin.value(),
            rt_bands         = bands,
        )

    # ------------------------------------------------------------------
    # CRUD actions
    # ------------------------------------------------------------------

    def _new_config(self) -> None:
        self._current_cfg = None
        blank = TestConfiguration(name="New Configuration")
        self._load_to_form(blank)
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _save_config(self) -> None:
        if self._current_cfg and self._current_cfg.read_only:
            ans = QMessageBox.question(
                self, "Read-only Configuration",
                "This configuration is locked.  Save as a new copy?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            self._current_cfg = None   # force new UUID

        cfg    = self._form_to_config()
        issues = cfg.validate()
        if issues:
            self._validation_lbl.setText("⚠  " + "\n⚠  ".join(issues))
            return
        self._validation_lbl.setText("")

        try:
            self._storage.save_config(cfg)
        except PermissionError as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))
            return

        self._current_cfg = cfg
        self._refresh_list()
        self.config_saved.emit(cfg)

        # Re-select in list
        for i in range(self._cfg_list.count()):
            item = self._cfg_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole).id == cfg.id:
                self._cfg_list.setCurrentItem(item)
                break

    def _delete_config(self) -> None:
        item = self._cfg_list.currentItem()
        if not item:
            return
        cfg: TestConfiguration = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(
            self, "Delete Configuration",
            f"Delete '{cfg.name}'?  This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self._storage.delete_config(cfg.id)
        except PermissionError as exc:
            QMessageBox.warning(self, "Delete Failed", str(exc))
            return
        self._current_cfg = None
        self._refresh_list()

    def _import_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Configuration", "",
            "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        from pathlib import Path
        try:
            cfg = self._storage.import_config(Path(path))
            self._refresh_list()
            QMessageBox.information(
                self, "Imported", f"'{cfg.name}' imported successfully.")
        except Exception as exc:
            QMessageBox.warning(self, "Import Failed", str(exc))

    def _export_config(self) -> None:
        if not self._current_cfg:
            QMessageBox.information(
                self, "Export", "Select a configuration first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Configuration",
            f"{self._current_cfg.name}.json",
            "JSON Files (*.json)")
        if not path:
            return
        from pathlib import Path
        try:
            self._storage.export_config(self._current_cfg, Path(path))
            QMessageBox.information(self, "Exported", f"Saved to {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    # ------------------------------------------------------------------
    # RT band helpers
    # ------------------------------------------------------------------

    def _pick_rt_color(self) -> None:
        row = self._rt_table.currentRow()
        if row < 0:
            return
        current_item = self._rt_table.item(row, 1)
        initial = QColor(current_item.text() if current_item else "#888888")
        color = QColorDialog.getColor(initial, self, "Choose Band Colour")
        if color.isValid():
            item = QTableWidgetItem(color.name())
            item.setBackground(color)
            self._rt_table.setItem(row, 1, item)

    def _reset_rt_bands(self) -> None:
        """Repopulate RT band table from the configuration defaults."""
        tmp = TestConfiguration(
            name="tmp",
            timeout_ms=self._timeout_spin.value(),
        )
        tmp.reset_default_bands()
        self._rt_table.clearContents()
        for row, band in enumerate(tmp.rt_bands[:5]):
            self._rt_table.setItem(row, 0, QTableWidgetItem(str(band.max_ms)))
            ci = QTableWidgetItem(band.color)
            ci.setBackground(QColor(band.color))
            self._rt_table.setItem(row, 1, ci)
            self._rt_table.setItem(row, 2, QTableWidgetItem(band.label))

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the configuration list (called after external changes)."""
        self._refresh_list()
