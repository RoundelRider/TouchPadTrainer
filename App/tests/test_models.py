"""
tests/test_models.py
~~~~~~~~~~~~~~~~~~~~
Unit tests for data.models — no I/O, no Qt, no hardware required.

Coverage targets
----------------
TestType / PadOrder          — enum values and coercions
ReactionBand                 — dict round-trip
PadConfig                    — adjacency, row/col, display properties, round-trip
TestConfiguration            — defaults, validation, band lookup, copy, round-trip
TrialResult                  — error classification, CSV row, round-trip
SessionResult                — stats, accuracy, error counts, per-pad stats
CalibrationProfile           — CRUD on entries, round-trip
_compute_stats               — edge cases (empty, single, multiple)
"""

from __future__ import annotations

import json
import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.models import (
    TestType, PadOrder,
    ReactionBand, PadConfig,
    TestConfiguration, TrialResult, SessionResult,
    CalibrationProfile, CalibrationEntry,
    _compute_stats,
)
from tests.conftest import make_config, make_trial, make_session, make_pads


# ===========================================================================
# Enumerations
# ===========================================================================

class TestEnums(unittest.TestCase):

    def test_test_type_values(self):
        self.assertEqual(TestType.SINGLE_WHITE,     0)
        self.assertEqual(TestType.SINGLE_SELECTIVE, 1)
        self.assertEqual(TestType.DOUBLE_WHITE,     2)
        self.assertEqual(TestType.DOUBLE_SELECTIVE, 3)

    def test_pad_order_values(self):
        self.assertEqual(PadOrder.RANDOM,        0)
        self.assertEqual(PadOrder.PSEUDO_RANDOM, 1)
        self.assertEqual(PadOrder.SEQUENTIAL,    2)

    def test_test_type_coercion(self):
        self.assertIs(TestType(2), TestType.DOUBLE_WHITE)

    def test_pad_order_coercion(self):
        self.assertIs(PadOrder(0), PadOrder.RANDOM)

    def test_invalid_test_type_raises(self):
        with self.assertRaises(ValueError):
            TestType(99)


# ===========================================================================
# ReactionBand
# ===========================================================================

class TestReactionBand(unittest.TestCase):

    def test_round_trip(self):
        band = ReactionBand(max_ms=500, color="#00FF00", label="Good")
        d    = band.to_dict()
        band2 = ReactionBand.from_dict(d)
        self.assertEqual(band2.max_ms, 500)
        self.assertEqual(band2.color,  "#00FF00")
        self.assertEqual(band2.label,  "Good")

    def test_from_dict_missing_label(self):
        """label is optional in stored data — should default to empty string."""
        band = ReactionBand.from_dict({"max_ms": 300, "color": "#AAA"})
        self.assertEqual(band.label, "")


# ===========================================================================
# PadConfig
# ===========================================================================

class TestPadConfig(unittest.TestCase):

    def test_row_and_col(self):
        # Pad index 5 → row 1, col 1
        pc = PadConfig(panel=0, pad=5)
        self.assertEqual(pc.row, 1)
        self.assertEqual(pc.col, 1)
        # Pad index 15 → row 3, col 3
        pc2 = PadConfig(panel=0, pad=15)
        self.assertEqual(pc2.row, 3)
        self.assertEqual(pc2.col, 3)

    def test_display_indices_are_one_based(self):
        pc = PadConfig(panel=0, pad=0)
        self.assertEqual(pc.display_panel, 1)
        self.assertEqual(pc.display_pad,   1)

    def test_adjacency_horizontal(self):
        left  = PadConfig(panel=0, pad=0)   # row 0, col 0
        right = PadConfig(panel=0, pad=1)   # row 0, col 1
        self.assertTrue(left.is_adjacent_to(right))
        self.assertTrue(right.is_adjacent_to(left))

    def test_adjacency_vertical(self):
        top    = PadConfig(panel=0, pad=0)   # row 0, col 0
        bottom = PadConfig(panel=0, pad=4)   # row 1, col 0
        self.assertTrue(top.is_adjacent_to(bottom))

    def test_not_adjacent_diagonal(self):
        a = PadConfig(panel=0, pad=0)   # row 0, col 0
        b = PadConfig(panel=0, pad=5)   # row 1, col 1
        self.assertFalse(a.is_adjacent_to(b))

    def test_not_adjacent_same_pad(self):
        a = PadConfig(panel=0, pad=3)
        self.assertFalse(a.is_adjacent_to(a))

    def test_not_adjacent_different_panel(self):
        a = PadConfig(panel=0, pad=0)
        b = PadConfig(panel=1, pad=1)
        self.assertFalse(a.is_adjacent_to(b))

    def test_not_adjacent_two_apart(self):
        a = PadConfig(panel=0, pad=0)
        b = PadConfig(panel=0, pad=2)   # col 2 — two columns away
        self.assertFalse(a.is_adjacent_to(b))

    def test_round_trip(self):
        pc  = PadConfig(panel=2, pad=9, faulty=True)
        pc2 = PadConfig.from_dict(pc.to_dict())
        self.assertEqual(pc2.panel,  2)
        self.assertEqual(pc2.pad,    9)
        self.assertTrue(pc2.faulty)


