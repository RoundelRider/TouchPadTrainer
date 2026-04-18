"""
tests/test_serial_manager.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for core.serial_manager — no real serial port required.

Strategy
--------
All tests that touch a real port are replaced by tests against the internal
parsing and command-building logic using in-process fakes.

* ArduinoResponse          — construction, ok property, repr
* _split_u16               — boundary values, clamping
* Frame parsing             — ACK, NAK, timeout via _read_response_frame
                             (exercised through a fake port buffer)
* Command byte construction — verify the correct bytes are queued by each
                             send_* helper using a patched queue
* Port discovery            — list_ports returns a list of strings
* Firmware check            — warning emitted for mismatched major version
* connect / disconnect       — guarded by unittest.skipUnless(pyserial open mock)

Qt-dependent tests (signals, worker thread) are skipped when PyQt6 is absent.
"""

from __future__ import annotations

import io
import queue
import struct
import sys
import pathlib
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

try:
    from core.serial_manager import (
        ArduinoResponse, _split_u16,
        COLOR_WHITE, COLOR_GREEN, COLOR_RED,
        CMD_ORIENT_ON, CMD_ORIENT_OFF, CMD_TEST_START, CMD_TEST_END,
        CMD_SINGLE_TOUCH, CMD_DUAL_TOUCH, CMD_VERSION, CMD_CALIBRATE, CMD_LATENCY,
        ACK, NAK,
    )
    _HAS_SERIAL = True
except ImportError:
    # pyserial not installed — skip all tests that need it
    _HAS_SERIAL = False
    ArduinoResponse = None     # stub so class bodies parse
    _split_u16 = None
    COLOR_WHITE = COLOR_GREEN = COLOR_RED = 0
    CMD_ORIENT_ON = CMD_ORIENT_OFF = CMD_TEST_START = CMD_TEST_END = 0
    CMD_SINGLE_TOUCH = CMD_DUAL_TOUCH = CMD_VERSION = CMD_CALIBRATE = CMD_LATENCY = 0
    ACK = NAK = 0

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    from core.serial_manager import SerialManager
    _HAS_QT = _HAS_SERIAL
except ImportError:
    _HAS_QT = False

_SKIP_QT = unittest.skipUnless(_HAS_QT, "PyQt6 not installed — skipping Qt tests")

# Ensure a QApplication exists when Qt tests run
if _HAS_QT:
    import sys as _sys
    _app = QApplication.instance() or QApplication(_sys.argv)


# ===========================================================================
# ArduinoResponse
# ===========================================================================

@unittest.skipUnless(_HAS_SERIAL, "pyserial not installed")
class TestArduinoResponse(unittest.TestCase):

    def test_ok_true_for_normal_response(self):
        r = ArduinoResponse(panel=0, pad=0, touched=True,
                            response_time_ms=300)
        self.assertTrue(r.ok)

    def test_ok_false_for_nak(self):
        r = ArduinoResponse(panel=0, pad=0, touched=False,
                            response_time_ms=0,
                            error="NAK", is_nak=True)
        self.assertFalse(r.ok)

    def test_ok_false_for_timeout(self):
        r = ArduinoResponse(panel=0, pad=0, touched=False,
                            response_time_ms=2000,
                            error="Timeout", is_timeout=True)
        self.assertFalse(r.ok)

    def test_ok_false_when_error_set(self):
        r = ArduinoResponse(panel=0, pad=0, touched=False,
                            response_time_ms=0, error="Something wrong")
        self.assertFalse(r.ok)

    def test_touched_false_by_default_when_nak(self):
        r = ArduinoResponse(panel=1, pad=2, touched=False,
                            response_time_ms=0, is_nak=True, error="NAK")
        self.assertFalse(r.touched)

    def test_repr_contains_panel_and_pad(self):
        r = ArduinoResponse(panel=2, pad=5, touched=True,
                            response_time_ms=350)
        rep = repr(r)
        self.assertIn("panel=2", rep)
        self.assertIn("pad=5",   rep)

    def test_repr_shows_ack_status(self):
        r = ArduinoResponse(0, 0, True, 300)
        self.assertIn("ACK", repr(r))

    def test_repr_shows_nak_status(self):
        r = ArduinoResponse(0, 0, False, 0, error="NAK", is_nak=True)
        self.assertIn("NAK", repr(r))

    def test_repr_shows_timeout_status(self):
        r = ArduinoResponse(0, 0, False, 2000,
                            error="Timeout", is_timeout=True)
        self.assertIn("TIMEOUT", repr(r))

    def test_all_fields_stored(self):
        r = ArduinoResponse(panel=3, pad=7, touched=True,
                            response_time_ms=512,
                            error="", is_nak=False, is_timeout=False)
        self.assertEqual(r.panel,            3)
        self.assertEqual(r.pad,              7)
        self.assertTrue(r.touched)
        self.assertEqual(r.response_time_ms, 512)


