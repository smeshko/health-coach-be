"""Idempotent `workouts` (+ `workout_statistics`) upsert service (E5·P2 TASK-002).

Workouts dedupe by `uuid` (`ON CONFLICT(uuid) DO NOTHING`). Each workout's
`statistics[]` and `zoneMinutes` are persisted as `workout_statistics` child rows —
but **only for net-new workouts**, because the child table has no `uuid`, so
re-writing a duplicate workout's children would double-insert (DB.md §1; epic R5).

`zoneMinutes` has no ingest column and the canonical `daily_metrics.z1_min…z5_min`
is derived from HR records by E6, so it is captured here as `zone_minutes_z*`
statistics rows — the only durable per-workout home (PLAN Decisions).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, NamedTuple

from sqlalchemy import select

from app.api.schemas.sync import Workout
from app.database.models import Workouts, WorkoutStatistics
from app.services._upsert import insert_new_by_uuid


class WorkoutUpsertResult(NamedTuple):
    """Counts for `SyncResponse.workoutsUpserted` (no duplicate split is surfaced)."""

    upserted: int
    duplicate: int


def _to_row(workout: Workout) -> dict[str, Any]:
    """Map a wire `Workout` onto a `workouts` row (DB.md §1; MODELS Workout).

    The `*_unit` columns carry the canonical unit implied by the wire field name
    (`durationS`→seconds, `distanceM`→meters, `activeEnergyKcal`→kcal).
    """
    return {
        "uuid": workout.uuid,
        "activity_type": workout.type,
        "duration": workout.duration_s,
        "duration_unit": "s",
        "total_distance": workout.distance_m,
        "total_distance_unit": "m",
        "total_energy_burned": workout.active_energy_kcal,
        "total_energy_burned_unit": "kcal",
        "effort_score": workout.effort_score,
        "start_date": workout.start.isoformat(),
        "end_date": workout.end.isoformat(),
        "origin": "sync",
    }


def _statistics_for(workout: Workout, workout_id: int) -> list[WorkoutStatistics]:
    """Build the child `workout_statistics` rows for one net-new workout.

    Each `WorkoutStat` routes its single `value` to `maximum` for `max_*` stats,
    else `average` (DB.md §1 has distinct columns). Each present zone in
    `zoneMinutes` becomes a `zone_minutes_z*` row (`sum=<min>`, `unit="min"`).
    """
    children: list[WorkoutStatistics] = []
    for stat in workout.statistics:
        column = "maximum" if stat.type.startswith("max_") else "average"
        children.append(
            WorkoutStatistics(
                workout_id=workout_id, type=stat.type, unit=stat.unit, **{column: stat.value}
            )
        )
    if workout.zone_minutes:
        for zone, minutes in workout.zone_minutes.items():
            children.append(
                WorkoutStatistics(
                    workout_id=workout_id, type=f"zone_minutes_{zone}", sum=minutes, unit="min"
                )
            )
    return children


def upsert_workouts(session, workouts: Iterable[Workout]) -> WorkoutUpsertResult:
    """Upsert workouts by `uuid`; write child statistics for net-new workouts only."""
    workouts = list(workouts)
    rows = [_to_row(w) for w in workouts]
    new_rows, upserted, duplicate = insert_new_by_uuid(session, Workouts, rows)

    new_uuids = {r["uuid"] for r in new_rows}
    if new_uuids:
        id_by_uuid = dict(
            session.execute(
                select(Workouts.uuid, Workouts.id).where(Workouts.uuid.in_(new_uuids))
            ).all()
        )
        children: list[WorkoutStatistics] = []
        processed: set[str] = set()
        for workout in workouts:
            if workout.uuid not in new_uuids or workout.uuid in processed:
                continue
            processed.add(workout.uuid)
            children.extend(_statistics_for(workout, id_by_uuid[workout.uuid]))
        if children:
            session.add_all(children)
            session.flush()

    return WorkoutUpsertResult(upserted=upserted, duplicate=duplicate)