# ===========================================================================
# TestConfiguration
# ===========================================================================

class TestTestConfiguration(unittest.TestCase):

    def setUp(self):
        self.cfg = make_config()

    def test_default_rt_bands_created(self):
        """Configuration must auto-create 5 RT bands when none supplied."""
        self.assertEqual(len(self.cfg.rt_bands), 5)

    def test_default_bands_cover_full_timeout(self):
        """Last band max_ms must equal timeout_ms."""
        last = sorted(self.cfg.rt_bands, key=lambda b: b.max_ms)[-1]
        self.assertEqual(last.max_ms, self.cfg.timeout_ms)

    def test_color_for_rt_first_band(self):
        """RT at or below first band max → first band color."""
        bands = sorted(self.cfg.rt_bands, key=lambda b: b.max_ms)
        color = self.cfg.color_for_rt(bands[0].max_ms)
        self.assertEqual(color, bands[0].color)

    def test_color_for_rt_last_band(self):
        """RT beyond all bands → last band color."""
        color = self.cfg.color_for_rt(99_999)
        bands = sorted(self.cfg.rt_bands, key=lambda b: b.max_ms)
        self.assertEqual(color, bands[-1].color)

    def test_color_for_rt_exact_boundary(self):
        """Exact boundary value belongs to the lower band."""
        bands = sorted(self.cfg.rt_bands, key=lambda b: b.max_ms)
        color = self.cfg.color_for_rt(bands[1].max_ms)
        self.assertEqual(color, bands[1].color)

    def test_band_for_rt_returns_object(self):
        band = self.cfg.band_for_rt(100)
        self.assertIsInstance(band, ReactionBand)

    def test_active_pads_excludes_faulty(self):
        self.cfg.pads[0].faulty = True
        active = self.cfg.active_pads
        self.assertNotIn(self.cfg.pads[0], active)
        self.assertEqual(len(active), len(self.cfg.pads) - 1)

    def test_adjacent_pairs_found(self):
        # pads 0 and 1 are in the default make_config() — they are adjacent
        pairs = self.cfg.adjacent_pairs()
        self.assertGreater(len(pairs), 0)
        for a, b in pairs:
            self.assertTrue(a.is_adjacent_to(b))

    def test_adjacent_pairs_respects_faulty(self):
        """Faulty pads must not appear in adjacent pairs."""
        self.cfg.pads[1].faulty = True   # mark pad index 1 faulty
        for a, b in self.cfg.adjacent_pairs():
            self.assertFalse(a.faulty)
            self.assertFalse(b.faulty)

    # ---- Validation --------------------------------------------------------

    def test_validate_passes_valid_config(self):
        issues = self.cfg.validate()
        self.assertEqual(issues, [])

    def test_validate_fails_empty_name(self):
        self.cfg.name = "   "
        self.assertIn(
            True,
            ["name" in i.lower() or "empty" in i.lower() for i in self.cfg.validate()]
        )

    def test_validate_fails_no_active_pads(self):
        for p in self.cfg.pads:
            p.faulty = True
        issues = self.cfg.validate()
        self.assertTrue(any("pad" in i.lower() for i in issues))

    def test_validate_fails_zero_trials(self):
        self.cfg.num_trials = 0
        issues = self.cfg.validate()
        self.assertTrue(any("trial" in i.lower() for i in issues))

    def test_validate_fails_low_timeout(self):
        self.cfg.timeout_ms = 50
        issues = self.cfg.validate()
        self.assertTrue(any("timeout" in i.lower() or "100" in i for i in issues))

    def test_validate_dual_touch_needs_adjacent_pads(self):
        self.cfg.test_type = TestType.DOUBLE_WHITE
        # Replace pads with non-adjacent ones (pad 0 and pad 5 are diagonal)
        self.cfg.pads = [PadConfig(0, 0), PadConfig(0, 5)]
        issues = self.cfg.validate()
        self.assertTrue(any("adjacent" in i.lower() for i in issues))

    def test_validate_dual_touch_passes_with_adjacent_pads(self):
        self.cfg.test_type = TestType.DOUBLE_WHITE
        self.cfg.pads = [PadConfig(0, 0), PadConfig(0, 1)]
        self.assertEqual(self.cfg.validate(), [])

    # ---- Serialisation -----------------------------------------------------

    def test_json_round_trip_preserves_name(self):
        cfg2 = TestConfiguration.from_json(self.cfg.to_json())
        self.assertEqual(cfg2.name, self.cfg.name)

    def test_json_round_trip_preserves_id(self):
        cfg2 = TestConfiguration.from_json(self.cfg.to_json())
        self.assertEqual(cfg2.id, self.cfg.id)

    def test_json_round_trip_preserves_enum_types(self):
        cfg2 = TestConfiguration.from_json(self.cfg.to_json())
        self.assertIsInstance(cfg2.test_type, TestType)
        self.assertIsInstance(cfg2.pad_order, PadOrder)

    def test_json_round_trip_preserves_pads(self):
        cfg2 = TestConfiguration.from_json(self.cfg.to_json())
        self.assertEqual(len(cfg2.pads), len(self.cfg.pads))

    def test_json_round_trip_preserves_rt_bands(self):
        cfg2 = TestConfiguration.from_json(self.cfg.to_json())
        self.assertEqual(len(cfg2.rt_bands), len(self.cfg.rt_bands))

    def test_from_dict_handles_missing_optional_fields(self):
        """Loading minimal dict should fill in defaults without raising."""
        minimal = {"name": "Minimal"}
        cfg = TestConfiguration.from_dict(minimal)
        self.assertEqual(cfg.name, "Minimal")
        self.assertEqual(cfg.num_trials, 10)  # default
        self.assertEqual(len(cfg.rt_bands), 5)

    def test_copy_as_new_has_different_id(self):
        copy = self.cfg.copy_as_new("Copy")
        self.assertNotEqual(copy.id, self.cfg.id)
        self.assertEqual(copy.name, "Copy")

    def test_copy_as_new_is_not_read_only(self):
        self.cfg.read_only = True
        copy = self.cfg.copy_as_new("Copy")
        self.assertFalse(copy.read_only)

    def test_enum_coercion_in_post_init(self):
        """Raw ints for test_type / pad_order must be coerced to enum instances."""
        d = self.cfg.to_dict()
        # Tamper: write raw ints instead of enum values
        d["test_type"] = 1
        d["pad_order"] = 2
        cfg2 = TestConfiguration.from_dict(d)
        self.assertIsInstance(cfg2.test_type, TestType)
        self.assertEqual(cfg2.test_type, TestType.SINGLE_SELECTIVE)

    def test_green_red_ratio_clamped(self):
        cfg = make_config(green_red_ratio=1.5)
        self.assertLessEqual(cfg.green_red_ratio, 1.0)
        cfg2 = make_config(green_red_ratio=-0.3)
        self.assertGreaterEqual(cfg2.green_red_ratio, 0.0)

    def test_reset_default_bands(self):
        self.cfg.rt_bands = []
        self.cfg.reset_default_bands()
        self.assertEqual(len(self.cfg.rt_bands), 5)


