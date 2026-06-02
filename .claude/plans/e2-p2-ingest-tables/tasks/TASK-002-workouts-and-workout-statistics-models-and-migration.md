# TASK-002: workouts and workout_statistics models and migration

Depends on: TASK-001
Suggested commit: `feat(database): add workouts + workout_statistics models and FK migration`

## Goal

Define the `Workouts` and `WorkoutStatistics` models (the latter FK→`workouts(id)`) and extend the ingest
Alembic migration to create both tables — `workouts` with `UNIQUE(uuid)`, `workout_statistics` with the
`(workout_id, type)` index and a FK whose `downgrade` drops the child table first.

## Files

- `app/database/models/workouts.py` — new: `Workouts(Base)` mapped to `workouts`:
  - `id` `Integer` PK; `uuid` `Text` **`nullable=True`** + `UniqueConstraint("uuid")`.
  - `activity_type` `Text` `nullable=False`.
  - `duration` `Float` + `duration_unit` `Text`; `total_distance` `Float` + `total_distance_unit` `Text`;
    `total_energy_burned` `Float` + `total_energy_burned_unit` `Text`.
  - `effort_score` `Float` `nullable=True` (RPE 1–10 from `WorkoutEffortScore`); `physical_effort` `Float`
    `nullable=True` (METs proxy).
  - `source_name` / `source_version` / `device` / `creation_date` `Text`.
  - `start_date` `Text` `nullable=False`; `end_date` `Text`; `origin` `Text` `nullable=False`.
  - `__table_args__`: `UniqueConstraint("uuid")`.
- `app/database/models/workout_statistics.py` — new: `WorkoutStatistics(Base)` mapped to
  `workout_statistics`:
  - `id` `Integer` PK; `workout_id` `Integer` `nullable=False`, `ForeignKey("workouts.id")`.
  - `type` `Text` `nullable=False`; `start_date` / `end_date` `Text`.
  - `sum` / `average` / `minimum` / `maximum` `Float`; `unit` `Text`.
  - `__table_args__`: `Index(None, "workout_id", "type")`.
- `app/database/models/__init__.py` — add `Workouts`, `WorkoutStatistics` to the imports/`__all__`.
- `alembic/versions/<rev>_ingest_tables.py` — extend the TASK-001 revision: `upgrade()` also
  `create_table("workouts", …)` then `create_table("workout_statistics", …)` (parent before child) + the
  `(workout_id, type)` index; `downgrade()` drops `workout_statistics` **before** `workouts` (and after the
  TASK-003 tables as ordered there).
- `tests/database/test_ingest_migration.py` — extend: assert `workouts`/`workout_statistics` columns/types,
  `UNIQUE(uuid)` on `workouts`, the `(workout_id, type)` index, and the FK via `PRAGMA
  foreign_key_list(workout_statistics)`.
- `tests/database/test_ingest_models.py` — extend: duplicate non-NULL `workouts.uuid` → `IntegrityError`;
  inserting a `workout_statistics` row with a non-existent `workout_id` over a `foreign_keys=ON`
  connection → `IntegrityError`.

## Acceptance

- [ ] After `upgrade head`, `workouts` and `workout_statistics` exist; `PRAGMA table_info` matches the
      column/type/nullability spec above (`effort_score`/`physical_effort` REAL nullable; `workout_id`
      INTEGER NOT NULL).
- [ ] `workouts` has a UNIQUE index on `(uuid)`; inserting two rows with the same non-NULL `uuid` raises
      `IntegrityError`.
- [ ] **`workouts` NULL-uuid seedability (round-1 #2):** inserting two `workouts` rows with `uuid=NULL` both
      succeed — the E4 90-day seed path; this proves `uuid` is nullable, not NOT NULL (mirrors `records`).
- [ ] `PRAGMA foreign_key_list(workout_statistics)` shows `workout_id` → `workouts(id)`; an index on
      `(workout_id, type)` exists.
- [ ] Inserting a `workout_statistics` row with a non-existent `workout_id` raises `IntegrityError` (FK
      enforced via E2·P1's `PRAGMA foreign_keys=ON`).
- [ ] `downgrade base` drops `workout_statistics` before `workouts` without an FK error; round-trip green.
- [ ] `import app.database.models` registers both tables in `Base.metadata.tables`.

## Steps

### RED
- [ ] Extend `test_ingest_migration.py`: assert both tables' columns/types, `workouts` UNIQUE(uuid), the
      `(workout_id, type)` index, and the FK row from `PRAGMA foreign_key_list`.
- [ ] Extend `test_ingest_models.py`: two `uuid=NULL` `workouts` rows both insert (seedability); duplicate
      non-NULL `workouts.uuid` → `IntegrityError`; orphan `workout_id` insert → `IntegrityError` over a
      connection with FK enforcement on.

### GREEN
- [ ] Implement `workouts.py` + `workout_statistics.py`, register them in `models/__init__.py`, and extend
      the ingest revision's `upgrade`/`downgrade` (parent-before-child create; child-before-parent drop).

### REFACTOR
- [ ] Keep FK declared via `ForeignKey("workouts.id")` so the `naming_convention` names it `fk_…`; ensure
      drop order is FK-safe and all timestamp columns are `Text`.

## Notes

The FK is only enforced because E2·P1's `set_sqlite_pragmas` connect listener issues `PRAGMA
foreign_keys=ON` (SQLite defaults it OFF per connection); the orphan-insert test must run over a
`get_engine()`/`make_engine()` connection that carries that listener, not a raw `sqlite3.connect`. Create
`workouts` before `workout_statistics` in `upgrade` and drop in reverse in `downgrade` so the round-trip
doesn't hit a dangling-reference error.
