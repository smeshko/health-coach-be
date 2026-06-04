"""E5·P3 TASK-002: strength_tests upsert by server-derived iso_week."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.api.schemas.sync import StrengthTest
from app.database.models import StrengthTests
from app.services.strength_test_upsert import upsert_strength_test


def _test(d: str = "2026-06-02", **over) -> StrengthTest:
    base = {"date": d, "maxPushups": 42, "maxPullups": 11}
    base.update(over)
    return StrengthTest.model_validate(base)


def _count(session) -> int:
    return session.execute(select(func.count()).select_from(StrengthTests)).scalar_one()


def _row(session):
    return session.execute(select(StrengthTests)).scalars().one()


def test_none_writes_no_row(session) -> None:
    assert upsert_strength_test(session, None) is False
    assert _count(session) == 0


def test_base_mapping_and_iso_week(session) -> None:
    assert upsert_strength_test(session, _test("2026-06-02")) is True  # Tuesday, W23
    row = _row(session)
    assert row.iso_week == "2026-W23"
    assert row.date == "2026-06-02"
    assert row.max_pushups == 42
    assert row.max_pullups == 11
    assert row.created_at is not None


@pytest.mark.parametrize(
    "d, expected_week",
    [
        ("2026-06-07", "2026-W23"),  # Sunday → the ending week
        ("2026-06-08", "2026-W24"),  # next Monday → the next week
        ("2024-12-30", "2025-W01"),  # year boundary (Mon)
        ("2021-01-01", "2020-W53"),  # year boundary (Fri)
    ],
)
def test_iso_week_edge_dates(session, d, expected_week) -> None:
    upsert_strength_test(session, _test(d))
    assert _row(session).iso_week == expected_week


@pytest.mark.parametrize(
    "d",
    ["2026-06-02", "2026-06-07", "2026-06-08", "2024-12-30", "2021-01-01", "2026-01-04"],
)
def test_midnight_sofia_combine_is_week_stable(session, d) -> None:
    # Combining at local midnight must not shift the week vs the calendar date's own
    # ISO calendar (guards against a UTC-combine off-by-one near a day boundary).
    upsert_strength_test(session, _test(d))
    cal = date.fromisoformat(d).isocalendar()
    assert _row(session).iso_week == f"{cal[0]:04d}-W{cal[1]:02d}"


def test_one_test_per_iso_week_upserts(session) -> None:
    upsert_strength_test(session, _test("2026-06-02", maxPushups=42, maxPullups=11))  # W23
    first = _row(session)
    created_first = first.created_at
    # Second test in the SAME ISO week (2026-06-04 is also W23).
    upsert_strength_test(session, _test("2026-06-04", maxPushups=50, maxPullups=14))
    assert _count(session) == 1  # one row per week
    session.expire_all()
    row = _row(session)
    assert row.iso_week == "2026-W23"
    assert row.date == "2026-06-04"  # second values
    assert row.max_pushups == 50
    assert row.max_pullups == 14
    assert row.created_at == created_first  # preserved


def test_created_at_is_timezone_aware(session) -> None:
    upsert_strength_test(session, _test())
    assert datetime.fromisoformat(_row(session).created_at).tzinfo is not None
