"""
ui.main_window
~~~~~~~~~~~~~~
Top-level application window.

Structure
---------
  ┌─────────────────────────────────────────────────┐
  │  ConnectionBar  (toolbar)                        │
  ├─────────────────────────────────────────────────┤
  │  QTabWidget                                      │
  │   ⚙ Configuration   ConfigEditorWidget           │
  │   ▶ Run Test        TestPanelWidget              │
  │   📊 Results        ResultsViewWidget            │
  │   🕒 History        SessionHistoryWidget         │
  │   🔧 Calibration    CalibrationWidget            │
  ├─────────────────────────────────────────────────┤
  │  Status bar                                      │
  └─────────────────────────────────────────────────┘

Signal flow
-----------
TestPanelWidget.session_saved
    → ResultsViewWidget.load_session   (switch to Results tab)
    → SessionHistoryWidget.refresh

SessionHistoryWidget.session_selected
    → ResultsViewWidget.load_session   (switch to Results tab)

ConfigEditorWidget.config_saved
    → TestPanelWidget.refresh_configs
"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtCore    import Qt, pyqtSlot
from PyQt6.QtGui     import QIcon, QAction
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget,
    QLabel, QMessageBox, QApplication,
)

from core.serial_manager import SerialManager
from data.storage        import StorageManager
from data.models         import SessionResult

from ui.connection_bar  import ConnectionBar
from ui.config_editor   import ConfigEditorWidget
from ui.test_panel      import TestPanelWidget
from ui.results_view    import ResultsViewWidget
from ui.session_history import SessionHistoryWidget
from ui.calibration     import CalibrationWidget
from ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

_APP_STYLESHEET = """
QMainWindow, QDialog {
    background: #F5F5F5;
}
QTabWidget::pane {
    border: 1px solid #BDBDBD;
    background: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    padding: 8px 18px;
    font-size: 12px;
    border: 1px solid #BDBDBD;
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    background: #EEEEEE;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    font-weight: bold;
    border-bottom: 1px solid #FFFFFF;
}
QGroupBox {
    font-weight: bold;
    margin-top: 10px;
    padding-top: 4px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QPushButton {
    padding: 5px 12px;
    border-radius: 4px;
    border: 1px solid #BDBDBD;
    background: #FAFAFA;
}
QPushButton:hover  { background: #E3F2FD; border-color: #90CAF9; }
QPushButton:pressed { background: #BBDEFB; }
QPushButton:disabled { color: #9E9E9E; background: #F5F5F5; }
QToolBar { spacing: 4px; padding: 4px; background: #ECEFF1; border-bottom: 1px solid #CFD8DC; }
QToolBar QLabel { padding: 0 2px; }
QStatusBar { font-size: 11px; }
QTableWidget { gridline-color: #E0E0E0; }
QHeaderView::section { background: #F5F5F5; padding: 4px; border: none; border-bottom: 1px solid #BDBDBD; font-weight: bold; }
"""


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self) -> None:
        super().__init__()
        self.serial  = SerialManager(self)
        self.storage = StorageManager()
        self._build_ui()
        self._connect_signals()
        self._apply_styles()
        self._set_window_icon()
        logger.info("MainWindow created")

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("TouchPad Test Program")
        self.resize(1280, 840)
        self.setMinimumSize(900, 600)

        # Connection toolbar
        self._conn_bar = ConnectionBar(self.serial, self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._conn_bar)

        # Tab widget
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._cfg_tab  = ConfigEditorWidget(self.storage, self)
        self._test_tab = TestPanelWidget(self.serial, self.storage, self)
        self._res_tab  = ResultsViewWidget(self.storage, self)
        self._hist_tab = SessionHistoryWidget(self.storage, self)
        self._cal_tab  = CalibrationWidget(self.serial, self.storage, self)

        self._tabs.addTab(self._cfg_tab,  "⚙  Configuration")
        self._tabs.addTab(self._test_tab, "▶  Run Test")
        self._tabs.addTab(self._res_tab,  "📊  Results")
        self._tabs.addTab(self._hist_tab, "🕒  History")
        self._tabs.addTab(self._cal_tab,  "🔧  Calibration")

        # Status bar
        self._serial_status = QLabel("Serial: Disconnected")
        self._serial_status.setStyleSheet("font-weight:bold; color:#616161;")
        self.statusBar().addPermanentWidget(self._serial_status)

        self._build_menu()

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")

        act_settings = QAction("&Settings…", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)

        act_export_summary = QAction("Export Session Summary CSV…", self)
        act_export_summary.triggered.connect(self._export_summary)
        file_menu.addAction(act_export_summary)

        file_menu.addSeparator()

        act_quit = QAction("&Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # View
        view_menu = mb.addMenu("&View")

        for label, size in (("Small font",    10),
                             ("Medium font",   11),
                             ("Large font",    13),
                             ("X-Large font",  15)):
            act = QAction(label, self)
            act.triggered.connect(
                lambda _, s=size: self._set_font_size(s))
            view_menu.addAction(act)

        view_menu.addSeparator()

        act_hc = QAction("High Contrast Mode", self)
        act_hc.setCheckable(True)
        act_hc.toggled.connect(self._toggle_high_contrast)
        view_menu.addAction(act_hc)

        # Help
        help_menu = mb.addMenu("&Help")
        act_about = QAction("&About…", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.serial.status_changed.connect(self._on_serial_status)
        self.serial.error_occurred.connect(self._on_serial_error)
        self.serial.firmware_warning.connect(self._on_firmware_warning)

        self._test_tab.session_saved.connect(self._on_session_saved)
        self._hist_tab.session_selected.connect(self._on_history_session_selected)
        self._cfg_tab.config_saved.connect(
            lambda _cfg: self._test_tab.refresh_configs())

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def _on_serial_status(self, status: str) -> None:
        color = {"Connected":    "#2E7D32",
                 "Disconnected": "#616161",
                 "Error":        "#B71C1C"}.get(status, "#616161")
        self._serial_status.setText(f"Serial: {status}")
        self._serial_status.setStyleSheet(
            f"font-weight:bold; color:{color};")

    @pyqtSlot(str)
    def _on_serial_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"Serial error: {msg}", 6000)
        logger.warning("Serial error: %s", msg)

    @pyqtSlot(str)
    def _on_firmware_warning(self, msg: str) -> None:
        QMessageBox.warning(self, "Firmware Version Warning", msg)

    @pyqtSlot(object)
    def _on_session_saved(self, session: SessionResult) -> None:
        self._res_tab.load_session(session)
        self._hist_tab.refresh()
        self._tabs.setCurrentWidget(self._res_tab)

    @pyqtSlot(object)
    def _on_history_session_selected(self, session: SessionResult) -> None:
        self._res_tab.load_session(session)
        self._tabs.setCurrentWidget(self._res_tab)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.serial, self)
        dlg.exec()

    def _export_summary(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Session Summary CSV",
            "sessions_summary.csv", "CSV Files (*.csv)")
        if not path:
            return
        try:
            self.storage.export_sessions_summary_csv(Path(path))
            self.statusBar().showMessage(f"Exported to {path}", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    def _set_font_size(self, size: int) -> None:
        font = QApplication.font()
        font.setPointSize(size)
        QApplication.setFont(font)

    def _toggle_high_contrast(self, enabled: bool) -> None:
        if enabled:
            from ui.settings_dialog import _apply_high_contrast
            _apply_high_contrast()
        else:
            QApplication.setPalette(
                QApplication.style().standardPalette())

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About TouchPad Test Program",
            "<b>TouchPad Test Program</b> v1.0.0<br><br>"
            "Capacitive touch-pad reaction-time testing<br>"
            "for clinical, sports-science, and research use.<br><br>"
            "Python 3.11+ · PyQt6 · PySerial<br><br>"
            "© 2025  TouchPad Program",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_styles(self) -> None:
        self.setStyleSheet(_APP_STYLESHEET)

    def _set_window_icon(self) -> None:
        try:
            from assets import icon_path_or_none
            p = icon_path_or_none("app_icon.png")
            if p:
                self.setWindowIcon(QIcon(str(p)))
        except Exception:
            pass   # icon is cosmetic — never crash on missing asset

    def closeEvent(self, event) -> None:
        if self.serial.is_connected:
            self.serial.disconnect()
        logger.info("Application closing")
        event.accept()