# ===========================================================================
# TrialResult
# ===========================================================================

class TestTrialResult(unittest.TestCase):

    def _hit(self, **kw):
        return make_trial(expect_touch=True, actual_touch=True, **kw)

    def _miss(self, **kw):
        return make_trial(expect_touch=True, actual_touch=False, **kw)

    def _false_alarm(self, **kw):
        return make_trial(expect_touch=False, actual_touch=True, **kw)

    def _correct_rejection(self, **kw):
        return make_trial(expect_touch=False, actual_touch=False, **kw)

    # ---- Classification ----------------------------------------------------

    def test_hit_classification(self):
        t = self._hit()
        self.assertTrue(t.is_hit)
        self.assertFalse(t.is_omission_error)
        self.assertFalse(t.is_commission_error)
        self.assertFalse(t.is_correct_rejection)
        self.assertTrue(t.is_correct)

    def test_omission_error(self):
        t = self._miss()
        self.assertTrue(t.is_omission_error)
        self.assertFalse(t.is_hit)
        self.assertFalse(t.is_commission_error)
        self.assertFalse(t.is_correct)

    def test_commission_error(self):
        t = self._false_alarm()
        self.assertTrue(t.is_commission_error)
        self.assertFalse(t.is_hit)
        self.assertFalse(t.is_omission_error)
        self.assertFalse(t.is_correct)

    def test_correct_rejection(self):
        t = self._correct_rejection()
        self.assertTrue(t.is_correct_rejection)
        self.assertTrue(t.is_correct)
        self.assertFalse(t.is_hit)
        self.assertFalse(t.is_commission_error)
        self.assertFalse(t.is_omission_error)

    # ---- CSV row -----------------------------------------------------------

    def test_csv_row_length(self):
        row = make_trial().to_csv_row("P001", "sess-1")
        self.assertEqual(len(row), 11)

    def test_csv_row_participant_id(self):
        row = make_trial().to_csv_row("Alice", "s1")
        self.assertEqual(row[0], "Alice")

    def test_csv_row_session_id(self):
        row = make_trial().to_csv_row("P", "my-session")
        self.assertEqual(row[1], "my-session")

    def test_csv_row_expect_touch_yes(self):
        row = make_trial(expect_touch=True).to_csv_row("P", "s")
        self.assertEqual(row[6], "yes")

    def test_csv_row_expect_touch_no(self):
        row = make_trial(expect_touch=False).to_csv_row("P", "s")
        self.assertEqual(row[6], "no")

    def test_csv_row_pad2_empty_for_single(self):
        row = make_trial(pad2=None).to_csv_row("P", "s")
        self.assertEqual(row[5], "")

    def test_csv_row_pad2_present_for_dual(self):
        row = make_trial(pad2=3).to_csv_row("P", "s")
        self.assertEqual(row[5], 4)   # 1-based

    def test_csv_row_panel_is_one_based(self):
        row = make_trial(panel=0).to_csv_row("P", "s")
        self.assertEqual(row[3], 1)

    def test_csv_row_pad_is_one_based(self):
        row = make_trial(pad=5).to_csv_row("P", "s")
        self.assertEqual(row[4], 6)

    def test_csv_row_outcome_hit(self):
        row = make_trial(expect_touch=True, actual_touch=True).to_csv_row("P", "s")
        self.assertEqual(row[9], "hit")

    def test_csv_row_outcome_omission(self):
        row = make_trial(expect_touch=True, actual_touch=False).to_csv_row("P", "s")
        self.assertEqual(row[9], "omission_error")

    def test_csv_row_outcome_commission(self):
        row = make_trial(expect_touch=False, actual_touch=True).to_csv_row("P", "s")
        self.assertEqual(row[9], "commission_error")

    def test_csv_row_outcome_correct_rejection(self):
        row = make_trial(expect_touch=False, actual_touch=False).to_csv_row("P", "s")
        self.assertEqual(row[9], "correct_rejection")

    def test_csv_row_trial_type_warmup(self):
        row = make_trial(is_warmup=True).to_csv_row("P", "s")
        self.assertEqual(row[10], "warmup")

    def test_csv_row_trial_type_scored(self):
        row = make_trial(is_warmup=False).to_csv_row("P", "s")
        self.assertEqual(row[10], "scored")

    # ---- Serialisation -----------------------------------------------------

    def test_round_trip_basic(self):
        t  = make_trial(trial_num=7, panel=1, pad=3, reaction_time_ms=412)
        t2 = TrialResult.from_dict(t.to_dict())
        self.assertEqual(t2.trial_num,        7)
        self.assertEqual(t2.panel,            1)
        self.assertEqual(t2.pad,              3)
        self.assertEqual(t2.reaction_time_ms, 412)

    def test_round_trip_dual_touch(self):
        t  = make_trial(pad=4, pad2=5)
        t2 = TrialResult.from_dict(t.to_dict())
        self.assertEqual(t2.pad2, 5)

    def test_round_trip_none_pad2(self):
        t  = make_trial(pad2=None)
        t2 = TrialResult.from_dict(t.to_dict())
        self.assertIsNone(t2.pad2)


