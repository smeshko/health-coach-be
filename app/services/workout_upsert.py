"""Idempotent `workouts` (+ `workout_statistics`) upsert service (E5·P2 TASK-002).

Workouts dedupe by `uuid` (`ON CONFLICT(uuid) DO NOTHING`). Each workout's
`statistics[]` and `zoneMinutes` are persisted as `workout_statistics` child rows —
but **only for net-new workouts**, because the child table has no `uuid`, so
re-writing a duplicate workout's children would double-insert (DB.md §1; epic R5).

`zoneMinutes` has no ingest column and the canonical `daily_metrics.z1_min…z5_min`
is derived from HR records by E6, so it is captured here as `zone_minutes_z*`
statistics rows — the only durable per-workout home (PLAN Decisions).

**Effort (RPE) backfill + repair.** `WorkoutEffortScore` is frequently entered in Apple
Fitness *after* a workout has already synced once. Plain `DO NOTHING` would drop that
later score (the workout uuid already exists), silently defeating the documented "effort
is used when present" behaviour. So we run a targeted, guarded write over the incoming
uuids: a *valid* incoming score lands wherever the stored value is `NULL` **or outside**
`HARD_EFFORT_VALID_RANGE`. A valid stored score is still never clobbered (a later
effort-less or contradicting re-sync can't wipe one), and only `effort_score` is touched
— all other workout columns remain insert-once.

The invalid-stored case exists because the classifier treats an out-of-range score as
absent (corroborated-hard-day DECISIONS.md Decision 7): without this repair path a stored
`99` would block its own correction forever and strand the workout as permanently
effort-absent. Rejecting such payloads at `/sync` is a separate, deliberately deferred
API-contract change.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, NamedTuple

from sqlalchemy import or_, select, update

from app.api.schemas.sync import Workout
from app.database.models import Workouts, WorkoutStatistics
from app.services._upsert import insert_new_by_uuid, iter_uuid_chunks
from app.services.daily_metrics_engine import HARD_EFFORT_VALID_RANGE, is_valid_effort_score


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


def _backfill_effort_scores(session, rows: list[dict[str, Any]]) -> None:
    """Land each **valid** incoming `effort_score` on its workout, but only where the
    stored value is `NULL` or itself invalid.

    The `WHERE effort_score IS NULL OR NOT BETWEEN <lo> AND <hi>` guard is what makes this
    safe to run over **all** incoming uuids rather than only the duplicates: a net-new
    row's insert already carried a valid score, so the update is a no-op on it, while a
    batch carrying the same uuid twice — `[uuid/99, uuid/9]` — still gets repaired. That
    matters because `insert_new_by_uuid` keeps only the FIRST occurrence of a uuid, so the
    corrected copy is never inserted (round-3 #1). Where a uuid repeats, the LAST valid
    incoming score wins **the repair** — but repair only lands where the stored value is
    `NULL` or invalid, so if an earlier occurrence already stored a valid score (e.g. a
    `[uuid/7, uuid/9]` pair inserted the 7), the never-clobber guard keeps it: the FIRST
    valid score is authoritative, exactly as it is across separate syncs (review round-1
    #2 — a payload carrying two conflicting valid scores is contradictory input, and
    without ordering metadata "newer" is indistinguishable from a stale duplicate).

    An invalid incoming score is skipped outright — it is noise, not a correction, so it
    can neither fill a `NULL` nor replace another invalid value.
    """
    pending: dict[str, int] = {
        r["uuid"]: r["effort_score"] for r in rows if is_valid_effort_score(r["effort_score"])
    }
    if not pending:
        return
    lo, hi = HARD_EFFORT_VALID_RANGE
    for uuid, score in pending.items():
        session.execute(
            update(Workouts)
            .where(
                Workouts.uuid == uuid,
                or_(
                    Workouts.effort_score.is_(None),
                    ~Workouts.effort_score.between(lo, hi),
                ),
            )
            .values(effort_score=score)
        )
    session.flush()


def upsert_workouts(session, workouts: Iterable[Workout]) -> WorkoutUpsertResult:
    """Upsert workouts by `uuid`; write child statistics for net-new workouts only."""
    workouts = list(workouts)
    rows = [_to_row(w) for w in workouts]
    new_rows, upserted, duplicate = insert_new_by_uuid(session, Workouts, rows)

    new_uuids = {r["uuid"] for r in new_rows}
    # Late-arriving or corrected RPE: fill NULL / repair out-of-range effort_score.
    _backfill_effort_scores(session, rows)

    if new_uuids:
        # Chunked like the shared helper: a first-ever sync can carry more workouts
        # than SQLite's bind-variable cap allows in a single IN (...) clause.
        id_by_uuid: dict[str, int] = {}
        for chunk in iter_uuid_chunks(list(new_uuids)):
            id_by_uuid.update(
                session.execute(
                    select(Workouts.uuid, Workouts.id).where(Workouts.uuid.in_(chunk))
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
