# Plan: E5·P2 — Idempotent upsert services + SyncResponse

Status: draft
Risk: medium
Created: 2026-06-03

> Epic **E5 — Sync / Ingest (`POST /sync`)**, phase **P2** (the second of three). Source of truth:
> [`epics/E05-sync-ingest.md`](../../../epics/E05-sync-ingest.md) (§1 summary, §2 **R3** whitelist /
> **R4** upsert rules / **R5** observable idempotency / **R6** deltas, §3 **E5·P2**, §4 acceptance, §6
> validation, §7 out-of-scope) · grounded in
> [`docs/architecture/MODELS.md`](../../../docs/architecture/MODELS.md) **"POST /sync"** (`HealthRecord`,
> `Workout`/`WorkoutStat`, `ActivitySummary`) and **"SyncResponse"** (the exact count fields +
> `serverTime`), [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) **§1** (the four ingest
> tables column-by-column + the `INSERT … ON CONFLICT(uuid) DO NOTHING` / upsert-by-`date` **write
> rule**; `origin='sync'`) and **§6** (write paths), and
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) **§3** (data model —
> ingest tables) + the **endpoints table** (`POST /sync` authed).
>
> **Depends on E5·P1** (`app/api/schemas/sync.py` wire models + `app/core/healthkit.py`
> `filter_whitelisted_records`), **E2·P2** (`app/database/models/` `Records`/`Workouts`/
> `WorkoutStatistics`/`ActivitySummary` + their migration), **E2·P1** (`app/database/engine.py`
> `SessionLocal`/`get_session`, WAL+FK pragmas, `app/core/time.py` Europe/Sofia timestamp helper) and
> **E1·P2** (`app/api/auth.py` bearer dep, `app/api/errors.py` `unauthorized` envelope, `create_app()`).
> This phase ships the **records/workouts/activity upsert services + the `/sync` endpoint shell**; the
> **check-in / strength-test upsert AND the `daily_metrics` recompute hook are E5·P3** (so
> `checkinSaved`/`strengthTestSaved` are stubbed `false` here).

## Goal

Ship idempotent upsert **services** that write the E5·P1 wire models into the E2·P2 ingest tables
(`records`/`workouts`/`workout_statistics` by `uuid`, `activity_summary` by `date`) and an authenticated
`POST /sync` endpoint that runs them and returns a `SyncResponse` whose split upserted-vs-duplicate counts
make idempotency observable — re-posting the same payload inserts nothing new.

## Scope

- **`app/services/record_upsert.py`** (TASK-001) — `upsert_records(session, records) -> RecordUpsertResult`:
  filters to whitelisted `records.type` via `app.core.healthkit.filter_whitelisted_records`, maps each
  surviving `HealthRecord` → a `Records` row (`value`→`value`, `category`→`value_text`, `unit`→`unit`,
  `start`/`end`→`start_date`/`end_date`, `source`→`source_name`, `type` (RecordType **value** string)→
  `type`, `origin='sync'`), then `INSERT … ON CONFLICT(uuid) DO NOTHING` (SQLite upsert via
  `sqlalchemy.dialects.sqlite.insert`), returning **`upserted`** (rows inserted) and **`duplicate`**
  (rows skipped by `uuid` conflict) counted deterministically (DB.md §1 write rule; epic R3/R4/R5).
- **`app/services/workout_upsert.py`** (TASK-002) — `upsert_workouts(session, workouts) ->
  WorkoutUpsertResult`: maps each `Workout` → a `Workouts` row (`type`→`activity_type`, `durationS`→
  `duration` (`duration_unit='s'`), `distanceM`→`total_distance` (`_unit='m'`), `activeEnergyKcal`→
  `total_energy_burned` (`_unit='kcal'`), `effortScore`→`effort_score`, `origin='sync'`),
  `ON CONFLICT(uuid) DO NOTHING`; for **newly-inserted** workouts only, writes each `WorkoutStat` in
  `statistics[]` → a `WorkoutStatistics` row (`type`→`type`, `unit`→`unit`, `workout_id`→the parent id,
  and the single wire `value` → `maximum` for `max_*` stats / `average` for `avg_*` stats — DB.md §1 has
  both columns) **and** writes the workout's `zoneMinutes` → `WorkoutStatistics` rows
  (`type="zone_minutes_z1".."z5"`, `sum=<minutes>`, `unit="min"`) — the only durable per-workout home
  for zone-minutes this phase (see Decisions; the canonical `daily_metrics.z1_min…z5_min` is E6). Returns
  `upserted` / `duplicate`.
