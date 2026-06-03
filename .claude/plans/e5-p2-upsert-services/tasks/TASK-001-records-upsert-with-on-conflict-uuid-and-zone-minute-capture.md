# TASK-001: records upsert with ON CONFLICT uuid and zone-minute capture

Depends on: None
Suggested commit: `feat(sync): add idempotent records upsert service (ON CONFLICT uuid, whitelist, origin=sync)`

## Goal

Add `app/services/record_upsert.py` `upsert_records(session, records)` that filters to whitelisted types,
maps each `HealthRecord` to a `Records` row, and writes `INSERT … ON CONFLICT(uuid) DO NOTHING`,
returning an exact `upserted` / `duplicate` split — the idempotent foundation the `/sync` counts read.

> **Re: the task title's "zone-minute capture"** — at the **records** level this means landing the HR
> samples losslessly; the deterministic engine's zone-minutes (`daily_metrics.z1_min…z5_min`) are
> **derived from those HR records by E6·P1** (DB.md §2), out of scope here. The **workout's** `zoneMinutes`
> field is persisted separately in **TASK-002** (as `workout_statistics` rows) — there is no zone writer
> in this task, by design.

## Files

- `app/services/__init__.py` (new, if absent) — package marker so `app.services` imports.
- `app/services/record_upsert.py` (new) — `RecordUpsertResult` (a small frozen dataclass or
  `NamedTuple` with `upserted: int`, `duplicate: int`) and
  `def upsert_records(session: Session, records: Iterable[HealthRecord]) -> RecordUpsertResult`:
  - `from app.core.healthkit import filter_whitelisted_records` — drop non-whitelisted `records.type`
    **first** (DB.md §1; epic R3).
  - map each surviving `HealthRecord` → a `Records` dict/row: `uuid`→`uuid`, `type` (the `RecordType`
    **value** string, i.e. `r.type.value`)→`type`, `value`→`value`, `category`→`value_text`,
    `unit`→`unit`, `start`(ISO str)→`start_date`, `end`(ISO str)→`end_date`, `source`→`source_name`,
    `origin='sync'` (DB.md §1 column semantics — `value_text` holds category enums).
  - count `upserted` vs `duplicate` deterministically: in **one** query, `SELECT uuid FROM records WHERE
    uuid IN (:batch_uuids)` to find already-present `uuid`s, partition the batch, insert only the new
    rows via `sqlalchemy.dialects.sqlite.insert(Records).values(new_rows).on_conflict_do_nothing(
    index_elements=["uuid"])`, and set `upserted=len(new_rows)`, `duplicate=len(batch)-len(new_rows)`.
    (The `on_conflict_do_nothing` is belt-and-suspenders against a concurrent insert; the pre-select
    drives the counts.)
  - **flush** but do **not** commit (the route owns the transaction).
- `tests/__init__.py`, `tests/services/__init__.py` (new, if absent) — package markers.
- `tests/services/conftest.py` (new) — a fixture yielding a `Session` bound to a **migrated temp file
  `app.db`** (run E2·P2's Alembic migration **or** `Base.metadata.create_all(engine)` over a
  `make_engine(tmp_path/'app.db')`, with `set_sqlite_pragmas` so WAL+FK are on). Reused by TASK-002.
- `tests/services/test_record_upsert.py` (new) — the record-upsert tests below.

## Acceptance

- [ ] `from app.services.record_upsert import upsert_records, RecordUpsertResult` succeeds.
- [ ] First upsert of N whitelisted records over a fresh DB returns `upserted=N`, `duplicate=0`, and
      `SELECT count(*) FROM records == N`.
- [ ] **Replay** the same batch → `upserted=0`, `duplicate=N`, and `count(*)` is **unchanged**
      (idempotent; DB.md §1 `ON CONFLICT(uuid) DO NOTHING`).
- [ ] **Overlapping batches** — a second batch sharing some `uuid`s inserts only the new `uuid`s; the
      shared ones are counted as `duplicate` and not re-inserted.
- [ ] A batch containing a **non-whitelisted** `records.type` stores only the whitelisted rows; the
      dropped type's `uuid` is absent from `records` (epic R3).
- [ ] **Quantity** sample (`value=57.0`, `unit="count/min"`, `category=None`) → row with `value=57.0`,
      `unit="count/min"`, `value_text IS NULL`; **category** sample (`category="asleepDeep"`,
      `value=None`) → row with `value_text="asleepDeep"`, `value IS NULL` (DB.md §1).
- [ ] Every written row has `origin='sync'` (`SELECT DISTINCT origin FROM records == {'sync'}`).
- [ ] `uv run ruff check app/services/record_upsert.py tests/services` is clean.

## Steps

### RED
- [ ] Add `tests/services/conftest.py` (migrated temp-file `app.db` session fixture) and
      `tests/services/test_record_upsert.py` asserting: first-upsert counts + row count; replay → all
      duplicate + unchanged count; overlapping batches; whitelist drop; quantity vs category
      `value`/`value_text` mapping; `origin='sync'`. Run — fails (no `app.services.record_upsert`).

### GREEN
- [ ] Add `app/services/__init__.py` and `app/services/record_upsert.py` with `RecordUpsertResult` +
      `upsert_records` per **Files** (whitelist filter → map → pre-select existing `uuid`s →
      `insert(...).on_conflict_do_nothing(index_elements=["uuid"])` → counts). Run — tests pass.

### REFACTOR
- [ ] Extract the wire→`Records`-row mapping into a small private `_to_row(record)` helper (reused by
      the replay/overlap tests' expectations); confirm `ruff check` is clean.

## Notes

`HealthRecord.type` is a `RecordType` enum — write its **`.value`** (the snake_case wire string) into
`records.type` (a free TEXT column), matching how the E4 seed and aggregate queries key on the type
string (DB.md §1). "Zone-minute capture" for the deterministic engine is sourced from **HR `records`**
(E6·P1 derives `daily_metrics.z1_min…z5_min` from them — DB.md §2), so this service's job is simply to
land the HR records losslessly; the **workout's** `zoneMinutes` field is persisted separately in TASK-002
(no zone column exists on the ingest tables, and the `daily_metrics` recompute is E6 / out of scope).
Do **not** commit inside the service — the `/sync` route (TASK-003) wraps all upserts in one transaction.
