"""
data — models and persistence for the TouchPad test program.

Public surface
--------------
Models (data/models.py)
    TestType            — enum of available test modes
    PadOrder            — enum of pad-selection strategies
    ReactionBand        — one coloured RT band in a configuration
    PadConfig           — panel + pad index + faulty flag
    TestConfiguration   — complete named test configuration
    TrialResult         — result of a single trial
    SessionResult       — full session with statistics helpers
    CalibrationProfile  — per-pad capacitive baseline data

Storage (data/storage.py)
    StorageManager      — load/save configs, sessions, CSV export
    app_data_dir        — resolve the platform-appropriate data root
"""

from data.models import (
    TestType,
    PadOrder,
    ReactionBand,
    PadConfig,
    TestConfiguration,
    TrialResult,
    SessionResult,
    CalibrationProfile,
)
from data.storage import StorageManager, app_data_dir

__all__ = [
    # models
    "TestType",
    "PadOrder",
    "ReactionBand",
    "PadConfig",
    "TestConfiguration",
    "TrialResult",
    "SessionResult",
    "CalibrationProfile",
    # storage
    "StorageManager",
    "app_data_dir",
]