# ===========================================================================
# _split_u16
# ===========================================================================

@unittest.skipUnless(_HAS_SERIAL, "pyserial not installed")
class TestSplitU16(unittest.TestCase):

    def test_zero(self):
        hi, lo = _split_u16(0)
        self.assertEqual(hi, 0)
        self.assertEqual(lo, 0)

    def test_one(self):
        hi, lo = _split_u16(1)
        self.assertEqual(hi, 0)
        self.assertEqual(lo, 1)

    def test_256(self):
        hi, lo = _split_u16(256)
        self.assertEqual(hi, 1)
        self.assertEqual(lo, 0)

    def test_max_u16(self):
        hi, lo = _split_u16(0xFFFF)
        self.assertEqual(hi, 0xFF)
        self.assertEqual(lo, 0xFF)

    def test_typical_timeout_2000ms(self):
        hi, lo = _split_u16(2000)
        self.assertEqual((hi << 8) | lo, 2000)

    def test_typical_timeout_5000ms(self):
        hi, lo = _split_u16(5000)
        self.assertEqual((hi << 8) | lo, 5000)

    def test_over_max_clamped_to_ffff(self):
        hi, lo = _split_u16(0x10000)
        self.assertEqual((hi << 8) | lo, 0xFFFF)

    def test_negative_clamped_to_zero(self):
        hi, lo = _split_u16(-100)
        self.assertEqual(hi, 0)
        self.assertEqual(lo, 0)

    def test_round_trip(self):
        for val in [0, 1, 255, 256, 1000, 5000, 65535]:
            hi, lo = _split_u16(val)
            self.assertEqual((hi << 8) | lo, val)


# ===========================================================================
# Protocol constants
# ===========================================================================

@unittest.skipUnless(_HAS_SERIAL, "pyserial not installed")
class TestProtocolConstants(unittest.TestCase):

    def test_colors_are_distinct(self):
        self.assertNotEqual(COLOR_WHITE, COLOR_GREEN)
        self.assertNotEqual(COLOR_GREEN, COLOR_RED)
        self.assertNotEqual(COLOR_WHITE, COLOR_RED)

    def test_ack_nak_distinct(self):
        self.assertNotEqual(ACK, NAK)

    def test_command_codes_unique(self):
        codes = [CMD_ORIENT_ON, CMD_ORIENT_OFF, CMD_TEST_START, CMD_TEST_END,
                 CMD_SINGLE_TOUCH, CMD_DUAL_TOUCH, CMD_VERSION,
                 CMD_CALIBRATE, CMD_LATENCY]
        self.assertEqual(len(codes), len(set(codes)))

    def test_all_command_codes_fit_in_byte(self):
        codes = [CMD_ORIENT_ON, CMD_ORIENT_OFF, CMD_TEST_START, CMD_TEST_END,
                 CMD_SINGLE_TOUCH, CMD_DUAL_TOUCH, CMD_VERSION,
                 CMD_CALIBRATE, CMD_LATENCY]
        for c in codes:
            self.assertGreaterEqual(c, 0)
            self.assertLessEqual(c, 255)


# ===========================================================================
# Frame parsing  (internal _read_response_frame via fake port)
# ===========================================================================

def _make_frame(status, panel, pad, touched, rt_ms):
    hi, lo = _split_u16(rt_ms)
    return bytes([status, panel, pad, touched, hi, lo])


