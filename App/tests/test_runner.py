"""
tests/test_runner.py
~~~~~~~~~~~~~~~~~~~~
Unit tests for core.test_runner.TestRunner and its module-level helpers.

Strategy
--------
TestRunner is a QObject that runs in a QThread and communicates with the
Arduino via SerialManager.  To test it without hardware (or a display):

  1. We test all pure-Python logic (sequence building, stimulus decisions,
     adjacency helpers) directly without any Qt plumbing.

  2. For the full Runner integration tests we use a MockSerialManager that
     records commands and injects synthetic ArduinoResponse objects, and run
     the runner synchronously on the main thread by calling runner.run()
     directly (bypassing QThread).  This requires PyQt6, so those tests are
     skipped automatically when the library is absent.

Coverage targets
----------------
_find_adjacent_pairs        — correctness, cross-panel, single pad
TestRunner._build_sequence  — SEQUENTIAL, RANDOM, PSEUDO_RANDOM, dual-touch
TestRunner._decide_stimulus — white/selective, colour codes
TestRunner.run              — trial count, signal emissions, cancel,
                              warmup separation, empty-pad early exit,
                              omission and commission recording
"""

from __future__ import annotations

import sys
import pathlib
import random
import threading
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.models import (
    TestConfiguration, TestType, PadOrder, PadConfig,
    TrialResult, SessionResult,
)
from tests.conftest import make_config, make_dual_config, make_pads

# ---------------------------------------------------------------------------
# Guard imports that depend on pyserial and/or PyQt6
# ---------------------------------------------------------------------------
try:
    from core.serial_manager import (
        ArduinoResponse, COLOR_WHITE, COLOR_GREEN, COLOR_RED,
    )
    from core.test_runner import _find_adjacent_pairs
    _HAS_SERIAL = True
except ImportError:
    _HAS_SERIAL = False
    ArduinoResponse = None
    COLOR_WHITE = COLOR_GREEN = COLOR_RED = 0
    def _find_adjacent_pairs(pads): return []

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    from core.test_runner import TestRunner
    from core.serial_manager import SerialManager
    _HAS_QT = _HAS_SERIAL
except ImportError:
    _HAS_QT = False

_SKIP_QT = unittest.skipUnless(_HAS_QT, "PyQt6 not installed — skipping Qt tests")
_SKIP_SERIAL = unittest.skipUnless(_HAS_SERIAL, "pyserial not installed")


# ===========================================================================
# _find_adjacent_pairs  (pure Python, no Qt)
# ===========================================================================

@_SKIP_SERIAL
class TestFindAdjacentPairs(unittest.TestCase):

    def _pads(self, *indices, panel=0) -> list[PadConfig]:
        return [PadConfig(panel=panel, pad=i) for i in indices]

    def test_horizontal_pair(self):
        pads  = self._pads(0, 1)         # col 0 and col 1, same row
        pairs = _find_adjacent_pairs(pads)
        self.assertEqual(len(pairs), 1)

    def test_vertical_pair(self):
        pads  = self._pads(0, 4)         # row 0 and row 1, same col
        pairs = _find_adjacent_pairs(pads)
        self.assertEqual(len(pairs), 1)

    def test_diagonal_not_adjacent(self):
        pads  = self._pads(0, 5)         # (row0,col0) and (row1,col1)
        pairs = _find_adjacent_pairs(pads)
        self.assertEqual(len(pairs), 0)

    def test_two_apart_not_adjacent(self):
        pads  = self._pads(0, 2)         # col 0 and col 2
        pairs = _find_adjacent_pairs(pads)
        self.assertEqual(len(pairs), 0)

    def test_single_pad_no_pairs(self):
        pads  = self._pads(5)
        pairs = _find_adjacent_pairs(pads)
        self.assertEqual(len(pairs), 0)

    def test_empty_list(self):
        self.assertEqual(_find_adjacent_pairs([]), [])

    def test_cross_panel_not_adjacent(self):
        a = PadConfig(panel=0, pad=0)
        b = PadConfig(panel=1, pad=1)    # adjacent indices but different panel
        pairs = _find_adjacent_pairs([a, b])
        self.assertEqual(len(pairs), 0)

    def test_multiple_pairs_in_row(self):
        # pads 0,1,2,3 in row 0 → three adjacent pairs: (0,1),(1,2),(2,3)
        pads  = self._pads(0, 1, 2, 3)
        pairs = _find_adjacent_pairs(pads)
        self.assertEqual(len(pairs), 3)

    def test_l_shape_correct_pair_count(self):
        # pads 0,1,4 → (0,1) horizontal, (0,4) vertical = 2 pairs
        pads  = self._pads(0, 1, 4)
        pairs = _find_adjacent_pairs(pads)
        self.assertEqual(len(pairs), 2)

    def test_returned_pairs_are_tuples(self):
        pads  = self._pads(0, 1)
        pairs = _find_adjacent_pairs(pads)
        self.assertIsInstance(pairs[0], tuple)
        self.assertEqual(len(pairs[0]), 2)

    def test_all_16_pads_pair_count(self):
        # Full 4×4 grid: 12 horizontal + 12 vertical = 24 pairs
        pads  = [PadConfig(0, i) for i in range(16)]
        pairs = _find_adjacent_pairs(pads)
        self.assertEqual(len(pairs), 24)


