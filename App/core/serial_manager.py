"""
core.serial_manager
~~~~~~~~~~~~~~~~~~~
Manages the serial connection to the Arduino controller.

Responsibilities:
  - Port discovery (Windows COM / macOS+Linux /dev/tty*)
  - Opening / closing the port with a clean reconnect path
  - Enqueueing outgoing commands so callers never block
  - Worker thread that drains the queue, writes bytes, and reads the
    fixed-length response frame
  - Firmware version query and compatibility check on connect
  - Qt signals for every observable state change so the UI can react
    without polling

No UI code lives here.  Qt is used only for QObject/pyqtSignal so that
signals cross the thread boundary safely.
"""

from __future__ import annotations

import queue
import threading
import time
import logging
from typing import Optional

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

# Command codes (PC → Arduino)
CMD_ORIENT_ON    = 0x01
CMD_ORIENT_OFF   = 0x02
CMD_TEST_START   = 0x03
CMD_TEST_END     = 0x04
CMD_SINGLE_TOUCH = 0x05
CMD_DUAL_TOUCH   = 0x06
CMD_VERSION      = 0x07
CMD_CALIBRATE    = 0x08
CMD_LATENCY      = 0x09

# LED colour codes used in command payloads
COLOR_WHITE = 0
COLOR_GREEN = 1
COLOR_RED   = 2

# Response status byte values
ACK = 0xAA
NAK = 0xFF

# Response frame length (bytes)
_FRAME_LEN = 6


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

class ArduinoResponse:
    """
    Parsed response frame from the Arduino.

    Frame layout: [ status, panel, pad, touched, rt_hi, rt_lo ]

    Attributes
    ----------
    panel           : 0-based panel index
    pad             : 0-based pad index within the panel
    touched         : True if a touch was recorded
    response_time_ms: reaction time in milliseconds (timeout value when no touch)
    error           : non-empty string when status == NAK or a timeout occurred
    is_nak          : True when the Arduino explicitly returned NAK
    is_timeout      : True when the host timed out waiting for a frame
    """

    __slots__ = ("panel", "pad", "touched", "response_time_ms",
                 "error", "is_nak", "is_timeout")

    def __init__(
        self,
        panel: int,
        pad: int,
        touched: bool,
        response_time_ms: int,
        error: str = "",
        is_nak: bool = False,
        is_timeout: bool = False,
    ) -> None:
        self.panel            = panel
        self.pad              = pad
        self.touched          = touched
        self.response_time_ms = response_time_ms
        self.error            = error
        self.is_nak           = is_nak
        self.is_timeout       = is_timeout

    @property
    def ok(self) -> bool:
        """True when the response represents a successful exchange."""
        return not self.error

    def __repr__(self) -> str:
        status = "NAK" if self.is_nak else ("TIMEOUT" if self.is_timeout else "ACK")
        return (
            f"ArduinoResponse({status} panel={self.panel} pad={self.pad} "
            f"touched={self.touched} rt={self.response_time_ms}ms)"
        )


# ---------------------------------------------------------------------------
# Serial manager
# ---------------------------------------------------------------------------

