"""
core — hardware interface and test-sequencing logic.

Nothing in this package imports from PyQt6 directly; all Qt integration is
done through the signal/slot mechanism on QObject subclasses so that the
business logic remains unit-testable without a running QApplication.
"""

from core.serial_manager import (
    SerialManager,
    ArduinoResponse,
    CMD_ORIENT_ON,
    CMD_ORIENT_OFF,
    CMD_TEST_START,
    CMD_TEST_END,
    CMD_SINGLE_TOUCH,
    CMD_DUAL_TOUCH,
    CMD_VERSION,
    CMD_CALIBRATE,
    CMD_LATENCY,
    COLOR_WHITE,
    COLOR_GREEN,
    COLOR_RED,
    ACK,
    NAK,
)
from core.test_runner import TestRunner
from core.audio import AudioCue

__all__ = [
    "SerialManager",
    "ArduinoResponse",
    "TestRunner",
    "AudioCue",
    # Command codes
    "CMD_ORIENT_ON", "CMD_ORIENT_OFF", "CMD_TEST_START", "CMD_TEST_END",
    "CMD_SINGLE_TOUCH", "CMD_DUAL_TOUCH", "CMD_VERSION",
    "CMD_CALIBRATE", "CMD_LATENCY",
    # Colour codes
    "COLOR_WHITE", "COLOR_GREEN", "COLOR_RED",
    # Response status bytes
    "ACK", "NAK",
]
