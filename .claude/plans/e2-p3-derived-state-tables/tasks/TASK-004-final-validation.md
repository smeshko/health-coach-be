# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e2-p3-derived-state-tables`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check (named command or
test), the five derived/coaching-state tables + their exact PK/UNIQUE constraints ship clean, `app.db`
holds **exactly the 9 tables with no `profile`**, and no `baseline`/dropped-stack leakage slipped in.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest tests/database` passes (all state migration + model tests green, alongside
      the E2·P1/E2·P2 suites).

### Acceptance-criteria mapping (1:1, concrete)

- [ ] **Exactly 9 tables, no `profile`** — `uv run pytest tests/database/test_state_migration.py -k "nine or
      tables or profile"` proves that after `command.upgrade(cfg, "head")` on a temp **file** DB the
      user-table set (excluding `alembic_version`) equals exactly `{records, workouts, workout_statistics,
      activity_summary, daily_metrics, checkins, strength_tests, plans, suggestions}` and `'profile'` is not
      present. (epic R3, §4; DB.md §0, §5)
- [ ] **Round-trip** — `uv run pytest tests/database/test_state_migration.py -k "round or downgrade"` proves
      `upgrade head`→`downgrade base`→`upgrade head` succeeds on a temp file DB and that after `downgrade
      base` none of the nine tables remain.
- [ ] **`daily_metrics` columns & types** — `uv run pytest tests/database/test_state_migration.py -k
      "daily_metrics"` proves `PRAGMA table_info(daily_metrics)` has `date` TEXT PK & `notnull=1`;
      `steps`/`hard_day`/`readiness_score` INTEGER; `band`/`computed_at` TEXT; and the sleep/HRV/RHR/30d/
      `active_energy`/`z1_min`…`z5_min`/`kcal_in`/`protein_in_g`/`carbs_in_g`/`fat_in_g`/`fiber_in_g`/
      `sodium_in_mg`/`water_in_l`/`body_weight` columns REAL (full column set asserted). (DB.md §2)
- [ ] **`daily_metrics` NULLs** — `uv run pytest tests/database/test_state_models.py -k "daily_metrics and
      (null or readiness or band)"` proves a row with `readiness_score`/`band` unset inserts and reads back
      NULL, and a `date=NULL` insert raises `IntegrityError`. (DB.md §2)
- [ ] **`checkins` columns & types (incl. no body_weight)** — `uv run pytest
      tests/database/test_state_migration.py -k "checkins"` proves `date` TEXT PK & `notnull=1`,
      `gi_symptoms`/`illness`/`knee_pain` INTEGER, `created_at`/`updated_at` TEXT, and that
      `'body_weight' not in` the columns; `uv run pytest tests/database/test_state_models.py -k "checkins and
      (null or date)"` proves a `date=NULL` insert raises `IntegrityError`. (DB.md §3; ARCHITECTURE §3)
- [ ] **`strength_tests` columns + UNIQUE(iso_week)** — `uv run pytest
      tests/database/test_state_migration.py -k "strength_tests"` proves `id` INTEGER PK, `date` TEXT NOT
      NULL, `iso_week` TEXT NOT NULL, `max_pushups`/`max_pullups` INTEGER, `created_at` TEXT, and a UNIQUE
      index on `(iso_week)` via `PRAGMA index_list`/`index_info`; `uv run pytest
      tests/database/test_state_models.py -k "strength_tests and (iso_week or dup or unique)"` proves two rows
      with the same `iso_week` raise `IntegrityError`. (DB.md §3; epic R5)
- [ ] **`plans` columns + UNIQUE(iso_week) + payload NOT NULL** — `uv run pytest
      tests/database/test_state_migration.py -k "plans"` proves `id` INTEGER PK, `iso_week` TEXT NOT NULL,
      `payload` TEXT `notnull=1`, `rationale`/`inputs_snapshot`/`model`/`constitution_version`/`created_at`
      TEXT, and a UNIQUE index on `(iso_week)`; `uv run pytest tests/database/test_state_models.py -k "plans
      and (iso_week or payload or dup or null)"` proves duplicate `iso_week` and NULL `payload` each raise
      `IntegrityError`. (DB.md §4; epic R5)
- [ ] **`suggestions` columns + UNIQUE(date) + payload NOT NULL + nullable gate_reason** — `uv run pytest
      tests/database/test_state_migration.py -k "suggestions"` proves `id` INTEGER PK, `date` TEXT NOT NULL,
      `readiness_score` INTEGER, `band` TEXT, `safety_gate_tripped` INTEGER, `gate_reason` TEXT (nullable),
      `payload` TEXT `notnull=1`, `inputs_snapshot`/`model`/`constitution_version`/`created_at` TEXT, and a
      UNIQUE index on `(date)`; `uv run pytest tests/database/test_state_models.py -k "suggestions and (date
      or payload or gate or dup or null)"` proves duplicate `date` and NULL `payload` each raise
      `IntegrityError` and that `gate_reason` reads back NULL when unset. (DB.md §4; epic R5)
- [ ] **Models registered on metadata** — `uv run python -c "import app.database.models as m; from
      app.database import Base; assert {'daily_metrics','checkins','strength_tests','plans','suggestions'} <=
      set(Base.metadata.tables), Base.metadata.tables"` exits 0. (epic E2·P3)
- [ ] **Migration ↔ metadata parity (no partial/stale revision)** — `uv run pytest
      tests/database/test_state_migration.py -k "parity or autogenerate or compare"` proves that after
      `upgrade head` `alembic.autogenerate.compare_metadata` against the live `Base.metadata` emits an
      **empty** diff (no model table missing from the single complete `state_tables` revision — the guard
      against a partial/stale revision; the revision is authored once in TASK-003, never grown task-by-task).
      (Codex round-1 #1, round-2 #1; epic §4)
- [ ] **No baseline / dropped-stack leakage** — `! grep -rn baseline alembic` (the new migration adds no
      `baseline` reference) **and** `! grep -REn "psycopg|pgvector|celery|redis|supabase|vecs" app` (no
      match). (DB.md §0; ARCHITECTURE §1)
- [ ] **Lint + suite** — `uv run ruff check .` and `uv run pytest tests/database` both pass.

- [ ] `PLAN.md` acceptance criteria all met (each mapped above).
