"""
data.storage
~~~~~~~~~~~~
File-system persistence for the TouchPad test program.

Directory layout (inside the platform app-data root)
-----------------------------------------------------
TouchPadProgram/
    configs/
        <uuid>.json          — one TestConfiguration per file
    sessions/
        <uuid>.json          — one SessionResult per file
    calibration/
        <uuid>.json          — one CalibrationProfile per file
    logs/
        touchpad.log         — written by main.py / logging setup

Nothing outside this package should construct file paths directly.
All I/O goes through StorageManager so the rest of the application
never has to think about file layout or encoding.

Atomic writes
-------------
Every JSON write goes through _atomic_write(), which writes to a
sibling temp file then renames it into place.  This prevents a half-
written file from corrupting a previously good save on crash or power loss.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from data.models import (
    TestConfiguration,
    SessionResult,
    CalibrationProfile,
    TrialResult,
)

logger = logging.getLogger(__name__)

# CSV column headers for per-trial export
_CSV_HEADERS = [
    "participant_id",
    "session_id",
    "timestamp",
    "panel",
    "pad",
    "pad2",
    "expect_touch",
    "actual_touch",
    "reaction_time_ms",
    "outcome",
    "trial_type",
]

# CSV column headers for the session summary export
_SUMMARY_HEADERS = [
    "session_id",
    "participant_id",
    "config_name",
    "start_time",
    "end_time",
    "duration_s",
    "scored_trials",
    "hits",
    "omission_errors",
    "commission_errors",
    "accuracy_pct",
    "mean_rt_ms",
    "median_rt_ms",
    "std_rt_ms",
    "min_rt_ms",
    "max_rt_ms",
]


# ---------------------------------------------------------------------------
# Platform data-directory helper
# ---------------------------------------------------------------------------

def app_data_dir() -> Path:
    """
    Return the platform-appropriate application data directory and create
    it if it does not already exist.

    Platform   Path
    ---------  -------------------------------------------------------
    Windows    %APPDATA%\\TouchPadProgram
    macOS      ~/Library/Application Support/TouchPadProgram  (via env)
    Linux      ~/.local/share/TouchPadProgram
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        # Respect XDG on Linux; fall back to ~/.local/share
        xdg = os.environ.get("XDG_DATA_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"

    root = base / "TouchPadProgram"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, text: str, encoding: str = "utf-8") -> None:
    """
    Write *text* to *path* atomically using a same-directory temp file.

    On POSIX, os.replace() is atomic.  On Windows it is not guaranteed to
    be atomic across all scenarios but is safer than a direct overwrite.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the temp file on failure, then re-raise
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_json(path: Path) -> dict:
    """Read a UTF-8 JSON file and return the parsed dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def _sorted_json_files(directory: Path) -> list[Path]:
    """Return JSON files in *directory* sorted by filename."""
    return sorted(directory.glob("*.json"))


# ---------------------------------------------------------------------------
# StorageManager
# ---------------------------------------------------------------------------

