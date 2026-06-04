"""One-time seed↔sync reconciliation (E4·P3, resolves DB.md §7's open item).

Run **after** the first live `/sync`es. Live `'sync'` rows are the authoritative
on-device HealthKit truth, so a Europe/Sofia day they cover supersedes the seed
estimate for that whole day: **a day D is "fully covered" iff ≥1 `'sync'` row exists
whose Sofia day is D**, and every `origin='seed'` row on D is dropped. A day with no
sync row keeps its seed rows (partial = not covered); `'sync'` rows are never deleted.

Scope = the origin-bearing tables `records` + `workouts` only. `activity_summary`
has no `origin` and is upserted by its `date` PK, so a live `/sync` already
overwrote the day's row — nothing to reconcile. `workout_statistics` has no `origin`
either; a seed workout's stats are removed by deleting the **child stats first**
(the FK has no ON DELETE CASCADE and foreign_keys=ON), then the parent workout.

Offline maintenance script: plain `sqlite3` + `app.core.time` (Sofia day keys).
Opens **only `app.db`** — never `baseline.db`. Idempotent: once a covered day's seed
is gone, a re-run deletes 0.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from app.core.time import period_date_of

SEED_ORIGIN = "seed"
SYNC_ORIGIN = "sync"


def _covered_days(conn: sqlite3.Connection) -> set[str]:
    """The set of Sofia days that have ≥1 'sync' row in records or workouts."""
    days: set[str] = set()
    for table in ("records", "workouts"):
        for (start_date,) in conn.execute(
            f"SELECT start_date FROM {table} WHERE origin = ?", (SYNC_ORIGIN,)
        ):
            days.add(period_date_of(start_date))
    return days


def reconcile_seed(conn: sqlite3.Connection) -> dict[str, int]:
    """Drop seed rows on fully-covered Sofia days; return per-table deleted counts."""
    covered = _covered_days(conn)
    deleted = {"records": 0, "workouts": 0, "workout_statistics": 0}
    if not covered:
        return deleted

    # workouts (+ their child stats first, since the FK has no ON DELETE CASCADE).
    seed_workouts = [
        (wid, start_date)
        for wid, start_date in conn.execute(
            "SELECT id, start_date FROM workouts WHERE origin = ?", (SEED_ORIGIN,)
        )
        if period_date_of(start_date) in covered
    ]
    for wid, _ in seed_workouts:
        cur = conn.execute("DELETE FROM workout_statistics WHERE workout_id = ?", (wid,))
        deleted["workout_statistics"] += cur.rowcount
        conn.execute("DELETE FROM workouts WHERE id = ?", (wid,))
        deleted["workouts"] += 1

    # records.
    seed_record_ids = [
        rid
        for rid, start_date in conn.execute(
            "SELECT id, start_date FROM records WHERE origin = ?", (SEED_ORIGIN,)
        )
        if period_date_of(start_date) in covered
    ]
    for rid in seed_record_ids:
        conn.execute("DELETE FROM records WHERE id = ?", (rid,))
        deleted["records"] += 1

    return deleted


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile seed↔sync: drop seed rows on Sofia days covered by live sync."
    )
    parser.add_argument("--app-db", type=Path, default=None, help="target app.db (default: settings)")
    args = parser.parse_args(argv)

    app_db_path = args.app_db
    if app_db_path is None:
        from app.core.settings import get_settings

        app_db_path = Path(get_settings().app_db_path)

    conn = sqlite3.connect(str(app_db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        deleted = reconcile_seed(conn)
        conn.commit()
    finally:
        conn.close()
    print(" ".join(f"{table}={deleted[table]}" for table in deleted))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
