"""
ui.settings_dialog
~~~~~~~~~~~~~~~~~~
Application preferences dialog.

Settings
--------
Serial        : response timeout
Appearance    : font size, high-contrast mode
Updates       : check for updates on launch
"""

from __future__ import annotations

from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QColor, QPalette, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QGroupBox,
    QSpinBox, QCheckBox, QDialogButtonBox,
    QApplication, QLabel, QComboBox,
)

from core.serial_manager import SerialManager


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, serial: SerialManager,
                 parent=None) -> None:
        super().__init__(parent)
        self._serial = serial
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self.setModal(True)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ---- Serial settings ------------------------------------------
        serial_grp = QGroupBox("Serial Communication")
        sf         = QFormLayout(serial_grp)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(500, 30_000)
        self._timeout_spin.setSuffix(" ms")
        self._timeout_spin.setValue(self._serial._timeout_ms)
        self._timeout_spin.setToolTip(
            "Maximum time to wait for an Arduino response frame before "
            "declaring a timeout.  Increase if using long USB cables.")
        sf.addRow("Response timeout:", self._timeout_spin)

        note = QLabel(
            "Changes take effect immediately for the next command sent.")
        note.setStyleSheet("color:#78909C; font-size:10px;")
        sf.addRow(note)
        root.addWidget(serial_grp)

        # ---- Appearance settings --------------------------------------
        appear_grp = QGroupBox("Appearance")
        af         = QFormLayout(appear_grp)

        self._font_combo = QComboBox()
        for label, size in (("Small (10pt)", 10),
                             ("Medium (11pt — default)", 11),
                             ("Large (13pt)", 13),
                             ("Extra large (15pt)", 15)):
            self._font_combo.addItem(label, size)
        # Pre-select current size
        current_size = QApplication.font().pointSize()
        for i in range(self._font_combo.count()):
            if self._font_combo.itemData(i) == current_size:
                self._font_combo.setCurrentIndex(i)
                break
        af.addRow("Font size:", self._font_combo)

        self._hc_chk = QCheckBox("High-contrast mode")
        self._hc_chk.setToolTip(
            "Black background with bright yellow text — "
            "useful in bright gyms or outdoor settings")
        af.addRow(self._hc_chk)
        root.addWidget(appear_grp)

        # ---- Update settings ------------------------------------------
        update_grp = QGroupBox("Software Updates")
        uv         = QVBoxLayout(update_grp)
        self._update_chk = QCheckBox("Check for updates on launch")
        self._update_chk.setChecked(True)
        uv.addWidget(self._update_chk)
        root.addWidget(update_grp)

        # ---- Buttons --------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _apply(self) -> None:
        # Serial
        self._serial.set_timeout(self._timeout_spin.value())

        # Font size
        size = self._font_combo.currentData()
        if size:
            font = QApplication.font()
            font.setPointSize(size)
            QApplication.setFont(font)

        # High-contrast mode
        if self._hc_chk.isChecked():
            _apply_high_contrast()
        else:
            QApplication.setPalette(
                QApplication.style().standardPalette())

        self.accept()


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _apply_high_contrast() -> None:
    """Switch the application palette to a high-contrast black/yellow theme."""
    pal = QPalette()
    BLACK  = QColor(0,   0,   0)
    YELLOW = QColor(255, 255, 0)
    DARK   = QColor(30,  30,  30)
    GREY   = QColor(80,  80,  80)

    pal.setColor(QPalette.ColorRole.Window,          BLACK)
    pal.setColor(QPalette.ColorRole.WindowText,      YELLOW)
    pal.setColor(QPalette.ColorRole.Base,            BLACK)
    pal.setColor(QPalette.ColorRole.AlternateBase,   DARK)
    pal.setColor(QPalette.ColorRole.Text,            YELLOW)
    pal.setColor(QPalette.ColorRole.Button,          DARK)
    pal.setColor(QPalette.ColorRole.ButtonText,      YELLOW)
    pal.setColor(QPalette.ColorRole.Highlight,       YELLOW)
    pal.setColor(QPalette.ColorRole.HighlightedText, BLACK)
    pal.setColor(QPalette.ColorRole.ToolTipBase,     DARK)
    pal.setColor(QPalette.ColorRole.ToolTipText,     YELLOW)
    pal.setColor(QPalette.ColorRole.PlaceholderText, GREY)

    QApplication.setPalette(pal)
