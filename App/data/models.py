"""
data.models
~~~~~~~~~~~
Pure-Python domain objects for the TouchPad test program.

No Qt, no file I/O, no serial code lives here.  Every class is a plain
dataclass that knows how to serialise itself to/from a dict so that
storage.py can persist it without coupling to the representation.

Class hierarchy
---------------
TestConfiguration
    └── pads: list[PadConfig]
    └── rt_bands: list[ReactionBand]

SessionResult
    └── trials: list[TrialResult]

CalibrationProfile
    └── entries: list[CalibrationEntry]
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import IntEnum
from typing import Optional


# ---------------------------------------------------------------------------
# Module-level helpers  (defined first so dataclass default_factory can use them)
# ---------------------------------------------------------------------------

def _now() -> str:
    """Return the current local time as an ISO-8601 string."""
    return datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TestType(IntEnum):
    """Which stimulus/response paradigm to use."""
    SINGLE_WHITE     = 0  # One pad lit white; touch always expected
    SINGLE_SELECTIVE = 1  # One pad lit green (expect) or red (don't touch)
    DOUBLE_WHITE     = 2  # Two adjacent pads lit white; both must be touched
    DOUBLE_SELECTIVE = 3  # Two adjacent pads lit green or red; selective rule


class PadOrder(IntEnum):
    """How the sequence of pads/pairs is chosen each trial."""
    RANDOM        = 0  # Uniformly random; immediate repeats possible
    PSEUDO_RANDOM = 1  # Random but no two consecutive identical pads/pairs
    SEQUENTIAL    = 2  # Cycle through the active pads in order


# ---------------------------------------------------------------------------
# Configuration building blocks
# ---------------------------------------------------------------------------

@dataclass
class ReactionBand:
    """
    One coloured band in the RT colour scale.

    Bands are sorted by *max_ms* ascending.  A trial whose RT falls at or
    below *max_ms* is assigned *color*.  The last band acts as a catch-all.

    Attributes
    ----------
    max_ms  : Upper bound of this band in milliseconds.
    color   : HTML hex colour string, e.g. ``"#00C800"``.
    label   : Short human-readable label, e.g. ``"Excellent"``.
    """
    max_ms: int
    color:  str
    label:  str

    def to_dict(self) -> dict:
        return {"max_ms": self.max_ms, "color": self.color, "label": self.label}

    @classmethod
    def from_dict(cls, d: dict) -> "ReactionBand":
        return cls(max_ms=int(d["max_ms"]), color=str(d["color"]),
                   label=str(d.get("label", "")))


@dataclass
class PadConfig:
    """
    Identifies a single pad within the panel array and records its state.

    Attributes
    ----------
    panel  : 0-based panel index (0–3).
    pad    : 0-based pad index within the panel (0–15, row-major 4×4).
    faulty : When True the pad is skipped in all tests but retained in the
             layout so its position is preserved.
    """
    panel:  int
    pad:    int
    faulty: bool = False

    # Convenience: human-readable 1-based identifiers
    @property
    def display_panel(self) -> int:
        return self.panel + 1

    @property
    def display_pad(self) -> int:
        return self.pad + 1

    @property
    def row(self) -> int:
        """0-based row in the 4×4 grid."""
        return self.pad // 4

    @property
    def col(self) -> int:
        """0-based column in the 4×4 grid."""
        return self.pad % 4

    def is_adjacent_to(self, other: "PadConfig") -> bool:
        """
        Return True when *other* is horizontally or vertically adjacent and
        on the same panel.
        """
        if self.panel != other.panel:
            return False
        return (
            (self.row == other.row and abs(self.col - other.col) == 1)
            or (self.col == other.col and abs(self.row - other.row) == 1)
        )

    def to_dict(self) -> dict:
        return {"panel": self.panel, "pad": self.pad, "faulty": self.faulty}

    @classmethod
    def from_dict(cls, d: dict) -> "PadConfig":
        return cls(panel=int(d["panel"]), pad=int(d["pad"]),
                   faulty=bool(d.get("faulty", False)))


# ---------------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------------

#: Default reaction-time band colours (best → worst)
_DEFAULT_BAND_COLORS = ["#00C800", "#90EE90", "#FFD700", "#FFD070", "#FF3030"]
_DEFAULT_BAND_LABELS = ["Excellent", "Good", "Fair", "Slow", "Miss"]

#: Maximum number of RT bands allowed
MAX_RT_BANDS = 5


@dataclass
class TestConfiguration:
    """
    A complete, named test configuration.

    Serialisation round-trip
    ------------------------
    cfg.to_json()  → JSON string
    TestConfiguration.from_json(s) → TestConfiguration

    cfg.to_dict()  → plain dict (used by StorageManager)
    TestConfiguration.from_dict(d) → TestConfiguration
    """

    # ---- Identity ----------------------------------------------------------
    name:          str
    id:            str  = field(default_factory=lambda: str(uuid.uuid4()))
    read_only:     bool = False
    last_modified: str  = field(default_factory=lambda: _now())

    # ---- Panel layout -------------------------------------------------------
    num_panels: int             = 1
    pads:       list[PadConfig] = field(default_factory=list)

    # ---- Test type ----------------------------------------------------------
    test_type: TestType = TestType.SINGLE_WHITE

    # ---- Timing & trial count -----------------------------------------------
    timeout_ms:       int = 2_000   # per-trial response window (ms)
    num_trials:       int = 10      # scored trials
    isi_min_ms:       int = 500    # inter-stimulus interval lower bound (ms)
    isi_max_ms:       int = 1_000  # inter-stimulus interval upper bound (ms)
    warmup_trials:    int = 0       # non-scored practice trials
    rest_every_n:     int = 0       # 0 = no rest breaks
    rest_duration_ms: int = 5_000   # how long each rest break lasts

    # Random pre-test delay: a uniformly random pause between the end of
    # the start pattern and the first trial.  Both bounds are in ms.
    # Set both to 0 to disable.  min must be <= max.
    pre_test_delay_min_ms: int = 0
    pre_test_delay_max_ms: int = 0

    # ---- Randomisation ------------------------------------------------------
    pad_order:      PadOrder = PadOrder.PSEUDO_RANDOM
    green_red_ratio: float   = 0.5  # proportion of trials that expect a touch

    # ---- Result display -----------------------------------------------------
    rt_bands: list[ReactionBand] = field(default_factory=list)

    # ---- Post-init ----------------------------------------------------------

    def __post_init__(self) -> None:
        # Coerce enum types in case they were passed as raw ints
        if not isinstance(self.test_type, TestType):
            self.test_type = TestType(int(self.test_type))
        if not isinstance(self.pad_order, PadOrder):
            self.pad_order = PadOrder(int(self.pad_order))
        # Clamp ratio to [0, 1]
        self.green_red_ratio = max(0.0, min(1.0, self.green_red_ratio))
        # Populate default bands if none supplied
        if not self.rt_bands:
            self.reset_default_bands()

    # ---- Band helpers -------------------------------------------------------

    def reset_default_bands(self) -> None:
        """Replace rt_bands with five evenly-spaced default bands."""
        step = max(1, self.timeout_ms // MAX_RT_BANDS)
        self.rt_bands = [
            ReactionBand(
                max_ms=(i + 1) * step,
                color=_DEFAULT_BAND_COLORS[i],
                label=_DEFAULT_BAND_LABELS[i],
            )
            for i in range(MAX_RT_BANDS)
        ]

    def color_for_rt(self, rt_ms: int) -> str:
        """
        Return the HTML colour that corresponds to *rt_ms*.

        Bands are evaluated in ascending order; the first band whose
        *max_ms* is ≥ *rt_ms* wins.  If *rt_ms* exceeds all bands the
        last band's colour is returned.
        """
        for band in sorted(self.rt_bands, key=lambda b: b.max_ms):
            if rt_ms <= band.max_ms:
                return band.color
        return self.rt_bands[-1].color if self.rt_bands else "#888888"

    def band_for_rt(self, rt_ms: int) -> Optional[ReactionBand]:
        """Return the matching ReactionBand object, or None if bands are empty."""
        for band in sorted(self.rt_bands, key=lambda b: b.max_ms):
            if rt_ms <= band.max_ms:
                return band
        return self.rt_bands[-1] if self.rt_bands else None

    # ---- Pad helpers --------------------------------------------------------

    @property
    def active_pads(self) -> list[PadConfig]:
        """All non-faulty pads."""
        return [p for p in self.pads if not p.faulty]

    def adjacent_pairs(self) -> list[tuple[PadConfig, PadConfig]]:
        """Return every pair of active pads that are horizontally/vertically adjacent."""
        active = self.active_pads
        pairs: list[tuple[PadConfig, PadConfig]] = []
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                if a.is_adjacent_to(b):
                    pairs.append((a, b))
        return pairs

    # ---- Validation ---------------------------------------------------------

    def validate(self) -> list[str]:
        """
        Return a list of human-readable problem descriptions, or an empty
        list when the configuration is valid.
        """
        issues: list[str] = []
        if not self.name.strip():
            issues.append("Configuration name must not be empty.")
        if not (1 <= self.num_panels <= 4):
            issues.append("Number of panels must be between 1 and 4.")
        if not self.active_pads:
            issues.append("At least one non-faulty pad must be included.")
        if self.num_trials < 1:
            issues.append("Number of trials must be at least 1.")
        if self.timeout_ms < 100:
            issues.append("Timeout must be at least 100 ms.")
        if not (0.0 <= self.green_red_ratio <= 1.0):
            issues.append("Green:red ratio must be between 0 and 1.")
        if self.isi_min_ms > self.isi_max_ms:
            issues.append(
                "ISI minimum must be less than or equal to ISI maximum.")
        if self.pre_test_delay_min_ms > self.pre_test_delay_max_ms:
            issues.append(
                "Pre-test delay minimum must be less than or equal to maximum.")
        if len(self.rt_bands) > MAX_RT_BANDS:
            issues.append(f"Maximum {MAX_RT_BANDS} reaction-time bands allowed.")
        if self.test_type in (TestType.DOUBLE_WHITE, TestType.DOUBLE_SELECTIVE):
            if not self.adjacent_pairs():
                issues.append(
                    "Dual-touch mode requires at least two adjacent active pads "
                    "on the same panel."
                )
        return issues

    # ---- Serialisation ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name":            self.name,
            "id":              self.id,
            "read_only":       self.read_only,
            "last_modified":   self.last_modified,
            "num_panels":      self.num_panels,
            "pads":            [p.to_dict() for p in self.pads],
            "test_type":       int(self.test_type),
            "timeout_ms":      self.timeout_ms,
            "num_trials":      self.num_trials,
            "isi_min_ms":      self.isi_min_ms,
            "isi_max_ms":      self.isi_max_ms,
            "warmup_trials":   self.warmup_trials,
            "rest_every_n":    self.rest_every_n,
            "rest_duration_ms":self.rest_duration_ms,
            "pre_test_delay_min_ms": self.pre_test_delay_min_ms,
            "pre_test_delay_max_ms": self.pre_test_delay_max_ms,
            "pad_order":       int(self.pad_order),
            "green_red_ratio": self.green_red_ratio,
            "rt_bands":        [b.to_dict() for b in self.rt_bands],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TestConfiguration":
        return cls(
            name            = str(d.get("name", "Unnamed")),
            id              = str(d.get("id", str(uuid.uuid4()))),
            read_only       = bool(d.get("read_only", False)),
            last_modified   = str(d.get("last_modified", _now())),
            num_panels      = int(d.get("num_panels", 1)),
            pads            = [PadConfig.from_dict(p) for p in d.get("pads", [])],
            test_type       = TestType(int(d.get("test_type", 0))),
            timeout_ms      = int(d.get("timeout_ms", 2_000)),
            num_trials      = int(d.get("num_trials", 10)),
            # Legacy configs stored a single "isi_ms"; use it as both
            # bounds so old sessions continue to behave as before.
            isi_min_ms      = int(d.get("isi_min_ms",
                                  d.get("isi_ms", 500))),
            isi_max_ms      = int(d.get("isi_max_ms",
                                  d.get("isi_ms", 1_000))),
            warmup_trials   = int(d.get("warmup_trials", 0)),
            rest_every_n    = int(d.get("rest_every_n", 0)),
            rest_duration_ms= int(d.get("rest_duration_ms", 5_000)),
            pre_test_delay_min_ms = int(d.get("pre_test_delay_min_ms", 0)),
            pre_test_delay_max_ms = int(d.get("pre_test_delay_max_ms", 0)),
            pad_order       = PadOrder(int(d.get("pad_order", 1))),
            green_red_ratio = float(d.get("green_red_ratio", 0.5)),
            rt_bands        = [ReactionBand.from_dict(b)
                               for b in d.get("rt_bands", [])],
        )

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "TestConfiguration":
        import json
        return cls.from_dict(json.loads(s))

    def copy_as_new(self, new_name: str) -> "TestConfiguration":
        """Return a deep copy with a new UUID, name, and timestamp."""
        d = self.to_dict()
        d["id"]            = str(uuid.uuid4())
        d["name"]          = new_name
        d["read_only"]     = False
        d["last_modified"] = _now()
        return TestConfiguration.from_dict(d)

    def __repr__(self) -> str:
        return (f"TestConfiguration(name={self.name!r} id={self.id[:8]}… "
                f"type={self.test_type.name} trials={self.num_trials})")


# ---------------------------------------------------------------------------
# Trial result
# ---------------------------------------------------------------------------

@dataclass
class TrialResult:
    """
    The outcome of a single trial (one or two pads lit, one response window).

    Attributes
    ----------
    trial_num        : 1-based index within the block (warmup or scored).
    panel            : 0-based panel index of the primary pad.
    pad              : 0-based index of the primary pad.
    pad2             : 0-based index of the secondary pad (dual-touch only).
    expect_touch     : True if the participant was supposed to touch the pad(s).
    actual_touch     : True if a valid touch was recorded.
    reaction_time_ms : Time from LED on to touch detection (ms).
                       Equal to the timeout value when no touch occurred.
    timestamp        : ISO-8601 wall-clock time the trial started.
    is_warmup        : True for practice trials that are not scored.
    """

    trial_num:        int
    panel:            int
    pad:              int
    pad2:             Optional[int]
    expect_touch:     bool
    actual_touch:     bool
    reaction_time_ms: int
    timestamp:        str  = field(default_factory=_now)
    is_warmup:        bool = False

    # ---- Error classification -----------------------------------------------

    @property
    def is_hit(self) -> bool:
        """Correctly touched an expected pad."""
        return self.expect_touch and self.actual_touch

    @property
    def is_correct_rejection(self) -> bool:
        """Correctly withheld touch on a no-touch pad."""
        return not self.expect_touch and not self.actual_touch

    @property
    def is_commission_error(self) -> bool:
        """False alarm — touched a red (no-touch) pad."""
        return not self.expect_touch and self.actual_touch

    @property
    def is_omission_error(self) -> bool:
        """Miss — failed to touch a green (expected) pad."""
        return self.expect_touch and not self.actual_touch

    @property
    def is_correct(self) -> bool:
        """True for both hits and correct rejections."""
        return self.expect_touch == self.actual_touch

    # ---- Serialisation ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "trial_num":        self.trial_num,
            "panel":            self.panel,
            "pad":              self.pad,
            "pad2":             self.pad2,
            "expect_touch":     self.expect_touch,
            "actual_touch":     self.actual_touch,
            "reaction_time_ms": self.reaction_time_ms,
            "timestamp":        self.timestamp,
            "is_warmup":        self.is_warmup,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrialResult":
        return cls(
            trial_num        = int(d["trial_num"]),
            panel            = int(d["panel"]),
            pad              = int(d["pad"]),
            pad2             = int(d["pad2"]) if d.get("pad2") is not None else None,
            expect_touch     = bool(d["expect_touch"]),
            actual_touch     = bool(d["actual_touch"]),
            reaction_time_ms = int(d["reaction_time_ms"]),
            timestamp        = str(d.get("timestamp", _now())),
            is_warmup        = bool(d.get("is_warmup", False)),
        )

    def to_csv_row(self, participant_id: str, session_id: str = "") -> list:
        """Return a flat list suitable for a csv.writer row."""
        return [
            participant_id,
            session_id,
            self.timestamp,
            self.panel + 1,          # 1-based for readability
            self.pad + 1,
            (self.pad2 + 1) if self.pad2 is not None else "",
            "yes" if self.expect_touch  else "no",
            "yes" if self.actual_touch  else "no",
            self.reaction_time_ms,
            _trial_outcome(self),
            "warmup" if self.is_warmup else "scored",
        ]

    def __repr__(self) -> str:
        outcome = "hit" if self.is_hit else (
            "CR"   if self.is_correct_rejection else (
            "FA"   if self.is_commission_error  else "miss"))
        return (f"TrialResult(#{self.trial_num} P{self.panel+1}/pad{self.pad+1} "
                f"{outcome} rt={self.reaction_time_ms}ms)")


# ---------------------------------------------------------------------------
# Session result
# ---------------------------------------------------------------------------

@dataclass
class SessionResult:
    """
    Aggregates all trials from one test run.

    Statistical methods only count scored (non-warmup) trials with
    ``actual_touch == True and expect_touch == True`` (genuine hits) unless
    otherwise stated.
    """

    session_id:     str             = field(default_factory=lambda: str(uuid.uuid4()))
    participant_id: str             = ""
    config_name:    str             = ""
    config_id:      str             = ""   # UUID of the configuration used
    start_time:     str             = field(default_factory=_now)
    end_time:       str             = ""
    trials:         list[TrialResult] = field(default_factory=list)

    # ---- Trial accessors ----------------------------------------------------

    @property
    def scored_trials(self) -> list[TrialResult]:
        """All non-warmup trials."""
        return [t for t in self.trials if not t.is_warmup]

    @property
    def warmup_trials(self) -> list[TrialResult]:
        return [t for t in self.trials if t.is_warmup]

    @property
    def hit_trials(self) -> list[TrialResult]:
        """Scored hits only (expect + actual touch)."""
        return [t for t in self.scored_trials if t.is_hit]

    # ---- Error counts -------------------------------------------------------

    def commission_errors(self) -> int:
        """Number of scored commission errors (false alarms)."""
        return sum(1 for t in self.scored_trials if t.is_commission_error)

    def omission_errors(self) -> int:
        """Number of scored omission errors (misses)."""
        return sum(1 for t in self.scored_trials if t.is_omission_error)

    def accuracy(self) -> float:
        """
        Proportion of scored trials with a correct outcome (hit or correct
        rejection).  Returns 0.0 when there are no scored trials.
        """
        scored = self.scored_trials
        if not scored:
            return 0.0
        return sum(1 for t in scored if t.is_correct) / len(scored)

    # ---- Statistics ---------------------------------------------------------

    def overall_stats(self) -> dict:
        """Descriptive statistics across all scored hits."""
        rts = [t.reaction_time_ms for t in self.hit_trials]
        return _compute_stats(rts)

    def stats_for_pad(self, panel: int, pad: int) -> dict:
        """Descriptive statistics for scored hits on one specific pad."""
        rts = [
            t.reaction_time_ms
            for t in self.hit_trials
            if t.panel == panel and t.pad == pad
        ]
        return _compute_stats(rts)

    def stats_per_pad(self) -> dict[tuple[int, int], dict]:
        """
        Return a mapping of (panel, pad) → stats dict for every pad that
        has at least one hit trial.
        """
        # Collect unique (panel, pad) pairs from hit trials
        keys = {(t.panel, t.pad) for t in self.hit_trials}
        return {key: self.stats_for_pad(*key) for key in sorted(keys)}

    def duration_seconds(self) -> float:
        """Elapsed time between start_time and end_time in seconds."""
        try:
            start = datetime.fromisoformat(self.start_time)
            end   = datetime.fromisoformat(self.end_time)
            return (end - start).total_seconds()
        except (ValueError, TypeError):
            return 0.0

    # ---- Serialisation ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "session_id":     self.session_id,
            "participant_id": self.participant_id,
            "config_name":    self.config_name,
            "config_id":      self.config_id,
            "start_time":     self.start_time,
            "end_time":       self.end_time,
            "trials":         [t.to_dict() for t in self.trials],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionResult":
        return cls(
            session_id     = str(d.get("session_id", str(uuid.uuid4()))),
            participant_id = str(d.get("participant_id", "")),
            config_name    = str(d.get("config_name", "")),
            config_id      = str(d.get("config_id", "")),
            start_time     = str(d.get("start_time", _now())),
            end_time       = str(d.get("end_time", "")),
            trials         = [TrialResult.from_dict(t)
                              for t in d.get("trials", [])],
        )

    def __repr__(self) -> str:
        return (f"SessionResult(id={self.session_id[:8]}… "
                f"participant={self.participant_id!r} "
                f"trials={len(self.trials)})")


# ---------------------------------------------------------------------------
# Calibration data
# ---------------------------------------------------------------------------

@dataclass
class CalibrationEntry:
    """
    Raw capacitive baseline reading for a single pad.

    Attributes
    ----------
    panel         : 0-based panel index.
    pad           : 0-based pad index.
    baseline      : Raw capacitive reading at rest (ADC counts or similar).
    threshold     : Touch-detection threshold set by the operator.
    timestamp     : When the calibration was performed.
    """
    panel:     int
    pad:       int
    baseline:  int
    threshold: int
    timestamp: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "panel":     self.panel,
            "pad":       self.pad,
            "baseline":  self.baseline,
            "threshold": self.threshold,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationEntry":
        return cls(
            panel     = int(d["panel"]),
            pad       = int(d["pad"]),
            baseline  = int(d.get("baseline", 0)),
            threshold = int(d.get("threshold", 0)),
            timestamp = str(d.get("timestamp", _now())),
        )


@dataclass
class CalibrationProfile:
    """
    Stores the baseline and threshold for every pad that has been calibrated.

    A profile is saved per physical panel setup.  Entries are keyed by
    (panel, pad); calling set_entry() overwrites any previous reading for
    that pad.
    """
    profile_id:  str                    = field(default_factory=lambda: str(uuid.uuid4()))
    name:        str                    = "Default"
    created:     str                    = field(default_factory=_now)
    entries:     list[CalibrationEntry] = field(default_factory=list)

    def set_entry(self, panel: int, pad: int, baseline: int, threshold: int) -> None:
        """Insert or replace the calibration entry for (panel, pad)."""
        # Remove any existing entry for this pad
        self.entries = [
            e for e in self.entries
            if not (e.panel == panel and e.pad == pad)
        ]
        self.entries.append(CalibrationEntry(
            panel=panel, pad=pad,
            baseline=baseline, threshold=threshold,
        ))

    def get_entry(self, panel: int, pad: int) -> Optional[CalibrationEntry]:
        """Return the entry for (panel, pad), or None if not calibrated."""
        for e in self.entries:
            if e.panel == panel and e.pad == pad:
                return e
        return None

    def threshold_for(self, panel: int, pad: int) -> Optional[int]:
        """Convenience: return just the threshold value, or None."""
        entry = self.get_entry(panel, pad)
        return entry.threshold if entry else None

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "name":       self.name,
            "created":    self.created,
            "entries":    [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationProfile":
        return cls(
            profile_id = str(d.get("profile_id", str(uuid.uuid4()))),
            name       = str(d.get("name", "Default")),
            created    = str(d.get("created", _now())),
            entries    = [CalibrationEntry.from_dict(e)
                          for e in d.get("entries", [])],
        )

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "CalibrationProfile":
        import json
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# Remaining module-level helpers
# ---------------------------------------------------------------------------

def _trial_outcome(trial: TrialResult) -> str:
    """Return a short string label for a trial's outcome."""
    if trial.is_hit:
        return "hit"
    if trial.is_correct_rejection:
        return "correct_rejection"
    if trial.is_commission_error:
        return "commission_error"
    if trial.is_omission_error:
        return "omission_error"
    return "unknown"


def _compute_stats(rts: list[int]) -> dict:
    """
    Compute descriptive statistics for a list of reaction times.

    Returns a dict with keys: n, mean, median, std, min, max.
    All values are rounded to the nearest integer millisecond.
    Returns zeros for all fields when *rts* is empty.
    """
    if not rts:
        return {"n": 0, "mean": 0, "median": 0, "std": 0, "min": 0, "max": 0}
    return {
        "n":      len(rts),
        "mean":   round(statistics.mean(rts)),
        "median": round(statistics.median(rts)),
        "std":    round(statistics.stdev(rts)) if len(rts) > 1 else 0,
        "min":    min(rts),
        "max":    max(rts),
    }
