"""Offline seed: copy the trailing ~90 days from baseline.db into app.db (E4·P3).

Copies whitelisted samples from the read-only `baseline.db` corpus (E4·P1) into
`app.db`'s four ingest tables (E2·P2) so the first `/brief/weekly` has valid
7/28-day rollups and 30-day HRV/RHR baselines on day one (ARCHITECTURE §3).

The copy is a near-straight mirror **modulo exactly three deltas** (DB.md §1, §6):
  1. add `uuid` → NULL for every seed row,
  2. add `origin` → 'seed' (only on `records` + `workouts`),
  3. rename `activity_summary.date_components` → `date`.
`effort_score`/`physical_effort` have no baseline source → NULL on seed workouts.

The window is the trailing `SEED_DAYS` by **Europe/Sofia** day boundaries — the cut
is on each sample's `period_date` (E2·P1 `app/core/time.py`), DST-aware, never a
fixed offset (DB.md §0). Idempotent: a re-run deletes the prior seed slice then
re-copies (`activity_summary` re-seeds via its date-PK upsert).

Offline build step: plain `sqlite3` + `app.core.healthkit` (whitelist) +
`app.core.time` (period keys). `baseline.db` is opened **read-only** and never at
runtime; `app/` never imports this script (ARCHITECTURE §6; DB.md §0).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from app.core.healthkit import is_whitelisted
from app.core.time import SOFIA, period_date, period_date_of

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT.parent / "db" / "baseline.db"

SEED_DAYS = 90
SEED_ORIGIN = "seed"

# app.db ingest columns the seed writes (E2·P2 schema). Note: app.db's
# activity_summary has NO active_energy_burned_unit column (baseline.db does).
_RECORD_COPY_COLS = (
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
)
_WORKOUT_COPY_COLS = (
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
)
_STAT_COPY_COLS = (
    "type",
    "start_date",
    "end_date",
    "sum",
    "average",
    "minimum",
    "maximum",
    "unit",
)
# (app.db column, baseline.db column) — the rename happens on date_components.
_SUMMARY_COLS = (
    ("date", "date_components"),
    ("active_energy_burned", "active_energy_burned"),
    ("active_energy_burned_goal", "active_energy_burned_goal"),
    ("apple_exercise_time", "apple_exercise_time"),
    ("apple_exercise_time_goal", "apple_exercise_time_goal"),
    ("apple_stand_hours", "apple_stand_hours"),
    ("apple_stand_hours_goal", "apple_stand_hours_goal"),
    ("apple_move_time", "apple_move_time"),
    ("apple_move_time_goal", "apple_move_time_goal"),
)


def _window(now: datetime, days: int) -> tuple[str, str]:
    """Inclusive [start, end] Sofia day bounds for the trailing `days` window."""
    end = period_date(now)
    start = period_date(now - timedelta(days=days - 1))
    return start, end


def _in_window(sofia_day: str, start: str, end: str) -> bool:
    # period_date returns ISO YYYY-MM-DD, which sorts chronologically as text.
    return start <= sofia_day <= end


def _delete_existing_seed(app: sqlite3.Connection) -> None:
    """Wholesale-remove the prior seed slice so a re-run doesn't duplicate.

    Child workout_statistics of seed workouts go first — the FK has no
    ON DELETE CASCADE and foreign_keys=ON (E2·P1), so deleting a parent with
    surviving children would raise IntegrityError.
    """
    app.execute(
        "DELETE FROM workout_statistics WHERE workout_id IN "
        "(SELECT id FROM workouts WHERE origin = ?)",
        (SEED_ORIGIN,),
    )
    app.execute("DELETE FROM workouts WHERE origin = ?", (SEED_ORIGIN,))
    app.execute("DELETE FROM records WHERE origin = ?", (SEED_ORIGIN,))


def _seed_records(baseline: sqlite3.Connection, app: sqlite3.Connection, start: str, end: str) -> int:
    cols = ", ".join(_RECORD_COPY_COLS)
    placeholders = ", ".join("?" for _ in _RECORD_COPY_COLS)
    insert = (
        f"INSERT INTO records (uuid, origin, {cols}) "
        f"VALUES (NULL, '{SEED_ORIGIN}', {placeholders})"
    )
    n = 0
    for row in baseline.execute(f"SELECT {cols} FROM records"):
        type_, start_date = row[0], row[8]
        if not is_whitelisted(type_):
            continue
        if not _in_window(period_date_of(start_date), start, end):
            continue
        app.execute(insert, row)
        n += 1
    return n


def _seed_workouts(baseline: sqlite3.Connection, app: sqlite3.Connection, start: str, end: str) -> tuple[int, int]:
    w_cols = ", ".join(_WORKOUT_COPY_COLS)
    w_placeholders = ", ".join("?" for _ in _WORKOUT_COPY_COLS)
    w_insert = (
        f"INSERT INTO workouts (uuid, origin, effort_score, physical_effort, {w_cols}) "
        f"VALUES (NULL, '{SEED_ORIGIN}', NULL, NULL, {w_placeholders})"
    )
    s_cols = ", ".join(_STAT_COPY_COLS)
    s_placeholders = ", ".join("?" for _ in _STAT_COPY_COLS)
    s_insert = f"INSERT INTO workout_statistics (workout_id, {s_cols}) VALUES (?, {s_placeholders})"

    n_workouts = n_stats = 0
    # start_date is index 11 in _WORKOUT_COPY_COLS; also fetch baseline id (first col).
    for row in baseline.execute(f"SELECT id, {w_cols} FROM workouts"):
        baseline_id = row[0]
        copy_values = row[1:]
        start_date = copy_values[11]
        if not _in_window(period_date_of(start_date), start, end):
            continue
        cur = app.execute(w_insert, copy_values)
        new_id = cur.lastrowid
        n_workouts += 1
        for stat in baseline.execute(
            f"SELECT {s_cols} FROM workout_statistics WHERE workout_id = ?", (baseline_id,)
        ):
            app.execute(s_insert, (new_id, *stat))
            n_stats += 1
    return n_workouts, n_stats


def _seed_activity_summary(baseline: sqlite3.Connection, app: sqlite3.Connection, start: str, end: str) -> int:
    app_cols = [a for a, _ in _SUMMARY_COLS]
    base_cols = [b for _, b in _SUMMARY_COLS]
    placeholders = ", ".join("?" for _ in app_cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in app_cols if c != "date")
    # date is already a Sofia date in baseline; upsert by the date PK (no origin).
    upsert = (
        f"INSERT INTO activity_summary ({', '.join(app_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(date) DO UPDATE SET {updates}"
    )
    n = 0
    for row in baseline.execute(f"SELECT {', '.join(base_cols)} FROM activity_summary"):
        day = row[0]  # date_components, already a Sofia date
        if not _in_window(day, start, end):
            continue
        app.execute(upsert, row)
        n += 1
    return n


def seed(
    baseline_path: str | Path,
    app_db_path: str | Path,
    now: datetime,
    days: int = SEED_DAYS,
) -> dict[str, int]:
    """Seed the trailing `days` Sofia-day window into app.db; return per-table counts."""
    start, end = _window(now, days)
    baseline = sqlite3.connect(f"file:{baseline_path}?mode=ro", uri=True)
    app = sqlite3.connect(str(app_db_path))
    app.execute("PRAGMA foreign_keys = ON;")  # match runtime; enforce child-first deletes
    try:
        _delete_existing_seed(app)
        n_records = _seed_records(baseline, app, start, end)
        n_workouts, n_stats = _seed_workouts(baseline, app, start, end)
        n_summary = _seed_activity_summary(baseline, app, start, end)
        app.commit()
        return {
            "records": n_records,
            "workouts": n_workouts,
            "workout_statistics": n_stats,
            "activity_summary": n_summary,
        }
    finally:
        baseline.close()
        app.close()


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(SOFIA)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SOFIA)
    return dt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed the trailing ~90 days from baseline.db into app.db (origin=seed)."
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="source baseline.db")
    parser.add_argument("--app-db", type=Path, default=None, help="target app.db (default: settings)")
    parser.add_argument("--now", default=None, help="window end (ISO date/datetime; default today Sofia)")
    parser.add_argument("--days", type=int, default=SEED_DAYS, help="window width in days")
    args = parser.parse_args(argv)

    if not args.baseline.exists():
        print(f"error: {args.baseline} not found", file=sys.stderr)
        return 1

    app_db_path = args.app_db
    if app_db_path is None:
        from app.core.settings import get_settings

        app_db_path = Path(get_settings().app_db_path)

    counts = seed(args.baseline, app_db_path, now=_parse_now(args.now), days=args.days)
    print(" ".join(f"{table}={counts[table]}" for table in counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
