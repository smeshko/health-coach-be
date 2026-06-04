"""E5·P2 TASK-002: workouts + workout_statistics (+ zoneMinutes) upsert service."""

from __future__ import annotations

from sqlalchemy import func, select

from app.api.schemas.sync import Workout
from app.database.models import Workouts, WorkoutStatistics
from app.services.workout_upsert import WorkoutUpsertResult, upsert_workouts


def _workout(uuid: str, **over) -> Workout:
    base = {
        "uuid": uuid,
        "type": "boxing",
        "start": "2026-06-01T18:00:00+03:00",
        "end": "2026-06-01T18:45:00+03:00",
        "durationS": 2700.0,
        "distanceM": None,
        "activeEnergyKcal": 410.0,
        "effortScore": 7,
    }
    base.update(over)
    return Workout.model_validate(base)


def _wcount(session) -> int:
    return session.execute(select(func.count()).select_from(Workouts)).scalar_one()


def _scount(session) -> int:
    return session.execute(select(func.count()).select_from(WorkoutStatistics)).scalar_one()


def test_first_upsert_counts_and_origin(session) -> None:
    ws = [_workout(f"w{i}") for i in range(2)]
    result = upsert_workouts(session, ws)
    assert isinstance(result, WorkoutUpsertResult)
    assert result.upserted == 2
    assert result.duplicate == 0
    assert _wcount(session) == 2
    origins = set(session.execute(select(Workouts.origin).distinct()).scalars())
    assert origins == {"sync"}


def test_column_mapping(session) -> None:
    upsert_workouts(session, [_workout("w", distanceM=5000.0)])
    row = session.execute(select(Workouts).where(Workouts.uuid == "w")).scalar_one()
    assert row.activity_type == "boxing"
    assert row.duration == 2700.0 and row.duration_unit == "s"
    assert row.total_distance == 5000.0 and row.total_distance_unit == "m"
    assert row.total_energy_burned == 410.0 and row.total_energy_burned_unit == "kcal"
    assert row.effort_score == 7
    assert row.start_date == "2026-06-01T18:00:00+03:00"


def test_replay_is_idempotent(session) -> None:
    ws = [_workout(f"w{i}") for i in range(2)]
    upsert_workouts(session, ws)
    before = _wcount(session)
    result = upsert_workouts(session, ws)
    assert result.upserted == 0
    assert result.duplicate == 2
    assert _wcount(session) == before


def test_statistics_route_avg_and_max_columns(session) -> None:
    w = _workout(
        "w",
        statistics=[
            {"type": "avg_hr", "value": 151.0, "unit": "count/min"},
            {"type": "max_hr", "value": 189.0, "unit": "count/min"},
        ],
    )
    upsert_workouts(session, [w])
    wid = session.execute(select(Workouts.id).where(Workouts.uuid == "w")).scalar_one()
    stats = session.execute(
        select(WorkoutStatistics).where(WorkoutStatistics.type.in_(["avg_hr", "max_hr"]))
    ).scalars().all()
    by_type = {s.type: s for s in stats}
    assert by_type["avg_hr"].average == 151.0
    assert by_type["avg_hr"].maximum is None
    assert by_type["max_hr"].maximum == 189.0
    assert by_type["max_hr"].average is None
    assert by_type["avg_hr"].unit == "count/min"
    assert by_type["avg_hr"].workout_id == wid  # FK holds


def test_zone_minutes_written_as_stat_rows(session) -> None:
    w = _workout("w", zoneMinutes={"z1": 5.0, "z2": 15.0, "z3": 35.0, "z4": 15.0, "z5": 5.0})
    upsert_workouts(session, [w])
    zone_rows = session.execute(
        select(WorkoutStatistics).where(WorkoutStatistics.type.like("zone_minutes_%"))
    ).scalars().all()
    assert len(zone_rows) == 5
    by_type = {s.type: s for s in zone_rows}
    assert by_type["zone_minutes_z3"].sum == 35.0
    assert all(s.unit == "min" for s in zone_rows)


def test_replay_adds_no_statistics_rows(session) -> None:
    w = _workout(
        "w",
        statistics=[{"type": "avg_hr", "value": 151.0, "unit": "count/min"}],
        zoneMinutes={"z2": 20.0},
    )
    upsert_workouts(session, [w])
    before = _scount(session)
    assert before == 2  # one stat + one zone row
    upsert_workouts(session, [w])  # replay
    assert _scount(session) == before  # net-new only — no duplicate children
