"""
ui.test_panel
~~~~~~~~~~~~~
"Run Test" tab.

Responsibilities
----------------
- Participant ID entry
- Configuration selector (with refresh)
- Auditory cue toggles (countdown beep, stimulus tone)
- Orientation-check button
- Start / Cancel buttons
- Progress bar and phase label
- Live 4×4 pad grid (mirrors physical pad state in real time)
- Scrolling trial log (last 10 trials)
- Wires TestRunner onto a QThread; saves the SessionResult when done
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore    import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui     import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QComboBox, QPushButton, QProgressBar,
    QCheckBox, QMessageBox, QScrollArea, QSizePolicy,
)

from core.audio          import AudioCue
from core.serial_manager import SerialManager
from core.test_runner    import TestRunner
from data.models         import TestConfiguration, SessionResult, TrialResult
from data.storage        import StorageManager
from ui.pad_grid         import PadGridWidget

logger = logging.getLogger(__name__)


class TestPanelWidget(QWidget):
    """Run-test tab widget."""

    #: Emitted after the session has been saved to disk.
    session_saved = pyqtSignal(object)   # SessionResult

    def __init__(
        self,
        serial:  SerialManager,
        storage: StorageManager,
        parent:  QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._serial          = serial
        self._storage         = storage
        self._audio           = AudioCue()
        self._runner: Optional[TestRunner] = None
        self._thread: Optional[QThread]    = None
        self._trial_log_lines: list[str]   = []
        self._pad_grids: list[PadGridWidget] = []
        self._grid_groups: list[QGroupBox]   = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ---- Top row: config + participant + cues ----------------------
        top = QHBoxLayout()

        cfg_grp = QGroupBox("Test Configuration")
        cf      = QFormLayout(cfg_grp)
        combo_row = QHBoxLayout()
        self._cfg_combo = QComboBox()
        self._cfg_combo.setMinimumWidth(200)
        self._refresh_cfg_btn = QPushButton("↺")
        self._refresh_cfg_btn.setFixedWidth(28)
        self._refresh_cfg_btn.setToolTip("Reload configuration list")
        self._refresh_cfg_btn.clicked.connect(self.refresh_configs)
        combo_row.addWidget(self._cfg_combo, 1)
        combo_row.addWidget(self._refresh_cfg_btn)
        cf.addRow("Config:", combo_row)
        top.addWidget(cfg_grp, 2)

        part_grp  = QGroupBox("Participant")
        pf        = QFormLayout(part_grp)
        self._pid_edit = QLineEdit()
        self._pid_edit.setPlaceholderText("Participant ID or name")
        pf.addRow("ID:", self._pid_edit)
        top.addWidget(part_grp, 1)

        cue_grp  = QGroupBox("Auditory Cues")
        cu       = QVBoxLayout(cue_grp)
        self._countdown_chk = QCheckBox("Countdown beep before start")
        self._countdown_chk.setChecked(True)
        self._tone_chk = QCheckBox("Tone on pad light-up")
        self._tone_chk.setChecked(False)
        if not self._audio.available:
            for chk in (self._countdown_chk, self._tone_chk):
                chk.setEnabled(False)
                chk.setToolTip("No audio backend detected on this system")
        cu.addWidget(self._countdown_chk)
        cu.addWidget(self._tone_chk)
        top.addWidget(cue_grp, 1)

        root.addLayout(top)

        # ---- Action buttons --------------------------------------------
        btn_row = QHBoxLayout()
        self._orient_btn = QPushButton("🔍  Check Orientation")
        self._orient_btn.setToolTip(
            "Light pad #1 on each panel to verify orientation and wiring")
        self._orient_btn.clicked.connect(self._check_orientation)
        btn_row.addWidget(self._orient_btn)
        btn_row.addStretch()

        self._start_btn = QPushButton("▶  Start Test")
        self._start_btn.setStyleSheet(
            "QPushButton{background:#43A047;color:white;font-size:14px;"
            "font-weight:bold;padding:10px 28px;border-radius:6px;}"
            "QPushButton:hover{background:#2E7D32;}"
            "QPushButton:disabled{background:#BDBDBD;}")
        self._start_btn.clicked.connect(self._start_test)
        btn_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("⏹  Cancel")
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#E53935;color:white;font-size:14px;"
            "font-weight:bold;padding:10px 28px;border-radius:6px;}"
            "QPushButton:hover{background:#B71C1C;}"
            "QPushButton:disabled{background:#BDBDBD;}")
        self._cancel_btn.clicked.connect(self._cancel_test)
        self._cancel_btn.setEnabled(False)
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

        # ---- Progress --------------------------------------------------
        prog_grp = QGroupBox("Progress")
        pv       = QVBoxLayout(prog_grp)
        self._phase_lbl = QLabel("Ready")
        self._phase_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont(); f.setPointSize(13); self._phase_lbl.setFont(f)
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("%v / %m")
        pv.addWidget(self._phase_lbl)
        pv.addWidget(self._progress_bar)
        root.addWidget(prog_grp)

        # ---- Live grid area --------------------------------------------
        self._grid_grp = QGroupBox("Live Pad Grid")
        self._grid_row = QHBoxLayout(self._grid_grp)
        root.addWidget(self._grid_grp, 1)

        # ---- Trial log -------------------------------------------------
        log_grp = QGroupBox("Trial Log  (last 10)")
        lv      = QVBoxLayout(log_grp)
        self._log_lbl = QLabel("—")
        self._log_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._log_lbl.setWordWrap(True)
        self._log_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._log_lbl.setStyleSheet("font-family:monospace; font-size:11px;")
        self._log_lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                                    QSizePolicy.Policy.Minimum)
        lv.addWidget(self._log_lbl)
        root.addWidget(log_grp)

        self.refresh_configs()

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    def refresh_configs(self) -> None:
        """Reload the configuration combo from storage."""
        current_id = (self._cfg_combo.currentData().id
                      if self._cfg_combo.currentData() else None)
        self._cfg_combo.clear()
        for cfg in self._storage.list_configs():
            self._cfg_combo.addItem(cfg.name, cfg)
        # Try to restore previous selection
        if current_id:
            for i in range(self._cfg_combo.count()):
                if self._cfg_combo.itemData(i).id == current_id:
                    self._cfg_combo.setCurrentIndex(i)
                    break

    def _selected_config(self) -> Optional[TestConfiguration]:
        return self._cfg_combo.currentData()

    # ------------------------------------------------------------------
    # Grid management
    # ------------------------------------------------------------------

    def _build_grids(self, num_panels: int) -> None:
        for grp in self._grid_groups:
            self._grid_row.removeWidget(grp)
            grp.deleteLater()
        self._grid_groups.clear()
        self._pad_grids.clear()

        for i in range(num_panels):
            grid = PadGridWidget(panel_index=i)
            grp  = QGroupBox(f"Panel {i + 1}")
            gv   = QVBoxLayout(grp)
            gv.addWidget(grid)
            self._pad_grids.append(grid)
            self._grid_groups.append(grp)
            self._grid_row.addWidget(grp)

    # ------------------------------------------------------------------
    # Orientation check
    # ------------------------------------------------------------------

    def _check_orientation(self) -> None:
        if not self._serial.is_connected:
            QMessageBox.warning(self, "Not Connected",
                                "Connect to the Arduino first.")
            return
        cfg = self._selected_config()
        n   = cfg.num_panels if cfg else 1
        for panel in range(n):
            self._serial.send_orient_on()
        self._phase_lbl.setText(
            f"Orientation check — pad #1 lit on {n} panel(s)")

    # ------------------------------------------------------------------
    # Test start / cancel
    # ------------------------------------------------------------------

    def _start_test(self) -> None:
        cfg = self._selected_config()
        if cfg is None:
            QMessageBox.warning(self, "No Configuration",
                "Create and select a configuration before starting.")
            return
        if not self._serial.is_connected:
            QMessageBox.warning(self, "Not Connected",
                "Connect to the Arduino before starting a test.")
            return

        issues = cfg.validate()
        if issues:
            QMessageBox.warning(self, "Invalid Configuration",
                "Fix these issues before starting:\n\n" +
                "\n".join(f"• {i}" for i in issues))
            return

        pid = self._pid_edit.text().strip() or "anonymous"

        # Reset UI
        self._build_grids(cfg.num_panels)
        self._trial_log_lines.clear()
        self._log_lbl.setText("—")
        self._progress_bar.setValue(0)
        self._progress_bar.setMaximum(cfg.num_trials)
        self._phase_lbl.setText("Starting…")

        if self._countdown_chk.isChecked():
            self._audio.play_countdown()

        # Create runner and thread
        self._runner = TestRunner(self._serial, cfg, pid)
        self._thread = QThread(self)
        self._runner.moveToThread(self._thread)

        self._thread.started.connect(self._runner.run)
        self._runner.warmup_started.connect(
            lambda: self._phase_lbl.setText("⚙  Warm-up trials…"))
        self._runner.scored_started.connect(
            lambda: self._phase_lbl.setText("▶  Scored trials running…"))
        self._runner.rest_prompt.connect(self._on_rest_prompt)
        self._runner.trial_started.connect(self._on_trial_started)
        self._runner.trial_completed.connect(self._on_trial_completed)
        self._runner.progress_updated.connect(self._on_progress)
        self._runner.test_finished.connect(self._on_test_finished)
        self._runner.test_cancelled.connect(self._on_test_cancelled)

        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._thread.start()
        logger.info("Test started — participant=%r config=%r", pid, cfg.name)

    def _cancel_test(self) -> None:
        if self._runner:
            self._runner.cancel()
        self._cancel_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Runner signal slots
    # ------------------------------------------------------------------

    @pyqtSlot(int)
    def _on_rest_prompt(self, duration_ms: int) -> None:
        self._phase_lbl.setText(f"😴  Rest break — {duration_ms // 1000}s…")
        self._audio.play_rest()

    @pyqtSlot(int, int, int, bool)
    def _on_trial_started(
        self, panel: int, pad: int, color: int, expect: bool
    ) -> None:
        # Clear all grids then light the target pad
        for g in self._pad_grids:
            g.clear_all()
        if panel < len(self._pad_grids):
            self._pad_grids[panel].light_pad(pad, color)
        if self._tone_chk.isChecked():
            self._audio.play_stimulus()

    @pyqtSlot(object)
    def _on_trial_completed(self, trial: TrialResult) -> None:
        # Clear the pad that just finished
        if trial.panel < len(self._pad_grids):
            self._pad_grids[trial.panel].clear_pad(trial.pad)

        # Build log entry
        outcome = (
            "✓ hit"   if trial.is_hit else
            "✗ miss"  if trial.is_omission_error else
            "✗ FA"    if trial.is_commission_error else
            "✓ CR"
        )
        prefix = "[W]" if trial.is_warmup else f" {trial.trial_num:3d}"
        entry  = (
            f"{prefix}  P{trial.panel+1}/#{trial.pad+1}"
            f"  {'expect' if trial.expect_touch else 'no-touch':9s}"
            f"  {trial.reaction_time_ms:5d}ms  {outcome}"
        )
        self._trial_log_lines.append(entry)
        if len(self._trial_log_lines) > 10:
            self._trial_log_lines.pop(0)
        self._log_lbl.setText("\n".join(self._trial_log_lines))

    @pyqtSlot(int, int)
    def _on_progress(self, current: int, total: int) -> None:
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._phase_lbl.setText(f"▶  Trial {current} of {total}")

    @pyqtSlot(object)
    def _on_test_finished(self, session: SessionResult) -> None:
        self._teardown_thread()
        self._phase_lbl.setText("✅  Test complete!")
        for g in self._pad_grids:
            g.clear_all()
        self._audio.play_test_end()

        try:
            self._storage.save_session(session)
        except Exception as exc:
            logger.error("Failed to save session: %s", exc)
            QMessageBox.warning(self, "Save Error",
                                f"Could not save session:\n{exc}")
        self.session_saved.emit(session)
        logger.info("Session saved — %d trials", len(session.trials))

    @pyqtSlot()
    def _on_test_cancelled(self) -> None:
        self._teardown_thread()
        self._phase_lbl.setText("⏹  Cancelled")
        for g in self._pad_grids:
            g.clear_all()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _teardown_thread(self) -> None:
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._runner = None
        self._thread = None
