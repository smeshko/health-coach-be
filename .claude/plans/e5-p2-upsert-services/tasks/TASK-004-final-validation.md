# TASK-004: Final Validation

Depends on: TASK-001, TASK-002, TASK-003
Suggested commit: `chore: final validation for e5-p2-upsert-services`

## Goal

Confirm every PLAN.md acceptance criterion is met by a concrete, non-circular check (a named command or
test), and the `/sync` upsert path is production-ready.

## Steps

- [ ] All task checkboxes in `PLAN.md` (TASK-001..003) are ticked.

### Lint + test gates
- [ ] `uv run ruff check .` passes with no errors.
- [ ] `uv run pytest tests/services tests/api/routes/test_sync.py` passes.

### Acceptance criteria — one concrete check each (maps 1:1 to PLAN.md "Acceptance Criteria")
- [ ] **AC1 — first sync upserts with correct split counts.** `tests/services/test_record_upsert.py`
      asserts a fresh `upsert_records` of N whitelisted records → `upserted=N, duplicate=0` and
      `count(*) records == N`; `test_workout_upsert.py` asserts `upsert_workouts` → `upserted=N,
      duplicate=0`; `test_activity_upsert.py` asserts `upsert_activity` returns the #distinct dates.
- [ ] **AC2 — replay is idempotent (re-post inserts nothing new).** The replay tests in
      `tests/services/test_record_upsert.py` and `test_workout_upsert.py` assert the second upsert →
      `upserted=0, duplicate=N` with `count(*)` on `records`/`workouts`/`workout_statistics` unchanged;
      `tests/api/routes/test_sync.py` asserts a second `POST /sync` of the same body returns
      all-duplicate/zero-new counts and unchanged row counts.
- [ ] **AC3 — overlapping date ranges never double-insert.** The overlapping-batches test in
      `tests/services/test_record_upsert.py` posts two batches with overlapping `uuid` sets and asserts
      each `uuid` is inserted exactly once and the overlap is counted as `duplicate`.
- [ ] **AC4 — `origin='sync'` on every live row.** Tests in `tests/services/test_record_upsert.py` and
      `test_workout_upsert.py` assert `SELECT DISTINCT origin FROM records == {'sync'}` (and `workouts`).
- [ ] **AC5 — whitelist applied, non-whitelisted ignored.** The whitelist test in
      `tests/services/test_record_upsert.py` posts a non-whitelisted (or recognised-but-unstored) `type`
      and asserts it is absent from `records`; `tests/api/routes/test_sync.py` asserts the same
      end-to-end through `POST /sync`.
- [ ] **AC6 — quantity vs category mapping.** The mapping test in
      `tests/services/test_record_upsert.py` asserts a quantity sample → `value`/`unit` set,
      `value_text IS NULL`, and a category sample (`category="asleepDeep"`) → `value_text="asleepDeep"`,
      `value IS NULL`.
- [ ] **AC7 — `workout_statistics` from `statistics[]` + `zoneMinutes`, net-new only.** Tests in
      `tests/services/test_workout_upsert.py` assert `avg_hr`→`average=151` / `max_hr`→`maximum=189`
      (DB.md §1 columns) **and** five `zone_minutes_z*` rows (`sum=<min>`, `unit="min"`) are written and
      FK'd to the workout, and a replay adds **zero** new `workout_statistics` rows.
- [ ] **AC8 — `activity_summary` upsert-by-date refreshes in place.** The test in
      `tests/services/test_activity_upsert.py` posts the same `date` twice with different ring values and
      asserts **one** row carrying the **second** values; a `steps`-set summary does not error and writes
      no steps column.
- [ ] **AC9 — `POST /sync` returns a complete `SyncResponse` with `serverTime`.** The success-path test
      in `tests/api/routes/test_sync.py` asserts `200` + camelCase
      `recordsUpserted`/`recordsDuplicate`/`workoutsUpserted`/`activityDaysUpserted`, `checkinSaved=false`,
      `strengthTestSaved=false`, and a `serverTime` that `datetime.fromisoformat` parses to a
      timezone-aware datetime; an injected Jan clock → `+02:00`, Jul → `+03:00` (DST proof).
- [ ] **AC10 — unauthenticated → `unauthorized` envelope.** The auth tests in
      `tests/api/routes/test_sync.py` assert no-token and wrong-token `POST /sync` → `401` +
      `{"error":{"code":"unauthorized",…}}`, and the correct token → `200`.
- [ ] **AC11 — no readiness / no `daily_metrics` recompute.** `tests/api/routes/test_sync.py` asserts
      `daily_metrics` is untouched after a sync, and the boundary grep
      `grep -RnE "recompute|readiness|daily_metrics" app/api/routes/sync.py app/services/` returns
      nothing (no recompute/readiness import in the `/sync` path).
- [ ] **AC12 — lint + targeted tests pass** (the two gate commands above).

### Boundaries
- [ ] No new wire model / `RecordType` / whitelist entry was added (E5·P1 owns them):
      `grep -RnE "class .*CamelModel|RecordType|WHITELISTED_TYPES *=" app/services app/api/routes/sync.py`
      finds no model/enum/whitelist **definition** (only imports/uses).
- [ ] No ORM model or Alembic migration was added (E2·P2 owns the schema): `git status` shows no new
      file under `app/database/models/` or `alembic/versions/`.
- [ ] No new auth/error code was defined (E1·P2 owns them): `/sync` only `Depends(require_auth)` and
      relies on the registered `unauthorized` handler.
- [ ] `checkinSaved`/`strengthTestSaved` are returned `false` (the E5·P3 stub) and `SyncRequest.checkin`/
      `strengthTest` are **not** persisted this phase — no write to `checkins`/`strength_tests`
      (`grep -RnE "checkins|strength_tests" app/services app/api/routes/sync.py` finds nothing).
