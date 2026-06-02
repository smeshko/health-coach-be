# TASK-003: activity_summary model and migration

Depends on: TASK-002
Suggested commit: `feat(database): add activity_summary model and complete ingest migration`

## Goal

Define the `ActivitySummary` model with a TEXT `date` primary key (the upsert/cache key) and finish the
ingest Alembic migration so all four ingest tables create/round-trip cleanly.

## Files

- `app/database/models/activity_summary.py` — new: `ActivitySummary(Base)` mapped to `activity_summary`:
  - `date` `Text` **`primary_key=True, nullable=False`** (Europe/Sofia date; the upsert key — no surrogate
    `id`). The explicit `nullable=False` matters: in SQLite a non-`WITHOUT ROWID` TEXT PRIMARY KEY is
    **NULL-tolerant**, so without it multiple `date=NULL` rows would slip in and break the upsert (round-1 #1).
  - `active_energy_burned` `Float` + `active_energy_burned_goal` `Float`.
  - `apple_exercise_time` `Float` + `apple_exercise_time_goal` `Float`.
  - `apple_stand_hours` `Integer` + `apple_stand_hours_goal` `Integer`.
  - `apple_move_time` `Float` + `apple_move_time_goal` `Float`.
- `app/database/models/__init__.py` — add `ActivitySummary` to the imports/`__all__`.
- `alembic/versions/<rev>_ingest_tables.py` — extend the same ingest revision: `upgrade()` also
  `create_table("activity_summary", …)`; `downgrade()` drops it (it has no FK, so order vs. the others is
  free — keep the overall downgrade child-before-parent for `workout_statistics`/`workouts`).
- `tests/database/test_ingest_migration.py` — extend: assert `activity_summary.date` is the PRIMARY KEY
  **and NOT NULL** (`PRAGMA table_info` → `pk=1` and `notnull=1` for `date`), the goal/value columns exist
  with correct affinity (`apple_stand_hours`(+`_goal`) INTEGER, the rest REAL), and the final assertion that
  **exactly** the four ingest tables (plus `alembic_version`) are present after `upgrade head`.
- `tests/database/test_ingest_models.py` — extend: inserting an `activity_summary` row with `date=NULL`
  raises `IntegrityError` (NOT NULL enforced).

## Acceptance

- [ ] After `upgrade head`, `activity_summary` exists; `PRAGMA table_info(activity_summary)` shows `date`
      TEXT as the PRIMARY KEY (`pk=1`) **and NOT NULL (`notnull=1`)**, `apple_stand_hours` +
      `apple_stand_hours_goal` INTEGER, and
      `active_energy_burned`(+`_goal`)/`apple_exercise_time`(+`_goal`)/`apple_move_time`(+`_goal`) REAL.
- [ ] Inserting an `activity_summary` row with `date=NULL` raises `IntegrityError` (date upsert key can't be
      NULL).
- [ ] After `upgrade head` the four ingest tables (`records`, `workouts`, `workout_statistics`,
      `activity_summary`) are all present (plus `alembic_version`).
- [ ] `import app.database.models` registers `activity_summary` in `Base.metadata.tables` (all four now
      present).
- [ ] Full `upgrade head`→`downgrade base`→`upgrade head` round-trips; after `downgrade base` none of the
      four ingest tables remain.

## Steps

### RED
- [ ] Extend `test_ingest_migration.py`: assert `date` is the PK of `activity_summary` **and `notnull=1`**,
      the INTEGER vs REAL affinities, and the four-tables-present check; add the round-trip-after-downgrade
      assertion that all four are gone.
- [ ] Extend `test_ingest_models.py`: inserting an `activity_summary` row with `date=NULL` raises
      `IntegrityError`.

### GREEN
- [ ] Implement `activity_summary.py`, register it in `models/__init__.py`, and add its `create_table`/
      `drop_table` to the ingest revision.

### REFACTOR
- [ ] Confirm the migration now matches `Base.metadata` exactly (a follow-up `--autogenerate` would emit an
      empty diff); keep `date` as a TEXT PK and timestamps/text as `Text`.

## Notes

`activity_summary` is upserted **by date** (one Apple-rings row per Europe/Sofia day), so the natural key
`date` is the PK — no surrogate `id`, matching the date-PK pattern `daily_metrics`/`checkins` use in E2·P3
(DB.md §1–§3). The upsert write itself is E5; this task only fixes the schema. After this task the ingest
migration is complete and `Base.metadata` ↔ migration are in sync.