@_SKIP_QT
class TestFrameParsing(unittest.TestCase):
    """
    Exercises _read_response_frame by replacing the real serial.Serial object
    inside SerialManager with a fake that returns pre-canned bytes.
    """

    def _manager_with_fake_port(self, data: bytes) -> SerialManager:
        """Return a SerialManager whose _port is a fake with *data* in its buffer."""
        sm = SerialManager()
        fake_port = MagicMock()
        fake_port.is_open = True
        # Simulate incremental reads from a buffer
        buf = bytearray(data)
        def fake_read(n):
            chunk = bytes(buf[:n])
            del buf[:n]
            return chunk
        fake_port.read.side_effect = fake_read
        fake_port.in_waiting = len(data)
        sm._port = fake_port
        return sm

    def test_ack_frame_parsed_correctly(self):
        frame = _make_frame(ACK, panel=1, pad=3, touched=1, rt_ms=312)
        sm = self._manager_with_fake_port(frame)
        response = sm._read_response_frame()
        self.assertTrue(response.ok)
        self.assertEqual(response.panel, 1)
        self.assertEqual(response.pad,   3)
        self.assertTrue(response.touched)
        self.assertEqual(response.response_time_ms, 312)

    def test_nak_frame_sets_is_nak(self):
        frame = _make_frame(NAK, panel=0, pad=0, touched=0, rt_ms=0)
        sm = self._manager_with_fake_port(frame)
        response = sm._read_response_frame()
        self.assertTrue(response.is_nak)
        self.assertFalse(response.ok)

    def test_no_touch_in_frame(self):
        frame = _make_frame(ACK, panel=0, pad=2, touched=0, rt_ms=2000)
        sm = self._manager_with_fake_port(frame)
        response = sm._read_response_frame()
        self.assertFalse(response.touched)

    def test_timeout_when_no_data(self):
        sm = SerialManager()
        fake_port = MagicMock()
        fake_port.is_open = True
        fake_port.in_waiting = 0
        fake_port.read.return_value = b''
        sm._port = fake_port
        sm._timeout_ms = 50    # short timeout so test runs fast
        response = sm._read_response_frame()
        self.assertTrue(response.is_timeout)
        self.assertFalse(response.ok)

    def test_timeout_response_has_timeout_rt(self):
        sm = SerialManager()
        fake_port = MagicMock()
        fake_port.is_open = True
        fake_port.in_waiting = 0
        fake_port.read.return_value = b''
        sm._port = fake_port
        sm._timeout_ms = 50
        response = sm._read_response_frame()
        self.assertEqual(response.response_time_ms, sm._timeout_ms)

    def test_rt_decoded_big_endian(self):
        # rt = 0x0190 = 400 ms
        frame = bytes([ACK, 0, 0, 1, 0x01, 0x90])
        sm = self._manager_with_fake_port(frame)
        response = sm._read_response_frame()
        self.assertEqual(response.response_time_ms, 400)


# ===========================================================================
# Command byte construction
# ===========================================================================

@_SKIP_QT
class TestCommandBytes(unittest.TestCase):
    """
    Verify that each send_* method places the expected bytes onto the queue.
    """

    def _manager_connected(self) -> "tuple[SerialManager, queue.Queue]":
        sm = SerialManager()
        fake_port = MagicMock()
        fake_port.is_open = True
        sm._port = fake_port
        return sm, sm._cmd_queue

    def test_orient_on_bytes(self):
        sm, q = self._manager_connected()
        sm.send_orient_on(panel=2, color=COLOR_GREEN)
        cmd = q.get_nowait()
        self.assertEqual(cmd[0], CMD_ORIENT_ON)
        self.assertEqual(cmd[1], 2)
        self.assertEqual(cmd[2], COLOR_GREEN)

    def test_orient_off_bytes(self):
        sm, q = self._manager_connected()
        sm.send_orient_off()
        cmd = q.get_nowait()
        self.assertEqual(cmd[0], CMD_ORIENT_OFF)
        self.assertEqual(len(cmd), 1)

    def test_test_start_bytes(self):
        sm, q = self._manager_connected()
        sm.send_test_start()
        self.assertEqual(q.get_nowait()[0], CMD_TEST_START)

    def test_test_end_bytes(self):
        sm, q = self._manager_connected()
        sm.send_test_end()
        self.assertEqual(q.get_nowait()[0], CMD_TEST_END)

    def test_single_touch_command_code(self):
        sm, q = self._manager_connected()
        sm.send_single_touch(0, 5, COLOR_WHITE, True, 2000)
        cmd = q.get_nowait()
        self.assertEqual(cmd[0], CMD_SINGLE_TOUCH)

    def test_single_touch_panel_and_pad(self):
        sm, q = self._manager_connected()
        sm.send_single_touch(panel=1, pad=7, color=COLOR_GREEN,
                             expect_touch=True, timeout_ms=1000)
        cmd = q.get_nowait()
        self.assertEqual(cmd[1], 1)  # panel
        self.assertEqual(cmd[2], 7)  # pad

    def test_single_touch_expect_flag_set(self):
        sm, q = self._manager_connected()
        sm.send_single_touch(0, 0, COLOR_WHITE, expect_touch=True, timeout_ms=500)
        cmd = q.get_nowait()
        self.assertEqual(cmd[4], 0x01)

    def test_single_touch_no_expect_flag_clear(self):
        sm, q = self._manager_connected()
        sm.send_single_touch(0, 0, COLOR_RED, expect_touch=False, timeout_ms=500)
        cmd = q.get_nowait()
        self.assertEqual(cmd[4], 0x00)

    def test_single_touch_timeout_encoded(self):
        sm, q = self._manager_connected()
        sm.send_single_touch(0, 0, COLOR_WHITE, True, timeout_ms=3000)
        cmd = q.get_nowait()
        hi, lo = cmd[5], cmd[6]
        self.assertEqual((hi << 8) | lo, 3000)

    def test_dual_touch_command_code(self):
        sm, q = self._manager_connected()
        sm.send_dual_touch(0, 0, 1, COLOR_WHITE, True, 2000)
        cmd = q.get_nowait()
        self.assertEqual(cmd[0], CMD_DUAL_TOUCH)

    def test_dual_touch_pads(self):
        sm, q = self._manager_connected()
        sm.send_dual_touch(panel=0, pad1=4, pad2=5,
                           color=COLOR_GREEN, expect_touch=True, timeout_ms=1500)
        cmd = q.get_nowait()
        self.assertEqual(cmd[2], 4)   # pad1
        self.assertEqual(cmd[3], 5)   # pad2

    def test_calibrate_bytes(self):
        sm, q = self._manager_connected()
        sm.send_calibrate(panel=1, pad=8)
        cmd = q.get_nowait()
        self.assertEqual(cmd[0], CMD_CALIBRATE)
        self.assertEqual(cmd[1], 1)
        self.assertEqual(cmd[2], 8)

    def test_latency_bytes(self):
        sm, q = self._manager_connected()
        sm.send_latency_test()
        cmd = q.get_nowait()
        self.assertEqual(cmd[0], CMD_LATENCY)

    def test_enqueue_fails_when_disconnected(self):
        sm = SerialManager()
        errors = []
        sm.error_occurred.connect(errors.append)
        sm.send_orient_off()   # port is None → should emit error, not raise
        self.assertEqual(len(errors), 1)
        self.assertIn("not connected", errors[0].lower())


