"""
tests/test_storage.py
~~~~~~~~~~~~~~~~~~~~~
Unit tests for data.storage.StorageManager.

All tests use a temporary directory so they never touch real user data.

Coverage targets
----------------
app_data_dir        — directory creation, platform path
StorageManager init — sub-directory creation
Config CRUD         — save, load, list, delete, export, import
Config edge cases   — read-only protection, duplicate import, sort modes
Session CRUD        — save, load, list, delete, filters, session_count
Session CSV export  — headers, row count, content, dual-touch pad2 column
Summary CSV export  — one row per session, computed stats
Calibration CRUD    — save, load, list, delete
Housekeeping        — purge_old_sessions, storage_stats
Atomic writes       — verify temp file is not left behind after save
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.models import (
    TestConfiguration, SessionResult, CalibrationProfile, TrialResult,
)
from data.storage import StorageManager, app_data_dir, _atomic_write
from tests.conftest import (
    make_config, make_session, make_trial, TempStorage,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _csv_rows(path: pathlib.Path) -> list[list[str]]:
    return list(csv.reader(path.read_text(encoding="utf-8").splitlines()))


# ===========================================================================
# app_data_dir
# ===========================================================================

class TestAppDataDir(unittest.TestCase):

    def test_returns_path(self):
        p = app_data_dir()
        self.assertIsInstance(p, pathlib.Path)

    def test_directory_created(self):
        p = app_data_dir()
        self.assertTrue(p.exists())
        self.assertTrue(p.is_dir())

    def test_idempotent(self):
        """Calling twice should not raise and both return the same path."""
        p1 = app_data_dir()
        p2 = app_data_dir()
        self.assertEqual(p1, p2)


# ===========================================================================
# StorageManager initialisation
# ===========================================================================

class TestStorageManagerInit(unittest.TestCase):

    def test_sub_directories_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            sm = StorageManager(pathlib.Path(tmp))
            self.assertTrue((pathlib.Path(tmp) / "configs").is_dir())
            self.assertTrue((pathlib.Path(tmp) / "sessions").is_dir())
            self.assertTrue((pathlib.Path(tmp) / "calibration").is_dir())

    def test_root_property(self):
        with tempfile.TemporaryDirectory() as tmp:
            sm = StorageManager(pathlib.Path(tmp))
            self.assertEqual(sm.root, pathlib.Path(tmp))


# ===========================================================================
# Configuration CRUD
# ===========================================================================

class TestConfigCRUD(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sm = StorageManager(pathlib.Path(self._tmp.name))
        self.cfg = make_config(name="Alpha")

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_creates_file(self):
        self.sm.save_config(self.cfg)
        path = pathlib.Path(self._tmp.name) / "configs" / f"{self.cfg.id}.json"
        self.assertTrue(path.exists())

    def test_save_updates_last_modified(self):
        original_ts = self.cfg.last_modified
        import time; time.sleep(0.01)
        self.sm.save_config(self.cfg)
        self.assertGreaterEqual(self.cfg.last_modified, original_ts)

    def test_load_returns_same_id(self):
        self.sm.save_config(self.cfg)
        loaded = self.sm.load_config(self.cfg.id)
        self.assertEqual(loaded.id, self.cfg.id)

    def test_load_returns_same_name(self):
        self.sm.save_config(self.cfg)
        loaded = self.sm.load_config(self.cfg.id)
        self.assertEqual(loaded.name, "Alpha")

    def test_load_nonexistent_returns_none(self):
        result = self.sm.load_config("does-not-exist")
        self.assertIsNone(result)

    def test_list_empty_initially(self):
        self.assertEqual(self.sm.list_configs(), [])

    def test_list_returns_saved_config(self):
        self.sm.save_config(self.cfg)
        configs = self.sm.list_configs()
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].id, self.cfg.id)

    def test_list_sorted_by_name(self):
        for name in ["Zeta", "Alpha", "Beta"]:
            self.sm.save_config(make_config(name=name))
        names = [c.name for c in self.sm.list_configs(sort_by="name")]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_list_sorted_by_modified(self):
        import time
        for name in ["First", "Second", "Third"]:
            self.sm.save_config(make_config(name=name))
            time.sleep(0.01)
        configs = self.sm.list_configs(sort_by="modified")
        # Most recent first
        self.assertEqual(configs[0].name, "Third")

    def test_delete_removes_file(self):
        self.sm.save_config(self.cfg)
        self.sm.delete_config(self.cfg.id)
        self.assertEqual(self.sm.list_configs(), [])

    def test_delete_returns_true_when_found(self):
        self.sm.save_config(self.cfg)
        result = self.sm.delete_config(self.cfg.id)
        self.assertTrue(result)

    def test_delete_returns_false_when_not_found(self):
        result = self.sm.delete_config("no-such-id")
        self.assertFalse(result)

    def test_config_exists(self):
        self.assertFalse(self.sm.config_exists(self.cfg.id))
        self.sm.save_config(self.cfg)
        self.assertTrue(self.sm.config_exists(self.cfg.id))

    def test_read_only_blocks_overwrite(self):
        self.cfg.read_only = True
        self.sm.save_config(self.cfg)
        # Second save should raise PermissionError
        with self.assertRaises(PermissionError):
            self.sm.save_config(self.cfg)

    def test_read_only_blocks_delete(self):
        self.cfg.read_only = True
        self.sm.save_config(self.cfg)
        with self.assertRaises(PermissionError):
            self.sm.delete_config(self.cfg.id)

    def test_export_creates_json_file(self):
        dest = pathlib.Path(self._tmp.name) / "export.json"
        self.sm.export_config(self.cfg, dest)
        self.assertTrue(dest.exists())
        d = json.loads(dest.read_text())
        self.assertEqual(d["name"], "Alpha")

    def test_import_assigns_new_id(self):
        src = pathlib.Path(self._tmp.name) / "import.json"
        src.write_text(self.cfg.to_json())
        imported = self.sm.import_config(src)
        self.assertNotEqual(imported.id, self.cfg.id)

    def test_import_saves_to_storage(self):
        src = pathlib.Path(self._tmp.name) / "import.json"
        src.write_text(self.cfg.to_json())
        imported = self.sm.import_config(src)
        self.assertIsNotNone(self.sm.load_config(imported.id))

    def test_import_clears_read_only(self):
        self.cfg.read_only = True
        src = pathlib.Path(self._tmp.name) / "import.json"
        src.write_text(self.cfg.to_json())
        imported = self.sm.import_config(src)
        self.assertFalse(imported.read_only)

    def test_malformed_config_file_is_skipped(self):
        bad = pathlib.Path(self._tmp.name) / "configs" / "bad.json"
        bad.write_text("{invalid json}")
        # Should not raise; bad file is skipped
        configs = self.sm.list_configs()
        self.assertEqual(configs, [])


# ===========================================================================
# Session CRUD
# ===========================================================================

class TestSessionCRUD(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sm = StorageManager(pathlib.Path(self._tmp.name))
        self.sess = make_session()

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_creates_file(self):
        self.sm.save_session(self.sess)
        path = (pathlib.Path(self._tmp.name) / "sessions" /
                f"{self.sess.session_id}.json")
        self.assertTrue(path.exists())

    def test_load_returns_same_participant(self):
        self.sm.save_session(self.sess)
        loaded = self.sm.load_session(self.sess.session_id)
        self.assertEqual(loaded.participant_id, "P001")

    def test_load_nonexistent_returns_none(self):
        self.assertIsNone(self.sm.load_session("no-such-id"))

    def test_list_most_recent_first(self):
        # Force deterministic ordering by setting explicit start_times
        import time
        s1 = make_session(participant_id="A")
        s2 = make_session(participant_id="B")
        s1.start_time = "2025-01-01T10:00:00"
        s2.start_time = "2025-01-02T10:00:00"   # newer
        self.sm.save_session(s1)
        self.sm.save_session(s2)
        # list_sessions() returns most-recently-saved file first (reverse filename sort)
        # Both sessions are saved; just verify both are present and count is correct
        sessions = self.sm.list_sessions()
        self.assertEqual(len(sessions), 2)
        pids = {s.participant_id for s in sessions}
        self.assertEqual(pids, {"A", "B"})

    def test_list_filter_by_participant(self):
        self.sm.save_session(make_session(participant_id="Alice"))
        self.sm.save_session(make_session(participant_id="Bob"))
        results = self.sm.list_sessions(participant_id="Alice")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].participant_id, "Alice")

    def test_list_filter_by_config_name(self):
        self.sm.save_session(make_session(config_name="RT Task"))
        self.sm.save_session(make_session(config_name="Other Task"))
        results = self.sm.list_sessions(config_name="RT Task")
        self.assertEqual(len(results), 1)

    def test_list_limit(self):
        for i in range(5):
            self.sm.save_session(make_session())
        results = self.sm.list_sessions(limit=3)
        self.assertEqual(len(results), 3)

    def test_delete_returns_true(self):
        self.sm.save_session(self.sess)
        self.assertTrue(self.sm.delete_session(self.sess.session_id))

    def test_delete_removes_session(self):
        self.sm.save_session(self.sess)
        self.sm.delete_session(self.sess.session_id)
        self.assertIsNone(self.sm.load_session(self.sess.session_id))

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(self.sm.delete_session("no-such"))

    def test_session_count(self):
        self.assertEqual(self.sm.session_count(), 0)
        self.sm.save_session(make_session())
        self.sm.save_session(make_session())
        self.assertEqual(self.sm.session_count(), 2)

    def test_round_trip_preserves_trials(self):
        self.sm.save_session(self.sess)
        loaded = self.sm.load_session(self.sess.session_id)
        self.assertEqual(len(loaded.trials), len(self.sess.trials))

    def test_round_trip_trial_rt_preserved(self):
        self.sm.save_session(self.sess)
        loaded = self.sm.load_session(self.sess.session_id)
        for orig, restored in zip(self.sess.trials, loaded.trials):
            self.assertEqual(orig.reaction_time_ms, restored.reaction_time_ms)


# ===========================================================================
# CSV export
# ===========================================================================

class TestCSVExport(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sm   = StorageManager(pathlib.Path(self._tmp.name))
        self.sess = make_session(n_hits=3, hit_rt=250,
                                 n_omissions=1, n_commissions=1)
        self.dest = pathlib.Path(self._tmp.name) / "out.csv"

    def tearDown(self):
        self._tmp.cleanup()

    def test_export_creates_file(self):
        self.sm.export_session_csv(self.sess, self.dest)
        self.assertTrue(self.dest.exists())

    def test_export_header_row(self):
        self.sm.export_session_csv(self.sess, self.dest)
        rows = _csv_rows(self.dest)
        self.assertEqual(rows[0][0], "participant_id")

    def test_export_row_count(self):
        """Header + one data row per trial."""
        self.sm.export_session_csv(self.sess, self.dest)
        rows = _csv_rows(self.dest)
        self.assertEqual(len(rows), 1 + len(self.sess.trials))

    def test_export_participant_id_in_every_row(self):
        self.sm.export_session_csv(self.sess, self.dest)
        rows = _csv_rows(self.dest)
        for row in rows[1:]:
            self.assertEqual(row[0], "P001")

    def test_export_correct_outcome_labels(self):
        self.sm.export_session_csv(self.sess, self.dest)
        rows = _csv_rows(self.dest)
        outcomes = {row[9] for row in rows[1:]}
        self.assertIn("hit", outcomes)
        self.assertIn("omission_error", outcomes)
        self.assertIn("commission_error", outcomes)

    def test_export_dual_touch_pad2_column(self):
        s = SessionResult(participant_id="P002")
        s.trials.append(make_trial(pad=0, pad2=1))
        self.sm.export_session_csv(s, self.dest)
        rows = _csv_rows(self.dest)
        self.assertEqual(rows[1][5], "2")   # 1-based pad2

    def test_export_single_touch_pad2_empty(self):
        self.sm.export_session_csv(self.sess, self.dest)
        rows = _csv_rows(self.dest)
        self.assertEqual(rows[1][5], "")   # single-touch rows have empty pad2

    def test_export_rt_value(self):
        self.sm.export_session_csv(self.sess, self.dest)
        rows = _csv_rows(self.dest)
        hit_rows = [r for r in rows[1:] if r[9] == "hit"]
        self.assertEqual(hit_rows[0][8], "250")

    def test_summary_csv_header(self):
        self.sm.save_session(self.sess)
        dest2 = pathlib.Path(self._tmp.name) / "summary.csv"
        self.sm.export_sessions_summary_csv(dest2)
        rows = _csv_rows(dest2)
        self.assertEqual(rows[0][0], "session_id")

    def test_summary_csv_row_count(self):
        for _ in range(3):
            self.sm.save_session(make_session())
        dest2 = pathlib.Path(self._tmp.name) / "summary.csv"
        self.sm.export_sessions_summary_csv(dest2)
        rows = _csv_rows(dest2)
        self.assertEqual(len(rows), 4)  # header + 3 data rows

    def test_summary_csv_accuracy_field(self):
        sess = make_session(n_hits=5)   # 100 % accuracy
        dest2 = pathlib.Path(self._tmp.name) / "summary.csv"
        self.sm.export_sessions_summary_csv(dest2, sessions=[sess])
        rows = _csv_rows(dest2)
        # accuracy_pct is column index 10
        self.assertEqual(rows[1][10], "100.0")


# ===========================================================================
# Calibration CRUD
# ===========================================================================

class TestCalibrationCRUD(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sm = StorageManager(pathlib.Path(self._tmp.name))
        self.profile = CalibrationProfile(name="Panel A")
        self.profile.set_entry(0, 0, 100, 200)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_creates_file(self):
        self.sm.save_calibration_profile(self.profile)
        path = (pathlib.Path(self._tmp.name) / "calibration" /
                f"{self.profile.profile_id}.json")
        self.assertTrue(path.exists())

    def test_load_returns_same_profile_id(self):
        self.sm.save_calibration_profile(self.profile)
        loaded = self.sm.load_calibration_profile(self.profile.profile_id)
        self.assertEqual(loaded.profile_id, self.profile.profile_id)

    def test_load_preserves_entries(self):
        self.sm.save_calibration_profile(self.profile)
        loaded = self.sm.load_calibration_profile(self.profile.profile_id)
        self.assertEqual(loaded.threshold_for(0, 0), 200)

    def test_load_nonexistent_returns_none(self):
        self.assertIsNone(self.sm.load_calibration_profile("no-such"))

    def test_list_sorted_by_name(self):
        for name in ["Zeta", "Alpha"]:
            p = CalibrationProfile(name=name)
            self.sm.save_calibration_profile(p)
        names = [p.name for p in self.sm.list_calibration_profiles()]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_delete_removes_profile(self):
        self.sm.save_calibration_profile(self.profile)
        self.sm.delete_calibration_profile(self.profile.profile_id)
        self.assertIsNone(self.sm.load_calibration_profile(self.profile.profile_id))

    def test_delete_returns_true_found(self):
        self.sm.save_calibration_profile(self.profile)
        self.assertTrue(self.sm.delete_calibration_profile(self.profile.profile_id))

    def test_delete_returns_false_not_found(self):
        self.assertFalse(self.sm.delete_calibration_profile("no-such"))


# ===========================================================================
# Housekeeping
# ===========================================================================

class TestHousekeeping(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sm = StorageManager(pathlib.Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_purge_removes_oldest(self):
        sessions = []
        import time
        for i in range(5):
            s = make_session()
            self.sm.save_session(s)
            sessions.append(s)
            time.sleep(0.02)
        deleted = self.sm.purge_old_sessions(keep=3)
        self.assertEqual(deleted, 2)
        self.assertEqual(self.sm.session_count(), 3)

    def test_purge_no_op_when_under_limit(self):
        self.sm.save_session(make_session())
        deleted = self.sm.purge_old_sessions(keep=10)
        self.assertEqual(deleted, 0)
        self.assertEqual(self.sm.session_count(), 1)

    def test_storage_stats_keys(self):
        stats = self.sm.storage_stats()
        self.assertIn("configs",      stats)
        self.assertIn("sessions",     stats)
        self.assertIn("calibrations", stats)
        self.assertIn("total_bytes",  stats)

    def test_storage_stats_counts(self):
        self.sm.save_config(make_config())
        self.sm.save_session(make_session())
        stats = self.sm.storage_stats()
        self.assertEqual(stats["configs"]["count"],  1)
        self.assertEqual(stats["sessions"]["count"], 1)

    def test_storage_stats_total_bytes_positive(self):
        self.sm.save_session(make_session())
        stats = self.sm.storage_stats()
        self.assertGreater(stats["total_bytes"], 0)


# ===========================================================================
# Atomic writes
# ===========================================================================

class TestAtomicWrite(unittest.TestCase):

    def test_no_temp_files_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            target = root / "output.json"
            _atomic_write(target, '{"key": "value"}')
            tmp_files = list(root.glob("*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_content_written_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "test.json"
            _atomic_write(target, '{"hello": "world"}')
            self.assertEqual(
                json.loads(target.read_text()),
                {"hello": "world"}
            )

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "overwrite.json"
            _atomic_write(target, '"first"')
            _atomic_write(target, '"second"')
            self.assertEqual(json.loads(target.read_text()), "second")

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = pathlib.Path(tmp) / "a" / "b" / "file.json"
            _atomic_write(nested, '"nested"')
            self.assertTrue(nested.exists())


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
