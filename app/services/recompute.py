"""`daily_metrics` recompute SEAM (E5·P3 TASK-003).

DB.md §6 says the `/sync` write path ends with "recompute `daily_metrics` for
affected dates" — but **computing** those values is E6. This module ships only the
*seam*: the `RecomputeDailyMetrics` protocol E6's engine implements, a no-op default,
and the `affected_dates(...)` fan-out. The `/sync` route injects the provider, so E6
swaps in the real engine by overriding the provider — no route change.

Pure: no FastAPI/HTTP imports.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from app.api.schemas.sync import SyncRequest
from app.core.healthkit import filter_whitelisted_records
from app.core.time import to_sofia


@runtime_checkable
class RecomputeDailyMetrics(Protocol):
    """The recompute contract E6 implements. This phase ships a no-op default."""

    def __call__(self, dates: set[date]) -> None: ...


def noop_recompute(dates: set[date]) -> None:
    """Default seam implementation — does nothing (the engine is E6; DB.md §6)."""
    return None


def affected_dates(request: SyncRequest) -> set[date]:
    """The set of Europe/Sofia dates this sync changed — the recompute fan-out.

    Every touched datum is bucketed to its **Europe/Sofia** date (not the wire
    offset), so an offset that crosses the Sofia day boundary lands on the Sofia day
    (ARCHITECTURE §4). Only **whitelisted** records contribute (a non-whitelisted
    record is not stored, so it changes no day's data). Workouts and activity
    summaries are not type-gated, so all contribute. Returns a de-duplicated set,
    possibly empty (an empty body, or one whose only records are non-whitelisted).
    """
    dates: set[date] = set()
    for record in filter_whitelisted_records(request.records):
        dates.add(to_sofia(record.start).date())
    for workout in request.workouts:
        dates.add(to_sofia(workout.start).date())
    for summary in request.activity_summary:
        dates.add(summary.date)
    if request.checkin is not None:
        dates.add(request.checkin.date)
    if request.strength_test is not None:
        dates.add(request.strength_test.date)
    return dates
