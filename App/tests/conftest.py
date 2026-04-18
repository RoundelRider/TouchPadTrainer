"""
tests/conftest.py
~~~~~~~~~~~~~~~~~
Shared pytest fixtures and helper factories used across the test suite.

Imported automatically by pytest; also importable directly by unittest
runners via  from tests.conftest import make_config, make_session, …
"""

from __future__ import annotations

import sys
import os
import tempfile
import pathlib

# Ensure the project root is on sys.path so imports work whether tests
# are run from the project root or from inside the tests/ directory.
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from data.models import (
    TestConfiguration,
    TestType,
    PadOrder,
    PadConfig,
    ReactionBand,
    TrialResult,
    SessionResult,
    CalibrationProfile,
)
from data.storage import StorageManager


# ---------------------------------------------------------------------------
# Configuration factories
# ---------------------------------------------------------------------------

def make_pads(
    panel: int = 0,
    indices: list[int] | None = None,
) -> list[PadConfig]:
    """Return a list of PadConfig objects for *panel*."""
    if indices is None:
        indices = list(range(16))
    return [PadConfig(panel=panel, pad=i) for i in indices]


def make_config(
    name: str = "Test Config",
    test_type: TestType = TestType.SINGLE_WHITE,
    num_trials: int = 5,
    timeout_ms: int = 2_000,
    isi_ms: int = 0,           # zero so tests run fast
    warmup_trials: int = 0,
    pad_order: PadOrder = PadOrder.SEQUENTIAL,
    num_panels: int = 1,
    pad_indices: list[int] | None = None,
    green_red_ratio: float = 0.5,
    rest_every_n: int = 0,
) -> TestConfiguration:
    """
    Return a minimal but valid TestConfiguration for use in tests.

    ISI defaults to 0 so test blocks complete without sleeping.
    """
    if pad_indices is None:
        pad_indices = [0, 1, 2, 3]   # four pads, first row
    pads = make_pads(panel=0, indices=pad_indices)
    return TestConfiguration(
        name=name,
        test_type=test_type,
        num_trials=num_trials,
        timeout_ms=timeout_ms,
        isi_ms=isi_ms,
        warmup_trials=warmup_trials,
        pad_order=pad_order,
        num_panels=num_panels,
        pads=pads,
        green_red_ratio=green_red_ratio,
        rest_every_n=rest_every_n,
    )


def make_dual_config(**kwargs) -> TestConfiguration:
    """Return a config with two adjacent pads and DOUBLE_WHITE test type."""
    defaults = dict(
        name="Dual Config",
        test_type=TestType.DOUBLE_WHITE,
        pad_indices=[0, 1],          # pads 0 and 1 are horizontally adjacent
        num_trials=4,
    )
    defaults.update(kwargs)
    return make_config(**defaults)


# ---------------------------------------------------------------------------
# Trial / session factories
# ---------------------------------------------------------------------------

def make_trial(
    trial_num: int = 1,
    panel: int = 0,
    pad: int = 0,
    pad2: int | None = None,
    expect_touch: bool = True,
    actual_touch: bool = True,
    reaction_time_ms: int = 350,
    is_warmup: bool = False,
) -> TrialResult:
    return TrialResult(
        trial_num=trial_num,
        panel=panel,
        pad=pad,
        pad2=pad2,
        expect_touch=expect_touch,
        actual_touch=actual_touch,
        reaction_time_ms=reaction_time_ms,
        is_warmup=is_warmup,
    )


def make_session(
    participant_id: str = "P001",
    config_name: str = "Test Config",
    n_hits: int = 5,
    hit_rt: int = 300,
    n_omissions: int = 0,
    n_commissions: int = 0,
) -> SessionResult:
    """
    Build a SessionResult pre-populated with synthetic trials.

    *n_hits*        : scored trials where expect and actual are both True
    *n_omissions*   : expect=True, actual=False
    *n_commissions* : expect=False, actual=True
    """
    s = SessionResult(participant_id=participant_id, config_name=config_name)
    n = 1
    for _ in range(n_hits):
        s.trials.append(make_trial(trial_num=n, reaction_time_ms=hit_rt))
        n += 1
    for _ in range(n_omissions):
        s.trials.append(make_trial(trial_num=n, expect_touch=True,
                                   actual_touch=False, reaction_time_ms=2000))
        n += 1
    for _ in range(n_commissions):
        s.trials.append(make_trial(trial_num=n, expect_touch=False,
                                   actual_touch=True, reaction_time_ms=150))
        n += 1
    return s


# ---------------------------------------------------------------------------
# Storage fixture helper
# ---------------------------------------------------------------------------

class TempStorage:
    """
    Context manager that provides a StorageManager backed by a temporary
    directory that is deleted on exit.

    Usage::

        with TempStorage() as storage:
            storage.save_config(cfg)
            ...
    """

    def __init__(self) -> None:
        self._tmpdir: tempfile.TemporaryDirectory | None = None
        self.storage: StorageManager | None = None

    def __enter__(self) -> StorageManager:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.storage = StorageManager(pathlib.Path(self._tmpdir.name))
        return self.storage

    def __exit__(self, *_) -> None:
        if self._tmpdir:
            self._tmpdir.cleanup()


# ---------------------------------------------------------------------------
# pytest fixtures (only registered when pytest is available)
# ---------------------------------------------------------------------------

try:
    import pytest

    @pytest.fixture
    def tmp_storage():
        """A StorageManager backed by a fresh temporary directory."""
        with TempStorage() as s:
            yield s

    @pytest.fixture
    def simple_config():
        """A minimal single-touch, sequential, 5-trial configuration."""
        return make_config()

    @pytest.fixture
    def dual_config():
        """A dual-touch configuration with two adjacent pads."""
        return make_dual_config()

    @pytest.fixture
    def simple_session():
        """A SessionResult with 5 hit trials at 300 ms each."""
        return make_session()

except ImportError:
    pass   # pytest not installed — fixtures unused by unittest runner
