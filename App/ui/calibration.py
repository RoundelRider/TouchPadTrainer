"""
ui.calibration
~~~~~~~~~~~~~~
"Calibration" tab.

Sections
--------
Orientation Check   : light pad #1 on any panel / turn all LEDs off
Pad Calibration     : trigger baseline-capture routine per pad
Latency Test        : measure round-trip serial latency
Diagnostic Log      : scrolling log of all activity on this tab
"""

from __future__ import annotations

import time
import logging
from typing import Optional

from PyQt6.QtCore    import Qt, pyqtSlot
from PyQt6.QtGui     import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QPushButton, QSpinBox,
    QTextEdit, QSizePolicy,
)

from core.serial_manager import SerialManager
from data.models         import CalibrationProfile
from data.storage        import StorageManager

logger = logging.getLogger(__name__)


class CalibrationWidget(QWidget):
    """Calibration and diagnostics tab."""

    def __init__(
        self,
        serial:  SerialManager,
        storage: StorageManager,
        parent:  QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._serial    = serial
        self._storage   = storage
        self._lat_start: Optional[float] = None
        self._setup_ui()
        self._serial.response_received.connect(self._on_response)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- Orientation check -----------------------------------------
        orient_grp = QGroupBox("Orientation Check")
        ov         = QHBoxLayout(orient_grp)
        ov.addWidget(QLabel("Panel:"))
        self._orient_panel_spin = QSpinBox()
        self._orient_panel_spin.setRange(1, 4)
        self._orient_panel_spin.setFixedWidth(60)
        ov.addWidget(self._orient_panel_spin)

        self._orient_on_btn  = QPushButton("💡  Light Pad #1")
        self._orient_off_btn = QPushButton("🌑  All LEDs Off")
        self._orient_on_btn.clicked.connect(self._orient_on)
        self._orient_off_btn.clicked.connect(self._orient_off)
        ov.addWidget(self._orient_on_btn)
        ov.addWidget(self._orient_off_btn)
        ov.addStretch()
        root.addWidget(orient_grp)

        # ---- Pad calibration -------------------------------------------
        cal_grp = QGroupBox("Pad Sensitivity Calibration")
        cf      = QFormLayout(cal_grp)
        self._cal_panel_spin = QSpinBox()
        self._cal_panel_spin.setRange(1, 4)
        self._cal_pad_spin   = QSpinBox()
        self._cal_pad_spin.setRange(1, 16)
        self._cal_btn = QPushButton("▶  Calibrate this Pad")
        self._cal_btn.clicked.connect(self._calibrate)
        cf.addRow("Panel:", self._cal_panel_spin)
        cf.addRow("Pad:",   self._cal_pad_spin)
        cf.addRow("",       self._cal_btn)

        note = QLabel(
            "Sends a calibration command to the Arduino to capture "
            "the capacitive baseline for the selected pad.  "
            "Ensure no fingers are touching the pad before running.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#78909C; font-size:10px;")
        cf.addRow(note)
        root.addWidget(cal_grp)

        # ---- Latency test ----------------------------------------------
        lat_grp = QGroupBox("Round-Trip Latency Test")
        lv      = QVBoxLayout(lat_grp)
        lat_btn_row = QHBoxLayout()
        self._lat_btn = QPushButton("⏱  Measure Latency")
        self._lat_btn.clicked.connect(self._measure_latency)
        self._lat_result = QLabel("Result: —")
        f = QFont(); f.setPointSize(12); f.setBold(True)
        self._lat_result.setFont(f)
        lat_btn_row.addWidget(self._lat_btn)
        lat_btn_row.addWidget(self._lat_result)
        lat_btn_row.addStretch()
        lv.addLayout(lat_btn_row)
        lv.addWidget(QLabel(
            "Measures the time between sending a ping command and receiving "
            "the Arduino's response.  This represents the minimum possible "
            "RT measurement overhead for this hardware setup.",
            wordWrap=True,
        ))
        root.addWidget(lat_grp)

        # ---- Diagnostic log --------------------------------------------
        log_grp = QGroupBox("Diagnostic Log")
        dgv     = QVBoxLayout(log_grp)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(160)
        self._log.setStyleSheet("font-family:monospace; font-size:11px;")
        clear_btn = QPushButton("Clear log")
        clear_btn.setFixedWidth(90)
        clear_btn.clicked.connect(self._log.clear)
        dgv.addWidget(self._log)
        dgv.addWidget(clear_btn, 0, Qt.AlignmentFlag.AlignRight)
        root.addWidget(log_grp)

        root.addStretch()

    # ------------------------------------------------------------------
    # Slots / actions
    # ------------------------------------------------------------------

    def _orient_on(self) -> None:
        if not self._check_connected():
            return
        panel = self._orient_panel_spin.value() - 1
        self._serial.send_orient_on(panel)
        self._log_line(f"Orientation ON — Panel {panel + 1}, pad #1 lit")

    def _orient_off(self) -> None:
        if not self._check_connected():
            return
        self._serial.send_orient_off()
        self._log_line("All LEDs turned off")

    def _calibrate(self) -> None:
        if not self._check_connected():
            return
        panel = self._cal_panel_spin.value() - 1
        pad   = self._cal_pad_spin.value()   - 1
        self._serial.send_calibrate(panel, pad)
        self._log_line(
            f"Calibration command sent — Panel {panel + 1}, Pad {pad + 1}")

    def _measure_latency(self) -> None:
        if not self._check_connected():
            return
        self._lat_start = time.monotonic()
        self._serial.send_latency_test()
        self._log_line("Latency ping sent…")
        self._lat_result.setText("Result: measuring…")

    @pyqtSlot(object)
    def _on_response(self, response) -> None:
        """Catch the next response after a latency ping."""
        if self._lat_start is not None:
            elapsed_ms = int((time.monotonic() - self._lat_start) * 1000)
            self._lat_result.setText(f"Result: {elapsed_ms} ms round-trip")
            self._log_line(f"Latency result: {elapsed_ms} ms")
            self._lat_start = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_connected(self) -> bool:
        if not self._serial.is_connected:
            self._log_line("ERROR: Not connected to Arduino")
            return False
        return True

    def _log_line(self, text: str) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(f"[{ts}]  {text}")
        logger.debug("Calibration tab: %s", text)
