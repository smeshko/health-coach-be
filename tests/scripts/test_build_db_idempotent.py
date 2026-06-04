"""TASK-002: idempotent wholesale rebuild.

Running build() twice into the same DB path must yield an identical corpus:
stable per-table counts, no row duplication, and identical four-table contents
*including* the AUTOINCREMENT ids (DROP TABLE resets sqlite_sequence, and a
deterministic re-parse re-assigns the same ids). The comparison is over table
*contents*, not raw file bytes — ANALYZE/sqlite_stat*/free-page layout aren't
byte-stable, so a byte diff would be a false negative (round-1 #2, #4).
"""

from __future__ import annotations

import sqlite3

TABLES = ("records", "workouts", "workout_statistics", "activity_summary")


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def _contents(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    # Order by rowid (insertion order) for a deterministic content comparison.
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in TABLES}


def test_second_run_is_identical(build_db, fixture_xml, tmp_path) -> None:
    db_path = tmp_path / "baseline.db"

    counts1 = build_db.build(fixture_xml, db_path)
    with sqlite3.connect(db_path) as conn:
        snapshot1 = _contents(conn)
        total1 = sum(_counts(conn).values())

    counts2 = build_db.build(fixture_xml, db_path)
    with sqlite3.connect(db_path) as conn:
        snapshot2 = _contents(conn)
        total2 = sum(_counts(conn).values())

    # Per-table counts stable, total unchanged (no duplication).
    assert counts1 == counts2
    assert total1 == total2

    # Full four-table contents (incl. workouts.id / workout_statistics.workout_id)
    # are identical across runs.
    for table in TABLES:
        assert snapshot1[table] == snapshot2[table]