# ===========================================================================
# SessionResult
# ===========================================================================

class TestSessionResult(unittest.TestCase):

    def setUp(self):
        # 5 hits at 300 ms, 1 omission, 1 commission
        self.session = make_session(
            n_hits=5, hit_rt=300,
            n_omissions=1, n_commissions=1,
        )

    def test_scored_trials_count(self):
        self.assertEqual(len(self.session.scored_trials), 7)

    def test_warmup_trials_excluded_from_scored(self):
        self.session.trials.append(make_trial(is_warmup=True))
        scored = self.session.scored_trials
        self.assertFalse(any(t.is_warmup for t in scored))

    def test_warmup_trials_property(self):
        self.session.trials.append(make_trial(is_warmup=True))
        self.assertEqual(len(self.session.warmup_trials), 1)

    def test_hit_trials_count(self):
        self.assertEqual(len(self.session.hit_trials), 5)

    def test_omission_error_count(self):
        self.assertEqual(self.session.omission_errors(), 1)

    def test_commission_error_count(self):
        self.assertEqual(self.session.commission_errors(), 1)

    def test_accuracy_all_correct(self):
        s = make_session(n_hits=10)
        self.assertAlmostEqual(s.accuracy(), 1.0)

    def test_accuracy_with_errors(self):
        # 5 hits + 1 omission + 1 commission = 7 trials, 5 correct (hits)
        # correct_rejections count as correct but we have none here
        correct = sum(1 for t in self.session.scored_trials if t.is_correct)
        expected = correct / len(self.session.scored_trials)
        self.assertAlmostEqual(self.session.accuracy(), expected)

    def test_accuracy_empty_session(self):
        s = SessionResult()
        self.assertEqual(s.accuracy(), 0.0)

    def test_overall_stats_mean(self):
        stats = self.session.overall_stats()
        self.assertEqual(stats["mean"], 300)

    def test_overall_stats_n_only_counts_hits(self):
        stats = self.session.overall_stats()
        self.assertEqual(stats["n"], 5)   # only the 5 hit trials

    def test_overall_stats_empty(self):
        s = SessionResult()
        stats = s.overall_stats()
        self.assertEqual(stats["n"], 0)
        self.assertEqual(stats["mean"], 0)

    def test_stats_for_pad_single_pad(self):
        # All hits in setUp use panel=0, pad=0
        stats = self.session.stats_for_pad(0, 0)
        self.assertEqual(stats["n"], 5)
        self.assertEqual(stats["mean"], 300)

    def test_stats_for_pad_wrong_pad_returns_zeros(self):
        stats = self.session.stats_for_pad(0, 15)
        self.assertEqual(stats["n"], 0)

    def test_stats_per_pad_keys(self):
        per_pad = self.session.stats_per_pad()
        self.assertIn((0, 0), per_pad)

    def test_stats_per_pad_values(self):
        per_pad = self.session.stats_per_pad()
        self.assertEqual(per_pad[(0, 0)]["n"], 5)

    def test_overall_stats_variance(self):
        s = SessionResult()
        for rt in [200, 300, 400]:
            s.trials.append(make_trial(reaction_time_ms=rt))
        stats = s.overall_stats()
        self.assertEqual(stats["min"], 200)
        self.assertEqual(stats["max"], 400)
        self.assertEqual(stats["mean"], 300)
        self.assertEqual(stats["median"], 300)
        self.assertGreater(stats["std"], 0)

    def test_duration_seconds(self):
        from datetime import datetime, timedelta
        s = SessionResult()
        start = datetime(2025, 1, 1, 12, 0, 0)
        s.start_time = start.isoformat()
        s.end_time   = (start + timedelta(seconds=90)).isoformat()
        self.assertAlmostEqual(s.duration_seconds(), 90.0)

    def test_duration_seconds_missing_end_time(self):
        s = SessionResult()
        self.assertEqual(s.duration_seconds(), 0.0)

    # ---- Serialisation -----------------------------------------------------

    def test_round_trip_preserves_participant(self):
        d  = self.session.to_dict()
        s2 = SessionResult.from_dict(d)
        self.assertEqual(s2.participant_id, self.session.participant_id)

    def test_round_trip_preserves_trial_count(self):
        d  = self.session.to_dict()
        s2 = SessionResult.from_dict(d)
        self.assertEqual(len(s2.trials), len(self.session.trials))

    def test_round_trip_restores_trial_types(self):
        d  = self.session.to_dict()
        s2 = SessionResult.from_dict(d)
        for t in s2.trials:
            self.assertIsInstance(t, TrialResult)