- **`app/services/activity_upsert.py`** (TASK-002) — `upsert_activity(session, summaries) -> int`
  (`activityDaysUpserted`): maps each `ActivitySummary` → an `activity_summary` row (`activeEnergyKcal`→
  `active_energy_burned`, `exerciseMinutes`→`apple_exercise_time`, `standHours`→`apple_stand_hours`;
  `steps` has **no column** → ignored), upsert by the `date` PK via `ON CONFLICT(date) DO UPDATE`
  (DB.md §1 "upsert by date"). Returns the count of dates processed.
- **`app/api/routes/sync.py`** (TASK-003) — `APIRouter` with `POST /sync`, **guarded by the E1·P2 bearer
  dependency** (`Depends(require_auth)` — the E1·P2 name), body `SyncRequest`. Opens a `SessionLocal`
  (one transaction),
  calls the three services, commits, and returns `SyncResponse(recordsUpserted=…, recordsDuplicate=…,
  workoutsUpserted=…, activityDaysUpserted=…, checkinSaved=False, strengthTestSaved=False,
  serverTime=<now in Europe/Sofia, ISO-8601 with offset>)`. **No** readiness computation, **no**
  `daily_metrics` recompute (MODELS "SyncResponse"; epic §3). Registered in `create_app()`
  (`app/api/app.py`).