# ===========================================================================
# Firmware version check
# ===========================================================================

@_SKIP_QT
class TestFirmwareCheck(unittest.TestCase):

    def test_matching_major_no_warning(self):
        sm = SerialManager()
        warnings = []
        sm.firmware_warning.connect(warnings.append)
        sm._check_firmware("1.0.0")
        self.assertEqual(warnings, [])

    def test_mismatched_major_emits_warning(self):
        sm = SerialManager()
        warnings = []
        sm.firmware_warning.connect(warnings.append)
        sm._check_firmware("2.0.0")   # app is 1.x.x
        self.assertEqual(len(warnings), 1)
        self.assertIn("2.0.0", warnings[0])

    def test_unparseable_version_emits_warning(self):
        sm = SerialManager()
        warnings = []
        sm.firmware_warning.connect(warnings.append)
        sm._check_firmware("unknown")
        self.assertEqual(len(warnings), 1)

    def test_empty_version_emits_warning(self):
        sm = SerialManager()
        warnings = []
        sm.firmware_warning.connect(warnings.append)
        sm._check_firmware("")
        self.assertEqual(len(warnings), 1)


# ===========================================================================
# set_timeout
# ===========================================================================

@_SKIP_QT
class TestSetTimeout(unittest.TestCase):

    def test_set_timeout_updates_value(self):
        sm = SerialManager()
        sm.set_timeout(8000)
        self.assertEqual(sm._timeout_ms, 8000)

    def test_set_timeout_clamps_low_values(self):
        sm = SerialManager()
        sm.set_timeout(10)
        self.assertGreaterEqual(sm._timeout_ms, 100)


# ===========================================================================
# Port discovery
# ===========================================================================

@unittest.skipUnless(_HAS_SERIAL, "pyserial not installed")
class TestListPorts(unittest.TestCase):

    def test_returns_list(self):
        with patch("core.serial_manager.serial.tools.list_ports.comports",
                   return_value=[]):
            ports = SerialManager.list_ports()
        self.assertIsInstance(ports, list)

    @unittest.skipUnless(_HAS_QT, "PyQt6 not installed")
    def test_returns_strings(self):
        fake_port = MagicMock()
        fake_port.device = "COM3"
        with patch("core.serial_manager.serial.tools.list_ports.comports",
                   return_value=[fake_port]):
            ports = SerialManager.list_ports()
        self.assertEqual(ports, ["COM3"])

    @unittest.skipUnless(_HAS_QT, "PyQt6 not installed")
    def test_empty_when_no_ports(self):
        with patch("core.serial_manager.serial.tools.list_ports.comports",
                   return_value=[]):
            ports = SerialManager.list_ports()
        self.assertEqual(ports, [])


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