# ===========================================================================
# CalibrationProfile
# ===========================================================================

class TestCalibrationProfile(unittest.TestCase):

    def setUp(self):
        self.profile = CalibrationProfile(name="Panel A")

    def test_set_entry_and_get_entry(self):
        self.profile.set_entry(panel=0, pad=5, baseline=100, threshold=180)
        e = self.profile.get_entry(0, 5)
        self.assertIsNotNone(e)
        self.assertEqual(e.baseline,  100)
        self.assertEqual(e.threshold, 180)

    def test_threshold_for_convenience(self):
        self.profile.set_entry(0, 3, 90, 160)
        self.assertEqual(self.profile.threshold_for(0, 3), 160)

    def test_get_entry_missing_returns_none(self):
        self.assertIsNone(self.profile.get_entry(0, 7))

    def test_threshold_for_missing_returns_none(self):
        self.assertIsNone(self.profile.threshold_for(1, 0))

    def test_set_entry_overwrites_previous(self):
        self.profile.set_entry(0, 2, 100, 180)
        self.profile.set_entry(0, 2, 110, 200)   # overwrite
        e = self.profile.get_entry(0, 2)
        self.assertEqual(e.baseline,  110)
        self.assertEqual(e.threshold, 200)
        # Only one entry should exist for this pad
        entries = [en for en in self.profile.entries if en.panel==0 and en.pad==2]
        self.assertEqual(len(entries), 1)

    def test_multiple_pads(self):
        for i in range(5):
            self.profile.set_entry(0, i, i * 10, i * 20)
        self.assertEqual(len(self.profile.entries), 5)

    def test_json_round_trip(self):
        self.profile.set_entry(0, 0, 120, 200)
        self.profile.set_entry(0, 1, 130, 210)
        j = self.profile.to_json()
        p2 = CalibrationProfile.from_json(j)
        self.assertEqual(p2.name, "Panel A")
        self.assertEqual(len(p2.entries), 2)
        self.assertEqual(p2.threshold_for(0, 0), 200)
        self.assertEqual(p2.threshold_for(0, 1), 210)

    def test_from_dict_missing_entries(self):
        d = {"name": "Empty"}
        p = CalibrationProfile.from_dict(d)
        self.assertEqual(p.entries, [])

    def test_calibration_entry_round_trip(self):
        e  = CalibrationEntry(panel=1, pad=7, baseline=88, threshold=150)
        e2 = CalibrationEntry.from_dict(e.to_dict())
        self.assertEqual(e2.panel,     1)
        self.assertEqual(e2.pad,       7)
        self.assertEqual(e2.baseline,  88)
        self.assertEqual(e2.threshold, 150)


