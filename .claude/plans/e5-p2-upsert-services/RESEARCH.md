# Research: E5·P2 — Idempotent upsert services + SyncResponse

Curated findings only — no raw conversation transcripts. Grounded in
[`epics/E05-sync-ingest.md`](../../../epics/E05-sync-ingest.md),
[`docs/architecture/MODELS.md`](../../../docs/architecture/MODELS.md) ("POST /sync" / "SyncResponse"),
[`docs/architecture/DB.md`](../../../docs/architecture/DB.md) §1/§6,
[`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §3 + the endpoints table,
and the already-authored dependency plans (E5·P1 models, E2·P2 tables, E2·P1 engine, E1·P2 auth/errors).

## Key Files & Directories (the contracts this phase wires together)

- `app/api/schemas/sync.py` (E5·P1) — the camelCase wire models this phase consumes/produces:
  `HealthRecord`, `Workout`, `WorkoutStat`, `ActivitySummary`, `SyncRequest`, `SyncResponse`,
  `RecordType`. `SyncResponse` fields: `recordsUpserted: int`, `recordsDuplicate: int`,
  `workoutsUpserted: int`, `activityDaysUpserted: int`, `checkinSaved: bool`,
  `strengthTestSaved: bool`, `serverTime: datetime` (MODELS "SyncResponse"). All inherit `CamelModel`
  (`serialize_by_alias=True`), so the route returns `SyncResponse` and FastAPI emits camelCase.
- `app/core/healthkit.py` (E5·P1 + E4·P3) — `filter_whitelisted_records(records)` (drops
  non-whitelisted `records.type`), `is_record_type_whitelisted`, `WHITELISTED_TYPES`. Only `records`
  are type-gated; `workouts`/`activitySummary` are **not** (DB.md §1 gates `records.type` only).
- `app/database/models/` (E2·P2) — ORM classes: `Records`, `Workouts`, `WorkoutStatistics`,
  `ActivitySummary`. Re-exported from `app/database/models/__init__.py`.
- `app/database/engine.py` / `app/database/__init__.py` (E2·P1) — `SessionLocal` (sessionmaker),
  `get_session()` provider, `get_engine()` (lazy, reads `settings.app_db_path`),
  `set_sqlite_pragmas` (WAL + `foreign_keys=ON` connect listener). No module-level `engine`.
- `app/api/auth.py` (E1·P2) — the reusable bearer dependency (constant-time vs
  `get_settings().api_token`; missing/wrong → `HTTPException(401)` → `unauthorized` envelope).
- `app/api/errors.py` (E1·P2) — the `{ "error": { code, message, detail } }` envelope; `401` →
  `unauthorized` via the status→code table; handlers registered in `create_app()`.
- `app/api/app.py` (E1·P1/E1·P2) — `create_app()`; routers are registered here (health + probe today).
- `app/api/routes/` (E1·P2) — where routers live (`health.py`); this phase adds `sync.py`.
- `app/core/time.py` (E2·P1) — Europe/Sofia period-key / ISO-8601 timestamp helpers (DST-aware).

## Architecture Facts (column-level, from DB.md §1)

- **`records`** (target of `HealthRecord` upsert): `id` PK; `uuid` TEXT **UNIQUE, nullable**; `type`
  TEXT NOT NULL; `unit` TEXT; `value` REAL; `value_text` TEXT (category enums — sleep stage / stand
  state); `source_name`/`source_version`/`device` TEXT; `creation_date` TEXT; `start_date` TEXT NOT
  NULL; `end_date` TEXT; `origin` TEXT NOT NULL. Write rule (DB.md §1): `INSERT … ON CONFLICT(uuid)
  DO NOTHING`. Wire→column mapping: `HealthRecord.value`→`value`, `.category`→`value_text`,
  `.unit`→`unit`, `.start`→`start_date`, `.end`→`end_date`, `.source`→`source_name`,
  `.type` (RecordType **value** string)→`type`. Live rows get `origin='sync'`.
- **`workouts`** (target of `Workout` upsert): `id` PK; `uuid` TEXT **UNIQUE, nullable**;
  `activity_type` TEXT NOT NULL; `duration`+`duration_unit`; `total_distance`+`_unit`;
  `total_energy_burned`+`_unit`; `effort_score` REAL nullable; `physical_effort` REAL nullable;
  provenance + `creation_date`; `start_date` TEXT NOT NULL; `end_date` TEXT; `origin` TEXT NOT NULL.
  `ON CONFLICT(uuid) DO NOTHING`. Wire→column: `.type`→`activity_type`, `.durationS`→`duration`
  (`duration_unit='s'`), `.distanceM`→`total_distance` (`_unit='m'`),
  `.activeEnergyKcal`→`total_energy_burned` (`_unit='kcal'`), `.effortScore`→`effort_score`.
- **`workout_statistics`** (per-workout aggregates, child of `workouts`): `id` PK; `workout_id`
  INTEGER NOT NULL FK→`workouts(id)`; `type` TEXT NOT NULL; `start_date`/`end_date` TEXT; `sum`/
  `average`/`minimum`/`maximum` REAL; `unit` TEXT. Index `(workout_id, type)`. Written from each
  workout's `statistics[]` (each `WorkoutStat {type, value, unit}` → a row; the single `value` routes to
  `maximum` for `max_*` stats / `average` for `avg_*` stats — distinct columns exist for both).
- **`activity_summary`** (target of `ActivitySummary` upsert): `date` TEXT **PK** (upsert by date);
  `active_energy_burned`+`_goal` REAL; `apple_exercise_time`+`_goal` REAL; `apple_stand_hours`+
  `_goal` INTEGER; `apple_move_time`+`_goal` REAL. Wire→column: `.activeEnergyKcal`→
  `active_energy_burned`, `.exerciseMinutes`→`apple_exercise_time`, `.standHours`→
  `apple_stand_hours`; `.steps` has **no column** in `activity_summary` (steps live in `records`
  /`daily_metrics`), so it is ignored at this layer. Upsert by `date` PK (`ON CONFLICT(date) DO UPDATE`).

## Constraints

- **Idempotency is the headline.** `records`/`workouts` dedupe by `uuid` (`ON CONFLICT(uuid) DO
  NOTHING`); re-posting the same payload inserts **0** new rows and every count is a duplicate
  (MODELS "SyncResponse" — counts split upserted vs ignored; DB.md §1; epic R5/§4).
- **Counts must be observable & exact**: `recordsUpserted` (rows actually inserted) vs
  `recordsDuplicate` (rows skipped by `uuid` conflict). `executemany` masks per-row conflict, so the
  service computes counts by diffing pre/post existence (or per-row `rowcount`) — see Decisions.
- **`activityDaysUpserted`** counts distinct dates written/updated; `activity_summary` is upsert-by-
  date (not `DO NOTHING`), so a re-post of the same date still "upserts" it — the count reflects rows
  processed, not net-new (MODELS lists only a single `activityDaysUpserted` count, no duplicate split).
- **Whitelist applied before the records upsert** — `filter_whitelisted_records` drops non-stored
  types so they never reach `records` (DB.md §1; epic R3).
- **`origin='sync'`** on every live row (DB.md §1 `'seed'`|`'sync'`).
- **Auth required** — `/sync` depends on E1·P2's bearer dep; no/wrong token → `unauthorized`
  envelope (epic §4; ARCHITECTURE endpoints table).
- **No readiness, no `daily_metrics` recompute here** — `/sync` does **no** readiness computation
  (MODELS "SyncResponse"); the `daily_metrics` recompute hook + check-in/strength-test upsert are
  **E5·P3** (epic §3). `checkinSaved`/`strengthTestSaved` are therefore stubbed `false` this phase.
- **`serverTime`** is the server clock as ISO-8601 with the **actual** Europe/Sofia DST offset
  (`+02:00` winter / `+03:00` summer), never hard-coded (MODELS "Conventions → Timestamps"; reuse
  E1·P2/E2·P1 time helper; runbook pitfall 6).
- **Zone-minutes (`workout.zoneMinutes`)**: there is **no** zone column on `workouts`/
  `workout_statistics`, and `daily_metrics.z1_min…z5_min` (the canonical home) are **derived from HR
  records by E6·P1, out of scope here** (DB.md §2 "from `records`"; E6·P1). So this phase persists the
  synced `zoneMinutes` as `workout_statistics` rows (the only available per-workout aggregate home)
  so the datum is captured/observable rather than dropped — see Decisions/Uncertainty.

## Useful Commands

```bash
uv run ruff check .
uv run pytest tests/services/test_record_upsert.py tests/services/test_workout_upsert.py \
              tests/services/test_activity_upsert.py tests/api/routes/test_sync.py
# idempotency proof — replay inserts 0:
uv run pytest -k "idempot or replay or duplicate"
```

## Uncertainty

- **Where does `workout.zoneMinutes` land in P2?** The DB schema (E2·P2) has **no** zone column on
  the ingest tables; `daily_metrics.z1_min…z5_min` is the canonical home and is **derived from HR
  records** by E6·P1 (DB.md §2; E6·P1 "zone-minutes from HR records") — explicitly out of scope here.
  Resolution: P2 persists each workout's `zoneMinutes` as `workout_statistics` rows
  (`type="zone_minutes_z1"…"z5"`, `sum=<minutes>`, `unit="min"`) so the synced datum is captured and
  observable in `workout_statistics`, with the canonical `daily_metrics` zone-minute derivation
  deferred to E6. This keeps the data path lossless without inventing a non-existent column.
- **`recordsUpserted` vs `recordsDuplicate` accounting** — `executemany` with `ON CONFLICT DO
  NOTHING` doesn't return per-row conflict info portably. Resolved by inserting per-record (or
  pre-checking existing `uuid`s in one query) and counting inserts vs skips deterministically; a
  replay test proves the split flips to all-duplicate.
- **`ActivitySummary.steps`** — present on the wire but has **no `activity_summary` column** (steps
  are a `records` sample / `daily_metrics.steps`). Resolved: ignored by the activity upsert (not an
  error); documented in Decisions.

## References

- `epics/E05-sync-ingest.md` §1 summary, §2 R3–R6, §3 E5·P2, §4 acceptance, §6 validation, §7 OOS.
- `docs/architecture/MODELS.md` — "POST /sync", "HealthRecord", "Workout"/"WorkoutStat",
  "ActivitySummary", "SyncResponse".
- `docs/architecture/DB.md` §1 (ingest tables + write rule), §2 (`daily_metrics`), §6 (write paths).
- `docs/architecture/ARCHITECTURE.md` §3 (data model) + the endpoints table (`POST /sync`).
- Dependency plans: `.claude/plans/e5-p1-sync-models/`, `e2-p2-ingest-tables/`,
  `e2-p1-db-engine-alembic/`, `e1-p2-auth-errors-health/`.
