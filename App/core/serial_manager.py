"""
core.serial_manager
~~~~~~~~~~~~~~~~~~~
Manages the serial connection to the Arduino TrainerPanel controller.

Protocol
--------
All communication is plain ASCII text, one command or response per line
(terminated with \\r\\n on send, \\n on receive).  This matches the
TrainerPanel.cpp implementation exactly and allows any serial terminal
(Arduino IDE Serial Monitor, PuTTY, screen) to be used for debugging.

Commands (PC -> Arduino)
------------------------
ORIENTATION ON               Light pad #1 to verify orientation
ORIENTATION OFF              Turn all LEDs off
PATTERN START                Flash green LEDs x3 (test starting)
PATTERN END                  Flash red LEDs x3  (test complete)
SINGLE <pad> <color> <expect> <timeout_ms>
                             Light one pad; optionally wait for touch
DOUBLE <pad1> <pad2> <color> <expect> <timeout_ms>
                             Light two adjacent pads; wait for both
CANCEL                       Abort the current touch measurement
VERSION                      Query firmware version string

Where:
  <pad>      1-based pad number (as used by TrainerPanel.h)
  <color>    WHITE | GREEN | RED
  <expect>   TRUE | FALSE
  <timeout>  milliseconds as a decimal integer

Responses (Arduino -> PC)
--------------------------
SINGLE_PAD_RESULT <pad> <touched> <reaction_time_ms>
DOUBLE_PAD_RESULT <pad1> <pad2> <touched> <reaction_time_ms>
ORIENTATION is ON | OFF
VERSION <version_string>
ERROR <message>              Any line starting with ERROR

Any other line is treated as a debug/info print from the Arduino and
is logged at DEBUG level but not parsed as a result.
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
# Protocol string constants  (must match TrainerPanel.h exactly)
# ---------------------------------------------------------------------------

CMD_ORIENTATION  = "ORIENTATION"
CMD_PATTERN      = "PATTERN"
CMD_SINGLE       = "SINGLE"
CMD_DOUBLE       = "DOUBLE"
CMD_CANCEL       = "CANCEL"
CMD_VERSION      = "VERSION"

COLOR_WHITE = "WHITE"
COLOR_GREEN = "GREEN"
COLOR_RED   = "RED"

RESP_SINGLE_RESULT = "SINGLE_PAD_RESULT"
RESP_DOUBLE_RESULT = "DOUBLE_PAD_RESULT"
RESP_VERSION       = "VERSION"
RESP_ERROR         = "ERROR"

# ---------------------------------------------------------------------------
# Response data class
# ---------------------------------------------------------------------------

class ArduinoResponse:
    """
    Parsed response from the Arduino.

    Attributes
    ----------
    pad               : 1-based pad number reported by the Arduino
    pad2              : second pad for DOUBLE results (0 if single)
    touched           : True if a touch was recorded
    reaction_time_ms  : time from LED-on to touch (ms); timeout value if no touch
    raw               : the original unparsed response line
    error             : non-empty when the Arduino sent ERROR or parsing failed
    is_timeout        : True when the PC timed out waiting for any response
    """

    __slots__ = ("pad", "pad2", "touched", "reaction_time_ms",
                 "raw", "error", "is_timeout")

    def __init__(
        self,
        pad: int               = 0,
        pad2: int              = 0,
        touched: bool          = False,
        reaction_time_ms: int  = 0,
        raw: str               = "",
        error: str             = "",
        is_timeout: bool       = False,
    ) -> None:
        self.pad              = pad
        self.pad2             = pad2
        self.touched          = touched
        self.reaction_time_ms = reaction_time_ms
        self.raw              = raw
        self.error            = error
        self.is_timeout       = is_timeout

    @property
    def ok(self) -> bool:
        """True when the response represents a successful result."""
        return not self.error and not self.is_timeout

    def __repr__(self) -> str:
        if self.is_timeout:
            return "ArduinoResponse(TIMEOUT)"
        if self.error:
            return f"ArduinoResponse(ERROR {self.error!r})"
        return (
            f"ArduinoResponse(pad={self.pad} pad2={self.pad2} "
            f"touched={self.touched} rt={self.reaction_time_ms}ms)"
        )


# ---------------------------------------------------------------------------
# Serial manager
# ---------------------------------------------------------------------------

class SerialManager(QObject):
    """
    Thread-safe serial port manager for the Arduino TrainerPanel controller.

    All public send_* methods are non-blocking: they place the command on
    an internal queue and return immediately.  The worker thread writes one
    command at a time, reads lines until it gets a result line, then emits
    response_received.

    Usage
    -----
    >>> mgr = SerialManager()
    >>> mgr.status_changed.connect(on_status)
    >>> mgr.response_received.connect(on_response)
    >>> mgr.connect("COM3")
    >>> mgr.send_single_touch(pad=3, color=COLOR_GREEN,
    ...                       expect_touch=True, timeout_ms=2000)
    >>> # response arrives via response_received signal
    >>> mgr.disconnect()
    """

    # ------------------------------------------------------------------
    # Qt signals
    # ------------------------------------------------------------------

    #: Emitted when the port opens successfully. Args: port name, firmware version.
    connected = pyqtSignal(str, str)

    #: Emitted when the port closes. Arg: reason string.
    disconnected = pyqtSignal(str)

    #: Emitted for every parsed result (SINGLE_PAD_RESULT / DOUBLE_PAD_RESULT).
    response_received = pyqtSignal(object)   # ArduinoResponse

    #: Non-fatal error (disconnected send attempt, parse failure, etc.)
    error_occurred = pyqtSignal(str)

    #: Persistent state string: "Connected" | "Disconnected" | "Error"
    status_changed = pyqtSignal(str)

    #: Emitted when the firmware version string looks incompatible.
    firmware_warning = pyqtSignal(str)

    # ------------------------------------------------------------------
    # Class-level configuration
    # ------------------------------------------------------------------

    APP_VERSION: tuple[int, int, int] = (1, 0, 0)

    #: Default time (ms) to wait for a result line before declaring timeout.
    DEFAULT_TIMEOUT_MS: int = 5_000

    #: Seconds to wait after opening the port for the Arduino to reset.
    _ARDUINO_RESET_DELAY: float = 2.0

    #: How long (s) the worker blocks on an empty queue.
    _QUEUE_POLL_INTERVAL: float = 0.05

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._port: Optional[serial.Serial] = None
        self._port_lock   = threading.Lock()
        self._cmd_queue: queue.Queue[str] = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._running     = False
        self._timeout_ms  = self.DEFAULT_TIMEOUT_MS
        self._firmware    = ""

    # ------------------------------------------------------------------
    # Port discovery
    # ------------------------------------------------------------------

    @staticmethod
    def list_ports() -> list[str]:
        """Return device names of all available serial ports."""
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
            logger.warning("connect() called while already connected -- disconnecting first")
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

        # Wait for the Arduino bootloader to finish resetting.
        time.sleep(self._ARDUINO_RESET_DELAY)

        with self._port_lock:
            self._port = ser

        self._running = True
        self._worker  = threading.Thread(
            target=self._worker_loop,
            name="SerialWorker",
            daemon=True,
        )
        self._worker.start()
        self.status_changed.emit("Connected")

        # Query firmware version directly (before the worker starts consuming lines).
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

        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        self._worker = None

        # Drain stale commands so they don't affect the next session.
        while not self._cmd_queue.empty():
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                break

        self.status_changed.emit("Disconnected")
        self.disconnected.emit(reason)

    @property
    def is_connected(self) -> bool:
        with self._port_lock:
            return self._port is not None and self._port.is_open

    @property
    def firmware_version(self) -> str:
        return self._firmware

    # ------------------------------------------------------------------
    # Runtime settings
    # ------------------------------------------------------------------

    def set_timeout(self, ms: int) -> None:
        """Change the response timeout. Takes effect on the next command."""
        self._timeout_ms = max(100, ms)

    # ------------------------------------------------------------------
    # Public command API  (all non-blocking)
    # ------------------------------------------------------------------

    def send_orient_on(self) -> None:
        """Light pad #1 so the operator can verify panel orientation."""
        self._enqueue(f"{CMD_ORIENTATION} ON")

    def send_orient_off(self) -> None:
        """Turn off all LEDs."""
        self._enqueue(f"{CMD_ORIENTATION} OFF")

    def send_test_start(self) -> None:
        """Flash green LEDs three times (test-starting signal)."""
        self._enqueue(f"{CMD_PATTERN} START")

    def send_test_end(self) -> None:
        """Flash red LEDs three times (test-complete signal)."""
        self._enqueue(f"{CMD_PATTERN} END")

    def send_single_touch(
        self,
        pad: int,
        color: str,
        expect_touch: bool,
        timeout_ms: int,
    ) -> None:
        """
        Light one pad and optionally wait for a touch.

        Parameters
        ----------
        pad          : 1-based pad number
        color        : COLOR_WHITE | COLOR_GREEN | COLOR_RED
        expect_touch : True to wait for and report a touch event
        timeout_ms   : give-up time in milliseconds
        """
        expect = "TRUE" if expect_touch else "FALSE"
        logger.debug(f"Sending {CMD_SINGLE} {pad} {color} {expect} {timeout_ms}")
        self._enqueue(f"{CMD_SINGLE} {pad} {color} {expect} {timeout_ms}")

    def send_dual_touch(
        self,
        pad1: int,
        pad2: int,
        color: str,
        expect_touch: bool,
        timeout_ms: int,
    ) -> None:
        """
        Light two adjacent pads simultaneously and wait for both to be touched.

        Parameters
        ----------
        pad1, pad2   : 1-based pad numbers (must be adjacent on the same panel)
        color        : COLOR_WHITE | COLOR_GREEN | COLOR_RED
        expect_touch : True to wait for and report touch events
        timeout_ms   : give-up time in milliseconds
        """
        expect = "TRUE" if expect_touch else "FALSE"
        logger.debug(f"Sending {CMD_DOUBLE} {pad1} {pad2} {color} {expect} {timeout_ms}")
        self._enqueue(f"{CMD_DOUBLE} {pad1} {pad2} {color} {expect} {timeout_ms}")

    def send_cancel(self) -> None:
        """Abort the current touch measurement."""
        self._enqueue(CMD_CANCEL)

    def send_latency_test(self) -> None:
        """
        Send a VERSION query; the round-trip time serves as a latency measure.
        The reply is emitted via response_received as a debug/info response.
        """
        self._enqueue(CMD_VERSION)

    def send_calibrate(self, pad: int) -> None:
        """
        Placeholder for a future CALIBRATE command.
        Logs a warning until the command is added to TrainerPanel firmware.
        """
        logger.warning(
            "send_calibrate(pad=%d) called but CALIBRATE is not yet "
            "implemented in the Arduino firmware.", pad
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enqueue(self, cmd: str) -> None:
        if not self.is_connected:
            self.error_occurred.emit(
                "Cannot send command: not connected to Arduino")
            return
        logger.debug("Queuing: %s", cmd)
        self._cmd_queue.put(cmd)

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """
        Drain the command queue one item at a time.

        For each command: write the line -> read lines until a result
        line (SINGLE_PAD_RESULT / DOUBLE_PAD_RESULT) or timeout arrives
        -> emit response_received.

        Non-result lines (Arduino debug prints, ORIENTATION confirmations,
        etc.) are logged at DEBUG level and do not unblock the wait.
        """
        logger.debug("Serial worker thread started")
        while self._running:
            try:
                cmd = self._cmd_queue.get(timeout=self._QUEUE_POLL_INTERVAL)
            except queue.Empty:
                continue

            with self._port_lock:
                if self._port is None or not self._port.is_open:
                    logger.warning("Port closed while worker was running")
                    break
                try:
                    self._port.write((cmd + "\r\n").encode("ascii"))
                    self._port.flush()
                    logger.debug("TX: %s", cmd)

                    # Only block for a result when the command expects one.
                    if _expects_result(cmd):
                        response = self._read_result_line()
                        logger.debug("RX: %r", response)
                        self.response_received.emit(response)

                except serial.SerialException as exc:
                    logger.error("Serial error in worker: %s", exc)
                    self._running = False
                    self.status_changed.emit("Error")
                    self.disconnected.emit(str(exc))
                    break

        logger.debug("Serial worker thread exiting")

    def _read_result_line(self) -> ArduinoResponse:
        """
        Read lines from the port until a SINGLE_PAD_RESULT or
        DOUBLE_PAD_RESULT line arrives, or the timeout expires.

        Intermediate lines (Arduino debug prints) are logged and discarded.
        """
        deadline = time.monotonic() + self._timeout_ms / 1_000.0

        while time.monotonic() < deadline:
            try:
                raw = self._port.readline()
                logger.debug(raw)
            except serial.SerialException:
                raise

            if not raw:
                # Port readline timed out with no data -- check overall deadline.
                continue

            line = raw.decode("ascii", errors="replace").strip()
            if not line:
                continue

            logger.debug("Arduino: %s", line)

            if line.startswith(RESP_SINGLE_RESULT):
                return _parse_single_result(line)
            if line.startswith(RESP_DOUBLE_RESULT):
                return _parse_double_result(line)
            if line.startswith(RESP_ERROR):
                return ArduinoResponse(error=line, raw=line)
            # Otherwise it is a debug/info print -- log and keep waiting.

        logger.warning("Response timeout after %d ms", self._timeout_ms)
        return ArduinoResponse(
            error="Timeout waiting for Arduino response",
            is_timeout=True,
            reaction_time_ms=self._timeout_ms,
        )

    # ------------------------------------------------------------------
    # Firmware helpers
    # ------------------------------------------------------------------

    def _query_firmware(self) -> str:
        """
        Send VERSION directly (bypassing the queue) and read the reply.
        Called once during connect() before the worker thread starts.
        """
        try:
            self._port.reset_input_buffer()
            self._port.write(b"VERSION\r\n")
            self._port.flush()
            raw  = self._port.readline()
            line = raw.decode("ascii", errors="replace").strip()
            # Expect "VERSION 1.0.0" or similar
            if line.upper().startswith("VERSION"):
                parts = line.split(None, 1)
                return parts[1] if len(parts) > 1 else "unknown"
            return line or "unknown"
        except Exception as exc:
            logger.warning("Firmware version query failed: %s", exc)
            return "unknown"

    def _check_firmware(self, fw: str) -> None:
        """Warn if the firmware major version does not match APP_VERSION[0]."""
        logger.debug(f"Checking firmware return value: {fw}")
        try:
            major = int(fw.split(".")[0])
            if major != self.APP_VERSION[0]:
                self.firmware_warning.emit(
                    f"Firmware version {fw!r} may be incompatible with "
                    f"app version "
                    f"{'.'.join(str(v) for v in self.APP_VERSION)}.\n\n"
                    "Please flash the correct firmware before running tests."
                )
        except (ValueError, IndexError):
            self.firmware_warning.emit(
                f"Could not parse firmware version {fw!r}. "
                "Ensure the Arduino is running the correct firmware."
            )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _expects_result(cmd: str) -> bool:
    """Return True when *cmd* will produce a SINGLE/DOUBLE_PAD_RESULT reply."""
    upper = cmd.upper()
    return upper.startswith(CMD_SINGLE) or upper.startswith(CMD_DOUBLE)


def _parse_single_result(line: str) -> ArduinoResponse:
    """
    Parse:  SINGLE_PAD_RESULT <pad> <TRUE|FALSE> <reaction_time_ms>

    Example:  SINGLE_PAD_RESULT 3 TRUE 412
    """
    try:
        parts   = line.split()
        pad     = int(parts[1])
        touched = parts[2].upper() == "TRUE"
        rt      = int(parts[3])
        return ArduinoResponse(pad=pad, touched=touched,
                               reaction_time_ms=rt, raw=line)
    except (IndexError, ValueError) as exc:
        logger.error("Could not parse SINGLE_PAD_RESULT %r: %s", line, exc)
        return ArduinoResponse(error=f"Parse error: {line}", raw=line)


def _parse_double_result(line: str) -> ArduinoResponse:
    """
    Parse:  DOUBLE_PAD_RESULT <pad1> <pad2> <TRUE|FALSE> <reaction_time_ms>

    Example:  DOUBLE_PAD_RESULT 3 4 TRUE 520
    """
    try:
        parts   = line.split()
        pad1    = int(parts[1])
        pad2    = int(parts[2])
        touched = parts[3].upper() == "TRUE"
        rt      = int(parts[4])
        return ArduinoResponse(pad=pad1, pad2=pad2, touched=touched,
                               reaction_time_ms=rt, raw=line)
    except (IndexError, ValueError) as exc:
        logger.error("Could not parse DOUBLE_PAD_RESULT %r: %s", line, exc)
        return ArduinoResponse(error=f"Parse error: {line}", raw=line)
