"""
ui.connection_bar
~~~~~~~~~~~~~~~~~
Toolbar that lives at the top of the main window.

Controls
--------
Port combo      : lists available serial ports
Refresh button  : re-scans for ports
Baud combo      : selects baud rate (default 115 200)
Connect button  : toggles connect / disconnect
Status dot + label : persistent "Connected / Disconnected / Error" indicator
Firmware label  : shows firmware version string after connect
"""

from __future__ import annotations

from PyQt6.QtCore    import Qt, pyqtSlot
from PyQt6.QtGui     import QFont
from PyQt6.QtWidgets import (
    QToolBar, QLabel, QComboBox, QPushButton,
    QWidget, QSizePolicy,
)

from core.serial_manager import SerialManager


# Colour scheme for the three connection states
_STATE_STYLES: dict[str, tuple[str, str]] = {
    #              dot-colour  label-colour
    "Connected":    ("#43A047", "#2E7D32"),
    "Disconnected": ("#9E9E9E", "#616161"),
    "Error":        ("#E53935", "#B71C1C"),
}

_CONNECT_BTN_STYLE = (
    "QPushButton {{ background:{bg}; color:white; padding:5px 14px; "
    "border-radius:4px; font-weight:bold; }}"
    "QPushButton:hover {{ background:{hover}; }}"
)


class ConnectionBar(QToolBar):
    """Serial port connection toolbar."""

    def __init__(self, serial: SerialManager,
                 parent: QWidget | None = None) -> None:
        super().__init__("Connection", parent)
        self._serial     = serial
        self._connected  = False
        self._build_ui()
        self._connect_signals()
        self.refresh_ports()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setMovable(False)
        self.setFloatable(False)

        # Port selector
        self.addWidget(QLabel(" Port: "))
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(140)
        self._port_combo.setToolTip("Available serial ports")
        self.addWidget(self._port_combo)

        self._refresh_btn = QPushButton("↺")
        self._refresh_btn.setFixedWidth(28)
        self._refresh_btn.setToolTip("Re-scan for serial ports")
        self._refresh_btn.clicked.connect(self.refresh_ports)
        self.addWidget(self._refresh_btn)

        self.addSeparator()

        # Baud rate
        self.addWidget(QLabel(" Baud: "))
        self._baud_combo = QComboBox()
        for rate in (9600, 19200, 57600, 115200):
            self._baud_combo.addItem(str(rate), rate)
        self._baud_combo.setCurrentText("115200")
        self.addWidget(self._baud_combo)

        self.addSeparator()

        # Connect / Disconnect button
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setMinimumWidth(110)
        self._connect_btn.clicked.connect(self._toggle_connection)
        self._style_connect_btn(connected=False)
        self.addWidget(self._connect_btn)

        self.addSeparator()

        # Status indicator
        self._dot   = QLabel("●")
        self._dot.setFixedWidth(18)
        font = QFont()
        font.setPointSize(14)
        self._dot.setFont(font)
        self._state_label = QLabel("Disconnected")
        bold = QFont()
        bold.setBold(True)
        self._state_label.setFont(bold)
        self.addWidget(self._dot)
        self.addWidget(self._state_label)

        # Push firmware label to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

        self._fw_label = QLabel("")
        self._fw_label.setStyleSheet("color:#78909C; font-size:10px;")
        self.addWidget(self._fw_label)

        # Apply initial style
        self._apply_state("Disconnected")

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._serial.status_changed.connect(self._apply_state)
        self._serial.connected.connect(self._on_connected)
        self._serial.disconnected.connect(self._on_disconnected)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot()
    def refresh_ports(self) -> None:
        """Re-scan available serial ports and repopulate the combo."""
        current = self._port_combo.currentText()
        self._port_combo.clear()
        ports = SerialManager.list_ports()
        for p in ports:
            self._port_combo.addItem(p)
        if current in ports:
            self._port_combo.setCurrentText(current)

    @pyqtSlot()
    def _toggle_connection(self) -> None:
        if self._connected:
            self._serial.disconnect()
        else:
            port = self._port_combo.currentText()
            if not port:
                return
            baud = int(self._baud_combo.currentData())
            self._serial.connect(port, baudrate=baud)

    @pyqtSlot(str)
    def _apply_state(self, state: str) -> None:
        dot_color, label_color = _STATE_STYLES.get(
            state, ("#9E9E9E", "#616161"))
        self._dot.setStyleSheet(
            f"color:{dot_color}; font-size:14px;")
        self._state_label.setText(state)
        self._state_label.setStyleSheet(
            f"font-weight:bold; color:{label_color};")

    @pyqtSlot(str, str)
    def _on_connected(self, port: str, firmware: str) -> None:
        self._connected = True
        self._style_connect_btn(connected=True)
        self._fw_label.setText(f"  Firmware: {firmware}  ")

    @pyqtSlot(str)
    def _on_disconnected(self, _reason: str) -> None:
        self._connected = False
        self._style_connect_btn(connected=False)
        self._fw_label.setText("")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _style_connect_btn(self, connected: bool) -> None:
        if connected:
            self._connect_btn.setText("Disconnect")
            self._connect_btn.setStyleSheet(
                _CONNECT_BTN_STYLE.format(bg="#E53935", hover="#B71C1C"))
        else:
            self._connect_btn.setText("Connect")
            self._connect_btn.setStyleSheet(
                _CONNECT_BTN_STYLE.format(bg="#43A047", hover="#2E7D32"))
