"""`activity_summary` upsert-by-date service (E5·P2 TASK-002).

Unlike the `uuid`-keyed `records`/`workouts` tables, `activity_summary` is keyed by
the Europe/Sofia `date` and uses `ON CONFLICT(date) DO UPDATE` — a re-synced day
must **refresh** the rings in place (a delta can correct a day) (DB.md §1
"upsert by date"; epic R4). `activityDaysUpserted` therefore counts distinct dates
processed, with no duplicate split.

`ActivitySummary.steps` has no `activity_summary` column (steps live in `records` /
`daily_metrics`), so it is ignored here — not lossy (PLAN Decisions).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.api.schemas.sync import ActivitySummary
from app.database.models import ActivitySummary as ActivitySummaryRow

# The ring columns refreshed on a re-synced day (everything the wire model carries).
_REFRESH_COLUMNS = ("active_energy_burned", "apple_exercise_time", "apple_stand_hours")


def _to_row(summary: ActivitySummary) -> dict[str, Any]:
    """Map a wire `ActivitySummary` onto an `activity_summary` row (DB.md §1)."""
    return {
        "date": summary.date.isoformat(),
        "active_energy_burned": summary.active_energy_kcal,
        "apple_exercise_time": summary.exercise_minutes,
        "apple_stand_hours": summary.stand_hours,
    }


def upsert_activity(session, summaries: Iterable[ActivitySummary]) -> int:
    """Upsert each day's rings by the `date` PK; return the count of distinct dates."""
    summaries = list(summaries)
    if not summaries:
        return 0

    # Dedupe by date (last wins) so the returned distinct-date count is exact and a
    # single statement never upserts one date twice. (Modern SQLite ≥3.35 applies a
    # repeated conflict target last-wins, but older SQLite errors "cannot UPSERT a
    # row twice" — deduping keeps the write deterministic and portable either way.)
    by_date: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        row = _to_row(summary)
        by_date[row["date"]] = row

    stmt = sqlite_insert(ActivitySummaryRow).values(list(by_date.values()))
    stmt = stmt.on_conflict_do_update(
        index_elements=["date"],
        set_={col: getattr(stmt.excluded, col) for col in _REFRESH_COLUMNS},
    )
    session.execute(stmt)
    session.flush()
    return len(by_date)