# ===========================================================================
# Sequence building  (pure logic extracted from TestRunner._build_sequence)
# ===========================================================================

def _build_sequence_direct(cfg: TestConfiguration,
                            active_pads: list[PadConfig]) -> list:
    """
    Call _build_sequence through a real (but idle) TestRunner instance.
    Requires PyQt6.
    """
    if not _HAS_QT:
        raise unittest.SkipTest("PyQt6 not installed")
    mock_serial = _make_mock_serial()
    runner = TestRunner(mock_serial, cfg, "tester")
    return runner._build_sequence(active_pads, cfg.num_trials)


@unittest.skipUnless(_HAS_QT, "PyQt6 not installed")
class TestBuildSequence(unittest.TestCase):

    def setUp(self):
        self.pads = make_pads(indices=[0, 1, 2, 3])

    def test_sequential_length(self):
        cfg = make_config(pad_order=PadOrder.SEQUENTIAL, num_trials=8,
                          pad_indices=[0,1,2,3])
        seq = _build_sequence_direct(cfg, self.pads)
        self.assertEqual(len(seq), 8)

    def test_sequential_cycles_correctly(self):
        # 4 pads, 8 trials → pads should cycle: 0,1,2,3,0,1,2,3
        cfg = make_config(pad_order=PadOrder.SEQUENTIAL, num_trials=8,
                          pad_indices=[0,1,2,3])
        seq = _build_sequence_direct(cfg, self.pads)
        pad_indices = [item[0].pad for item in seq]
        self.assertEqual(pad_indices, [0,1,2,3,0,1,2,3])

    def test_random_length(self):
        cfg = make_config(pad_order=PadOrder.RANDOM, num_trials=10,
                          pad_indices=[0,1,2,3])
        seq = _build_sequence_direct(cfg, self.pads)
        self.assertEqual(len(seq), 10)

    def test_random_only_uses_active_pads(self):
        cfg = make_config(pad_order=PadOrder.RANDOM, num_trials=20,
                          pad_indices=[0,1,2,3])
        seq = _build_sequence_direct(cfg, self.pads)
        for primary, _ in seq:
            self.assertIn(primary.pad, [0, 1, 2, 3])

    def test_pseudo_random_no_immediate_repeat(self):
        cfg = make_config(pad_order=PadOrder.PSEUDO_RANDOM, num_trials=20,
                          pad_indices=[0,1,2,3])
        seq = _build_sequence_direct(cfg, self.pads)
        for i in range(1, len(seq)):
            self.assertNotEqual(seq[i][0].pad, seq[i-1][0].pad,
                                msg=f"Immediate repeat at position {i}")

    def test_pseudo_random_length(self):
        cfg = make_config(pad_order=PadOrder.PSEUDO_RANDOM, num_trials=15,
                          pad_indices=[0,1,2,3])
        seq = _build_sequence_direct(cfg, self.pads)
        self.assertEqual(len(seq), 15)

    def test_dual_touch_uses_adjacent_pairs(self):
        cfg = make_dual_config(num_trials=6, pad_order=PadOrder.SEQUENTIAL)
        pads = make_pads(indices=[0, 1])   # adjacent
        seq = _build_sequence_direct(cfg, pads)
        for primary, secondary in seq:
            self.assertIsNotNone(secondary)
            self.assertTrue(primary.is_adjacent_to(secondary))

    def test_dual_touch_falls_back_when_no_pairs(self):
        # pads 0 and 5 are not adjacent → fallback to single pad
        cfg = make_dual_config(num_trials=4)
        cfg.pads = [PadConfig(0, 0), PadConfig(0, 5)]
        seq = _build_sequence_direct(cfg, cfg.pads)
        self.assertEqual(len(seq), 4)   # should not crash

    def test_empty_active_pads_returns_empty_sequence(self):
        cfg = make_config(num_trials=5)
        seq = _build_sequence_direct(cfg, [])
        self.assertEqual(seq, [])