class SerialManager(QObject):
    """
    Thread-safe serial port manager for the Arduino controller.

    Usage
    -----
    >>> mgr = SerialManager()
    >>> mgr.status_changed.connect(on_status)
    >>> mgr.response_received.connect(on_response)
    >>> mgr.connect("COM3")
    >>> mgr.send_single_touch(panel=0, pad=5, color=COLOR_GREEN,
    ...                       expect_touch=True, timeout_ms=2000)
    >>> # … response arrives via response_received signal …
    >>> mgr.disconnect()

    All public send_* methods are non-blocking: they place the command on
    an internal queue and return immediately.  The worker thread processes
    one command at a time and emits response_received for each.
    """

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    #: Emitted when the port opens successfully.  Args: port name, firmware version.
    connected = pyqtSignal(str, str)

    #: Emitted when the port closes (user-initiated or error).  Arg: reason string.
    disconnected = pyqtSignal(str)

    #: Emitted for every parsed Arduino response frame.
    response_received = pyqtSignal(object)   # ArduinoResponse

    #: Non-fatal error message (e.g. queue full, NAK received).
    error_occurred = pyqtSignal(str)

    #: Persistent connection state: "Connected" | "Disconnected" | "Error"
    status_changed = pyqtSignal(str)

    #: Emitted when the firmware major version does not match APP_VERSION[0].
    firmware_warning = pyqtSignal(str)

    # ------------------------------------------------------------------
    # Class-level configuration
    # ------------------------------------------------------------------

    #: Application version tuple used for firmware compatibility checks.
    APP_VERSION: tuple[int, int, int] = (1, 0, 0)

    #: Default time (ms) to wait for a response frame before declaring timeout.
    DEFAULT_TIMEOUT_MS: int = 5_000

    #: Seconds to pause after opening the port so the Arduino can reset.
    _ARDUINO_RESET_DELAY: float = 2.0

    #: How long (s) the worker blocks waiting for a new queue item.
    _QUEUE_POLL_INTERVAL: float = 0.05

    #: Sleep interval (s) inside the response-read loop.
    _READ_POLL_INTERVAL: float = 0.005

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self._port: Optional[serial.Serial] = None
        self._port_lock = threading.Lock()          # guards self._port
        self._cmd_queue: queue.Queue[bytes] = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._timeout_ms: int = self.DEFAULT_TIMEOUT_MS
        self._firmware: str = ""

    # ------------------------------------------------------------------
    # Port discovery
    # ------------------------------------------------------------------

    @staticmethod
    def list_ports() -> list[str]:
        """Return the device names of all available serial ports."""
        return [p.device for p in serial.tools.list_ports.comports()]

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(
        self,
        port: str,
        baudrate: int = 115_200,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> bool:
        """
        Open *port* and start the command worker.

        Returns True on success, False on failure (error_occurred is also
        emitted with a description).
        """
        if self.is_connected:
            logger.warning("connect() called while already connected; disconnecting first")
            self.disconnect()

        self._timeout_ms = timeout_ms
        logger.info("Opening serial port %s @ %d baud", port, baudrate)

        try:
            ser = serial.Serial(
                port,
                baudrate=baudrate,
                timeout=self._timeout_ms / 1_000.0,
            )
        except serial.SerialException as exc:
            msg = f"Could not open {port}: {exc}"
            logger.error(msg)
            self.status_changed.emit("Error")
            self.error_occurred.emit(msg)
            return False

        # Wait for the Arduino's bootloader to finish resetting.
        time.sleep(self._ARDUINO_RESET_DELAY)

        with self._port_lock:
            self._port = ser

        self._running = True
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="SerialWorker",
            daemon=True,
        )
        self._worker.start()

        self.status_changed.emit("Connected")

        # Query firmware version (done directly on the port, not via the queue,
        # so we can block here before handing control back to the caller).
        fw = self._query_firmware()
        self._firmware = fw
        self._check_firmware(fw)
        self.connected.emit(port, fw)
        logger.info("Connected to %s  firmware=%s", port, fw)
        return True

    def disconnect(self, reason: str = "User disconnected") -> None:
        """Close the port and stop the worker thread."""
        logger.info("Disconnecting: %s", reason)
        self._running = False

        with self._port_lock:
            if self._port is not None and self._port.is_open:
                try:
                    self._port.close()
                except Exception:
                    pass
            self._port = None

        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        self._worker = None

        # Drain any pending commands so stale items don't confuse the next session.
        while not self._cmd_queue.empty():
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                break

        self.status_changed.emit("Disconnected")
        self.disconnected.emit(reason)

    @property
    def is_connected(self) -> bool:
        """True when the port is open and the worker is running."""
        with self._port_lock:
            return self._port is not None and self._port.is_open

    @property
    def firmware_version(self) -> str:
        """Firmware version string reported by the Arduino on connect."""
        return self._firmware

    # ------------------------------------------------------------------
    # Runtime settings
    # ------------------------------------------------------------------

    def set_timeout(self, ms: int) -> None:
        """Change the response-frame timeout.  Takes effect on the next command."""
        self._timeout_ms = max(100, ms)

    # ------------------------------------------------------------------
    # Public command API  (all non-blocking)
    # ------------------------------------------------------------------

    def send_orient_on(self, panel: int, color: int = COLOR_WHITE) -> None:
        """Light pad #1 on *panel* to let the operator verify orientation."""
        self._enqueue(bytes([CMD_ORIENT_ON, panel & 0xFF, color & 0xFF]))

    def send_orient_off(self) -> None:
        """Turn off all LEDs on all panels."""
        self._enqueue(bytes([CMD_ORIENT_OFF]))

    def send_test_start(self) -> None:
        """Trigger the test-start LED pattern (green blink ×3)."""
        self._enqueue(bytes([CMD_TEST_START]))

    def send_test_end(self) -> None:
        """Trigger the test-end LED pattern (red blink)."""
        self._enqueue(bytes([CMD_TEST_END]))

    def send_single_touch(
        self,
        panel: int,
        pad: int,
        color: int,
        expect_touch: bool,
        timeout_ms: int,
    ) -> None:
        """
        Command the Arduino to light one pad and optionally measure a touch.

        Parameters
        ----------
        panel       : 0-based panel index
        pad         : 0-based pad index (0–15)
        color       : COLOR_WHITE | COLOR_GREEN | COLOR_RED
        expect_touch: when True the Arduino waits for a touch event
        timeout_ms  : give-up time in milliseconds (max 65535)
        """
        hi, lo = _split_u16(timeout_ms)
        flags  = 0x01 if expect_touch else 0x00
        self._enqueue(bytes([
            CMD_SINGLE_TOUCH,
            panel & 0xFF, pad & 0xFF, color & 0xFF,
            flags, hi, lo,
        ]))

    def send_dual_touch(
        self,
        panel: int,
        pad1: int,
        pad2: int,
        color: int,
        expect_touch: bool,
        timeout_ms: int,
    ) -> None:
        """
        Command the Arduino to light two adjacent pads simultaneously.

        *pad1* and *pad2* must be horizontally or vertically adjacent on the
        same panel.  Both must be touched for a successful result.
        """
        hi, lo = _split_u16(timeout_ms)
        flags  = 0x01 if expect_touch else 0x00
        self._enqueue(bytes([
            CMD_DUAL_TOUCH,
            panel & 0xFF, pad1 & 0xFF, pad2 & 0xFF,
            color & 0xFF, flags, hi, lo,
        ]))

    def send_calibrate(self, panel: int, pad: int) -> None:
        """Start a capacitive baseline calibration for a single pad."""
        self._enqueue(bytes([CMD_CALIBRATE, panel & 0xFF, pad & 0xFF]))

    def send_latency_test(self) -> None:
        """Send a round-trip latency ping to the Arduino."""
        self._enqueue(bytes([CMD_LATENCY]))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enqueue(self, cmd: bytes) -> None:
        """Place *cmd* on the outgoing queue, or emit an error if disconnected."""
        if not self.is_connected:
            self.error_occurred.emit("Cannot send command: not connected to Arduino")
            return
        self._cmd_queue.put(cmd)

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """
        Drain the command queue one item at a time.

        Each iteration: write bytes → read response frame → emit signal.
        Runs until self._running is False or a serial error occurs.
        """
        logger.debug("Serial worker thread started")
        while self._running:
            # Block briefly for a new command.
            try:
                cmd = self._cmd_queue.get(timeout=self._QUEUE_POLL_INTERVAL)
            except queue.Empty:
                continue

            with self._port_lock:
                if self._port is None or not self._port.is_open:
                    logger.warning("Port closed while worker was running")
                    break
                try:
                    self._port.write(cmd)
                    self._port.flush()
                    logger.debug("TX %s", cmd.hex(" ").upper())

                    response = self._read_response_frame()
                    logger.debug("RX %r", response)
                except serial.SerialException as exc:
                    logger.error("Serial error in worker: %s", exc)
                    self._running = False
                    # Emit from a worker thread — Qt will queue it to the main thread.
                    self.status_changed.emit("Error")
                    self.disconnected.emit(str(exc))
                    break

            self.response_received.emit(response)

        logger.debug("Serial worker thread exiting")

    def _read_response_frame(self) -> ArduinoResponse:
        """
        Block until a complete 6-byte frame arrives or the timeout expires.

        Frame:  [ status, panel, pad, touched, rt_hi, rt_lo ]
        """
        deadline = time.monotonic() + self._timeout_ms / 1_000.0
        buf = bytearray()

        while time.monotonic() < deadline:
            waiting = self._port.in_waiting
            if waiting:
                need = _FRAME_LEN - len(buf)
                buf += self._port.read(min(waiting, need))
            if len(buf) >= _FRAME_LEN:
                break
            time.sleep(self._READ_POLL_INTERVAL)

        if len(buf) < _FRAME_LEN:
            logger.warning("Response timeout after %d ms (got %d/%d bytes)",
                           self._timeout_ms, len(buf), _FRAME_LEN)
            return ArduinoResponse(
                panel=0, pad=0, touched=False,
                response_time_ms=self._timeout_ms,
                error="Timeout waiting for Arduino response",
                is_timeout=True,
            )

        status, panel, pad, touched_byte, rt_hi, rt_lo = buf[:_FRAME_LEN]

        if status == NAK:
            logger.warning("Arduino returned NAK for panel=%d pad=%d", panel, pad)
            return ArduinoResponse(
                panel=panel, pad=pad, touched=False,
                response_time_ms=0,
                error="Arduino NAK — command not executed",
                is_nak=True,
            )

        rt = (rt_hi << 8) | rt_lo
        return ArduinoResponse(
            panel=panel, pad=pad,
            touched=bool(touched_byte),
            response_time_ms=rt,
        )

    # ------------------------------------------------------------------
    # Firmware helpers (called directly on connect, not via queue)
    # ------------------------------------------------------------------

    def _query_firmware(self) -> str:
        """
        Send the version command directly (bypassing the queue) and read
        the ASCII response line.  Called once during connect() before the
        worker thread starts, so no locking is needed.
        """
        try:
            self._port.reset_input_buffer()
            self._port.write(bytes([CMD_VERSION]))
            self._port.flush()
            raw = self._port.readline()
            version = raw.decode("ascii", errors="replace").strip()
            return version or "unknown"
        except Exception as exc:
            logger.warning("Firmware version query failed: %s", exc)
            return "unknown"

    def _check_firmware(self, fw: str) -> None:
        """Emit firmware_warning if the major version does not match."""
        try:
            major = int(fw.split(".")[0])
            if major != self.APP_VERSION[0]:
                self.firmware_warning.emit(
                    f"Firmware version {fw!r} is not compatible with "
                    f"application version "
                    f"{'.'.join(str(v) for v in self.APP_VERSION)}.\n\n"
                    "Please flash the correct firmware before running tests."
                )
        except (ValueError, IndexError):
            self.firmware_warning.emit(
                f"Could not parse firmware version string {fw!r}.\n"
                "Ensure the Arduino is running the correct firmware."
            )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _split_u16(value: int) -> tuple[int, int]:
    """Split an unsigned 16-bit integer into (high_byte, low_byte)."""
    clamped = max(0, min(0xFFFF, value))
    return (clamped >> 8) & 0xFF, clamped & 0xFF
