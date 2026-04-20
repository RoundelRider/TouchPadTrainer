"""
core.test_runner
~~~~~~~~~~~~~~~~
Drives the Arduino through a complete test session.

Design
------
TestRunner is a QObject intended to be moved onto a QThread by the UI:

    runner = TestRunner(serial, config, participant_id)
    thread = QThread()
    runner.moveToThread(thread)
    thread.started.connect(runner.run)
    thread.start()

The runner emits Qt signals for every observable event so the UI can update
without polling.  It never touches any widget directly.

Response collection uses a threading.Event bridge:  the SerialManager worker
thread emits response_received, which is connected to a local slot that sets
the event, allowing _wait_for_response() to block in the runner thread without
spinning.
"""

from __future__ import annotations

import datetime
import random
import threading
import time
import logging
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from core.serial_manager import (
    SerialManager, ArduinoResponse,
    COLOR_WHITE, COLOR_GREEN, COLOR_RED,
)
# Note: COLOR_* are now plain strings ("WHITE", "GREEN", "RED") matching
# the TrainerPanel text protocol.  The rest of this module is unchanged.
from data.models import (
    TestConfiguration, SessionResult, TrialResult,
    TestType, PadOrder, PadConfig,
)

logger = logging.getLogger(__name__)


class TestRunner(QObject):
    """
    Executes one test session and emits results back to the UI thread.

    Signals
    -------
    warmup_started      : warm-up phase is beginning
    scored_started      : scored phase is beginning
    trial_started(panel, pad, color, expect_touch)
                        : a new trial has begun; the pad is now lit
    trial_completed(TrialResult)
                        : a trial has finished (touch recorded or timed out)
    progress_updated(current, total)
                        : scored trial index updated
    rest_prompt(duration_ms)
                        : runner is pausing for a rest break
    test_finished(SessionResult)
                        : all trials done; session data is complete
    test_cancelled      : run() returned early because cancel() was called
    """

    warmup_started   = pyqtSignal()
    scored_started   = pyqtSignal()
    trial_started    = pyqtSignal(int, int, int, bool)  # panel, pad, color, expect
    trial_completed  = pyqtSignal(object)               # TrialResult
    progress_updated = pyqtSignal(int, int)             # current, total
    rest_prompt      = pyqtSignal(int)                  # duration_ms
    test_finished    = pyqtSignal(object)               # SessionResult
    test_cancelled   = pyqtSignal()

    # How many extra milliseconds to allow beyond the configured timeout
    # when waiting for a serial response (network + processing overhead).
    _RESPONSE_MARGIN_MS: int = 500

    def __init__(
        self,
        serial: SerialManager,
        config: TestConfiguration,
        participant_id: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._serial       = serial
        self._config       = config
        self._participant  = participant_id.strip() or "anonymous"
        self._cancel_flag  = False

        # Bridge between the serial worker signal and _wait_for_response().
        self._response_event  = threading.Event()
        self._pending_response: Optional[ArduinoResponse] = None
        self._response_lock   = threading.Lock()

        # Connect once for the lifetime of this runner.
        self._serial.response_received.connect(self._on_response_received)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Request the run loop to stop after the current trial completes."""
        logger.info("Test cancellation requested")
        self._cancel_flag = True

    # ------------------------------------------------------------------
    # Main run method  (called by QThread.started)
    # ------------------------------------------------------------------

    @pyqtSlot()
    def run(self) -> None:
        """Execute the full test session."""
        cfg = self._config
        logger.info(
            "Test started — config=%r participant=%r trials=%d",
            cfg.name, self._participant, cfg.num_trials,
        )

        session = SessionResult(
            participant_id=self._participant,
            config_name=cfg.name,
        )

        active_pads = [p for p in cfg.pads if not p.faulty]
        if not active_pads:
            logger.warning("No active (non-faulty) pads in configuration")
            session.end_time = _now()
            self.test_finished.emit(session)
            return

        self._serial.send_test_start()
        time.sleep(0.5)   # let the start-pattern blink finish

        # ---- Warm-up block (not scored) --------------------------------
        if cfg.warmup_trials > 0:
            logger.debug("Running %d warm-up trials", cfg.warmup_trials)
            self.warmup_started.emit()
            cancelled = self._run_block(
                session, active_pads, cfg.warmup_trials, is_warmup=True
            )
            if cancelled:
                self._finish_cancelled(session)
                return

        # ---- Scored block ----------------------------------------------
        logger.debug("Running %d scored trials", cfg.num_trials)
        self.scored_started.emit()
        cancelled = self._run_block(
            session, active_pads, cfg.num_trials, is_warmup=False
        )
        if cancelled:
            self._finish_cancelled(session)
            return

        # ---- Wrap up ---------------------------------------------------
        self._serial.send_test_end()
        session.end_time = _now()
        logger.info(
            "Test finished — %d trials, overall mean RT %d ms",
            len(session.scored_trials),
            session.overall_stats().get("mean", 0),
        )
        self.test_finished.emit(session)
        self._cleanup()

    # ------------------------------------------------------------------
    # Trial block execution
    # ------------------------------------------------------------------

    def _run_block(
        self,
        session: SessionResult,
        active_pads: list[PadConfig],
        num_trials: int,
        is_warmup: bool,
    ) -> bool:
        """
        Run *num_trials* trials, appending TrialResult objects to *session*.

        Returns True if the block was cancelled mid-way, False if it
        completed normally.
        """
        cfg = self._config
        sequence = self._build_sequence(active_pads, num_trials)
        total_scored = num_trials  # used for progress reporting

        for i, (pad_cfg, pad2_cfg) in enumerate(sequence):
            if self._cancel_flag:
                return True

            # ---- Optional rest break -----------------------------------
            if (
                not is_warmup
                and cfg.rest_every_n > 0
                and i > 0
                and i % cfg.rest_every_n == 0
            ):
                logger.debug("Rest break after trial %d", i)
                self.rest_prompt.emit(cfg.rest_duration_ms)
                self._interruptible_sleep(cfg.rest_duration_ms / 1_000.0)
                if self._cancel_flag:
                    return True

            # ---- Decide colour / expect_touch --------------------------
            expect_touch, color = self._decide_stimulus(cfg)

            # ---- Emit so live grid lights up ---------------------------
            self.trial_started.emit(pad_cfg.panel, pad_cfg.pad, color, expect_touch)

            # ---- Send command to Arduino --------------------------------
            if pad2_cfg is None:
                self._serial.send_single_touch(
                    pad_cfg.pad + 1, color,   # +1: serial API is 1-based
                    expect_touch, cfg.timeout_ms,
                )
            else:
                self._serial.send_dual_touch(
                    pad_cfg.pad + 1, pad2_cfg.pad + 1, color,  # +1: 1-based
                    expect_touch, cfg.timeout_ms,
                )

            # ---- Collect response --------------------------------------
            wait_ms = cfg.timeout_ms + self._RESPONSE_MARGIN_MS
            response = self._wait_for_response(wait_ms)

            if response is None or response.is_timeout:
                rt      = cfg.timeout_ms
                touched = False
            else:
                rt      = response.response_time_ms
                touched = response.touched

            # ---- Record trial result -----------------------------------
            trial = TrialResult(
                trial_num=i + 1,
                panel=pad_cfg.panel,
                pad=pad_cfg.pad,
                pad2=pad2_cfg.pad if pad2_cfg is not None else None,
                expect_touch=expect_touch,
                actual_touch=touched,
                reaction_time_ms=rt,
                is_warmup=is_warmup,
            )
            session.trials.append(trial)
            self.trial_completed.emit(trial)

            if not is_warmup:
                self.progress_updated.emit(i + 1, total_scored)

            # ---- Inter-stimulus interval --------------------------------
            if cfg.isi_ms > 0:
                self._interruptible_sleep(cfg.isi_ms / 1_000.0)

        return False   # completed normally

    # ------------------------------------------------------------------
    # Sequence building
    # ------------------------------------------------------------------

    def _build_sequence(
        self,
        active_pads: list[PadConfig],
        num_trials: int,
    ) -> list[tuple[PadConfig, Optional[PadConfig]]]:
        """
        Return an ordered list of (primary_pad, secondary_pad_or_None) tuples.

        For dual-touch test types the pool is adjacent pairs; for single-touch
        types pad2 is always None.
        """
        cfg = self._config
        is_dual = cfg.test_type in (TestType.DOUBLE_WHITE, TestType.DOUBLE_SELECTIVE)

        if is_dual:
            pool = _find_adjacent_pairs(active_pads)
            if not pool:
                logger.warning(
                    "Dual-touch mode requested but no adjacent pairs found; "
                    "falling back to single-pad mode"
                )
                pool = [(p, None) for p in active_pads]
        else:
            pool = [(p, None) for p in active_pads]

        if not pool:
            return []

        if cfg.pad_order == PadOrder.SEQUENTIAL:
            return [pool[i % len(pool)] for i in range(num_trials)]

        if cfg.pad_order == PadOrder.RANDOM:
            return [random.choice(pool) for _ in range(num_trials)]

        # PSEUDO_RANDOM — no immediate repeat of the same pad/pair
        sequence: list[tuple[PadConfig, Optional[PadConfig]]] = []
        last: Optional[tuple] = None
        for _ in range(num_trials):
            candidates = [item for item in pool if item != last]
            if not candidates:
                candidates = pool
            chosen = random.choice(candidates)
            sequence.append(chosen)
            last = chosen
        return sequence

    # ------------------------------------------------------------------
    # Stimulus decision
    # ------------------------------------------------------------------

    @staticmethod
    def _decide_stimulus(cfg: TestConfiguration) -> tuple[bool, int]:
        """
        Return (expect_touch, color_code) for the next trial.

        Selective modes randomly decide whether to expect a touch based on the
        configured green:red ratio.
        """
        selective = cfg.test_type in (
            TestType.SINGLE_SELECTIVE, TestType.DOUBLE_SELECTIVE
        )
        if selective:
            expect = random.random() < cfg.green_red_ratio
            color  = COLOR_GREEN if expect else COLOR_RED
        else:
            expect = True
            color  = COLOR_WHITE
        return expect, color

    # ------------------------------------------------------------------
    # Response waiting  (thread-safe event bridge)
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def _on_response_received(self, response: ArduinoResponse) -> None:
        """
        Slot connected to SerialManager.response_received.

        Qt delivers this in whatever thread the signal was emitted from
        (the serial worker thread).  We store the response and set the event
        so _wait_for_response() can unblock.
        """
        with self._response_lock:
            self._pending_response = response
        self._response_event.set()

    def _wait_for_response(self, timeout_ms: int) -> Optional[ArduinoResponse]:
        """
        Block the runner thread until a response arrives or *timeout_ms* elapses.

        Returns the ArduinoResponse, or None if the wait timed out without
        any response being delivered.
        """
        self._response_event.clear()
        with self._response_lock:
            self._pending_response = None

        fired = self._response_event.wait(timeout=timeout_ms / 1_000.0)
        if not fired:
            logger.warning("_wait_for_response timed out after %d ms", timeout_ms)
            return None

        with self._response_lock:
            return self._pending_response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in short increments so cancel() is noticed quickly."""
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._cancel_flag:
            time.sleep(min(0.05, end - time.monotonic()))

    def _finish_cancelled(self, session: SessionResult) -> None:
        session.end_time = _now()
        logger.info("Test cancelled after %d trials", len(session.trials))
        self.test_cancelled.emit()
        self._cleanup()

    def _cleanup(self) -> None:
        """Disconnect the response signal to avoid stale connections."""
        try:
            self._serial.response_received.disconnect(self._on_response_received)
        except RuntimeError:
            pass   # already disconnected


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.datetime.now().isoformat()


def _find_adjacent_pairs(
    pads: list[PadConfig],
) -> list[tuple[PadConfig, PadConfig]]:
    """
    Return every pair of pads that are horizontally or vertically adjacent
    on the same panel.

    Pad indices are 0-based within a 4-column grid, so pad N occupies
    row = N // 4, col = N % 4.
    """
    pairs: list[tuple[PadConfig, PadConfig]] = []
    for i, a in enumerate(pads):
        for b in pads[i + 1:]:
            if a.panel != b.panel:
                continue
            row_a, col_a = divmod(a.pad, 4)
            row_b, col_b = divmod(b.pad, 4)
            horizontal = (row_a == row_b) and abs(col_a - col_b) == 1
            vertical   = (col_a == col_b) and abs(row_a - row_b) == 1
            if horizontal or vertical:
                pairs.append((a, b))
    return pairs