# ===========================================================================
# Stimulus decision  (pure Python static method)
# ===========================================================================

@unittest.skipUnless(_HAS_QT, "PyQt6 not installed")
class TestDecideStimulus(unittest.TestCase):

    def test_single_white_always_expect(self):
        cfg = make_config(test_type=TestType.SINGLE_WHITE)
        for _ in range(20):
            expect, color = TestRunner._decide_stimulus(cfg)
            self.assertTrue(expect)
            self.assertEqual(color, COLOR_WHITE)

    def test_double_white_always_expect(self):
        cfg = make_config(test_type=TestType.DOUBLE_WHITE)
        for _ in range(10):
            expect, color = TestRunner._decide_stimulus(cfg)
            self.assertTrue(expect)
            self.assertEqual(color, COLOR_WHITE)

    def test_selective_green_when_expect(self):
        cfg = make_config(test_type=TestType.SINGLE_SELECTIVE,
                          green_red_ratio=1.0)  # always expect
        expect, color = TestRunner._decide_stimulus(cfg)
        self.assertTrue(expect)
        self.assertEqual(color, COLOR_GREEN)

    def test_selective_red_when_not_expect(self):
        cfg = make_config(test_type=TestType.SINGLE_SELECTIVE,
                          green_red_ratio=0.0)  # never expect
        expect, color = TestRunner._decide_stimulus(cfg)
        self.assertFalse(expect)
        self.assertEqual(color, COLOR_RED)

    def test_selective_ratio_approximate(self):
        """With ratio=0.5 roughly half the trials should be green."""
        cfg = make_config(test_type=TestType.SINGLE_SELECTIVE,
                          green_red_ratio=0.5)
        random.seed(42)
        greens = sum(1 for _ in range(200)
                     if TestRunner._decide_stimulus(cfg)[0])
        # Allow ±15 % tolerance
        self.assertGreater(greens, 70)
        self.assertLess(greens, 130)

    def test_double_selective_uses_green_red_colors(self):
        cfg = make_config(test_type=TestType.DOUBLE_SELECTIVE,
                          green_red_ratio=1.0)
        _, color = TestRunner._decide_stimulus(cfg)
        self.assertEqual(color, COLOR_GREEN)


# ===========================================================================
# Mock serial helper
# ===========================================================================

