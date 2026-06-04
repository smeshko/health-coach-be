"""TASK-003: seed↔sync reconciliation.

A Sofia day with ≥1 'sync' row is "fully covered" → its 'seed' rows in records +
workouts (and the child workout_statistics of deleted seed workouts) are dropped;
'sync' rows are never touched; seed rows on a day with no sync row are kept;
activity_summary (no origin, date-PK upsert) is excluded. Idempotent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Sofia days: D1 will be sync-covered, D2 is seed-only.
D1_SEED = "2026-05-01 12:00:00 +0300"
D1_SYNC = "2026-05-01 08:00:00 +0300"
D2_SEED = "2026-05-10 12:00:00 +0300"


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON;")  # match runtime; child-first deletes matter
    return con


def _insert_record(con, start, origin, uuid=None):
    con.execute(
        "INSERT INTO records (uuid, type, start_date, origin) VALUES (?,?,?,?)",
        (uuid, "HKQuantityTypeIdentifierHeartRate", start, origin),
    )


def _insert_workout(con, start, origin, uuid=None) -> int:
    cur = con.execute(
        "INSERT INTO workouts (uuid, activity_type, start_date, origin) VALUES (?,?,?,?)",
        (uuid, "HKWorkoutActivityTypeRunning", start, origin),
    )
    wid = cur.lastrowid
    con.execute(
        "INSERT INTO workout_statistics (workout_id, type, average) VALUES (?,?,?)",
        (wid, "HKQuantityTypeIdentifierHeartRate", 150.0),
    )
    return wid


def _seed_and_sync(con) -> None:
    # records: D1 seed (covered), D2 seed (kept), D1 sync (authoritative).
    _insert_record(con, D1_SEED, "seed")
    _insert_record(con, D2_SEED, "seed")
    _insert_record(con, D1_SYNC, "sync", uuid="rec-sync-1")
    # workouts: D1 seed (covered, has child stat), D2 seed (kept), D1 sync.
    _insert_workout(con, D1_SEED, "seed")
    _insert_workout(con, D2_SEED, "seed")
    _insert_workout(con, D1_SYNC, "sync", uuid="wk-sync-1")
    # activity_summary (no origin) — must survive untouched.
    con.execute(
        "INSERT INTO activity_summary (date, active_energy_burned) VALUES (?,?)",
        ("2026-05-01", 650.0),
    )
    con.commit()


def test_drops_covered_seed_keeps_sync_and_partial(reconcile_seed_mod, migrated_app_db) -> None:
    con = _connect(migrated_app_db)
    try:
        _seed_and_sync(con)
        deleted = reconcile_seed_mod.reconcile_seed(con)
        con.commit()

        # D1 seed records/workouts gone; D2 seed kept; sync kept.
        seed_rec_days = [r[0] for r in con.execute("SELECT start_date FROM records WHERE origin='seed'")]
        assert seed_rec_days == [D2_SEED]
        seed_wk_days = [r[0] for r in con.execute("SELECT start_date FROM workouts WHERE origin='seed'")]
        assert seed_wk_days == [D2_SEED]
        # sync rows untouched
        assert con.execute("SELECT COUNT(*) FROM records WHERE origin='sync'").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM workouts WHERE origin='sync'").fetchone()[0] == 1
        # The deleted seed workout's child stat is gone; the kept seed workout's stat remains,
        # plus the sync workout's stat → 2 stats remain (D2 seed + D1 sync).
        assert con.execute("SELECT COUNT(*) FROM workout_statistics").fetchone()[0] == 2
        # No orphaned stats (every stat points at an existing workout).
        orphans = con.execute(
            "SELECT COUNT(*) FROM workout_statistics ws "
            "LEFT JOIN workouts w ON w.id = ws.workout_id WHERE w.id IS NULL"
        ).fetchone()[0]
        assert orphans == 0
        # activity_summary untouched.
        assert con.execute("SELECT COUNT(*) FROM activity_summary").fetchone()[0] == 1

        assert deleted == {"records": 1, "workouts": 1, "workout_statistics": 1}
    finally:
        con.close()


def test_reconcile_is_idempotent(reconcile_seed_mod, migrated_app_db) -> None:
    con = _connect(migrated_app_db)
    try:
        _seed_and_sync(con)
        reconcile_seed_mod.reconcile_seed(con)
        con.commit()
        second = reconcile_seed_mod.reconcile_seed(con)
        con.commit()
        assert second == {"records": 0, "workouts": 0, "workout_statistics": 0}
    finally:
        con.close()
