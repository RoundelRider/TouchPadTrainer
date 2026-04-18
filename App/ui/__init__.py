"""
ui — PyQt6 widget layer for the TouchPad Test Program.

All widgets are thin presentation shells.  Business logic lives in
core/ and data/; widgets only translate Qt events into core calls and
core signals into visual updates.

Public widgets
--------------
MainWindow          — top-level QMainWindow
ConnectionBar       — serial port selector toolbar
PadGridWidget       — interactive 4×4 pad grid
ConfigEditorWidget  — configuration CRUD editor
TestPanelWidget     — run-test tab with live grid and trial log
ResultsViewWidget   — statistics, heatmap and session comparison
SessionHistoryWidget— past-session browser
CalibrationWidget   — calibration and diagnostics tab
SettingsDialog      — application preferences dialog
"""

from ui.pad_grid          import PadGridWidget, PadCell
from ui.connection_bar    import ConnectionBar
from ui.config_editor     import ConfigEditorWidget
from ui.test_panel        import TestPanelWidget
from ui.results_view      import ResultsViewWidget
from ui.session_history   import SessionHistoryWidget
from ui.calibration       import CalibrationWidget
from ui.settings_dialog   import SettingsDialog
from ui.main_window       import MainWindow

__all__ = [
    "MainWindow",
    "ConnectionBar",
    "PadGridWidget",
    "PadCell",
    "ConfigEditorWidget",
    "TestPanelWidget",
    "ResultsViewWidget",
    "SessionHistoryWidget",
    "CalibrationWidget",
    "SettingsDialog",
]
