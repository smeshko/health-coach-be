"""TASK-002/003: build baseline.db raw tables + summary report.

ETL the small fixture through `build()` and assert the raw column shape (no
runtime deltas), exact per-table counts, timestamp fidelity, the
value/value_text split, child→parent FK keying, and the summarize() report.
"""

from __future__ import annotations

import sqlite3

import pytest

# Raw column sets — mirror app.db ingest *minus* the runtime-only deltas
# (no uuid/origin/effort_score/physical_effort, no records PK, keeps
# activity_summary.date_components). See DB.md §1, ARCHITECTURE §3.
RECORDS_COLS = [
    "type",
    "unit",
    "value",
    "value_text",
    "source_name",
    "source_version",
    "device",
    "creation_date",
    "start_date",
    "end_date",
]
WORKOUTS_COLS = [
    "id",
    "activity_type",
    "duration",
    "duration_unit",
    "total_distance",
    "total_distance_unit",
    "total_energy_burned",
    "total_energy_burned_unit",
    "source_name",
    "source_version",
    "device",
    "creation_date",
    "start_date",
    "end_date",
]
WORKOUT_STATISTICS_COLS = [
    "workout_id",
    "type",
    "start_date",
    "end_date",
    "sum",
    "average",
    "minimum",
    "maximum",
    "unit",
]
ACTIVITY_SUMMARY_COLS = [
    "date_components",
    "active_energy_burned",
    "active_energy_burned_goal",
    "active_energy_burned_unit",
    "apple_exercise_time",
    "apple_exercise_time_goal",
    "apple_stand_hours",
    "apple_stand_hours_goal",
    "apple_move_time",
    "apple_move_time_goal",
]

FORBIDDEN_DELTAS = {"uuid", "origin", "effort_score", "physical_effort"}


@pytest.fixture
def built_db(build_db, fixture_xml, tmp_path):
    """A freshly built baseline.db from the fixture; returns (counts, db_path)."""
    db_path = tmp_path / "baseline.db"
    counts = build_db.build(fixture_xml, db_path)
    return counts, db_path


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[5]]


# --- raw column shape -------------------------------------------------------


def test_records_raw_shape_no_pk_no_deltas(built_db) -> None:
    _, db_path = built_db
    with sqlite3.connect(db_path) as conn:
        cols = _columns(conn, "records")
        assert cols == RECORDS_COLS
        assert _pk_columns(conn, "records") == []  # raw dump: no PK on records
        assert FORBIDDEN_DELTAS.isdisjoint(cols)


def test_workouts_raw_shape_local_id_only(built_db) -> None:
    _, db_path = built_db
    with sqlite3.connect(db_path) as conn:
        cols = _columns(conn, "workouts")
        assert cols == WORKOUTS_COLS
        # `id` is the build-local child-stats FK target, the only PK.
        assert _pk_columns(conn, "workouts") == ["id"]
        assert FORBIDDEN_DELTAS.isdisjoint(cols)


def test_workout_statistics_shape(built_db) -> None:
    _, db_path = built_db
    with sqlite3.connect(db_path) as conn:
        assert _columns(conn, "workout_statistics") == WORKOUT_STATISTICS_COLS


def test_activity_summary_keeps_date_components(built_db) -> None:
    _, db_path = built_db
    with sqlite3.connect(db_path) as conn:
        cols = _columns(conn, "activity_summary")
        assert cols == ACTIVITY_SUMMARY_COLS
        assert "date_components" in cols
        assert "date" not in cols


# --- counts -----------------------------------------------------------------


def test_exact_nonzero_counts(built_db) -> None:
    counts, db_path = built_db
    expected = {
        "records": 5,
        "workouts": 2,
        "workout_statistics": 2,
        "activity_summary": 2,
    }
    assert counts == expected
    with sqlite3.connect(db_path) as conn:
        for table, n in expected.items():
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == n
            assert n > 0


# --- timestamp fidelity -----------------------------------------------------


def test_timestamp_stored_verbatim(built_db) -> None:
    _, db_path = built_db
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT start_date FROM records WHERE type = ?",
            ("HKQuantityTypeIdentifierHeartRate",),
        ).fetchone()
    assert row[0] == "2025-04-15 07:32:11 +0300"


# --- category vs quantity value ---------------------------------------------


def test_category_value_text_quantity_value(built_db) -> None:
    _, db_path = built_db
    with sqlite3.connect(db_path) as conn:
        sleep = conn.execute(
            "SELECT value, value_text FROM records WHERE type = ?",
            ("HKCategoryTypeIdentifierSleepAnalysis",),
        ).fetchone()
        assert sleep[0] is None
        assert sleep[1] == "HKCategoryValueSleepAnalysisAsleepCore"

        hr = conn.execute(
            "SELECT value FROM records WHERE type = ?",
            ("HKQuantityTypeIdentifierHeartRate",),
        ).fetchone()
        assert hr[0] == 62.0


# --- child→parent FK keying -------------------------------------------------


def test_workout_statistics_keyed_to_parent(built_db) -> None:
    _, db_path = built_db
    with sqlite3.connect(db_path) as conn:
        wid = conn.execute(
            "SELECT id FROM workouts WHERE activity_type = ?",
            ("HKWorkoutActivityTypeRunning",),
        ).fetchone()[0]
        stat_wid = conn.execute(
            "SELECT workout_id FROM workout_statistics WHERE type = ?",
            ("HKQuantityTypeIdentifierHeartRate",),
        ).fetchone()[0]
    assert stat_wid == wid


# --- summary report ---------------------------------------------------------


def test_summarize_matches_table_counts(build_db, built_db) -> None:
    _, db_path = built_db
    with sqlite3.connect(db_path) as conn:
        report = build_db.summarize(conn)
        assert set(report) == {
            "records",
            "workouts",
            "workout_statistics",
            "activity_summary",
        }
        for table, n in report.items():
            assert n == conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_main_prints_report(build_db, fixture_xml, tmp_path, capsys) -> None:
    db_path = tmp_path / "baseline.db"
    rc = build_db.main(["--xml", str(fixture_xml), "--db", str(db_path)])
    assert rc == 0
    out = capsys.readouterr().out
    for table in ("records", "workouts", "workout_statistics", "activity_summary"):
        assert table in out
