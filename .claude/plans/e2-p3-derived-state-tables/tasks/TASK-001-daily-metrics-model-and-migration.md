# TASK-001: daily_metrics model

Depends on: None
Suggested commit: `feat(database): add daily_metrics model`

## Goal

Define the `DailyMetrics` model (one row per Europe/Sofia day, with `date` as a NOT-NULL TEXT PK and
nullable `readiness_score`/`band`) and prove its schema/constraints via engine-level `create_all` on a
temp DB — **no Alembic revision is created in this task** (the single `state_tables` revision is authored
complete in TASK-003 to avoid a partial/stale stamped revision; Codex round-2 #1).

## Files

- `app/database/models/daily_metrics.py` — new: `DailyMetrics(Base)` mapped to table `daily_metrics`
  (DB.md §2):
  - `date` `Text` **`primary_key=True, nullable=False`** (Europe/Sofia day; no surrogate `id`; explicit
    `nullable=False` because a SQLite non-`WITHOUT ROWID` TEXT PK is NULL-tolerant).
  - `sleep_h` / `hrv_sdnn` / `rhr` / `hrv_30d_mean` / `hrv_30d_sd` / `rhr_30d_mean` `Float`.
  - `steps` `Integer`; `active_energy` `Float`.
  - `z1_min` / `z2_min` / `z3_min` / `z4_min` / `z5_min` `Float`.
  - `kcal_in` / `protein_in_g` / `carbs_in_g` / `fat_in_g` / `fiber_in_g` / `sodium_in_mg` / `water_in_l`
    `Float` (nutrition intake).
  - `body_weight` `Float`.
  - `hard_day` `Integer` (0/1).
  - `readiness_score` `Integer` **`nullable=True`** (filled later by the daily brief, E11 — DB.md §2
    "nullable until the daily brief runs").
  - `band` `Text` **`nullable=True`** (`GREEN`/`AMBER`/`RED`, filled alongside `readiness_score`).
  - `computed_at` `Text`.
- `app/database/models/__init__.py` — extend E2·P2's imports/`__all__` to add `DailyMetrics`
  (TASK-002/003 add the other four).
- `tests/database/test_state_models.py` — new: model-level constraint tests over a `get_engine()`/
  `make_engine(temp)` session whose schema comes from `Base.metadata.create_all(engine)` (E2·P1's WAL/FK
  listener applies) — **not** Alembic: `daily_metrics` `date=NULL` rejected; a row with
  `readiness_score`/`band` unset inserts and reads back NULL; `PRAGMA table_info(daily_metrics)` shows
  `date` `pk=1`/`notnull=1` and the INTEGER/REAL/TEXT affinities for the full column set. Extended by later
  tasks. (The Alembic up/down/parity/9-table tests land once, in TASK-003.)

## Acceptance

- [ ] `DailyMetrics` maps to table `daily_metrics`; after `Base.metadata.create_all(engine)`, `PRAGMA
      table_info(daily_metrics)` shows `date` TEXT as the PRIMARY KEY (`pk=1`) **and NOT NULL (`notnull=1`)**.
- [ ] Column affinities: `steps`/`hard_day`/`readiness_score` INTEGER; `band`/`computed_at` TEXT; the
      sleep/HRV/RHR/30d/`active_energy`/`z1_min`…`z5_min`/nutrition-intake/`body_weight` columns REAL.
- [ ] `readiness_score` and `band` are nullable: inserting a `daily_metrics` row leaving them unset succeeds
      and reads back NULL.
- [ ] Inserting a `daily_metrics` row with `date=NULL` raises `IntegrityError`.
- [ ] `import app.database.models` registers `daily_metrics` in `Base.metadata.tables`.
- [ ] **No Alembic revision is added in this task** (`alembic/versions/` is unchanged — the `state_tables`
      revision is authored complete in TASK-003).

## Steps

### RED
- [ ] Add `tests/database/test_state_models.py`: a temp-file engine whose schema is built with
      `Base.metadata.create_all(engine)`; assert `PRAGMA table_info(daily_metrics)` reports `date`
      `pk=1`/`notnull=1` and the INTEGER/REAL/TEXT affinities; inserting `date=NULL` raises `IntegrityError`;
      a row with `readiness_score`/`band` unset inserts and reads back NULL.

### GREEN
- [ ] Implement `daily_metrics.py` and register it in `models/__init__.py`. Do **not** create an Alembic
      revision here.

### REFACTOR
- [ ] Keep `date` a TEXT PK and timestamps as `Text`; ensure the model is on `Base.metadata` for the
      TASK-003 autogenerate/parity step.

## Notes

`daily_metrics` is a materialized per-day cache recomputed on sync (E6), so `date` is the natural PK (one
row per Europe/Sofia day — DB.md §2), matching the date-PK pattern E2·P2 used for `activity_summary`.
`readiness_score`/`band` stay NULL until the daily brief runs (E11), so they must be nullable for a
sync-time row to persist. This task delivers the **model only** (validated via `create_all`); the single
`state_tables` Alembic revision creating all five tables is authored in TASK-003, so there is never an
intermediate partial/stale stamped revision (Codex round-2 #1). The recompute / brief-fill write paths are
E6/E11.