def _make_mock_serial():
    """Return a MagicMock that looks like a SerialManager with the right signals."""
    if not _HAS_QT:
        return MagicMock()

    class MockSerial(QObject):
        """Minimal SerialManager stand-in for test use."""
        response_received = pyqtSignal(object)

        def __init__(self):
            super().__init__()
            self.commands: list[str] = []
            self._is_connected = True
            self._response: ArduinoResponse | None = None

        @property
        def is_connected(self):
            return self._is_connected

        def send_test_start(self):
            self.commands.append("test_start")

        def send_test_end(self):
            self.commands.append("test_end")

        def send_single_touch(self, panel, pad, color, expect_touch, timeout_ms):
            self.commands.append(
                f"single:{panel},{pad},color={color},expect={expect_touch}"
            )
            if self._response is not None:
                r = self._response
                # Fire the signal from this thread; runner is also on this thread
                self.response_received.emit(r)

        def send_dual_touch(self, panel, pad1, pad2, color, expect_touch, timeout_ms):
            self.commands.append(
                f"dual:{panel},{pad1},{pad2},color={color},expect={expect_touch}"
            )
            if self._response is not None:
                self.response_received.emit(self._response)

        def set_response(self, resp: ArduinoResponse):
            self._response = resp

    return MockSerial()


def _make_ack(panel=0, pad=0, touched=True, rt=300) -> ArduinoResponse:
    return ArduinoResponse(panel=panel, pad=pad, touched=touched,
                           response_time_ms=rt)


def _make_timeout(rt=2000) -> ArduinoResponse:
    return ArduinoResponse(panel=0, pad=0, touched=False,
                           response_time_ms=rt,
                           error="Timeout", is_timeout=True)


# ===========================================================================
# Full runner integration  (Qt required)
# ===========================================================================

