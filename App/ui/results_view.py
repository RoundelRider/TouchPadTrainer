"""
ui.results_view
~~~~~~~~~~~~~~~
Results tab — displays statistics and a per-pad heatmap after each session,
and supports side-by-side comparison with a previous session.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore    import Qt, pyqtSlot
from PyQt6.QtGui     import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QComboBox, QFormLayout,
)

from data.models  import SessionResult, TestConfiguration
from data.storage import StorageManager
from ui.pad_grid  import PadGridWidget

logger = logging.getLogger(__name__)


class ResultsViewWidget(QWidget):
    """Results view: statistics, pad heatmap, session comparison."""

    def __init__(self, storage: StorageManager,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._storage  = storage
        self._session: Optional[SessionResult]  = None
        self._compare: Optional[SessionResult]  = None
        self._result_grids: list[PadGridWidget] = []
        self._result_grid_groups: list[QGroupBox] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)

        # ---- Header row ------------------------------------------------
        hdr = QHBoxLayout()
        self._title_lbl = QLabel("<i>No results loaded</i>")
        f = QFont(); f.setPointSize(12); self._title_lbl.setFont(f)
        hdr.addWidget(self._title_lbl, 1)

        self._compare_combo = QComboBox()
        self._compare_combo.setMinimumWidth(200)
        self._compare_combo.addItem("Compare with…")
        self._compare_btn = QPushButton("Load comparison")
        self._compare_btn.clicked.connect(self._load_compare)
        self._export_btn = QPushButton("Export CSV…")
        self._export_btn.clicked.connect(self._export_csv)
        hdr.addWidget(self._compare_combo)
        hdr.addWidget(self._compare_btn)
        hdr.addWidget(self._export_btn)
        root.addLayout(hdr)

        # ---- Main splitter ---------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # Left: stats + errors
        left = QWidget()
        lv   = QVBoxLayout(left)

        stats_grp = QGroupBox("Overall Statistics")
        sv        = QVBoxLayout(stats_grp)
        self._stats_table = QTableWidget(6, 2)
        self._stats_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self._stats_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._stats_table.verticalHeader().setVisible(False)
        self._stats_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self._stats_table.setMaximumHeight(210)
        for r, name in enumerate(
            ["N (hits)", "Mean RT (ms)", "Median RT (ms)",
             "Std Dev (ms)", "Min RT (ms)", "Max RT (ms)"]
        ):
            self._stats_table.setItem(r, 0, QTableWidgetItem(name))
            self._stats_table.setItem(r, 1, QTableWidgetItem("—"))
        sv.addWidget(self._stats_table)
        lv.addWidget(stats_grp)

        err_grp = QGroupBox("Error Summary")
        ev      = QFormLayout(err_grp)
        self._accuracy_lbl    = QLabel("—")
        self._commission_lbl  = QLabel("—")
        self._omission_lbl    = QLabel("—")
        ev.addRow("Accuracy:",             self._accuracy_lbl)
        ev.addRow("Commission errors (FA):", self._commission_lbl)
        ev.addRow("Omission errors (miss):", self._omission_lbl)
        lv.addWidget(err_grp)

        # Comparison block (initially hidden)
        self._compare_grp = QGroupBox("Session Comparison")
        cv = QVBoxLayout(self._compare_grp)
        self._compare_lbl = QLabel("No comparison loaded.")
        self._compare_lbl.setWordWrap(True)
        self._compare_lbl.setStyleSheet("color:#1565C0;")
        cv.addWidget(self._compare_lbl)
        lv.addWidget(self._compare_grp)

        lv.addStretch()
        splitter.addWidget(left)

        # Right: heatmap + per-pad table
        right = QWidget()
        rv    = QVBoxLayout(right)

        self._heatmap_grp = QGroupBox("Per-Pad Result Heatmap")
        self._heatmap_row = QHBoxLayout(self._heatmap_grp)
        rv.addWidget(self._heatmap_grp)

        per_grp = QGroupBox("Per-Pad Statistics")
        pv      = QVBoxLayout(per_grp)
        self._per_pad_table = QTableWidget(0, 5)
        self._per_pad_table.setHorizontalHeaderLabels(
            ["Panel", "Pad", "N (hits)", "Mean RT (ms)", "Band"])
        self._per_pad_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._per_pad_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        pv.addWidget(self._per_pad_table)
        rv.addWidget(per_grp, 1)

        splitter.addWidget(right)
        splitter.setSizes([300, 700])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_session(self, session: SessionResult) -> None:
        """Display results for *session*."""
        self._session = session
        self._refresh_session_ui()
        self._refresh_compare_combo()

    # ------------------------------------------------------------------
    # Internal refresh
    # ------------------------------------------------------------------

    def _refresh_session_ui(self) -> None:
        s = self._session
        if not s:
            return

        self._title_lbl.setText(
            f"<b>{s.config_name}</b>  ·  "
            f"Participant: <b>{s.participant_id}</b>  ·  "
            f"{s.start_time[:19].replace('T', ' ')}")

        # Overall stats
        stats = s.overall_stats()
        vals  = [stats["n"], stats["mean"], stats["median"],
                 stats["std"], stats["min"], stats["max"]]
        for r, v in enumerate(vals):
            self._stats_table.item(r, 1).setText(str(v))

        self._accuracy_lbl.setText(
            f"{s.accuracy() * 100:.1f} %  "
            f"({sum(1 for t in s.scored_trials if t.is_correct)}"
            f" / {len(s.scored_trials)} correct)")
        self._commission_lbl.setText(str(s.commission_errors()))
        self._omission_lbl.setText(str(s.omission_errors()))

        # Find the config to get RT-band colours
        cfg = self._find_config(s.config_name)

        # Rebuild heatmap grids
        for grp in self._result_grid_groups:
            self._heatmap_row.removeWidget(grp)
            grp.deleteLater()
        self._result_grid_groups.clear()
        self._result_grids.clear()

        panels = sorted({t.panel for t in s.trials})
        for panel in panels:
            grid = PadGridWidget(panel_index=panel)
            for pad in range(16):
                ps = s.stats_for_pad(panel, pad)
                if ps["n"] > 0:
                    color = (cfg.color_for_rt(ps["mean"])
                             if cfg else "#9E9E9E")
                    grid.light_pad_hex(pad, color)
            self._result_grids.append(grid)
            grp = QGroupBox(f"Panel {panel + 1}")
            gv  = QVBoxLayout(grp)
            gv.addWidget(grid)
            self._result_grid_groups.append(grp)
            self._heatmap_row.addWidget(grp)

        # Per-pad table
        per_pad = s.stats_per_pad()
        self._per_pad_table.setRowCount(len(per_pad))
        for r, ((panel, pad), ps) in enumerate(
            sorted(per_pad.items())
        ):
            color  = cfg.color_for_rt(ps["mean"]) if cfg and ps["n"] else "#E0E0E0"
            label  = cfg.band_for_rt(ps["mean"]).label if cfg and ps["n"] else "—"
            items  = [panel + 1, pad + 1, ps["n"], ps["mean"], label]
            for c, val in enumerate(items):
                item = QTableWidgetItem(str(val))
                if c == 4:
                    item.setBackground(QColor(color))
                self._per_pad_table.setItem(r, c, item)

        # Update comparison if one is loaded
        if self._compare:
            self._render_comparison()

    def _refresh_compare_combo(self) -> None:
        self._compare_combo.clear()
        self._compare_combo.addItem("Compare with previous session…", None)
        current_id = self._session.session_id if self._session else None
        for s in self._storage.list_sessions(limit=20):
            if s.session_id != current_id:
                label = (f"{s.start_time[:10]}  {s.participant_id}"
                         f"  [{s.config_name}]")
                self._compare_combo.addItem(label, s)

    def _load_compare(self) -> None:
        s = self._compare_combo.currentData()
        if s is None:
            return
        self._compare = s
        self._render_comparison()

    def _render_comparison(self) -> None:
        if not self._session or not self._compare:
            return
        cs = self._compare.overall_stats()
        ms = self._session.overall_stats()
        diff = ms["mean"] - cs["mean"]
        sign = "+" if diff > 0 else ""
        direction = "slower" if diff > 0 else "faster"
        self._compare_lbl.setText(
            f"Comparing with  <b>{self._compare.participant_id}</b>  "
            f"({self._compare.start_time[:10]},  {self._compare.config_name})\n\n"
            f"Current mean RT: <b>{ms['mean']} ms</b>  ·  "
            f"Previous: <b>{cs['mean']} ms</b>  ·  "
            f"Difference: <b>{sign}{diff} ms</b> ({direction})\n"
            f"Current accuracy: {self._session.accuracy()*100:.1f}%  ·  "
            f"Previous: {self._compare.accuracy()*100:.1f}%"
        )

    def _find_config(self, name: str) -> Optional[TestConfiguration]:
        for cfg in self._storage.list_configs():
            if cfg.name == name:
                return cfg
        return None

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_csv(self) -> None:
        if not self._session:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Session CSV",
            f"{self._session.participant_id}_results.csv",
            "CSV Files (*.csv)")
        if not path:
            return
        from pathlib import Path
        try:
            self._storage.export_session_csv(self._session, Path(path))
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Failed", str(exc))