- **Tests** (`tests/services/` + `tests/api/routes/`), each over a **migrated temp file `app.db`** (via
  E2·P2's Alembic migration / `Base.metadata.create_all`) so the real `ON CONFLICT` paths run:
  - `tests/services/test_record_upsert.py` — first upsert returns correct `upserted`/`duplicate`;
    **replay → all duplicate** (idempotent); `origin='sync'`; whitelist drops a non-whitelisted type;
    quantity (`value`/`unit`) vs category (`value_text`) mapping; overlapping date ranges never double-insert.
  - `tests/services/test_workout_upsert.py` — workout upsert + `workout_statistics` from `statistics[]`;
    `zoneMinutes` → `zone_minutes_z*` stat rows; replay inserts no new workouts **or** stat rows; FK to
    `workouts(id)` holds; `origin='sync'`.
  - `tests/services/test_activity_upsert.py` — upsert-by-`date`; re-posting the same date updates in place
    (one row per date); `steps` ignored without error.
  - `tests/api/routes/test_sync.py` — `POST /sync` with a valid token returns `200` + `SyncResponse`
    JSON (camelCase counts, `checkinSaved=false`, `strengthTestSaved=false`, `serverTime` present &
    aware); **replay** of the same payload → all counts duplicate/zero-new (idempotent end-to-end);
    `401` `unauthorized` envelope without a token; non-whitelisted record not stored.

## Out of Scope

- **Check-in & strength-test upsert** (`checkins` by date, `strength_tests` by derived ISO week) — **E5·P3**
  (epic §3 E5·P3). `SyncRequest.checkin`/`strengthTest` are accepted by the model but **not persisted**
  here; `checkinSaved`/`strengthTestSaved` are returned **`false`** (stubbed) and completed in P3.
- **The `daily_metrics` recompute fan-out** (fire `recompute(date)` for every affected date) — **E5·P3 →
  E6** (epic §3; DB.md §6). `/sync` does **no** recompute and **no** readiness computation this phase
  (MODELS "SyncResponse").
- **Computing `daily_metrics` values** incl. the canonical zone-minutes `z1_min…z5_min` **derived from HR
  records** — **E6·P1** owns that (DB.md §2; E6·P1). This phase only persists the raw synced rows
  (records, workouts + the workout's `zoneMinutes` as `workout_statistics`) that E6 will read.
- **The wire models, `RecordType`, and the type whitelist** — **E5·P1** (`app/api/schemas/sync.py`,
  `app/core/healthkit.py`). This phase **consumes** them; it defines no new wire model and adds no
  whitelist entry.
- **The ingest tables / migration** — **E2·P2** (`app/database/models/`). This phase **writes into** them
  and defines no ORM model or migration.
- **The bearer auth dependency / error envelope** — **E1·P2** (`app/api/auth.py`, `app/api/errors.py`).
  This phase **applies** the dependency to `/sync`; it does not redefine auth or the envelope.
- **`/brief/daily` & `/brief/weekly`** (E10/E11) and the **90-day seed** (E4).
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/`vecs` (ARCHITECTURE §1).
  Synchronous SQLAlchemy over SQLite (WAL).

## Research Summary

See [`RESEARCH.md`](./RESEARCH.md) for the column-level wire→table mapping. In short: `/sync` is the
first of the three endpoints (ARCHITECTURE §3 endpoints table) — an **idempotent** upsert keyed by the
HealthKit **`uuid`** so re-syncing overlapping ranges never double-inserts (MODELS "POST /sync"
provenance; DB.md §1 write rule). The four ingest tables and their constraints already exist (E2·P2);
the wire models and the type whitelist already exist (E5·P1); the bearer dep + `unauthorized` envelope
already exist (E1·P2). This phase is therefore **services + endpoint wiring**, not new schema or
contracts. `records`/`workouts` write `INSERT … ON CONFLICT(uuid) DO NOTHING` and **split** counts into
`upserted` vs `duplicate` so idempotency is observable in `SyncResponse` (MODELS "SyncResponse"; epic R5).
`activity_summary` is upsert-by-`date` (its PK). The one genuine ambiguity — where `workout.zoneMinutes`
lands when no ingest column exists for it and the canonical `daily_metrics.z1_min…z5_min` is **derived
from HR records by E6** (DB.md §2; E6·P1, out of scope) — is resolved by persisting it as
`workout_statistics` rows (the only per-workout aggregate home) so the synced datum is captured, not
dropped. `serverTime` is the server clock as ISO-8601 carrying the **actual** Europe/Sofia DST offset,
reusing the E1·P2/E2·P1 time helper (MODELS "Conventions → Timestamps").

## Decisions

- **Upsert logic lives in `app/services/` (one module per ingest group), the route in
  `app/api/routes/sync.py`** (NOTES; mirrors the E1·P2 routes layout). Services are pure
  `(session, models) -> result` functions with **no** HTTP/FastAPI imports, so they are unit-testable
  against a session without a client and reusable by the E4 seed / E5·P3. The route is the thin shell
  that opens the transaction, calls the services, and shapes `SyncResponse`.
- **Idempotency via SQLite `INSERT … ON CONFLICT(uuid) DO NOTHING`, counts derived deterministically**
  (DB.md §1 write rule; MODELS "SyncResponse"; epic R5). `records`/`workouts` use
  `sqlalchemy.dialects.sqlite.insert(...).on_conflict_do_nothing(index_elements=["uuid"])`. Because a
  bulk `executemany` can't report per-row conflict portably, the service counts `upserted` vs
  `duplicate` by **pre-selecting the existing `uuid`s for the batch in one query** and partitioning the
  incoming rows (then inserting only the new ones) — so the split is exact and a replay flips every row
  to `duplicate`. (Single-`uuid`-per-row inserts checking `rowcount` is the fallback if a batch
  pre-select is unwieldy; either way the count is deterministic — see TASK-001.)
- **`activity_summary` is `ON CONFLICT(date) DO UPDATE` (true upsert), not `DO NOTHING`** (DB.md §1
  "upsert by date"; epic R4). A re-synced day must **refresh** the rings (a delta can correct a day),
  so the activity writer updates in place. `activityDaysUpserted` therefore counts **dates processed**
  (MODELS lists a single `activityDaysUpserted` with no duplicate split, unlike records/workouts).
- **`HealthRecord.category` maps to `records.value_text`, `value`/`unit` to `value`/`unit`** (DB.md §1
  `value_text` = "category enums `value` can't hold"; MODELS HealthRecord). Quantity samples carry
  `value`+`unit` (→ `value`/`unit`, `value_text` NULL); category samples carry `category` (→
  `value_text`, `value` NULL). This is the faithful DB.md §1 column semantics, not an invented field.
- **`workout.zoneMinutes` is persisted as `workout_statistics` rows; the canonical
  `daily_metrics.z1_min…z5_min` derivation (from HR records) is deferred to E6** (DB.md §2 "from
  `records`"; E6·P1; epic §3/§7). No ingest table has a zone column, and recompute is out of scope, so
  to keep the synced datum lossless and **observable** this phase the workout writer emits one
  `workout_statistics` row per present zone (`type="zone_minutes_z1".."z5"`, `sum=<minutes>`,
  `unit="min"`, same `workout_id`). This is the smallest faithful home for the field without inventing a
  schema column; E6 still derives the authoritative per-day zone-minutes from HR records independently.
- **`WorkoutStat.value` routes to the `average` or `maximum` column by the stat kind, not always
  `average`** (DB.md §1; MODELS WorkoutStat; round-1 #1). `workout_statistics` carries distinct
  `average`/`maximum` (and `sum`/`minimum`) columns, while the wire `WorkoutStat` carries a single
  `value`; `WorkoutStat.type` ∈ {`avg_hr`,`max_hr`,`avg_speed`,`max_speed`,`avg_power`,`avg_cadence`}.
  The writer routes `value`→`maximum` when `type` starts with `max_`, else `value`→`average`, so a
  `max_hr` value lands in `maximum` (not silently in `average`) and the seed-mirroring aggregate queries
  read the right column. (`type` already records the kind; routing the value column keeps the schema
  semantics intact.)
- **Wire→column unit literals (`'s'`/`'m'`/`'kcal'`) are set by the writer** (MODELS Workout —
  `durationS` seconds, `distanceM` meters, `activeEnergyKcal` kcal). The wire fields are unit-implicit
  (the name encodes the unit), but the ingest columns carry an explicit `*_unit`; the writer fills the
  canonical unit so the seed-mirroring `baseline.db` aggregate queries (DB.md §1) read a consistent unit.
- **`workout_statistics` is written only for newly-inserted workouts** (DB.md §1; idempotency). A
  duplicate workout (`uuid` conflict → `DO NOTHING`) already has its statistics rows from the first
  sync; re-writing them would double-insert child rows (no `uuid` on `workout_statistics`). So the
  writer inserts statistics **only** for the `uuid`s that were net-new this call — replay adds **zero**
  stat rows (asserted in TASK-002).
- **`ActivitySummary.steps` is ignored by the activity writer** (DB.md §1 — `activity_summary` has no
  steps column; steps are a `records` sample → `daily_metrics.steps`). Dropping it at this layer is
  correct, not lossy: the step count arrives as a `step_count` `HealthRecord` and is stored in
  `records`. Documented so a reviewer doesn't read it as a missed mapping.
- **`origin='sync'` on every row written here** (DB.md §1 `'seed'`|`'sync'`). The E4 seed writes
  `'seed'`; everything `/sync` writes is live `'sync'`. Asserted by a test reading the column back.
- **`checkinSaved`/`strengthTestSaved` returned `false` (stubbed) this phase** (epic §3 — check-in /
  strength-test upsert is E5·P3). The response **shape** is complete (E5·P1 model), but the two flags
  reflect "not persisted yet"; P3 flips them when it adds the `checkins`/`strength_tests` writers.
  Stated in Out of Scope so the `false` is a deliberate, documented stub, not a bug.
- **`serverTime` from a shared Europe/Sofia time helper relocated to `app/core/time.py`, never a
  hard-coded offset** (MODELS "Conventions → Timestamps"; runbook pitfall 6; round-1 #3). E1·P2 placed
  `now_sofia` in `app/api/routes/health.py`; this phase **moves** it to `app/core/time.py` (alongside the
  E2·P1 `period_date`/`iso_week` helpers) so `/sync` and `/health` both import the one DST-aware,
  instant-preserving helper without a route→route import (avoiding an import cycle as routers grow). The
  offset is DST-correct (`+02:00`/`+03:00`); a test asserts the parsed `serverTime` is timezone-aware
  with a non-`None` offset, and `/health`'s existing DST tests stay green after the move.
- **One transaction per `/sync` call** — the route opens a single `SessionLocal`, runs all three
  services, and commits once (rolls back on error). Idempotency means a partial-then-retried sync is
  safe, but a single transaction keeps a request atomic and the counts consistent with what was
  committed.

## Risks

- **Counts wrong — `recordsUpserted`/`recordsDuplicate` don't reflect actual inserts** → idempotency is
  not observable (epic R5 violated). Mitigation: the service partitions incoming rows by a one-query
  pre-select of existing `uuid`s (or per-row `rowcount`) and a **replay** test asserts the second post
  returns `upserted=0`, `duplicate=N` and the table row-count is unchanged.
- **Replay double-inserts `workout_statistics`** (child rows have no `uuid`) → duplicated stats after a
  retry. Mitigation: statistics (incl. `zone_minutes_*`) are written **only** for net-new workout
  `uuid`s; a replay test asserts `SELECT count(*) FROM workout_statistics` is unchanged after the second
  post.
- **Non-whitelisted records reach `records`** → the engine stores types it never reads (epic R3).
  Mitigation: `upsert_records` calls `filter_whitelisted_records` **before** mapping; a test posts a
  non-whitelisted (or recognised-but-unstored) type and asserts it is absent from `records`.
- **`activity_summary` `DO NOTHING` instead of `DO UPDATE`** → a corrected day never refreshes.
  Mitigation: the writer uses `ON CONFLICT(date) DO UPDATE`; a test posts the same `date` twice with
  different ring values and asserts the row reflects the **second** values and there is **one** row.
- **`category` lost or mis-mapped** (written to `value` instead of `value_text`, or NULL) → sleep-stage
  samples unreadable downstream. Mitigation: explicit `category`→`value_text` mapping; a test inserts a
  category sample (`category="asleepDeep"`, `value=None`) and asserts `value_text="asleepDeep"`,
  `value IS NULL`.
- **`/sync` unauthenticated or wrong envelope on 401** → security/contract regression (epic §4).
  Mitigation: the route declares the E1·P2 bearer `Depends`; tests assert `401` + the **`unauthorized`**
  envelope (`{"error":{"code":"unauthorized",…}}`) with no token and a wrong token, and `200` with the
  correct `Bearer <api_token>`.
- **`serverTime` hard-codes `+03:00` / loses the offset** → drift checks break across DST (MODELS).
  Mitigation: use the shared Europe/Sofia helper; a test parses `serverTime` and asserts `tzinfo is not
  None` (and an injected-clock winter instant yields `+02:00`, summer `+03:00`).
- **`zoneMinutes` silently dropped** (no column) → a synced signal vanishes. Mitigation: persist it as
  `workout_statistics` `zone_minutes_z*` rows; a test asserts the rows exist with `unit="min"` for a
  workout carrying `zoneMinutes`, and that E6's canonical derivation is documented as the out-of-scope
  authoritative path (no double source of truth).
- **The service accidentally fires a recompute / readiness** → scope creep into E5·P3/E6 and a slow
  `/sync`. Mitigation: the route imports **no** recompute/readiness module; a boundary check greps
  `app/api/routes/sync.py` + the services for `recompute`/`readiness`/`daily_metrics` and finds nothing.
- **FK violation writing `workout_statistics`** (parent id not flushed) → `IntegrityError`. Mitigation:
  the writer `flush()`es the inserted `Workouts` rows to obtain their `id` before inserting children;
  E2·P1's `foreign_keys=ON` is active, and a test inserts a workout + stats in one call and asserts the
  FK holds.

## Acceptance Criteria

- [ ] **First sync upserts with correct split counts.** `upsert_records` over a fresh DB returns
      `upserted = <#whitelisted records>`, `duplicate = 0`; `upsert_workouts` returns `upserted = <#workouts>`,
      `duplicate = 0`; `upsert_activity` returns `<#distinct dates>`
      (`tests/services/test_record_upsert.py`, `test_workout_upsert.py`, `test_activity_upsert.py`). (epic R5, §4)
- [ ] **Replay is idempotent — re-posting the same payload inserts nothing new.** A second
      `upsert_records`/`upsert_workouts` of the identical batch returns `upserted = 0`, `duplicate = N`,
      and `SELECT count(*)` on `records`/`workouts`/`workout_statistics` is **unchanged**; end-to-end, a
      second `POST /sync` of the same body returns all-duplicate/zero-new counts
      (`tests/services/*`, `tests/api/routes/test_sync.py`). (epic R5, §4; DB.md §1)
- [ ] **Overlapping date ranges never double-insert.** Posting two batches whose `uuid` sets overlap
      inserts each `uuid` exactly once; the overlap is counted as `duplicate`
      (`tests/services/test_record_upsert.py`). (epic §4 "overlapping ranges"; MODELS provenance)
- [ ] **`origin='sync'` on every live row.** After an upsert, `SELECT DISTINCT origin FROM records` (and
      `workouts`) is `{'sync'}` (`tests/services/*`). (DB.md §1)
- [ ] **Whitelist applied — non-whitelisted records ignored.** A batch containing a non-whitelisted (or
      recognised-but-unstored) `records.type` stores **only** the whitelisted rows; the dropped type is
      absent from `records` (`tests/services/test_record_upsert.py`). (epic R3; DB.md §1)
- [ ] **Quantity vs category mapping.** A quantity sample → `value`/`unit` set, `value_text` NULL; a
      category sample (`category="asleepDeep"`) → `value_text` set, `value` NULL
      (`tests/services/test_record_upsert.py`). (DB.md §1; MODELS HealthRecord)
- [ ] **`workout_statistics` written from `statistics[]` + `zoneMinutes`, only for net-new workouts.**
      A workout with `statistics=[avg_hr,max_hr]` and `zoneMinutes={z1..z5}` yields the `avg_hr` row in
      `average` and the `max_hr` row in `maximum` (DB.md §1 columns) **plus** `zone_minutes_z1..z5` rows
      (`sum=<min>`, `unit="min"`), all FK'd to the workout; a replay adds **zero** new
      `workout_statistics` rows
      (`tests/services/test_workout_upsert.py`). (DB.md §1; MODELS Workout/WorkoutStat; Decisions)
- [ ] **`activity_summary` upsert-by-date refreshes in place.** Posting the same `date` twice with
      different ring values leaves **one** row carrying the **second** values; `steps` is ignored without
      error (`tests/services/test_activity_upsert.py`). (DB.md §1 "upsert by date")
- [ ] **`POST /sync` returns a complete `SyncResponse` with `serverTime`.** With a valid `Bearer`
      token, `POST /sync` returns `200` and JSON with camelCase `recordsUpserted`/`recordsDuplicate`/
      `workoutsUpserted`/`activityDaysUpserted`, `checkinSaved=false`, `strengthTestSaved=false`, and a
      `serverTime` that parses as a **timezone-aware** ISO-8601 datetime (non-`None` offset)
      (`tests/api/routes/test_sync.py`). (MODELS "SyncResponse"; ARCHITECTURE endpoints table)
- [ ] **Unauthenticated → `unauthorized` envelope.** `POST /sync` with no token **and** with a wrong
      token returns `401` with the `{"error":{"code":"unauthorized",…}}` envelope; the correct token →
      `200` (`tests/api/routes/test_sync.py`). (epic §4; E1·P2)
- [ ] **No readiness / no `daily_metrics` recompute here.** `/sync` performs no readiness computation
      and fires no recompute: the route + services import no `readiness`/`recompute`/`daily_metrics`
      module (grep-asserted), and `daily_metrics` is untouched after a sync
      (`tests/api/routes/test_sync.py`). (MODELS "SyncResponse"; epic §3, §7)
- [ ] `uv run ruff check .` and `uv run pytest tests/services tests/api/routes/test_sync.py` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [ ] TASK-001: records upsert with ON CONFLICT uuid and zone-minute capture
- [ ] TASK-002: workouts and workout_statistics upsert; activity_summary upsert by date
- [ ] TASK-003: POST /sync endpoint with SyncResponse counts and serverTime
- [ ] TASK-004: Final Validation