# ===========================================================================
# _compute_stats (module-level helper)
# ===========================================================================

class TestComputeStats(unittest.TestCase):

    def test_empty_returns_zeros(self):
        s = _compute_stats([])
        self.assertEqual(s["n"],      0)
        self.assertEqual(s["mean"],   0)
        self.assertEqual(s["median"], 0)
        self.assertEqual(s["std"],    0)
        self.assertEqual(s["min"],    0)
        self.assertEqual(s["max"],    0)

    def test_single_value(self):
        s = _compute_stats([500])
        self.assertEqual(s["n"],      1)
        self.assertEqual(s["mean"],   500)
        self.assertEqual(s["median"], 500)
        self.assertEqual(s["std"],    0)   # stdev undefined for n=1 → 0
        self.assertEqual(s["min"],    500)
        self.assertEqual(s["max"],    500)

    def test_multiple_values_mean(self):
        s = _compute_stats([100, 200, 300])
        self.assertEqual(s["mean"], 200)

    def test_multiple_values_min_max(self):
        s = _compute_stats([100, 200, 300])
        self.assertEqual(s["min"], 100)
        self.assertEqual(s["max"], 300)

    def test_std_nonzero_for_varied_data(self):
        s = _compute_stats([100, 200, 300])
        self.assertGreater(s["std"], 0)

    def test_std_zero_for_identical_data(self):
        s = _compute_stats([250, 250, 250])
        self.assertEqual(s["std"], 0)

    def test_returns_integers(self):
        s = _compute_stats([101, 203, 305])
        for key in ("mean", "median", "std", "min", "max"):
            self.assertIsInstance(s[key], int)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
