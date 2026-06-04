"""E5·P3 TASK-001: checkins upsert-by-date service."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.api.schemas.sync import DailyCheckin
from app.database.models import Checkins
from app.services.checkin_upsert import upsert_checkin


def _checkin(date: str = "2026-06-02", **over) -> DailyCheckin:
    base = {"date": date, "giSymptoms": True, "kneePain": 4, "illness": False}
    base.update(over)
    return DailyCheckin.model_validate(base)


def _count(session) -> int:
    return session.execute(select(func.count()).select_from(Checkins)).scalar_one()


def test_none_writes_no_row(session) -> None:
    assert upsert_checkin(session, None) is False
    assert _count(session) == 0


def test_first_insert_maps_flags_and_knee_pain(session) -> None:
    assert upsert_checkin(session, _checkin()) is True
    row = session.execute(select(Checkins).where(Checkins.date == "2026-06-02")).scalar_one()
    assert row.gi_symptoms == 1
    assert row.illness == 0
    assert row.knee_pain == 4
    assert row.created_at is not None
    assert row.updated_at is not None
    assert _count(session) == 1


def test_second_post_same_date_updates_in_place(session) -> None:
    upsert_checkin(session, _checkin(giSymptoms=True, kneePain=4, illness=False))
    first = session.execute(select(Checkins).where(Checkins.date == "2026-06-02")).scalar_one()
    created_first = first.created_at
    # Second post, same date, different flags.
    upsert_checkin(session, _checkin(giSymptoms=False, kneePain=0, illness=True))
    assert _count(session) == 1  # still one row
    # The service writes via core SQL; expire the identity map so the ORM re-read
    # reflects the updated row rather than the cached pre-update object.
    session.expire_all()
    row = session.execute(select(Checkins).where(Checkins.date == "2026-06-02")).scalar_one()
    assert row.gi_symptoms == 0
    assert row.illness == 1
    assert row.knee_pain == 0
    assert row.created_at == created_first  # preserved
    # updated_at re-written (>= created; same instant acceptable, but must be present)
    assert row.updated_at is not None


def test_objective_only_columns_written(session) -> None:
    upsert_checkin(session, _checkin())
    row = session.execute(select(Checkins).where(Checkins.date == "2026-06-02")).scalar_one()
    # No body-weight column exists on Checkins; the written set is objective-only.
    written = {c for c in Checkins.__table__.columns.keys()}
    assert written == {"date", "gi_symptoms", "illness", "knee_pain", "created_at", "updated_at"}
    assert not hasattr(row, "weight")


def test_timestamps_are_timezone_aware(session) -> None:
    upsert_checkin(session, _checkin())
    row = session.execute(select(Checkins).where(Checkins.date == "2026-06-02")).scalar_one()
    assert datetime.fromisoformat(row.created_at).tzinfo is not None
    assert datetime.fromisoformat(row.updated_at).tzinfo is not None
