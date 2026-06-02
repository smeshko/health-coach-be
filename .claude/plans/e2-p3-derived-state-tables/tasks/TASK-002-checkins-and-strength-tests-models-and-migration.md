# TASK-002: checkins and strength_tests models

Depends on: TASK-001
Suggested commit: `feat(database): add checkins and strength_tests models`

## Goal

Define the two coaching-state **input** models — `Checkins` (objective-only, `date` TEXT PK, no body-weight
field) and `StrengthTests` (`id` PK + `UNIQUE(iso_week)`) — and prove their schema/constraints via
engine-level `create_all` on a temp DB. **No Alembic revision in this task** — the single `state_tables`
revision is authored complete in TASK-003 (Codex round-2 #1).

## Files

- `app/database/models/checkins.py` — new: `Checkins(Base)` mapped to table `checkins` (DB.md §3):
  - `date` `Text` **`primary_key=True, nullable=False`** (Europe/Sofia day; upsertable by date — same
    NULL-tolerant TEXT-PK guard as `daily_metrics`).
  - `gi_symptoms` `Integer` (0/1 — any GI flare sign).
  - `illness` `Integer` (0/1).
  - `knee_pain` `Integer` (0–10, 0 = none).
  - `created_at` / `updated_at` `Text`.
  - **No `body_weight` column** — objective-only; weight is HealthKit `body_mass` → `daily_metrics.body_weight`
    (DB.md §3; ARCHITECTURE §3).
- `app/database/models/strength_tests.py` — new: `StrengthTests(Base)` mapped to table `strength_tests`
  (DB.md §3):
  - `id` `Integer` PK.
  - `date` `Text` `nullable=False`.
  - `iso_week` `Text` `nullable=False`, with a `UniqueConstraint("iso_week")` (one test per week).
  - `max_pushups` / `max_pullups` `Integer`.
  - `created_at` `Text`.
- `app/database/models/__init__.py` — add `Checkins` and `StrengthTests` to the imports/`__all__`.
- `tests/database/test_state_models.py` — extend (still using `Base.metadata.create_all(engine)` on a temp
  DB, no Alembic): assert `checkins.date` is the PK **and NOT NULL** and has **no** `body_weight` column;
  assert `strength_tests` columns/affinities and a UNIQUE index on `(iso_week)`; `checkins` `date=NULL`
  raises `IntegrityError`; inserting two `strength_tests` rows with the same `iso_week` raises
  `IntegrityError`. (The Alembic migration creating these tables is authored in TASK-003.)

## Acceptance

- [ ] After `Base.metadata.create_all(engine)`, `checkins` exists; `PRAGMA table_info(checkins)` shows
      `date` TEXT PK (`pk=1`) **and NOT NULL (`notnull=1`)**, `gi_symptoms`/`illness`/`knee_pain` INTEGER,
      `created_at`/`updated_at` TEXT, and **no `body_weight` column**; `date=NULL` raises `IntegrityError`.
- [ ] After `create_all`, `strength_tests` exists; `PRAGMA table_info(strength_tests)` shows `id` INTEGER
      PK, `date` TEXT NOT NULL, `iso_week` TEXT NOT NULL, `max_pushups`/`max_pullups` INTEGER, `created_at`
      TEXT.
- [ ] A UNIQUE index on `strength_tests(iso_week)` exists (`PRAGMA index_list`/`index_info`); inserting two
      rows with the same `iso_week` raises `IntegrityError`.
- [ ] `import app.database.models` registers `checkins` and `strength_tests` in `Base.metadata.tables`.
- [ ] **No Alembic revision is added in this task** (`alembic/versions/` unchanged — the migration is
      authored in TASK-003).

## Steps

### RED
- [ ] Extend `test_state_models.py` (engine `create_all`, no Alembic): assert `checkins.date` PK + `notnull=1`
      and that `'body_weight' not in` its columns; assert `strength_tests` columns/affinities and the
      `UNIQUE(iso_week)` index; `checkins` `date=NULL` → `IntegrityError`; duplicate `strength_tests.iso_week`
      → `IntegrityError`.

### GREEN
- [ ] Implement `checkins.py` and `strength_tests.py` (the latter with the `UniqueConstraint("iso_week")`)
      and register both in `models/__init__.py`. Do **not** create an Alembic revision here.

### REFACTOR
- [ ] Keep `date`/`iso_week`/timestamps as `Text`; ensure both models are on `Base.metadata` for the
      TASK-003 autogenerate/parity step.

## Notes

The check-in is **objective-only** (readiness is physiological — DB.md §3, ARCHITECTURE §3): no subjective
self-report and **no body-weight field** (weight is HealthKit `body_mass`). `knee_pain` is `0–10` (0 = none),
not a boolean. `strength_tests` keeps a surrogate `id` PK with `iso_week` carrying the UNIQUE "one test per
week" constraint (DB.md §3; epic R5). The 0/1 and 0–10 ranges are write-layer invariants (E5), not DB CHECK
constraints — the schema mirrors DB.md without inventing constraints it doesn't specify.
