"""TASK-002: seed the trailing ~90 Sofia days from baseline.db into app.db.

Builds a tiny synthetic baseline.db + a migrated temp app.db; the real corpus is
never read. The window is cut on Europe/Sofia days (DST-aware), and the copy adds
exactly three deltas (uuid=NULL, origin='seed', date_components→date).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SOFIA = ZoneInfo("Europe/Sofia")

# Fixed window anchor: now = 2026-06-02 Sofia, days=90 → window [2026-03-05 … 2026-06-02].
NOW = datetime(2026, 6, 2, 12, 0, tzinfo=SOFIA)
DAYS = 90

_BASELINE_RECORDS_DDL = """
CREATE TABLE records (
    type TEXT NOT NULL, unit TEXT, value REAL, value_text TEXT,
    source_name TEXT, source_version TEXT, device TEXT,
    creation_date TEXT, start_date TEXT NOT NULL, end_date TEXT
);
"""
_BASELINE_WORKOUTS_DDL = """
CREATE TABLE workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, activity_type TEXT NOT NULL,
    duration REAL, duration_unit TEXT, total_distance REAL, total_distance_unit TEXT,
    total_energy_burned REAL, total_energy_burned_unit TEXT, source_name TEXT,
    source_version TEXT, device TEXT, creation_date TEXT, start_date TEXT NOT NULL, end_date TEXT
);
"""
_BASELINE_STATS_DDL = """
CREATE TABLE workout_statistics (
    workout_id INTEGER NOT NULL, type TEXT NOT NULL, start_date TEXT, end_date TEXT,
    sum REAL, average REAL, minimum REAL, maximum REAL, unit TEXT
);
"""
_BASELINE_SUMMARY_DDL = """
CREATE TABLE activity_summary (
    date_components TEXT NOT NULL, active_energy_burned REAL, active_energy_burned_goal REAL,
    active_energy_burned_unit TEXT, apple_exercise_time REAL, apple_exercise_time_goal REAL,
    apple_stand_hours INTEGER, apple_stand_hours_goal INTEGER, apple_move_time REAL, apple_move_time_goal REAL
);
"""

# (type, start_date) — what should/shouldn't seed and why.
SEED_RECORDS = [
    ("HKQuantityTypeIdentifierHeartRate", "2026-05-01 12:00:00 +0300"),  # in-window, whitelisted
    ("HKQuantityTypeIdentifierBodyMass", "2026-05-15 08:00:00 +0300"),  # in-window
    ("HKQuantityTypeIdentifierDietaryProtein", "2026-05-20 13:00:00 +0300"),  # in-window dietary
    # In-window but NOT whitelisted → must be dropped.
    ("HKQuantityTypeIdentifierEnvironmentalAudioExposure", "2026-05-10 12:00:00 +0300"),
    # Out-of-window (before start) → dropped.
    ("HKQuantityTypeIdentifierHeartRate", "2026-01-01 12:00:00 +0200"),
    # DST/Sofia-day cut: UTC 2026-03-04 22:30 == Sofia 2026-03-05 00:30 (+0200) == start → KEPT.
    ("HKQuantityTypeIdentifierHeartRate", "2026-03-04 22:30:00 +0000"),
    # DST/Sofia-day cut: UTC 2026-06-02 21:30 == Sofia 2026-06-03 00:30 (+0300) > end → DROPPED.
    ("HKQuantityTypeIdentifierHeartRate", "2026-06-02 21:30:00 +0000"),
]
KEPT_RECORD_STARTS = {
    "2026-05-01 12:00:00 +0300",
    "2026-05-15 08:00:00 +0300",
    "2026-05-20 13:00:00 +0300",
    "2026-03-04 22:30:00 +0000",
}


def _make_baseline(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        _BASELINE_RECORDS_DDL + _BASELINE_WORKOUTS_DDL + _BASELINE_STATS_DDL + _BASELINE_SUMMARY_DDL
    )
    con.executemany(
        "INSERT INTO records (type, value, start_date) VALUES (?, 1.0, ?)", SEED_RECORDS
    )
    # In-window workout (+ child stat) and an out-of-window one.
    con.execute(
        "INSERT INTO workouts (activity_type, total_distance, start_date) VALUES (?,?,?)",
        ("HKWorkoutActivityTypeRunning", 5000.0, "2026-05-01 17:00:00 +0300"),
    )
    w_in = con.execute("SELECT id FROM workouts WHERE start_date LIKE '2026-05-01%'").fetchone()[0]
    con.execute(
        "INSERT INTO workout_statistics (workout_id, type, average, unit) VALUES (?,?,?,?)",
        (w_in, "HKQuantityTypeIdentifierHeartRate", 150.0, "count/min"),
    )
    con.execute(
        "INSERT INTO workouts (activity_type, start_date) VALUES (?,?)",
        ("HKWorkoutActivityTypeWalking", "2026-01-01 12:00:00 +0200"),
    )
    # In-window + out-of-window activity-summary days.
    con.executemany(
        "INSERT INTO activity_summary (date_components, active_energy_burned, "
        "active_energy_burned_unit, apple_stand_hours) VALUES (?,?,?,?)",
        [("2026-05-01", 650.0, "kcal", 11), ("2026-01-01", 500.0, "kcal", 9)],
    )
    con.commit()
    con.close()
    return path


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _seed(seed_app_db, baseline: Path, app_db: Path):
    return seed_app_db.seed(baseline, app_db, now=NOW, days=DAYS)


def test_window_bounds_sofia_dst(seed_app_db, migrated_app_db, tmp_path) -> None:
    baseline = _make_baseline(tmp_path / "baseline.db")
    _seed(seed_app_db, baseline, migrated_app_db)
    con = sqlite3.connect(migrated_app_db)
    try:
        starts = {r[0] for r in con.execute("SELECT start_date FROM records")}
    finally:
        con.close()
    assert starts == KEPT_RECORD_STARTS
    # Out-of-window (2026-01-01) and the Sofia-day-2026-06-03 sample are dropped.
    assert "2026-01-01 12:00:00 +0200" not in starts
    assert "2026-06-02 21:30:00 +0000" not in starts
    # The UTC-2026-03-04 sample (Sofia 2026-03-05 = window start) is kept.
    assert "2026-03-04 22:30:00 +0000" in starts


def test_origin_seed_and_uuid_null(seed_app_db, migrated_app_db, tmp_path) -> None:
    baseline = _make_baseline(tmp_path / "baseline.db")
    _seed(seed_app_db, baseline, migrated_app_db)
    con = sqlite3.connect(migrated_app_db)
    try:
        for table in ("records", "workouts"):
            rows = con.execute(f"SELECT origin, uuid FROM {table}").fetchall()
            assert rows, table
            assert all(origin == "seed" and uuid is None for origin, uuid in rows), table
        # activity_summary has no origin column at all.
        assert "origin" not in _columns(con, "activity_summary")
    finally:
        con.close()


def test_whitelist_filtering(seed_app_db, migrated_app_db, tmp_path) -> None:
    baseline = _make_baseline(tmp_path / "baseline.db")
    _seed(seed_app_db, baseline, migrated_app_db)
    con = sqlite3.connect(migrated_app_db)
    try:
        types = {r[0] for r in con.execute("SELECT type FROM records")}
    finally:
        con.close()
    assert "HKQuantityTypeIdentifierBodyMass" in types
    assert "HKQuantityTypeIdentifierDietaryProtein" in types
    assert "HKQuantityTypeIdentifierEnvironmentalAudioExposure" not in types


def test_three_delta_copy(seed_app_db, migrated_app_db, tmp_path) -> None:
    baseline = _make_baseline(tmp_path / "baseline.db")
    _seed(seed_app_db, baseline, migrated_app_db)
    con = sqlite3.connect(migrated_app_db)
    try:
        # date_components -> date, addressable by the date PK.
        summ = con.execute(
            "SELECT date FROM activity_summary WHERE date = ?", ("2026-05-01",)
        ).fetchone()
        assert summ is not None and summ[0] == "2026-05-01"
        # only the in-window day seeded
        assert con.execute("SELECT COUNT(*) FROM activity_summary").fetchone()[0] == 1
        # stat FK re-pointed to the new workouts.id; seed workout effort columns NULL
        wid = con.execute("SELECT id FROM workouts").fetchone()[0]
        stat = con.execute(
            "SELECT workout_id FROM workout_statistics"
        ).fetchone()
        assert stat is not None and stat[0] == wid
        effort = con.execute(
            "SELECT effort_score, physical_effort FROM workouts WHERE id = ?", (wid,)
        ).fetchone()
        assert effort == (None, None)
    finally:
        con.close()


def test_seed_is_idempotent(seed_app_db, migrated_app_db, tmp_path) -> None:
    baseline = _make_baseline(tmp_path / "baseline.db")
    counts1 = _seed(seed_app_db, baseline, migrated_app_db)
    con = sqlite3.connect(migrated_app_db)
    try:
        totals1 = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("records", "workouts", "workout_statistics", "activity_summary")
        }
    finally:
        con.close()
    counts2 = _seed(seed_app_db, baseline, migrated_app_db)
    con = sqlite3.connect(migrated_app_db)
    try:
        totals2 = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("records", "workouts", "workout_statistics", "activity_summary")
        }
    finally:
        con.close()
    assert counts1 == counts2
    assert totals1 == totals2
    # No duplication: 4 records, 1 workout, 1 stat, 1 activity_summary.
    assert totals2 == {"records": 4, "workouts": 1, "workout_statistics": 1, "activity_summary": 1}