class StorageManager:
    """
    Central access point for all persistent data.

    Parameters
    ----------
    data_dir : Optional override for the root storage directory.
               Pass a temporary directory in tests to avoid touching real data.

    Usage
    -----
    >>> storage = StorageManager()
    >>> cfg = TestConfiguration(name="My Test")
    >>> storage.save_config(cfg)
    >>> configs = storage.list_configs()
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._root        = data_dir or app_data_dir()
        self._cfg_dir     = self._root / "configs"
        self._session_dir = self._root / "sessions"
        self._cal_dir     = self._root / "calibration"

        for d in (self._cfg_dir, self._session_dir, self._cal_dir):
            d.mkdir(parents=True, exist_ok=True)

        logger.debug("StorageManager root: %s", self._root)

    @property
    def root(self) -> Path:
        """The storage root directory."""
        return self._root

    # ------------------------------------------------------------------
    # Configurations
    # ------------------------------------------------------------------

    def list_configs(self, sort_by: str = "name") -> list[TestConfiguration]:
        """
        Return all saved configurations.

        Parameters
        ----------
        sort_by : ``"name"`` (default, case-insensitive) or ``"modified"``
                  (most recently modified first).
        """
        configs: list[TestConfiguration] = []
        for path in _sorted_json_files(self._cfg_dir):
            try:
                cfg = TestConfiguration.from_dict(_load_json(path))
                configs.append(cfg)
            except Exception as exc:
                logger.warning("Skipping malformed config %s: %s", path.name, exc)

        if sort_by == "modified":
            configs.sort(key=lambda c: c.last_modified, reverse=True)
        else:
            configs.sort(key=lambda c: c.name.lower())
        return configs

    def load_config(self, config_id: str) -> Optional[TestConfiguration]:
        """Load a single configuration by its UUID.  Returns None if not found."""
        path = self._cfg_dir / f"{config_id}.json"
        if not path.exists():
            return None
        try:
            return TestConfiguration.from_dict(_load_json(path))
        except Exception as exc:
            logger.error("Could not load config %s: %s", config_id, exc)
            return None

    def save_config(self, cfg: TestConfiguration) -> Path:
        """
        Persist *cfg* to disk.

        If the configuration is marked read-only and a file already exists
        for its ID, raises ``PermissionError``.

        The ``last_modified`` field is updated to the current time.
        """
        path = self._cfg_dir / f"{cfg.id}.json"
        if cfg.read_only and path.exists():
            raise PermissionError(
                f"Configuration '{cfg.name}' is read-only and cannot be overwritten."
            )
        cfg.last_modified = datetime.now().isoformat()
        _atomic_write(path, cfg.to_json())
        logger.info("Saved config '%s' → %s", cfg.name, path.name)
        return path

    def delete_config(self, config_id: str) -> bool:
        """
        Delete the configuration with *config_id*.

        Returns True if deleted, False if the file did not exist.
        Raises ``PermissionError`` if the configuration is read-only.
        """
        path = self._cfg_dir / f"{config_id}.json"
        if not path.exists():
            return False
        # Check read-only flag before deleting
        try:
            cfg = TestConfiguration.from_dict(_load_json(path))
            if cfg.read_only:
                raise PermissionError(
                    f"Configuration '{cfg.name}' is read-only and cannot be deleted."
                )
        except PermissionError:
            raise
        except Exception:
            pass  # Malformed file — allow deletion
        path.unlink()
        logger.info("Deleted config %s", config_id)
        return True

    def export_config(self, cfg: TestConfiguration, dest: Path) -> None:
        """Write *cfg* as a JSON file to *dest* (for sharing between machines)."""
        _atomic_write(dest, cfg.to_json())
        logger.info("Exported config '%s' → %s", cfg.name, dest)

    def import_config(self, src: Path) -> TestConfiguration:
        """
        Read a configuration from *src*, assign a new UUID to avoid ID
        collisions, save it, and return the result.
        """
        cfg = TestConfiguration.from_dict(_load_json(src))
        # Assign fresh identity so it cannot clash with an existing config
        cfg.id = str(uuid.uuid4())
        cfg.read_only = False
        cfg.last_modified = datetime.now().isoformat()
        self.save_config(cfg)
        logger.info("Imported config '%s' from %s", cfg.name, src.name)
        return cfg

    def config_exists(self, config_id: str) -> bool:
        return (self._cfg_dir / f"{config_id}.json").exists()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def save_session(self, session: SessionResult) -> Path:
        """Persist a completed session.  Overwrites any previous file for the same ID."""
        path = self._session_dir / f"{session.session_id}.json"
        _atomic_write(path, json.dumps(session.to_dict(), indent=2,
                                       ensure_ascii=False))
        logger.info(
            "Saved session %s (participant=%s, trials=%d)",
            session.session_id[:8], session.participant_id, len(session.trials),
        )
        return path

    def load_session(self, session_id: str) -> Optional[SessionResult]:
        """Load a single session by UUID.  Returns None if not found."""
        path = self._session_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return SessionResult.from_dict(_load_json(path))
        except Exception as exc:
            logger.error("Could not load session %s: %s", session_id, exc)
            return None

    def list_sessions(
        self,
        participant_id: Optional[str] = None,
        config_name:    Optional[str] = None,
        limit:          Optional[int] = None,
    ) -> list[SessionResult]:
        """
        Return saved sessions, most recent first.

        Parameters
        ----------
        participant_id : When given, only sessions for this participant.
        config_name    : When given, only sessions that used this config name.
        limit          : Maximum number of sessions to return.
        """
        sessions: list[SessionResult] = []
        for path in sorted(_sorted_json_files(self._session_dir), reverse=True):
            try:
                s = SessionResult.from_dict(_load_json(path))
            except Exception as exc:
                logger.warning("Skipping malformed session %s: %s", path.name, exc)
                continue
            if participant_id and s.participant_id != participant_id:
                continue
            if config_name and s.config_name != config_name:
                continue
            sessions.append(s)
            if limit and len(sessions) >= limit:
                break
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session file.  Returns True if deleted, False if not found."""
        path = self._session_dir / f"{session_id}.json"
        if not path.exists():
            return False
        path.unlink()
        logger.info("Deleted session %s", session_id)
        return True

    def session_count(self) -> int:
        """Return the total number of saved sessions."""
        return sum(1 for _ in self._session_dir.glob("*.json"))

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def export_session_csv(self, session: SessionResult, dest: Path) -> None:
        """
        Export every trial in *session* as a CSV file.

        Columns: participant_id, session_id, timestamp, panel, pad, pad2,
                 expect_touch, actual_touch, reaction_time_ms, outcome,
                 trial_type
        """
        with open(dest, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(_CSV_HEADERS)
            for trial in session.trials:
                writer.writerow(
                    trial.to_csv_row(session.participant_id, session.session_id)
                )
        logger.info("Exported %d trials → %s", len(session.trials), dest)

    def export_sessions_summary_csv(
        self,
        dest: Path,
        sessions: Optional[list[SessionResult]] = None,
    ) -> None:
        """
        Export a one-row-per-session summary CSV.

        If *sessions* is None all stored sessions are included.
        Columns include accuracy, mean/median/std/min/max RT, and error counts.
        """
        if sessions is None:
            sessions = self.list_sessions()

        with open(dest, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(_SUMMARY_HEADERS)
            for s in sessions:
                stats = s.overall_stats()
                writer.writerow([
                    s.session_id,
                    s.participant_id,
                    s.config_name,
                    s.start_time,
                    s.end_time,
                    round(s.duration_seconds(), 1),
                    len(s.scored_trials),
                    len(s.hit_trials),
                    s.omission_errors(),
                    s.commission_errors(),
                    round(s.accuracy() * 100, 1),
                    stats["mean"],
                    stats["median"],
                    stats["std"],
                    stats["min"],
                    stats["max"],
                ])
        logger.info("Exported session summary (%d rows) → %s", len(sessions), dest)

    # ------------------------------------------------------------------
    # Calibration profiles
    # ------------------------------------------------------------------

    def list_calibration_profiles(self) -> list[CalibrationProfile]:
        """Return all saved calibration profiles, sorted by name."""
        profiles: list[CalibrationProfile] = []
        for path in _sorted_json_files(self._cal_dir):
            try:
                profiles.append(CalibrationProfile.from_dict(_load_json(path)))
            except Exception as exc:
                logger.warning("Skipping malformed calibration %s: %s",
                               path.name, exc)
        profiles.sort(key=lambda p: p.name.lower())
        return profiles

    def load_calibration_profile(
        self, profile_id: str
    ) -> Optional[CalibrationProfile]:
        path = self._cal_dir / f"{profile_id}.json"
        if not path.exists():
            return None
        try:
            return CalibrationProfile.from_dict(_load_json(path))
        except Exception as exc:
            logger.error("Could not load calibration %s: %s", profile_id, exc)
            return None

    def save_calibration_profile(self, profile: CalibrationProfile) -> Path:
        path = self._cal_dir / f"{profile.profile_id}.json"
        _atomic_write(path, profile.to_json())
        logger.info("Saved calibration profile '%s'", profile.name)
        return path

    def delete_calibration_profile(self, profile_id: str) -> bool:
        path = self._cal_dir / f"{profile_id}.json"
        if not path.exists():
            return False
        path.unlink()
        logger.info("Deleted calibration profile %s", profile_id)
        return True

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def purge_old_sessions(self, keep: int = 500) -> int:
        """
        Delete the oldest sessions if the total exceeds *keep*.

        Returns the number of sessions deleted.
        """
        files = sorted(_sorted_json_files(self._session_dir))  # oldest first
        to_delete = files[: max(0, len(files) - keep)]
        for path in to_delete:
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Could not delete %s: %s", path.name, exc)
        if to_delete:
            logger.info("Purged %d old session files", len(to_delete))
        return len(to_delete)

    def storage_stats(self) -> dict:
        """Return a dict with counts and total sizes for diagnostics."""
        def _dir_stats(d: Path) -> tuple[int, int]:
            files = list(d.glob("*.json"))
            total = sum(f.stat().st_size for f in files)
            return len(files), total

        cfg_n,  cfg_b  = _dir_stats(self._cfg_dir)
        sess_n, sess_b = _dir_stats(self._session_dir)
        cal_n,  cal_b  = _dir_stats(self._cal_dir)
        return {
            "configs":       {"count": cfg_n,  "bytes": cfg_b},
            "sessions":      {"count": sess_n, "bytes": sess_b},
            "calibrations":  {"count": cal_n,  "bytes": cal_b},
            "total_bytes":   cfg_b + sess_b + cal_b,
        }
