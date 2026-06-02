# TASK-003: plans and suggestions models and migration

Depends on: TASK-002
Suggested commit: `feat(database): add plans and suggestions models and complete state migration`

## Goal

Define the two coaching-state **output** (brief-cache) models — `Plans` (`id` PK + `UNIQUE(iso_week)`) and
`Suggestions` (`id` PK + `UNIQUE(date)`) — then author the **single, complete `state_tables` Alembic
revision in one shot** (all five E2·P3 tables, chained off E2·P2's `ingest_tables` head) so it round-trips,
brings `app.db` to **exactly the 9 tables** with **no `profile`**, and matches `Base.metadata` (parity).
There is no partial revision: TASK-001/002 added only models, so this is the first and only time the
revision exists (Codex round-2 #1).

## Files

- `app/database/models/plans.py` — new: `Plans(Base)` mapped to table `plans` (DB.md §4):
  - `id` `Integer` PK.
  - `iso_week` `Text` `nullable=False`, with a `UniqueConstraint("iso_week")` (one plan per ISO week →
    cache key).
  - `payload` `Text` **`nullable=False`** (JSON-as-TEXT — the cached weekly plan).
  - `rationale` `Text`; `inputs_snapshot` `Text` (JSON-as-TEXT); `model` `Text`; `constitution_version`
    `Text`; `created_at` `Text`.
- `app/database/models/suggestions.py` — new: `Suggestions(Base)` mapped to table `suggestions` (DB.md §4):
  - `id` `Integer` PK.
  - `date` `Text` `nullable=False`, with a `UniqueConstraint("date")` (one suggestion per day → cache key).
  - `readiness_score` `Integer`; `band` `Text`.
  - `safety_gate_tripped` `Integer` (0/1).
  - `gate_reason` `Text` **`nullable=True`** (only set when the gate trips).
  - `payload` `Text` **`nullable=False`** (JSON-as-TEXT — the cached daily session).
  - `inputs_snapshot` `Text` (JSON-as-TEXT); `model` `Text`; `constitution_version` `Text`; `created_at`
    `Text`.
- `app/database/models/__init__.py` — add `Plans` and `Suggestions` to the imports/`__all__` (all nine
  models now registered).
- `alembic/versions/<rev>_state_tables.py` — **new (created here, complete in one revision)**: `down_revision`
  = the E2·P2 `ingest_tables` head revision; `upgrade()` `create_table` for **all five** tables
  (`daily_metrics`, `checkins`, `strength_tests`, `plans`, `suggestions`) with their PK/NOT-NULL/`UNIQUE`
  constraints (`UNIQUE(iso_week)` on `strength_tests`/`plans`, `UNIQUE(date)` on `suggestions`);
  `downgrade()` drops all five (no inter-table FKs, so order is free). Best authored via
  `alembic revision --autogenerate` (the five models are already on `Base.metadata` from TASK-001/002) then
  hand-verified.
- `tests/database/test_state_migration.py` — **new**: a fixture that runs `command.upgrade(cfg, "head")` on a
  temp **file** DB via E2·P1's Alembic config (test override), then introspects schema — asserts all five
  tables + their PK/NOT-NULL/`UNIQUE(iso_week)`/`UNIQUE(date)` constraints and `payload NOT NULL`; the
  **exactly-9-tables assertion** (user tables == the 9 named tables; `'profile'` absent); the full
  `upgrade head`→`downgrade base`→`upgrade head` round-trip (after `downgrade base` none of the nine remain);
  and the **migration↔metadata parity** assertion (empty `compare_metadata`/`--autogenerate` diff after
  `upgrade head`).
- `tests/database/test_state_models.py` — extend: duplicate `plans.iso_week` → `IntegrityError`; duplicate
  `suggestions.date` → `IntegrityError`; NULL `payload` on either → `IntegrityError`; `suggestions` row with
  `gate_reason` unset reads back NULL. (Still `create_all`-based, consistent with TASK-001/002.)

## Acceptance

- [ ] After `upgrade head`, `plans` exists; `PRAGMA table_info(plans)` shows `id` INTEGER PK, `iso_week`
      TEXT NOT NULL, `payload` TEXT **NOT NULL**, `rationale`/`inputs_snapshot`/`model`/`constitution_version`/
      `created_at` TEXT; a UNIQUE index on `(iso_week)` exists; duplicate `iso_week` and NULL `payload` each
      raise `IntegrityError`.
- [ ] After `upgrade head`, `suggestions` exists; `PRAGMA table_info(suggestions)` shows `id` INTEGER PK,
      `date` TEXT NOT NULL, `readiness_score` INTEGER, `band` TEXT, `safety_gate_tripped` INTEGER,
      `gate_reason` TEXT (nullable), `payload` TEXT **NOT NULL**, `inputs_snapshot`/`model`/
      `constitution_version`/`created_at` TEXT; a UNIQUE index on `(date)` exists; duplicate `date` and NULL
      `payload` each raise `IntegrityError`; `gate_reason` reads back NULL when unset.
- [ ] **Exactly 9 tables, no `profile`:** after `upgrade head` the user-table set (excluding
      `alembic_version`) is **exactly** `records`, `workouts`, `workout_statistics`, `activity_summary`,
      `daily_metrics`, `checkins`, `strength_tests`, `plans`, `suggestions`; `'profile'` is not present.
- [ ] `import app.database.models` registers `plans` and `suggestions` (all nine now in
      `Base.metadata.tables`).
- [ ] Full `upgrade head`→`downgrade base`→`upgrade head` round-trips; after `downgrade base` none of the
      nine tables remain.
- [ ] **Migration↔metadata parity:** after `upgrade head`, an Alembic `--autogenerate`/`compare_metadata`
      against the live `Base.metadata` emits an **empty** diff (no model table missing from the now-complete
      `state_tables` revision). (Codex round-1 #1)

## Steps

### RED
- [ ] Extend `test_state_migration.py`: assert `plans`/`suggestions` columns/affinities, `payload NOT NULL`,
      the `UNIQUE(iso_week)`/`UNIQUE(date)` indexes, and the exactly-9-tables (no `profile`) assertion;
      assert the full round-trip leaves no table after `downgrade base`; add the migration↔metadata parity
      assertion (empty `--autogenerate`/`compare_metadata` diff after `upgrade head`).
- [ ] Extend `test_state_models.py`: duplicate `plans.iso_week` and duplicate `suggestions.date` each raise
      `IntegrityError`; a NULL `payload` insert on either raises `IntegrityError`; `gate_reason` reads back
      NULL when unset.

### GREEN
- [ ] Implement `plans.py` and `suggestions.py`, register both in `models/__init__.py`, then author the
      **single complete** `state_tables` Alembic revision (`down_revision` = E2·P2 ingest head) whose
      `upgrade()` creates all five tables (with their `UNIQUE` constraints) and `downgrade()` drops all five.

### REFACTOR
- [ ] Confirm the migration matches `Base.metadata` exactly via the **parity** test: after
      `command.upgrade(cfg, "head")` on a temp file DB, run `alembic.autogenerate.compare_metadata` against
      the live `Base.metadata` over the migrated connection and assert the diff is **empty** — proving no
      model table is missing from the revision (the guard against any stale/partial revision; Codex round-1
      #1 / round-2 #1). Keep `payload`/`inputs_snapshot` as `Text` (JSON-as-TEXT) and timestamps as `Text`.

## Notes

`plans` and `suggestions` are **brief-cache** tables: each caches one brief per period and the
`UNIQUE(iso_week)`/`UNIQUE(date)` constraints enforce "one brief per period" for the get-or-generate flow
(DB.md §4; ARCHITECTURE §4). They keep a surrogate `id` PK with the period column carrying the UNIQUE
constraint (unlike `daily_metrics`/`checkins`, which use `date` as the PK directly). `payload` is `NOT NULL`
(a cached brief with no body is meaningless); `inputs_snapshot`/`rationale`/`gate_reason` are nullable
snapshots. JSON is stored as TEXT (SQLite JSON1 operates on TEXT); the `?refresh=true` delete-and-regenerate
and the actual brief writes are E10/E11. The **single `state_tables` Alembic revision is created here, in
one shot, for all five tables** — TASK-001/002 added only models (validated via `create_all`), so there is
never an intermediate partial/stale stamped revision (Codex round-2 #1). After this task `Base.metadata` ↔
migration are in sync (proven by the parity test), bringing `app.db` to its full 9 tables.
