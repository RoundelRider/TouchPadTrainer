"""
core -- hardware interface and test-sequencing logic.

Nothing in this package imports from PyQt6 directly; all Qt integration is
done through the signal/slot mechanism on QObject subclasses so that the
business logic remains unit-testable without a running QApplication.
"""

from core.serial_manager import (
    SerialManager,
    ArduinoResponse,
    CMD_ORIENTATION,
    CMD_PATTERN,
    CMD_SINGLE,
    CMD_DOUBLE,
    CMD_CANCEL,
    CMD_VERSION,
    COLOR_WHITE,
    COLOR_GREEN,
    COLOR_RED,
    RESP_SINGLE_RESULT,
    RESP_DOUBLE_RESULT,
)
from core.test_runner import TestRunner
from core.audio import AudioCue

__all__ = [
    "SerialManager",
    "ArduinoResponse",
    "TestRunner",
    "AudioCue",
    # Command strings
    "CMD_ORIENTATION", "CMD_PATTERN", "CMD_SINGLE", "CMD_DOUBLE",
    "CMD_CANCEL", "CMD_VERSION",
    # Colour strings
    "COLOR_WHITE", "COLOR_GREEN", "COLOR_RED",
    # Response prefixes
    "RESP_SINGLE_RESULT", "RESP_DOUBLE_RESULT",
]
