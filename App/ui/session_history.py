"""
ui.session_history
~~~~~~~~~~~~~~~~~~
"History" tab — shows all saved sessions in a sortable table, allows
loading a session into the Results view, and supports per-session CSV export.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore    import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QLabel, QFileDialog, QMessageBox,
    QAbstractItemView,
)

from data.models  import SessionResult
from data.storage import StorageManager


class SessionHistoryWidget(QWidget):
    """Browsable table of past sessions."""

    #: Emitted when the user clicks "View Results" for a session.
    session_selected = pyqtSignal(object)   # SessionResult

    def __init__(self, storage: StorageManager,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._storage:  StorageManager       = storage
        self._sessions: list[SessionResult]  = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("<b>Past Sessions</b>"))

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([
            "Date / Time", "Participant", "Configuration",
            "Scored trials", "Accuracy", "Mean RT (ms)", "Duration",
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_double_click)
        root.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._view_btn   = QPushButton("📊  View Results")
        self._export_btn = QPushButton("Export CSV…")
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setStyleSheet("color:#E53935;")
        self._view_btn.clicked.connect(self._view_selected)
        self._export_btn.clicked.connect(self._export_selected)
        self._delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self._view_btn)
        btn_row.addWidget(self._export_btn)
        btn_row.addWidget(self._delete_btn)
        root.addLayout(btn_row)

        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the session list from storage."""
        self._sessions = self._storage.list_sessions()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._sessions))

        for r, s in enumerate(self._sessions):
            stats      = s.overall_stats()
            acc_pct    = f"{s.accuracy() * 100:.1f} %"
            duration   = (f"{s.duration_seconds():.0f}s"
                          if s.end_time else "—")
            mean_rt    = str(stats["mean"]) if stats["n"] else "—"

            for c, val in enumerate([
                s.start_time[:19].replace("T", " "),
                s.participant_id,
                s.config_name,
                str(len(s.scored_trials)),
                acc_pct,
                mean_rt,
                duration,
            ]):
                item = QTableWidgetItem(val)
                item.setData(Qt.ItemDataRole.UserRole, s)
                self._table.setItem(r, c, item)

        self._table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _selected_session(self) -> Optional[SessionResult]:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._sessions):
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _view_selected(self) -> None:
        s = self._selected_session()
        if s:
            self.session_selected.emit(s)

    def _on_double_click(self, _index) -> None:
        self._view_selected()

    def _export_selected(self) -> None:
        s = self._selected_session()
        if not s:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Session CSV",
            f"{s.participant_id}_{s.start_time[:10]}.csv",
            "CSV Files (*.csv)")
        if not path:
            return
        from pathlib import Path
        try:
            self._storage.export_session_csv(s, Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    def _delete_selected(self) -> None:
        s = self._selected_session()
        if not s:
            return
        ans = QMessageBox.question(
            self, "Delete Session",
            f"Delete the session for '{s.participant_id}' "
            f"on {s.start_time[:10]}?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._storage.delete_session(s.session_id)
            self.refresh()
