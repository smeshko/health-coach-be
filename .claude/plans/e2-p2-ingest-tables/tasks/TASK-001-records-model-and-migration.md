# TASK-001: records model and migration

Depends on: None
Suggested commit: `feat(database): add records ingest model and Alembic migration`

## Goal

Define the `Records` SQLAlchemy model under `app/database/models/` (mirroring `baseline.db` plus
`uuid`/`origin`) and stamp the start of the ingest Alembic migration that creates the `records` table with
`UNIQUE(uuid)` + `(type, start_date)` + `(start_date)` indexes.

## Files

- `app/database/models/__init__.py` — new: import/re-export the ingest models so `import
  app.database.models` registers them on `Base.metadata`. This task adds `Records`; TASK-002/003 extend it.
- `app/database/models/records.py` — new: `Records(Base)` mapped to table `records`:
  - `id` `Integer` PK.
  - `uuid` `Text`/`String`, **`nullable=True`**, with a `UniqueConstraint("uuid")` (NULL for seeded rows;
    NULLs are distinct under the unique index).
  - `type` `Text` `nullable=False`; `unit` `Text`; `value` `Float` (REAL); `value_text` `Text`.
  - `source_name` / `source_version` / `device` `Text`; `creation_date` `Text`.
  - `start_date` `Text` `nullable=False`; `end_date` `Text`.
  - `origin` `Text` `nullable=False`.
  - `__table_args__`: `UniqueConstraint("uuid")`, `Index(None, "type", "start_date")`,
    `Index(None, "start_date")` — names supplied by E2·P1's `naming_convention`.
- `alembic/versions/<rev>_ingest_tables.py` — new (autogenerate then hand-verify): `down_revision` = the
  E2·P1 initial revision; `upgrade()` `create_table("records", …)` with the columns above + the three
  indexes; `downgrade()` `drop_table("records")` (TASK-002/003 add the other tables to this same revision).
- `tests/database/test_ingest_migration.py` — new: a fixture that runs `command.upgrade(cfg, "head")` on a
  temp **file** DB via E2·P1's Alembic config (test override), then introspects schema. This task adds the
  `records` assertions; TASK-002/003 extend the same file.
- `tests/database/test_ingest_models.py` — new: model-level constraint tests over a `get_engine()`/
  `make_engine(temp)` session (UNIQUE uuid behaviour). Extended by later tasks.

## Acceptance

- [ ] After `upgrade head`, `records` exists in `sqlite_master` with columns `id`, `uuid`, `type`, `unit`,
      `value`, `value_text`, `source_name`, `source_version`, `device`, `creation_date`, `start_date`,
      `end_date`, `origin`.
- [ ] `PRAGMA table_info(records)`: `id` INTEGER PK; `type` NOT NULL; `start_date` NOT NULL; `origin` NOT
      NULL; `uuid`/`unit`/`value_text`/`end_date` nullable; `value` REAL affinity; timestamps TEXT affinity.
- [ ] Introspection shows a **UNIQUE** index on `(uuid)`, a non-unique index on `(type, start_date)`, and a
      non-unique index on `(start_date)`.
- [ ] Inserting two `records` rows with `uuid=NULL` both succeed; inserting two with the **same non-NULL**
      `uuid` raises `IntegrityError`.
- [ ] `import app.database.models` registers `records` in `Base.metadata.tables`.
- [ ] `upgrade head`→`downgrade base`→`upgrade head` round-trips (with whatever tables exist at this point).

## Steps

### RED
- [ ] `tests/database/test_ingest_migration.py`: build a temp-file Alembic config (E2·P1 test override),
      `command.upgrade(cfg, "head")`, assert `records` in `sqlite_master`, assert `PRAGMA table_info` types/
      nullability, and assert the three indexes via `PRAGMA index_list`/`index_info` (one UNIQUE on `uuid`).
- [ ] `tests/database/test_ingest_models.py`: over a `make_engine(tmp)` session, assert two NULL-uuid rows
      insert and a duplicate non-NULL uuid raises `IntegrityError`.

### GREEN
- [ ] Implement `app/database/models/records.py` + `app/database/models/__init__.py`; autogenerate the
      Alembic revision (`down_revision` = E2·P1 initial), hand-verify it creates `records` + the three
      indexes, and that `downgrade` drops it.

### REFACTOR
- [ ] Let the `naming_convention` name the constraints/indexes (don't hard-code names); keep all timestamp
      columns `Text`, never `DateTime`.

## Notes

`records.uuid` is **UNIQUE but nullable** — seeded rows (E4) carry no HealthKit UUID, and SQLite treats
each NULL as distinct under a unique index, so the constraint admits all seeded rows while rejecting
duplicate live UUIDs (DB.md §1). The idempotent `INSERT … ON CONFLICT(uuid) DO NOTHING` write path is
**E5**, not here — this task only proves the constraint via raw duplicate inserts. Test against a **file**
DB, not `:memory:`.
