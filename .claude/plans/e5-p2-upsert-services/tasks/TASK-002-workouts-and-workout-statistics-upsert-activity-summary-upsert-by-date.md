# TASK-002: workouts and workout_statistics upsert; activity_summary upsert by date

Depends on: TASK-001
Suggested commit: `feat(sync): add workout (+statistics/zoneMinutes) and activity_summary upsert services`

## Goal

Add `app/services/workout_upsert.py` (`upsert_workouts` — `ON CONFLICT(uuid) DO NOTHING`, writing
`workout_statistics` from `statistics[]` **and** `zoneMinutes` for net-new workouts only) and
`app/services/activity_upsert.py` (`upsert_activity` — upsert by the `date` PK), completing the three
ingest upsert services `/sync` calls.

## Files

- `app/services/workout_upsert.py` (new) — `WorkoutUpsertResult` (`upserted: int`, `duplicate: int`) and
  `def upsert_workouts(session: Session, workouts: Iterable[Workout]) -> WorkoutUpsertResult`:
  - map each `Workout` → a `Workouts` row: `uuid`→`uuid`, `type`→`activity_type`, `durationS`→
    `duration` (`duration_unit='s'`), `distanceM`→`total_distance` (`total_distance_unit='m'`),
    `activeEnergyKcal`→`total_energy_burned` (`total_energy_burned_unit='kcal'`), `effortScore`→
    `effort_score`, `start`→`start_date`, `end`→`end_date`, `origin='sync'` (DB.md §1; MODELS Workout).
  - pre-select existing `uuid`s in one query, partition, insert only net-new via
    `sqlalchemy.dialects.sqlite.insert(Workouts).…on_conflict_do_nothing(index_elements=["uuid"])`,
    `flush()` to get the inserted rows' `id`s; counts `upserted`/`duplicate` as in TASK-001.
  - for **net-new** workouts **only** (their `uuid` was not pre-existing), write child
    `WorkoutStatistics` rows:
    - one per `WorkoutStat` in `statistics[]`: `type`→`type`, `unit`→`unit`, `workout_id`→the parent
      `id`, and route the single wire `value` to the column that matches the stat kind —
      `value`→`maximum` when `type` starts with `max_` (e.g. `max_hr`/`max_speed`), else `value`→
      `average` (the `avg_*` stats). DB.md §1 gives `workout_statistics` distinct `average`/`maximum`
      columns, so a `max_*` value must not land in `average` (round-1 #1; DB.md §1; MODELS WorkoutStat).
    - one per present zone in `zoneMinutes` (if not `None`): `type=f"zone_minutes_{z}"` (e.g.
      `zone_minutes_z1`), `sum=<minutes>`, `unit="min"`, `workout_id`→parent `id` (Decisions — the
      only durable per-workout home for `zoneMinutes`; canonical `daily_metrics` zone-min is E6).
  - duplicate workouts (conflict → `DO NOTHING`) get **no** new statistics rows (they already have them
    from the first sync — `workout_statistics` has no `uuid`, so re-writing would double-insert).
  - `flush`, do not commit.
- `app/services/activity_upsert.py` (new) — `def upsert_activity(session: Session, summaries:
  Iterable[ActivitySummary]) -> int`:
  - map each `ActivitySummary` → an `activity_summary` row: `date`(ISO `YYYY-MM-DD`)→`date`,
    `activeEnergyKcal`→`active_energy_burned`, `exerciseMinutes`→`apple_exercise_time`, `standHours`→
    `apple_stand_hours`; **`steps` has no column → ignored** (DB.md §1; Decisions).
  - upsert by the `date` PK: `insert(ActivitySummary).values(rows).on_conflict_do_update(
    index_elements=["date"], set_={...the ring columns...})` — a re-synced day **refreshes** in place.
  - return the count of dates processed (`activityDaysUpserted`).
- `tests/services/test_workout_upsert.py` (new) — workout + statistics + zoneMinutes + replay tests.
- `tests/services/test_activity_upsert.py` (new) — upsert-by-date + steps-ignored tests.
  (Both reuse the migrated temp-file `app.db` session fixture from `tests/services/conftest.py`.)

## Acceptance

- [ ] `from app.services.workout_upsert import upsert_workouts` and
      `from app.services.activity_upsert import upsert_activity` succeed.
- [ ] First `upsert_workouts` of N workouts → `upserted=N`, `duplicate=0`, `count(*) workouts == N`,
      every row `origin='sync'`; **replay** → `upserted=0`, `duplicate=N`, `count(*)` unchanged.
- [ ] A workout with `statistics=[avg_hr(151), max_hr(189)]` writes two `workout_statistics` rows: the
      `avg_hr` row has `average=151` (`maximum` NULL) and the `max_hr` row has `maximum=189` (`average`
      NULL), both `unit="count/min"`, FK'd to the workout — i.e. `max_*` routes to `maximum`, `avg_*` to
      `average` (round-1 #1; DB.md §1; MODELS WorkoutStat).
- [ ] A workout with `zoneMinutes={z1:5,z2:15,z3:35,z4:15,z5:5}` writes five `zone_minutes_z*` rows
      (`sum=5/15/35/15/5`, `unit="min"`), FK'd to the workout (Decisions; MODELS Workout `zoneMinutes`).
- [ ] **Replay** of a workout batch adds **zero** new `workout_statistics` rows
      (`SELECT count(*) FROM workout_statistics` unchanged) — statistics written only for net-new
      workouts.
- [ ] `upsert_activity` of M summaries → returns M and writes M rows; **re-posting the same `date`**
      with different ring values leaves **one** row carrying the **second** values (upsert-by-date).
- [ ] `ActivitySummary.steps` set on the wire does **not** error and is **not** written (no column).
- [ ] `uv run ruff check app/services/workout_upsert.py app/services/activity_upsert.py tests/services`
      is clean.

## Steps

### RED
- [ ] Add `tests/services/test_workout_upsert.py` (counts + replay; `statistics[]`→rows with `avg_*`→
      `average`/`max_*`→`maximum`; `zoneMinutes`→`zone_minutes_z*` rows; replay adds no stat rows; FK
      holds; `origin='sync'`) and
      `tests/services/test_activity_upsert.py` (upsert-by-date refresh; one row per date; steps ignored).
      Run — fails (no modules).

### GREEN
- [ ] Add `app/services/workout_upsert.py` and `app/services/activity_upsert.py` per **Files**
      (workout `on_conflict_do_nothing(uuid)` + flush + children for net-new only; activity
      `on_conflict_do_update(date)`). Run — tests pass.

### REFACTOR
- [ ] Factor the shared "pre-select existing `uuid`s → partition → insert net-new → counts" logic used
      by records (TASK-001) and workouts into a tiny private helper if it reads cleanly (keep it
      table-agnostic; don't over-abstract); confirm `ruff check` is clean.

## Notes

`workout_statistics` has **no** `uuid` and is a pure child of `workouts`, so idempotency is achieved by
writing children **only for the workout `uuid`s that were net-new this call** — a replay's workouts all
conflict (`DO NOTHING`), so no children are added. `flush()` the inserted `Workouts` before building
children so their auto `id`s exist (FK enforced via E2·P1's `foreign_keys=ON`). The unit literals
(`'s'`/`'m'`/`'kcal'`) come from the wire field names (`durationS`/`distanceM`/`activeEnergyKcal` —
MODELS Workout). `activity_summary` is the **only** upsert-by-`date` table this phase and uses
`on_conflict_do_update` (a corrected day must refresh), unlike the `DO NOTHING` `uuid` tables.