@_SKIP_QT
class TestRunnerIntegration(unittest.TestCase):
    """
    Run TestRunner.run() synchronously on the main thread.

    The MockSerial fires response_received immediately inside send_single_touch,
    so _wait_for_response() unblocks in the same call stack without needing a
    real QThread.
    """

    def _run(self, cfg, response=None, participant="P001"):
        mock_serial = _make_mock_serial()
        if response is not None:
            mock_serial.set_response(response)
        else:
            mock_serial.set_response(_make_ack())

        # Capture emitted signals
        finished_sessions = []
        cancelled_signals = []
        trials_completed  = []
        progress_updates  = []

        runner = TestRunner(mock_serial, cfg, participant)
        runner.test_finished.connect(finished_sessions.append)
        runner.test_cancelled.connect(lambda: cancelled_signals.append(True))
        runner.trial_completed.connect(trials_completed.append)
        runner.progress_updated.connect(
            lambda cur, tot: progress_updates.append((cur, tot)))

        # Patch time.sleep so tests run instantly
        with patch("core.test_runner.time.sleep"):
            runner.run()

        return runner, mock_serial, finished_sessions, cancelled_signals, \
               trials_completed, progress_updates

    def test_run_emits_test_finished(self):
        cfg = make_config(num_trials=3, isi_ms=0)
        _, _, finished, _, _, _ = self._run(cfg)
        self.assertEqual(len(finished), 1)

    def test_run_correct_trial_count(self):
        cfg = make_config(num_trials=5, isi_ms=0)
        _, _, finished, _, trials, _ = self._run(cfg)
        self.assertEqual(len(trials), 5)

    def test_run_session_participant_id(self):
        cfg = make_config(num_trials=2, isi_ms=0)
        _, _, finished, _, _, _ = self._run(cfg, participant="Alice")
        self.assertEqual(finished[0].participant_id, "Alice")

    def test_run_session_has_end_time(self):
        cfg = make_config(num_trials=2, isi_ms=0)
        _, _, finished, _, _, _ = self._run(cfg)
        self.assertTrue(finished[0].end_time)

    def test_run_progress_updates_match_trials(self):
        cfg = make_config(num_trials=4, isi_ms=0)
        _, _, _, _, _, progress = self._run(cfg)
        self.assertEqual(len(progress), 4)
        self.assertEqual(progress[-1], (4, 4))

    def test_run_sends_test_start_and_end(self):
        cfg = make_config(num_trials=2, isi_ms=0)
        _, mock_serial, _, _, _, _ = self._run(cfg)
        self.assertIn("test_start", mock_serial.commands)
        self.assertIn("test_end",   mock_serial.commands)

    def test_run_sends_one_command_per_trial(self):
        cfg = make_config(num_trials=3, isi_ms=0,
                          pad_order=PadOrder.SEQUENTIAL)
        _, mock_serial, _, _, _, _ = self._run(cfg)
        single_touch_cmds = [c for c in mock_serial.commands
                             if c.startswith("single:")]
        self.assertEqual(len(single_touch_cmds), 3)

    def test_run_touch_recorded_in_trial(self):
        cfg = make_config(num_trials=1, isi_ms=0)
        _, _, _, _, trials, _ = self._run(cfg, response=_make_ack(rt=250))
        self.assertTrue(trials[0].actual_touch)
        self.assertEqual(trials[0].reaction_time_ms, 250)

    def test_run_timeout_recorded_as_no_touch(self):
        cfg = make_config(num_trials=1, isi_ms=0, timeout_ms=2000)
        _, _, _, _, trials, _ = self._run(cfg, response=_make_timeout(rt=2000))
        self.assertFalse(trials[0].actual_touch)
        self.assertEqual(trials[0].reaction_time_ms, 2000)

    def test_run_empty_pads_exits_early(self):
        cfg = make_config(num_trials=5, isi_ms=0)
        for p in cfg.pads:
            p.faulty = True
        _, _, finished, _, trials, _ = self._run(cfg)
        # Should still emit test_finished with zero trials
        self.assertEqual(len(finished), 1)
        self.assertEqual(len(trials), 0)

    def test_warmup_trials_not_in_scored(self):
        cfg = make_config(num_trials=3, warmup_trials=2, isi_ms=0)
        _, _, finished, _, trials, _ = self._run(cfg)
        session = finished[0]
        warmup_count = len(session.warmup_trials)
        scored_count = len(session.scored_trials)
        self.assertEqual(warmup_count, 2)
        self.assertEqual(scored_count, 3)

    def test_warmup_trials_not_in_progress_updates(self):
        """Progress signals should only fire for scored trials."""
        cfg = make_config(num_trials=3, warmup_trials=2, isi_ms=0)
        _, _, _, _, _, progress = self._run(cfg)
        self.assertEqual(len(progress), 3)

    def test_cancel_stops_run(self):
        cfg = make_config(num_trials=10, isi_ms=0)
        mock_serial = _make_mock_serial()
        mock_serial.set_response(_make_ack())

        cancelled = []
        trials    = []

        runner = TestRunner(mock_serial, cfg, "P")
        runner.test_cancelled.connect(lambda: cancelled.append(True))
        runner.trial_completed.connect(trials.append)

        call_count = [0]
        original_send = mock_serial.send_single_touch

        def send_and_maybe_cancel(panel, pad, color, expect_touch, timeout_ms):
            call_count[0] += 1
            original_send(panel, pad, color, expect_touch, timeout_ms)
            if call_count[0] == 3:
                runner.cancel()

        mock_serial.send_single_touch = send_and_maybe_cancel

        with patch("core.test_runner.time.sleep"):
            runner.run()

        self.assertEqual(len(cancelled), 1)
        self.assertLess(len(trials), 10)

    def test_dual_touch_sends_dual_command(self):
        cfg = make_dual_config(num_trials=2, isi_ms=0,
                               pad_order=PadOrder.SEQUENTIAL)
        _, mock_serial, _, _, _, _ = self._run(cfg)
        dual_cmds = [c for c in mock_serial.commands if c.startswith("dual:")]
        self.assertEqual(len(dual_cmds), 2)

    def test_omission_error_recorded(self):
        cfg = make_config(test_type=TestType.SINGLE_WHITE, num_trials=1,
                          isi_ms=0)
        _, _, _, _, trials, _ = self._run(
            cfg, response=_make_ack(touched=False, rt=2000))
        t = trials[0]
        self.assertTrue(t.expect_touch)
        self.assertFalse(t.actual_touch)
        self.assertTrue(t.is_omission_error)

    def test_anonymous_participant_when_blank(self):
        cfg = make_config(num_trials=1, isi_ms=0)
        _, _, finished, _, _, _ = self._run(cfg, participant="  ")
        self.assertEqual(finished[0].participant_id, "anonymous")


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
