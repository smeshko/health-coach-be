"""E5·P2 TASK-002: activity_summary upsert-by-date service."""

from __future__ import annotations

from sqlalchemy import func, select

from app.api.schemas.sync import ActivitySummary
from app.database.models import ActivitySummary as ActivitySummaryRow
from app.services.activity_upsert import upsert_activity


def _summary(date: str, **over) -> ActivitySummary:
    base = {
        "date": date,
        "activeEnergyKcal": 620.0,
        "exerciseMinutes": 48,
        "standHours": 11,
    }
    base.update(over)
    return ActivitySummary.model_validate(base)


def _count(session) -> int:
    return session.execute(select(func.count()).select_from(ActivitySummaryRow)).scalar_one()


def test_first_upsert_writes_rows_and_returns_count(session) -> None:
    days = upsert_activity(session, [_summary("2026-06-01"), _summary("2026-06-02")])
    assert days == 2
    assert _count(session) == 2


def test_column_mapping(session) -> None:
    upsert_activity(session, [_summary("2026-06-01")])
    row = session.execute(
        select(ActivitySummaryRow).where(ActivitySummaryRow.date == "2026-06-01")
    ).scalar_one()
    assert row.active_energy_burned == 620.0
    assert row.apple_exercise_time == 48
    assert row.apple_stand_hours == 11


def test_upsert_by_date_refreshes_in_place(session) -> None:
    upsert_activity(session, [_summary("2026-06-01", activeEnergyKcal=620.0, standHours=11)])
    upsert_activity(session, [_summary("2026-06-01", activeEnergyKcal=700.0, standHours=12)])
    assert _count(session) == 1  # one row per date
    row = session.execute(
        select(ActivitySummaryRow).where(ActivitySummaryRow.date == "2026-06-01")
    ).scalar_one()
    assert row.active_energy_burned == 700.0  # second values
    assert row.apple_stand_hours == 12


def test_steps_ignored_without_error(session) -> None:
    days = upsert_activity(session, [_summary("2026-06-01", steps=9800)])
    assert days == 1
    # steps has no column; the row still writes the ring fields.
    row = session.execute(
        select(ActivitySummaryRow).where(ActivitySummaryRow.date == "2026-06-01")
    ).scalar_one()
    assert row.active_energy_burned == 620.0
