# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e2-p2-ingest-tables`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check (named command or
test), the four ingest tables + their exact UNIQUE/index/FK constraints ship clean, and no
`baseline`/dropped-stack leakage slipped in.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest tests/database` passes (all ingest migration + model tests green).

### Acceptance-criteria mapping (1:1, concrete)

- [ ] **Four ingest tables created** — `uv run pytest tests/database/test_ingest_migration.py -k "tables or
      created"` proves that after `command.upgrade(cfg, "head")` on a temp **file** DB, `sqlite_master`
      contains `records`, `workouts`, `workout_statistics`, `activity_summary`. (epic §3, §4; DB.md §1)
- [ ] **Round-trip** — `uv run pytest tests/database/test_ingest_migration.py -k "round or downgrade"`
      proves `upgrade head`→`downgrade base`→`upgrade head` succeeds on a temp file DB, and that after
      `downgrade base` none of the four ingest tables remain (FK drop order `workout_statistics` before
      `workouts` does not error).
- [ ] **`records` columns & types** — `uv run pytest tests/database/test_ingest_migration.py -k "records"`
      proves `PRAGMA table_info(records)` has `id` INTEGER PK; `type`/`start_date`/`origin` NOT NULL; `uuid`
      nullable; `value` REAL; timestamps TEXT (full column set asserted).
- [ ] **`records` indexes** — `uv run pytest tests/database/test_ingest_migration.py -k "records_index or
      index"` proves a UNIQUE index on `(uuid)`, a non-unique index on `(type, start_date)`, and a
      non-unique index on `(start_date)` via `PRAGMA index_list`/`index_info`.
- [ ] **`records.uuid` UNIQUE, NULL-tolerant** — `uv run pytest tests/database/test_ingest_models.py -k
      "records and (null or uuid)"` proves two `uuid=NULL` rows both insert and two same-non-NULL-`uuid`
      rows raise `IntegrityError`.
- [ ] **`workouts` columns & types** — `uv run pytest tests/database/test_ingest_migration.py -k "workouts"`
      proves `PRAGMA table_info(workouts)` matches the spec (`effort_score`/`physical_effort` REAL nullable;
      `activity_type`/`start_date`/`origin` NOT NULL; `*_unit` TEXT).
- [ ] **`workouts.uuid` UNIQUE, NULL-tolerant** — `uv run pytest tests/database/test_ingest_models.py -k
      "workouts and uuid"` proves two `uuid=NULL` `workouts` rows both insert (E4 seedability) and a
      duplicate non-NULL `workouts.uuid` raises `IntegrityError`. (round-1 #2)
- [ ] **`workout_statistics` columns & types** — `uv run pytest tests/database/test_ingest_migration.py -k
      "workout_statistics and (column or table_info or type)"` proves `PRAGMA table_info(workout_statistics)`
      shows `id` INTEGER PK, `workout_id` INTEGER NOT NULL, `type` TEXT NOT NULL, `start_date`/`end_date`
      TEXT, `sum`/`average`/`minimum`/`maximum` REAL, and `unit` TEXT (so a missing/mistyped aggregate
      column fails final validation). (round-2 #1; PLAN.md acceptance; DB.md §1)
- [ ] **`workout_statistics` FK + index** — `uv run pytest tests/database/test_ingest_migration.py -k "fk or
      foreign or workout_statistics"` proves `PRAGMA foreign_key_list(workout_statistics)` shows `workout_id`
      → `workouts(id)` and an index on `(workout_id, type)` exists; `uv run pytest
      tests/database/test_ingest_models.py -k "orphan or fk"` proves inserting a row with a non-existent
      `workout_id` raises `IntegrityError` (FK enforced via E2·P1's `foreign_keys=ON`).
- [ ] **`activity_summary` PK & types (incl. date NOT NULL)** — `uv run pytest
      tests/database/test_ingest_migration.py -k "activity_summary"` proves `date` TEXT is the PRIMARY KEY
      (`pk=1`) **and `notnull=1`**, `apple_stand_hours`(+`_goal`) are INTEGER, and the
      energy/exercise/move(+`_goal`) columns are REAL; `uv run pytest tests/database/test_ingest_models.py
      -k "activity_summary and (null or date)"` proves inserting a row with `date=NULL` raises
      `IntegrityError`. (round-1 #1)
- [ ] **Models registered on metadata** — `uv run python -c "import app.database.models as m; from
      app.database import Base; assert {'records','workouts','workout_statistics','activity_summary'} <=
      set(Base.metadata.tables), Base.metadata.tables"` exits 0.
- [ ] **No baseline / dropped-stack leakage** — `! grep -rn baseline alembic` (the new migration adds no
      `baseline` reference) **and** `! grep -REn "psycopg|pgvector|celery|redis|supabase|vecs" app` (no
      match). (DB.md §0; ARCHITECTURE §1)
- [ ] **Lint + suite** — `uv run ruff check .` and `uv run pytest tests/database` both pass.

- [ ] `PLAN.md` acceptance criteria all met (each mapped above).
